"""Strict portable manifest. Parsing and planning never modify the host."""
import copy
import hashlib
import ipaddress
import json
import re
from pathlib import Path

MIB = 1024 * 1024


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,31}', value):
        raise ValueError('Identifier: letter followed by up to 31 letters, digits, _ or -.')
    return value


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label}: integer {low}..{high} required.')
    return value


def keys(obj, allowed, label):
    if not isinstance(obj, dict) or set(obj) - set(allowed):
        raise ValueError(f'{label}: object with known fields required ({", ".join(allowed)}).')


def argv(value):
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v or '\0' in v for v in value):
        raise ValueError('Command must be a nonempty array of strings, not a shell string.')
    return value


def asset(value):
    if not isinstance(value, str) or not Path(value).is_absolute() or any(c in value for c in ',:\n\0'):
        raise ValueError('Asset requires an absolute path without overlay mount separators.')
    if Path(value).resolve() == Path('/'):
        raise ValueError('The host root cannot be an appliance asset.')
    return value


def validate(data):
    data = copy.deepcopy(data)
    keys(data, ('version', 'name', 'budget_mib', 'reserve_mib', 'nodes', 'links'), 'Lab')
    if type(data.get('version')) is not int or data['version'] not in (1, 2):
        raise ValueError('Native manifest version 1 or 2 required.')
    identifier(data.get('name'))
    budget = integer(data.setdefault('budget_mib', 2048), 128, 1048576, 'budget_mib')
    reserve = integer(data.setdefault('reserve_mib', 512), 64, budget, 'reserve_mib')
    if not isinstance(data.get('nodes'), list) or not data['nodes'] or len(data['nodes']) > 256:
        raise ValueError('1..256 nodes required.')
    names = set()
    for node_index, original in enumerate(data['nodes']):
        # In-memory callers can reuse the same dict in several nodes. Each node
        # must own its configuration, just as if it had been loaded from JSON.
        node = copy.deepcopy(original)
        data['nodes'][node_index] = node
        from .lan import LAN_FIELDS, addresses, validate_lan
        keys(node, ('name', 'runtime', 'role', 'rootfs', 'kernel', 'disk', 'memory_mib', 'command', 'startup', 'interfaces', 'gateway', *LAN_FIELDS), 'Node')
        name = identifier(node.get('name'))
        if name in names:
            raise ValueError('Duplicate node: ' + name)
        names.add(name)
        runtime = node.get('runtime')
        if runtime not in ('oci', 'firecracker'):
            raise ValueError(f'{runtime}: no native runtime adapter. Wasm uses its existing separate fabric.')
        role = node.setdefault('role', 'host')
        if role not in ('host', 'switch', 'router', 'firewall'):
            raise ValueError('Unknown role: ' + str(role))
        integer(node.setdefault('memory_mib', 64), 16, budget, 'memory_mib')
        interfaces = node.setdefault('interfaces', {})
        if not isinstance(interfaces, dict) or len(interfaces) > 64:
            raise ValueError('interfaces must be an object with at most 64 entries.')
        for name, address in interfaces.items():
            if not re.fullmatch(r'eth[0-9]{1,2}', name):
                raise ValueError('Native interface names: eth0..eth99.')
            if not isinstance(address, str):
                raise ValueError('Interface address must be a string.')
            if address:
                ipaddress.IPv4Interface(address)
        validate_lan(node)
        if node.get('gateway'):
            ipaddress.IPv4Address(node['gateway'])
            if not any(address and ipaddress.IPv4Address(node['gateway']) in ipaddress.IPv4Interface(address).network for address in addresses(node).values()):
                raise ValueError('Gateway must belong to a configured interface subnet.')
        if runtime == 'oci':
            asset(node.get('rootfs'))
            if 'kernel' in node or 'disk' in node:
                raise ValueError('OCI node cannot contain VM assets.')
            argv(node.setdefault('command', ['/bin/sleep', '2147483647']))
            startup = node.setdefault('startup', [])
            if not isinstance(startup, list):
                raise ValueError('startup must be a list of argv arrays.')
            for command in startup:
                argv(command)
            if role == 'firewall' and not startup:
                raise ValueError('Firewall requires explicit startup rules; no fake firewall or default pass-through.')
            if role == 'switch' and (any(interfaces.values()) or node.get('gateway')):
                raise ValueError('Switch is initially an unnumbered bridge; management IP requires explicit startup commands.')
        else:
            asset(node.get('kernel')); asset(node.get('disk'))
            if 'rootfs' in node or 'command' in node or 'startup' in node:
                raise ValueError('Firecracker uses kernel/disk, not OCI commands.')
            if role != 'host' or list(interfaces) != ['eth0'] or not interfaces['eth0']:
                raise ValueError('Firecracker initial adapter: host with one static IPv4 eth0 only.')
    links = data.setdefault('links', [])
    if not isinstance(links, list) or len(links) > 512:
        raise ValueError('links must be an array with at most 512 entries.')
    ports = {(n['name'], port) for n in data['nodes'] for port in n['interfaces']}
    used = set()
    switches = {n['name'] for n in data['nodes'] if n['role'] == 'switch'}
    parent = {name: name for name in switches}
    def root(name):
        while parent[name] != name:
            name = parent[name]
        return name
    for link in links:
        if not isinstance(link, list) or len(link) != 2:
            raise ValueError('Link requires exactly two [node, interface] endpoints.')
        for endpoint in link:
            if not isinstance(endpoint, list) or len(endpoint) != 2 or any(not isinstance(x, str) for x in endpoint):
                raise ValueError('Link endpoint must be [node, interface].')
            pair = tuple(endpoint)
            if pair not in ports or pair in used:
                raise ValueError('Unknown or already connected port: ' + str(pair))
            used.add(pair)
        if link[0][0] == link[1][0]:
            raise ValueError('Self links are not supported.')
        a, b = link[0][0], link[1][0]
        if a in switches and b in switches:
            if root(a) == root(b):
                raise ValueError('Layer-2 switch loop: initial bridge mode has STP disabled.')
            parent[root(a)] = root(b)
    if sum(n['memory_mib'] for n in data['nodes']) + reserve > budget:
        raise ValueError('Node memory allocations + GUI/host overhead reserve exceed lab budget.')
    return data


def load(path):
    return validate(json.loads(Path(path).read_text(encoding='utf-8')))


def prefix(spec):
    return 'nl' + hashlib.sha256(spec['name'].encode()).hexdigest()[:8]


def namespace(spec, index):
    return f'{prefix(spec)}n{index}'


def example(rootfs):
    return validate({'version': 1, 'name': 'micro-lan', 'nodes': [
        {'name': 'PC1', 'runtime': 'oci', 'rootfs': str(Path(rootfs).resolve()), 'interfaces': {'eth0': '192.0.2.10/24'}},
        {'name': 'SW1', 'runtime': 'oci', 'role': 'switch', 'rootfs': str(Path(rootfs).resolve()), 'interfaces': {'eth0': '', 'eth1': ''}},
        {'name': 'PC2', 'runtime': 'oci', 'rootfs': str(Path(rootfs).resolve()), 'interfaces': {'eth0': '192.0.2.20/24'}},
    ], 'links': [[['PC1', 'eth0'], ['SW1', 'eth0']], [['SW1', 'eth1'], ['PC2', 'eth0']]]})
