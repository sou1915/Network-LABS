"""Single-/64 DHCPv6 PD from Kea to BusyBox, with finite downstream gateway and SLAAC."""
import ipaddress
import json
from pathlib import Path
import time

from .spec import keys, integer
from .service_config import observe_config

KEA = '/usr/sbin/kea-dhcp6'
HOOK = '/usr/lib/network-labs/dhcpv6-pd-hook'
LAN_SETTINGS = {'disable_ipv6': 0, 'accept_ra': 0, 'autoconf': 0, 'forwarding': 1, 'accept_dad': 1}


def rootfs_assets(kea=None, hook=None):
    from .dns_rootfs import assets
    result = []
    if kea is not None:
        result += assets(kea, destination=KEA, identity='Kea DHCPv6 server', version_args=('-h',),
                         version_check=lambda r: r.returncode in (0, 1) and 'kea-dhcp6' in r.stdout + r.stderr and
                         '-c' in r.stdout + r.stderr and '-t' in r.stdout + r.stderr)
    if hook is not None:
        result += assets(hook, destination=HOOK, identity='Network LABS DHCPv6 PD hook 1',
                         version_check=lambda r: r.returncode == 0 and r.stdout == 'Network LABS DHCPv6 PD hook 1\n')
    return result


def validate_node(node):
    client = node.setdefault('dhcpv6_pd_client', None)
    server = node.setdefault('dhcpv6_pd_server', None)
    if client is None and server is None: return
    if (client is not None and server is not None or node['runtime'] != 'oci' or node['role'] != 'router' or
            not node['ipv6_forwarding'] or node['forwarding'] or any(node['interfaces'].values()) or
            any(node.get(k) for k in ('ospf', 'ospfv3', 'svis', 'subinterfaces', 'port_channels', 'dhcpv6_server',
                                    'dhcpv6_clients', 'dhcpv6_relay', 'dhcpv6_remote_server', 'router_advertisements', 'slaac'))):
        raise ValueError('PD requires separate physical IPv6-only OCI routers without other managed routing/DHCP/RA services.')
    policy = client or server
    keys(policy, ('interface', 'downstream', 'server', 'prefix', 'lease_seconds', 'advertise') if client else
                 ('interface', 'prefix', 'lease_seconds'), 'DHCPv6 PD')
    port = policy.get('interface')
    if not isinstance(port, str) or port not in node['interfaces'] or port not in node['ipv6'] or port in node['shutdown']:
        raise ValueError('PD requires an UP statically numbered physical upstream/server port.')
    value = policy.get('prefix')
    if not isinstance(value, str) or '%' in value: raise ValueError('PD prefix requires unscoped IPv6 /64 text.')
    network = ipaddress.IPv6Network(value, strict=True); ip = network.network_address
    if network.prefixlen != 64 or ip.is_unspecified or ip.is_link_local or ip.is_loopback or ip.is_multicast or ip.ipv4_mapped:
        raise ValueError('Initial PD profile delegates one usable unicast /64 only.')
    if any(network.overlaps(ipaddress.IPv6Interface(v).network) for v in node['ipv6'].values()):
        raise ValueError('Delegated PD subnet must not overlap static interface networks.')
    policy['prefix'] = str(network)
    integer(policy.setdefault('lease_seconds', 30), 10, 3600, 'PD lease_seconds')
    if client:
        lan = client.get('downstream')
        if (not isinstance(lan, str) or lan not in node['interfaces'] or lan == port or lan in node['ipv6'] or
                lan in node['shutdown'] or client.get('advertise') is not True):
            raise ValueError('PD needs a distinct UP unnumbered downstream physical port and advertise:true.')
        address = client.get('server')
        if not isinstance(address, str) or '%' in address: raise ValueError('PD server requires unscoped IPv6 text.')
        address = ipaddress.IPv6Address(address); local = ipaddress.IPv6Interface(node['ipv6'][port])
        if (address not in local.network or address in (local.ip, local.network.network_address) or address.is_multicast or
                address.is_link_local or address.is_loopback or address.is_unspecified or address.ipv4_mapped):
            raise ValueError('PD server must be remote unicast on the upstream /64.')
        client['server'] = str(address)


def validate_lab(spec):
    clients = [n for n in spec['nodes'] if n['dhcpv6_pd_client']]
    servers = [n for n in spec['nodes'] if n['dhcpv6_pd_server']]
    if not clients and not servers: return
    if len(clients) != 1 or len(servers) != 1: raise ValueError('PD profile requires exactly one requesting and one delegating router.')
    if any(n.get(k) for n in spec['nodes'] for k in ('dhcpv6_clients', 'dhcpv6_server', 'dhcpv6_relay',
            'dhcpv6_remote_server', 'router_advertisements', 'ospfv3')):
        raise ValueError('PD/DHCPv6 and other managed RA/routing service coexistence is outside this profile.')
    client, server = clients[0], servers[0]; cp, sp = client['dhcpv6_pd_client'], server['dhcpv6_pd_server']
    upstream = ipaddress.IPv6Interface(client['ipv6'][cp['interface']])
    address = ipaddress.IPv6Interface(server['ipv6'][sp['interface']])
    if cp['server'] != str(address.ip) or upstream.network != address.network or cp['prefix'] != sp['prefix'] or cp['lease_seconds'] != sp['lease_seconds']:
        raise ValueError('PD client/server address, prefix and lifetime declarations must match on one upstream subnet.')
    network = ipaddress.IPv6Network(cp['prefix'])
    if any(network.overlaps(ipaddress.IPv6Interface(v).network) for n in spec['nodes'] for v in n['ipv6'].values()):
        raise ValueError('PD pool overlaps a statically numbered subnet in the lab.')
    if {'destination': cp['prefix'], 'gateway': str(upstream.ip), 'interface': sp['interface']} not in server['ipv6_routes']:
        raise ValueError('PD delegating router requires an explicit static return route to the pool via the requesting router.')


def gateway(node):
    policy = node['dhcpv6_pd_client']
    return str(ipaddress.IPv6Interface(str(ipaddress.IPv6Network(policy['prefix']).network_address + 1) + '/64'))


def hook_policy(node):
    p = node['dhcpv6_pd_client']
    return f'{p["downstream"]}\n{p["prefix"]}\n{p["lease_seconds"]}\n'


def ra_config(node):
    p = node['dhcpv6_pd_client']; lan = p['downstream']
    return '\n'.join(['port=0', 'no-resolv', 'no-hosts', 'bind-interfaces', 'enable-ra',
                      'user=root', 'group=root', 'log-facility=-', 'dhcp-option=option6:dns-server',
                      'interface=' + lan, 'dhcp-range=::,constructor:' + lan + ',ra-only,64,2h',
                      'ra-param=' + lan + ',5,15', 'pid-file=/run/pd-ra.pid']) + '\n'


def server_config(node):
    p = node['dhcpv6_pd_server']; network = ipaddress.IPv6Network(p['prefix']); lease = p['lease_seconds']
    data = {'interfaces-config': {'interfaces': [p['interface']]}, 'data-directory': '/run/kea',
            'lease-database': {'type': 'memfile', 'persist': False, 'lfc-interval': 0},
            'server-id': {'type': 'EN', 'enterprise-id': 2495, 'identifier': '4e4c504431', 'persist': False},
            'valid-lifetime': lease, 'preferred-lifetime': lease, 'renew-timer': max(1, lease // 3),
            'rebind-timer': max(2, lease * 2 // 3), 'multi-threading': {'enable-multi-threading': False},
            'subnet6': [{'id': 1, 'subnet': str(ipaddress.IPv6Interface(node['ipv6'][p['interface']]).network),
                         'interface': p['interface'], 'pd-pools': [{'prefix': str(network.network_address),
                         'prefix-len': 64, 'delegated-len': 64}]}],
            'loggers': [{'name': 'kea-dhcp6', 'severity': 'INFO', 'output_options': [{'output': 'stdout'}]}]}
    return json.dumps({'Dhcp6': data}, indent=2, sort_keys=True) + '\n'


def prepare_files(bundle, node):
    root = Path(bundle) / 'files'
    if node['dhcpv6_pd_client']:
        (root / 'dhcpv6-pd.policy').write_text(hook_policy(node))
        (root / 'pd-ra.conf').write_text(ra_config(node))
    if node['dhcpv6_pd_server']: (root / 'kea-pd.json').write_text(server_config(node))


def configure(manager, index, node):
    if not node['dhcpv6_pd_client']: return
    port = node['dhcpv6_pd_client']['downstream']
    for key, value in LAN_SETTINGS.items():
        manager.ns(index, 'sysctl', '-w', 'net/ipv6/conf/' + port + '/' + key + '=' + str(value))


PROCESS_SCRIPT = r'''for proc in /proc/[0-9]*; do
    [ "$(/bin/busybox readlink "$proc/exe" 2>/dev/null)" = /usr/sbin/kea-dhcp6 ] || continue
    if [ "$2" != all ]; then
    /bin/busybox tr '\000' '\n' < "$proc/cmdline" | /bin/busybox awk '
        previous == "-c" { config = $0 } { previous = $0 }
        END { exit !(config == "/etc/kea/kea-dhcp6.conf") }' || continue
    fi
    pid=${proc##*/}
    if [ "$1" = stop ]; then [ "$pid" -gt 1 ] || exit 1; /bin/busybox kill -TERM "$pid" || exit 1
    else echo "$pid"; fi
done
'''


def processes(manager, node, *, stop=False, managed=True):
    return manager.crun('exec', node['name'], '/bin/sh', '-c', PROCESS_SCRIPT, 'pd-server',
                        'stop' if stop else 'list', 'managed' if managed else 'all', timeout=3).stdout.splitlines()


def stop_server(manager, node):
    from .runtime import RuntimeFailure
    if processes(manager, node) != processes(manager, node, managed=False):
        raise RuntimeFailure('Unmanaged Kea process detected; refusing PD server stop.')
    processes(manager, node, stop=True)
    deadline = time.monotonic() + 5
    while processes(manager, node):
        if time.monotonic() >= deadline: raise RuntimeFailure('Managed PD server did not stop.')
        time.sleep(.1)


def start_server(manager, node):
    from .runtime import RuntimeFailure
    if processes(manager, node, managed=False): raise RuntimeFailure('Refusing PD startup while a Kea process already exists.')
    manager.crun('exec', node['name'], '/bin/busybox', 'mkdir', '-p', '/run/kea', timeout=3)
    command = ['/bin/busybox', 'env', 'KEA_PIDFILE_DIR=/run/kea', 'KEA_LOCKFILE_DIR=/run/kea', KEA]
    result = manager.crun('exec', node['name'], *command, '-t', '/etc/kea/kea-dhcp6.conf', timeout=5, check=False)
    if result.returncode:
        evidence = manager.crun('exec', node['name'], '/bin/busybox', 'ls', '-l', '/etc/kea/kea-dhcp6.conf', check=False, timeout=3)
        raise RuntimeFailure('Kea PD config check failed: ' + (result.stderr or result.stdout)[-3000:] + '; file: ' + evidence.stdout + evidence.stderr)
    manager.crun('exec', '--detach', node['name'], *command, '-c', '/etc/kea/kea-dhcp6.conf',
                 log=manager.directory / node['name'] / 'pd-server.log')
    deadline = time.monotonic() + 5
    while len(processes(manager, node)) != 1:
        if time.monotonic() >= deadline: raise RuntimeFailure('Managed PD server process unavailable.')
        time.sleep(.1)


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if node['dhcpv6_pd_server']: start_server(manager, node)
    for node in manager.state['spec']['nodes']:
        if not node['dhcpv6_pd_client']: continue
        p = node['dhcpv6_pd_client']
        applets = manager.crun('exec', node['name'], '/bin/busybox', '--list', timeout=3).stdout.splitlines()
        if 'udhcpc6' not in applets:
            from .runtime import RuntimeFailure
            raise RuntimeFailure('PD requires a rootfs BusyBox with udhcpc6.')
        manager.crun('exec', node['name'], '/usr/sbin/dnsmasq', '--test', '--conf-file=/lab/pd-ra.conf', timeout=3)
        manager.crun('exec', '--detach', node['name'], '/usr/sbin/dnsmasq', '--keep-in-foreground',
                     '--conf-file=/lab/pd-ra.conf', log=manager.directory / node['name'] / 'pd-ra.log')
        manager.crun('exec', '--detach', node['name'], '/bin/busybox', 'udhcpc6', '-f', '-i', p['interface'],
                     '-s', HOOK, '-p', '/run/pd-client.pid', '-d', '-r', 'no', '-o', '-t', '3', '-T', '1', '-A', '3',
                     log=manager.directory / node['name'] / 'pd-client.log')


def dynamic_address(node, port, value, address):
    p = node.get('dhcpv6_pd_client')
    if not p or port != p['downstream'] or value != gateway(node): return False
    valid, preferred = address.get('valid_life_time'), address.get('preferred_life_time')
    return type(valid) is int and type(preferred) is int and 0 < valid <= p['lease_seconds'] and 0 <= preferred <= valid


def observe(manager, node):
    p = node['dhcpv6_pd_client']
    files = {'/lab/dhcpv6-pd.policy': hook_policy(node), '/lab/pd-ra.conf': ra_config(node)} if p else {'/lab/kea-pd.json': server_config(node)}
    evidence = {path: observe_config(manager, node['name'], path, content) for path, content in files.items()}
    return {'configuration_verified': all(v['configuration_verified'] for v in evidence.values()), 'files': evidence,
            'source': 'Managed PD configuration files; actual addresses/routes observed separately',
            'note': 'No lease or origin claim from file conformity. One allowed /64; no saved DUID, lease or learned address.'}


def drift(manager, index, node):
    if not node['dhcpv6_pd_client'] and not node['dhcpv6_pd_server']: return []
    errors = []
    if not observe(manager, node)['configuration_verified']: errors.append(node['name'] + ': PD configuration differs or unavailable')
    if node['dhcpv6_pd_client']:
        for key, value in LAN_SETTINGS.items():
            actual = manager.ns(index, 'sysctl', '-n', 'net/ipv6/conf/' + node['dhcpv6_pd_client']['downstream'] + '/' + key, timeout=3).stdout.strip()
            if actual != str(value): errors.append(node['name'] + ': PD downstream ' + key + ' differs')
    return errors
