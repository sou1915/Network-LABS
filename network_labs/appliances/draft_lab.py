"""The project itself as the lab a device's CLI talks to, while the lab is stopped: type at once, as in Packet Tracer.

The node terminal (guest_console.Console) needs a lab: read its spec, observe a node, ping, change a node. A running
lab answers from the micro-VMs. Before ▶ Démarrer, DraftLab answers from the project: configuration lines change the
device in the project (what Démarrer then starts), « show » is computed from the configuration and the network model
(addresses, routes, OSPF and BGP as they would converge, VLANs), and « ping » is the network model's verdict. Nothing
here touches a micro-VM; the CLI window says so.
"""
import contextlib
import copy
import ipaddress

from . import network_model


class DraftLab:
    def __init__(self, get_spec, commit):
        self.get_spec, self.commit = get_spec, commit
        self.state = None

    # ---- what guest_console.Console uses ----

    @contextlib.contextmanager
    def locked(self):
        yield self

    def read(self):
        return {'spec': self.get_spec(), 'phase': 'draft'}

    def configure_routing(self, name, node):
        spec = copy.deepcopy(self.get_spec())
        spec['nodes'] = [copy.deepcopy(node) if n['name'] == name else n for n in spec['nodes']]
        self.commit(spec)
        return {'configured': name}

    def configure_firewall(self, name, policy):
        spec = copy.deepcopy(self.get_spec())
        for node in spec['nodes']:
            if node['name'] == name:
                node['firewall'] = copy.deepcopy(policy)
        self.commit(spec)
        return {'configured': name}

    def observe_node(self, name):
        spec = self.get_spec()
        model = network_model.Model(spec)
        node = model.nodes[name]
        down = set(node.get('shutdown') or [])
        held = model.held(name)
        interfaces = []
        for port in [*node['interfaces'], *(node.get('subinterfaces') or {})]:
            parent = port.split('.')[0]
            addresses = [str(a) for i, a in held.items() if network_model._port_of(i) == port]
            interfaces.append({'port': port, 'up': parent not in down, 'addresses': addresses})
        from .svi import management
        svi = management(node)
        for name, policy in (node.get('svis') or {}).items():  # a switch's management SVI: up once it runs
            interfaces.append({'port': name, 'up': bool(svi), 'addresses': [policy['address']] if policy.get('address') else []})
        routes = []
        if node['role'] != 'switch':
            for network, gateway in network_model.static_routes(node):
                port = next((network_model._port_of(i) for i, a in held.items() if gateway in a.network), None)
                if port is not None:
                    routes.append({'network': str(network), 'gateway': str(gateway), 'port': port})
            for network, gateway, cost in model.ospf.get(name, []):
                port = next((network_model._port_of(i) for i, a in held.items() if gateway in a.network), None)
                routes.append({'network': str(network), 'gateway': str(gateway), 'port': port, 'protocol': 'ospf', 'metric': cost})
            for network, gateway, hops in model.rip.get(name, []):
                port = next((network_model._port_of(i) for i, a in held.items() if gateway in a.network), None)
                routes.append({'network': str(network), 'gateway': str(gateway), 'port': port, 'protocol': 'rip', 'metric': hops})
            for network, gateway in model.bgp.get(name, []):
                port = next((network_model._port_of(i) for i, a in held.items() if gateway in a.network), None)
                routes.append({'network': str(network), 'gateway': str(gateway), 'port': port, 'protocol': 'bgp', 'metric': 0,
                               'path': ''})
        return {'node': name, 'interfaces': interfaces, 'routes': routes, 'vlans': _vlans(node),
                'ospf': _ospf(spec, model, node), 'bgp': _bgp(spec, model, node), 'sessions': None}

    def ping_node(self, name, destination, count=5):
        ok, why = network_model.Model(self.get_spec()).ping(name, str(ipaddress.IPv4Address(destination)))
        replies = [{'ok': ok, 'ttl': 64 if ok else None, 'time_ms': 1.0 if ok else None, 'sequence': i} for i in range(count)]
        return {'node': name, 'destination': destination, 'replies': replies, 'why': why}

    def trace_node(self, name, destination):
        from . import trace
        result = trace.from_model(network_model.Model(self.get_spec()), name, str(ipaddress.IPv4Address(destination)))
        return dict(result, node=name)

    def query_node(self, name, operation):
        """The host shell's « ip addr » and « ip route », written as BusyBox prints them, from the project."""
        observation = self.observe_node(name)
        if operation == 'addresses':
            lines = ['1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536', '    inet 127.0.0.1/8 scope host lo']
            for index, interface in enumerate(observation['interfaces'], 2):
                flags = 'BROADCAST,MULTICAST,UP,LOWER_UP' if interface['up'] else 'BROADCAST,MULTICAST'
                lines.append(f'{index}: {interface["port"]}: <{flags}> mtu 1500')
                lines += [f'    inet {address} scope global {interface["port"]}' for address in interface['addresses']]
            return '\n'.join(lines) + '\n'
        lines = []
        for route in observation['routes']:
            network = 'default' if route['network'] == '0.0.0.0/0' else route['network']
            lines.append(f'{network} via {route["gateway"]} dev {route["port"]}')
        for interface in observation['interfaces']:
            for address in interface['addresses'] if interface['up'] else []:
                value = ipaddress.IPv4Interface(address)
                lines.append(f'{value.network} dev {interface["port"]} scope link  src {value.ip}')
        return '\n'.join(lines) + ('\n' if lines else '')


def _vlans(node):
    if node['role'] != 'switch':
        return None
    from .guest_startup import vlan_plan
    plan = vlan_plan(node)
    if plan is None:
        return [{'port': port, 'vlan': 1, 'untagged': True} for port in node['interfaces']]
    return [{'port': port, 'vlan': vid, 'untagged': mode == 'pvid'} for port, vid, mode in sorted(plan)]


def _ospf(spec, model, node):
    """OSPF neighbours as they would form: another OSPF router on the same segment, on an enabled interface."""
    if not node.get('ospf'):
        return None
    from .ospf import enabled_interfaces
    mine = enabled_interfaces(node)
    neighbors = []
    for other in spec['nodes']:
        if other['name'] == node['name'] or not other.get('ospf'):
            continue
        theirs = enabled_interfaces(other)
        for port in mine:
            for peer_port in theirs:
                if model.seg.get((node['name'], port)) == model.seg.get((other['name'], peer_port)) and \
                        not mine[port].get('passive') and not theirs[peer_port].get('passive'):
                    address = other['interfaces'].get(peer_port, '').split('/')[0]
                    neighbors.append({'router_id': other['ospf']['router_id'], 'priority': theirs[peer_port].get('priority', 1),
                                      'state': 'Full', 'role': '', 'dead': 9.0, 'port': port, 'address': address})
    return {'router_id': node['ospf']['router_id'], 'neighbors': neighbors, 'metrics': {}}


def _bgp(spec, model, node):
    """BGP peers as they would come up: the neighbour's address is on a shared segment and it names this router back."""
    if not node.get('bgp'):
        return None
    mine = network_model.addresses(node)
    peers = []
    for neighbor in node['bgp']['neighbors']:
        state = 'Active'
        for other in spec['nodes']:
            if other['name'] == node['name'] or not other.get('bgp') or other['bgp']['asn'] != neighbor['remote_as']:
                continue
            theirs = {p: a for p, a in network_model.addresses(other).items() if str(a.ip) == neighbor['address']}
            back = [n for n in other['bgp']['neighbors'] if n['remote_as'] == node['bgp']['asn']
                    and any(str(a.ip) == n['address'] for a in mine.values())]
            if theirs and back:
                state = 'Established'
        received = sum(1 for _ in model.bgp.get(node['name'], [])) if state == 'Established' else 0
        peers.append({'address': neighbor['address'], 'remote_as': neighbor['remote_as'], 'state': state, 'uptime': '00:00:01',
                      'received': received, 'sent': 0, 'msg_in': 0, 'msg_out': 0})
    paths = {str(network): {'path': '', 'nexthop': str(gateway), 'local': False, 'origin': 'IGP'}
             for network, gateway in model.bgp.get(node['name'], [])}
    for network in node['bgp']['networks']:
        paths.setdefault(network, {'path': '', 'nexthop': '0.0.0.0', 'local': True, 'origin': 'IGP'})
    return {'asn': node['bgp']['asn'], 'router_id': node['bgp']['router_id'], 'peers': peers, 'paths': paths}
