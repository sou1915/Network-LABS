"""IOS-style extended access lists on router micro-VMs, applied inbound on interfaces.

A router declares named lists ('acls': {name: [entry, ...]}) and binds them to ports ('acl_ports': {port: name}).
Each entry is {'action': 'permit' | 'deny', 'protocol': 'ip' | 'icmp' | 'tcp' | 'udp', 'source': prefix,
'destination': prefix, 'dport': optional port}. Like IOS, a packet entering a port with a list is checked
entry by entry, the first match decides, and the end of the list denies. Lists are stateless: replies are
checked by the list on the port they enter. Only inbound lists are offered: in the guest's forward chain an
inbound permit would otherwise skip an outbound list on the exit port.

The guest runs them in its iptables forward chain (the image needs --with-firewall): policy() compiles them
into the same policy schema the firewall guests use, and evaluate() gives the network model the same answer.
"""
import ipaddress
import re

PROTOCOLS = ('ip', 'icmp', 'tcp', 'udp')
MAX_ENTRIES = 32


def validate(node):
    lists, ports = node.setdefault('acls', {}), node.setdefault('acl_ports', {})
    if not isinstance(lists, dict) or not isinstance(ports, dict):
        raise ValueError('acls and acl_ports must be objects.')
    if (lists or ports) and (node.get('role') != 'router' or node.get('runtime') != 'firecracker'):
        raise ValueError('Access lists apply to micro-VM routers.')
    for name, entries in lists.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', name):
            raise ValueError('Access list name: a letter, then up to 31 letters, digits, _ or -.')
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            raise ValueError(f'Access list {name}: at most {MAX_ENTRIES} entries.')
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - {'action', 'protocol', 'source', 'destination', 'dport'}:
                raise ValueError(f'Access list {name}: entry fields are action, protocol, source, destination, dport.')
            if entry.get('action') not in ('permit', 'deny') or entry.setdefault('protocol', 'ip') not in PROTOCOLS:
                raise ValueError(f'Access list {name}: permit or deny, protocol ip, icmp, tcp or udp.')
            for field in ('source', 'destination'):
                entry[field] = str(ipaddress.IPv4Network(entry.setdefault(field, '0.0.0.0/0'), strict=False))
            if 'dport' in entry and (type(entry['dport']) is not int or not 1 <= entry['dport'] <= 65535
                                     or entry['protocol'] not in ('tcp', 'udp')):
                raise ValueError(f'Access list {name}: a port needs tcp or udp and 1..65535.')
    for port, name in ports.items():
        if port not in node['interfaces'] or name not in lists:
            raise ValueError('ip access-group: a declared port and an existing access list.')


def policy(node):
    """The forward-chain policy that runs NODE's lists: per bound port, its entries, then the implicit deny."""
    rules = []
    for port, name in sorted((node.get('acl_ports') or {}).items()):
        for index, entry in enumerate(node['acls'][name], 1):
            rule = {'name': f'{name}-{index}', 'in': port, 'action': 'accept' if entry['action'] == 'permit' else 'drop',
                    'protocol': 'any' if entry['protocol'] == 'ip' else entry['protocol']}
            for field in ('source', 'destination'):
                if entry[field] != '0.0.0.0/0':
                    rule[field] = entry[field]
            if 'dport' in entry:
                rule['dport'] = entry['dport']
            rules.append(rule)
        rules.append({'name': f'{name}-implicit-deny', 'in': port, 'action': 'drop', 'protocol': 'any'})
    return {'default': 'accept', 'stateful': False, 'rules': rules, 'nat': []}


def evaluate(node, port, packet):
    """'permit' or 'deny' for PACKET {source, destination, protocol, dport?} entering NODE on PORT."""
    name = (node.get('acl_ports') or {}).get(port)
    if name is None:
        return 'permit'
    source, destination = ipaddress.IPv4Address(packet['source']), ipaddress.IPv4Address(packet['destination'])
    for entry in node['acls'][name]:
        if entry['protocol'] not in ('ip', packet['protocol']):
            continue
        if source not in ipaddress.IPv4Network(entry['source']) or destination not in ipaddress.IPv4Network(entry['destination']):
            continue
        if 'dport' in entry and entry['dport'] != packet.get('dport'):
            continue
        return entry['action']
    return 'deny'
