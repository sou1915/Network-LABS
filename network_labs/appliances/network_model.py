"""What a micro-VM lab should do, computed from its draft: the expected outcome of a ping, and where it stops.

The model follows the same rules the guests run. Ethernet segments come from cables, switch access and trunk
ports (802.1Q tags, native VLANs, plain bridges that pass tags through) and router subinterfaces. IP
forwarding uses connected networks, host gateways, static routes and OSPF (adjacencies on shared segments
between active interfaces, shortest paths by cost). Firewalls apply their policy to new connections:
destination NAT, the first matching rule, then the default, with replies allowed back and masquerade on
the way out. It does not model timing, MTU, ARP caches or IPv6.

It is used to keep only generated faults that really break something, to grade a repair by behaviour (any
correct fix passes), and to tell a student, step by step, where a packet stops.
"""
import heapq
import ipaddress

MAX_HOPS = 32


# ---- Ethernet segments ----

class _Union:
    def __init__(self):
        self.parent = {}

    def find(self, key):
        self.parent.setdefault(key, key)
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def join(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def _frames(node, port):
    """{tag or None: segment key} a port exchanges on its cable."""
    if node['role'] == 'switch':
        from .guest_startup import vlan_plan
        if vlan_plan(node) is None:
            # A plain bridge (only VLAN 1, no filtering): untagged frames and tagged ones pass unchanged.
            return {None: ('switch', node['name'], None), **{tag: ('switch', node['name'], tag) for tag in range(1, 4095)}}
        switchport = (node.get('switchports') or {}).get(port, {'mode': 'access', 'vlan': 1})
        if switchport['mode'] == 'access':
            return {None: ('switch', node['name'], switchport['vlan'])}
        allowed = node.get('vlans', []) if switchport['allowed'] == 'all' else switchport['allowed']
        frames = {tag: ('switch', node['name'], tag) for tag in allowed if tag != switchport['native_vlan']}
        frames[None] = ('switch', node['name'], switchport['native_vlan'])
        return frames
    frames = {None: ('port', node['name'], port)}
    for name, sub in (node.get('subinterfaces') or {}).items():
        if sub['parent'] == port and sub.get('vlan'):
            frames[sub['vlan']] = ('port', node['name'], name)
    return frames


def segments(spec):
    """{(node, interface): segment id} for every L3 interface (ports and subinterfaces)."""
    nodes = {n['name']: n for n in spec['nodes']}
    union = _Union()
    for a, b in spec['links']:
        if a[1] in (nodes[a[0]].get('shutdown') or []) or b[1] in (nodes[b[0]].get('shutdown') or []):
            continue  # a shut port carries nothing
        left, right = _frames(nodes[a[0]], a[1]), _frames(nodes[b[0]], b[1])
        if len(left) > 4094 and len(right) > 4094:
            union.join(left[None], right[None])  # two plain bridges: one segment for everything
            for tag in range(1, 4095):
                union.join(left[tag], right[tag])
            continue
        for tag in set(left) & set(right):
            union.join(left[tag], right[tag])
    found = {}
    for node in spec['nodes']:
        if node['role'] == 'switch':
            from .guest_startup import vlan_plan
            from .svi import management
            svi = management(node)  # a switch's management SVI sits on its VLAN's segment
            if svi:
                found[(node['name'], svi['name'])] = union.find(('switch', node['name'], None if vlan_plan(node) is None else svi['vlan']))
            continue
        for name in [*node['interfaces'], *(node.get('subinterfaces') or {})]:
            found[(node['name'], name)] = union.find(('port', node['name'], name))
    return found


# ---- addresses and routes ----

def addresses(node):
    """{interface: IPv4Interface} the node holds on its working interfaces (a shut port has no connected network)."""
    if node.get('role') == 'switch':
        from .svi import management
        svi = management(node)  # a switch holds only its management SVI's address
        return {svi['name']: ipaddress.IPv4Interface(svi['address'])} if svi else {}
    down = set(node.get('shutdown') or [])
    found = {port: ipaddress.IPv4Interface(a) for port, a in node['interfaces'].items() if a and port not in down}
    found.update({name: ipaddress.IPv4Interface(sub['address']) for name, sub in (node.get('subinterfaces') or {}).items()
                  if sub.get('address') and sub['parent'] not in down})
    for port, extra in ({'eth0': (node.get('guest_network') or {}).get('addresses', [])}
                        | (node.get('guest_network') or {}).get('port_addresses', {})).items():
        if port in down:
            continue
        for address in extra:
            found.setdefault(port + '#' + address, ipaddress.IPv4Interface(address))
    return found


def _port_of(name):
    return name.split('#')[0]


def static_routes(node):
    """[(network, gateway)] including the default route."""
    if node.get('role') == 'switch':  # « ip default-gateway », when it lies in the management SVI's subnet
        from .svi import management
        svi = management(node)
        return [(ipaddress.IPv4Network('0.0.0.0/0'), ipaddress.IPv4Address(svi['gateway']))] if svi and svi['gateway'] else []
    from .vendor_config import routes
    return [(ipaddress.IPv4Network(network), ipaddress.IPv4Address(gateway)) for network, gateway in routes(node)]


def ospf_routes(spec, seg):
    """{router: [(network, gateway, cost)]} computed as OSPF would converge in area 0."""
    from .ospf import enabled_interfaces
    routers = {n['name']: n for n in spec['nodes'] if n.get('ospf')}
    links = {}  # router -> [(neighbour, cost, neighbour's address on the shared segment)]
    stubs = {}  # router -> [(network, cost)]
    for name, node in routers.items():
        held = addresses(node)
        stubs[name] = []
        for port, value in enabled_interfaces(node).items():
            if port not in held:
                continue
            stubs[name].append((held[port].network, value['cost']))
            if value['passive']:
                continue
            for other, peer in routers.items():
                if other == name:
                    continue
                for peer_port, peer_value in enabled_interfaces(peer).items():
                    peer_address = addresses(peer).get(peer_port)
                    if (peer_address is None or peer_value['passive'] or seg.get((other, peer_port)) != seg.get((name, port))
                            or peer_address.network != held[port].network or peer_value['network_type'] != value['network_type']
                            or (peer['ospf']['hello'], peer['ospf']['dead']) != (node['ospf']['hello'], node['ospf']['dead'])):
                        continue
                    links.setdefault(name, []).append((other, value['cost'], peer_address.ip))
    found = {}
    for source in routers:
        best, queue = {source: (0, None)}, [(0, source, None)]
        while queue:
            cost, here, first_hop = heapq.heappop(queue)
            if cost > best.get(here, (float('inf'),))[0]:
                continue
            for other, step, address in links.get(here, []):
                hop = first_hop if here != source else address
                if cost + step < best.get(other, (float('inf'),))[0]:
                    best[other] = (cost + step, hop)
                    heapq.heappush(queue, (cost + step, other, hop))
        table = {}
        for router, (cost, hop) in best.items():
            if router == source:
                continue
            for network, stub_cost in stubs[router]:
                total = cost + stub_cost
                if network not in table or total < table[network][1]:
                    table[network] = (hop, total)
        own = {a.network for a in addresses(routers[source]).values()}
        found[source] = [(network, hop, cost) for network, (hop, cost) in table.items() if network not in own]
    return found


def rip_routes(spec, seg):
    """{router: [(network, gateway, hops)]} as RIP converges: updates sent by active RIP ports, heard by RIP ports on the
    same segment; each router announces its RIP ports' networks; fewest hops wins, 15 at most."""
    from .rip import process
    running = {n['name']: (n, process(n)) for n in spec['nodes'] if process(n)}
    if not running:
        return {}
    down = {name: set(node.get('shutdown') or []) for name, (node, _) in running.items()}
    ports = {name: {p['port']: p['passive'] for p in rip['interfaces'] if p['port'] not in down[name]}
             for name, (_, rip) in running.items()}
    tables = {name: {ipaddress.IPv4Interface(node['interfaces'][port]).network: (0, None) for port in ports[name]}
              for name, (node, _) in running.items()}
    for _ in range(16):
        changed = False
        for name, (node, _) in running.items():
            for other, (peer, _) in running.items():
                if other == name:
                    continue
                for port in ports[name]:
                    for peer_port, passive in ports[other].items():
                        if passive or seg.get((name, port)) is None or seg.get((name, port)) != seg.get((other, peer_port)):
                            continue
                        hop = ipaddress.IPv4Interface(peer['interfaces'][peer_port]).ip
                        for network, (hops, _) in list(tables[other].items()):
                            candidate = hops + 1
                            current = tables[name].get(network)
                            if candidate <= 15 and (current is None or candidate < current[0]):
                                tables[name][network] = (candidate, hop)
                                changed = True
        if not changed:
            break
    return {name: [(network, hop, hops) for network, (hops, hop) in table.items() if hop is not None]
            for name, table in tables.items()}


def bgp_routes(spec, seg):
    """{router: [(network, next hop)]} as eBGP converges: sessions only where both sides name each other with the
    right AS on a shared segment, networks announced only when held exactly, shortest AS path, no AS loops."""
    from .bgp import announced
    routers = {n['name']: n for n in spec['nodes'] if n.get('bgp')}
    sessions = {name: [] for name in routers}
    for name, node in routers.items():
        mine = addresses(node)
        for neighbor in node['bgp']['neighbors']:
            target = ipaddress.IPv4Address(neighbor['address'])
            port = next((p for p, a in mine.items() if target in a.network), None)
            for other, peer in routers.items():
                theirs = {p: a for p, a in addresses(peer).items() if a.ip == target}
                if other == name or not theirs or peer['bgp']['asn'] != neighbor['remote_as']:
                    continue
                peer_port, peer_address = next(iter(theirs.items()))
                back = any(n['address'] == str(mine[port].ip) and n['remote_as'] == node['bgp']['asn'] for n in peer['bgp']['neighbors'])
                if back and seg.get((name, _port_of(port))) == seg.get((other, _port_of(peer_port))):
                    sessions[name].append((other, target))
    rib = {}
    for name, node in routers.items():
        static = [r['network'] for r in (node.get('guest_network') or {}).get('routes', [])]
        rib[name] = {ipaddress.IPv4Network(n): ((), None) for n in announced(node, static)}
    for _ in range(len(routers) + 2):
        changed = False
        for name, node in routers.items():
            for other, hop in sessions[name]:
                for prefix, (path, _) in list(rib[other].items()):
                    candidate = (routers[other]['bgp']['asn'],) + path
                    if node['bgp']['asn'] in candidate:
                        continue
                    current = rib[name].get(prefix)
                    if current is None or (current[1] is not None and len(candidate) < len(current[0])):
                        rib[name][prefix] = (candidate, hop)
                        changed = True
        if not changed:
            break
    return {name: [(prefix, hop) for prefix, (_, hop) in table.items() if hop is not None] for name, table in rib.items()}


# ---- forwarding ----

class Model:
    def __init__(self, spec):
        self.spec = spec
        self.nodes = {n['name']: n for n in spec['nodes']}
        self.seg = segments(spec)
        self.ospf = ospf_routes(spec, self.seg)
        self.bgp = bgp_routes(spec, self.seg)
        self.rip = rip_routes(spec, self.seg)
        self.leases = {}  # (node, port) -> (address, gateway): DHCP clients take the first free pool address
        servers = [(n, n['dhcp_server']) for n in spec['nodes'] if n.get('dhcp_server')]
        for node in spec['nodes']:
            for port in node.get('dhcp_clients') or []:
                for server_node, server in servers:
                    if 'network' in server:
                        continue  # a relayed pool serves the remote LAN only, through its relay (below)
                    if self.seg.get((server_node['name'], server['interface'])) == self.seg.get((node['name'], port)):
                        prefix = ipaddress.IPv4Interface(server_node['interfaces'][server['interface']]).network.prefixlen
                        offered = ipaddress.IPv4Address(server['start']) + sum(1 for _ in self.leases)
                        router = ipaddress.IPv4Address(server['router']) if server.get('router') else None
                        self.leases[(node['name'], port)] = (ipaddress.IPv4Interface(f'{offered}/{prefix}'), router)
                        break
        self._relayed_leases(servers)
        self.owners = {}  # (segment, address) -> (node, interface)
        for node in spec['nodes']:  # a switch holds only its management SVI (addresses())
            for name, address in self.held(node['name']).items():
                key = (self.seg.get((node['name'], _port_of(name))), address.ip)
                self.owners.setdefault(key, (node['name'], _port_of(name)))
            from .ios_nat import public_addresses
            for port, values in public_addresses(node).items():  # a router answers for its static NAT and pool addresses
                for value in values:
                    self.owners.setdefault((self.seg.get((node['name'], port)), ipaddress.IPv4Interface(value).ip), (node['name'], port))

    def _relayed_leases(self, servers):
        """Leases through an « ip helper-address » relay: a router on the client's segment relays to a server whose
        relayed pool holds the relay port's address (giaddr), with a route each way and the pool served on the port the
        relayed requests reach the server by."""
        from .ios_relay import process
        relays = [(n, process(n)) for n in self.spec['nodes'] if process(n)]
        for node in self.spec['nodes']:
            for port in node.get('dhcp_clients') or []:
                if (node['name'], port) in self.leases:
                    continue
                for relay_node, relay in relays:
                    for client_port in relay['clients']:
                        held = addresses(relay_node).get(client_port)
                        if held is None or self.seg.get((relay_node['name'], client_port)) != self.seg.get((node['name'], port)):
                            continue
                        lease = self._relayed_lease(servers, relay_node['name'], relay['server'], held.ip)
                        if lease is not None:
                            self.leases[(node['name'], port)] = lease
                            break
                    if (node['name'], port) in self.leases:
                        break

    def _relayed_lease(self, servers, relay, server_address, giaddr):
        server_address = ipaddress.IPv4Address(server_address)
        for server_node, server in servers:
            if 'network' not in server or giaddr not in ipaddress.IPv4Network(server['network']):
                continue
            if not any(a.ip == server_address for a in addresses(server_node).values()):
                continue
            there, back = self.route(relay, server_address)[0], self.route(server_node['name'], giaddr)[0]
            if there is None or back is None or _port_of(back) != server['interface']:
                return None
            offered = ipaddress.IPv4Address(server['start']) + sum(1 for _ in self.leases)
            router = ipaddress.IPv4Address(server['router']) if server.get('router') else None
            return ipaddress.IPv4Interface(f'{offered}/{ipaddress.IPv4Network(server["network"]).prefixlen}'), router
        return None

    def held(self, name):
        found = addresses(self.nodes[name])
        found.update({port: lease for (node, port), (lease, _) in self.leases.items() if node == name})
        return found

    def local(self, name, destination):
        return any(a.ip == destination for a in self.held(name).values())

    def route(self, name, destination):
        """(interface, next hop address, reason) or (None, None, reason) for a packet leaving NAME."""
        node = self.nodes[name]
        held = self.held(name)
        best = None
        for interface, address in held.items():
            if destination in address.network and (best is None or address.network.prefixlen > best[0]):
                best = (address.network.prefixlen, _port_of(interface), destination, 'réseau connecté')
        candidates = [(network, gateway, 'passerelle par défaut' if network.prefixlen == 0 and node['role'] == 'host'
                       else 'route statique') for network, gateway in static_routes(node)]
        candidates += [(ipaddress.IPv4Network('0.0.0.0/0'), router, 'passerelle DHCP') for (n, _), (_, router) in self.leases.items()
                       if n == name and router]
        candidates += [(network, gateway, 'route OSPF') for network, gateway, _ in self.ospf.get(name, [])]
        candidates += [(network, gateway, 'route BGP') for network, gateway in self.bgp.get(name, [])]
        candidates += [(network, gateway, 'route RIP') for network, gateway, _ in self.rip.get(name, [])]
        for network, gateway, kind in candidates:
            if destination in network and (best is None or network.prefixlen > best[0]):
                port = next((_port_of(i) for i, a in held.items() if gateway in a.network), None)
                if port is not None:
                    best = (network.prefixlen, port, gateway, kind)
        if best is None:
            return None, None, f'{name} n’a aucune route vers {destination}'
        return best[1], best[2], best[3]

    def step(self, name, destination):
        """Where a packet for DESTINATION goes from NAME: (node, its ingress port, egress port) or (None, why, None)."""
        interface, hop, kind = self.route(name, destination)
        if interface is None:
            return None, kind, None
        owner = self.owners.get((self.seg.get((name, interface)), hop))
        if owner is None:
            what = 'la passerelle' if hop != destination else 'la destination'
            return None, f'{name} : {what} {hop} ne répond pas sur ce segment ({kind})', None
        return owner[0], owner[1], interface

    def nat(self, name):
        """The NAT entries a node runs: a firewall's policy, or a router's IOS NAT (PAT, static, pools)."""
        node = self.nodes[name]
        if node['role'] == 'firewall':
            return (node.get('firewall') or {}).get('nat', [])
        if node['role'] == 'router' and node.get('cli_config'):
            from .ios_nat import entries
            return entries(node)
        return []

    def _nat_out(self, name, port, source):
        """Source NAT on leaving NAME by PORT: the translated source address, or SOURCE."""
        for entry in self.nat(name):
            if entry['type'] in ('masquerade', 'snat') and entry.get('out') == port and (
                    not entry.get('source') or source in ipaddress.IPv4Network(entry['source'])):
                if entry['type'] == 'snat':  # a pool range A-B: its first address (one inside host in a lab)
                    return ipaddress.IPv4Address(entry['to'].split('-')[0])
                held = self.held(name).get(port)
                return held.ip if held else source
        return source

    def _nat_in(self, name, port, destination):
        for entry in self.nat(name):
            if (entry['type'] == 'dnat' and entry.get('in') == port and entry.get('protocol', 'any') in ('any', 'icmp')
                    and destination in ipaddress.IPv4Network(entry['destination'])):
                return ipaddress.IPv4Address(entry['to'])
        return destination

    def deliver(self, source, packet, tracked=None, hops=None):
        """Walk PACKET {source, destination} from node SOURCE. A request records its translations in a new
        'tracked' list; a reply passes TRACKED to be translated back. Returns (ok, path, why, tracked, node).
        HOPS, when given, receives each (node, port it arrives by) on the way."""
        from .missions import evaluate_policy
        path, here, ingress = [source], source, None
        reply = tracked is not None
        tracked = tracked if reply else []
        for _ in range(MAX_HOPS):
            node = self.nodes[here]
            if node.get('acl_ports') and ingress is not None:
                from .acl import evaluate
                wanted = {'source': str(packet['source']), 'destination': str(packet['destination']),
                          'protocol': packet.get('protocol', 'icmp'), **({'dport': packet['dport']} if packet.get('dport') else {})}
                if evaluate(node, ingress, wanted) != 'permit':
                    from .native_models import port_names
                    shown = port_names(node).get(ingress, ingress)
                    return False, path, f'{here} : l’ACL {node["acl_ports"][ingress]} de {shown} refuse le paquet', tracked, here
            translating = node['role'] == 'firewall' or bool(self.nat(here))
            if translating and ingress is not None:
                if reply:
                    for firewall, before, after in tracked:
                        if firewall == here and packet['destination'] == after[0]:
                            packet = {'source': before[1], 'destination': before[0],  # the reply, translated back
                                      'protocol': packet.get('protocol', 'icmp')}
                else:
                    wanted = {'in': ingress, 'source': str(packet['source']), 'destination': str(packet['destination']),
                              'protocol': packet.get('protocol', 'icmp'), **({'dport': packet['dport']} if packet.get('dport') else {})}
                    if node['role'] == 'firewall' and evaluate_policy(node, wanted) != 'accept':
                        return False, path, f'{here} bloque le flux (politique de pare-feu)', tracked, here
                    translated = self._nat_in(here, ingress, packet['destination'])
                    if translated != packet['destination']:
                        tracked.append((here, (packet['source'], packet['destination']), (packet['source'], translated)))
                        packet = dict(packet, destination=translated)
            if self.local(here, packet['destination']):
                return True, path, None, tracked, here
            if here != source and node['role'] not in ('router', 'firewall'):
                return False, path, f'{here} reçoit le paquet mais ne route pas', tracked, here
            following, port, egress = self.step(here, packet['destination'])
            if following is None:
                return False, path, port, tracked, here
            if translating and not reply:
                translated = self._nat_out(here, egress, packet['source'])
                if translated != packet['source']:
                    original = next((b for f, b, _ in tracked if f == here), (packet['source'], packet['destination']))
                    tracked = [t for t in tracked if t[0] != here]
                    tracked.append((here, original, (translated, packet['destination'])))
                    packet = dict(packet, source=translated)
            if path.count(following) >= 2:
                loop = path[path.index(following):]
                return False, path[:path.index(following) + 2], f'boucle de routage entre {" et ".join(dict.fromkeys(loop))}', tracked, here
            path.append(following)
            if hops is not None:
                hops.append((following, port))
            here, ingress = following, port
        return False, path, 'boucle de routage', tracked, here

    def source_address(self, name, destination):
        interface, _, _ = self.route(name, destination)
        held = self.held(name)
        return next((a.ip for i, a in held.items() if _port_of(i) == interface), None)

    def ping(self, source, destination, protocol='icmp', dport=None):
        """(ok, explanation): the request reaches DESTINATION and its reply comes back to SOURCE. PROTOCOL and DPORT
        make it a TCP or UDP connection's first packet (« telnet » is tcp 23), for the access lists on the way."""
        destination = ipaddress.IPv4Address(destination)
        address = self.source_address(source, destination)
        if address is None:
            return False, self.route(source, destination)[2]
        ok, path, why, tracked, target = self.deliver(source, {'source': address, 'destination': destination, 'protocol': protocol,
                                                                **({'dport': dport} if dport else {})})
        if not ok:
            return False, 'aller : ' + ' → '.join(path) + ' · ' + why
        # The reply leaves the target towards the address it saw (after translations on the way).
        seen = next((after[0] for _, _, after in reversed(tracked) if after[0] != address), address)
        reply_to = seen
        back, back_path, why, _, _ = self.deliver(target, {'source': destination, 'destination': reply_to, 'protocol': protocol}, tracked)
        if not back:
            return False, 'retour : ' + ' → '.join(back_path) + ' · ' + why
        return True, ' → '.join(path) + ' (retour ' + ' → '.join(back_path) + ')'


    def trace(self, source, destination):
        """{'hops': [address or None], 'reached', 'why'}: each router on the way answers from the port the probe
        arrives by, if it has a way back to SOURCE; the destination last. A router whose ACL or policy drops the
        probe stays silent."""
        destination = ipaddress.IPv4Address(destination)
        if self.local(source, destination):
            return {'hops': [str(destination)], 'reached': True, 'why': None}
        address = self.source_address(source, destination)
        if address is None:
            return {'hops': [], 'reached': False, 'why': self.route(source, destination)[2]}
        walked = []
        ok, _, why, _, _ = self.deliver(source, {'source': address, 'destination': destination}, hops=walked)
        found = []
        for index, (node, port) in enumerate(walked):
            if self.local(node, destination):
                reached = self.ping(source, str(destination))[0]
                found.append(str(destination) if reached else None)
                return {'hops': found, 'reached': reached, 'why': None if reached else 'la réponse ne revient pas'}
            dropped = not ok and index == len(walked) - 1 and why and ('ACL' in why or 'bloque' in why)
            here = next((a.ip for i, a in self.held(node).items() if _port_of(i) == port), None)
            back = here is not None and not dropped and self.deliver(node, {'source': here, 'destination': address})[0]
            found.append(str(here) if back else None)
        return {'hops': found, 'reached': False, 'why': why}

    def ping_all(self, probes):
        return [self.ping(source, destination) for source, destination in probes]


def reachability(spec, probes):
    """[(ok, explanation)] for PROBES [(source, destination address)]."""
    model = Model(spec)
    return [model.ping(source, destination) for source, destination in probes]
