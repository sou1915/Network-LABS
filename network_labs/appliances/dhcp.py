"""BusyBox DHCP server/client inside OCI nodes, with a real DHCP event hook."""
import ipaddress
from pathlib import Path

from .lan import addresses


CLIENT_SCRIPT = '''#!/bin/sh
set -eu
case "$1" in
    deconfig)
        /bin/busybox ip -4 addr flush dev "$interface" scope global
        /bin/busybox ip -4 route flush default
        ;;
    bound|renew)
        prefix=$(/bin/busybox ipcalc -p "$ip" "$subnet")
        prefix=${prefix#PREFIX=}
        /bin/busybox ip -4 addr flush dev "$interface" scope global
        /bin/busybox ip addr add "$ip/$prefix" dev "$interface"
        /bin/busybox ip -4 route flush default
        for gateway in ${router:-}; do
            /bin/busybox ip route add default via "$gateway" dev "$interface"
            break
        done
        : > /etc/resolv.conf
        for server in ${dns:-}; do
            printf 'nameserver %s\\n' "$server" >> /etc/resolv.conf
        done
        ;;
esac
'''


def pool_network(node):
    config = node['dhcp_server']
    return ipaddress.IPv4Network(config['network'], strict=True) if 'network' in config else ipaddress.IPv4Interface(addresses(node)[config['interface']]).network


def validate_reservations(node):
    from .spec import keys
    from .port_security import mac_address
    config = node['dhcp_server']
    reservations = config.setdefault('reservations', [])
    if not isinstance(reservations, list) or len(reservations) > 256:
        raise ValueError('DHCP reservations must be an array with at most 256 entries.')
    local = ipaddress.IPv4Interface(addresses(node)[config['interface']])
    network = pool_network(node)
    macs, ips = set(), set()
    for entry in reservations:
        keys(entry, ('mac', 'address'), 'DHCP reservation')
        mac = mac_address(entry.get('mac'))
        if not isinstance(entry.get('address'), str):
            raise ValueError('DHCP reservation address must be IPv4 text.')
        address = ipaddress.IPv4Address(entry['address'])
        if address not in network or address in (network.network_address, network.broadcast_address, local.ip) or str(address) == config['router'] or address.is_multicast or address.is_loopback or address.is_unspecified:
            raise ValueError('DHCP reservation requires a usable address in the server subnet, distinct from server/router.')
        if mac in macs or address in ips:
            raise ValueError('DHCP reservations require unique MAC addresses and unique IPv4 addresses.')
        entry['mac'], entry['address'] = mac, str(address)
        macs.add(mac); ips.add(address)
    config['reservations'] = sorted(reservations, key=lambda item: item['mac'])


def server_config(node):
    config = node['dhcp_server']
    network = pool_network(node)
    maximum = int(ipaddress.IPv4Address(config['end'])) - int(ipaddress.IPv4Address(config['start'])) + 1
    lines = [f'interface {config["interface"]}', f'start {config["start"]}', f'end {config["end"]}',
             f'max_leases {maximum}', 'remaining yes', 'auto_time 30',
             'lease_file /run/udhcpd.leases', 'pidfile /run/udhcpd.pid',
             f'option subnet {network.netmask}', f'option lease {config["lease_seconds"]}']
    if config['router']:
        lines.append('option router ' + config['router'])
    if config['dns']:
        lines.append('option dns ' + ' '.join(config['dns']))
    for reservation in config.get('reservations', []):
        lines.append(f'static_lease {reservation["mac"]} {reservation["address"]}')
    return '\n'.join(lines) + '\n'


def observe_server(manager, node):
    # Read the config in the container mount namespace. Do not follow a
    # container-controlled /proc/PID/root symlink from the host. Bound output.
    from .service_config import observe_config
    observation = observe_config(manager, node['name'], '/lab/udhcpd.conf', server_config(node))
    return {**observation, 'source': 'Declared BusyBox DHCP policy and bounded container config-file observation',
            'reservations': node['dhcp_server'].get('reservations', []),
            'pool': {key: node['dhcp_server'][key] for key in ('interface', 'start', 'end')},
            'pool_network': str(pool_network(node)),
            'note': 'Reservations are declared policy, not observed leases or proof the daemon is running/loaded unchanged. Actual client addresses and DHCP snooping ACKs are separate evidence. No runtime lease snapshot.'}


def prepare_files(bundle, node):
    folder = Path(bundle) / 'files'; folder.mkdir()
    (folder / 'dhcp-client.sh').write_text(CLIENT_SCRIPT)
    (folder / 'dhcp-client.sh').chmod(0o755)
    if node['dhcp_server']:
        (folder / 'udhcpd.conf').write_text(server_config(node))


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if node.get('dhcp_server'):
            manager.crun('exec', '--detach', node['name'], '/bin/busybox', 'udhcpd', '-f', '/lab/udhcpd.conf',
                         log=manager.directory / node['name'] / 'dhcp.log')


def start_clients(manager):
    for node in manager.state['spec']['nodes']:
        for interface in node.get('dhcp_clients', []):
            manager.crun('exec', '--detach', node['name'], '/bin/busybox', 'udhcpc', '-f',
                         '-i', interface, '-s', '/lab/dhcp-client.sh', '-p', '/run/udhcpc.pid',
                         '-t', '3', '-T', '1', '-A', '3',
                         log=manager.directory / node['name'] / 'dhcp.log')

def validate_server(node):
    from .lan import addresses
    from .spec import keys, integer
    all_interfaces = addresses(node)
    server = node['dhcp_server']
    keys(server, ('interface', 'start', 'end', 'router', 'dns', 'lease_seconds', 'reservations', 'network'), 'DHCP server')
    interface = server.get('interface')
    if interface not in all_interfaces or not all_interfaces[interface] or node['role'] == 'switch':
        raise ValueError('DHCP server requires a numbered interface on a host/router/firewall.')
    network = ipaddress.IPv4Interface(all_interfaces[interface])
    if 'network' in server and not isinstance(server['network'], str):
        raise ValueError('DHCP network must be canonical IPv4 CIDR text.')
    pool = pool_network(node)
    if 'network' in server:
        if pool.prefixlen == 0 or pool.prefixlen > 30 or any(pool.overlaps(ipaddress.IPv4Network(block)) for block in ('0.0.0.0/8', '127.0.0.0/8', '224.0.0.0/4', '240.0.0.0/4')):
            raise ValueError('DHCP network requires a canonical broadcast IPv4 subnet with prefix 1..30.')
        if pool != network.network and any(address and pool.overlaps(ipaddress.IPv4Interface(address).network) for address in all_interfaces.values()):
            raise ValueError('A remote DHCP network must be disjoint from the server interface networks.')
        server['network'] = str(pool)
    start, end = ipaddress.IPv4Address(server.get('start')), ipaddress.IPv4Address(server.get('end'))
    if not (pool.network_address < start <= end < pool.broadcast_address) or int(end) - int(start) >= 256:
        raise ValueError('DHCP pool: 1..256 usable addresses in the server subnet.')
    if start <= network.ip <= end:
        raise ValueError('DHCP pool overlaps its server address.')
    router = server.setdefault('router', '')
    if router:
        gateway = ipaddress.IPv4Address(router)
        if gateway not in pool or gateway in (pool.network_address, pool.broadcast_address) or start <= gateway <= end:
            raise ValueError('DHCP router must be usable, in subnet and outside the pool.')
    dns = server.setdefault('dns', [])
    if not isinstance(dns, list) or len(dns) > 3:
        raise ValueError('DHCP dns: array of up to three IPv4 addresses.')
    for address in dns:
        ipaddress.IPv4Address(address)
    integer(server.setdefault('lease_seconds', 3600), 60, 604800, 'DHCP lease_seconds')
    validate_reservations(node)
