"""« show spanning-tree » on a switch micro-VM, as a Catalyst prints it for VLAN 1 (the guest bridge runs one classic
802.1D tree for the whole switch, the kernel's).

A running switch answers from its bridge (sysfs, through the agent: guest_startup.stp_listing). A stopped lab answers
from the topology: the same 802.1D election (lowest bridge ID: priority, then the bridge's MAC, which is fixed
(runtime.guest_mac); lowest root path cost; designated port per cable), so the port that will block is shown.
"""
from .native_models import port_names
from .vendor_config import ios_name, ios_short

STATES = {'0': 'BKN', '1': 'LIS', '2': 'LRN', '3': 'FWD', '4': 'BLK'}


def _mac(bridge_id):
    digits = bridge_id.split('.', 1)[1]
    return '.'.join(digits[i:i + 4] for i in range(0, 12, 4))


def from_guest(listing, node):
    """The view from the guest bridge's sysfs values."""
    bridge = listing['bridge']
    root_port = int(bridge['root_port'], 0)
    view = {'priority': int(bridge['priority']), 'address': _mac(bridge['bridge_id']),
            'root_priority': int(bridge['root_id'].split('.')[0], 16), 'root_address': _mac(bridge['root_id']),
            'root_cost': int(bridge['root_path_cost']),
            'timers': [int(bridge[k]) // 100 for k in ('hello_time', 'max_age', 'forward_delay')],  # centiseconds
            'ports': []}
    for port in node['interfaces']:
        values = listing.get(port)
        if not values or values.get('state') == '0':
            continue  # a shut or unconnected port is not in the tree
        number = int(values['port_no'], 0)
        role = 'Root' if number == root_port else 'Altn' if values['state'] == '4' else 'Desg'
        view['ports'].append({'port': port, 'role': role, 'state': STATES.get(values['state'], 'BKN'), 'cost': int(values['path_cost']),
                              'priority': int(values['priority']) * 16, 'number': number})
        if role == 'Root':
            view['root_port'] = port
    return view


def bridge_mac(node):
    """The switch guest bridge's MAC, Cisco style: its lowest port's (eth0's, the fixed MACs differ by the last byte)."""
    from .runtime import guest_mac
    digits = guest_mac(node['name'], min(node['interfaces'], key=lambda p: int(p[3:]))).replace(':', '')
    return '.'.join(digits[i:i + 4] for i in range(0, 12, 4))


def from_model(spec, name):
    """The view a stopped lab will converge to (802.1D on the switch cables)."""
    nodes = {n['name']: n for n in spec['nodes']}
    stp = {n: v for n, v in nodes.items() if v.get('role') == 'switch' and (v.get('spanning_tree') or {}).get('mode') == 'stp'}
    down = {n: set(v.get('shutdown') or []) for n, v in nodes.items()}
    cables = [(tuple(a), tuple(b)) for a, b in spec['links'] if a[1] not in down[a[0]] and b[1] not in down[b[0]]]
    ident = lambda n: (stp[n]['spanning_tree']['priority'], bridge_mac(stp[n]))
    cost = lambda n, p: ((stp[n]['spanning_tree'].get('ports') or {}).get(p) or {}).get('cost', 100)
    pid = lambda n, p: (((stp[n]['spanning_tree'].get('ports') or {}).get(p) or {}).get('priority', 128),
                        list(nodes[n]['interfaces']).index(p) + 1)  # the kernel numbers ports in the order they join
    trunk = [(a, b) for a, b in cables if a[0] in stp and b[0] in stp]
    # Component of NAME, its root, then root path costs (Dijkstra over the switch cables, cost of the receiving port).
    component, pending = set(), [name]
    while pending:
        item = pending.pop()
        if item not in component:
            component.add(item)
            pending += [b[0] for a, b in trunk if a[0] == item] + [a[0] for a, b in trunk if b[0] == item]
    root = min(component, key=ident)
    best = {root: (0, root, None)}  # switch -> (root cost, designated bridge towards the root, root port)
    changed = True
    while changed:
        changed = False
        for a, b in trunk + [(b, a) for a, b in trunk]:
            if a[0] in best:
                offer = (best[a[0]][0] + cost(b[0], b[1]), ident(a[0]), pid(a[0], a[1]))
                current = best.get(b[0])
                if b[0] != root and (current is None or offer < (current[0], current[1], current[3])):
                    best[b[0]] = (offer[0], offer[1], b[1], offer[2])
                    changed = True
    me = stp[name]['spanning_tree']
    view = {'priority': me['priority'], 'address': bridge_mac(stp[name]), 'root_priority': stp[root]['spanning_tree']['priority'],
            'root_address': bridge_mac(stp[root]), 'root_cost': best[name][0],
            'timers': [me['hello_time'], me['max_age'], me['forward_delay']],
            'ports': []}
    for port in nodes[name]['interfaces']:
        cable = next(((a, b) for a, b in cables if a == (name, port) or b == (name, port)), None)
        if cable is None:
            continue
        other = cable[1] if cable[0] == (name, port) else cable[0]
        if name != root and best[name][2] == port:
            role = 'Root'
        elif other[0] in stp and (best[other[0]][0], ident(other[0]), pid(*other)) < (best[name][0], ident(name), pid(name, port)):
            role = 'Altn'  # the other end is the cable's designated port
        else:
            role = 'Desg'
        view['ports'].append({'port': port, 'role': role, 'state': 'BLK' if role == 'Altn' else 'FWD', 'cost': cost(name, port),
                              'priority': pid(name, port)[0], 'number': pid(name, port)[1]})
        if role == 'Root':
            view['root_port'] = port
    return view


def render(node, view):
    names = port_names(node)
    hello, age, delay = view['timers']
    timers = f'Hello Time  {hello} sec  Max Age {age} sec  Forward Delay {delay} sec'
    lines = ['VLAN0001', '  Spanning tree enabled protocol ieee',
             f'  Root ID    Priority    {view["root_priority"] + 1}', f'             Address     {view["root_address"]}']
    if view.get('root_port'):
        port = view['root_port']
        number = next(p['number'] for p in view['ports'] if p['port'] == port)
        lines += [f'             Cost        {view["root_cost"]}', f'             Port        {number}({ios_name(names.get(port, port))})']
    else:
        lines.append('             This bridge is the root')
    lines += [f'             {timers}', '',
              f'  Bridge ID  Priority    {view["priority"] + 1}  (priority {view["priority"]} sys-id-ext 1)',
              f'             Address     {view["address"]}', f'             {timers}', '             Aging Time  300', '',
              f'{"Interface":<20}{"Role":<5}{"Sts":<4}{"Cost":<10}{"Prio.Nbr":<9}Type',
              f'{"-" * 19} {"-" * 4} {"-" * 3} {"-" * 9} {"-" * 8} {"-" * 32}']
    for p in view['ports']:
        number = f'{p["priority"]}.{p["number"]}'
        lines.append(f'{ios_short(ios_name(names.get(p["port"], p["port"]))):<20}{p["role"]:<5}{p["state"]:<4}{p["cost"]:<10}'
                     f'{number:<9}P2p')
    return '\n'.join(lines)
