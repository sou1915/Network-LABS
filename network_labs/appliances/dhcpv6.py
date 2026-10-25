"""Stateful IA_NA DHCPv6 on one physical client LAN; gateway discovery stays RA."""
import ipaddress
from pathlib import Path
from .service_config import observe_config

# BusyBox udhcpc6 exports the IA_NA address as ipv6 and its valid lifetime as
# lease. The supported dnsmasq profile advertises equal preferred/valid times.
# Never flush link-local addresses, RA prefix/default routes or IPv4 state.
CLIENT_SCRIPT = '''#!/bin/sh
set -eu
case "$1" in
    deconfig)
        /bin/busybox ip -6 addr flush dev "$interface" scope global
        ;;
    bound|renew)
        : "${ipv6:?Missing DHCPv6 IA_NA address}" "${lease:?Missing DHCPv6 lifetime}"
        case "$lease" in ''|*[!0-9]*) exit 1;; esac
        /bin/busybox ip -6 addr flush dev "$interface" scope global
        /bin/busybox ip -6 addr add "$ipv6/128" dev "$interface" valid_lft "$lease" preferred_lft "$lease"
        ;;
esac
'''


def validate_node(node):
    from .spec import keys, integer
    clients = node.setdefault('dhcpv6_clients', [])
    server = node.setdefault('dhcpv6_server', None)
    if (not isinstance(clients, list) or len(clients) > 1 or
            any(not isinstance(p, str) or p not in node['interfaces'] for p in clients)):
        raise ValueError('dhcpv6_clients requires at most one declared physical interface.')
    if clients and (node['runtime'] != 'oci' or node['role'] != 'host' or set(clients) != set(node['interfaces']) or
                    node['ipv6'] or node['ipv6_routes'] or node['ipv6_forwarding'] or node.get('slaac')):
        raise ValueError('DHCPv6 client requires a single-interface OCI host without static IPv6, routes or SLAAC.')
    if any(p in node.get('shutdown', []) for p in clients):
        raise ValueError('DHCPv6 client must be administratively UP.')
    if server is None:
        return
    keys(server, ('interface', 'start', 'end', 'lease_seconds'), 'DHCPv6 server')
    port = server.get('interface')
    if (node['runtime'] != 'oci' or node['role'] != 'router' or not node['ipv6_forwarding'] or
            not isinstance(port, str) or port not in node['ipv6'] or port not in node.get('router_advertisements', [])):
        raise ValueError('DHCPv6 server requires a numbered IPv6-forwarding router port with router_advertisements enabled.')
    if not all(isinstance(server.get(k), str) and '%' not in server[k] for k in ('start', 'end')):
        raise ValueError('DHCPv6 start/end must be unscoped IPv6 address strings.')
    start, end = (ipaddress.IPv6Address(server[k]) for k in ('start', 'end'))
    local = ipaddress.IPv6Interface(node['ipv6'][port])
    if (not local.network.network_address < start <= end < local.network.broadcast_address or
            int(end) - int(start) >= 256 or start <= local.ip <= end):
        raise ValueError('DHCPv6 pool requires 1..256 usable local /64 addresses, excluding its router.')
    server.update(start=str(start), end=str(end))
    integer(server.setdefault('lease_seconds', 120), 60, 86400, 'DHCPv6 lease_seconds')


def validate_lab(spec):
    # Static endpoints must never overlap dynamically allocated pool addresses.
    static = [ipaddress.IPv6Interface(v).ip for n in spec['nodes'] for v in n['ipv6'].values()]
    pools = [n['dhcpv6_server'] for n in spec['nodes'] if n['dhcpv6_server']]
    for i, pool in enumerate(pools):
        start, end = (ipaddress.IPv6Address(pool[k]) for k in ('start', 'end'))
        if any(start <= a <= end for a in static):
            raise ValueError('DHCPv6 pool overlaps a declared static IPv6 address.')
        if any(start <= ipaddress.IPv6Address(other['end']) and ipaddress.IPv6Address(other['start']) <= end for other in pools[i + 1:]):
            raise ValueError('Overlapping DHCPv6 pools are outside this profile.')


def prepare_files(bundle, node):
    if node['dhcpv6_clients']:
        path = Path(bundle) / 'files/dhcpv6-client.sh'
        path.write_text(CLIENT_SCRIPT); path.chmod(0o755)


def start_clients(manager):
    from .runtime import RuntimeFailure
    for node in manager.state['spec']['nodes']:
        if not node['dhcpv6_clients']:
            continue
        applets = manager.crun('exec', node['name'], '/bin/busybox', '--list', timeout=3).stdout.splitlines()
        if 'udhcpc6' not in applets:
            raise RuntimeFailure(node['name'] + ': rootfs BusyBox must include udhcpc6; no simulated fallback is used.')
        for port in node['dhcpv6_clients']:
            manager.crun('exec', '--detach', node['name'], '/bin/busybox', 'udhcpc6', '-f',
                         '-i', port, '-s', '/lab/dhcpv6-client.sh', '-p', '/run/udhcpc6.pid',
                         '-t', '3', '-T', '1', '-A', '3', '-o',
                         log=manager.directory / node['name'] / 'dhcpv6.log')


def observe_client(manager, node):
    return {**observe_config(manager, node['name'], '/lab/dhcpv6-client.sh', CLIENT_SCRIPT),
            'interfaces': node['dhcpv6_clients'],
            'source': 'Managed BusyBox udhcpc6 event script',
            'note': 'File conformity does not prove client liveness, a lease or DHCP origin. Actual addresses/DAD and RA defaults must be observed separately. No DNS, IA_PD or lease snapshot.'}


def drift(manager, index, node):
    if node['dhcpv6_clients'] and not observe_client(manager, node)['configuration_verified']:
        return [node['name'] + ': DHCPv6 client script differs or is unavailable']
    return []
