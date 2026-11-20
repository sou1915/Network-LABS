"""EtherChannel on switch micro-VMs, as IOS configures it: « channel-group N mode active|passive » on ports bundles them
into Port-channel N, the guest's 802.3ad bond bondN, bridged as one port (one spanning tree port, both cables
forwarding). LACP runs for real between the guests (their cables pass every frame); the lab computes the same outcome
for a stopped lab and for « show etherchannel summary »: a bundle forms when every member's cable leads to the same
bundle on the other switch, whose members all lead back, and one side at least is active.
"""
import re

FLAGS = '''Flags:  D - down        P - bundled in port-channel
        I - stand-alone s - suspended
        H - Hot-standby (LACP only)
        R - Layer3      S - Layer2
        U - in use      N - not in use, no aggregation
        f - failed to allocate aggregator

        M - not in use, minimum links not met
        m - not in use, port not aggregated due to minimum links not met
        u - unsuitable for bundling
        w - waiting to be aggregated
        d - default port

        A - formed by Auto LAG
'''


def bundles(node):
    return node.get('port_channels') or {}


def number(bond):
    return int(bond[4:])


def bundle_of(node, port):
    """The bond PORT belongs to, or PORT itself."""
    return next((bond for bond, channel in bundles(node).items() if port in channel['members']), port)


def bridged_ports(node):
    """A switch's bridge ports: its physical ports outside a bundle, then its bonds in channel order."""
    members = {p for channel in bundles(node).values() for p in channel['members']}
    return [p for p in node['interfaces'] if p not in members] + sorted(bundles(node), key=number)


def partners(spec):
    """{(switch, bond): (other switch, its bond)} for the bundles that form."""
    nodes = {n['name']: n for n in spec['nodes']}
    far = {}
    for a, b in spec['links']:
        far[tuple(a)], far[tuple(b)] = tuple(b), tuple(a)
    found = {}
    for name, node in nodes.items():
        for bond, channel in bundles(node).items():
            ends = {far.get((name, member)) for member in channel['members']}
            if not channel['members'] or None in ends or len({end[0] for end in ends}) != 1:
                continue
            other = next(iter(ends))[0]
            theirs = {bundle_of(nodes[other], port) for _, port in ends}
            if len(theirs) != 1 or next(iter(theirs)) not in bundles(nodes[other]):
                continue
            remote = next(iter(theirs))
            back = {far.get((other, member)) for member in bundles(nodes[other])[remote]['members']}
            if back != {(name, member) for member in channel['members']}:
                continue
            if channel['mode'] == bundles(nodes[other])[remote]['mode'] == 'passive':
                continue  # LACP needs one active end
            found[(name, bond)] = (other, remote)
    return found


def ios_cost(node, bond):
    """IOS's STP cost of a port-channel: its members' speed added up (2 FastEthernet: 12, 2 GigabitEthernet: 3)."""
    from .spanning_tree import ios_cost as port_cost
    members = bundles(node)[bond]['members']
    single = port_cost(node, members[0]) if members else 19
    count = len(members)
    if single == 19:
        return 19 if count <= 1 else 12 if count == 2 else 9 if count <= 4 else 8
    if single == 4:
        return 4 if count <= 1 else 3 if count == 2 else 2
    return single


def summary(spec, node, guest=None):
    """« show etherchannel summary »: each group, its Port-channel and members with their flags. GUEST, when the switch
    runs: {bond: {'up': bool, 'bundled': {member, …}}} read from its bonds; otherwise the lab's own outcome."""
    from .native_models import port_names
    from .vendor_config import ios_name, ios_short
    names = port_names(node)
    formed = partners(spec)
    down = set(node.get('shutdown') or [])
    rows = []
    for bond in sorted(bundles(node), key=number):
        channel = bundles(node)[bond]
        if guest is not None:
            state = guest.get(bond, {'up': False, 'bundled': set()})
            in_use, bundled = state['up'] and bool(state['bundled']), state['bundled']
        else:
            in_use = (node['name'], bond) in formed and any(m not in down for m in channel['members'])
            bundled = {m for m in channel['members'] if m not in down} if in_use else set()
        members = []
        for member in channel['members']:
            flag = 'D' if member in down else 'P' if member in bundled else 'I'
            members.append(f'{ios_short(ios_name(names.get(member, member)))}({flag})')
        po = f'Po{number(bond)}(S{"U" if in_use else "D"})'
        rows.append(f'{number(bond):<7}{po:<16}{"LACP":<10}' + '  '.join(members))
    return '\n'.join([FLAGS, '', f'Number of channel-groups in use: {len(rows)}', f'Number of aggregators:           {len(rows)}', '',
                      'Group  Port-channel  Protocol    Ports',
                      '------+-------------+-----------+-----------------------------------------------', *rows])


def parse_bonds(text):
    """{bond: {'up', 'bundled'}} from BOND_SHOW (each /proc/net/bonding file after « == bondN »): a member is bundled when
    it is up and in the bond's active aggregator, with an LACP partner."""
    found = {}
    for block in re.split(r'^== ', text, flags=re.M)[1:]:
        lines = block.splitlines()
        bond = lines[0].strip()
        body = '\n'.join(lines[1:])
        active = re.search(r'Active Aggregator Info:\s*\n\s*Aggregator ID: (\d+)', body)
        partner = re.search(r'Active Aggregator Info:(?:.*\n)*?\s*Partner Mac Address: (\S+)', body)
        has_partner = bool(partner) and partner[1] != '00:00:00:00:00:00'
        bundled = set()
        for slave in re.split(r'^Slave Interface: ', body, flags=re.M)[1:]:
            name = slave.split('\n', 1)[0].strip()
            up = re.search(r'^MII Status: up', slave, re.M)
            aggregator = re.search(r'^Aggregator ID: (\d+)', slave, re.M)
            if up and aggregator and active and aggregator[1] == active[1] and has_partner:
                bundled.add(name)
        found[bond] = {'up': bool(re.search(r'^MII Status: up', body, re.M)), 'bundled': bundled}
    return found
