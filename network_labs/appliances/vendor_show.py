"""Live 'show' commands for modelled nodes: the running node's Linux state printed in its vendor's format.

observe_guest() and observe_container() turn what a running node reports (the micro-VM agent's read-only
requests, or `ip -j` in a container) into one neutral observation; show() prints it in IOS, FortiOS, Junos
or RouterOS layout. Every value comes from the running Linux node; nothing is invented to fill a vendor
column the node does not have (counters, protocol timers, hardware state).
"""
import ipaddress
import re

from .native_models import port_names
from .guest_startup import learned as bird_route
from .vendor_config import dialect

COMMANDS = {
    'ios': ['show ip interface brief', 'show ip route', 'show vlan brief', 'show ip ospf neighbor', 'show access-lists',
            'show ip bgp summary', 'show ip bgp'],
    'fortios': ['get system interface', 'get router info routing-table all'],
    'junos': ['show interfaces terse', 'show route', 'show ospf neighbor', 'show bgp summary'],
    'routeros': ['/interface print', '/ip address print', '/ip route print'],
    'eos': ['show ip interface brief', 'show ip route', 'show vlan', 'show ip ospf neighbor', 'show ip bgp summary', 'show ip bgp'],
    'vrp': ['display ip interface brief', 'display ip routing-table', 'display vlan', 'display ospf peer brief', 'display bgp peer',
            'display bgp routing-table'],
    'panos': ['show interface all', 'show routing route'],
}
PROMPTS = {'ios': '{}#', 'fortios': '{} #', 'junos': 'admin@{}>', 'routeros': '[admin@{}] >', 'eos': '{}#',
           'vrp': '<{}>', 'panos': 'admin@{}>'}
SWITCH_ONLY = {'show vlan brief', 'show vlan', 'display vlan'}
OSPF_ONLY = {'show ip ospf neighbor', 'show ospf neighbor', 'display ospf peer brief'}
BGP_ONLY = {'show ip bgp summary', 'show ip bgp', 'show bgp summary', 'display bgp peer', 'display bgp routing-table'}


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
    bgp = None
    if node.get('bgp'):
        bgp = parse_bgp(query('bgp-show', state='summary'), query('bgp-show', state='routes'))
    ospf = None
    if node.get('ospf'):
        ospf = {'router_id': node['ospf']['router_id'], 'neighbors': parse_neighbors(query('ospf-show', state='neighbors')),
                'metrics': parse_ospf_metrics(query('ospf-show', state='routes'))}
    from .rip import process as rip_process
    rip = parse_rip_metrics(query('rip-show', state='routes')) if rip_process(node) else None
    routes = []
    for line in query('routes').splitlines():
        fields = line.split()
        if not fields or 'dev' not in fields:
            continue
        network = '0.0.0.0/0' if fields[0] == 'default' else str(ipaddress.IPv4Network(fields[0], strict=False))
        gateway = fields[fields.index('via') + 1] if 'via' in fields else None
        learned = bool(node.get('ospf') or node.get('bgp') or rip is not None) and bird_route(fields)
        if learned and gateway is None:
            continue  # BIRD's copy of a connected network: the kernel's own entry is shown
        route = {'network': network, 'gateway': gateway, 'port': fields[fields.index('dev') + 1]}
        if learned and rip is not None:
            route.update(protocol='rip', metric=rip.get(network))
        elif learned and bgp is not None:
            best = bgp['paths'].get(network, {})
            route.update(protocol='bgp', metric=0, path=best.get('path', ''))
        elif learned:
            route.update(protocol='ospf', metric=(ospf or {}).get('metrics', {}).get(network))
        routes.append(route)
    observation = {'node': node['name'], 'interfaces': _declared(node, interfaces), 'routes': routes, 'vlans': None, 'ospf': ospf,
                   'bgp': bgp}
    if node['role'] == 'switch':
        observation['vlans'] = _vlans(node, query('bridge-vlans'))
    return observation


def parse_bgp(summary, table):
    """FRR's 'show ip bgp summary json' and 'show ip bgp json': {asn, router_id, peers, paths}."""
    import json
    unicast = (json.loads(summary or '{}') or {}).get('ipv4Unicast', {})
    peers = [{'address': address, 'remote_as': peer.get('remoteAs'), 'state': peer.get('state', ''),
              'uptime': peer.get('peerUptime', ''), 'received': peer.get('pfxRcd', 0), 'sent': peer.get('pfxSnt', 0),
              'msg_in': peer.get('msgRcvd', 0), 'msg_out': peer.get('msgSent', 0)}
             for address, peer in sorted(unicast.get('peers', {}).items())]
    paths = {}
    for prefix, entries in ((json.loads(table or '{}') or {}).get('routes') or {}).items():
        best = next((e for e in entries if e.get('bestpath')), entries[0] if entries else None)
        if best:
            hop = (best.get('nexthops') or [{}])[0].get('ip', '0.0.0.0')
            paths[prefix] = {'path': best.get('path', ''), 'nexthop': hop, 'local': hop == '0.0.0.0', 'origin': best.get('origin', 'IGP')}
    return {'asn': unicast.get('as'), 'router_id': unicast.get('routerId'), 'peers': peers, 'paths': paths}


def parse_neighbors(text):
    """BIRD 'show ospf neighbors' rows: [{router_id, priority, state, dead, port, address}]."""
    rows = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 6 or not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', fields[0]) or not fields[1].isdigit():
            continue
        state, _, role = fields[2].partition('/')
        rows.append({'router_id': fields[0], 'priority': int(fields[1]), 'state': state, 'role': role,
                     'dead': float(fields[3]), 'port': fields[4], 'address': fields[5]})
    return rows


def parse_rip_metrics(text):
    """BIRD 'show route protocol rip4': {network: hop count as IOS shows it}. BIRD's metric includes the cost of the
    network itself (a neighbour's connected network comes in at 2), IOS counts the routers on the way (1): one less."""
    metrics = {}
    for line in text.splitlines():
        match = re.match(r'^(\d+\.\d+\.\d+\.\d+/\d+)\s+unicast \[rip4[^\]]*\][^(]*\((\d+)/(\d+)', line)
        if match:
            metrics[match[1]] = max(1, int(match[3]) - 1)
    return metrics


def parse_ospf_metrics(text):
    """BIRD 'show route protocol ospf4': {network: OSPF metric}."""
    metrics = {}
    for line in text.splitlines():
        match = re.match(r'^(\d+\.\d+\.\d+\.\d+/\d+)\s+unicast \[ospf4[^\]]*\][^(]*\((\d+)/(\d+)', line)
        if match:
            metrics[match[1]] = int(match[3])
    return metrics


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
    if dialect(node) == 'ios':
        from .vendor_config import ios_name
        names = {port: ios_name(label) for port, label in names.items()}  # IOS writes its ports in full

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
    return [r for r in observation['routes'] if r['gateway'] and r.get('protocol') not in ('ospf', 'bgp', 'rip')]


def _rip(observation):
    return [r for r in observation['routes'] if r.get('protocol') == 'rip']


def _ospf(observation):
    return [r for r in observation['routes'] if r.get('protocol') == 'ospf']


def _bgp(observation):
    return [r for r in observation['routes'] if r.get('protocol') == 'bgp']


def _metric(route):
    return route['metric'] if route.get('metric') is not None else '?'


def show(node, observation, command):
    """Vendor output for one command; ValueError lists the supported commands for anything else."""
    syntax = dialect(node)
    if syntax is None:
        raise ValueError('Pas de commandes constructeur pour ce nœud.')
    wanted = ' '.join(command.split()).lower()
    for known in COMMANDS[syntax]:
        if wanted == known or (syntax in ('ios', 'eos', 'vrp') and _abbreviates(wanted, known)):
            if known in SWITCH_ONLY and observation.get('vlans') is None:
                raise ValueError(known + ' : uniquement sur un switch.')
            if known in OSPF_ONLY and not observation.get('ospf'):
                raise ValueError(known + ' : OSPF n’est pas configuré sur ce routeur micro-VM.')
            if known in BGP_ONLY and not observation.get('bgp'):
                raise ValueError(known + ' : BGP n’est pas configuré sur ce routeur micro-VM.')
            return FORMATS[syntax, known](node, observation, _names(node))
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
        shut = interface['port'] in (node.get('shutdown') or [])
        status, protocol = ('administratively down', 'down') if shut else (state, state)
        lines.append(f'{name(interface["port"]):<23}{address:<16}YES {method:<6} {status:<22}{protocol}')
    return '\n'.join(lines)


def _ios_route(node, observation, name):
    lines = ['Codes: L - local, C - connected, S - static, R - RIP, O - OSPF, B - BGP, * - candidate default', '']
    default = next((r for r in observation['routes'] if r['network'] == '0.0.0.0/0'), None)
    lines.append(f'Gateway of last resort is {default["gateway"]} to network 0.0.0.0' if default
                 else 'Gateway of last resort is not set')
    lines.append('')
    for route in _static(observation):
        code = 'S*' if route['network'] == '0.0.0.0/0' else 'S '
        lines.append(f'{code}       {route["network"]} [1/0] via {route["gateway"]}, {name(route["port"])}')
    for route in _rip(observation):
        lines.append(f'R        {route["network"]} [120/{_metric(route)}] via {route["gateway"]}, {name(route["port"])}')
    for route in _ospf(observation):
        lines.append(f'O        {route["network"]} [110/{_metric(route)}] via {route["gateway"]}, {name(route["port"])}')
    for route in _bgp(observation):
        lines.append(f'B        {route["network"]} [20/0] via {route["gateway"]}, {name(route["port"])}')
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
    # As IOS: short port names, four per line; trunk ports are not listed (show interfaces trunk lists them).
    from .ios_store import vlan_name
    from .vendor_config import ios_short
    lines = [f'{"VLAN":<5}{"Name":<33}{"Status":<10}Ports', f'{"-" * 4} {"-" * 32} {"-" * 9} {"-" * 31}']
    for vid in sorted({*members, *(e['vlan'] for e in observation['vlans']), *(node.get('vlans') or [])}):
        label = vlan_name(node, vid) or ('default' if vid == 1 else f'VLAN{vid:04d}')
        ports = [ios_short(p) for p in members.get(vid, [])]
        rows = [', '.join(ports[i:i + 4]) for i in range(0, len(ports), 4)] or ['']
        lines.append(f'{vid:<5}{label:<33}{"active":<10}' + rows[0])
        lines += [' ' * 48 + row for row in rows[1:]]
    lines += [f'{vid:<5}{label:<33}act/unsup' for vid, label in
              ((1002, 'fddi-default'), (1003, 'token-ring-default'), (1004, 'fddinet-default'), (1005, 'trnet-default'))]
    return '\n'.join(line.rstrip() for line in lines)


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
    for route in _ospf(observation):
        entries.append((route['network'], f'*[OSPF/10] metric {_metric(route)}', f'>  to {route["gateway"]} via {name(route["port"])}.0'))
    for route in _bgp(observation):
        entries.append((route['network'], f'*[BGP/170] AS path: {route.get("path") or ""} I',
                        f'>  to {route["gateway"]} via {name(route["port"])}.0'))
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


def _eos_brief(node, observation, name):
    lines = [f'{"Interface":<16}{"IP Address":<20}{"Status":<12}{"Protocol":<10}MTU',
             f'{"-" * 15} {"-" * 19} {"-" * 11} {"-" * 9} {"-" * 5}']
    for interface in observation['interfaces']:
        if not interface['addresses']:
            continue
        state = 'up' if interface['up'] else 'down'
        lines.append(f'{name(interface["port"]):<16}{interface["addresses"][0]:<20}{state:<12}{state:<10}1500')
    return '\n'.join(lines)


def _eos_route(node, observation, name):
    lines = ['VRF: default', 'Codes: C - connected, S - static, O - OSPF, B E - BGP external', '']
    default = next((r for r in observation['routes'] if r['network'] == '0.0.0.0/0'), None)
    lines += [f'Gateway of last resort is {default["gateway"]} to network 0.0.0.0/0' if default
              else 'Gateway of last resort is not set', '']
    for route in _static(observation):
        lines.append(f' S        {route["network"]} [1/0] via {route["gateway"]}, {name(route["port"])}')
    for route in _ospf(observation):
        lines.append(f' O        {route["network"]} [110/{_metric(route)}] via {route["gateway"]}, {name(route["port"])}')
    for route in _bgp(observation):
        lines.append(f' B E      {route["network"]} [200/0] via {route["gateway"]}, {name(route["port"])}')
    for network, _, port in _connected(observation):
        lines.append(f' C        {network} is directly connected, {name(port)}')
    return '\n'.join(lines)


def _vlan_members(observation, name):
    tagged = {e['port'] for e in observation['vlans'] if not e['untagged']}
    members = {}
    for entry in observation['vlans']:
        if entry['untagged'] and entry['port'] not in tagged:
            members.setdefault(entry['vlan'], []).append(name(entry['port']))
        elif not entry['untagged']:
            members.setdefault(entry['vlan'], [])
    return members, tagged


def _eos_vlan(node, observation, name):
    members, tagged = _vlan_members(observation, name)
    lines = [f'{"VLAN":<5}{"Name":<33}{"Status":<10}Ports', f'{"-" * 4} {"-" * 32} {"-" * 9} {"-" * 24}']
    for vid in sorted(members):
        ports = members[vid] + [name(p) for p in sorted(tagged) if any(e['port'] == p and e['vlan'] == vid for e in observation['vlans'])]
        lines.append(f'{vid:<5}{"default" if vid == 1 else f"VLAN{vid:04d}":<33}{"active":<10}' + ', '.join(ports))
    return '\n'.join(lines)


def _vrp_brief(node, observation, name):
    lines = ['*down: administratively down', f'{"Interface":<26}{"IP Address/Mask":<20}{"Physical":<10}Protocol']
    for interface in observation['interfaces']:
        address = interface['addresses'][0] if interface['addresses'] else 'unassigned'
        state = 'up' if interface['up'] else 'down'
        lines.append(f'{name(interface["port"]):<26}{address:<20}{state:<10}{state}')
    return '\n'.join(lines)


def _vrp_route(node, observation, name):
    rows = [(network, 'Direct', 0, 0, address, port) for network, address, port in _connected(observation)]
    rows += [(r['network'], 'Static', 60, 0, r['gateway'], r['port']) for r in _static(observation)]
    rows += [(r['network'], 'OSPF', 10, _metric(r), r['gateway'], r['port']) for r in _ospf(observation)]
    rows += [(r['network'], 'EBGP', 255, 0, r['gateway'], r['port']) for r in _bgp(observation)]
    rows.sort(key=lambda row: ipaddress.IPv4Network(row[0]))
    lines = ['Route Flags: R - relay, D - download to fib', '-' * 62, 'Routing Tables: Public',
             f'         Destinations : {len(rows)}        Routes : {len(rows)}', '',
             f'{"Destination/Mask":<20}{"Proto":<8}{"Pre":<5}{"Cost":<6}{"Flags":<6}{"NextHop":<16}Interface']
    for network, proto, preference, cost, hop, port in rows:
        flags = 'D' if proto == 'Direct' else 'RD'
        lines.append(f'{network:<20}{proto:<8}{preference:<5}{cost:<6}{flags:<6}{hop:<16}{name(port)}')
    return '\n'.join(lines)


def _vrp_vlan(node, observation, name):
    members, tagged = _vlan_members(observation, name)
    lines = ['U: Up;  D: Down;  TG: Tagged;  UT: Untagged', f'{"VID":<5}{"Type":<10}Ports', '-' * 60]
    for vid in sorted(members):
        ports = [f'UT:{port}(U)' for port in members[vid]]
        ports += [f'TG:{name(p)}(U)' for p in sorted(tagged) if any(e['port'] == p and e['vlan'] == vid for e in observation['vlans'])]
        lines.append(f'{vid:<5}{"common":<10}' + '  '.join(ports))
    return '\n'.join(lines)


def _panos_interfaces(node, observation, name):
    lines = [f'{"name":<20}{"id":<6}{"speed/duplex/state":<24}mac address', '-' * 70]
    for index, interface in enumerate(observation['interfaces'], 16):
        state = 'up' if interface['up'] else 'down'
        lines.append(f'{name(interface["port"]):<20}{index:<6}{"ukn/ukn/" + state:<24}(non observée)')
    lines += ['', f'{"name":<20}{"id":<6}{"vsys":<6}{"zone":<20}address', '-' * 70]
    from .vendor_config import _zone
    for index, interface in enumerate(observation['interfaces'], 16):
        address = interface['addresses'][0] if interface['addresses'] else 'N/A'
        lines.append(f'{name(interface["port"]):<20}{index:<6}{"1":<6}{_zone(name(interface["port"])):<20}{address}')
    return '\n'.join(lines)


def _panos_route(node, observation, name):
    lines = ['flags: A:active, C:connect, S:static', '', 'VIRTUAL ROUTER: default (id 1)', '  ==========',
             f'{"destination":<20}{"nexthop":<17}{"metric":<8}{"flags":<7}interface']
    rows = [(network, address, 0, 'A C', port) for network, address, port in _connected(observation)]
    rows += [(r['network'], r['gateway'], 10, 'A S', r['port']) for r in _static(observation)]
    for network, hop, metric, flags, port in sorted(rows, key=lambda row: ipaddress.IPv4Network(row[0])):
        lines.append(f'{network:<20}{hop:<17}{metric:<8}{flags:<7}{name(port)}')
    lines.append(f'total routes shown: {len(rows)}')
    return '\n'.join(lines)


def _seconds(value):
    whole = int(value)
    return f'{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}'


def _ios_neighbors(node, observation, name):
    """Neighbors as the guest's BIRD reports them; a point-to-point link has no DR, shown as '-'."""
    lines = [f'{"Neighbor ID":<16}{"Pri":>3}   {"State":<16}{"Dead Time":<12}{"Address":<16}Interface']
    for row in observation['ospf']['neighbors']:
        role = {'PtP': '-', 'DR': 'DR', 'BDR': 'BDR', 'Other': 'DROTHER'}.get(row['role'], row['role'] or '-')
        state = f'{row["state"].upper()}/{role:>4}' if role == '-' else f'{row["state"].upper()}/{role}'
        lines.append(f'{row["router_id"]:<16}{row["priority"]:>3}   {state:<16}{_seconds(row["dead"]):<12}{row["address"]:<16}'
                     f'{name(row["port"])}')
    return '\n'.join(lines)


def _junos_neighbors(node, observation, name):
    lines = [f'{"Address":<17}{"Interface":<23}{"State":<10}{"ID":<17}{"Pri":>3}  Dead']
    for row in observation['ospf']['neighbors']:
        lines.append(f'{row["address"]:<17}{name(row["port"]) + ".0":<23}{row["state"]:<10}{row["router_id"]:<17}{row["priority"]:>3}'
                     f'{int(row["dead"]):>6}')
    return '\n'.join(lines)


def _vrp_peers(node, observation, name):
    lines = ['', f'\t OSPF Process {node["ospf"]["process_id"]} with Router ID {observation["ospf"]["router_id"]}',
             '\t\t  Peer Statistic Information', ' ' + '-' * 76,
             f' {"Area Id":<17}{"Interface":<33}{"Neighbor id":<17}State']
    for row in observation['ospf']['neighbors']:
        lines.append(f' {"0.0.0.0":<17}{name(row["port"]):<33}{row["router_id"]:<17}{row["state"]}')
    return '\n'.join(lines + [' ' + '-' * 76])


def _ios_access_lists(node, observation, name):
    """The lists the node runs (the guest's forward chain is read back at start and on each change); no hit counters."""
    from .vendor_config import _acl_address
    lines = []
    for list_name, entries in sorted((node.get('acls') or {}).items()):
        bound = [name(p) for p, n in sorted((node.get('acl_ports') or {}).items()) if n == list_name]
        lines.append(f'Extended IP access list {list_name}' + (f'    (in : {", ".join(bound)})' if bound else '    (non appliquée)'))
        for index, entry in enumerate(entries, 1):
            port = f' eq {entry["dport"]}' if 'dport' in entry else ''
            lines.append(f'    {index * 10} {entry["action"]} {entry["protocol"]} {_acl_address(entry["source"])} '
                         f'{_acl_address(entry["destination"])}{port}')
    return '\n'.join(lines) or 'Aucune liste d’accès.'


def _ios_bgp_summary(node, observation, name):
    bgp = observation['bgp']
    lines = [f'BGP router identifier {bgp["router_id"]}, local AS number {bgp["asn"]}', '',
             f'{"Neighbor":<16}{"V":<4}{"AS":>10} {"MsgRcvd":>8} {"MsgSent":>8} {"Up/Down":>9}  State/PfxRcd']
    for peer in bgp['peers']:
        state = str(peer['received']) if peer['state'] == 'Established' else peer['state']
        lines.append(f'{peer["address"]:<16}{"4":<4}{peer["remote_as"]:>10} {peer["msg_in"]:>8} {peer["msg_out"]:>8} '
                     f'{peer["uptime"] or "never":>9}  {state}')
    return '\n'.join(lines)


def _ios_bgp_table(node, observation, name):
    bgp = observation['bgp']
    lines = [f'BGP table version is {len(bgp["paths"])}, local router ID is {bgp["router_id"]}',
             'Status codes: * valid, > best', 'Origin codes: i - IGP, e - EGP, ? - incomplete', '',
             f'     {"Network":<20}{"Next Hop":<20}Path']
    for prefix, best in sorted(bgp['paths'].items(), key=lambda item: ipaddress.IPv4Network(item[0])):
        origin = {'IGP': 'i', 'EGP': 'e'}.get(best['origin'], '?')
        lines.append(f' *>  {prefix:<20}{best["nexthop"]:<20}{(best["path"] + " ") if best["path"] else ""}{origin}')
    return '\n'.join(lines)


def _junos_bgp_summary(node, observation, name):
    bgp = observation['bgp']
    up = sum(1 for p in bgp['peers'] if p['state'] == 'Established')
    lines = [f'Groups: 1 Peers: {len(bgp["peers"])} Down peers: {len(bgp["peers"]) - up}',
             f'{"Peer":<20}{"AS":>10}{"InPkt":>8}{"OutPkt":>8}  {"Last Up/Dwn":<12}State|#Active/Received/Accepted']
    for peer in bgp['peers']:
        state = (f'Establ\n  inet.0: {peer["received"]}/{peer["received"]}/{peer["received"]}' if peer['state'] == 'Established'
                 else peer['state'])
        lines.append(f'{peer["address"]:<20}{peer["remote_as"]:>10}{peer["msg_in"]:>8}{peer["msg_out"]:>8}  {peer["uptime"]:<12}{state}')
    return '\n'.join(lines)


def _vrp_bgp_peer(node, observation, name):
    bgp = observation['bgp']
    up = sum(1 for p in bgp['peers'] if p['state'] == 'Established')
    lines = ['', f' BGP local router ID : {bgp["router_id"]}', f' Local AS number : {bgp["asn"]}',
             f' Total number of peers : {len(bgp["peers"])}\t\t Peers in established state : {up}', '',
             f'  {"Peer":<16}{"V":<4}{"AS":>10}{"MsgRcvd":>9}{"MsgSent":>9}  {"Up/Down":<10}{"State":<13}PrefRcv']
    for peer in bgp['peers']:
        lines.append(f'  {peer["address"]:<16}{"4":<4}{peer["remote_as"]:>10}{peer["msg_in"]:>9}{peer["msg_out"]:>9}  '
                     f'{peer["uptime"]:<10}{peer["state"]:<13}{peer["received"]}')
    return '\n'.join(lines)


def _vrp_bgp_table(node, observation, name):
    bgp = observation['bgp']
    lines = ['', f' BGP Local router ID is {bgp["router_id"]}', ' Status codes: * - valid, > - best', '',
             f' Total Number of Routes: {len(bgp["paths"])}', f'      {"Network":<20}{"NextHop":<18}Path/Ogn']
    for prefix, best in sorted(bgp['paths'].items(), key=lambda item: ipaddress.IPv4Network(item[0])):
        origin = {'IGP': 'i', 'EGP': 'e'}.get(best['origin'], '?')
        lines.append(f' *>   {prefix:<20}{best["nexthop"]:<18}{(best["path"] + " ") if best["path"] else ""}{origin}')
    return '\n'.join(lines)


FORMATS = {
    ('ios', 'show ip bgp summary'): _ios_bgp_summary, ('ios', 'show ip bgp'): _ios_bgp_table,
    ('eos', 'show ip bgp summary'): _ios_bgp_summary, ('eos', 'show ip bgp'): _ios_bgp_table,
    ('junos', 'show bgp summary'): _junos_bgp_summary,
    ('vrp', 'display bgp peer'): _vrp_bgp_peer, ('vrp', 'display bgp routing-table'): _vrp_bgp_table,
    ('ios', 'show access-lists'): _ios_access_lists,
    ('ios', 'show ip ospf neighbor'): _ios_neighbors, ('eos', 'show ip ospf neighbor'): _ios_neighbors,
    ('junos', 'show ospf neighbor'): _junos_neighbors, ('vrp', 'display ospf peer brief'): _vrp_peers,
    ('ios', 'show ip interface brief'): _ios_brief, ('ios', 'show ip route'): _ios_route, ('ios', 'show vlan brief'): _ios_vlan,
    ('fortios', 'get system interface'): _forti_interfaces, ('fortios', 'get router info routing-table all'): _forti_routes,
    ('junos', 'show interfaces terse'): _junos_terse, ('junos', 'show route'): _junos_route,
    ('routeros', '/interface print'): _ros_interfaces, ('routeros', '/ip address print'): _ros_addresses,
    ('routeros', '/ip route print'): _ros_routes,
    ('eos', 'show ip interface brief'): _eos_brief, ('eos', 'show ip route'): _eos_route, ('eos', 'show vlan'): _eos_vlan,
    ('vrp', 'display ip interface brief'): _vrp_brief, ('vrp', 'display ip routing-table'): _vrp_route,
    ('vrp', 'display vlan'): _vrp_vlan,
    ('panos', 'show interface all'): _panos_interfaces, ('panos', 'show routing route'): _panos_route,
}


# ---- ping ----

# Each vendor's ping command, reduced to its destination; options beyond the destination are refused.
PING_SYNTAX = {'ios': r'ping (?:ip )?(\S+)', 'eos': r'ping (\S+)', 'vrp': r'ping (\S+)', 'junos': r'ping (\S+)(?: count 5)?',
               'fortios': r'execute ping (\S+)', 'routeros': r'/ping (?:address=)?(\S+?)(?: count=5)?',
               'panos': r'ping host (\S+)'}


PING_HELP = {'ios': 'ping A.B.C.D', 'eos': 'ping A.B.C.D', 'vrp': 'ping A.B.C.D', 'junos': 'ping A.B.C.D',
             'fortios': 'execute ping A.B.C.D', 'routeros': '/ping A.B.C.D', 'panos': 'ping host A.B.C.D'}


def ping_destination(node, command):
    """The IPv4 destination of a vendor ping command, None when the command is not a ping."""
    syntax = dialect(node)
    match = re.fullmatch(PING_SYNTAX.get(syntax, r'(?!)'), ' '.join(command.split()), re.IGNORECASE)
    return str(ipaddress.IPv4Address(match[1])) if match else None


def echo_reply(code, output):
    """One probe's outcome from busybox or iputils ping output: answered, TTL and time."""
    match = re.search(r'ttl=(\d+) time=([\d.]+) ms', output)
    if code or not match:
        return {'ok': False, 'ttl': None, 'time_ms': None}
    return {'ok': True, 'ttl': int(match[1]), 'time_ms': float(match[2])}


def _stats(replies):
    times = [r['time_ms'] for r in replies if r['ok']]
    received = len(times)
    return received, times


def ping_text(node, result):
    destination, replies = result['destination'], result['replies']
    received, times = _stats(replies)
    sent, loss = len(replies), round(100 * (len(replies) - received) / len(replies))
    low, mean, high = (min(times), sum(times) / len(times), max(times)) if times else (0, 0, 0)
    syntax = dialect(node)
    if syntax == 'ios':
        marks = ''.join('!' if r['ok'] else '.' for r in replies)
        lines = ['Type escape sequence to abort.', f'Sending {sent}, 64-byte ICMP Echos to {destination}, timeout is 1 seconds:', marks,
                 f'Success rate is {100 - loss} percent ({received}/{sent})'
                 + (f', round-trip min/avg/max = {max(1, round(low))}/{max(1, round(mean))}/{max(1, round(high))} ms' if times else '')]
        return '\n'.join(lines)
    if syntax == 'vrp':
        lines = [f'  PING {destination}: 56  data bytes, press CTRL_C to break']
        for reply in replies:
            lines.append(f'    Reply from {destination}: bytes=56 Sequence={reply["sequence"] + 1} ttl={reply["ttl"]} '
                         f'time={max(1, round(reply["time_ms"]))} ms' if reply['ok'] else '    Request time out')
        lines += ['', f'  --- {destination} ping statistics ---', f'    {sent} packet(s) transmitted', f'    {received} packet(s) received',
                  f'    {loss:.2f}% packet loss']
        if times:
            lines.append(f'    round-trip min/avg/max = {max(1, round(low))}/{max(1, round(mean))}/{max(1, round(high))} ms')
        return '\n'.join(lines)
    if syntax == 'routeros':
        lines = [f'  SEQ HOST{" " * 37}SIZE TTL TIME       STATUS']
        for reply in replies:
            if reply['ok']:
                lines.append(f'{reply["sequence"]:>5} {destination:<40}{56:>5} {reply["ttl"]:>3} {round(reply["time_ms"] * 1000)}us')
            else:
                lines.append(f'{reply["sequence"]:>5} {destination:<40}{"":>5} {"":>3} {"":<10} timeout')
        summary = f'    sent={sent} received={received} packet-loss={loss}%'
        if times:
            summary += f' min-rtt={round(low * 1000)}us avg-rtt={round(mean * 1000)}us max-rtt={round(high * 1000)}us'
        return '\n'.join(lines + [summary])
    # Junos, FortiOS, EOS and PAN-OS print the BSD/Linux layout.
    lines = [f'PING {destination} ({destination}): 56 data bytes']
    for reply in replies:
        lines.append(f'64 bytes from {destination}: icmp_seq={reply["sequence"]} ttl={reply["ttl"]} time={reply["time_ms"]:.3f} ms'
                     if reply['ok'] else f'Request timeout for icmp_seq {reply["sequence"]}')
    lines += ['', f'--- {destination} ping statistics ---', f'{sent} packets transmitted, {received} packets received, {loss}% packet loss']
    if times:
        lines.append(f'round-trip min/avg/max = {low:.3f}/{mean:.3f}/{high:.3f} ms')
    return '\n'.join(lines)


# ---- firewall sessions ----

def parse_sessions(text, limit=100):
    """Tracked IPv4 connections from /proc/net/nf_conntrack or `conntrack -L` lines: the original direction only."""
    sessions = []
    for line in text.splitlines():
        words = [w.strip('[]') for w in line.split()]  # conntrack writes flags as [ASSURED], [UNREPLIED]
        protocol = next((w for w in words if w in ('tcp', 'udp', 'icmp')), None)
        fields, replies = {}, {}
        for word in words:
            key, sign, value = word.partition('=')
            if sign and key not in fields:
                fields[key] = value  # the first src/dst/dport are the original direction
            elif sign and key not in replies:
                replies[key] = value  # the second ones, the reply direction (after NAT)
        if protocol is None or 'src' not in fields or 'dst' not in fields:
            continue
        state = next((w for w in words if w.isupper() and w.isalpha() and w not in ('ASSURED', 'UNREPLIED')), '')
        sessions.append({'protocol': protocol, 'source': fields['src'], 'destination': fields['dst'],
                         'port': fields.get('dport', ''), 'state': state or ('ASSURED' if 'ASSURED' in words else ''),
                         'replied': 'UNREPLIED' not in words, 'reply_source': replies.get('src', ''),
                         'reply_destination': replies.get('dst', '')})
        if len(sessions) >= limit:
            break
    return sessions
