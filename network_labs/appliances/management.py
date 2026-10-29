"""Real Dropbear SSH, authenticated BusyBox Telnet and UDP syslog forwarding."""
import base64
import ipaddress
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
from .service_config import observe_config

DROPBEAR = '/usr/sbin/dropbear'
USER_LINE = 'lab:{password}:65532:65532:Network LABS:/home/lab:/bin/sh'


def public_key(value):
    if not isinstance(value, str) or '\n' in value.strip() or '\r' in value or len(value) > 512:
        raise ValueError('SSH requires one OpenSSH ed25519 public key per entry, without options.')
    parts = value.strip().split()
    if len(parts) < 2 or parts[0] != 'ssh-ed25519':
        raise ValueError('Initial SSH profile accepts ssh-ed25519 public keys only.')
    try:
        raw = base64.b64decode(parts[1], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('Invalid SSH public key encoding.') from error
    if len(raw) != 51 or raw[:19] != struct.pack('!I', 11) + b'ssh-ed25519' + struct.pack('!I', 32):
        raise ValueError('Invalid SSH ed25519 public key wire format.')
    return 'ssh-ed25519 ' + base64.b64encode(raw).decode()


def validate_node(node):
    from .lan import addresses
    from .spec import keys
    config = node.setdefault('management', None)
    if config is None: return
    keys(config, ('interface', 'ssh_keys', 'ssh_actions', 'ssh_radius', 'telnet_password_hash', 'syslog_remote'), 'Management')
    port = config.get('interface')
    values = addresses(node)
    if (node['runtime'] != 'oci' or not isinstance(port, str) or port not in values or not values[port] or
            port in node['shutdown'] or node.get('startup')):
        raise ValueError('Management requires a numbered, UP OCI IPv4 interface and no unmanaged startup commands.')
    interface = ipaddress.IPv4Interface(values[port]); local = interface.ip
    if (local.is_unspecified or local.is_multicast or local.is_loopback or local.is_reserved or
            (interface.network.prefixlen < 31 and local in (interface.network.network_address, interface.network.broadcast_address))):
        raise ValueError('Management requires a usable IPv4 address.')
    keys_list = config.setdefault('ssh_keys', [])
    if not isinstance(keys_list, list) or len(keys_list) > 16:
        raise ValueError('ssh_keys requires at most 16 public ed25519 keys.')
    config['ssh_keys'] = sorted({public_key(key) for key in keys_list})
    password = config.setdefault('telnet_password_hash', '')
    if not isinstance(password, str) or (password and not re.fullmatch(r'\$6\$(?:rounds=[0-9]{4,7}\$)?[A-Za-z0-9./]{1,16}\$[A-Za-z0-9./]{86}', password)):
        raise ValueError('Telnet requires a SHA-512 crypt password hash; plaintext passwords are not accepted.')
    if password.startswith('$6$rounds=') and not 1000 <= int(password.split('$')[2].split('=')[1]) <= 200000:
        raise ValueError('Telnet crypt rounds must be between 1000 and 200000.')
    if type(config.get('ssh_radius', False)) is not bool:
        raise ValueError('SSH RADIUS selection must be boolean.')
    if config.get('ssh_radius') and (config.get('ssh_actions') is None or not node.get('radius_access')):
        raise ValueError('SSH RADIUS requires restricted SSH actions and a RADIUS access policy.')
    actions = config.get('ssh_actions')
    if actions is not None:
        from .ssh_access import ACTIONS
        supported = (*ACTIONS, 'shell') if config.get('ssh_radius') else tuple(ACTIONS)
        if (not isinstance(actions, list) or len(actions) > len(supported) or
                any(not isinstance(a, str) or a not in supported for a in actions) or len(set(actions)) != len(actions)):
            raise ValueError('SSH actions require distinct supported diagnostics, or shell with RADIUS; an empty list denies all commands.')
        if not config['ssh_keys'] or password:
            raise ValueError('Restricted SSH actions require SSH keys and no Telnet shell on the same node.')
        config['ssh_actions'] = sorted(actions)
    remote = config.setdefault('syslog_remote', '')
    if not isinstance(remote, str): raise ValueError('syslog_remote must be IPv4 text.')
    if remote:
        address = ipaddress.IPv4Address(remote)
        if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_reserved or address == local:
            raise ValueError('Syslog forwarding requires a remote unicast IPv4 collector.')
        config['syslog_remote'] = str(address)
    if not (config['ssh_keys'] or password or remote):
        raise ValueError('Enable at least one management service.')


def validate_lab(spec):
    from .lan import addresses
    for node in spec['nodes']:
        if (node.get('management') or {}).get('ssh_radius'):
            from .ssh_radius import managed_secret
            if node['role'] != 'host' or set(node['interfaces']) != {'eth0'}:
                raise ValueError('SSH RADIUS requires a single-interface OCI host.')
            managed_secret(spec, node)
        remote = (node.get('management') or {}).get('syslog_remote')
        if remote:
            peers = [n['name'] for n in spec['nodes'] if remote in {str(ipaddress.IPv4Interface(v).ip) for v in addresses(n).values() if v}]
            if peers != [name for name in peers if name != node['name']] or len(peers) != 1:
                raise ValueError('Syslog collector must be one other uniquely numbered managed IPv4 node.')


def rootfs_assets(binary):
    from .dns_rootfs import assets
    return assets(binary, destination=DROPBEAR, version_args=('-V',), identity='Dropbear SSH',
                  version_check=lambda r: r.returncode == 0 and 'dropbear v' in (r.stdout + r.stderr).lower())


def listen_address(node):
    from .lan import addresses
    return str(ipaddress.IPv4Interface(addresses(node)[node['management']['interface']]).ip)


def commands(node):
    config = node['management']; result = {}
    if config['syslog_remote']:
        result['syslog'] = ['/bin/busybox', 'syslogd', '-n', '-O', '/run/messages', '-s', '64', '-b', '1',
                            '-R', config['syslog_remote'] + ':514', '-L']
    if config['ssh_keys']:
        result['ssh'] = [DROPBEAR, '-F', '-E', '-R', '-s', '-w', '-j', '-k',
                         '-p', listen_address(node) + ':22', '-P', '/run/dropbear.pid']
    if config['telnet_password_hash']:
        result['telnet'] = ['/bin/busybox', 'telnetd', '-F', '-K', '-b', listen_address(node),
                            '-p', '23', '-l', '/bin/login']
    return result


def managed_files(node):
    config = node['management']
    result = {'management.json': json.dumps({'commands': commands(node)}, sort_keys=True, indent=2) + '\n'}
    if config['ssh_keys'] or config['telnet_password_hash']:
        # Copy the trusted offline base account file, preserving service users.
        with (Path(node['rootfs']) / 'etc/passwd').open() as source:
            raw = source.read(65537)
        if len(raw) > 65536: raise ValueError('Rootfs account file exceeds 64 KiB.')
        lines = [line for line in raw.splitlines() if not line.startswith('lab:')]
        lines.append(USER_LINE.format(password=config['telnet_password_hash'] or 'x'))
        result['management-passwd'] = '\n'.join(lines) + '\n'
        with (Path(node['rootfs']) / 'etc/group').open() as source:
            groups = source.read(65537)
        if len(groups) > 65536: raise ValueError('Rootfs group file exceeds 64 KiB.')
        result['management-group'] = '\n'.join([line for line in groups.splitlines() if not line.startswith('lab:')] + ['lab:x:65532:']) + '\n'
    if config['ssh_keys']:
        from .ssh_access import key_options, dispatcher
        actions = config.get('ssh_actions')
        prefix = '' if actions is None else key_options(actions) + ' '
        result['authorized_keys'] = '\n'.join(prefix + key for key in config['ssh_keys']) + '\n'
        if actions is not None: result['ssh-dispatch.sh'] = dispatcher(actions, radius=config.get('ssh_radius', False),
                session_seconds=(node.get('radius_access') or {}).get('session_seconds', 300))
        if config.get('ssh_radius'):
            from .ssh_radius import CLIENT
            result['ssh-radius-client.sh'] = CLIENT
    return result


def prepare_files(bundle, node):
    if node['management']:
        for name, value in managed_files(node).items():
            path = Path(bundle) / 'files' / name; path.write_text(value); path.chmod(0o644)


def start_service(manager, node, service):
    argv = commands(node).get(service)
    if argv is None: raise ValueError('Management service is not enabled.')
    log = manager.directory / node['name'] / (service + '.log')
    if service == 'ssh' and node['management'].get('ssh_actions') is not None:
        from .ssh_access import service_process
        with tempfile.NamedTemporaryFile(mode='w+', prefix='ssh-process-', suffix='.json', dir=manager.directory) as process:
            json.dump(service_process(argv, terminal='shell' in node['management']['ssh_actions']), process); process.flush()
            manager.crun('exec', '--detach', '--process', process.name, node['name'], log=log)
    else:
        manager.crun('exec', '--detach', node['name'], *argv, log=log)


def start_servers(manager):
    from .runtime import RuntimeFailure
    for index, node in enumerate(manager.state['spec']['nodes']):
        config = node['management']
        if not config: continue
        expected = {'syslogd', 'logger'} if config['syslog_remote'] else set()
        if config['telnet_password_hash']: expected.update(('telnetd', 'login'))
        if config.get('ssh_radius'): expected.update(('nc', 'timeout', 'cat', 'stty', 'base64', 'mktemp', 'mkfifo', 'rm'))
        installed = manager.crun('exec', node['name'], '/bin/busybox', '--list', timeout=3).stdout.splitlines()
        if expected - set(installed):
            raise RuntimeFailure(node['name'] + ': missing BusyBox management applets: ' + ', '.join(sorted(expected - set(installed))))
        for applet, flags in ([('telnetd', ('-F', '-b', '-p', '-l'))] if config['telnet_password_hash'] else []) + ([('syslogd', ('-R', '-L', '-s', '-b'))] if config['syslog_remote'] else []):
            help_result = manager.crun('exec', node['name'], '/bin/busybox', applet, '--help', check=False, timeout=3)
            help_text = help_result.stdout + help_result.stderr
            if any(flag not in help_text for flag in flags):
                raise RuntimeFailure(node['name'] + ': BusyBox ' + applet + ' lacks required management options.')
        if config['ssh_keys'] or config['telnet_password_hash']:
            manager.crun('exec', node['name'], '/bin/busybox', 'mkdir', '-p', '/home/lab/.ssh', '/etc/dropbear')
            if config.get('ssh_actions') is not None:
                # A writable ancestor could replace the directory containing
                # the read-only authorized_keys bind mount.
                manager.crun('exec', node['name'], '/bin/busybox', 'chown', '0:0', '/home', '/home/lab', '/home/lab/.ssh')
                manager.crun('exec', node['name'], '/bin/busybox', 'chmod', '755', '/home', '/home/lab', '/home/lab/.ssh')
            else:
                manager.crun('exec', node['name'], '/bin/busybox', 'chown', '65532:65532', '/home/lab')
        if config.get('ssh_radius') and 'shell' in config['ssh_actions']:
            from .ssh_access import RELAY_BINARY
            checked = manager.crun('exec', node['name'], RELAY_BINARY, '--version', check=False, timeout=3)
            if checked.returncode or checked.stdout != 'Network LABS SSH relay 1\n':
                raise RuntimeFailure(node['name'] + ': SSH RADIUS relay identity unavailable.')
        if config.get('ssh_radius'):
            checked = manager.crun('exec', node['name'], '/bin/sh', '-c',
                                   'IFS= read -r -n 2 value; [ "$value" = ab ]', input_text='ab\n', check=False, timeout=3)
            if checked.returncode: raise RuntimeFailure(node['name'] + ': SSH RADIUS requires bounded BusyBox read.')
            from .ssh_radius import start_worker
            start_worker(manager, index, node)
        for service in commands(node): start_service(manager, node, service)


def observe(manager, node):
    files = managed_files(node)
    checks = {name: observe_config(manager, node['name'], '/lab/' + name, value) for name, value in files.items()}
    config = node['management']
    if 'management-passwd' in files:
        checks['active_passwd'] = observe_config(manager, node['name'], '/etc/passwd', files['management-passwd'])
        checks['active_group'] = observe_config(manager, node['name'], '/etc/group', files['management-group'])
    if 'authorized_keys' in files:
        checks['active_authorized_keys'] = observe_config(manager, node['name'], '/home/lab/.ssh/authorized_keys', files['authorized_keys'])
    if config.get('ssh_actions') is not None:
        verified = False
        try:
            mode = manager.crun('exec', node['name'], '/bin/busybox', 'stat', '-c', '%a:%u:%g',
                                '/home', '/home/lab', '/home/lab/.ssh', '/lab/ssh-dispatch.sh',
                                *(['/lab/ssh-radius-client.sh'] if config.get('ssh_radius') else []), check=False, timeout=3)
            verified = mode.returncode == 0 and mode.stdout == ('755:0:0\n755:0:0\n755:0:0\n644:0:0\n' +
                ('644:0:0\n' if config.get('ssh_radius') else ''))
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass
        checks['ssh_policy_permissions'] = {'configuration_verified': verified}
    bridge_available = None
    if config.get('ssh_radius'):
        from .ssh_radius import alive
        bridge_available = alive(manager.read().get('ssh_radius_workers', {}).get(node['name']))
    return {'configuration_verified': all(v['configuration_verified'] for v in checks.values()),
            'files': checks, 'address': listen_address(node), 'ssh': bool(config['ssh_keys']),
            'telnet': bool(config['telnet_password_hash']), 'syslog_remote': config['syslog_remote'],
            'ssh_actions': config.get('ssh_actions'), 'ssh_radius': config.get('ssh_radius', False),
            'ssh_radius_worker_available': bridge_available,
            'note': 'Managed file conformity only; not daemon liveness, authentication, received logs or vendor CLI fidelity. SSH/Telnet use uid 65532. An explicit ssh_actions list confines SSH to declared diagnostics and an optional explicitly authorized RADIUS shell; forwarding stays disabled; SSH key authentication is followed by RADIUS per diagnostic only when ssh_radius is enabled. Worker availability is a process observation, not an authentication verdict. Syslog sends UDP/514; no collector/TCP/TLS service or runtime log/host-key snapshot.'}


def drift(manager, node):
    return [node['name'] + ': management configuration differs or is unavailable'] if node['management'] and not observe(manager, node)['configuration_verified'] else []
