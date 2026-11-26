"""What the web management pages show about one device: identity, front-panel ports, neighbours and routes.

Everything comes from the validated lab draft (and the vendor model catalogue); nothing is observed here.
"""
import ipaddress

from .native_models import MODELS, label, port_names
from .vendor_config import TITLES, dialect, routes

ROLE_NAMES = {'firewall': 'Pare-feu', 'router': 'Routeur', 'switch': 'Switch', 'host': 'Poste'}


def art(node, spec):
    """The device drawing the canvas uses for this node (served as /devices/<art>@<size>.png)."""
    model = MODELS.get(node.get('model'))
    if node['role'] == 'host':
        if model and model['presentation'] == 'server':
            return 'server'
        hosts = [n['name'] for n in spec['nodes'] if n['role'] == 'host']
        return 'host-red' if hosts.index(node['name']) % 2 else 'host-blue'
    return node['role']


def neighbours(spec, name):
    """{port: 'PEER · peer-port'} for every cabled port of NAME, peer ports in their vendor names."""
    nodes = {n['name']: n for n in spec['nodes']}
    found = {}
    for a, b in spec['links']:
        for mine, other in ((a, b), (b, a)):
            if mine[0] == name:
                found[mine[1]] = f'{other[0]} · {port_names(nodes[other[0]]).get(other[1], other[1])}'
    return found


def features(node):
    """What the device runs beyond addresses and routes, as [{'name', 'detail'}] (routing protocols, HSRP, NAT, DHCP,
    spanning tree, EtherChannel, port security…), each from the project; one that cannot be read is left out."""
    shown = port_names(node)
    name = lambda port: shown.get(port.partition('.')[0], port.partition('.')[0]) + ('.' + port.partition('.')[2] if '.' in port else '')
    found = []

    def add(title, detail):
        found.append({'name': title, 'detail': detail})

    def attempt(work):
        try:
            work()
        except (ValueError, KeyError, TypeError, AttributeError, IndexError):
            pass

    def ospf():
        if node.get('ospf'):
            from .ospf import enabled_interfaces
            ports = enabled_interfaces(node)
            add('OSPF', f"router-id {node['ospf'].get('router_id', '—')} · zone 0 · {len(ports)} interface{'s' if len(ports) > 1 else ''}")

    def rip():
        from .rip import process
        found_rip = process(node)
        if found_rip:
            add('RIP', f"version {found_rip['version']} · " + ', '.join(name(i['port']) for i in found_rip['interfaces']))

    def eigrp():
        from .eigrp import process
        found_eigrp = process(node)
        if found_eigrp:
            add('EIGRP', f"AS {found_eigrp['asn']} · " + ', '.join(name(i['port']) for i in found_eigrp['interfaces']))

    def bgp():
        if node.get('bgp'):
            neighbours = node['bgp'].get('neighbors') or []
            add('BGP', f"AS {node['bgp'].get('asn', '—')} · {len(neighbours)} voisin{'s' if len(neighbours) > 1 else ''}")

    def hsrp():
        from .hsrp import groups
        for port, entry in sorted(groups(node).items()):
            for group, settings in sorted(entry['groups'].items()):
                add('HSRP', f"{name(port)} · groupe {group} · {settings['ip'] or 'sans adresse'} · priorité {settings['priority']}"
                            + (' · preempt' if settings['preempt'] else ''))

    def nat():
        from .ios_nat import entries
        rules = entries(node) if node.get('role') == 'router' and node.get('cli_config') else []
        if rules:
            add('NAT', f"{len(rules)} traduction{'s' if len(rules) > 1 else ''} (IOS)")

    def relay():
        from .ios_relay import process
        found_relay = process(node)
        if found_relay:
            add('Relais DHCP', f"vers {found_relay['server']} · " + ', '.join(name(p) for p in found_relay['clients']))

    def dhcp():
        from .dhcp import pools
        for server in pools(node):  # one row per pool (a router guest serves one per LAN or VLAN)
            add('Serveur DHCP', f"{server.get('start', '?')} – {server.get('end', '?')} · {name(server.get('interface', ''))}")

    def acl():
        if node.get('acl_ports'):
            add('ACL', ', '.join(f'{acl} sur {name(port)}' for port, acl in sorted(node['acl_ports'].items())))

    def stp():
        tree = node.get('spanning_tree') or {}
        if node.get('role') == 'switch' and tree.get('mode') == 'stp':
            add('Spanning tree', f"802.1D · priorité {tree.get('priority', 32768)}")

    def channels():
        from .etherchannel import bundles
        for bond, channel in sorted(bundles(node).items()):
            add('EtherChannel', f"Port-channel{bond[4:]} · LACP · " + ', '.join(name(m) for m in channel['members']))

    def security():
        from .port_guard import policy
        guarded = policy(node)
        secure = [name(p) for p, v in guarded.items() if v['secure']]
        guard = [name(p) for p, v in guarded.items() if v['bpduguard']]
        if secure:
            add('Sécurité des ports', ', '.join(secure))
        if guard:
            add('BPDU guard', ', '.join(guard))

    def layer3():
        from .svi import routing
        if node.get('role') == 'switch' and routing(node):
            add('Routage inter-VLAN', 'ip routing · ' + ', '.join(f'Vlan{s[4:]}' for s in sorted(node.get('svis') or {})))

    for work in (ospf, rip, eigrp, bgp, hsrp, nat, relay, dhcp, acl, stp, channels, security, layer3):
        attempt(work)
    return found


def summary(spec, node):
    model = MODELS.get(node.get('model'))
    shown = port_names(node)
    cabled = neighbours(spec, node['name'])
    switchports = node.get('switchports') or {}
    ports = []
    for port, address in node['interfaces'].items():
        policy = switchports.get(port)
        if node['role'] == 'switch':
            if policy and policy.get('mode') == 'trunk':
                allowed = policy['allowed']
                detail = 'Trunk ' + ('toutes' if allowed == 'all' else ','.join(map(str, allowed)))
                vlan = None
            else:
                vlan = policy['vlan'] if policy else 1
                detail = f'VLAN {vlan}'
        else:
            vlan = None
            subs = [s for s, v in (node.get('subinterfaces') or {}).items() if v.get('parent') == port]
            detail = ('DHCP' if port in node.get('dhcp_clients', []) else address
                      or (f'802.1Q ×{len(subs)}' if subs else 'Sans adresse'))
        ports.append({'port': port, 'name': shown[port], 'address': address, 'detail': detail, 'vlan': vlan,
                      'trunk': bool(policy and policy.get('mode') == 'trunk'), 'peer': cabled.get(port),
                      'down': port in node.get('shutdown', [])})
    connected = []
    for port, address in node['interfaces'].items():
        if address:
            connected.append({'network': str(ipaddress.IPv4Interface(address).network), 'gateway': None, 'port': shown[port]})
    for sub, value in (node.get('subinterfaces') or {}).items():
        if value.get('address'):
            parent, _, vid = sub.partition('.')
            connected.append({'network': str(ipaddress.IPv4Interface(value['address']).network), 'gateway': None,
                              'port': shown.get(parent, parent) + '.' + vid})
    static = []
    for network, gateway in routes(node):
        hop = ipaddress.IPv4Address(gateway)
        port = next((p for p, a in node['interfaces'].items() if a and hop in ipaddress.IPv4Interface(a).network), None)
        static.append({'network': network, 'gateway': gateway, 'port': shown.get(port, '—') if port else '—'})
    # The model's other front-panel ports, which this lab does not declare (shown dimmed).
    names = model['ports'] if model and node['role'] != 'host' else []
    spare = [name for name in names if name not in shown.values()][:max(0, 28 - len(ports))]
    subinterfaces = [{'port': sub, 'name': shown.get(v.get('parent'), v.get('parent', '')) + '.' + sub.partition('.')[2],
                      'address': v.get('address', ''), 'vlan': v.get('vlan')} for sub, v in (node.get('subinterfaces') or {}).items()]
    syntax = dialect(node)
    return {
        'title': label(node, short=True) if model else label(node),
        # a server (Packet Tracer's Server: its Services tab), or a generic Linux node that can serve
        'server': node['role'] == 'host' and node.get('runtime') == 'firecracker' and (not model or model.get('presentation') == 'server'),
        'brand': model['brand'] if model else 'Linux', 'model': model['model'] if model else 'Nœud Linux générique',
        'role_name': ROLE_NAMES.get(node['role'], node['role']), 'art': art(node, spec), 'ports': ports,
        'port_names': shown, 'connected': connected, 'static': static, 'spare': spare, 'subinterfaces': subinterfaces,
        'cli': TITLES[syntax] if syntax else None,
        'runtime': 'Micro-VM Firecracker' if node['runtime'] == 'firecracker' else 'Conteneur OCI',
        'vlans': sorted(set(node.get('vlans') or [])) if node['role'] == 'switch' else [],
        'ospf': bool(node.get('ospf')),
        'features': features(node),
    }


def live(spec, node, observation):
    """The running node's observed state beside what the lab declares, row by row, with a verdict for each."""
    shown = port_names(node)
    name = lambda port: shown.get(port.partition('.')[0], port.partition('.')[0]) + (('.' + port.partition('.')[2]) if '.' in port else '')
    declared = {**node['interfaces'], **{s: v.get('address', '') for s, v in (node.get('subinterfaces') or {}).items()}}
    interfaces = []
    for item in observation['interfaces']:
        want = declared.get(item['port'], '')
        dynamic = item['port'] in node.get('dhcp_clients', [])
        ok = item['up'] and (dynamic or not want or str(ipaddress.IPv4Interface(want)) in item['addresses'])
        interfaces.append({'name': name(item['port']), 'port': item['port'], 'up': item['up'], 'addresses': item['addresses'],
                           'declared': 'DHCP' if dynamic else want, 'ok': ok})
    observed_routes = {r['network']: r for r in observation['routes'] if r['gateway'] and r.get('protocol') != 'ospf'}
    route_rows = []
    for network, gateway in routes(node):
        seen = observed_routes.pop(network, None)
        route_rows.append({'network': network, 'gateway': gateway, 'port': name(seen['port']) if seen else '—',
                           'state': 'ok' if seen and seen['gateway'] == gateway else 'différente' if seen else 'absente'})
    for network, seen in observed_routes.items():
        route_rows.append({'network': network, 'gateway': seen['gateway'], 'port': name(seen['port']), 'state': 'non déclarée'})
    # Routes OSPF learned are the protocol's result, not a declared item: listed, never an écart.
    route_rows += [{'network': r['network'], 'gateway': r['gateway'], 'port': name(r['port']), 'state': 'ospf',
                    'metric': r.get('metric')} for r in observation['routes'] if r.get('protocol') == 'ospf']
    ospf = None
    if node.get('ospf'):
        from .ospf import enabled_interfaces
        seen = (observation.get('ospf') or {}).get('neighbors', [])
        active = [port for port, value in enabled_interfaces(node).items() if not value['passive']]
        ospf = {'router_id': node['ospf']['router_id'], 'running': observation.get('ospf') is not None,
                'neighbors': [dict(row, port=name(row['port'])) for row in seen],
                'interfaces': [{'name': name(port), 'passive': value['passive'], 'cost': value['cost'],
                                'neighbors': sum(1 for row in seen if row['port'] == port and row['state'] == 'Full')}
                               for port, value in enabled_interfaces(node).items()],
                'complete': all(any(row['port'] == port and row['state'] == 'Full' for row in seen) for port in active)}
    vlans = None
    if observation.get('vlans') is not None:
        from .guest_startup import vlan_plan
        plan = vlan_plan(node) or set()
        seen = {(e['port'], e['vlan'], 'pvid' if e['untagged'] else 'tagged') for e in observation['vlans']}
        vlans = [{'port': shown.get(p, p), 'vlan': v, 'mode': m, 'state': 'ok' if (p, v, m) in seen else 'absente'}
                 for p, v, m in sorted(plan)]
        vlans += [{'port': shown.get(p, p), 'vlan': v, 'mode': m, 'state': 'non déclarée'} for p, v, m in sorted(seen - plan)]
    return {'interfaces': interfaces, 'routes': route_rows, 'vlans': vlans, 'ospf': ospf, 'sessions': observation.get('sessions'),
            'sessions_error': observation.get('sessions_error'),
            'conform': all(i['ok'] for i in interfaces) and all(r['state'] in ('ok', 'ospf') for r in route_rows)
            and all(v['state'] == 'ok' for v in (vlans or []))}
