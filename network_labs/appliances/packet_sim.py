"""Packet Tracer's simulation mode for one ping: every frame that crosses a cable, in order, with its headers.

The routed path (each router, the port it leaves by, the next hop, translations and access lists) is the network
model's own walk (Model.deliver), so the animation shows exactly what « ping » computes. Between two routed hops the
frame crosses the switches of that VLAN: access ports untagged, trunks tagged (the native VLAN untagged), shut ports
and the ports spanning tree blocks left out, so it follows the tree. Before the first frame to a next hop, ARP: the
request floods the VLAN (every port it reaches, at once), the reply comes back unicast; both ends then know each
other, as Linux and IOS learn the asker from its request. MAC addresses are the micro-VMs' fixed ones
(runtime.guest_mac). TTL starts at 64 (the guests run Linux) and each router takes one off.
"""
import ipaddress

from .guest_startup import vlan_plan
from .native_models import port_names
from .network_model import Model, _port_of

TTL = 64
BROADCAST = 'ffff.ffff.ffff'


def _cisco(mac):
    digits = mac.replace(':', '')
    return '.'.join(digits[i:i + 4] for i in range(0, 12, 4))


class _Fabric:
    """The cables and switches of a lab, for frames."""

    def __init__(self, spec):
        from .guest_stp import blocked_ports
        self.nodes = {n['name']: n for n in spec['nodes']}
        self.peer = {}
        for a, b in spec['links']:
            a, b = tuple(a), tuple(b)
            if a[1] in (self.nodes[a[0]].get('shutdown') or []) or b[1] in (self.nodes[b[0]].get('shutdown') or []):
                continue  # a shut port carries nothing
            self.peer[a], self.peer[b] = b, a
        self.blocked = blocked_ports(spec)

    def mac(self, node, interface):
        """The MAC a frame from (or to) NODE's INTERFACE carries: the port's own; a subinterface's parent's; a switch SVI's
        the bridge's (its first port's)."""
        from .runtime import guest_mac
        record = self.nodes[node]
        if record['role'] == 'switch':
            return _cisco(guest_mac(node, min(record['interfaces'], key=lambda p: int(p[3:]))))
        sub = (record.get('subinterfaces') or {}).get(interface)
        return _cisco(guest_mac(node, sub['parent'] if sub else _port_of(interface)))

    def attachment(self, node, interface):
        """(physical port or None, VLAN tag or VLAN): a port untagged, a subinterface tagged on its parent, a switch SVI
        inside the switch (no port, its VLAN)."""
        record = self.nodes[node]
        if record['role'] == 'switch' and interface in (record.get('svis') or {}):
            return None, record['svis'][interface]['vlan']
        sub = (record.get('subinterfaces') or {}).get(interface)
        return (sub['parent'], sub['vlan']) if sub else (_port_of(interface), None)

    def classify(self, switch, port, tag):
        """The VLAN a frame arriving on a switch port with TAG belongs to there, or None when the port drops it."""
        record = self.nodes[switch]
        if (switch, port) in self.blocked:
            return None
        if vlan_plan(record) is None:
            return tag or 1  # a plain bridge: one untagged VLAN 1, tagged frames pass as they are
        settings = record['switchports'][port]
        if settings['mode'] == 'access':
            return settings['vlan'] if tag is None else None
        allowed = record['vlans'] if settings['allowed'] == 'all' else settings['allowed']
        vid = settings['native_vlan'] if tag is None else tag
        return vid if vid in allowed or vid == settings['native_vlan'] else None

    def egress(self, switch, vid, came_in):
        """[(port, tag)] a switch sends a VLAN VID frame out of: every other port carrying the VLAN (not shut, not blocked)."""
        record = self.nodes[switch]
        found = []
        for port in record['interfaces']:
            if port == came_in or (switch, port) not in self.peer or (switch, port) in self.blocked:
                continue
            if vlan_plan(record) is None:
                found.append((port, None if vid == 1 else vid))
                continue
            settings = record['switchports'][port]
            if settings['mode'] == 'access':
                if settings['vlan'] == vid:
                    found.append((port, None))
                continue
            allowed = record['vlans'] if settings['allowed'] == 'all' else settings['allowed']
            if vid in allowed or vid == settings['native_vlan']:
                found.append((port, None if vid == settings['native_vlan'] else vid))
        return found

    def frames(self, sender, interface, target=None):
        """The cable crossings of one frame from SENDER's INTERFACE, as [[crossing, …] per step]: to TARGET (node,
        interface) along the switches' path (one crossing per step), or, TARGET None, a broadcast to every port of its
        VLAN (each step the crossings made at once). None when TARGET is out of reach."""
        port, tag = self.attachment(sender, interface)
        goal = self.attachment(*target) if target else None
        parents, layers, seen, reached = {}, [], set(), None
        inside, pending = [], []  # frames inside switches (switch, VLAN, port it came in by, crossing), frames on cables
        if port is None:  # a switch's SVI: the frame starts inside the switch, in the SVI's VLAN
            inside.append((sender, tag, None, None))
            seen.add((sender, tag))
        elif (sender, port) in self.peer:
            far = self.peer[(sender, port)]
            pending.append({'from': sender, 'from_port': port, 'to': far[0], 'to_port': far[1], 'tag': tag})
        while inside or pending:
            for at, vid, came_in, parent in inside:
                for out, out_tag in self.egress(at, vid, came_in):
                    far = self.peer[(at, out)]
                    crossing = {'from': at, 'from_port': out, 'to': far[0], 'to_port': far[1], 'tag': out_tag}
                    parents[id(crossing)] = parent
                    pending.append(crossing)
            inside = []
            if not pending:
                break
            layers.append(pending)
            for crossing in pending:
                at, arrived, ctag = crossing['to'], crossing['to_port'], crossing['tag']
                if target and at == target[0] and goal == (arrived, ctag):
                    reached = crossing
                elif self.nodes[at]['role'] == 'switch':
                    vid = self.classify(at, arrived, ctag)
                    if vid is None or (at, vid) in seen:
                        continue
                    seen.add((at, vid))
                    if target and at == target[0] and goal == (None, vid):
                        reached = crossing
                        continue
                    inside.append((at, vid, arrived, crossing))
            pending = []
            if reached:
                break
        if target is None:
            return layers
        if reached is None:
            return None
        path, crossing = [], reached
        while crossing is not None:
            path.append(crossing)
            crossing = parents.get(id(crossing))
        return [[c] for c in reversed(path)]


def simulate(spec, source, destination, arp=True):
    """{'events': [event], 'ok', 'why'} for « ping DESTINATION » from SOURCE: one event per frame crossing a cable,
    {'step', 'kind' (ARP | ICMP), 'what', 'from', 'from_port', 'to', 'to_port', 'tag', 'layers': {...}, 'arrival'},
    events of one step moving together (a flooded broadcast); a dropped packet ends with an event whose 'drop' says why."""
    model, fabric = Model(spec), _Fabric(spec)
    destination = ipaddress.IPv4Address(destination)
    address = model.source_address(source, destination)
    events, cache, step = [], set(), [0]
    if address is None:
        why = model.route(source, destination)[2]
        return {'events': [_drop(0, source, why)], 'ok': False, 'why': why}
    from .vendor_config import dialect, ios_name, ios_short
    shown = {name: port_names(node) for name, node in fabric.nodes.items()}

    def label(node, port):
        text = shown[node].get(port, port)
        return ios_short(ios_name(text)) if dialect(fabric.nodes[node]) == 'ios' else text

    def emit(layers, kind, what, details, arrival):
        for layer in layers:
            step[0] += 1
            for crossing in layer:
                events.append({'step': step[0], 'kind': kind, 'what': what, **crossing, 'layers': details(crossing),
                               'arrival': arrival(crossing)})

    def resolve(leg, sender_ip):
        """ARP before the first frame from LEG's sender to its next hop."""
        gateway, here, there = leg['gateway'], leg['from'], leg['to']
        if (here, gateway) in cache:
            return
        mac = fabric.mac(here, leg['egress'])
        flood = fabric.frames(here, leg['egress'])
        ask = f'Qui a {gateway} ? Répondre à {sender_ip}'
        emit(flood, 'ARP', 'requête ARP (diffusion)',
             lambda c: {'Couche 2': f'Ethernet II : {mac} → {BROADCAST}' + _tag(c), 'ARP': f'Requête : {ask}'},
             lambda c: _arrival_arp(fabric, c, there, label))
        back = fabric.frames(there, leg['ingress'], (here, leg['egress'])) or []
        there_mac = fabric.mac(there, leg['ingress'])
        emit(back, 'ARP', 'réponse ARP',
             lambda c: {'Couche 2': f'Ethernet II : {there_mac} → {mac}' + _tag(c), 'ARP': f'Réponse : {gateway} est à {there_mac}'},
             lambda c: _arrival(fabric, c, here, label, f'{here} met {gateway} → {there_mac} dans sa table ARP'))
        cache.add((here, gateway))
        cache.add((there, sender_ip))

    def walk(legs, kind, start_ttl):
        for index, leg in enumerate(legs):
            packet = leg['packet']
            held = model.held(leg['from'])
            sender_ip = next((a.ip for i, a in held.items() if _port_of(i) == _port_of(leg['egress'])), packet['source'])
            if arp:
                resolve(leg, sender_ip)
            ttl = start_ttl - index
            source_mac, target_mac = fabric.mac(leg['from'], leg['egress']), fabric.mac(leg['to'], leg['ingress'])
            frames = fabric.frames(leg['from'], leg['egress'], (leg['to'], leg['ingress'])) or []
            last = index == len(legs) - 1
            emit(frames, 'ICMP', kind,
                 lambda c, p=packet, t=ttl, s=source_mac, d=target_mac: {
                     'Couche 2': f'Ethernet II : {s} → {d}' + _tag(c),
                     'Couche 3': f'IPv4 : {p["source"]} → {p["destination"]}, TTL {t}',
                     'Couche 4': 'ICMP Echo Request (type 8)' if kind == 'requête' else 'ICMP Echo Reply (type 0)'},
                 lambda c, leg=leg, last=last, t=ttl: _arrival_ip(model, fabric, c, leg, last, t, label))

    request = {'source': address, 'destination': destination, 'protocol': 'icmp'}
    legs = []
    ok, path, why, tracked, target = model.deliver(source, request, legs=legs)
    walk(legs, 'requête', TTL)
    if not ok:
        events.append(_drop(step[0] + 1, path[-1], why))
        return {'events': events, 'ok': False, 'why': why}
    reply_to = next((after[0] for _, _, after in reversed(tracked) if after[0] != address), address)
    back_legs = []
    back, back_path, why, _, _ = model.deliver(target, {'source': destination, 'destination': reply_to, 'protocol': 'icmp'}, tracked,
                                               legs=back_legs)
    walk(back_legs, 'réponse', TTL)
    if not back:
        events.append(_drop(step[0] + 1, back_path[-1], why))
        return {'events': events, 'ok': False, 'why': why}
    return {'events': events, 'ok': True, 'why': None}


def _tag(crossing):
    return f' · 802.1Q VLAN {crossing["tag"]}' if crossing.get('tag') else ''


def _drop(step, node, why):
    return {'step': step, 'kind': 'DROP', 'what': 'paquet abandonné', 'from': node, 'from_port': None, 'to': node, 'to_port': None,
            'tag': None, 'layers': {}, 'arrival': why, 'drop': why}


def _refused(fabric, crossing, label):
    """Why a switch drops a frame arriving on a port, or None when it takes it."""
    at, port = crossing['to'], crossing['to_port']
    if fabric.nodes[at]['role'] != 'switch' or fabric.classify(at, port, crossing['tag']) is not None:
        return None
    if (at, port) in fabric.blocked:
        return f'{at} rejette la trame : son port {label(at, port)} est bloqué par le spanning tree (BLK)'
    return f'{at} rejette la trame : son port {label(at, port)} ne porte pas ce VLAN'


def _arrival(fabric, crossing, wanted, label, done):
    at, port = crossing['to'], crossing['to_port']
    if fabric.nodes[at]['role'] == 'switch' and at != wanted:
        vid = fabric.classify(at, port, crossing['tag'])
        return _refused(fabric, crossing, label) or f'{at} apprend la MAC source sur {label(at, port)} (VLAN {vid}) et transmet la trame'
    return done if at == wanted else f'{at} ignore la trame'


def _arrival_arp(fabric, crossing, wanted, label):
    at, port = crossing['to'], crossing['to_port']
    if fabric.nodes[at]['role'] == 'switch':
        vid = fabric.classify(at, port, crossing['tag'])
        answer = f'{at} répond (c’est l’adresse de son interface Vlan{vid}) et diffuse' if at == wanted else f'{at} diffuse'
        return _refused(fabric, crossing, label) or f'{answer} la requête sur tous ses ports du VLAN {vid}, sauf {label(at, port)}'
    return f'{at} répond : c’est son adresse' if at == wanted else f'{at} ignore la requête : ce n’est pas son adresse'


def _arrival_ip(model, fabric, crossing, leg, last, ttl, label):
    at, port = crossing['to'], crossing['to_port']
    if at != leg['to']:
        vid = fabric.classify(at, port, crossing['tag'])
        return f'{at} apprend la MAC source sur {label(at, port)} (VLAN {vid}) et transmet la trame vers sa destination'
    if last:
        return f'{at} reçoit le paquet : il lui est adressé'
    destination = leg['packet']['destination']
    out, hop, kind = model.route(at, destination)
    return (f'{at} cherche {destination} dans sa table de routage ({kind}) : sortie par {label(at, _port_of(out))}'
            + (f' vers {hop}' if hop != destination else '') + f', TTL {ttl - 1}')
