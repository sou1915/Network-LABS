"""Fresh sender-engine bindings for managed USM traps, not engine discovery.

Bindings live only in active runtime state. Receiver users are replaced before
starting a newly identified sender; old identities are not kept as trusted users.
"""
import re
import secrets
from .service_config import observe_config

USERS = '/lab/snmp-trap-users.conf'


def is_sender(node):
    config = (node.get('snmp_agent') or {}).get('notifications') or {}
    return bool(config.get('usm') and config.get('mode') == 'trap')


def wire_engine(token):
    # Net-SNMP engineID TEXT uses its enterprise prefix plus the ASCII text.
    # This is a provisioned format, checked against actual packets in native CI.
    if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{24}', token):
        raise ValueError('Trap engine binding requires a 96-bit runtime token.')
    return '80001f8804' + token.encode('ascii').hex()


def users_text(state, node):
    from .runtime import RuntimeFailure
    config = node['snmp_receiver']; user = config['usm']; lines = []
    for name in config['trap_senders']:
        binding = state.get('snmp_trap_engines', {}).get(name)
        try: engine = wire_engine(binding['token'])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeFailure('Current trap engine binding unavailable for ' + name) from error
        lines.append('createUser -e 0x' + engine + ' ' + user['username'] + ' SHA-256 -m 0x' + user['auth_master_key']
                     + ' AES -m 0x' + user['privacy_master_key'])
    return '\n'.join(lines) + '\n'


def write_users(manager, node):
    path = manager.directory / node['name'] / 'files/snmp-trap-users.conf'
    temporary = path.with_suffix('.tmp')
    # The enclosing bundle is private. An exclusive temporary file also refuses
    # leftover writes rather than adopting an interrupted installation.
    with temporary.open('x') as target:
        temporary.chmod(0o600); target.write(users_text(manager.state, node))
    temporary.replace(path)


def observe_users(manager, node):
    from .runtime import RuntimeFailure
    try: expected = users_text(manager.read(), node)
    except (RuntimeFailure, KeyError, TypeError, ValueError):
        return {'configuration_verified': False, 'configuration_available': False,
                'detail': 'Current managed trap bindings unavailable; no identity fallback.'}
    return observe_config(manager, node['name'], USERS, expected)


def provisioned_engines(manager, node):
    """Public provisioning records, not a claim of observed engine identity."""
    from .runtime import RuntimeFailure
    try:
        state = manager.read(); users_text(state, node)
        return {name: '0x' + wire_engine(state['snmp_trap_engines'][name]['token'])
                for name in node['snmp_receiver']['trap_senders']}
    except (RuntimeFailure, KeyError, TypeError, ValueError):
        return None


def verify_users(manager, node):
    from .runtime import RuntimeFailure
    if not observe_users(manager, node)['configuration_verified']:
        raise RuntimeFailure(node['name'] + ': current trap-user file differs or bindings are unavailable.')


def initialize(manager):
    senders = [n for n in manager.state['spec']['nodes'] if is_sender(n)]
    if not senders: return
    from .runtime import RuntimeFailure
    if 'snmp_trap_engines' in manager.state:
        raise RuntimeFailure('Trap engines are already allocated; refusing to reset active identities.')
    manager.state['snmp_trap_engines'] = {n['name']: {'token': secrets.token_hex(12), 'launched': False} for n in senders}
    manager.save()
    for node in manager.state['spec']['nodes']:
        if (node.get('snmp_receiver') or {}).get('trap_senders'): write_users(manager, node)


def stop_receiver(manager, node, index):
    from .runtime import RuntimeFailure
    from .snmp_notifications import BINARY, _wait
    result = manager.crun('exec', node['name'], '/bin/busybox', 'cat', '/run/snmptrapd.pid')
    pid = result.stdout.strip()
    if not pid.isdecimal() or int(pid) <= 1:
        raise RuntimeFailure('Refusing invalid receiver PID for ' + node['name'])
    executable = manager.crun('exec', node['name'], '/bin/busybox', 'readlink', '/proc/' + pid + '/exe').stdout.strip()
    if executable != BINARY: raise RuntimeFailure('Refusing a PID which does not identify the owned notification receiver.')
    manager.crun('exec', node['name'], '/bin/busybox', 'kill', '-TERM', pid)
    _wait(manager, node, lambda: manager.crun('exec', node['name'], '/bin/busybox', 'readlink', '/proc/' + pid + '/exe',
                                            check=False, timeout=2).stdout.strip() != BINARY,
          'Old receiver has not exited; trap identity rotation aborted.')
    _wait(manager, node, lambda: not manager.ns(index, 'ss', '-H', '-lun', 'sport = :162', timeout=2).stdout.strip(),
          'Old receiver still listens; trap identity rotation aborted.')


def sender_token(manager, node):
    from .runtime import RuntimeFailure
    from .snmp_notifications import observe, start_trapd
    nodes = manager.state['spec']['nodes']; index = next(i for i, n in enumerate(nodes) if n['name'] == node['name'])
    if manager.ns(index, 'ss', '-H', '-lun', 'sport = :161', timeout=2).stdout.strip():
        raise RuntimeFailure('Stop the old SNMP agent before allocating a fresh trap identity.')
    binding = manager.state.get('snmp_trap_engines', {}).get(node['name'])
    if not binding: raise RuntimeFailure('Managed trap engine allocation is missing; recreate the lab.')
    wire_engine(binding.get('token'))
    receiver_index, receiver = next((i, n) for i, n in enumerate(nodes)
                                    if node['name'] in (n.get('snmp_receiver') or {}).get('trap_senders', []))
    if not observe(manager, receiver)['configuration_verified']:
        raise RuntimeFailure('Receiver configuration drift blocks trap sender startup/identity rotation.')
    if binding['launched']:
        # Fail closed: errors can leave the receiver/agent unavailable, but do
        # not revive the retired identity with reset engine boots/time.
        stop_receiver(manager, receiver, receiver_index)
        binding['token'] = secrets.token_hex(12); manager.save()
        write_users(manager, receiver)
        start_trapd(manager, receiver, receiver_index)
    binding['launched'] = True; manager.save()
    return binding['token']
