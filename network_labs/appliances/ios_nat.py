"""IOS NAT on a router micro-VM, for real: PAT, static NAT and NAT pools.

The IOS lines stay in the device's stored configuration (ios_store); this module compiles them into the NAT entries
the guest firewall already runs (iptables nat table: DNAT before routing, SNAT and masquerade after it), and the
network model reads the same entries. As on IOS, nothing is translated unless an outgoing port is marked
« ip nat outside » and some port « ip nat inside ».

- « ip nat inside source list N interface PORT overload »: the list's sources leave PORT with its address (masquerade).
- « ip nat inside source static L G »: L leaves every outside port as G, and G arriving there is sent to L. The router
  holds G on the outside port whose subnet contains it (as IOS answers ARP for it), so the next router reaches it.
- « ip nat pool P A B netmask M » with « ip nat inside source list N pool P [overload] »: the list's sources leave with
  the pool's addresses (overload: all with A, ports translated, as IOS fills the first address first; without
  overload: Linux picks one address of A..B per inside host). The router holds the pool's addresses (16 at most).

The sources of a list are its « permit » entries, in order; a « deny » entry stops the permits it covers entirely (a deny
that covers only part of a later permit is not honoured: the whole permit is translated).
"""
import ipaddress
import re

from . import ios_store

IP = r'\d+\.\d+\.\d+\.\d+'
SOURCE = re.compile(r'ip nat inside source list (\S+) (interface|pool) (\S+)( overload)?', re.IGNORECASE)
STATIC = re.compile(rf'ip nat inside source static ({IP}) ({IP})', re.IGNORECASE)
POOL = re.compile(rf'ip nat pool (\S+) ({IP}) ({IP}) (?:netmask ({IP})|prefix-length (\d+))', re.IGNORECASE)
POOL_LIMIT = 16


def _marked(node, side):
    lines = ios_store.config(node)['interfaces']
    return {port for port, entries in lines.items() if any(l.lower() == f'ip nat {side}' for l in entries)}


def _global(node):
    return [line.strip() for line in ios_store.config(node)['global']]


def pools(node):
    """{name: (first, last)} for the pools whose range is ascending and at most POOL_LIMIT addresses."""
    found = {}
    for line in _global(node):
        match = POOL.fullmatch(line)
        if match:
            first, last = ipaddress.IPv4Address(match[2]), ipaddress.IPv4Address(match[3])
            if first <= last and int(last) - int(first) < POOL_LIMIT:
                found[match[1]] = (first, last)
    return found


def _sources(node, name):
    """The networks list NAME translates: its permits, in order, minus those a deny before them covers."""
    denied, found = [], []
    for index, entry in enumerate((node.get('acls') or {}).get(name, []), 1):
        network = ipaddress.IPv4Network(entry['source'])
        if entry['action'] == 'deny':
            denied.append(network)
        elif not any(network.subnet_of(d) for d in denied):
            found.append((index, network))
    return found


def _active(node):
    """(outside ports, inside ports) when IOS would translate at all, else None."""
    if node.get('role') != 'router' or not node.get('cli_config'):
        return None
    outside, inside = _marked(node, 'outside'), _marked(node, 'inside')
    return (outside, inside) if outside and inside else None


def entries(node):
    """The NAT entries the router's IOS NAT lines give (empty when nothing would be translated)."""
    active = _active(node)
    if active is None:
        return []
    from .vendor_config import _port
    outside, _ = active
    found = []
    for number, line in enumerate(_global(node), 1):  # static first: a published host keeps its own public address
        match = STATIC.fullmatch(line)
        if match:
            for port in sorted(outside):
                found.append({'name': f'nat-static-{number}-{port}-in', 'type': 'dnat', 'in': port, 'protocol': 'any',
                              'destination': f'{match[2]}/32', 'to': match[1]})
                found.append({'name': f'nat-static-{number}-{port}-out', 'type': 'snat', 'out': port, 'protocol': 'any',
                              'source': f'{match[1]}/32', 'to': match[2]})
    ranges = pools(node)
    for line in _global(node):
        match = SOURCE.fullmatch(line)
        if not match:
            continue
        if match[2].lower() == 'interface':
            try:
                ports, target = [_port(node, match[3])], None
            except ValueError:
                continue
            if ports[0] not in outside:
                continue  # IOS translates only out of an outside port
        elif match[3] in ranges:
            first, last = ranges[match[3]]
            ports = sorted(outside)
            target = str(first) if match[4] or first == last else f'{first}-{last}'
        else:
            continue
        for index, network in _sources(node, match[1]):
            for port in ports:
                entry = {'name': f'nat-{match[1]}-{index}' + ('' if target is None else f'-{port}'), 'out': port, 'protocol': 'any',
                         **({} if network.prefixlen == 0 else {'source': str(network)})}
                found.append(dict(entry, type='masquerade') if target is None else dict(entry, type='snat', to=target))
    return found


def public_addresses(node):
    """{port: ['G/32', …]}: the static and pool addresses the router holds on an outside port, so it answers ARP for
    them there; only addresses inside that port's subnet, other than its own."""
    active = _active(node)
    if active is None:
        return {}
    outside, _ = active
    wanted = [ipaddress.IPv4Address(STATIC.fullmatch(l)[2]) for l in _global(node) if STATIC.fullmatch(l)]
    used = {SOURCE.fullmatch(l)[3] for l in _global(node) if SOURCE.fullmatch(l) and SOURCE.fullmatch(l)[2].lower() == 'pool'}
    for name, (first, last) in pools(node).items():
        if name in used:
            wanted += [ipaddress.IPv4Address(value) for value in range(int(first), int(last) + 1)]
    found = {}
    for port in sorted(outside):
        primary = node['interfaces'].get(port)
        if not primary:
            continue
        interface = ipaddress.IPv4Interface(primary)
        held = sorted({a for a in wanted if a in interface.network and a != interface.ip and a not in
                       (interface.network.network_address, interface.network.broadcast_address)})
        if held:
            found[port] = [f'{a}/32' for a in held]
    return found
