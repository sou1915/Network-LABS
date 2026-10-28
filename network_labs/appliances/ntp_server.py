"""Bounded chronyd server with an explicit upstream; never controls host time."""
import ipaddress
from pathlib import Path
import re
import subprocess

from .service_config import observe_config

BINARY = '/usr/lib/network-labs/chronyd'
CONFIG = '/lab/ntp-server.conf'
PIDFILE = '/run/network-labs-chronyd.pid'
# chronyd refuses a Unix control socket in a directory accessible to other
# users. /run itself is shared (normally 0755); let chronyd create its private
# subdirectory with the required permissions.
CONTROL_SOCKET = '/run/network-labs-chrony/chronyd.sock'
CHRONYC = '/usr/lib/network-labs/chronyc'


def validate_node(node):
    from .lan import addresses
    from .spec import integer, keys
    config = node.setdefault('ntp_server', None)
    if config is None:
        return
    keys(config, ('interface', 'upstream', 'local_stratum', 'clients'), 'NTP server')
    port = config.get('interface'); addresses_by_port = addresses(node)
    if (node['runtime'] != 'oci' or not isinstance(port, str) or not addresses_by_port.get(port) or
            port in node['shutdown'] or node.get('startup')):
        raise ValueError('NTP requires a numbered UP OCI interface and no unmanaged startup.')
    interface = ipaddress.IPv4Interface(addresses_by_port[port]); local = interface.ip
    if (local.is_unspecified or local.is_multicast or local.is_loopback or local.is_reserved or
            (interface.network.prefixlen < 31 and local in (interface.network.network_address, interface.network.broadcast_address))):
        raise ValueError('NTP server requires a usable IPv4 address.')
    def remote(value):
        address = ipaddress.IPv4Address(value)
        if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_reserved or address == local:
            raise ValueError('NTP peers must be remote unicast IPv4 addresses.')
        return str(address)
    if ('upstream' in config) == ('local_stratum' in config):
        raise ValueError('Choose exactly one NTP upstream or isolated local reference.')
    if 'upstream' in config:
        if not isinstance(config['upstream'], str):
            raise ValueError('NTP upstream must be an explicit IPv4 address.')
        config['upstream'] = remote(config['upstream'])
    else:
        integer(config['local_stratum'], 2, 14, 'NTP local reference stratum')
    clients = config.get('clients')
    if not isinstance(clients, list) or not 1 <= len(clients) <= 16 or not all(isinstance(x, str) for x in clients):
        raise ValueError('NTP requires 1..16 explicit IPv4 clients.')
    config['clients'] = sorted(set(remote(x) for x in clients))
    if config.get('upstream') in config['clients']:
        raise ValueError('NTP upstream and downstream clients must be distinct.')


def validate_lab(spec):
    from .lan import addresses
    for node in spec['nodes']:
        config = node.get('ntp_server')
        if not config:
            continue
        for address in ([config['upstream']] if 'upstream' in config else []) + config['clients']:
            peers = [n for n in spec['nodes'] if any(v and str(ipaddress.IPv4Interface(v).ip) == address for v in addresses(n).values())]
            if len(peers) != 1 or peers[0]['name'] == node['name']:
                raise ValueError('Each NTP peer must identify exactly one other managed node.')


def config_text(node):
    from .lan import addresses
    config = node['ntp_server']
    address = str(ipaddress.IPv4Interface(addresses(node)[config['interface']]).ip)
    source = 'server ' + config['upstream'] + ' iburst' if 'upstream' in config else 'local stratum ' + str(config['local_stratum'])
    return '\n'.join(['bindaddress ' + address, 'cmdport 0', 'bindcmdaddress ' + CONTROL_SOCKET, 'pidfile ' + PIDFILE,
                      source,
                      *['allow ' + client + '/32' for client in config['clients']], ''])


def prepare_files(bundle, node):
    if node.get('ntp_server'):
        path = Path(bundle) / 'files/ntp-server.conf'
        path.write_text(config_text(node)); path.chmod(0o644)


def command():
    return [BINARY, '-n', '-4', '-x', '-u', 'root', '-f', CONFIG]


def start_servers(manager):
    from .runtime import RuntimeFailure
    for node in manager.state['spec']['nodes']:
        if not node.get('ntp_server'):
            continue
        checked = manager.crun('exec', node['name'], BINARY, '-p', '-f', CONFIG, check=False, timeout=5)
        if checked.returncode:
            raise RuntimeFailure(node['name'] + ': chronyd configuration rejected: ' + (checked.stdout + checked.stderr)[-2048:])
        manager.crun('exec', '--detach', node['name'], *command(), log=manager.directory / node['name'] / 'chronyd.log')


def observe_process(manager, node):
    """A pidfile and matching /proc argv are observations, not service health."""
    from .runtime import RuntimeFailure
    result = {'status': 'unknown', 'pid': None, 'detail': None}
    try:
        pidfile = manager.crun('exec', node['name'], '/bin/busybox', 'cat', PIDFILE, check=False, timeout=3)
        if pidfile.returncode or not re.fullmatch(r'[0-9]{1,10}\s*', pidfile.stdout):
            result['detail'] = 'PID file missing, unreadable or invalid.'
            return result
        pid = int(pidfile.stdout.strip())
        if not 1 <= pid <= 2147483647:
            result['detail'] = 'PID outside valid range.'
            return result
        result['pid'] = pid
        proc = manager.crun('exec', node['name'], '/bin/busybox', 'cat', '/proc/' + str(pid) + '/cmdline', check=False, timeout=3)
        if proc.returncode or not proc.stdout:
            result['detail'] = 'PID command line unavailable; process may have stopped.'
            return result
        args = proc.stdout.split('\0')
        if args[-1] == '':
            args.pop()
        if args != command():
            result.update(status='mismatch', detail='PID command line differs from managed chronyd invocation.')
            return result
        result.update(status='observed', detail='PID and expected invocation observed at read time.')
        return result
    except (OSError, RuntimeFailure, subprocess.TimeoutExpired, UnicodeError, ValueError) as error:
        result['detail'] = str(error)[:300]
        return result


def observe(manager, node):
    from .lan import addresses
    from .ntp_socket import observe_socket
    result = observe_config(manager, node['name'], CONFIG, config_text(node))
    address = str(ipaddress.IPv4Interface(addresses(node)[node['ntp_server']['interface']]).ip)
    return {'configuration_verified': result['configuration_verified'], 'file': result, 'process': observe_process(manager, node),
            'udp_socket': observe_socket(manager, node, address),
            'upstream': node['ntp_server'].get('upstream'), 'local_stratum': node['ntp_server'].get('local_stratum'), 'clients': node['ntp_server']['clients'],
            'note': 'File, PID/argv and IPv4 UDP bindings are separate sequential observations. A binding is not attributed to chronyd and does not prove synchronization or delivery. PID reuse or state changes may occur. Local reference does not prove accurate time. No clock adjustment; unauthenticated IPv4 NTP.'}


def drift(manager, node):
    return [node['name'] + ': NTP server configuration differs or is unavailable'] if node.get('ntp_server') and not observe(manager, node)['configuration_verified'] else []


def rootfs_assets(binary):
    from .dns_rootfs import assets
    return assets(binary, destination=BINARY, identity='chronyd', version_args=('-v',),
                  version_check=lambda r: r.returncode == 0 and (r.stdout + r.stderr).lower().startswith('chronyd '))


def client_rootfs_assets(binary):
    from .dns_rootfs import assets
    return assets(binary, destination=CHRONYC, identity='chronyc', version_args=('-v',),
                  version_check=lambda r: r.returncode == 0 and (r.stdout + r.stderr).lower().startswith('chronyc '))


def read_cli(manager, node, operation):
    from .runtime import RuntimeFailure
    if operation not in ('tracking', 'sources'):
        raise ValueError('Unsupported chronyc read operation.')
    result = manager.crun('exec', node, CHRONYC, '-n', '-h', CONTROL_SOCKET, operation, check=False, timeout=5)
    if result.returncode or not result.stdout.strip() or len(result.stdout) > 32768:
        raise RuntimeFailure('chronyc or local NTP control socket unavailable; no NTP status can be inferred.')
    return result.stdout
