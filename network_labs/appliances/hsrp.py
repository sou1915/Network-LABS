"""HSRP on router micro-VMs, as IOS has it: « standby [GROUP] ip A.B.C.D », « standby [GROUP] priority N »,
« standby [GROUP] preempt », « standby [GROUP] timers HELLO HOLD », « standby [GROUP] authentication TEXT » and
« standby version 1|2 », typed on a LAN port or a router-on-a-stick subinterface.

The lines are kept with the port's IOS lines (ios_store) and make its groups (groups()). In the guest, the agent's
--hsrp mode speaks HSRP for real (version 1 or 2): the routers of a group elect the active router (highest priority,
then highest address; with preempt a higher priority takes over), the active one answers for the virtual address with
the group's virtual MAC (0000.0c07.acNN, version 2 0000.0c9f.fNNN), and the standby takes over when the active one
falls silent for the hold time. A stopped lab gets the same election from the cables (model()), so ping and
« show standby » see it.
"""
import ipaddress
import re

from . import ios_store

LINE = re.compile(r'standby(?: (\d+))? (ip|priority|preempt|timers|authentication)(?: (.*))?')
VERSION = re.compile(r'standby version ([12])')
DEFAULTS = {'ip': None, 'priority': 100, 'preempt': False, 'hello': 3, 'hold': 10, 'auth': 'cisco', 'configured': False}
ORDER = ('ip', 'timers', 'priority', 'preempt', 'authentication')  # as IOS writes them under the interface
MAX_GROUPS = 16  # per router: the agent's limit


def _parsed(line):
    """(group, keyword, value words as typed) of a stored standby line, ('version', ...) for the version, else None."""
    low = ' '.join(line.lower().split())
    if VERSION.fullmatch(low):
        return None, 'version', [low.split()[-1]]
    match = LINE.fullmatch(low)
    if not match:
        return None
    words = line.split()
    return int(match[1] or 0), match[2], words[3 if match[1] else 2:]


def _applies(node):
    return node.get('role') == 'router' and node.get('runtime') == 'firecracker'


def groups(node):
    """{port: {'version': 1|2, 'groups': {group: settings}}} for a router micro-VM's ports with standby lines."""
    if not _applies(node) or not node.get('cli_config'):
        return {}
    found = {}
    for port, typed in ios_store.config(node)['interfaces'].items():
        version, entries = 1, {}
        for line in typed:
            parsed = _parsed(line)
            if parsed is None:
                continue
            group, keyword, values = parsed
            if keyword == 'version':
                version = int(values[0])
                continue
            settings = entries.setdefault(group, dict(DEFAULTS))
            if keyword == 'ip':
                settings['ip'] = values[0]
            elif keyword == 'priority':
                settings['priority'], settings['configured'] = int(values[0]), True
            elif keyword == 'preempt':
                settings['preempt'] = True
            elif keyword == 'timers':
                settings['hello'], settings['hold'] = int(values[0]), int(values[1])
            else:
                settings['auth'] = values[-1]
        if entries:
            found[port] = {'version': version, 'groups': entries}
    return found


def _port_key(port):
    parent, _, vid = port.partition('.')
    return int(parent[3:]) if parent[3:].isdigit() else 99, int(vid or 0)


def arguments(node):
    """The agent's --hsrp arguments, one per group with a virtual address (IFACE/GROUP/VERSION/VIP/PRIORITY/PREEMPT/HELLO/
    HOLD/AUTH in hex), on the ports the guest has (a subinterface once its VLAN is set)."""
    found = []
    subinterfaces = node.get('subinterfaces') or {}
    for port, entry in sorted(groups(node).items(), key=lambda item: _port_key(item[0])):
        if port not in node['interfaces'] and port not in subinterfaces:
            continue
        for group, settings in sorted(entry['groups'].items()):
            if settings['ip']:
                found.append('/'.join([port, str(group), str(entry['version']), settings['ip'], str(settings['priority']),
                                       'y' if settings['preempt'] else 'n', str(settings['hello']), str(settings['hold']),
                                       settings['auth'].encode().hex()]))
    return found[:MAX_GROUPS]


def virtual_addresses(node):
    """{port: {'A.B.C.D/32'}}: the virtual addresses the guest may hold on (or beside) each port when it is active."""
    found = {}
    for port, entry in groups(node).items():
        for settings in entry['groups'].values():
            if settings['ip']:
                found.setdefault(port, set()).add(settings['ip'] + '/32')
    return found


def virtual_mac(group, version):
    return f'0000.0c07.ac{group:02x}' if version == 1 else f'0000.0c9f.f{group:03x}'


# ---- typed lines ----

def _port_address(node, port):
    sub = (node.get('subinterfaces') or {}).get(port)
    address = sub.get('address') if sub is not None else node['interfaces'].get(port)
    return ipaddress.IPv4Interface(address) if address else None


def _store(node, port, key, line=None):
    """Replace (or with LINE None, remove) the standby lines of KEY (group, keyword); group None and keyword None
    remove every line of the group. Standby lines are kept in IOS's order after the port's other lines."""
    current = ios_store.config(node)
    typed = current['interfaces'].setdefault(port, [])
    others = [l for l in typed if _parsed(l) is None]
    kept = []
    for existing in typed:
        parsed = _parsed(existing)
        if parsed is None:
            continue
        group, keyword, _ = parsed
        if key[1] is None and keyword != 'version' and group == key[0]:
            continue
        if (group if keyword != 'version' else None, keyword) == key:
            continue
        kept.append(existing)
    if line:
        kept.append(line)

    def order(text):
        group, keyword, _ = _parsed(text)
        return (0, 0, 0) if keyword == 'version' else (1, group, ORDER.index(keyword))
    typed[:] = others + sorted(kept, key=order)
    node['cli_config'] = current


def configure(node, port, command):
    """One typed « [no] standby … » line on PORT, with IOS's checks."""
    if not _applies(node):
        raise ValueError('Network LABS : HSRP (standby) sur les routeurs micro-VM.')
    words = command.split()
    negative = words[0].lower() == 'no'
    words = words[1:] if negative else words
    rest = words[1:]
    low = [w.lower() for w in rest]
    if not rest:
        if negative:  # « no standby »: every group of the port
            for group in list((groups(node).get(port) or {}).get('groups', {})):
                _store(node, port, (group, None))
            return _store(node, port, (None, 'version'))
        raise ValueError('Incomplete command.')
    entry = groups(node).get(port) or {'version': 1, 'groups': {}}
    if low[0] == 'version':
        if negative or low[1:] == ['1']:
            if any(group > 255 for group in entry['groups']):
                raise ValueError('Un groupe au-delà de 255 demande HSRP version 2.')
            return _store(node, port, (None, 'version'))
        if low[1:] != ['2']:
            raise ValueError('Incomplete command.' if len(low) == 1 else "Invalid input detected at '^' marker.")
        return _store(node, port, (None, 'version'), 'standby version 2')
    group = None
    if low[0].isdigit():
        group, rest, low = int(low[0]), rest[1:], low[1:]
        limit = 255 if entry['version'] == 1 else 4095
        if group > limit:
            raise ValueError(f'Groupe HSRP de 0 à {limit} en version {entry["version"]} (standby version 2 : jusqu’à 4095).')
    number = group or 0
    prefix = 'standby ' + ('' if group is None else f'{group} ')
    if not rest:
        if negative:
            return _store(node, port, (number, None))
        raise ValueError('Incomplete command.')
    keyword, values = low[0], rest[1:]
    if keyword not in ORDER:
        raise ValueError('Network LABS : standby [groupe] ip, priority, preempt, timers, authentication ; standby version 1|2.')
    if negative:
        return _store(node, port, (number, keyword))
    if keyword == 'ip':
        if not values:
            raise ValueError('Network LABS : donner l’adresse virtuelle (standby N ip A.B.C.D) ; le lab ne l’apprend pas du routeur actif.')
        try:
            address = ipaddress.IPv4Address(values[0])
        except ValueError:
            raise ValueError("Invalid input detected at '^' marker.") from None
        own = _port_address(node, port)
        if own is None or address not in own.network or address in (own.network.network_address, own.network.broadcast_address):
            raise ValueError('Warning: address is not within a subnet on this interface')
        if address == own.ip:
            raise ValueError(f'Address {address} in group {number} is this interface\'s own address')
        if number not in entry['groups'] and sum(len(e['groups']) for e in groups(node).values()) >= MAX_GROUPS:
            raise ValueError(f'Network LABS : {MAX_GROUPS} groupes HSRP au plus par routeur.')
        return _store(node, port, (number, 'ip'), f'{prefix}ip {address}')
    if keyword == 'priority':
        if not values:
            raise ValueError('Incomplete command.')
        if not values[0].isdigit() or int(values[0]) > 255:
            raise ValueError('Priorité HSRP de 0 à 255 (100 par défaut).')
        return _store(node, port, (number, 'priority'), f'{prefix}priority {int(values[0])}')
    if keyword == 'preempt':
        if values:
            raise ValueError('Network LABS : standby N preempt (sans délai).')
        return _store(node, port, (number, 'preempt'), f'{prefix}preempt')
    if keyword == 'timers':
        if len(values) < 2:
            raise ValueError('Incomplete command.')
        if not all(v.isdigit() for v in values[:2]) or len(values) > 2:
            raise ValueError('Network LABS : standby N timers HELLO HOLD, en secondes.')
        hello, hold = int(values[0]), int(values[1])
        if not 1 <= hello <= 254 or not hello < hold <= 255:
            raise ValueError('Hello de 1 à 254 s, hold de hello+1 à 255 s.')
        return _store(node, port, (number, 'timers'), f'{prefix}timers {hello} {hold}')
    if values and values[0].lower() == 'md5':
        raise ValueError('Network LABS : authentification HSRP en texte seulement (standby N authentication MOT).')
    text = values[1:] if values and values[0].lower() == 'text' else values
    if len(text) != 1 or len(text[0]) > 8:
        raise ValueError('Incomplete command.' if not text else 'Le mot d’authentification HSRP fait 8 caractères au plus.')
    return _store(node, port, (number, 'authentication'), f'{prefix}authentication {text[0]}')


# ---- states: the guest's, or the election a stopped lab makes ----

def parse(text):
    """{(port, group): state} from HSRP_SHOW: state, active / standby ('local', an address or None) with their priority and
    seconds left, changes, seconds since the last change, seconds to the next hello, macvlan (the virtual MAC in use)."""
    now_match = re.search(r'^now ([\d.]+)', text, re.M)
    now = float(now_match[1]) if now_match else 0.0
    found = {}
    for block in re.split(r'^== ', text, flags=re.M)[1:]:
        values = dict(line.split(' ', 1) for line in block.splitlines()[1:] if ' ' in line)
        if 'interface' not in values or 'group' not in values:
            continue
        state = {'state': values.get('state', 'init'), 'changes': int(values.get('changes', 0)),
                 'since': max(0.0, now - float(values.get('since', now))) if float(values.get('since', 0)) else None,
                 'next': max(0.0, float(values.get('next', now)) - now), 'macvlan': values.get('macvlan') == '1'}
        for role in ('active', 'standby'):
            who, priority, until = (values.get(role, '- 0 0').split() + ['0', '0'])[:3]
            state[role] = None if who == '-' else who
            state[role + '_priority'] = int(priority)
            state[role + '_expires'] = max(0.0, float(until) - now)
        found[(values['interface'], int(values['group']))] = state
    return found


def election(spec, seg=None):
    """{(node, port, group): state} as the routers of each group elect when they start together: the highest priority
    (then address) active, the next standby, the others listening; a shut port or one without its address in Init."""
    from .network_model import addresses, segments
    seg = segments(spec) if seg is None else seg
    found, members = {}, {}
    for node in spec['nodes']:
        held = addresses(node)
        for port, entry in groups(node).items():
            for group, settings in entry['groups'].items():
                found[(node['name'], port, group)] = {'state': 'init', 'changes': None, 'since': None, 'next': None,
                                                      'macvlan': True, 'active': None, 'standby': None, 'active_priority': 0,
                                                      'standby_priority': 0, 'active_expires': None, 'standby_expires': None}
                if not settings['ip'] or port not in held:
                    continue
                key = (seg.get((node['name'], port)), group, entry['version'], settings['ip'], settings['auth'])
                members.setdefault(key, []).append((settings['priority'], held[port].ip, node['name'], port, group))
    for key, routers in members.items():
        ranked = sorted(routers, reverse=True)
        for index, (_, _, name, port, group) in enumerate(ranked):
            state = found[(name, port, group)]
            state['state'] = 'active' if index == 0 else 'standby' if index == 1 else 'listen'
            state['active'] = 'local' if index == 0 else str(ranked[0][1])
            state['active_priority'] = ranked[0][0]
            if len(ranked) > 1:
                state['standby'] = 'local' if index == 1 else str(ranked[1][1])
                state['standby_priority'] = ranked[1][0]
    return found


def virtual_owners(spec, seg):
    """{(segment, virtual address): (router, port)}: who answers for each group's address in a stopped lab."""
    found = {}
    for (name, port, group), state in election(spec, seg).items():
        if state['state'] == 'active':
            node = next(n for n in spec['nodes'] if n['name'] == name)
            entry = groups(node)[port]
            found[(seg.get((name, port)), ipaddress.IPv4Address(entry['groups'][group]['ip']))] = (name, port)
    return found


# ---- IOS output ----

def _shown(node, port, short=False):
    from .native_models import port_names
    from .vendor_config import ios_name, ios_short
    parent, _, vid = port.partition('.')
    label = ios_name(port_names(node).get(parent, parent)) + (f'.{vid}' if vid else '')
    return ios_short(label) if short else label


def _clock(seconds):
    seconds = int(seconds)
    return f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'


def _rows(node, states):
    for port, entry in sorted(groups(node).items(), key=lambda item: _port_key(item[0])):
        for group, settings in sorted(entry['groups'].items()):
            yield port, entry['version'], group, settings, states.get((port, group)) or dict(
                state='init', changes=None, since=None, next=None, macvlan=True, active=None, standby=None,
                active_priority=0, standby_priority=0, active_expires=None, standby_expires=None)


def show(node, states, port=None):
    """« show standby [PORT] »."""
    from .runtime import guest_mac
    blocks = []
    for name, version, group, settings, state in _rows(node, states):
        if port is not None and name != port:
            continue
        down = state['state'] == 'init'
        lines = [f'{_shown(node, name)} - Group {group}' + (' (version 2)' if version == 2 else ''),
                 f'  State is {state["state"].capitalize()}' + (' (interface down)' if down and settings['ip'] else '')]
        if state['changes'] is not None:
            last = _clock(state['since']) if state['since'] is not None else 'never'
            lines.append(f'    {state["changes"]} state change{"s" if state["changes"] != 1 else ""}, last state change {last}')
        lines.append(f'  Virtual IP address is {settings["ip"] or "unknown"}')
        own = virtual_mac(group, version)
        in_use = own if state['macvlan'] else guest_mac(node['name'], name.split('.')[0]).replace(':', '')
        in_use = in_use if '.' in in_use else '.'.join(in_use[i:i + 4] for i in range(0, 12, 4))
        if state['active'] is None:
            lines.append('  Active virtual MAC address is unknown (MAC Not In Use)')
        else:
            lines.append(f'  Active virtual MAC address is {in_use} (MAC {"In Use" if state["state"] == "active" else "Not In Use"})')
        lines.append(f'    Local virtual MAC address is {own} (v{version} default)')
        lines.append(f'  Hello time {settings["hello"]} sec, hold time {settings["hold"]} sec')
        if state['next'] is not None and state['state'] in ('speak', 'standby', 'active'):
            lines.append(f'    Next hello sent in {state["next"]:.3f} secs')
        if settings['auth'] != 'cisco':
            lines.append(f'  Authentication text, string "{settings["auth"]}"')
        lines.append(f'  Preemption {"enabled" if settings["preempt"] else "disabled"}')
        for role in ('active', 'standby'):
            who = state[role]
            label = role.capitalize()
            if who is None:
                lines.append(f'  {label} router is unknown')
            elif who == 'local':
                lines.append(f'  {label} router is local')
            else:
                expires = state[role + '_expires']
                lines.append(f'  {label} router is {who}, priority {state[role + "_priority"]}'
                             + (f' (expires in {expires:.3f} sec)' if expires is not None else ''))
        lines.append(f'  Priority {settings["priority"]} ({"configured" if settings["configured"] else "default"} '
                     f'{settings["priority"] if settings["configured"] else 100})')
        lines.append(f'  Group name is "hsrp-{_shown(node, name, short=True)}-{group}" (default)')
        blocks.append('\n'.join(lines))
    return '\n'.join(blocks)


def brief(node, states):
    """« show standby brief »."""
    lines = ['                     P indicates configured to preempt.', '                     |',
             'Interface   Grp  Pri P State   Active          Standby         Virtual IP']
    for name, _, group, settings, state in _rows(node, states):
        lines.append(f'{_shown(node, name, short=True):<12}{group:<5}{settings["priority"]:<4}{"P" if settings["preempt"] else " "} '
                     f'{state["state"].capitalize():<8}{state["active"] or "unknown":<16}{state["standby"] or "unknown":<16}'
                     f'{settings["ip"] or "unknown"}')
    return '\n'.join(lines)
