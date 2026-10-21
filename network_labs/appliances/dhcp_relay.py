"""One IPv4 client LAN relayed by a real in-container dnsmasq process."""
import ipaddress
from pathlib import Path

from .spec import keys
from .service_config import observe_config

BINARY = '/usr/sbin/dnsmasq'


def validate_relay(node):
    policy = node.setdefault('dhcp_relay', None)
    if policy is None:
        return
    from .lan import addresses
    keys(policy, ('interface', 'server', 'upstream_interface'), 'DHCP relay')
    if node['runtime'] != 'oci' or node['role'] not in ('router', 'switch') or node.get('switch_backend', 'linux') != 'linux' or not node['forwarding']:
        raise ValueError('DHCP relay requires a forwarding OCI router or Linux L3 switch.')
    if any((node.get('startup'), node.get('dhcp_server'), node.get('dhcp_clients'), node.get('dns_server'),
            node.get('lldp'), (node.get('dhcp_snooping') or {}).get('enabled'), node.get('arp_inspection'), node.get('ip_source_guard'))):
        raise ValueError('Initial DHCP relay profile excludes untracked startup, DHCP/DNS/LLDP services and DHCP snooping/ARP/IP source guards on the relay node.')
    local = addresses(node)
    interfaces = [policy.get('interface'), policy.get('upstream_interface')]
    if any(not isinstance(name, str) or not local.get(name) or name in node['shutdown'] or
           (node['role'] == 'switch' and name not in node['svis']) for name in interfaces) or interfaces[0] == interfaces[1]:
        raise ValueError('DHCP relay needs two distinct UP static routed interfaces or SVIs.')
    client, upstream = (ipaddress.IPv4Interface(local[name]) for name in interfaces)
    if client.network.overlaps(upstream.network):
        raise ValueError('DHCP relay client and upstream networks must be disjoint.')
    if client.network.prefixlen >= 31 or client.ip in (client.network.network_address, client.network.broadcast_address) or client.ip.is_multicast or client.ip.is_loopback or client.ip.is_unspecified:
        raise ValueError('DHCP relay client address must be usable on a broadcast IPv4 subnet.')
    if not isinstance(policy.get('server'), str):
        raise ValueError('DHCP relay server must be IPv4 text.')
    server = ipaddress.IPv4Address(policy['server'])
    if server.is_unspecified or server.is_multicast or server.is_loopback or server not in upstream.network or (upstream.network.prefixlen < 31 and server in (upstream.network.network_address, upstream.network.broadcast_address)) or any(value and server == ipaddress.IPv4Interface(value).ip for value in local.values()):
        raise ValueError('DHCP relay server must be a usable on-link upstream peer.')
    policy['server'] = str(server)


def server_config(node):
    from .lan import addresses
    policy = node['dhcp_relay']
    local = str(ipaddress.IPv4Interface(addresses(node)[policy['interface']]).ip)
    return '\n'.join(['port=0', 'no-resolv', 'no-hosts', 'bind-interfaces',
        'interface=' + policy['interface'], 'interface=' + policy['upstream_interface'],
        f'dhcp-relay={local},{policy["server"]},{policy["upstream_interface"]}',
        'pid-file=/run/dhcp-relay.pid', 'user=root', 'group=root', 'log-facility=-', 'log-dhcp']) + '\n'


def prepare_files(bundle, node):
    if node.get('dhcp_relay') is not None:
        (Path(bundle) / 'files' / 'dhcp-relay.conf').write_text(server_config(node))


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if node.get('dhcp_relay') is not None:
            for args in (('--test',), ('--keep-in-foreground',)):
                command = ['exec'] + ([] if args == ('--test',) else ['--detach'])
                manager.crun(*command, node['name'], BINARY, *args, '--conf-file=/lab/dhcp-relay.conf',
                             log=manager.directory / node['name'] / 'dhcp-relay.log')


def observe(manager, index, node):
    result = observe_config(manager, node['name'], '/lab/dhcp-relay.conf', server_config(node))
    sockets = manager.ns(index, 'ss', '-H', '-lun', '( sport = :67 )', check=False)
    return {**result, 'source': 'Managed dnsmasq relay config and actual UDP socket snapshot',
            'policy': node['dhcp_relay'], 'listener_snapshot': sockets.stdout.splitlines() if sockets.returncode == 0 else None,
            'note': 'File/socket observations do not prove a running/loaded relay or successful leases. No DHCPv6, Option 82, multi-pool or live service adapter.'}
