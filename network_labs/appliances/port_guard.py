"""Port security and BPDU guard on switch micro-VMs, as IOS has them: the lines typed on an access port
(« switchport port-security », « … maximum N », « … violation shutdown|restrict|protect », « … mac-address sticky »,
« … mac-address H.H.H », « spanning-tree bpduguard enable ») make its policy. In the guest, the agent's port guard
watches the port's frames: an address beyond the maximum is a violation (shutdown: the port goes err-disabled, its link
down, until « shutdown » then « no shutdown »; restrict and protect: nothing is forwarded to that address any more); a
BPDU on a BPDU-guard port err-disables it. A stopped lab gets the same outcome from the cables (the micro-VMs' MAC
addresses are fixed).
"""
import re

MODES = {'shutdown': 's', 'restrict': 'r', 'protect': 'p'}
MAXIMUM = 8  # secure addresses per port in the lab (IOS allows more; a lab port has one PC, or a few behind a hub)
MAC = re.compile(r'([0-9a-f]{4})\.([0-9a-f]{4})\.([0-9a-f]{4})')


def cisco(mac):
    digits = mac.replace(':', '').replace('.', '').lower()
    return '.'.join(digits[i:i + 4] for i in range(0, 12, 4))


def policy(node):
    """{port: {'secure', 'maximum', 'violation', 'sticky', 'macs', 'bpduguard'}} for a switch micro-VM's guarded ports."""
    if node.get('role') != 'switch' or node.get('runtime') != 'firecracker' or not node.get('cli_config'):
        return {}
    from . import ios_store
    from .etherchannel import bundle_of
    found = {}
    for port, typed in ios_store.config(node)['interfaces'].items():
        if port not in node['interfaces'] or bundle_of(node, port) != port:
            continue
        lines = [' '.join(line.lower().split()) for line in typed]
        secure = 'switchport port-security' in lines
        bpdu = 'spanning-tree bpduguard enable' in lines
        if not secure and not bpdu:
            continue
        maximum = next((int(l.split()[-1]) for l in lines if re.fullmatch(r'switchport port-security maximum \d+', l)), 1)
        violation = next((l.split()[-1] for l in lines if re.fullmatch(r'switchport port-security violation \w+', l)), 'shutdown')
        macs = [cisco(match[0]) for l in lines
                if l.startswith('switchport port-security mac-address') and (match := MAC.search(l))]
        found[port] = {'secure': secure, 'maximum': maximum, 'violation': violation, 'bpduguard': bpdu, 'macs': macs,
                       'sticky': 'switchport port-security mac-address sticky' in lines}
    return found


def arguments(node):
    """The agent's --port-guard arguments, one per guarded port (PORT/MAX/MODE/STICKY/BPDU/VID/MACS)."""
    from .guest_startup import vlan_plan
    filtering = vlan_plan(node) is not None
    found = []
    for port, settings in sorted(policy(node).items(), key=lambda item: int(item[0][3:])):
        vid = ((node.get('switchports') or {}).get(port) or {}).get('vlan', 1) if filtering else 0
        macs = '+'.join(m.replace('.', '') for m in settings['macs'][:settings['maximum']]) or '-'
        found.append('/'.join([port, str(settings['maximum'] if settings['secure'] else 0),
                               MODES[settings['violation']] if settings['secure'] else 'n', 'y' if settings['sticky'] else 'n',
                               'y' if settings['bpduguard'] else 'n', str(vid), macs]))
    return found


def parse(text):
    """{port: {'state', 'reason', 'violations', 'last', 'macs': [(mac, kind)]}} from PORT_GUARD_SHOW; kind s (configured),
    k (learned, sticky), d (learned)."""
    found = {}
    for block in re.split(r'^== ', text, flags=re.M)[1:]:
        lines = block.splitlines()
        values = dict(line.split(' ', 1) for line in lines[1:] if ' ' in line)
        found[lines[0].strip()] = {
            'state': values.get('state', 'secure'), 'reason': values.get('reason', '-'), 'violations': int(values.get('violations', 0)),
            'last': None if values.get('last', '-') == '-' else cisco(values['last']),
            'macs': [(cisco(item.split(':')[0]), item.split(':')[1]) for item in values.get('macs', '').split() if ':' in item]}
    return found


def model(spec):
    """The same states for a stopped lab, from the cables: {(switch, port): state} as parse() gives them, plus 'blocked',
    the addresses restrict / protect keep out."""
    from .runtime import guest_mac
    nodes = {n['name']: n for n in spec['nodes']}
    far = {}
    for a, b in spec['links']:
        far[tuple(a)], far[tuple(b)] = tuple(b), tuple(a)
    found = {}
    for name, node in nodes.items():
        for port, settings in policy(node).items():
            state = {'state': 'secure', 'reason': '-', 'violations': 0, 'last': None, 'blocked': set(),
                     'macs': [(m, 's') for m in settings['macs']]}
            found[(name, port)] = state
            other = far.get((name, port))
            if other is None or port in (node.get('shutdown') or []):
                continue
            behind = _addresses(nodes, far, name, other)
            if settings['bpduguard'] and nodes[other[0]].get('role') == 'switch' \
                    and (nodes[other[0]].get('spanning_tree') or {}).get('mode') == 'stp':
                state.update(state='err-disabled', reason='bpduguard')
                continue
            if not settings['secure']:
                continue
            for mac in (cisco(guest_mac(*end)) for end in behind):
                if mac in (m for m, _ in state['macs']):
                    continue
                if len(state['macs']) < settings['maximum']:
                    state['macs'].append((mac, 'k' if settings['sticky'] else 'd'))
                    continue
                state['violations'] += 1
                state['last'] = mac
                if settings['violation'] == 'shutdown':
                    state.update(state='err-disabled', reason='psecure-violation')
                    break
                state['blocked'].add(mac)
    return found


def _addresses(nodes, far, switch, end):
    """The (node, port) ends whose frames arrive on SWITCH's port through cable end END: the device there, or, behind
    another switch, every device that switch reaches without coming back."""
    node = nodes[end[0]]
    if node.get('role') != 'switch':
        sub = (node.get('subinterfaces') or {})
        return [(end[0], sub[end[1]]['parent'] if end[1] in sub else end[1])]
    found, seen, pending = [], {switch}, [end[0]]
    while pending:
        here = pending.pop()
        if here in seen:
            continue
        seen.add(here)
        for port in nodes[here]['interfaces']:
            there = far.get((here, port))
            if there is None or there[0] in seen:
                continue
            if nodes[there[0]].get('role') == 'switch':
                pending.append(there[0])
            else:
                found.append(there)
    return found


def disabled_ends(spec):
    """{(node, port)} that carry nothing in a stopped lab: err-disabled guarded ports, and the device cables restrict /
    protect keep out."""
    from .runtime import guest_mac
    found = set()
    far = {}
    for a, b in spec['links']:
        far[tuple(a)], far[tuple(b)] = tuple(b), tuple(a)
    for (switch, port), state in model(spec).items():
        if state['state'] == 'err-disabled':
            found.add((switch, port))
        elif state['blocked']:
            other = far.get((switch, port))
            if other and cisco(guest_mac(*other)) in state['blocked']:
                found.add((switch, port))
    return found


# ---- IOS output ----

def _short(node, port):
    from .native_models import port_names
    from .vendor_config import ios_name, ios_short
    return ios_short(ios_name(port_names(node).get(port, port)))


def _vlan(node, port):
    return ((node.get('switchports') or {}).get(port) or {}).get('vlan', 1)


FOOTER = ['Total Addresses in System (excluding one mac per port)     : 0',
          'Max Addresses limit in System (excluding one mac per port) : 8192']


def summary(node, states):
    """« show port-security »."""
    lines = ['Secure Port  MaxSecureAddr  CurrentAddr  SecurityViolation  Security Action',
             '                (Count)       (Count)          (Count)', '-' * 75]
    for port, settings in sorted(policy(node).items(), key=lambda item: int(item[0][3:])):
        if not settings['secure']:
            continue
        state = states.get(port) or {'macs': [(m, 's') for m in settings['macs']], 'violations': 0}
        lines.append(f'{_short(node, port):>11}{settings["maximum"]:>15}{len(state["macs"]):>13}{state["violations"]:>19}'
                     f'{settings["violation"].capitalize():>17}')
    return '\n'.join(lines + ['-' * 75] + FOOTER)


def interface(node, port, states):
    """« show port-security interface PORT »."""
    settings = policy(node).get(port)
    secure = bool(settings and settings['secure'])
    state = states.get(port) or {'state': 'secure', 'macs': [], 'violations': 0, 'last': None}
    down = port in (node.get('shutdown') or [])
    status = 'Secure-shutdown' if secure and state['state'] == 'err-disabled' else 'Secure-down' if secure and down \
        else 'Secure-up' if secure else 'Secure-down'
    macs = state['macs']
    source = state.get('last') or (macs[-1][0] if macs else None)
    last = f'{source}:{_vlan(node, port)}' if source else '0000.0000.0000:0'
    rows = [('Port Security', 'Enabled' if secure else 'Disabled'), ('Port Status', status),
            ('Violation Mode', (settings['violation'] if settings else 'shutdown').capitalize()), ('Aging Time', '0 mins'),
            ('Aging Type', 'Absolute'), ('SecureStatic Address Aging', 'Disabled'),
            ('Maximum MAC Addresses', settings['maximum'] if settings else 1), ('Total MAC Addresses', len(macs)),
            ('Configured MAC Addresses', sum(1 for _, k in macs if k == 's' and not (settings or {}).get('sticky'))),
            ('Sticky MAC Addresses', sum(1 for _, k in macs if k == 'k' or (k == 's' and (settings or {}).get('sticky')))),
            ('Last Source Address:Vlan', last), ('Security Violation Count', state['violations'])]
    return '\n'.join(f'{label:<27}: {value}' for label, value in rows)


def addresses(node, states):
    """« show port-security address »."""
    lines = ['               Secure Mac Address Table', '-' * 77,
             'Vlan    Mac Address       Type                          Ports   Remaining Age',
             '                                                                   (mins)',
             '----    -----------       ----                          -----   -------------']
    for port, settings in sorted(policy(node).items(), key=lambda item: int(item[0][3:])):
        if not settings['secure']:
            continue
        state = states.get(port) or {'macs': [(m, 's') for m in settings['macs']]}
        for mac, kind in state['macs']:
            label = 'SecureSticky' if kind == 'k' or (kind == 's' and settings['sticky']) else \
                'SecureConfigured' if kind == 's' else 'SecureDynamic'
            lines.append(f'{_vlan(node, port):>4}    {mac:<18}{label:<30}{_short(node, port):<8}{"-":>8}')
    return '\n'.join(lines + ['-' * 77] + FOOTER)
