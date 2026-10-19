"""VLAN reachability model. No packets or real sockets are emitted."""
from dataclasses import dataclass, field, asdict
from ipaddress import IPv4Interface, IPv4Address
import json

@dataclass
class Node:
    name: str
    kind: str
    x: int = 200
    y: int = 150
    address: str = ''
    gateway: str = ''
    # Router subinterfaces: VLAN ID -> IPv4 CIDR. One trunk per router.
    interfaces: dict = field(default_factory=dict)

@dataclass
class Link:
    a: str
    b: str
    mode: str = 'access'
    vlans: list = field(default_factory=lambda: [1])

class Lab:
    def __init__(self):
        self.nodes = {}
        self.links = []

    def add(self, node):
        if not node.name or node.name in self.nodes:
            raise ValueError('Nom vide ou déjà utilisé.')
        if node.kind not in ('PC', 'Switch', 'Routeur'):
            raise ValueError('Type non pris en charge.')
        self.nodes[node.name] = node

    def connect(self, a, b, mode='access', vlans=None):
        vlans = list(vlans or [1])
        if a == b or a not in self.nodes or b not in self.nodes:
            raise ValueError('Extrémités invalides.')
        if mode not in ('access', 'trunk') or not vlans or any(type(v) is not int or not 1 <= v <= 4094 for v in vlans):
            raise ValueError('Mode ou VLAN invalide.')
        if mode == 'access' and len(vlans) != 1:
            raise ValueError('Un port access appartient à un seul VLAN.')
        if any({l.a, l.b} == {a, b} for l in self.links):
            raise ValueError('Lien déjà présent.')
        for name in (a, b):
            if self.nodes[name].kind != 'Switch' and any(name in (l.a, l.b) for l in self.links):
                raise ValueError('Prototype : un seul lien physique par PC/routeur.')
        if any(self.nodes[n].kind == 'PC' for n in (a, b)) and mode != 'access':
            raise ValueError('Les PC utilisent un lien access.')
        self.links.append(Link(a, b, mode, vlans))

    def path(self, source, target, vlan):
        queue = [(source, [source])]
        seen = {source}
        while queue:
            current, path = queue.pop(0)
            if current == target:
                return path
            if current != source and self.nodes[current].kind != 'Switch':
                continue
            for link in self.links:
                if current not in (link.a, link.b) or vlan not in link.vlans:
                    continue
                other = link.b if current == link.a else link.a
                if other not in seen:
                    seen.add(other)
                    queue.append((other, path + [other]))
        return None

    def vlan(self, name):
        links = [l for l in self.links if name in (l.a, l.b)]
        if not links:
            raise ValueError(f'{name} : aucun câble.')
        return links[0].vlans[0]

    def ping(self, source, destination):
        """Check request AND reply using connected routes only."""
        try:
            src = self.nodes[source]
            if src.kind != 'PC':
                raise ValueError('Sélectionner un PC source.')
            src_ip = IPv4Interface(src.address)
            dst_ip = IPv4Address(destination)
            targets = [n for n in self.nodes.values() if n.kind == 'PC' and n.address and IPv4Interface(n.address).ip == dst_ip]
            if len(targets) != 1:
                raise ValueError('Destination PC absente ou adresse ambiguë.')
            dst = targets[0]
            trace = []
            for a, b in ((src, dst), (dst, src)):
                ai, bi = IPv4Interface(a.address), IPv4Interface(b.address)
                av, bv = self.vlan(a.name), self.vlan(b.name)
                if bi.ip in ai.network:
                    path = self.path(a.name, b.name, av) if av == bv else None
                    if not path:
                        raise ValueError(f'{a.name} : destination locale inaccessible en VLAN {av}.')
                    trace.append('Connectivité L2 : ' + ' → '.join(path))
                    continue
                gateway = IPv4Address(a.gateway)
                if gateway not in ai.network:
                    raise ValueError(f'{a.name} : passerelle hors sous-réseau.')
                found = False
                for router in self.nodes.values():
                    if router.kind != 'Routeur':
                        continue
                    incoming = router.interfaces.get(str(av))
                    outgoing = router.interfaces.get(str(bv))
                    if not incoming or not outgoing:
                        continue
                    ri, ro = IPv4Interface(incoming), IPv4Interface(outgoing)
                    if ri.ip != gateway or bi.ip not in ro.network:
                        continue
                    p1, p2 = self.path(a.name, router.name, av), self.path(router.name, b.name, bv)
                    if p1 and p2:
                        trace.append(f'Route connectée VLAN {av} → {bv} : ' + ' → '.join(p1 + p2[1:]))
                        found = True
                        break
                if not found:
                    raise ValueError(f'{a.name} : passerelle, trunk ou route connectée inaccessible.')
            return True, trace + ['Réussite : aller et retour accessibles (modèle simplifié).']
        except (ValueError, KeyError) as error:
            return False, [str(error)]

    def dumps(self):
        return json.dumps({'version': 1, 'nodes': [asdict(n) for n in self.nodes.values()], 'links': [asdict(l) for l in self.links]}, indent=2)

    @classmethod
    def loads(cls, text):
        data = json.loads(text)
        if data.get('version') != 1:
            raise ValueError('Version de projet incompatible.')
        lab = cls()
        for node in data['nodes']:
            lab.add(Node(**node))
        for link in data['links']:
            lab.connect(**link)
        return lab


def demo():
    lab = Lab()
    for node in (Node('PC1', 'PC', 120, 160, '192.168.10.10/24', '192.168.10.1'), Node('PC2', 'PC', 120, 350, '192.168.20.10/24', '192.168.20.1'), Node('SW1', 'Switch', 380, 250), Node('R1', 'Routeur', 650, 250, interfaces={'10': '192.168.10.1/24', '20': '192.168.20.1/24'})):
        lab.add(node)
    lab.connect('PC1', 'SW1', vlans=[10])
    lab.connect('PC2', 'SW1', vlans=[20])
    lab.connect('SW1', 'R1', 'trunk', [10, 20])
    return lab
