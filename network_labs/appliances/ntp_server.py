"""Bounded chronyd server with an explicit upstream; never controls host time."""
import ipaddress
from pathlib import Path

from .service_config import observe_config

BINARY = '/usr/lib/network-labs/chronyd'
CONFIG = '/lab/ntp-server.conf'


def validate_node(node):
    from .lan import addresses
    from .spec import keys
    config = node.setdefault('ntp_server', None)
    if config is None:
        return
    keys(config, ('interface', 'upstream', 'clients'), 'NTP server')
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
    if not isinstance(config.get('upstream'), str):
        raise ValueError('NTP requires one explicit IPv4 upstream.')
    config['upstream'] = remote(config['upstream'])
    clients = config.get('clients')
    if not isinstance(clients, list) or not 1 <= len(clients) <= 16 or not all(isinstance(x, str) for x in clients):
        raise ValueError('NTP requires 1..16 explicit IPv4 clients.')
    config['clients'] = sorted(set(remote(x) for x in clients))
    if config['upstream'] in config['clients']:
        raise ValueError('NTP upstream and downstream clients must be distinct.')


def validate_lab(spec):
    from .lan import addresses
    for node in spec['nodes']:
        config = node.get('ntp_server')
        if not config:
            continue
        for address in [config['upstream'], *config['clients']]:
            peers = [n for n in spec['nodes'] if any(v and str(ipaddress.IPv4Interface(v).ip) == address for v in addresses(n).values())]
            if len(peers) != 1 or peers[0]['name'] == node['name']:
                raise ValueError('Each NTP peer must identify exactly one other managed node.')


def config_text(node):
    from .lan import addresses
    config = node['ntp_server']
    address = str(ipaddress.IPv4Interface(addresses(node)[config['interface']]).ip)
    return '\n'.join(['bindaddress ' + address, 'cmdport 0', 'bindcmdaddress /run/network-labs-chronyd.sock', 'pidfile /run/network-labs-chronyd.pid',
                      'server ' + config['upstream'] + ' iburst',
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


def observe(manager, node):
    result = observe_config(manager, node['name'], CONFIG, config_text(node))
    return {'configuration_verified': result['configuration_verified'], 'file': result,
            'upstream': node['ntp_server']['upstream'], 'clients': node['ntp_server']['clients'],
            'note': 'Configuration conformity only; not daemon liveness, synchronization or delivery. No clock adjustment; unauthenticated IPv4 NTP.'}


def drift(manager, node):
    return [node['name'] + ': NTP server configuration differs or is unavailable'] if node.get('ntp_server') and not observe(manager, node)['configuration_verified'] else []


def rootfs_assets(binary):
    from .dns_rootfs import assets
    return assets(binary, destination=BINARY, identity='chronyd', version_args=('-v',),
                  version_check=lambda r: r.returncode == 0 and (r.stdout + r.stderr).lower().startswith('chronyd '))
