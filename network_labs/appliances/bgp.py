"""eBGP on router micro-VMs, run by FRR (zebra and bgpd) in the guest.

A router declares 'bgp': {'asn', 'router_id', 'neighbors': [{'address', 'remote_as'}], 'networks': [prefix]}.
Neighbours are directly connected peers in another AS (eBGP, one hop). As on a real router, a network is only
announced when the routing table holds it exactly (FRR's import check): a connected network or a static route.
The guest agent writes FRR's configuration itself from the typed process (guest_process), byte-identical to
config() here, which startup and save read back.
"""
import ipaddress

MAX_NEIGHBORS = 4
MAX_NETWORKS = 8


def validate(node):
    policy = node.setdefault('bgp', None)
    if policy is None:
        return
    if node.get('runtime') != 'firecracker' or node.get('role') != 'router':
        raise ValueError('BGP runs on micro-VM routers.')
    if node.get('ospf'):
        raise ValueError('OSPF and BGP on the same router: not yet (OSPF moves to FRR first).')
    if not isinstance(policy, dict) or set(policy) - {'asn', 'router_id', 'neighbors', 'networks'}:
        raise ValueError('BGP: asn, router_id, neighbors, networks.')
    asn = policy.get('asn')
    if type(asn) is not int or not 1 <= asn <= 4294967295:
        raise ValueError('BGP AS number: 1..4294967295.')
    if not isinstance(policy.get('router_id'), str):
        raise ValueError('BGP router-id: IPv4 text.')
    policy['router_id'] = str(ipaddress.IPv4Address(policy['router_id']))
    neighbors = policy.setdefault('neighbors', [])
    if not isinstance(neighbors, list) or not 1 <= len(neighbors) <= MAX_NEIGHBORS:
        raise ValueError(f'BGP: 1..{MAX_NEIGHBORS} neighbours.')
    local = [ipaddress.IPv4Interface(a) for a in node['interfaces'].values() if a]
    seen = set()
    for neighbor in neighbors:
        if not isinstance(neighbor, dict) or set(neighbor) != {'address', 'remote_as'}:
            raise ValueError('BGP neighbour: address and remote_as.')
        address = ipaddress.IPv4Address(neighbor['address'])
        if type(neighbor['remote_as']) is not int or not 1 <= neighbor['remote_as'] <= 4294967295:
            raise ValueError('BGP neighbour remote-as: 1..4294967295.')
        if neighbor['remote_as'] == asn:
            raise ValueError('BGP: neighbours in another AS (eBGP); iBGP is not available yet.')
        if not any(address in i.network and address != i.ip for i in local):
            raise ValueError(f'BGP neighbour {address}: on a directly connected network of this router (one hop).')
        if address in seen:
            raise ValueError(f'BGP neighbour {address} declared twice.')
        seen.add(address)
        neighbor['address'] = str(address)
    networks = policy.setdefault('networks', [])
    if not isinstance(networks, list) or len(networks) > MAX_NETWORKS:
        raise ValueError(f'BGP: at most {MAX_NETWORKS} networks.')
    policy['networks'] = sorted({str(ipaddress.IPv4Network(n, strict=True)) for n in networks},
                                key=lambda n: ipaddress.IPv4Network(n))
    policy['neighbors'] = sorted(neighbors, key=lambda n: ipaddress.IPv4Address(n['address']))


def config(node):
    """FRR's bgpd.conf for NODE, exactly as the guest agent writes it."""
    policy = node['bgp']
    lines = ['frr defaults traditional', f'router bgp {policy["asn"]}', f' bgp router-id {policy["router_id"]}',
             ' no bgp ebgp-requires-policy']
    for neighbor in policy['neighbors']:
        address = neighbor['address']
        lines += [f' neighbor {address} remote-as {neighbor["remote_as"]}', f' neighbor {address} timers 3 9',
                  f' neighbor {address} timers connect 5']
    lines.append(' address-family ipv4 unicast')
    lines += [f'  network {network}' for network in policy['networks']]
    lines.append(' exit-address-family')
    return '\n'.join(lines) + '\n'


def guest_process(node):
    policy = node['bgp']
    return {'asn': policy['asn'], 'router_id': policy['router_id'],
            'neighbors': [{'address': n['address'], 'remote_as': n['remote_as']} for n in policy['neighbors']],
            'networks': list(policy['networks'])}


def announced(node, static=()):
    """The networks NODE really announces: those its routing table holds exactly (connected or static)."""
    held = {ipaddress.IPv4Interface(a).network for a in node['interfaces'].values() if a}
    held |= {ipaddress.IPv4Network(n) for n in static}
    return [n for n in node['bgp']['networks'] if ipaddress.IPv4Network(n) in held]
