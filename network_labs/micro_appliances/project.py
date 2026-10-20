"""Execute an explicit, supported component of the user's project in Wasm.

No model path/fdb/firewall helpers are used. Instances are fresh per request;
only the bounded capture and counters survive, without retaining guest Stores.
"""
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Interface
from .runtime import Fabric, ApplianceFault, DependencyMissing
from .experiment import echo_ping, memory_sample
from .packets import describe

RAM_TARGET = 2 * 1024 ** 3
MAX_NODES = 256


@dataclass
class Capture:
    frames: list
    counters: dict
    port_names: dict
    request: dict

    def stats(self):
        return self.counters

    def write_pcap(self, path):
        Fabric.write_pcap(self, path)


def component(lab, source):
    if source not in lab.nodes or lab.nodes[source].kind != 'PC':
        raise ValueError('Sélectionner un endpoint comme source Wasm.')
    names = {source}
    while True:
        expanded = names | {n for link in lab.links if link.a in names or link.b in names for n in (link.a, link.b)}
        if expanded == names:
            break
        names = expanded
    return sorted(names), [l for l in lab.links if l.a in names and l.b in names]


def validate(lab, source):
    """Fail closed on unsupported forwarding/configuration, before instantiation."""
    from ..profiles import PROFILES, profile_role
    names, links = component(lab, source)
    if len(names) > MAX_NODES:
        raise ValueError('Wasm : maximum 256 équipements dans la composante exécutée.')
    addresses = set()
    network = None
    for name in names:
        node = lab.nodes[name]
        if node.kind not in ('PC', 'Switch') or profile_role(PROFILES[node.profile]) == 'Firewall':
            raise ValueError(name + ' : routeur/firewall pas encore porté vers Wasm. Choisir le moteur pédagogique.')
        if node.kind == 'PC':
            try:
                address = IPv4Interface(node.address)
            except ValueError as error:
                raise ValueError(name + ' : adresse IPv4 statique /24 requise pour Wasm.') from error
            if address.network.prefixlen != 24 or node.address_mode != 'static':
                raise ValueError(name + ' : IPv4 statique /24 requise ; DHCP pas encore porté.')
            if address.ip in (address.network.network_address, address.network.broadcast_address) or address.ip in addresses:
                raise ValueError(name + ' : adresse hôte invalide ou IPv4 dupliquée.')
            addresses.add(address.ip)
            if network is not None and network != address.network:
                raise ValueError('Wasm : un seul sous-réseau IPv4 /24 dans la composante exécutée.')
            network = address.network
        elif node.dhcp_snooping or node.dai_vlans or node.dot1x_enabled or node.dhcp_pools or node.vtp_mode not in ('transparent', 'off'):
            raise ValueError(name + ' : DHCP/protections/802.1X/VTP pas encore portés vers Wasm.')
    # Reject active L2 loops. STP is not silently approximated by a model path.
    parent = {n:n for n in names}
    def root(n):
        while parent[n] != n:
            n = parent[n]
        return n
    for link in links:
        if not link.a_port or not link.b_port:
            raise ValueError('Wasm : chaque câble doit identifier ses ports.')
        active = link.enabled
        for name, port_name in ((link.a, link.a_port), (link.b, link.b_port)):
            node = lab.nodes[name]
            port = node.ports[port_name]
            if port.mode != 'access' or port.access_vlan != 1:
                raise ValueError(name + '/' + port_name + ' : Wasm supporte seulement access VLAN 1 ; trunk/VLAN pas encore portés.')
            if port.channel or port.security or port.bpduguard or port.auth_control != 'force-authorized' or port.authenticator or port.source_guard:
                raise ValueError(name + '/' + port_name + ' : agrégation/protection de port pas encore portée vers Wasm.')
            active = active and not port.shutdown and not port.errdisabled
        if active:
            a, b = root(link.a), root(link.b)
            if a == b:
                raise ValueError('Wasm : boucle Ethernet active ; STP pas encore porté. Désactiver une liaison.')
            parent[a] = b
    return names, links


def endpoint_mac(lab, name):
    names, _ = component(lab, name)
    identity = names.index(name) + 1
    return f'02:00:00:00:{identity >> 8:02x}:{identity & 255:02x}'


def execute(lab, source, destination, protocol='icmp', port=0):
    lab.last_micro_capture = None
    lab.last_micro_error = ''
    fabric = None
    trace = ['Wasm · topologie du projet · nouvelles instances pour ce test · aucun OS invité.']
    try:
        try:
            target = str(IPv4Address(destination))  # No synthetic DNS resolution.
        except ValueError as error:
            raise ValueError('Wasm : destination IPv4 littérale requise ; DNS pas encore porté.') from error
        if protocol not in ('icmp', 'tcp') or protocol == 'tcp' and int(port) != 8080:
            raise ValueError('Wasm : ICMP et TCP echo/8080 uniquement ; DNS/UDP/autres services pas encore portés.')
        names, links = validate(lab, source)
        rss = memory_sample().get('rss_bytes', 0)
        if rss >= RAM_TARGET:
            raise ValueError('Budget cible de 2 Gio déjà atteint : fermer des fenêtres ou réduire le projet avant un nouveau test.')
        server = next((n for n in names if lab.nodes[n].kind == 'PC' and str(IPv4Interface(lab.nodes[n].address).ip) == target and 'tcp/8080' in lab.nodes[n].services), None) if protocol == 'tcp' else None
        fabric = Fabric()
        ports = {}
        for identity, name in enumerate(names, 1):
            node = lab.nodes[name]
            # Keep physical names and all switch ports; GUI/CLI config is canonical.
            physical = [p for p in node.ports if '.' not in p and not p.startswith('po')]
            if node.kind == 'PC' and len(physical) != 1:
                raise ValueError(name + ' : une seule NIC endpoint est supportée.')
            ports[name] = {p:i for i,p in enumerate(physical)}
            role = 1 if node.kind == 'Switch' else 2 if name == server else 0
            address = '0.0.0.0' if node.kind == 'Switch' else str(IPv4Interface(node.address).ip)
            fabric.add(name, role, address, identity, len(physical))
        for link in links:
            ap, bp = ports[link.a][link.a_port], ports[link.b][link.b_port]
            fabric.connect(link.a, ap, link.b, bp)
            active = link.enabled and all(not lab.nodes[n].ports[p].shutdown and not lab.nodes[n].ports[p].errdisabled for n,p in ((link.a, link.a_port), (link.b, link.b_port)))
            if not active:
                fabric.set_link_enabled(link.a, ap, False)
        if protocol == 'icmp':
            ok = echo_ping(fabric, source, target)['ok']
            result = 'ICMP : réponse vérifiée reçue.' if ok else 'ICMP : aucune réponse avant le délai virtuel.'
        else:
            payload = b'Network-LABS project TCP echo'
            client = fabric.nodes[source]
            client.connect(target, 8080, payload)
            ok = fabric.run_until(lambda:client.reply() == payload)
            result = 'TCP/8080 : handshake et données echo aller-retour vérifiés.' if ok else 'TCP/8080 : aucun écho reçu (liaison, adresse ou service echo non activé).'
        # Retain bytes and counters only; no live guest state or host callbacks.
        counters = fabric.stats()
        counters['process_memory'] = memory_sample()
        counters['ram_target_bytes'] = RAM_TARGET
        reverse_ports = {n:{i:p for p,i in mapping.items()} for n,mapping in ports.items()}
        lab.last_micro_capture = Capture(list(fabric.frames), counters, reverse_ports,
                                        {'source':source, 'destination':target, 'protocol':protocol, 'port':int(port)})
        lookup = {frozenset(((l.a, ports[l.a][l.a_port]), (l.b, ports[l.b][l.b_port]))):i for i,l in enumerate(lab.links) if l in links}
        lab.last_hops = [[(lookup[frozenset(((f.source,f.source_port),(f.destination,f.destination_port)))], f.source, f.destination, 1) for f in fabric.frames]] if fabric.frames else []
        trace += [f'{len(names)} instances · {len(fabric.frames)} observations Ethernet · {counters["linear_memory_bytes"]//1024} Kio de capacité linéaire.', result]
        return ok, trace
    except (ValueError, KeyError, ApplianceFault, DependencyMissing, OSError) as error:
        lab.last_hops, lab.last_paths, lab.events = [], [], []
        lab.last_micro_error = str(error)
        return False, trace + [str(error)]
    finally:
        if fabric is not None:
            fabric.close()


def explain(lab, ok, trace):
    request = lab.last_request
    capture = getattr(lab, 'last_micro_capture', None)
    steps = []
    def add(title, body, phase='Préparation', evidence=''):
        steps.append({'number':len(steps)+1, 'phase':phase, 'title':title, 'body':body, 'evidence':evidence})
    add('Exécution du projet dans Wasm', trace[0], evidence='États ARP/TCP et commutation dans les invités ; transport des octets par le runtime.')
    if capture:
        for frame in capture.frames:
            packet = describe(frame)
            ap = capture.port_names[frame.source][frame.source_port]
            bp = capture.port_names[frame.destination][frame.destination_port]
            add(frame.source+' → '+frame.destination, packet.get('explanation',packet['protocol']), 'Trames',
                f'{frame.time_ms} ms virtuelles · {ap} → {bp} · {len(frame.data)} octets · '+packet['protocol'])
        learned = [n for n in capture.counters['nodes'] if n['role'] == 'switch']
        if learned:
            add('Apprentissage MAC', ' · '.join(n['name']+' : '+str(n['learned_macs'])+' MAC apprises' for n in learned), 'État invité')
    add('Résultat : réussi' if ok else 'Résultat : interrompu', trace[-1], 'Résultat')
    return {'title':request['source']+' → '+request['destination']+' · Wasm', 'ok':ok,
            'summary':trace[-1], 'steps':steps,
            'checks':[] if ok else ['Lire le diagnostic et les trames observées. Aucun repli automatique vers le moteur pédagogique.'],
            'limits':'Instances recréées à chaque test. LAN access VLAN 1 / IPv4 statique /24 ; ICMP ou TCP echo/8080. Horloge virtuelle, aucun trafic réseau hôte. La capture observe chaque sortie de port connecté, avec doublons entre liaisons.'}


def demo():
    from ..engine import Lab, Node
    lab = Lab()
    for node in (Node('PC1','PC',130,180,'192.168.50.10/24',profile='windows-11'),
                 Node('SW1','Switch',410,230,profile='cisco-2960'),
                 Node('SRV1','PC',720,180,'192.168.50.20/24',profile='server-linux',services={'tcp/8080':'Wasm echo'})):
        lab.add(node)
    lab.connect('PC1','SW1');lab.connect('SW1','SRV1')
    lab.execution_backend = 'wasm'
    return lab
