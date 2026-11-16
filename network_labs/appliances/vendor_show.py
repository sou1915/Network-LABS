"""Live 'show' commands for modelled nodes: the running node's Linux state printed in its vendor's format.

observe_guest() and observe_container() turn what a running node reports (the micro-VM agent's read-only
requests, or `ip -j` in a container) into one neutral observation; show() prints it in IOS, FortiOS, Junos
or RouterOS layout. Every value comes from the running Linux node; nothing is invented to fill a vendor
column the node does not have (counters, protocol timers, hardware state).
"""
import ipaddress
import re

from .native_models import port_names
from .vendor_config import dialect

COMMANDS = {
    'ios': ['show ip interface brief', 'show ip route', 'show vlan brief'],
    'fortios': ['get system interface', 'get router info routing-table all'],
    'junos': ['show interfaces terse', 'show route'],
    'routeros': ['/interface print', '/ip address print', '/ip route print'],
}
PROMPTS = {'ios': '{}#', 'fortios': '{} #', 'junos': 'admin@{}>', 'routeros': '[admin@{}] >'}


# ---- observations ----

def observe_guest(query, node):
    """Neutral observation of a micro-VM through its agent; query(operation) returns the reply text."""
    interfaces, current = {}, None
    for line in query('addresses').splitlines():
        header = re.match(r'^\d+: ([^:@]+)(?:@[^:]+)?: <([^>]*)>', line)
        if header:
            current = header[1]
            interfaces[current] = {'port': current, 'up': 'UP' in header[2].split(','), 'addresses': []}
            continue
        fields = line.split()
        if fields[:1] == ['inet'] and current in interfaces:
            interfaces[current]['addresses'].append(str(ipaddress.IPv4Interface(fields[1])))
    routes = []
    for line in query('routes').splitlines():
        fields = line.split()
        if not fields or 'dev' not in fields:
            continue
        network = '0.0.0.0/0' if fields[0] == 'default' else str(ipaddress.IPv4Network(fields[0], strict=False))
        gateway = fields[fields.index('via') + 1] if 'via' in fields else None
        routes.append({'network': network, 'gateway': gateway, 'port': fields[fields.index('dev') + 1]})
    observation = {'node': node['name'], 'interfaces': _declared(node, interfaces), 'routes': routes, 'vlans': None}
    if node['role'] == 'switch':
        observation['vlans'] = _vlans(node, query('bridge-vlans'))
    return observation


def observe_container(observed, node):
    """Neutral observation of a container from lan.observe()'s `ip -j` addresses and routes."""
    interfaces = {}
    for item in observed['addresses']:
        addresses = [f'{a["local"]}/{a["prefixlen"]}' for a in item.get('addr_info', []) if a.get('family') == 'inet']
        interfaces[item['ifname']] = {'port': item['ifname'], 'up': 'UP' in item.get('flags', []), 'addresses': addresses}
    routes = []
    for route in observed['routes']:
        network = '0.0.0.0/0' if route['dst'] == 'default' else str(ipaddress.IPv4Network(route['dst'], strict=False))
        routes.append({'network': network, 'gateway': route.get('gateway'), 'port': route.get('dev')})
    return {'node': node['name'], 'interfaces': _declared(node, interfaces), 'routes': routes, 'vlans': None}


def _declared(node, interfaces):
    """Declared ports and their subinterfaces, in port order; loopback and bridge devices are not ports."""
    wanted = [*node['interfaces'], *node.get('subinterfaces', {})]
    return [interfaces.get(port, {'port': port, 'up': False, 'addresses': []}) for port in wanted]


def _vlans(node, listing):
    entries = []
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] in node['interfaces'] and fields[1].isdigit():
            entries.append({'port': fields[0], 'vlan': int(fields[1]), 'untagged': 'untagged' in fields[2:]})
    return entries


# ---- formatting ----

def _names(node):
    names = port_names(node)

    def name(port):
        parent, dot, vid = (port or '').partition('.')
        return names.get(parent, parent) + dot + vid if parent in names else (port or '')
    return name


def _connected(observation):
    """(network, address, port) for each address the node holds."""
    found = []
    for interface in observation['interfaces']:
        for address in interface['addresses']:
            value = ipaddress.IPv4Interface(address)
            found.append((str(value.network), str(value.ip), interface['port']))
    return found


def _static(observation):
    return [r for r in observation['routes'] if r['gateway']]


def show(node, observation, command):
    """Vendor output for one command; ValueError lists the supported commands for anything else."""
    syntax = dialect(node)
    if syntax is None:
        raise ValueError('Pas de commandes constructeur pour ce nœud.')
    wanted = ' '.join(command.split()).lower()
    for known in COMMANDS[syntax]:
        if wanted == known or (syntax == 'ios' and _abbreviates(wanted, known)):
            if known == 'show vlan brief' and observation.get('vlans') is None:
                raise ValueError('show vlan brief : uniquement sur un switch.')
            return FORMATS[known](node, observation, _names(node))
    raise ValueError('Commandes disponibles : ' + ', '.join(COMMANDS[syntax]) + '.')


def _abbreviates(wanted, known):
    """IOS-style abbreviations: 'sh ip int br' for 'show ip interface brief'."""
    words, full = wanted.split(), known.split()
    return len(words) == len(full) and all(target.startswith(word) for word, target in zip(words, full))


def _ios_brief(node, observation, name):
    lines = [f'{"Interface":<23}{"IP-Address":<16}OK? Method {"Status":<22}Protocol']
    for interface in observation['interfaces']:
        address = interface['addresses'][0].split('/')[0] if interface['addresses'] else 'unassigned'
        method = 'manual' if interface['addresses'] else 'unset'
        state = 'up' if interface['up'] else 'down'
        lines.append(f'{name(interface["port"]):<23}{address:<16}YES {method:<6} {state:<22}{state}')
    return '\n'.join(lines)


def _ios_route(node, observation, name):
    lines = ['Codes: L - local, C - connected, S - static, * - candidate default', '']
    default = next((r for r in observation['routes'] if r['network'] == '0.0.0.0/0'), None)
    lines.append(f'Gateway of last resort is {default["gateway"]} to network 0.0.0.0' if default
                 else 'Gateway of last resort is not set')
    lines.append('')
    for route in _static(observation):
        code = 'S*' if route['network'] == '0.0.0.0/0' else 'S '
        lines.append(f'{code}       {route["network"]} [1/0] via {route["gateway"]}, {name(route["port"])}')
    for network, address, port in _connected(observation):
        lines.append(f'C        {network} is directly connected, {name(port)}')
        lines.append(f'L        {address}/32 is directly connected, {name(port)}')
    return '\n'.join(lines)


def _ios_vlan(node, observation, name):
    tagged = {e['port'] for e in observation['vlans'] if not e['untagged']}
    members = {}
    for entry in observation['vlans']:
        if entry['untagged'] and entry['port'] not in tagged:
            members.setdefault(entry['vlan'], []).append(name(entry['port']))
    lines = [f'{"VLAN":<5}{"Name":<33}{"Status":<10}Ports', f'{"-" * 4} {"-" * 32} {"-" * 9} {"-" * 24}']
    for vid in sorted({*members, *(e['vlan'] for e in observation['vlans'])}):
        label = 'default' if vid == 1 else f'VLAN{vid:04d}'
        lines.append(f'{vid:<5}{label:<33}{"active":<10}' + ', '.join(members.get(vid, [])))
    if tagged:
        lines += ['', 'Trunks (802.1Q) : ' + ', '.join(sorted(name(p) for p in tagged))]
    return '\n'.join(lines)


def _forti_interfaces(node, observation, name):
    lines = []
    for interface in observation['interfaces']:
        address = ipaddress.IPv4Interface(interface['addresses'][0]) if interface['addresses'] else None
        ip = f'{address.ip} {address.netmask}' if address else '0.0.0.0 0.0.0.0'
        lines += [f'== [ {name(interface["port"])} ]',
                  f'name: {name(interface["port"])}   mode: static    ip: {ip}   status: {"up" if interface["up"] else "down"}']
    return '\n'.join(lines)


def _forti_routes(node, observation, name):
    lines = ['Codes: K - kernel, C - connected, S - static', '']
    for route in _static(observation):
        code = 'S*' if route['network'] == '0.0.0.0/0' else 'S '
        lines.append(f'{code}      {route["network"]} [10/0] via {route["gateway"]}, {name(route["port"])}')
    for network, _, port in _connected(observation):
        lines.append(f'C       {network} is directly connected, {name(port)}')
    return '\n'.join(lines)


def _junos_terse(node, observation, name):
    lines = [f'{"Interface":<24}{"Admin":<6}{"Link":<5}{"Proto":<9}Local']
    for interface in observation['interfaces']:
        state = 'up' if interface['up'] else 'down'
        lines.append(f'{name(interface["port"]):<24}{"up":<6}{state}')
        for address in interface['addresses']:
            lines.append(f'{name(interface["port"]) + ".0":<24}{"up":<6}{state:<5}{"inet":<9}{address}')
    return '\n'.join(lines)


def _junos_route(node, observation, name):
    entries = []
    for network, address, port in _connected(observation):
        entries += [(network, '*[Direct/0]', f'>  via {name(port)}.0'), (f'{address}/32', '*[Local/0]', f'   Local via {name(port)}.0')]
    for route in _static(observation):
        entries.append((route['network'], '*[Static/5]', f'>  to {route["gateway"]} via {name(route["port"])}.0'))
    entries.sort(key=lambda entry: ipaddress.IPv4Network(entry[0]))
    lines = [f'inet.0: {len(entries)} destinations, {len(entries)} routes ({len(entries)} active, 0 holddown, 0 hidden)',
             '+ = Active Route, - = Last Active, * = Both', '']
    for network, kind, via in entries:
        lines += [f'{network:<19}{kind}', f'{"":<20}{via}']
    return '\n'.join(lines)


def _ros_interfaces(node, observation, name):
    lines = ['Flags: D - dynamic, X - disabled, R - running', f' #     {"NAME":<20}TYPE']
    for index, interface in enumerate(observation['interfaces']):
        kind = 'vlan' if '.' in interface['port'] else 'ether'
        lines.append(f'{index:>2}  {"R" if interface["up"] else " "}  {name(interface["port"]):<20}{kind}')
    return '\n'.join(lines)


def _ros_addresses(node, observation, name):
    lines = ['Flags: X - disabled, I - invalid, D - dynamic', f' #   {"ADDRESS":<19}{"NETWORK":<16}INTERFACE']
    for index, (network, address, port) in enumerate(_connected(observation)):
        prefix = network.split('/')[1]
        lines.append(f'{index:>2}   {address + "/" + prefix:<19}{network.split("/")[0]:<16}{name(port)}')
    return '\n'.join(lines)


def _ros_routes(node, observation, name):
    lines = ['Flags: X - disabled, A - active, D - dynamic, C - connect, S - static',
             f' #      {"DST-ADDRESS":<19}{"PREF-SRC":<16}{"GATEWAY":<19}DISTANCE']
    rows = [('ADC', network, address, name(port), 0) for network, address, port in _connected(observation)]
    rows += [('A S', r['network'], '', r['gateway'], 1) for r in _static(observation)]
    for index, (flags, network, source, gateway, distance) in enumerate(rows):
        lines.append(f'{index:>2} {flags:<4} {network:<19}{source:<16}{gateway:<19}{distance:>8}')
    return '\n'.join(lines)


FORMATS = {
    'show ip interface brief': _ios_brief, 'show ip route': _ios_route, 'show vlan brief': _ios_vlan,
    'get system interface': _forti_interfaces, 'get router info routing-table all': _forti_routes,
    'show interfaces terse': _junos_terse, 'show route': _junos_route,
    '/interface print': _ros_interfaces, '/ip address print': _ros_addresses, '/ip route print': _ros_routes,
}
