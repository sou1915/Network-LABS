"""BusyBox DHCP server/client inside OCI nodes, with a real DHCP event hook."""
import ipaddress
import subprocess
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


def validate_reservations(node):
    from .spec import keys
    from .port_security import mac_address
    config = node['dhcp_server']
    reservations = config.setdefault('reservations', [])
    if not isinstance(reservations, list) or len(reservations) > 256:
        raise ValueError('DHCP reservations must be an array with at most 256 entries.')
    local = ipaddress.IPv4Interface(addresses(node)[config['interface']])
    macs, ips = set(), set()
    for entry in reservations:
        keys(entry, ('mac', 'address'), 'DHCP reservation')
        mac = mac_address(entry.get('mac'))
        if not isinstance(entry.get('address'), str):
            raise ValueError('DHCP reservation address must be IPv4 text.')
        address = ipaddress.IPv4Address(entry['address'])
        if address not in local.network or address in (local.network.network_address, local.network.broadcast_address, local.ip) or str(address) == config['router'] or address.is_multicast or address.is_loopback or address.is_unspecified:
            raise ValueError('DHCP reservation requires a usable address in the server subnet, distinct from server/router.')
        if mac in macs or address in ips:
            raise ValueError('DHCP reservations require unique MAC addresses and unique IPv4 addresses.')
        entry['mac'], entry['address'] = mac, str(address)
        macs.add(mac); ips.add(address)
    config['reservations'] = sorted(reservations, key=lambda item: item['mac'])


def server_config(node):
    config = node['dhcp_server']
    address = ipaddress.IPv4Interface(addresses(node)[config['interface']])
    maximum = int(ipaddress.IPv4Address(config['end'])) - int(ipaddress.IPv4Address(config['start'])) + 1
    lines = [f'interface {config["interface"]}', f'start {config["start"]}', f'end {config["end"]}',
             f'max_leases {maximum}', 'remaining yes', 'auto_time 30',
             'lease_file /run/udhcpd.leases', 'pidfile /run/udhcpd.pid',
             f'option subnet {address.netmask}', f'option lease {config["lease_seconds"]}']
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
    detail = None
    content = None
    try:
        observed = manager.crun('exec', node['name'], '/bin/busybox', 'head', '-c', '65537',
                                '/lab/udhcpd.conf', check=False)
        available = observed.returncode == 0 and len(observed.stdout.encode('utf-8')) <= 65536
        content = observed.stdout if available else None
        if not available:
            detail = 'Config read failed or exceeded 64 KiB.'
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        available = False
        detail = str(exc)[:1024]
    return {'source': 'Declared BusyBox DHCP policy and bounded container config-file observation',
            'configuration_verified': available and content == server_config(node),
            'configuration_available': available, 'detail': detail,
            'reservations': node['dhcp_server'].get('reservations', []),
            'pool': {key: node['dhcp_server'][key] for key in ('interface', 'start', 'end')},
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
