"""Native Net-SNMP v2c notifications and a log-only node-local receiver."""
import ipaddress
import json
from pathlib import Path
import re
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
    keys(config, ('interface', 'community', 'sources'), 'SNMP receiver')
    port = config.get('interface'); values = addresses(node)
    if (node['runtime'] != 'oci' or not isinstance(port, str) or not values.get(port) or
            port in node['shutdown'] or node.get('startup') or (node.get('management') or {}).get('syslog_remote')):
        raise ValueError('SNMP receiver requires a numbered UP OCI IPv4 interface, no unmanaged startup and exclusive ownership of local syslogd.')
    local = ipaddress.IPv4Interface(values[port]); address(str(local.ip))
    if local.network.prefixlen < 31 and local.ip in (local.network.network_address, local.network.broadcast_address):
        raise ValueError('SNMP receiver requires a usable interface address.')
    community(config.get('community'))
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
    keys(config, ('receiver', 'community', 'mode'), 'SNMP notifications')
    if agent.get('usm'): raise ValueError('This notification profile is v2c only; USM notifications require a separate profile.')
    config['receiver'] = address(config.get('receiver')); community(config.get('community'))
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
        sender = (node.get('snmp_agent') or {}).get('notifications')
        if sender:
            found = peers(sender['receiver'])
            destination = found[0].get('snmp_receiver') if len(found) == 1 else None
            if (not destination or listen_address(found[0]) != sender['receiver'] or
                    destination['community'] != sender['community'] or sender_address(node) not in destination['sources']):
                raise ValueError('Notifications require one matching managed receiver community, bind address and source policy.')


def sender_lines(node):
    from .snmp import listen_address as sender_address
    config = node['snmp_agent'].get('notifications')
    if not config: return []
    flags = '-Ci ' if config['mode'] == 'inform' else ''
    return ['[snmp] clientaddr ' + sender_address(node),
            'trapsess -v2c ' + flags + '-c ' + config['community'] + ' -t 1 -r 1 udp:' + config['receiver'] + ':162']


def client_config(node):
    from .snmp import listen_address as sender_address
    config = node['snmp_agent']['notifications']
    return '\n'.join(['defVersion 2c', 'defCommunity ' + config['community'], 'clientaddr ' + sender_address(node), ''])


def config_text(node):
    config = node['snmp_receiver']
    return '\n'.join([
        'snmpTrapdAddr udp:' + listen_address(node) + ':162', '[snmp] persistentDir /run/snmptrapd',
        'sourceFilterType acceptlist',
        *['sourceFilterAddress ' + ip for ip in config['sources']],
        *['authCommunity log ' + config['community'] + ' ' + ip for ip in config['sources']],
        'format1 %b %v\\n', 'format syslog1 %b %v\\n',
        'format2 %b %v\\n', 'format syslog2 %b %v\\n', '',
    ])


def log_command():
    return ['/bin/sh', '-c', 'umask 077; exec "$@"', 'notification-log',
            '/bin/busybox', 'syslogd', '-n', '-O', LOG, '-s', '64', '-b', '1']


def command():
    return [BINARY, '-f', '-C', '-c', CONFIG, '-m', '', '-On', '-n', '-X', '-Ls6', '-p', '/run/snmptrapd.pid']


def prepare_files(bundle, node):
    if not node.get('snmp_receiver'): return
    for name, text in {'snmp-receiver.conf': config_text(node),
                       'snmp-notification-log.json': json.dumps({'command': log_command()}, sort_keys=True, indent=2) + '\n'}.items():
        path = Path(bundle) / 'files' / name; path.write_text(text); path.chmod(0o600)


def _wait(manager, node, check, message):
    from .runtime import RuntimeFailure
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if check(): return
        time.sleep(.05)
    raise RuntimeFailure(node['name'] + ': ' + message)


def start_trapd(manager, node, index):
    manager.crun('exec', node['name'], '/bin/busybox', 'mkdir', '-p', '/run/snmptrapd')
    manager.crun('exec', '--detach', node['name'], *command(), log=manager.directory / node['name'] / 'snmptrapd.log')
    _wait(manager, node, lambda: listen_address(node) + ':162' in manager.ns(index, 'ss', '-H', '-lun', 'sport = :162', timeout=2).stdout.split(),
          'SNMP receiver did not bind its declared UDP address.')


def start_receivers(manager):
    from .runtime import RuntimeFailure
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
    return {'configuration_verified': all(row['configuration_verified'] for row in files.values()), 'files': files,
            'address': listen_address(node), 'port': 162, 'sources': node['snmp_receiver']['sources'], 'versions': ['1', '2c'], 'log': LOG,
            'note': 'Managed config conformity, not ongoing liveness, receipt, authorization or log delivery. Community notifications (v1/v2c) are plaintext; source policy is not anti-spoofing. INFORM acknowledgement and accepted logging are separate evidence. Logs rotate at 64 KiB with one backup in volatile /run; payloads can be truncated. No execution hooks, forwarding, v3 notifications, durable queue/history or automatic link-event mapping.'}


def drift(manager, node):
    return [node['name'] + ': SNMP receiver configuration differs or is unavailable'] if node.get('snmp_receiver') and not observe(manager, node)['configuration_verified'] else []


def rootfs_assets(binary):
    from .dns_rootfs import assets
    return assets(binary, destination=BINARY, version_args=('-v',), identity='Net-SNMP notification receiver',
                  version_check=lambda r: r.returncode == 0 and 'net-snmp version' in (r.stdout + r.stderr).lower())
