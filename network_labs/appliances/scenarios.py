"""Generated troubleshooting scenarios: numbered micro-VM networks, each with one random fault and no hint by default.

scenario(N) always builds the same lab for the same number. A family (routed chain, star around a core router,
VLAN campus, Internet exit behind a firewall) is drawn with random size, addressing, names, vendors and routing
(static or OSPF), then one fault from a shared catalogue (routes, next hops, addresses, gateways, OSPF, VLANs,
trunks, subinterfaces, cabling, firewall rules and NAT). The network model (network_model.py) keeps only faults
that change what the network does, sets what every probe should give, grades a repair by behaviour (any
correct fix passes) and builds the help a student can ask for, one step at a time.
"""
import copy
import ipaddress
from pathlib import Path
import random

from .network_model import Model
from .spec import validate

COUNT = 1200
FAMILIES = ('chaine', 'etoile', 'campus', 'sortie')
FAMILY_TITLES = {'chaine': 'Sites en chaîne', 'etoile': 'Étoile autour d’un cœur de réseau', 'campus': 'Campus et VLAN',
                 'sortie': 'Sortie Internet derrière un pare-feu'}
OSPF_ROUTERS = ('cisco-isr4331', 'cisco-ios-router', 'juniper-mx204', 'huawei-ar6120', 'arista-7280r')
STATIC_ROUTERS = OSPF_ROUTERS + ('mikrotik-ccr', 'mikrotik-chr')
STICK_ROUTERS = ('cisco-isr4331', 'cisco-ios-router')
SWITCHES = ('cisco-9200l', 'cisco-2960', 'arista-7050', 'huawei-s5700')
FIREWALLS = ('fortigate', 'palo-alto')
SITES = ('Paris', 'Lyon', 'Lille', 'Nantes', 'Brest', 'Nice', 'Dijon', 'Metz', 'Tours', 'Rouen', 'Caen', 'Pau', 'Reims', 'Annecy')
HOSTS = ('PC-Compta', 'PC-RH', 'PC-Direction', 'PC-Accueil', 'PC-Atelier', 'PC-Labo', 'PC-Dev', 'PC-Support', 'PC-Ventes',
         'Srv-Web', 'Srv-Fichiers', 'Srv-Mail', 'Srv-DNS', 'Srv-Backup', 'Caisse', 'NAS', 'Camera', 'Borne')
OUTSIDE = ('Web-Externe', 'DNS-Public', 'Cloud-Mail', 'Site-Partenaire', 'Serveur-Mises-a-jour')
HELP_STEPS = 5
MAX_PROBES = 12


def _ports(count):
    return [f'eth{i}' for i in range(count)]


class _Plan:
    """A lab being drawn: nodes, cables, an address plan and the routers' transit links."""

    def __init__(self, rng, kernel, disk, number):
        self.rng, self.number = rng, number
        self.base = {'runtime': 'firecracker', 'kernel': str(Path(kernel).resolve()), 'disk': str(Path(disk).resolve()),
                     'memory_mib': 64, 'vcpus': 1}
        self.nodes, self.links, self.transits, self.lans = [], [], [], {}
        self.hosts = list(HOSTS)
        rng.shuffle(self.hosts)
        self.sites = list(SITES)
        rng.shuffle(self.sites)
        style = rng.choice(('10', '172', '192'))
        a, b = rng.randrange(1, 250), rng.randrange(0, 120)
        self.lan_prefix = {'10': lambda i: f'10.{a}.{b + i}', '172': lambda i: f'172.{16 + a % 16}.{b + i}',
                           '192': lambda i: f'192.168.{b + i}'}[style]
        self.transit_block = ipaddress.IPv4Network({'10': f'10.{a}.250.0/24', '172': f'172.{16 + a % 16}.250.0/24',
                                                    '192': f'192.168.{b + 130}.0/24'}[style])
        self.gateway_host = rng.choice((1, 254))
        self.lan_count = 0

    def node(self, name, role, **fields):
        node = dict(self.base, name=name, role=role, **fields)
        self.nodes.append(node)
        return node

    def find(self, name):
        return next(n for n in self.nodes if n['name'] == name)

    def link(self, a, pa, b, pb):
        self.links.append([[a, pa], [b, pb]])

    def free_port(self, name):
        used = {end[1] for link in self.links for end in link if end[0] == name}
        return next(p for p in self.find(name)['interfaces'] if p not in used)

    def new_lan(self):
        self.lan_count += 1
        return ipaddress.IPv4Network(self.lan_prefix(self.lan_count) + '.0/24')

    def host(self, network, gateway=None, name=None):
        name = name or self.hosts.pop()
        used = {ipaddress.IPv4Interface(a).ip for n in self.nodes for a in n['interfaces'].values() if a}
        free = [h for h in network.hosts() if h not in used and h != network.network_address + self.gateway_host
                and int(h) - int(network.network_address) >= min(10, network.num_addresses // 4)]
        address = self.rng.choice(free)
        fields = {'interfaces': {'eth0': f'{address}/{network.prefixlen}'}}
        if gateway:
            fields['gateway'] = str(gateway)
        self.node(name, 'host', **fields)
        return name

    def lan(self, router, port, hosts=1, switch_model=None):
        """A LAN on ROUTER's PORT: one host on the cable, or a plain switch with HOSTS hosts."""
        network = self.new_lan()
        gateway = network.network_address + self.gateway_host
        self.find(router)['interfaces'][port] = f'{gateway}/{network.prefixlen}'
        self.lans[(router, port)] = network
        if hosts == 1:
            name = self.host(network, gateway)
            self.link(router, port, name, 'eth0')
            return [name]
        switch = f'SW-{router.split("-")[-1]}'
        self.node(switch, 'switch', model=switch_model or self.rng.choice(SWITCHES), interfaces={p: '' for p in _ports(hosts + 1)})
        self.link(router, port, switch, 'eth0')
        names = []
        for index in range(hosts):
            name = self.host(network, gateway)
            self.link(switch, f'eth{index + 1}', name, 'eth0')
            names.append(name)
        return names

    def transit(self, left, right):
        network = list(self.transit_block.subnets(new_prefix=30))[len(self.transits)]
        first, second = list(network.hosts())
        lp, rp = self.free_port(left), self.free_port(right)
        self.find(left)['interfaces'][lp] = f'{first}/30'
        self.find(right)['interfaces'][rp] = f'{second}/30'
        self.link(left, lp, right, rp)
        self.transits.append((left, lp, first, right, rp, second))

    def routing(self, routers, kind):
        """Static routes to every LAN (shortest path over the transit links), or OSPF everywhere."""
        if kind == 'ospf':
            for index, name in enumerate(routers, 1):
                node = self.find(name)
                lan_ports = {port for (router, port) in self.lans if router == name}
                node['ospf'] = {'router_id': f'{index}.{index}.{index}.{index}',
                                'interfaces': {port: {'cost': 10, 'passive': port in lan_ports}
                                               for port, address in node['interfaces'].items() if address}}
            return
        neighbours = {name: [] for name in routers}
        for left, _, first, right, _, second in self.transits:
            neighbours[left].append((right, second))
            neighbours[right].append((left, first))
        for name in routers:
            first_hop, queue = {name: None}, [name]
            while queue:
                here = queue.pop(0)
                for other, address in neighbours[here]:
                    if other not in first_hop:
                        first_hop[other] = address if here == name else first_hop[here]
                        queue.append(other)
            wanted = [{'network': str(network), 'gateway': str(first_hop[router])}
                      for (router, _), network in self.lans.items() if router != name and router in first_hop]
            if wanted:
                self.find(name)['guest_network'] = {'addresses': [], 'routes': sorted(wanted, key=lambda r: r['network'])}

    def spec(self, title):
        return {'version': 1, 'name': f'scenario-{self.number:04d}', 'budget_mib': 2048, 'reserve_mib': 512,
                'nodes': self.nodes, 'links': self.links, 'title': title}


# ---- families ----

def _routers(plan, count, kind):
    models = OSPF_ROUTERS if kind == 'ospf' else STATIC_ROUTERS
    names = [f'R-{plan.sites[i]}' for i in range(count)]
    for name in names:
        plan.node(name, 'router', model=plan.rng.choice(models), interfaces={p: '' for p in _ports(3)})
    return names


def _trim(plan):
    """Routers keep only the ports they use (contiguous eth0..), so every port is numbered."""
    for node in plan.nodes:
        if node['role'] == 'router':
            used = {end[1] for link in plan.links for end in link if end[0] == node['name']}
            node['interfaces'] = {p: a for p, a in node['interfaces'].items() if p in used}


def _chaine(plan):
    rng = plan.rng
    kind = rng.choice(('statique', 'ospf'))
    routers = _routers(plan, rng.choice((2, 3, 3, 4)), kind)
    for left, right in zip(routers, routers[1:]):
        plan.transit(left, right)
    plan.lan(routers[0], plan.free_port(routers[0]), hosts=rng.choice((1, 1, 2)))
    plan.lan(routers[-1], plan.free_port(routers[-1]), hosts=rng.choice((1, 2)))
    if len(routers) > 2 and rng.random() < .5:
        middle = rng.choice(routers[1:-1])
        plan.lan(middle, plan.free_port(middle))
    _trim(plan)
    plan.routing(routers, kind)
    return f'{len(routers)} sites en chaîne · routage {kind}', ['ospf'] if kind == 'ospf' else []


def _etoile(plan):
    rng = plan.rng
    kind = rng.choice(('statique', 'ospf'))
    branches = rng.choice((2, 3))
    core = _routers(plan, 1, kind)[0]
    plan.find(core)['interfaces'] = {p: '' for p in _ports(4)}
    plan.find(core)['model'] = rng.choice(('juniper-mx204', 'huawei-ar6120', 'arista-7280r', 'cisco-ios-router'))
    routers = [core]
    for index in range(branches):
        edge = f'R-{plan.sites[index + 1]}'
        plan.node(edge, 'router', model=rng.choice(OSPF_ROUTERS if kind == 'ospf' else STATIC_ROUTERS),
                  interfaces={p: '' for p in _ports(2)})
        routers.append(edge)
        plan.transit(core, edge)
        plan.lan(edge, plan.free_port(edge))
    if rng.random() < .6:
        plan.lan(core, plan.free_port(core), hosts=rng.choice((1, 2)))
    _trim(plan)
    plan.routing(routers, kind)
    return f'cœur et {branches} sites · routage {kind}', ['ospf'] if kind == 'ospf' else []


def _campus(plan):
    rng = plan.rng
    vids = sorted(rng.sample((10, 20, 30, 40, 50, 100, 110, 200), rng.choice((2, 3))))
    networks = {vid: plan.new_lan() for vid in vids}
    routed = rng.random() < .65
    two = rng.random() < .6
    switches = ['SW-Bat-A'] + (['SW-Bat-B'] if two else [])
    for name in switches:
        plan.node(name, 'switch', model=rng.choice(SWITCHES), interfaces={p: '' for p in _ports(4)}, vlans=[1, *vids],
                  switchports={})
    def access(switch, vid):
        port = plan.free_port(switch)
        gateway = networks[vid].network_address + plan.gateway_host if routed else None
        name = plan.host(networks[vid], gateway)
        plan.find(switch)['switchports'][port] = {'mode': 'access', 'vlan': vid}
        plan.link(switch, port, name, 'eth0')
    if routed:
        router = f'R-{plan.sites[0]}'
        subs = {f'eth0.{vid}': {'parent': 'eth0', 'vlan': vid,
                                'address': f'{networks[vid].network_address + plan.gateway_host}/{networks[vid].prefixlen}'}
                for vid in vids}
        plan.node(router, 'router', model=rng.choice(STICK_ROUTERS), interfaces={'eth0': ''}, subinterfaces=subs)
        port = plan.free_port(switches[0])
        plan.find(switches[0])['switchports'][port] = {'mode': 'trunk', 'native_vlan': 1, 'allowed': list(vids)}
        plan.link(switches[0], port, router, 'eth0')
    if two:
        a, b = plan.free_port(switches[0]), plan.free_port(switches[1])
        for name, port in ((switches[0], a), (switches[1], b)):
            plan.find(name)['switchports'][port] = {'mode': 'trunk', 'native_vlan': 1, 'allowed': list(vids)}
        plan.link(switches[0], a, switches[1], b)
    order = list(vids) + [rng.choice(vids) for _ in range(5)]
    for switch in switches:
        while any(p not in plan.find(switch)['switchports'] for p in plan.find(switch)['interfaces']) and order:
            access(switch, order.pop(0))
    for name in switches:  # a switch keeps its used ports only
        node = plan.find(name)
        node['interfaces'] = {p: '' for p in node['interfaces'] if p in node['switchports']}
    title = f'{len(switches)} switch{"es" if two else ""}, VLAN {", ".join(map(str, vids))}'
    return title + (' · routage inter-VLAN sur un lien' if routed else ' · VLAN isolés'), ['802.1q']


def _sortie(plan):
    rng = plan.rng
    firewall = 'FW-' + plan.sites[0]
    plan.node(firewall, 'firewall', model=rng.choice(FIREWALLS), interfaces={'eth0': '', 'eth1': ''})
    inside = plan.lan(firewall, 'eth0', hosts=rng.choice((1, 2)))
    inside_net = plan.lans[(firewall, 'eth0')]
    outside = ipaddress.IPv4Network(f'203.0.113.{rng.choice((0, 64, 128))}/26')
    public = list(outside.hosts())
    plan.find(firewall)['interfaces']['eth1'] = f'{public[0]}/26'
    isp = rng.random() < .5
    servers_net = ipaddress.IPv4Network(f'198.51.100.{rng.choice((0, 128))}/25')
    if isp:
        router = 'R-FAI'
        plan.node(router, 'router', model=rng.choice(STATIC_ROUTERS), interfaces={'eth0': f'{public[1]}/26', 'eth1': ''})
        plan.link(firewall, 'eth1', router, 'eth0')
        server_gateway = servers_net.network_address + 1
        plan.find(router)['interfaces']['eth1'] = f'{server_gateway}/25'
        server = plan.host(servers_net, server_gateway, name=rng.choice(OUTSIDE))
        plan.link(router, 'eth1', server, 'eth0')
        plan.find(firewall)['guest_network'] = {'addresses': [], 'routes': [{'network': '0.0.0.0/0', 'gateway': str(public[1])}]}
        target = plan.find(server)['interfaces']['eth0'].split('/')[0]
    else:
        server = plan.host(outside, name=rng.choice(OUTSIDE))
        plan.link(firewall, 'eth1', server, 'eth0')
        target = plan.find(server)['interfaces']['eth0'].split('/')[0]
    rules = [{'name': 'lan-vers-internet', 'in': 'eth0', 'out': 'eth1', 'source': str(inside_net), 'protocol': 'icmp', 'action': 'accept'}]
    nat = [{'name': 'masquer-le-lan', 'type': 'masquerade', 'out': 'eth1', 'source': str(inside_net), 'protocol': 'any'}]
    published = None
    if rng.random() < .5:
        published = rng.choice(inside)
        private = plan.find(published)['interfaces']['eth0'].split('/')[0]
        rules.append({'name': 'publier-' + published.lower(), 'in': 'eth1', 'out': 'eth0', 'destination': f'{private}/32',
                      'protocol': 'icmp', 'action': 'accept'})
        nat.append({'name': 'vip-' + published.lower(), 'type': 'dnat', 'in': 'eth1', 'destination': f'{public[0]}/32',
                    'protocol': 'icmp', 'to': private})
    plan.find(firewall)['firewall'] = {'default': 'drop', 'stateful': True, 'rules': rules, 'nat': nat}
    plan.extra_probes = [(server, str(public[0]))] if published else []
    plan.extra_probes.append((inside[0], target))
    return ('LAN, pare-feu et ' + ('fournisseur d’accès' if isp else 'Internet') + (' · serveur publié' if published else '')), ['firewall']


BUILDERS = {'chaine': _chaine, 'etoile': _etoile, 'campus': _campus, 'sortie': _sortie}


# ---- faults: each draws one change in a copy of the working lab, or returns None when it does not apply ----

def _nodes(spec, role=None, test=lambda n: True):
    return [n for n in spec['nodes'] if (role is None or n['role'] == role) and test(n)]


def _shown(node, port):
    from .native_models import port_names
    parent, dot, vid = port.partition('.')
    return port_names(node).get(parent, parent) + dot + vid


def _route_missing(spec, rng):
    routers = _nodes(spec, 'router', lambda n: (n.get('guest_network') or {}).get('routes'))
    if not routers:
        return None
    node = rng.choice(routers)
    route = rng.choice(node['guest_network']['routes'])
    node['guest_network']['routes'].remove(route)
    return {'node': node['name'], 'category': 'Route statique manquante',
            'answer': f'{node["name"]} n’a plus sa route vers {route["network"]} (via {route["gateway"]}).'}


def _route_hop(spec, rng):
    routers = _nodes(spec, 'router', lambda n: len((n.get('guest_network') or {}).get('routes', [])) and
                     len([a for a in n['interfaces'].values() if a and a.endswith('/30')]) >= 2)
    if not routers:
        return None
    node = rng.choice(routers)
    route = rng.choice(node['guest_network']['routes'])
    others = []
    for link in spec['links']:
        for mine, peer in (link, link[::-1]):
            if mine[0] == node['name'] and node['interfaces'].get(mine[1], '').endswith('/30'):
                peer_node = next(n for n in spec['nodes'] if n['name'] == peer[0])
                address = peer_node['interfaces'].get(peer[1], '').split('/')[0]
                if address and address != route['gateway']:
                    others.append(address)
    if not others:
        return None
    wrong = rng.choice(others)
    right = route['gateway']
    route['gateway'] = wrong
    return {'node': node['name'], 'category': 'Route statique vers le mauvais voisin',
            'answer': f'Sur {node["name"]}, la route vers {route["network"]} passe par {wrong} au lieu de {right}.'}


def _gateway_address(spec, rng):
    gateways = {n['gateway'] for n in spec['nodes'] if n.get('gateway')}
    candidates = [(n, p) for n in _nodes(spec, 'router') + _nodes(spec, 'firewall') for p, a in n['interfaces'].items()
                  if a and a.split('/')[0] in gateways]
    if not candidates:
        return None
    node, port = rng.choice(candidates)
    current = ipaddress.IPv4Interface(node['interfaces'][port])
    used = {ipaddress.IPv4Interface(a).ip for n in spec['nodes'] for a in n['interfaces'].values() if a}
    choices = [h for h in current.network.hosts() if h not in used]
    wrong = rng.choice(choices[:60] + choices[-60:])
    node['interfaces'][port] = f'{wrong}/{current.network.prefixlen}'
    if node.get('dhcp_server'):
        return None
    return {'node': node['name'], 'category': 'Adresse d’interface',
            'answer': f'{node["name"]} {_shown(node, port)} a l’adresse {wrong} au lieu de {current.ip} (la passerelle des postes).'}


def _transit_address(spec, rng):
    routers = _nodes(spec, 'router', lambda n: any(a.endswith('/30') for a in n['interfaces'].values() if a))
    if not routers:
        return None
    node = rng.choice(routers)
    port = rng.choice([p for p, a in node['interfaces'].items() if a and a.endswith('/30')])
    current = ipaddress.IPv4Interface(node['interfaces'][port])
    wrong = ipaddress.IPv4Interface(f'{current.network.network_address + 1 + 252 - (int(current.network.network_address) % 256) % 252}/30')
    if wrong.network.overlaps(current.network) or any(ipaddress.IPv4Interface(a).network.overlaps(wrong.network)
                                                    for n in spec['nodes'] for a in n['interfaces'].values() if a):
        return None
    node['interfaces'][port] = str(wrong)
    if node.get('guest_network'):
        node['guest_network']['routes'] = [r for r in node['guest_network']['routes']
                                           if any(ipaddress.IPv4Address(r['gateway']) in ipaddress.IPv4Interface(a).network
                                                  for a in node['interfaces'].values() if a)]
    if node.get('ospf'):
        node['ospf']['networks'] = [n for n in node['ospf'].get('networks', []) if n != str(current.network)] + [str(wrong.network)]
    return {'node': node['name'], 'category': 'Adresse d’interface (lien entre routeurs)',
            'answer': f'{node["name"]} {_shown(node, port)} est en {wrong} au lieu de {current} : plus sur le réseau de son voisin.'}


def _host_gateway(spec, rng):
    hosts = _nodes(spec, 'host', lambda n: n.get('gateway'))
    if not hosts:
        return None
    node = rng.choice(hosts)
    network = ipaddress.IPv4Interface(node['interfaces']['eth0']).network
    used = {ipaddress.IPv4Interface(a).ip for n in spec['nodes'] for a in n['interfaces'].values() if a}
    wrong = rng.choice([h for h in network.hosts() if h not in used])
    right, node['gateway'] = node['gateway'], str(wrong)
    return {'node': node['name'], 'category': 'Passerelle du poste',
            'answer': f'La passerelle de {node["name"]} est {wrong} au lieu de {right}.'}


def _ospf_passive(spec, rng):
    from .ospf import enabled_interfaces
    candidates = [(n, p) for n in _nodes(spec, 'router', lambda n: n.get('ospf'))
                  for p, v in enabled_interfaces(n).items() if not v['passive']]
    if not candidates:
        return None
    node, port = rng.choice(candidates)
    node['ospf']['interfaces'][port]['passive'] = True
    return {'node': node['name'], 'category': 'OSPF : interface passive',
            'answer': f'Sur {node["name"]}, {_shown(node, port)} est passive : pas de voisin OSPF sur ce lien.'}


def _ospf_network(spec, rng):
    from .ospf import enabled_interfaces
    candidates = [(n, p) for n in _nodes(spec, 'router', lambda n: n.get('ospf')) for p in enabled_interfaces(n)
                  if sum(1 for v in enabled_interfaces(n).values() if not v['passive']) > (0 if enabled_interfaces(n)[p]['passive'] else 1)]
    if not candidates:
        return None
    node, port = rng.choice(candidates)
    network = str(ipaddress.IPv4Interface(node['interfaces'][port]).network)
    node['ospf']['networks'] = [n for n in node['ospf']['networks'] if n != network]
    node['ospf']['interfaces'].pop(port)
    return {'node': node['name'], 'category': 'OSPF : réseau non annoncé',
            'answer': f'{node["name"]} n’active plus OSPF sur {_shown(node, port)} ({network}).'}


def _ospf_off(spec, rng):
    routers = _nodes(spec, 'router', lambda n: n.get('ospf'))
    if not routers:
        return None
    node = rng.choice(routers)
    node['ospf'] = None
    return {'node': node['name'], 'category': 'OSPF absent', 'answer': f'OSPF a été retiré de {node["name"]}.'}


def _access_vlan(spec, rng):
    candidates = [(n, p, s) for n in _nodes(spec, 'switch') for p, s in (n.get('switchports') or {}).items() if s['mode'] == 'access'
                  and len(n['vlans']) > 2]
    if not candidates:
        return None
    node, port, switchport = rng.choice(candidates)
    wrong = rng.choice([v for v in node['vlans'] if v not in (1, switchport['vlan'])])
    right, switchport['vlan'] = switchport['vlan'], wrong
    return {'node': node['name'], 'category': 'VLAN d’un port d’accès',
            'answer': f'Sur {node["name"]}, {_shown(node, port)} est en VLAN {wrong} au lieu de {right}.'}


def _trunk_vlan(spec, rng):
    candidates = [(n, p, s) for n in _nodes(spec, 'switch') for p, s in (n.get('switchports') or {}).items()
                  if s['mode'] == 'trunk' and s['allowed'] != 'all' and len(s['allowed']) > 1]
    if not candidates:
        return None
    node, port, switchport = rng.choice(candidates)
    missing = rng.choice(switchport['allowed'])
    switchport['allowed'] = [v for v in switchport['allowed'] if v != missing]
    return {'node': node['name'], 'category': 'Trunk 802.1Q',
            'answer': f'Le trunk {_shown(node, port)} de {node["name"]} ne porte plus le VLAN {missing}.'}


def _subinterface(spec, rng):
    candidates = [(n, name, sub) for n in _nodes(spec, 'router') for name, sub in (n.get('subinterfaces') or {}).items()]
    if not candidates:
        return None
    node, name, sub = rng.choice(candidates)
    others = [s['vlan'] for s in node['subinterfaces'].values()]
    wrong = rng.choice([v for v in (10, 20, 30, 40, 50, 60, 99, 100, 110, 200) if v not in others])
    right, sub['vlan'] = sub['vlan'], wrong
    return {'node': node['name'], 'category': 'Sous-interface 802.1Q',
            'answer': f'Sur {node["name"]}, la sous-interface {_shown(node, name)} est étiquetée {wrong} au lieu de {right}.'}


def _cables(spec, rng):
    """Two hosts in different VLANs plugged into each other's switch port."""
    pairs = []
    for node in _nodes(spec, 'switch'):
        ports = node.get('switchports') or {}
        hosts = {n['name'] for n in spec['nodes'] if n['role'] == 'host'}
        cabled = [(i, link) for i, link in enumerate(spec['links']) if link[0][0] == node['name'] and link[1][0] in hosts
                  and ports.get(link[0][1], {}).get('mode') == 'access']
        pairs += [(a, b) for a in cabled for b in cabled if a[0] < b[0] and ports[a[1][0][1]]['vlan'] != ports[b[1][0][1]]['vlan']]
    if not pairs:
        return None
    (i, first), (j, second) = rng.choice(pairs)
    spec['links'][i], spec['links'][j] = [first[0], second[1]], [second[0], first[1]]
    switch = first[0][0]
    return {'node': switch, 'category': 'Câblage',
            'answer': f'Les câbles de {first[1][0]} et {second[1][0]} sont inversés sur {switch} '
                      f'({first[0][1]} et {second[0][1]} ne sont pas dans le même VLAN).'}


def _firewall_rule(spec, rng):
    firewalls = _nodes(spec, 'firewall', lambda n: (n.get('firewall') or {}).get('rules'))
    if not firewalls:
        return None
    node = rng.choice(firewalls)
    rule = rng.choice(node['firewall']['rules'])
    if rng.random() < .5:
        node['firewall']['rules'].remove(rule)
        answer = f'La règle {rule["name"]} a été supprimée de {node["name"]}.'
    else:
        rule['action'] = 'drop'
        answer = f'La règle {rule["name"]} de {node["name"]} est passée en blocage (deny).'
    return {'node': node['name'], 'category': 'Politique de pare-feu', 'answer': answer}


def _nat(spec, rng):
    firewalls = _nodes(spec, 'firewall', lambda n: (n.get('firewall') or {}).get('nat'))
    if not firewalls:
        return None
    node = rng.choice(firewalls)
    entry = rng.choice(node['firewall']['nat'])
    node['firewall']['nat'].remove(entry)
    what = 'la traduction d’adresse sortante (masquerade)' if entry['type'] != 'dnat' else 'la publication (VIP / DNAT)'
    return {'node': node['name'], 'category': 'NAT', 'answer': f'{node["name"]} a perdu {what} « {entry["name"]} ».'}


FAULTS = {'route-missing': _route_missing, 'route-hop': _route_hop, 'gateway-address': _gateway_address,
          'transit-address': _transit_address, 'host-gateway': _host_gateway, 'ospf-passive': _ospf_passive,
          'ospf-network': _ospf_network, 'ospf-off': _ospf_off, 'access-vlan': _access_vlan, 'trunk-vlan': _trunk_vlan,
          'subinterface': _subinterface, 'cables': _cables, 'firewall-rule': _firewall_rule, 'nat': _nat}


# ---- scenarios ----

def _probes(spec, plan):
    hosts = [n for n in spec['nodes'] if n['role'] == 'host']
    found = [(a['name'], b['interfaces']['eth0'].split('/')[0]) for a in hosts for b in hosts if a is not b]
    found += [p for p in getattr(plan, 'extra_probes', []) if p not in found]
    rng = random.Random(plan.number)
    rng.shuffle(found)
    return found[:MAX_PROBES]


def _names(spec):
    return {ipaddress.IPv4Interface(a).ip: n['name'] for n in spec['nodes'] for a in n['interfaces'].values() if a}


def scenario(number, kernel='/assets/vmlinux', disk='/assets/guest.ext4'):
    """Scenario NUMBER (1..COUNT): {number, title, family, needs, spec, original, probes, expected, fault, ticket}."""
    if type(number) is not int or not 1 <= number <= COUNT:
        raise ValueError(f'Scénario 1 à {COUNT}.')
    for attempt in range(40):
        rng = random.Random(number * 1009 + attempt)
        family = FAMILIES[(number + attempt) % len(FAMILIES)]
        plan = _Plan(rng, kernel, disk, number)
        detail, needs = BUILDERS[family](plan)
        title = plan.spec('')
        title.pop('title')
        try:
            working = validate(copy.deepcopy(title))
        except ValueError:
            continue
        probes = _probes(working, plan)
        expected = [ok for ok, _ in Model(working).ping_all(probes)]
        if not any(expected):
            continue
        kinds = sorted(FAULTS)
        rng.shuffle(kinds)
        for kind in kinds:
            broken = copy.deepcopy(working)
            fault = FAULTS[kind](broken, rng)
            if fault is None:
                continue
            try:
                broken = validate(broken)
            except ValueError:
                continue
            outcome = Model(broken).ping_all(probes)
            changed = [i for i, (ok, _) in enumerate(outcome) if ok != expected[i]]
            if not changed:
                continue
            names = _names(working)
            source, destination = probes[changed[0]]
            target = names.get(ipaddress.IPv4Address(destination), destination)
            ticket = (f'« {source} ne joint plus {target}. »' if expected[changed[0]] else
                      f'« {source} joint {target}, ce qui ne devrait pas être possible. »')
            return {'number': number, 'id': f'scenario-{number:04d}', 'family': family, 'title': FAMILY_TITLES[family],
                    'detail': detail, 'needs': needs, 'spec': broken, 'original': working, 'probes': probes,
                    'expected': expected, 'fault': dict(fault, kind=kind), 'ticket': ticket}
    raise ValueError(f'Scénario {number} : aucune panne observable n’a pu être générée.')


def mission_for(number):
    """The scenario's probes as a mission for the privileged 'mission' request (real pings from the guests)."""
    item = scenario(number)
    names = _names(item['original'])
    checks = [{'kind': 'reach', 'source': s, 'destination': d, 'expect': e,
               'text': f'{s} {"joint" if e else "ne joint pas"} {names.get(ipaddress.IPv4Address(d), d)} ({d})'}
              for (s, d), e in zip(item['probes'], item['expected'])]
    return {'id': item['id'], 'lab': item['id'], 'checks': checks}


def grade(spec, item, real=None):
    """The network behaves as designed (model of the draft), then each probe on the running lab."""
    try:
        outcome = Model(validate(copy.deepcopy(spec))).ping_all(item['probes'])
        wrong = [i for i, (ok, _) in enumerate(outcome) if ok != item['expected'][i]]
        ok, detail = not wrong, ('le réseau se comporte comme prévu' if not wrong
                                 else f'{len(wrong)} test(s) sur {len(outcome)} encore en écart')
    except ValueError as error:
        ok, detail = False, 'projet invalide : ' + str(error)
    results = [{'text': 'La panne est réparée (comportement du réseau)', 'kind': 'configuration',
                'status': 'ok' if ok else 'fail', 'detail': detail}]
    for index, check in enumerate(mission_for(item['number'])['checks']):
        if real and index in real:
            passed, shown = real[index]
            results.append({'text': check['text'], 'kind': 'réel', 'status': 'ok' if passed else 'fail', 'detail': shown})
        else:
            results.append({'text': check['text'], 'kind': 'réel', 'status': 'pending',
                            'detail': 'lab à démarrer puis « Tester sur le lab »'})
    passed = sum(r['status'] == 'ok' for r in results)
    return {'mission': item['id'], 'results': results, 'passed': passed, 'total': len(results), 'solved': passed == len(results)}


def help_step(spec, item, step):
    """Help number STEP (1..HELP_STEPS), each one a little more precise; the first ones read the current draft."""
    names = _names(item['original'])
    if step == 1:
        try:
            outcome = Model(validate(copy.deepcopy(spec))).ping_all(item['probes'])
        except ValueError as error:
            return 'Le projet est invalide : ' + str(error)
        wrong = [f'{s} → {names.get(ipaddress.IPv4Address(d), d)} ({"devrait répondre" if e else "ne devrait pas répondre"})'
                 for (s, d), e, (ok, _) in zip(item['probes'], item['expected'], outcome) if ok != e]
        return 'Tests en écart : ' + ('; '.join(wrong) if wrong else 'aucun, le réseau semble réparé.')
    if step == 2:
        try:
            outcome = Model(validate(copy.deepcopy(spec))).ping_all(item['probes'])
        except ValueError as error:
            return 'Le projet est invalide : ' + str(error)
        for (source, destination), expected, (ok, why) in zip(item['probes'], item['expected'], outcome):
            if ok != expected:
                return f'Ping de {source} vers {names.get(ipaddress.IPv4Address(destination), destination)} : {why}'
        return 'Aucun test en écart.'
    if step == 3:
        return 'L’équipement en cause : ' + item['fault']['node'] + '.'
    if step == 4:
        return 'Nature de la panne : ' + item['fault']['category'] + '.'
    return 'Solution : ' + item['fault']['answer']
