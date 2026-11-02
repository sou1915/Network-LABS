"""Bounded physical DHCPv6 relay and remote IA_NA pool, with independent BIRD RA."""
import ipaddress
from pathlib import Path
import time

from .spec import keys, integer
from .service_config import observe_config

BINARY = '/usr/sbin/dnsmasq'


def validate_node(node):
    relay = node.setdefault('dhcpv6_relay', None)
    server = node.setdefault('dhcpv6_remote_server', None)
    if relay is None and server is None:
        return
    if (relay is not None and server is not None or node['runtime'] != 'oci' or
            node['role'] not in ('host', 'router') or not node['ipv6'] or node['forwarding'] or
            any(node['interfaces'].values()) or any(node.get(k) for k in
            ('svis', 'subinterfaces', 'port_channels', 'ospf', 'ospfv3', 'router_advertisements',
             'slaac', 'dhcpv6_clients', 'dhcpv6_server', 'dhcpv6_pd_client', 'dhcpv6_pd_server'))):
        raise ValueError('DHCPv6 relay/remote server requires a separate physical IPv6-only OCI node without other DHCP/RA/routing daemons.')
    if relay is not None:
        keys(relay, ('interface', 'upstream', 'server', 'advertise'), 'DHCPv6 relay')
        down, up = relay.get('interface'), relay.get('upstream')
        if (node['role'] != 'router' or not node['ipv6_forwarding'] or
                not isinstance(down, str) or not isinstance(up, str) or down == up or
                down not in node['ipv6'] or up not in node['ipv6'] or
                down not in node['interfaces'] or up not in node['interfaces'] or
                any(p in node['shutdown'] for p in (down, up)) or relay.get('advertise') is not True):
            raise ValueError('DHCPv6 relay needs two UP numbered physical router ports, IPv6 forwarding and explicit advertise:true.')
        value = relay.get('server')
        if not isinstance(value, str) or '%' in value:
            raise ValueError('DHCPv6 relay server must be an unscoped unicast IPv6 address.')
        address = ipaddress.IPv6Address(value); local = ipaddress.IPv6Interface(node['ipv6'][up])
        if (address not in local.network or address == local.ip or address == local.network.network_address or
                address.is_multicast or address.is_link_local or address.is_loopback or address.is_unspecified or address.ipv4_mapped):
            raise ValueError('DHCPv6 relay server must be remote unicast on the numbered upstream subnet.')
        relay['server'] = str(address)
    if server is not None:
        keys(server, ('interface', 'network', 'start', 'end', 'lease_seconds'), 'Remote DHCPv6 server')
        port = server.get('interface')
        if not isinstance(port, str) or port not in node['interfaces'] or port not in node['ipv6'] or port in node['shutdown']:
            raise ValueError('Remote DHCPv6 server requires an UP numbered physical interface.')
        if not all(isinstance(server.get(k), str) and '%' not in server[k] for k in ('network', 'start', 'end')):
            raise ValueError('Remote DHCPv6 network/start/end must be unscoped IPv6 text.')
        network = ipaddress.IPv6Network(server['network'], strict=True)
        start, end = (ipaddress.IPv6Address(server[k]) for k in ('start', 'end'))
        if (network.prefixlen != 64 or network.network_address.is_multicast or network.network_address.is_link_local or
                network.network_address.is_unspecified or network.network_address.is_loopback or network.network_address.ipv4_mapped or
                not network.network_address < start <= end < network.broadcast_address or int(end) - int(start) >= 256 or
                any(network.overlaps(ipaddress.IPv6Interface(v).network) for v in node['ipv6'].values())):
            raise ValueError('Remote DHCPv6 pool needs 1..256 usable addresses on a nonlocal unicast /64.')
        server.update(network=str(network), start=str(start), end=str(end))
        integer(server.setdefault('lease_seconds', 120), 120, 86400, 'DHCPv6 lease_seconds')


def validate_lab(spec):
    relays = [n for n in spec['nodes'] if n['dhcpv6_relay']]
    servers = [n for n in spec['nodes'] if n['dhcpv6_remote_server']]
    used = set()
    for node in relays:
        policy = node['dhcpv6_relay']
        down = ipaddress.IPv6Interface(node['ipv6'][policy['interface']])
        up = ipaddress.IPv6Interface(node['ipv6'][policy['upstream']])
        matches = [n for n in servers if str(ipaddress.IPv6Interface(n['ipv6'][n['dhcpv6_remote_server']['interface']]).ip) == policy['server']]
        if len(matches) != 1:
            raise ValueError('DHCPv6 relay requires exactly one declared remote server at its upstream address.')
        server = matches[0]; pool = server['dhcpv6_remote_server']
        if pool['network'] != str(down.network) or server['name'] in used:
            raise ValueError('This DHCPv6 profile pairs one remote pool/server with one relay client subnet.')
        if not any(r == {'destination': str(down.network), 'gateway': str(up.ip), 'interface': pool['interface']}
                   for r in server['ipv6_routes']):
            raise ValueError('Remote DHCPv6 server needs an explicit return route to the client subnet via the relay upstream address.')
        used.add(server['name'])
    if used != {n['name'] for n in servers}:
        raise ValueError('Remote DHCPv6 pool requires a matching declared relay.')


def config(node):
    relay, server = node['dhcpv6_relay'], node['dhcpv6_remote_server']
    lines = ['port=0', 'no-resolv', 'no-hosts', 'bind-interfaces', 'user=root', 'group=root',
             'log-facility=-', 'log-dhcp', 'pid-file=/run/dhcpv6-service.pid']
    if relay:
        local = str(ipaddress.IPv6Interface(node['ipv6'][relay['interface']]).ip)
        lines += ['interface=' + relay['interface'], 'interface=' + relay['upstream'],
                  'dhcp-relay=' + ','.join((local, relay['server'], relay['upstream']))]
    else:
        lines += ['interface=' + server['interface'], 'dhcp-option=option6:dns-server',
                  f'dhcp-range={server["start"]},{server["end"]},64,{server["lease_seconds"]}s',
                  'dhcp-leasefile=/run/dhcpv6-remote.leases']
    return '\n'.join(lines) + '\n'


def ra_config(node):
    relay = node['dhcpv6_relay']; port = relay['interface']
    prefix = ipaddress.IPv6Interface(node['ipv6'][port]).network
    # First-match prefix rules: advertise only the declared client prefix.
    return f'''router id 192.0.2.1;
log stderr all;
protocol device {{ scan time 1; }}
protocol radv relay_ra {{
  ipv6 {{ import none; export none; }};
  interface "{port}" {{
    min ra interval 3; max ra interval 5; default lifetime 15;
    managed yes; other config no;
    prefix {prefix} {{ onlink yes; autonomous no; valid lifetime 120; preferred lifetime 120; }};
    prefix ::/0 {{ skip yes; }};
  }};
}}
'''


def filename(node):
    return 'dhcpv6-relay.conf' if node['dhcpv6_relay'] else 'dhcpv6-remote.conf'


def prepare_files(bundle, node):
    if node['dhcpv6_relay'] or node['dhcpv6_remote_server']:
        (Path(bundle) / 'files' / filename(node)).write_text(config(node))
    if node['dhcpv6_relay']:
        (Path(bundle) / 'files/bird.conf').write_text(ra_config(node))


PROCESS_SCRIPT = r'''for proc in /proc/[0-9]*; do
    [ "$(/bin/busybox readlink "$proc/exe" 2>/dev/null)" = /usr/sbin/dnsmasq ] || continue
    if [ "$2" != all ]; then
        /bin/busybox tr '\000' '\n' < "$proc/cmdline" | /bin/busybox grep -Fx -- "$2" >/dev/null || continue
    fi
    pid=${proc##*/}
    if [ "$1" = stop ]; then
        [ "$pid" -gt 1 ] || exit 1
        /bin/busybox kill -TERM "$pid" || exit 1
    else echo "$pid"; fi
done
'''


def processes(manager, node, *, stop=False, managed=True):
    selector = '--conf-file=/lab/' + filename(node) if managed else 'all'
    return manager.crun('exec', node['name'], '/bin/sh', '-c', PROCESS_SCRIPT, 'dhcpv6-process',
                        'stop' if stop else 'list', selector, timeout=3).stdout.splitlines()


def start_one(manager, node):
    from .runtime import RuntimeFailure
    if processes(manager, node, managed=False):
        raise RuntimeFailure('Refusing to start DHCPv6 service while a dnsmasq process already exists.')
    args = ['--conf-file=/lab/' + filename(node)]
    manager.crun('exec', node['name'], BINARY, '--test', *args, timeout=3)
    manager.crun('exec', '--detach', node['name'], BINARY, '--keep-in-foreground', *args,
                 log=manager.directory / node['name'] / 'dhcpv6-service.log')
    deadline = time.monotonic() + 5
    while len(processes(manager, node)) != 1:
        if time.monotonic() >= deadline:
            raise RuntimeFailure(node['name'] + ': DHCPv6 service process unavailable.')
        time.sleep(.1)


def stop_one(manager, node):
    from .runtime import RuntimeFailure
    if processes(manager, node) != processes(manager, node, managed=False):
        raise RuntimeFailure('Unmanaged dnsmasq process detected; refusing DHCPv6 service stop.')
    processes(manager, node, stop=True)
    deadline = time.monotonic() + 5
    while processes(manager, node, managed=False):
        if time.monotonic() >= deadline: raise RuntimeFailure('DHCPv6 service did not stop.')
        time.sleep(.1)


def start_servers(manager):
    from .ipv6 import wait_addresses
    from .ospf import start_one as start_bird
    # RA has no UDP/547 listener. dnsmasq relay and allocation live on distinct nodes.
    for node in manager.state['spec']['nodes']:
        if node['dhcpv6_remote_server']: start_one(manager, node)
    for index, node in enumerate(manager.state['spec']['nodes']):
        if node['dhcpv6_relay']:
            wait_addresses(manager, index, node)
            start_one(manager, node)
            start_bird(manager, node)


def observe(manager, node):
    result = observe_config(manager, node['name'], '/lab/' + filename(node), config(node))
    if node['dhcpv6_relay']:
        from .ospf import read_cli
        ra = observe_config(manager, node['name'], '/lab/bird.conf', ra_config(node))
        result['ra_configuration'] = ra
        result['configuration_verified'] = result['configuration_verified'] and ra['configuration_verified']
        result['ra_protocol'] = read_cli(manager, node['name'], 'show protocols all relay_ra')
    return {**result, 'source': 'Managed dnsmasq config and optional BIRD RAdv control output',
            'note': 'File conformity does not prove loaded policy, lease acquisition or packet delivery. No DNS, PD, lease snapshot or authenticated relay-origin claim.'}


def drift(manager, node):
    if (node['dhcpv6_relay'] or node['dhcpv6_remote_server']) and not observe(manager, node)['configuration_verified']:
        return [node['name'] + ': DHCPv6 relay/remote server configuration differs or is unavailable']
    return []
