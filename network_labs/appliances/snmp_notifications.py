"""Native community and USM notifications, with log-only local receivers."""
import ipaddress
import json
from pathlib import Path
import re
import secrets
import time
from .service_config import observe_config

BINARY = '/usr/lib/network-labs/snmptrapd'
CONFIG = '/lab/snmp-receiver.conf'
LOG = '/run/snmp-notifications.log'
HEARTBEAT = '.1.3.6.1.4.1.8072.2.3.0.1'
HEARTBEAT_RATE = '.1.3.6.1.4.1.8072.2.3.2.1.0'
HEARTBEAT_NAME = '.1.3.6.1.4.1.8072.2.3.2.2.0'


def community(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', value):
        raise ValueError('Notification community requires 8..64 ASCII token characters.')
    return value


def address(value):
    if not isinstance(value, str): raise ValueError('Notification address must be IPv4 text.')
    result = ipaddress.IPv4Address(value)
    if result.is_unspecified or result.is_multicast or result.is_loopback or result.is_reserved:
        raise ValueError('Notification endpoint requires unicast IPv4.')
    return str(result)


def listen_address(node):
    from .lan import addresses
    return str(ipaddress.IPv4Interface(addresses(node)[node['snmp_receiver']['interface']]).ip)


def validate_node(node):
    from .lan import addresses
    from .spec import keys
    config = node.setdefault('snmp_receiver', None)
    if config is None: return
    keys(config, ('interface', 'community', 'usm', 'sources', 'trap_senders'), 'SNMP receiver')
    port = config.get('interface'); values = addresses(node)
    if (node['runtime'] != 'oci' or not isinstance(port, str) or not values.get(port) or
            port in node['shutdown'] or node.get('startup') or (node.get('management') or {}).get('syslog_remote')):
        raise ValueError('SNMP receiver requires a numbered UP OCI IPv4 interface, no unmanaged startup and exclusive ownership of local syslogd.')
    local = ipaddress.IPv4Interface(values[port]); address(str(local.ip))
    if local.network.prefixlen < 31 and local.ip in (local.network.network_address, local.network.broadcast_address):
        raise ValueError('SNMP receiver requires a usable interface address.')
    if 'usm' in config:
        from .snmp import validate_usm
        if 'community' in config: raise ValueError('Choose community or USM receiver, without fallback.')
        validate_usm(config['usm'])
    else:
        community(config.get('community'))
    if 'trap_senders' in config:
        senders = config['trap_senders']
        if (not config.get('usm') or not isinstance(senders, list) or not 1 <= len(senders) <= 16 or
                not all(isinstance(name, str) for name in senders) or len(set(senders)) != len(senders)):
            raise ValueError('Trap receivers require USM and 1..16 distinct managed sender names.')
        config['trap_senders'] = sorted(senders)
    sources = config.get('sources')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 16:
        raise ValueError('SNMP receiver requires 1..16 explicit source IPv4 addresses.')
    config['sources'] = sorted({address(value) for value in sources})
    if str(local.ip) in config['sources']: raise ValueError('SNMP receiver sources must be other managed nodes.')


def validate_sender(node):
    from .snmp import listen_address as sender_address
    from .spec import keys
    agent = node.get('snmp_agent') or {}
    if 'notifications' not in agent: return
    config = agent['notifications']
    keys(config, ('receiver', 'community', 'usm', 'mode'), 'SNMP notifications')
    if 'usm' in config:
        from .snmp import validate_usm
        if 'community' in config or not agent.get('usm'):
            raise ValueError('USM notifications require a USM agent, without community fallback.')
        validate_usm(config['usm'])
        if (config.get('mode') == 'trap' and config['usm']['username'] == agent['usm']['username'] and
                config['usm'] != agent['usm']):
            raise ValueError('One sender-engine USM username cannot use different polling and trap keys; choose another notification username.')
    else:
        if agent.get('usm'): raise ValueError('USM agents cannot downgrade notifications to community security.')
        community(config.get('community'))
    config['receiver'] = address(config.get('receiver'))
    if config.get('mode') not in ('trap', 'inform'): raise ValueError('Choose trap or inform notifications.')
    if config['receiver'] == sender_address(node): raise ValueError('Notification receiver must be another node.')


def validate_lab(spec):
    from .lan import addresses
    from .snmp import listen_address as sender_address
    def peers(value):
        return [node for node in spec['nodes'] if any(ip and str(ipaddress.IPv4Interface(ip).ip) == value for ip in addresses(node).values())]
    for node in spec['nodes']:
        receiver = node.get('snmp_receiver')
        if receiver:
            for value in receiver['sources']:
                found = peers(value)
                if len(found) != 1 or found[0]['name'] == node['name']:
                    raise ValueError('Notification source must be one other uniquely numbered managed IPv4 node.')
            if receiver.get('trap_senders'):
                names = {n['name']: n for n in spec['nodes']}
                expected_sources = set()
                for name in receiver['trap_senders']:
                    peer = names.get(name); agent = (peer or {}).get('snmp_agent') or {}
                    notification = agent.get('notifications') or {}
                    if (not peer or name == node['name'] or notification.get('mode') != 'trap' or
                            notification.get('usm') != receiver['usm'] or notification.get('receiver') != listen_address(node)):
                        raise ValueError('Trap receiver names must identify matching USM trap senders targeting it.')
                    expected_sources.add(sender_address(peer))
                if expected_sources != set(receiver['sources']):
                    raise ValueError('Trap receiver source policy must exactly match its named sender addresses.')
        sender = (node.get('snmp_agent') or {}).get('notifications')
        if sender:
            found = peers(sender['receiver'])
            destination = found[0].get('snmp_receiver') if len(found) == 1 else None
            if (not destination or listen_address(found[0]) != sender['receiver'] or
                    destination.get('community') != sender.get('community') or destination.get('usm') != sender.get('usm') or
                    sender_address(node) not in destination['sources']):
                raise ValueError('Notifications require one matching managed receiver credentials, bind address and source policy.')
            if sender.get('usm') and ((sender['mode'] == 'trap') != bool(destination.get('trap_senders')) or
                                     (sender['mode'] == 'trap' and node['name'] not in destination['trap_senders'])):
                raise ValueError('Choose a receiver-authoritative inform profile or an explicitly named sender-engine trap profile.')
            if sender.get('usm') and sender['mode'] == 'inform' and sender['receiver'] not in node['snmp_agent']['managers']:
                raise ValueError('USM inform receiver must also be an allowed agent manager for session responses.')


def sender_lines(node):
    from .snmp import listen_address as sender_address
    config = node['snmp_agent'].get('notifications')
    if not config: return []
    if config.get('usm'):
        user = config['usm']
        flags = '-Ci ' if config['mode'] == 'inform' else ''
        return ['[snmp] clientaddr ' + sender_address(node),
                'trapsess -v3 ' + flags + '-u ' + user['username'] + ' -l authPriv -a SHA-256 -x AES -3m 0x' + user['auth_master_key']
                + ' -3M 0x' + user['privacy_master_key'] + ' -t 1 -r 1 udp:' + config['receiver'] + ':162']
    flags = '-Ci ' if config['mode'] == 'inform' else ''
    return ['[snmp] clientaddr ' + sender_address(node),
            'trapsess -v2c ' + flags + '-c ' + config['community'] + ' -t 1 -r 1 udp:' + config['receiver'] + ':162']


def client_config(node):
    from .snmp import listen_address as sender_address
    config = node['snmp_agent']['notifications']
    if config.get('usm'):
        from .snmp import client_config as usm_client_config
        return usm_client_config(config['usm']) + 'clientaddr ' + sender_address(node) + '\n'
    return '\n'.join(['defVersion 2c', 'defCommunity ' + config['community'], 'clientaddr ' + sender_address(node), ''])


def config_text(node):
    config = node['snmp_receiver']
    user = config.get('usm')
    policy = (['createUser ' + user['username'] + ' SHA-256 -m 0x' + user['auth_master_key'] + ' AES -m 0x' + user['privacy_master_key'],
               'authUser log ' + user['username'] + ' priv'] if user else
              ['authCommunity log ' + config['community'] + ' ' + ip for ip in config['sources']])
    if config.get('trap_senders'):
        from .snmp_traps import USERS
        policy = ['includeFile ' + USERS, 'authUser log ' + user['username'] + ' priv']
    return '\n'.join([
        'snmpTrapdAddr udp:' + listen_address(node) + ':162', '[snmp] persistentDir /run/snmptrapd',
        'sourceFilterType acceptlist',
        *['sourceFilterAddress ' + ip for ip in config['sources']],
        *policy,
        'format1 %b %v\\n', 'format syslog1 %b %v\\n',
        'format2 %b %v\\n', 'format syslog2 %b %v\\n', '',
    ])


def log_command():
    return ['/bin/sh', '-c', 'umask 077; exec "$@"', 'notification-log',
            '/bin/busybox', 'syslogd', '-n', '-O', LOG, '-s', '64', '-b', '1']


def command(node=None, engine_id=None):
    v3 = bool(node and node['snmp_receiver'].get('usm'))
    if v3 and (not isinstance(engine_id, str) or not re.fullmatch(r'[0-9a-f]{24}', engine_id)):
        raise ValueError('SNMPv3 receiver startup requires a fresh runtime engine token.')
    return [BINARY, '-f', '-C', '-c', CONFIG, '-m', '', '-On', '-n', '-X', '-Ls6', '-p', '/run/snmptrapd.pid'] + (['--engineID=' + engine_id] if v3 else [])


def prepare_files(bundle, node):
    if not node.get('snmp_receiver'): return
    for name, text in {'snmp-receiver.conf': config_text(node),
                       'snmp-notification-log.json': json.dumps({'command': log_command()}, sort_keys=True, indent=2) + '\n'}.items():
        path = Path(bundle) / 'files' / name; path.write_text(text); path.chmod(0o600)
    if node['snmp_receiver'].get('trap_senders'):
        path = Path(bundle) / 'files/snmp-trap-users.conf'; path.write_text(''); path.chmod(0o600)


def _wait(manager, node, check, message):
    from .runtime import RuntimeFailure
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if check(): return
        time.sleep(.05)
    raise RuntimeFailure(node['name'] + ': ' + message)


def start_trapd(manager, node, index):
    if node['snmp_receiver'].get('trap_senders'):
        from .snmp_traps import verify_users
        verify_users(manager, node)
    manager.crun('exec', node['name'], '/bin/busybox', 'mkdir', '-p', '/run/snmptrapd')
    manager.crun('exec', '--detach', node['name'], *command(node, secrets.token_hex(12)), log=manager.directory / node['name'] / 'snmptrapd.log')
    _wait(manager, node, lambda: listen_address(node) + ':162' in manager.ns(index, 'ss', '-H', '-lun', 'sport = :162', timeout=2).stdout.split(),
          'SNMP receiver did not bind its declared UDP address.')


def start_receivers(manager):
    from .runtime import RuntimeFailure
    from .snmp_traps import initialize
    initialize(manager)
    for index, node in enumerate(manager.state['spec']['nodes']):
        if not node.get('snmp_receiver'): continue
        help_result = manager.crun('exec', node['name'], '/bin/busybox', 'syslogd', '--help', check=False, timeout=3)
        if any(flag not in help_result.stdout + help_result.stderr for flag in ('-n', '-O', '-s', '-b')):
            raise RuntimeFailure(node['name'] + ': required BusyBox syslogd rotation options are unavailable.')
        manager.crun('exec', '--detach', node['name'], *log_command(), log=manager.directory / node['name'] / 'notification-syslogd.log')
        _wait(manager, node, lambda: manager.crun('exec', node['name'], '/bin/busybox', 'test', '-S', '/dev/log', check=False, timeout=2).returncode == 0,
              'Local notification log socket is not ready.')
        start_trapd(manager, node, index)


def observe(manager, node):
    expected = {'snmp-receiver.conf': config_text(node),
                'snmp-notification-log.json': json.dumps({'command': log_command()}, sort_keys=True, indent=2) + '\n'}
    files = {name: observe_config(manager, node['name'], '/lab/' + name, value) for name, value in expected.items()}
    engines = None
    if node['snmp_receiver'].get('trap_senders'):
        from .snmp_traps import observe_users, provisioned_engines
        files['snmp-trap-users.conf'] = observe_users(manager, node)
        engines = provisioned_engines(manager, node)
    return {'configuration_verified': all(row['configuration_verified'] for row in files.values()), 'files': files,
            'address': listen_address(node), 'port': 162, 'sources': node['snmp_receiver']['sources'],
            'versions': ['3'] if node['snmp_receiver'].get('usm') else ['1', '2c'], 'log': LOG,
            'security': {'level': 'authPriv', 'username': node['snmp_receiver']['usm']['username'],
                         'authentication': 'SHA-256', 'privacy': 'AES-128', 'engine_identity': 'Current sender engines are provisioned; receiver engine is not authoritative for traps.' if node['snmp_receiver'].get('trap_senders') else 'Fresh per receiver start; new sessions rediscover.'}
                        if node['snmp_receiver'].get('usm') else {'level': 'community'},
            'trap_senders': node['snmp_receiver'].get('trap_senders', []),
            'provisioned_trap_engines': engines,
            'note': 'Managed config conformity, not ongoing liveness, receipt, authorization or log delivery. '
                    + ('USM trap users are bound to current managed sender engines; no receiver-local inform user. Sender identity rotation restarts this receiver; in-flight traps can be lost. ' if node['snmp_receiver'].get('trap_senders') else
                       'USM master keys are credential-equivalent secrets; only authPriv logging is authorized, without community fallback. Informs use the receiver engine. Restart sender sessions after receiver replacement. ' if node['snmp_receiver'].get('usm') else 'Community notifications (v1/v2c) are plaintext; ')
                    + 'Source policy is not anti-spoofing. INFORM acknowledgement and accepted logging are separate evidence. Logs rotate at 64 KiB with one backup in volatile /run; payloads can be truncated. No execution hooks, forwarding, durable queue/history or automatic link-event mapping.'}


def drift(manager, node):
    return [node['name'] + ': SNMP receiver configuration differs or is unavailable'] if node.get('snmp_receiver') and not observe(manager, node)['configuration_verified'] else []


def rootfs_assets(binary):
    from .dns_rootfs import assets
    return assets(binary, destination=BINARY, version_args=('-v',), identity='Net-SNMP notification receiver',
                  version_check=lambda r: r.returncode == 0 and 'net-snmp version' in (r.stdout + r.stderr).lower())
