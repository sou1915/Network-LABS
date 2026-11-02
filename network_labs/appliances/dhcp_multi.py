"""Remote DHCPv4 pools served by one real dnsmasq process."""
import copy
import ipaddress
from pathlib import Path

from .spec import keys
from .service_config import observe_config


def validate_pools(node):
    policy = node.setdefault('dhcp_pools', None)
    if policy is None:
        return
    from .lan import addresses
    from .dhcp import validate_server
    keys(policy, ('interface', 'pools'), 'DHCP pools')
    if node['runtime'] != 'oci' or node['role'] not in ('host', 'router', 'firewall'):
        raise ValueError('DHCP pools require an OCI host/router/firewall.')
    if any(node.get(key) for key in ('dhcp_server', 'dhcp_clients', 'dhcp_relay', 'dns_server', 'lldp', 'startup')):
        raise ValueError('DHCP pools cannot share a node with other managed services or untracked startup.')
    interface = policy.get('interface')
    if not isinstance(interface, str) or not addresses(node).get(interface) or interface in node['shutdown']:
        raise ValueError('DHCP pools require an UP numbered server interface.')
    pools = policy.get('pools')
    if not isinstance(pools, list) or not 1 <= len(pools) <= 16:
        raise ValueError('DHCP pools require 1..16 remote pools.')
    networks, macs = [], set()
    for pool in pools:
        keys(pool, ('network', 'start', 'end', 'router', 'dns', 'lease_seconds', 'reservations'), 'DHCP pool')
        if not isinstance(pool.get('network'), str):
            raise ValueError('Each DHCP pool requires an explicit network.')
        if any(not isinstance(pool.get(key, ''), str) for key in ('start', 'end', 'router')):
            raise ValueError('DHCP pool addresses must be IPv4 text.')
        temporary = copy.deepcopy(node)
        temporary['dhcp_server'] = {**pool, 'interface': interface}
        validate_server(temporary)
        normalized = temporary['dhcp_server']; normalized.pop('interface')
        pool.clear(); pool.update(normalized)
        network = ipaddress.IPv4Network(pool['network'])
        if any(network.overlaps(existing) for existing in networks) or any(
                address and network.overlaps(ipaddress.IPv4Interface(address).network)
                for address in addresses(node).values()):
            raise ValueError('DHCP pools must be disjoint remote networks, separate from all server interfaces.')
        networks.append(network)
        for reservation in pool['reservations']:
            if reservation['mac'] in macs:
                raise ValueError('DHCP pool reservations require globally unique MAC addresses.')
            macs.add(reservation['mac'])
        for value in pool['dns']:
            if not isinstance(value, str):
                raise ValueError('DHCP pool DNS addresses must be IPv4 text.')
            address = ipaddress.IPv4Address(value)
            if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_reserved:
                raise ValueError('DHCP pool DNS requires usable unicast addresses.')
    policy['pools'] = sorted(pools, key=lambda pool: int(ipaddress.IPv4Network(pool['network']).network_address))


def server_config(node):
    policy = node['dhcp_pools']
    lines = ['port=0', 'no-resolv', 'no-hosts', 'bind-interfaces', 'interface=' + policy['interface'],
             'pid-file=/run/dhcp-pools.pid', 'dhcp-leasefile=/run/dhcp-pools.leases',
             'user=root', 'group=root', 'log-facility=-', 'log-dhcp']
    maximum = sum(int(ipaddress.IPv4Address(p['end'])) - int(ipaddress.IPv4Address(p['start'])) + 1 + len(p['reservations']) for p in policy['pools'])
    lines.append('dhcp-lease-max=' + str(maximum))
    for index, pool in enumerate(policy['pools']):
        tag = 'pool' + str(index)
        mask = ipaddress.IPv4Network(pool['network']).netmask
        lines.append(f'dhcp-range=set:{tag},{pool["start"]},{pool["end"]},{mask},{pool["lease_seconds"]}s')
        for option, values in (('router', [pool['router']] if pool['router'] else []), ('dns-server', pool['dns'])):
            lines.append(f'dhcp-option=tag:{tag},option:{option}' + (',' + ','.join(values) if values else ''))
        for reservation in pool['reservations']:
            lines.append(f'dhcp-host={reservation["mac"]},{reservation["address"]}')
    return '\n'.join(lines) + '\n'


def prepare_files(bundle, node):
    if node.get('dhcp_pools') is not None:
        (Path(bundle) / 'files' / 'dhcp-pools.conf').write_text(server_config(node))


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if node.get('dhcp_pools') is not None:
            manager.crun('exec', node['name'], '/usr/sbin/dnsmasq', '--test', '--conf-file=/lab/dhcp-pools.conf', timeout=3)
            manager.crun('exec', '--detach', node['name'], '/usr/sbin/dnsmasq', '--keep-in-foreground', '--conf-file=/lab/dhcp-pools.conf',
                         log=manager.directory / node['name'] / 'dhcp-pools.log')


def observe(manager, index, node):
    result = observe_config(manager, node['name'], '/lab/dhcp-pools.conf', server_config(node))
    sockets = manager.ns(index, 'ss', '-H', '-lun', '( sport = :67 )', check=False)
    return {**result, 'source': 'Managed dnsmasq DHCP pools config and actual UDP socket snapshot',
            'policy': node['dhcp_pools'], 'listener_snapshot': sockets.stdout.splitlines() if sockets.returncode == 0 else None,
            'note': 'Declared pools/file/socket evidence, not observed leases or proof of loaded policy. No DHCPv6/HA or live pool editor.'}
