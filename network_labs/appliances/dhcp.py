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
    return '\n'.join(lines) + '\n'


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
