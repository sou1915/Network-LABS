"""VRRP on router micro-VMs, as IOS has it (RFC 3768, VRRP version 2): « vrrp N ip A.B.C.D », « vrrp N priority P »,
« [no] vrrp N preempt », « vrrp N timers advertise S », « vrrp N authentication text W », « vrrp N description TEXT » and
« [no] vrrp N shutdown », typed on a LAN port or a router-on-a-stick subinterface.

The lines are kept with the port's IOS lines (ios_store) and make its groups (groups()). In the guest, keepalived speaks
VRRP for real (the agent's --vrrp mode writes its configuration and reads its state back for « show vrrp »): adverts (IP
protocol 112 to 224.0.0.18, TTL 255) every advertisement interval; the router of
the highest priority (then the highest address) is the master and holds the virtual address with the virtual MAC
0000.5e00.01NN; a backup takes over when the master falls silent for the master down interval (three adverts and a skew
that favours the higher priority), or at once when the master resigns (an advert of priority 0). Preemption is on by
default, as on IOS. A router whose own port address is the virtual address owns it: priority 255. A stopped lab gets the
same election from the cables (election()), so ping and « show vrrp » see it.
"""
import ipaddress
import re

from . import ios_store

LINE = re.compile(r'(no )?vrrp (\d+) (ip|priority|preempt|timers|authentication|description|shutdown)(?: (.*))?')
DEFAULTS = {'ip': None, 'priority': 100, 'configured': False, 'preempt': True, 'advertise': 1, 'auth': None, 'description': '',
            'shutdown': False}
ORDER = ('description', 'ip', 'timers', 'priority', 'preempt', 'authentication', 'shutdown')  # IOS's order under the interface
MAX_GROUPS = 16  # per router: the agent's limit


def _parsed(line):
    """(group, keyword, value words as typed, negative) of a stored vrrp line, else None."""
    match = LINE.fullmatch(' '.join(line.lower().split()))
    if not match:
        return None
    words = line.split()[1 if match[1] else 0:]
    return int(match[2]), match[3], words[3:], bool(match[1])


def _applies(node):
    return node.get('role') == 'router' and node.get('runtime') == 'firecracker'


def _port_address(node, port):
    sub = (node.get('subinterfaces') or {}).get(port)
    address = sub.get('address') if sub is not None else node['interfaces'].get(port)
    return ipaddress.IPv4Interface(address) if address else None


def groups(node):
    """{port: {group: settings}} for a router micro-VM's ports with vrrp lines; settings['owner'] when the virtual address
    is the port's own (priority 255)."""
    if not _applies(node) or not node.get('cli_config'):
        return {}
    found = {}
    for port, typed in ios_store.config(node)['interfaces'].items():
        entries = {}
        for line in typed:
            parsed = _parsed(line)
            if parsed is None:
                continue
            group, keyword, values, negative = parsed
            settings = entries.setdefault(group, dict(DEFAULTS))
            if keyword == 'ip':
                settings['ip'] = values[0]
            elif keyword == 'priority':
                settings['priority'], settings['configured'] = int(values[0]), True
            elif keyword == 'preempt':
                settings['preempt'] = not negative
            elif keyword == 'timers':
                settings['advertise'] = int(values[-1])
            elif keyword == 'authentication':
                settings['auth'] = values[-1]
            elif keyword == 'description':
                settings['description'] = ' '.join(values)
            else:
                settings['shutdown'] = True
        own = _port_address(node, port)
        for settings in entries.values():
            settings['owner'] = bool(own and settings['ip'] and ipaddress.IPv4Address(settings['ip']) == own.ip)
            settings['effective'] = 255 if settings['owner'] else settings['priority']
        if entries:
            found[port] = entries
    return found


def _port_key(port):
    parent, _, vid = port.partition('.')
    return int(parent[3:]) if parent[3:].isdigit() else 99, int(vid or 0)


def arguments(node):
    """The agent's --vrrp arguments, one per group with a virtual address and not shut (IFACE/VRID/VIP/PRIORITY/PREEMPT/
    ADVERT/AUTH, AUTH in hex or -), on the ports the guest has."""
    found = []
    subinterfaces = node.get('subinterfaces') or {}
    for port, entries in sorted(groups(node).items(), key=lambda item: _port_key(item[0])):
        if port not in node['interfaces'] and port not in subinterfaces:
            continue
        for group, settings in sorted(entries.items()):
            if settings['ip'] and not settings['shutdown']:
                found.append('/'.join([port, str(group), settings['ip'], str(settings['effective']), 'y' if settings['preempt'] else 'n',
                                       str(settings['advertise']), settings['auth'].encode().hex() if settings['auth'] else '-']))
    return found[:MAX_GROUPS]


def virtual_addresses(node):
    """{port: {'A.B.C.D/32'}}: the virtual addresses the guest may hold beside each port while master. The owner's too:
    keepalived adds the virtual address as a /32 beside the port's own address, which it already is."""
    found = {}
    for port, entries in groups(node).items():
        for settings in entries.values():
            if settings['ip']:
                found.setdefault(port, set()).add(settings['ip'] + '/32')
    return found


def virtual_mac(group):
    return f'0000.5e00.01{group:02x}'


def down_interval(advertise, priority):
    """The master down interval, in seconds: three adverts and the skew time (256 - priority) / 256."""
    return 3 * advertise + (256 - priority) / 256


# ---- typed lines ----

def _store(node, port, key, line=None):
    """Replace (or with LINE None, remove) the vrrp line of KEY (group, keyword); keyword None removes the whole group."""
    current = ios_store.config(node)
    typed = current['interfaces'].setdefault(port, [])
    others = [l for l in typed if _parsed(l) is None]
    kept = [l for l in typed if _parsed(l) is not None and not (_parsed(l)[0] == key[0] and key[1] in (None, _parsed(l)[1]))]
    if line:
        kept.append(line)
    typed[:] = others + sorted(kept, key=lambda text: (_parsed(text)[0], ORDER.index(_parsed(text)[1])))
    node['cli_config'] = current


def configure(node, port, command):
    """One typed « [no] vrrp … » line on PORT, with IOS's checks."""
    if not _applies(node):
        raise ValueError('Network LABS : VRRP sur les routeurs micro-VM.')
    words = command.split()
    negative = words[0].lower() == 'no'
    words = words[1:] if negative else words
    rest = words[1:]
    if not rest:
        raise ValueError('Incomplete command.')
    if not rest[0].isdigit():
        raise ValueError("Invalid input detected at '^' marker.")
    group = int(rest[0])
    if not 1 <= group <= 255:
        raise ValueError('Groupe VRRP de 1 à 255.')
    entries = groups(node).get(port) or {}
    prefix = f'vrrp {group} '
    if len(rest) == 1:
        if negative:  # « no vrrp N »: the whole group
            return _store(node, port, (group, None))
        raise ValueError('Incomplete command.')
    keyword, values = rest[1].lower(), rest[2:]
    if keyword not in ORDER:
        raise ValueError('Network LABS : vrrp N ip, priority, preempt, timers advertise, authentication text, description, shutdown.')
    if keyword == 'preempt':  # on by default: IOS keeps « no vrrp N preempt » when it is turned off
        if values and not negative:
            raise ValueError('Network LABS : vrrp N preempt (sans délai).')
        return _store(node, port, (group, 'preempt'), f'no {prefix}preempt' if negative else None)
    if negative:
        return _store(node, port, (group, keyword))
    if keyword == 'ip':
        if not values:
            raise ValueError('Incomplete command.')
        if len(values) > 1:
            raise ValueError('Network LABS : une adresse virtuelle par groupe (pas de secondary).')
        try:
            address = ipaddress.IPv4Address(values[0])
        except ValueError:
            raise ValueError("Invalid input detected at '^' marker.") from None
        own = _port_address(node, port)
        if own is None or address not in own.network or address in (own.network.network_address, own.network.broadcast_address):
            raise ValueError(f'% Address {address} is not in a subnet on this interface')
        if group not in entries and sum(len(e) for e in groups(node).values()) >= MAX_GROUPS:
            raise ValueError(f'Network LABS : {MAX_GROUPS} groupes VRRP au plus par routeur.')
        return _store(node, port, (group, 'ip'), f'{prefix}ip {address}')
    if keyword == 'priority':
        if not values:
            raise ValueError('Incomplete command.')
        if not values[0].isdigit() or not 1 <= int(values[0]) <= 254:
            raise ValueError('Priorité VRRP de 1 à 254 (100 par défaut ; 255 est celle du propriétaire de l’adresse).')
        return _store(node, port, (group, 'priority'), f'{prefix}priority {int(values[0])}')
    if keyword == 'timers':
        if not values or values[0].lower() != 'advertise':
            raise ValueError('Network LABS : vrrp N timers advertise SECONDES.')
        if len(values) != 2 or not values[1].isdigit() or not 1 <= int(values[1]) <= 255:
            raise ValueError('Intervalle d’annonce VRRP de 1 à 255 secondes (1 par défaut).')
        return _store(node, port, (group, 'timers'), f'{prefix}timers advertise {int(values[1])}')
    if keyword == 'authentication':
        if values and values[0].lower() in ('md5', 'key-chain'):
            raise ValueError('Network LABS : authentification VRRP en texte seulement (vrrp N authentication text MOT).')
        text = values[1:] if values and values[0].lower() == 'text' else values
        if len(text) != 1 or len(text[0]) > 8:
            raise ValueError('Incomplete command.' if not text else 'Le mot d’authentification VRRP fait 8 caractères au plus.')
        if not all(33 <= ord(c) <= 126 and c not in '"\\' for c in text[0]):  # keepalived's configuration quotes it
            raise ValueError('Network LABS : le mot d’authentification VRRP s’écrit en caractères ASCII, sans " ni \\.')
        return _store(node, port, (group, 'authentication'), f'{prefix}authentication text {text[0]}')
    if keyword == 'description':
        text = ' '.join(values)
        if not text or len(text) > 80:
            raise ValueError('Incomplete command.' if not text else 'Description de 80 caractères au plus.')
        return _store(node, port, (group, 'description'), f'{prefix}description {text}')
    if values:
        raise ValueError("Invalid input detected at '^' marker.")
    return _store(node, port, (group, 'shutdown'), f'{prefix}shutdown')


# ---- states: the guest's, or the election a stopped lab makes ----

def _blank():
    return {'state': 'init', 'changes': None, 'since': None, 'master': None, 'master_priority': 0, 'master_advert': None,
            'down_expires': None, 'macvlan': True}


def parse(text):
    """{(port, group): state} from VRRP_SHOW: state (init, backup, master), the master ('local', an address or None) with
    its priority and advertisement interval, seconds left on the master down timer, changes, seconds since the last change."""
    now_match = re.search(r'^now ([\d.]+)', text, re.M)
    now = float(now_match[1]) if now_match else 0.0
    found = {}
    for block in re.split(r'^== ', text, flags=re.M)[1:]:
        values = dict(line.split(' ', 1) for line in block.splitlines()[1:] if ' ' in line)
        if 'interface' not in values or 'group' not in values:
            continue
        who, priority, advert = (values.get('master', '- 0 0').split() + ['0', '0'])[:3]
        since = float(values.get('since', 0) or 0)
        state = _blank()
        state.update(state=values.get('state', 'init'), changes=int(values.get('changes', 0)), since=max(0.0,
                                                                                                         now - since) if since else None,
                     master=None if who == '-' else who, master_priority=int(priority), master_advert=int(advert) or None,
                     macvlan=values.get('macvlan') == '1')
        if state['state'] == 'backup' and float(values.get('down', 0) or 0):
            state['down_expires'] = max(0.0, float(values['down']) - now)
        found[(values['interface'], int(values['group']))] = state
    return found


def election(spec, seg=None):
    """{(node, port, group): state} as the routers of each group elect: the highest priority (the owner's 255, then the
    highest address) master, the others backup; a shut port, a port without its address or a shut group in Init."""
    from .network_model import addresses, segments
    seg = segments(spec) if seg is None else seg
    found, members = {}, {}
    for node in spec['nodes']:
        held = addresses(node)
        for port, entries in groups(node).items():
            for group, settings in entries.items():
                found[(node['name'], port, group)] = _blank()
                if not settings['ip'] or settings['shutdown'] or port not in held:
                    continue
                key = (seg.get((node['name'], port)), group, settings['ip'], settings['auth'])
                members.setdefault(key, []).append((settings['effective'], held[port].ip, node['name'], port, group, settings['advertise']))
    for routers in members.values():
        ranked = sorted(routers, reverse=True)
        top = ranked[0]
        for index, (_, _, name, port, group, _) in enumerate(ranked):
            found[(name, port, group)].update(state='master' if index == 0 else 'backup', master='local' if index == 0 else str(top[1]),
                                              master_priority=top[0], master_advert=top[5])
    return found


def virtual_owners(spec, seg):
    """{(segment, virtual address): (router, port)}: who answers for each group's address in a stopped lab."""
    found = {}
    for (name, port, group), state in election(spec, seg).items():
        if state['state'] == 'master':
            node = next(n for n in spec['nodes'] if n['name'] == name)
            found[(seg.get((name, port)), ipaddress.IPv4Address(groups(node)[port][group]['ip']))] = (name, port)
    return found


# ---- IOS output ----

def _shown(node, port, short=False):
    from .hsrp import _shown as shown
    return shown(node, port, short)


def _rows(node, states):
    for port, entries in sorted(groups(node).items(), key=lambda item: _port_key(item[0])):
        for group, settings in sorted(entries.items()):
            yield port, group, settings, states.get((port, group)) or _blank()


def _own_address(node, port):
    own = _port_address(node, port)
    return str(own.ip) if own else 'unknown'


def show(node, states):
    """« show vrrp »."""
    blocks = []
    for port, group, settings, state in _rows(node, states):
        lines = [f'{_shown(node, port)} - Group {group}']
        if settings['description']:
            lines.append(f'  {settings["description"]}')
        lines.append(f'  State is {state["state"].capitalize()}')
        lines.append(f'  Virtual IP address is {settings["ip"] or "unknown"}')
        lines.append(f'  Virtual MAC address is {virtual_mac(group)}')
        lines.append(f'  Advertisement interval is {settings["advertise"]:.3f} sec')
        lines.append(f'  Preemption {"enabled" if settings["preempt"] else "disabled"}')
        lines.append(f'  Priority is {settings["effective"]}' + (' (IP address owner)' if settings['owner'] else ''))
        if settings['auth']:
            lines.append(f'  Authentication text "{settings["auth"]}"')
        if state['master'] == 'local':
            lines.append(f'  Master Router is {_own_address(node, port)} (local), priority is {settings["effective"]}')
        elif state['master']:
            lines.append(f'  Master Router is {state["master"]}, priority is {state["master_priority"]}')
        else:
            lines.append('  Master Router is unknown, priority is unknown')
        advert = state['master_advert'] or settings['advertise']
        lines.append(f'  Master Advertisement interval is {advert:.3f} sec')
        interval = down_interval(advert, settings['effective'])
        backup = state['state'] == 'backup' and state['down_expires'] is not None
        expires = f' (expires in {state["down_expires"]:.3f} sec)' if backup else ''
        lines.append(f'  Master Down interval is {interval:.3f} sec{expires}')
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


def brief(node, states):
    """« show vrrp brief »."""
    lines = ['Interface          Grp Pri Time  Own Pre State   Master addr     Group addr']
    for port, group, settings, state in _rows(node, states):
        master = _own_address(node, port) if state['master'] == 'local' else state['master'] or 'unknown'
        time_ms = round(down_interval(settings['advertise'], settings['effective']) * 1000)
        lines.append(f'{_shown(node, port,
                               short=True):<19}{group:<4}{settings["effective"]:<4}{time_ms:<6}{"Y" if settings["owner"] else " ":<4}'
                     f'{"Y" if settings["preempt"] else " ":<4}{state["state"].capitalize():<8}{master:<16}{settings["ip"] or "unknown"}')
    return '\n'.join(lines)
