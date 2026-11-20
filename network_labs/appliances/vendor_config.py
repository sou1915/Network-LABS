"""Vendor-style configuration for modelled native nodes: IOS, FortiOS, Junos and RouterOS subsets.

render() prints a node's lab configuration in its vendor's syntax; apply() reads commands in that syntax
and writes them into the lab draft, which is then validated like any other edit. Nothing here runs vendor
firmware: the commands drive the same Linux configuration (addresses, static routes, firewall policy,
switch VLAN ports) that the workbench forms edit. Commands outside the subset are refused with their line.
"""
import copy
import ipaddress
import itertools
import re
import shlex

from . import ios_store
from .native_models import MODELS, port_names
from .spec import validate

DIALECTS = {'Cisco': 'ios', 'Fortinet': 'fortios', 'Juniper': 'junos', 'MikroTik': 'routeros', 'Arista': 'eos',
            'Huawei': 'vrp', 'Palo Alto': 'panos'}
TITLES = {'ios': 'Cisco IOS', 'fortios': 'FortiOS', 'junos': 'Junos', 'routeros': 'RouterOS', 'eos': 'Arista EOS',
          'vrp': 'Huawei VRP', 'panos': 'PAN-OS'}
HINTS = {'ios': 'Sous-ensemble IOS : hostname, interface, ip address, ip route, vlan, switchport, router ospf (zone 0).',
         'fortios': 'Sous-ensemble FortiOS : system interface (ip), router static, firewall policy.',
         'junos': 'Sous-ensemble Junos : set/delete interfaces … family inet address, routing-options static route, protocols ospf.',
         'routeros': 'Sous-ensemble RouterOS : /ip address, /ip route, /ip firewall filter (chain=forward).',
         'eos': 'Sous-ensemble EOS : hostname, interface, ip address a.b.c.d/n, ip route, vlan, switchport, router ospf.',
         'vrp': 'Sous-ensemble VRP : sysname, interface, ip address, ip route-static, vlan batch, port link-type, ospf.',
         'panos': 'Sous-ensemble PAN-OS : network interface … layer3 ip, zone, static-route, rulebase security rules.'}
# FortiOS predefined services this subset maps to the lab's protocol and port fields.
SERVICES = {'ALL': ('any', None), 'ALL_ICMP': ('icmp', None), 'PING': ('icmp', None), 'HTTP': ('tcp', 80),
            'HTTPS': ('tcp', 443), 'SSH': ('tcp', 22), 'DNS': ('udp', 53), 'TELNET': ('tcp', 23)}


def dialect(node):
    """The vendor syntax a node accepts, or None (generic Linux nodes and brands without a CLI subset)."""
    model = MODELS.get(node.get('model'))
    return DIALECTS.get(model['brand']) if model else None


def _node(spec, name):
    node = next((n for n in spec['nodes'] if n['name'] == name), None)
    if node is None:
        raise ValueError('Équipement inconnu : ' + name)
    if dialect(node) is None:
        raise ValueError('Pas de configuration constructeur pour ce nœud : utiliser le formulaire GUI.')
    return node


def _mask(prefix):
    return str(ipaddress.IPv4Network(f'0.0.0.0/{prefix}').netmask)


def _prefix(address, mask=None):
    """'10.0.0.1/24' or ('10.0.0.1', '255.255.255.0') -> '10.0.0.1/24'."""
    if mask is not None:
        address = f'{address}/{ipaddress.IPv4Network("0.0.0.0/" + mask).prefixlen}'
    return str(ipaddress.IPv4Interface(address))


def _network(value, mask=None):
    if mask is not None:
        value = f'{value}/{mask}'
    return str(ipaddress.IPv4Network(value, strict=False))


LONG_NAMES = {'gi': 'gigabitethernet', 'fa': 'fastethernet', 'te': 'tengigabitethernet', 'ge': 'gigabitethernet',
              'xge': 'xgigabitethernet', 'ethernet': 'ethernet', 'et': 'ethernet'}


IOS_NAMES = {'gi': 'GigabitEthernet', 'fa': 'FastEthernet', 'te': 'TenGigabitEthernet', 'eth': 'Ethernet', 'vlan': 'Vlan'}


def ios_name(label):
    """A Cisco port as IOS writes it in its output: gi0/0/0 -> GigabitEthernet0/0/0 (other names unchanged)."""
    match = re.fullmatch(r'([a-z]+)([\d/.:]+)', label)
    return IOS_NAMES.get(match[1], match[1]) + match[2] if match and match[1] in IOS_NAMES else label


SHORT_NAMES = {'GigabitEthernet': 'Gi', 'FastEthernet': 'Fa', 'TenGigabitEthernet': 'Te', 'Ethernet': 'Et', 'Port-channel': 'Po'}


def ios_short(name):
    """A port as IOS abbreviates it in tables (show vlan brief, show interfaces status): GigabitEthernet0/1 -> Gi0/1."""
    match = re.fullmatch(r'([A-Za-z-]+)([\d/.:]+)', ios_name(name.lower()) if name[:1].islower() else name)
    return SHORT_NAMES.get(match[1], match[1]) + match[2] if match and match[1] in SHORT_NAMES else name


def _port(node, name):
    """A vendor port name (any case, abbreviated as on the device: g0/0/0, gi0/0/0, GigabitEthernet0/0/0) or an eth name."""
    shown = port_names(node)
    typed = name.lower().replace(' ', '')
    for port, label in shown.items():
        if typed in (label.lower(), port.lower()):
            return port
    match = re.fullmatch(r'([a-z-]+)([\d/.:]+)', typed)
    for port, label in shown.items():
        parts = re.fullmatch(r'([A-Za-z-]+)([\d/.:]+)', label)
        if match and parts and match[2] == parts[2]:
            short = parts[1].lower()
            if any(full.startswith(match[1]) for full in (short, LONG_NAMES.get(short, short))):
                return port
    raise ValueError(f'Port inconnu : {name} (ports : {", ".join(shown.values())})')


# Static routes: containers keep them in 'routes', micro-VM guests in 'guest_network'; the default route is
# the node's gateway when the runtime allows it there.

def routes(node):
    """[(network, gateway)] with the default route first when there is one."""
    found = [('0.0.0.0/0', node['gateway'])] if node.get('gateway') else []
    if node['runtime'] == 'firecracker':
        found += [(r['network'], r['gateway']) for r in (node.get('guest_network') or {}).get('routes', [])]
    else:
        found += [(r['destination'], r['gateway']) for r in node.get('routes', [])]
    return found


def _set_routes(node, wanted):
    default = next((gateway for network, gateway in wanted if network == '0.0.0.0/0'), None)
    others = [(network, gateway) for network, gateway in wanted if network != '0.0.0.0/0']
    node.pop('gateway', None)
    guest = node['runtime'] == 'firecracker'
    if default and guest and not _on_port(node, 'eth0', default):
        # A guest's boot gateway sits on eth0; a default route through another port is a declared route.
        others.insert(0, ('0.0.0.0/0', default))
    elif default:
        node['gateway'] = default
    if guest:
        profile = node.get('guest_network') or {'addresses': [], 'routes': []}
        profile['routes'] = [{'network': network, 'gateway': gateway} for network, gateway in others]
        if profile['routes'] or profile['addresses'] or profile.get('port_addresses'):
            node['guest_network'] = profile
        else:
            node.pop('guest_network', None)
        return
    node['routes'] = []
    for network, gateway in others:
        port = next((p for p in node['interfaces'] if _on_port(node, p, gateway)), None)
        if port is None:
            raise ValueError(f'Passerelle {gateway} hors des réseaux des ports.')
        node['routes'].append({'destination': network, 'gateway': gateway, 'interface': port})


def _on_port(node, port, gateway):
    address = node['interfaces'].get(port)
    return bool(address) and ipaddress.IPv4Address(gateway) in ipaddress.IPv4Interface(address).network


def _upsert_route(node, network, gateway):
    current = [(n, g) for n, g in routes(node) if n != network]
    _set_routes(node, current + [(network, gateway)])


def _delete_route(node, network):
    current = routes(node)
    if network not in [n for n, _ in current]:
        raise ValueError('Route absente : ' + network)
    _set_routes(node, [(n, g) for n, g in current if n != network])


def _is_ipv4(word):
    try:
        ipaddress.IPv4Address(word)
        return True
    except ValueError:
        return False


def _set_address(node, port, address):
    if node['role'] == 'switch':
        raise ValueError('Un switch n’a pas d’adresse IP sur ses ports.')
    node['interfaces'][port] = address


def _policy(node):
    if node['role'] != 'firewall' or node.get('firewall') is None:
        raise ValueError('Politique de pare-feu : uniquement sur un pare-feu.')
    return node['firewall']


def _check_hostname(node, value):
    if value.strip('"') != node['name']:
        raise ValueError('Renommer l’équipement depuis le formulaire GUI (Nom système).')


# OSPF, area 0 only, on routers. IOS, EOS and VRP declare networks with wildcard masks; Junos names interfaces.
# Every dialect shows the interface network type it runs; the lab default is point-to-point on every link.

def _mask_of_wildcard(wildcard):
    value = int(ipaddress.IPv4Address(wildcard))
    if value & (value + 1):
        raise ValueError('Masque générique contigu attendu (par exemple 0.0.0.255).')
    return str(ipaddress.IPv4Address(0xffffffff ^ value))


def _acl_address(prefix):
    network = ipaddress.IPv4Network(prefix)
    if network.prefixlen == 0:
        return 'any'
    if network.prefixlen == 32:
        return f'host {network.network_address}'
    return f'{network.network_address} {network.hostmask}'


def _bgp_policy(node, asn=None):
    if node['role'] != 'router':
        raise ValueError('BGP : uniquement sur un routeur.')
    if node.get('bgp') is None:
        if asn is None:
            raise ValueError('BGP : router bgp <AS> d’abord.')
        node['bgp'] = {'asn': asn, 'router_id': '', 'neighbors': [], 'networks': []}
    elif asn is not None and node['bgp']['asn'] != asn:
        raise ValueError(f'BGP : ce routeur est déjà dans l’AS {node["bgp"]["asn"]} (no router bgp pour en changer).')
    return node['bgp']


def _bgp_neighbor(node, address, remote_as=None, remove=False):
    policy = _bgp_policy(node)
    address = str(ipaddress.IPv4Address(address))
    policy['neighbors'] = [n for n in policy['neighbors'] if n['address'] != address]
    if not remove:
        policy['neighbors'].append({'address': address, 'remote_as': int(remote_as)})


def _bgp_network(node, prefix, remove=False):
    policy = _bgp_policy(node)
    prefix = str(ipaddress.IPv4Network(prefix, strict=False))
    policy['networks'] = [n for n in policy['networks'] if n != prefix] + ([] if remove else [prefix])


def _bgp_finish(node):
    policy = node.get('bgp')
    if policy is not None and not policy.get('router_id'):
        addresses = [ipaddress.IPv4Interface(a).ip for a in node['interfaces'].values() if a]
        if not addresses:
            raise ValueError('BGP : router-id requis.')
        policy['router_id'] = str(max(addresses))  # like IOS: the highest interface address


def _ospf_policy(node):
    if node['role'] != 'router':
        raise ValueError('OSPF : uniquement sur un routeur.')
    if node.get('ospf') is None:
        node['ospf'] = {'router_id': '', 'interfaces': {}, 'networks': []}
    return node['ospf']


def _ospf_area(value):
    if value not in ('0', '0.0.0.0'):
        raise ValueError('OSPF : zone 0 (backbone, 0.0.0.0) uniquement.')


def _ospf_network(node, address, wildcard, remove=False):
    from .ospf import configure_network
    policy = _ospf_policy(node)
    if '/' in address:
        network = ipaddress.IPv4Network(address, strict=False)
        address, wildcard = str(network.network_address), str(network.hostmask)
    if remove and str(ipaddress.IPv4Network(f'{address}/{wildcard}', strict=False)) not in policy['networks']:
        raise ValueError(f'Réseau OSPF absent : {address} {wildcard}')
    try:
        configure_network(node, address, wildcard, remove=remove)
    except ValueError:
        raise ValueError(f'OSPF : aucun port de ce routeur n’est dans {address} {wildcard} (masque générique contigu).') from None


def _ospf_port(node, port, remove=False):
    """Junos style: OSPF on one port, which advertises that port's network."""
    policy = _ospf_policy(node)
    address = node['interfaces'].get(port)
    if not address:
        raise ValueError('OSPF : le port doit avoir une adresse IPv4.')
    network = str(ipaddress.IPv4Interface(address).network)
    if remove:
        policy['networks'] = [n for n in policy['networks'] if n != network]
        policy['interfaces'].pop(port, None)
        return
    policy['interfaces'].setdefault(port, {'cost': 10, 'passive': False})
    if network not in policy['networks']:
        policy['networks'].append(network)


def _ospf_finish(node, pending):
    """Per-port settings given before or after the networks that enable the port, then IOS's default router ID."""
    policy = node.get('ospf')
    if policy is None:
        if pending:
            raise ValueError('Réglage OSPF d’interface sans processus OSPF (router ospf).')
        return
    shown = port_names(node)
    for port, values in pending.items():
        if port not in policy['interfaces']:
            raise ValueError(f'{shown.get(port, port)} : réglage OSPF sur un port qu’aucun réseau OSPF ne couvre.')
        policy['interfaces'][port].update(values)
    if not policy.get('router_id'):
        addresses = [ipaddress.IPv4Interface(a).ip for a in node['interfaces'].values() if a]
        if not addresses:
            raise ValueError('OSPF : router-id requis.')
        policy['router_id'] = str(max(addresses))  # IOS picks the highest interface address


def _ospf_enabled(node):
    if not node.get('ospf'):
        return {}
    from .ospf import enabled_interfaces
    return enabled_interfaces(node)


def _wildcard(network):
    network = ipaddress.IPv4Network(network)
    return f'{network.network_address} {network.hostmask}'


# ---- rendering ----

def render(spec, name):
    node = _node(spec, name)
    return {'ios': _render_ios, 'fortios': _render_fortios, 'junos': _render_junos, 'routeros': _render_routeros,
            'eos': lambda n: _render_ios(n, eos=True), 'vrp': _render_vrp, 'panos': _render_panos}[dialect(node)](node)


def _render_ios(node, eos=False):
    """IOS, or Arista EOS (same structure, prefix-length addresses and routes)."""
    shown = port_names(node)
    if not eos:
        shown = {port: ios_name(label) for port, label in shown.items()}  # IOS writes its ports in full
    system = 'Arista EOS' if eos else 'Cisco IOS'
    lines = [f'! Network LABS · sous-ensemble {system.split()[-1]}', f'! le nœud exécute Linux, pas {system}', '!',
             'hostname ' + ios_store.hostname(node), '!']
    stored = ios_store.render_global(node)
    if stored:
        lines += stored + ['!']
    for vid in node.get('vlans', []):
        if vid != 1:
            name = ios_store.vlan_name(node, vid)
            lines += [f'vlan {vid}'] + ([f' name {name}'] if name else []) + ['!']
    from .etherchannel import bundle_of, bundles, number
    for bond in sorted(bundles(node), key=number) if node.get('runtime') == 'firecracker' else ():
        switchport = node.get('switchports', {}).get(bond) or {'mode': 'access', 'vlan': 1}
        lines.append('interface ' + shown.get(bond, bond))
        if switchport['mode'] == 'trunk':
            allowed = switchport['allowed']
            lines += [' switchport mode trunk', f' switchport trunk native vlan {switchport["native_vlan"]}',
                      ' switchport trunk allowed vlan ' + ('all' if allowed == 'all' else ','.join(map(str, allowed)))]
        else:
            lines += [' switchport mode access', f' switchport access vlan {switchport["vlan"]}']
        lines.append('!')
    for port, address in node['interfaces'].items():
        lines.append('interface ' + shown[port])
        described, extra = ios_store.render_interface(node, port)
        lines += [' ' + line for line in described]
        switchport = node.get('switchports', {}).get(bundle_of(node, port))
        if node['role'] == 'switch':
            if switchport and switchport['mode'] == 'trunk':
                allowed = switchport['allowed']
                lines += [' switchport mode trunk', f' switchport trunk native vlan {switchport["native_vlan"]}',
                          ' switchport trunk allowed vlan ' + ('all' if allowed == 'all' else ','.join(map(str, allowed)))]
            else:
                lines += [' switchport mode access', f' switchport access vlan {switchport["vlan"] if switchport else 1}']
        elif address:
            interface = ipaddress.IPv4Interface(address)
            lines.append(f' ip address {address}' if eos else f' ip address {interface.ip} {interface.netmask}')
        else:
            lines.append(' no ip address')
        if (node.get('acl_ports') or {}).get(port) and not eos:
            lines.append(f' ip access-group {node["acl_ports"][port]} in')
        ospf_port = _ospf_enabled(node).get(port)
        if ospf_port:
            if ospf_port['network_type'] == 'point-to-point':
                lines.append(' ip ospf network point-to-point')
            elif ospf_port['priority'] != 1:
                lines.append(f' ip ospf priority {ospf_port["priority"]}')
            lines.append(f' ip ospf cost {ospf_port["cost"]}')
        lines += [' ' + line for line in extra]
        if bundle_of(node, port) != port:
            lines.append(f' channel-group {number(bundle_of(node, port))} mode {bundles(node)[bundle_of(node, port)]["mode"]}')
        if port in (node.get('shutdown') or []):
            lines.append(' shutdown')
        lines.append('!')
    for name, sub in sorted((node.get('subinterfaces') or {}).items()):
        parent, _, vid = name.partition('.')
        lines += [f'interface {shown.get(parent, parent)}.{vid}', f' encapsulation dot1Q {sub["vlan"]}']
        if sub.get('address'):
            interface = ipaddress.IPv4Interface(sub['address'])
            lines.append(f' ip address {sub["address"]}' if eos else f' ip address {interface.ip} {interface.netmask}')
        lines.append('!')
    for name, svi in sorted((node.get('svis') or {}).items()):  # a switch's management SVI
        described, extra = ios_store.render_interface(node, name)
        lines += [f'interface Vlan{svi["vlan"]}'] + [' ' + line for line in described]
        if svi.get('address'):
            interface = ipaddress.IPv4Interface(svi['address'])
            lines.append(f' ip address {svi["address"]}' if eos else f' ip address {interface.ip} {interface.netmask}')
        else:
            lines.append(' no ip address')
        lines += [' ' + line for line in extra]
        if name in (node.get('shutdown') or []):
            lines.append(' shutdown')
        lines.append('!')
    server = node.get('dhcp_server')
    if server and not eos and node['interfaces'].get(server['interface']):
        relayed = 'network' in server  # a remote LAN's pool: its own network, no router address inside it
        network = ipaddress.IPv4Network(server['network']) if relayed else ipaddress.IPv4Interface(node['interfaces'][server['interface']]).network
        own = None if relayed else ipaddress.IPv4Interface(node['interfaces'][server['interface']]).ip
        start, end = ipaddress.IPv4Address(server['start']), ipaddress.IPv4Address(server['end'])
        first, last = network.network_address + 1, network.broadcast_address - 1
        for low, high in ((first, start - 1), (end + 1, last)):
            if low <= high and not (low == high == own):
                lines.append(f'ip dhcp excluded-address {low}' + (f' {high}' if high != low else ''))
        lease = int(server.get('lease_seconds', 86400))
        lines += [f'ip dhcp pool {server.get("name", "LAN")}', f' network {network.network_address} {network.netmask}']
        if server.get('router'):
            lines.append(f' default-router {server["router"]}')
        if server.get('dns'):
            lines.append(' dns-server ' + ' '.join(server['dns']))
        lines += [f' lease {lease // 86400} {lease % 86400 // 3600} {lease % 3600 // 60}', '!']
    for name, entries in sorted((node.get('acls') or {}).items()) if not eos else []:
        if name.isdigit():  # a numbered list: « access-list N … » lines
            standard = int(name) < 100 or 1300 <= int(name) <= 1999
            for entry in entries:
                port = f' eq {entry["dport"]}' if 'dport' in entry else ''
                body = _acl_address(entry['source']) if standard else \
                    f'{entry["protocol"]} {_acl_address(entry["source"])} {_acl_address(entry["destination"])}{port}'
                lines.append(f'access-list {name} {entry["action"]} {body}')
            lines.append('!')
            continue
        lines.append(f'ip access-list extended {name}')
        for index, entry in enumerate(entries, 1):
            port = f' eq {entry["dport"]}' if 'dport' in entry else ''
            lines.append(f' {index * 10} {entry["action"]} {entry["protocol"]} {_acl_address(entry["source"])} '
                         f'{_acl_address(entry["destination"])}{port}')
        lines.append('!')
    if node.get('bgp'):
        policy = node['bgp']
        lines += [f'router bgp {policy["asn"]}', f' bgp router-id {policy["router_id"]}']
        lines += [f' neighbor {n["address"]} remote-as {n["remote_as"]}' for n in policy['neighbors']]
        for network in policy['networks']:
            net = ipaddress.IPv4Network(network)
            lines.append(f' network {network}' if eos else f' network {net.network_address} mask {net.netmask}')
        lines.append('!')
    if node.get('ospf'):
        policy = node['ospf']
        lines += [f'router ospf {policy["process_id"]}', f' router-id {policy["router_id"]}']
        lines += [f' passive-interface {shown[port]}' for port, value in _ospf_enabled(node).items() if value['passive']]
        lines += [f' network {network} area 0.0.0.0' if eos else f' network {_wildcard(network)} area 0' for network in policy['networks']]
        lines.append('!')
    for network, gateway in routes(node):
        net = ipaddress.IPv4Network(network)
        lines.append(f'ip route {network} {gateway}' if eos else f'ip route {net.network_address} {net.netmask} {gateway}')
    if node.get('cli_config'):  # « ip route NET MASK PORT » lines, kept as typed
        lines += [l for l in ios_store.config(node)['global'] if l.lower().startswith('ip route ')]
    return '\n'.join(lines + ['!'] + ios_store.render_tail(node) + ['end']) + '\n'


def _render_vrp(node):
    shown = port_names(node)
    lines = ['# Network LABS · sous-ensemble VRP', '# le nœud exécute Linux, pas Huawei VRP', f'sysname {node["name"]}', '#']
    vlans = [vid for vid in node.get('vlans', []) if vid != 1]
    if vlans:
        lines += ['vlan batch ' + ' '.join(map(str, vlans)), '#']
    for port, address in node['interfaces'].items():
        lines.append('interface ' + shown[port])
        described, extra = ios_store.render_interface(node, port)
        lines += [' ' + line for line in described]
        switchport = node.get('switchports', {}).get(port)
        if node['role'] == 'switch':
            if switchport and switchport['mode'] == 'trunk':
                allowed = switchport['allowed']
                lines += [' port link-type trunk', f' port trunk pvid vlan {switchport["native_vlan"]}',
                          ' port trunk allow-pass vlan ' + ('all' if allowed == 'all' else ' '.join(map(str, allowed)))]
            else:
                lines += [' port link-type access', f' port default vlan {switchport["vlan"] if switchport else 1}']
        elif address:
            interface = ipaddress.IPv4Interface(address)
            lines.append(f' ip address {interface.ip} {interface.netmask}')
        ospf_port = _ospf_enabled(node).get(port)
        if ospf_port:
            if ospf_port['network_type'] == 'point-to-point':
                lines.append(' ospf network-type p2p')
            elif ospf_port['priority'] != 1:
                lines.append(f' ospf dr-priority {ospf_port["priority"]}')
            lines.append(f' ospf cost {ospf_port["cost"]}')
        lines.append('#')
    if node.get('bgp'):
        policy = node['bgp']
        lines += [f'bgp {policy["asn"]}', f' router-id {policy["router_id"]}']
        lines += [f' peer {n["address"]} as-number {n["remote_as"]}' for n in policy['neighbors']]
        lines.append(' ipv4-family unicast')
        for network in policy['networks']:
            net = ipaddress.IPv4Network(network)
            lines.append(f'  network {net.network_address} {net.netmask}')
        lines.append('#')
    if node.get('ospf'):
        policy = node['ospf']
        lines.append(f'ospf {policy["process_id"]} router-id {policy["router_id"]}')
        lines += [f' silent-interface {shown[port]}' for port, value in _ospf_enabled(node).items() if value['passive']]
        lines += [' area 0.0.0.0'] + [f'  network {_wildcard(network)}' for network in policy['networks']] + ['#']
    for network, gateway in routes(node):
        net = ipaddress.IPv4Network(network)
        lines.append(f'ip route-static {net.network_address} {net.netmask} {gateway}')
    return '\n'.join(lines + ['return']) + '\n'


def _zone(name):
    """The zone the PAN-OS view gives each port: one zone per port ('l3-ethernet1-1')."""
    return 'l3-' + name.replace('/', '-')


def _route_name(network):
    return 'r-' + network.replace('/', '-')


def _render_panos(node):
    shown = port_names(node)
    lines = ['# Network LABS · sous-ensemble PAN-OS', '# le nœud exécute Linux, pas PAN-OS',
             f'set deviceconfig system hostname {node["name"]}']
    for port, address in node['interfaces'].items():
        if address:
            lines.append(f'set network interface ethernet {shown[port]} layer3 ip {address}')
        lines.append(f'set zone {_zone(shown[port])} network layer3 {shown[port]}')
    for network, gateway in routes(node):
        lines.append(f'set network virtual-router default routing-table ip static-route {_route_name(network)} '
                     f'destination {network} nexthop ip-address {gateway}')
    if node['role'] == 'firewall' and node.get('firewall') is not None:
        for rule in node['firewall']['rules']:
            source = _zone(shown[rule['in']]) if rule.get('in') else 'any'
            target = _zone(shown[rule['out']]) if rule.get('out') else 'any'
            lines.append(f'set rulebase security rules {rule["name"]} from {source} to {target} '
                         f'source {rule.get("source", "any")} destination {rule.get("destination", "any")} '
                         f'application any service {_panos_service(rule)} '
                         f'action {"allow" if rule["action"] == "accept" else "deny"}')
    return '\n'.join(lines) + '\n'


def _panos_service(rule):
    protocol, port = rule.get('protocol', 'any'), rule.get('dport')
    named = {('tcp', 80): 'service-http', ('tcp', 443): 'service-https'}
    if (protocol, port) in named:
        return named[(protocol, port)]
    if port:
        return f'{protocol}-{port}'
    return 'icmp' if protocol == 'icmp' else 'any'


def _service(rule):
    protocol, port = rule.get('protocol', 'any'), rule.get('dport')
    for service, value in SERVICES.items():
        if value == (protocol, port) and service != 'PING':
            return service
    return f'{protocol.upper()}-{port}' if port else protocol.upper()


def _render_fortios(node):
    shown = port_names(node)
    lines = ['# Network LABS · sous-ensemble FortiOS', '# le nœud exécute Linux, pas FortiOS',
             'config system global', f'    set hostname "{node["name"]}"', 'end', 'config system interface']
    for port, address in node['interfaces'].items():
        lines.append(f'    edit "{shown[port]}"')
        if address:
            interface = ipaddress.IPv4Interface(address)
            lines.append(f'        set ip {interface.ip} {interface.netmask}')
        lines.append('    next')
    lines.append('end')
    server = node.get('dhcp_server')
    if server:
        interface = ipaddress.IPv4Interface(node['interfaces'].get(server['interface']) or '0.0.0.0/0')
        port = shown.get(server['interface'], server['interface'])
        lines += ['config system dhcp server', '    edit 1', f'        set interface "{port}"',
                  f'        set netmask {interface.netmask}']
        if server.get('router'):
            lines.append(f'        set default-gateway {server["router"]}')
        for i, address in enumerate(server.get('dns') or [], 1):
            lines.append(f'        set dns-server{i} {address}')
        lines += [f'        set lease-time {server.get("lease_seconds", 600)}', '        config ip-range', '            edit 1',
                  f'                set start-ip {server["start"]}', f'                set end-ip {server["end"]}', '            next',
                  '        end', '    next', 'end']
    lines.append('config router static')
    for index, (network, gateway) in enumerate(routes(node), 1):
        net = ipaddress.IPv4Network(network)
        lines.append(f'    edit {index}')
        if net.prefixlen:
            lines.append(f'        set dst {net.network_address} {net.netmask}')
        lines.append(f'        set gateway {gateway}')
        device = next((p for p in node['interfaces'] if _on_port(node, p, gateway)), None)
        if device:
            lines.append(f'        set device "{shown[device]}"')
        lines.append('    next')
    lines.append('end')
    if node['role'] == 'firewall' and node.get('firewall') is not None:
        lines.append('config firewall policy')
        for index, rule in enumerate(node['firewall']['rules'], 1):
            lines += [f'    edit {index}', f'        set name "{rule["name"]}"',
                      f'        set srcintf "{shown.get(rule.get("in"), "any")}"',
                      f'        set dstintf "{shown.get(rule.get("out"), "any")}"',
                      f'        set srcaddr "{rule.get("source", "all")}"', f'        set dstaddr "{rule.get("destination", "all")}"',
                      f'        set action {"accept" if rule["action"] == "accept" else "deny"}',
                      '        set schedule "always"', f'        set service "{_service(rule)}"']
            if any(r['name'] == rule['name'] + '-nat' for r in node['firewall']['nat']):
                lines.append('        set nat enable')
            lines.append('    next')
        lines.append('end')
        vips = [r for r in node['firewall']['nat'] if r['type'] == 'dnat']
        if vips:
            lines.append('config firewall vip')
            for vip in vips:
                lines += [f'    edit "{vip["name"]}"', f'        set extip {vip["destination"].split("/")[0]}',
                          f'        set mappedip "{vip["to"]}"', f'        set extintf "{shown.get(vip["in"], vip["in"])}"']
                if vip.get('dport'):
                    lines += ['        set portforward enable', f'        set protocol {vip["protocol"]}',
                              f'        set extport {vip["dport"]}',
                              f'        set mappedport {vip.get("to_port", vip["dport"])}']
                lines.append('    next')
            lines.append('end')
    return '\n'.join(lines) + '\n'


def _render_junos(node):
    shown = port_names(node)
    lines = ['# Network LABS · sous-ensemble Junos', '# le nœud exécute Linux, pas Junos', f'set system host-name {node["name"]}']
    for port, address in node['interfaces'].items():
        if address:
            lines.append(f'set interfaces {shown[port]} unit 0 family inet address {address}')
    for network, gateway in routes(node):
        lines.append(f'set routing-options static route {network} next-hop {gateway}')
    router_id = (node.get('ospf') or node.get('bgp') or {}).get('router_id')
    if router_id:
        lines.append(f'set routing-options router-id {router_id}')
    if node.get('bgp'):
        policy = node['bgp']
        lines += [f'set routing-options autonomous-system {policy["asn"]}', 'set protocols bgp group EBGP type external']
        lines += [f'set protocols bgp group EBGP neighbor {n["address"]} peer-as {n["remote_as"]}' for n in policy['neighbors']]
        if policy['networks']:
            lines.append('set protocols bgp group EBGP export ANNONCE-BGP')
            lines += [f'set policy-options policy-statement ANNONCE-BGP term 1 from route-filter {n} exact' for n in policy['networks']]
            lines.append('set policy-options policy-statement ANNONCE-BGP term 1 then accept')
    if node.get('ospf'):
        for port, value in _ospf_enabled(node).items():
            stem = f'set protocols ospf area 0.0.0.0 interface {shown[port]}.0'
            lines.append(stem + (' interface-type p2p' if value['network_type'] == 'point-to-point' else ''))
            lines.append(f'{stem} metric {value["cost"]}')
            if value['network_type'] == 'broadcast' and value['priority'] != 1:
                lines.append(f'{stem} priority {value["priority"]}')
            if value['passive']:
                lines.append(stem + ' passive')
    return '\n'.join(lines) + '\n'


def _render_routeros(node):
    shown = port_names(node)
    lines = ['# Network LABS · sous-ensemble RouterOS', '# le nœud exécute Linux, pas RouterOS',
             '/system identity', f'set name={node["name"]}', '/ip address']
    lines += [f'add address={address} interface={shown[port]}' for port, address in node['interfaces'].items() if address]
    lines.append('/ip route')
    lines += [f'add dst-address={network} gateway={gateway}' for network, gateway in routes(node)]
    if node['role'] == 'firewall' and node.get('firewall') is not None:
        lines.append('/ip firewall filter')
        for rule in node['firewall']['rules']:
            words = ['add', 'action=' + rule['action'], 'chain=forward']
            for field, key in (('in', 'in-interface'), ('out', 'out-interface')):
                if rule.get(field):
                    words.append(f'{key}={shown.get(rule[field], rule[field])}')
            for field, key in (('source', 'src-address'), ('destination', 'dst-address'), ('protocol', 'protocol'),
                               ('dport', 'dst-port')):
                if rule.get(field) not in (None, 'any'):
                    words.append(f'{key}={rule[field]}')
            words.append(f'comment="{rule["name"]}"')
            lines.append(' '.join(words))
    return '\n'.join(lines) + '\n'


# ---- applying ----

def apply(spec, name, text):
    """Apply vendor commands to a copy of the lab draft; returns the validated draft or raises ValueError('Ligne N : ...')."""
    if not isinstance(text, str) or len(text) > 65536:
        raise ValueError('Configuration : texte de 64 Kio au plus.')
    draft = copy.deepcopy(spec)
    node = _node(draft, name)
    parsers = {'ios': IOS, 'eos': IOS, 'vrp': VRP, 'fortios': FortiOS, 'junos': Junos, 'routeros': RouterOS, 'panos': PANOS}
    parser = parsers[dialect(node)](node)
    for number, line in enumerate(text.splitlines(), 1):
        command = line.strip()
        if not command or command.startswith(parser.comment):
            continue
        try:
            parser.line(command)
        except (ValueError, KeyError, IndexError) as error:
            raise ValueError(f'Ligne {number} : {command}\n{error}') from None
    parser.finish()
    return validate(draft)


class IOS:
    comment = '!'

    def __init__(self, node):
        self.node, self.port = node, None
        self.pool = None  # 'ip dhcp pool' being configured: {'network', 'router', 'dns', 'lease'}
        self.excluded = None  # 'ip dhcp excluded-address' ranges, when the block sets any
        self.ospf = False  # inside 'router ospf'
        self.acl = None  # inside 'ip access-list extended NAME'
        self.bgp = False  # inside 'router bgp'
        self.ospf_ports = {}  # per-port OSPF settings, applied once the networks are known
        self.block = self.block_mode = None  # inside 'line con 0', 'router rip'…: lines kept in the configuration
        self.range = None  # 'interface range': the ports the next interface lines apply to

    def line(self, command):
        node, low = self.node, command.lower()
        if low in ('enable', 'configure terminal', 'conf t', 'write memory', 'wr'):
            return
        if low in ('end', 'exit'):
            self.port, self.ospf, self.acl, self.bgp, self.block, self.range = None, False, None, False, None, None
            if self.pool is not None:
                self.pool['open'] = False
            return
        words = command.split()
        if self.block is not None:
            if ios_store.store(node, self.block_mode, command, block=self.block):
                return
            self.block = self.block_mode = None  # a global command leaves the block, as on IOS
        match = re.fullmatch(r'(no )?vlan (\d+)', low)
        if match:  # « vlan N » creates it and enters config-vlan (« name … »); « no vlan N » removes it and its name
            self.port, self.ospf, self.acl, self.bgp, self.range = None, False, None, False, None
            self._vlan(int(match[2]), bool(match[1]))
            header = f'vlan {int(match[2])}'
            if match[1]:
                ios_store.drop_block(node, header)
            self.block, self.block_mode = (None, None) if match[1] else (header, 'config-vlan')
            return
        mode, header = ios_store.enter_block(node, low)
        if mode is not None:
            self.port, self.ospf, self.acl, self.bgp, self.range = None, False, None, False, None
            self.block, self.block_mode = (None, None) if mode == 'removed' else (header, mode)
            return
        if words[0].lower() == 'hostname':
            ios_store.store(node, 'config', command)  # the prompt and « show running-config » follow; the lab keeps its name
            return
        if re.fullmatch(r'(no )?access-list \d+.*', low):
            return self._numbered_acl(low, words)
        if low.startswith(('ip dhcp ', 'no ip dhcp ')) or (self.pool is not None and self.pool.get('open')):
            return self._dhcp(low, words)
        match = re.fullmatch(r'(no )?router bgp (\d+)', low)
        if match:
            if match[1]:
                node['bgp'], self.bgp = None, False
            else:
                _bgp_policy(node, int(match[2]))
                self.port, self.ospf, self.acl, self.bgp = None, False, None, True
            return
        if self.bgp and not low.startswith('interface ') and self._bgp(low, words):
            return
        self.bgp = False
        match = re.fullmatch(r'(no )?ip access-list extended (\S+)', low)
        if match:
            name = words[-1]
            if match[1]:
                node.get('acls', {}).pop(name, None)
                node['acl_ports'] = {p: n for p, n in (node.get('acl_ports') or {}).items() if n != name}
                self.acl = None
            else:
                node.setdefault('acls', {}).setdefault(name, [])
                self.port, self.ospf, self.acl = None, False, name
            return
        if self.acl is not None and not low.startswith('interface ') and self._acl_entry(low, words):
            return
        self.acl = None
        if re.fullmatch(r'no router ospf \d+', low):
            self.node['ospf'], self.ospf, self.ospf_ports = None, False, {}
            return
        match = re.fullmatch(r'router ospf (\d+)', low)
        if match:
            _ospf_policy(node)['process_id'] = int(match[1])
            self.port, self.ospf = None, True
            return
        if self.ospf and not low.startswith('interface ') and self._ospf(low, words):
            return
        self.ospf = False
        match = re.fullmatch(r'no interface (?:port-channel|po)\s*(\d+)', low)
        if match and node['role'] == 'switch' and node.get('runtime') == 'firecracker':
            return self._drop_port_channel(f'bond{int(match[1])}')
        match = re.fullmatch(r'no interface vlan\s*(\d+)', low)
        if match and node['role'] == 'switch':
            name = f'vlan{int(match[1])}'
            (node.get('svis') or {}).pop(name, None)
            node['shutdown'] = [p for p in node.get('shutdown') or [] if p != name]
            if node.get('cli_config'):
                ios_store.config(node)['interfaces'].pop(name, None)
            return
        if low.startswith('no interface ') and '.' in words[2]:
            parent, _, vid = words[2].partition('.')
            node.get('subinterfaces', {}).pop(f'{_port(node, parent)}.{vid}', None)
            return
        match = re.fullmatch(r'interface range (.+)', low)
        if match:
            self.range = _port_range(node, command.split(None, 2)[2])
            self.port = self.range[0]
            return
        self.range = None if low.startswith('interface ') else self.range
        if low.startswith('interface '):
            name = command.split(None, 1)[1].strip()
            if '.' in name and not name.lower().startswith('vlan'):
                parent, _, vid = name.rpartition('.')
                if node['role'] not in ('router', 'firewall') or not vid.isdigit():
                    raise ValueError('Sous-interfaces 802.1Q : routeur ou pare-feu, interface <port>.<n>.')
                port = _port(node, parent)
                self.port = f'{port}.{vid}'
                node.setdefault('subinterfaces', {}).setdefault(self.port, {'parent': port, 'vlan': None, 'address': ''})
                return
            match = re.fullmatch(r'vlan\s*(\d+)', name.lower())
            if match and node['role'] == 'switch':
                self.port = self._svi(int(match[1]))
                return
            match = re.fullmatch(r'(?:port-channel|po)\s*(\d+)', name.lower())
            if match and node['role'] == 'switch' and node.get('runtime') == 'firecracker':
                self.port = self._port_channel(int(match[1]))
                return
            self.port = _port(node, name)
            return
        if low in ('ip routing', 'no ip routing') and node['role'] == 'switch' and node.get('runtime') == 'firecracker':
            from .native_models import MODELS
            from .svi import layer3
            if not layer3(node):
                model = MODELS.get(node.get('model'), {}).get('title') or 'switch'
                raise ValueError(f'Network LABS : le {model} est un switch de niveau 2 ; ip routing demande un switch de niveau 3 '
                                 '(Catalyst 9200L).')
            self.port, self.range = None, None  # a global command leaves the interface, as on IOS
            ios_store.store(node, 'config', low)  # the SVIs route between them (svi.routed), live too
            return
        match = re.fullmatch(r'(no )?spanning-tree vlan (\S+)(?: priority(?: (\d+))?| root (primary|secondary))?', low)
        if match and node['role'] == 'switch' and node.get('runtime') == 'firecracker':
            self.port, self.range = None, None  # a global command leaves the interface, as on IOS
            return self._stp_priority(match)
        if low.startswith(('ip route ', 'no ip route ')) and node['role'] == 'switch' and node.get('runtime') == 'firecracker':
            return self._switch_route(low, words)
        if low.startswith(('ip route ', 'no ip route ')):
            values = words[3:] if low.startswith('no') else words[2:]
            # 'ip route 10.0.0.0 255.0.0.0 GW' (IOS) or 'ip route 10.0.0.0/8 GW' (EOS).
            if '/' in values[0]:
                network, rest = _network(values[0]), values[1:]
            else:
                network, rest = _network(values[0], values[1]), values[2:]
            from . import ios_routes
            target = ipaddress.IPv4Network(network)
            if low.startswith('no'):
                held = any(n == target for n, _ in ios_routes.port_routes(node))
                ios_routes.store(node, target, None, remove=True)
                return None if held and network not in [n for n, _ in routes(node)] else _delete_route(node, network)
            if rest and not _is_ipv4(rest[0]):  # « ip route NET MASK PORT [NEXT-HOP] »
                if len(rest) > 1 and _is_ipv4(rest[1]):
                    _port(node, rest[0])
                    return _upsert_route(node, network, rest[1])
                if network in [n for n, _ in routes(node)]:
                    _delete_route(node, network)
                return ios_routes.store(node, target, rest[0])
            ios_routes.store(node, target, None, remove=True)
            return _upsert_route(node, network, rest[0])
        if self.port is None:
            if ios_store.store(node, 'config', command):
                return
            raise ValueError('Commande non prise en charge ici (sous-ensemble : hostname, interface, ip route, vlan).')
        if self.range and len(self.range) > 1:
            for port in self.range:  # « interface range »: each line on every port of the range
                self.port = port
                self._interface(command, low, words)
            return
        return self._interface(command, low, words)

    def _svi(self, vid):
        """« interface vlan N » on a switch: its management SVI, created shut as on a Catalyst (no shutdown brings it up)."""
        node, name = self.node, f'vlan{vid}'
        svis = node.setdefault('svis', {})
        if name not in svis:
            from .svi import layer3
            if svis and node.get('runtime') == 'firecracker' and not layer3(node):
                raise ValueError('Une seule interface vlan de gestion sur ce switch de niveau 2 (Catalyst 2960) ; '
                                 'un Catalyst 9200L en prend plusieurs et route entre elles (ip routing).')
            if len(svis) >= 8 and node.get('runtime') == 'firecracker':
                raise ValueError('Huit interfaces vlan au plus par switch dans le lab.')
            self._vlan(vid, False)
            svis[name] = {'vlan': vid, 'address': ''}
            node['shutdown'] = sorted(set(node.get('shutdown') or []) | {name})
        return name

    def _interface(self, command, low, words):
        node = self.node
        if low.split()[:1] == ['standby'] or low.split()[:2] == ['no', 'standby']:
            from .hsrp import configure  # HSRP: a router port's or subinterface's standby groups (acts in the guest)
            return configure(node, self.port, ' '.join(command.split()))
        if self.port in (node.get('svis') or {}):
            svi = node['svis'][self.port]
            if low.startswith('ip address '):
                svi['address'] = _prefix(words[2]) if '/' in words[2] else _prefix(words[2], words[3])
            elif low == 'no ip address':
                svi['address'] = ''
            elif low in ('shutdown', 'no shutdown'):
                down = [p for p in node.get('shutdown', []) if p != self.port]
                node['shutdown'] = sorted(down + [self.port]) if low == 'shutdown' else down
            elif not ios_store.store(node, 'config-if', command, port=self.port):
                raise ValueError('interface vlan : ip address, shutdown / no shutdown, description.')
            return
        sub = (node.get('subinterfaces') or {}).get(self.port)
        if sub is not None:
            match = re.fullmatch(r'encapsulation dot1q (\d{1,4})', low)
            if match:
                sub['vlan'] = int(match[1])
                return
            if low.startswith('ip address '):
                sub['address'] = _prefix(words[2]) if '/' in words[2] else _prefix(words[2], words[3])
                return
            if low == 'no ip address':
                sub['address'] = ''
                return
            if ios_store.store(node, 'config-if', command, port=self.port):
                return
            raise ValueError('Sous-interface : encapsulation dot1Q <vlan>, ip address, description.')
        if low.startswith('ip address '):
            return _set_address(node, self.port, _prefix(words[2]) if '/' in words[2] else _prefix(words[2], words[3]))
        match = re.fullmatch(r'(no )?ip access-group (\S+) (in|out)', low)
        if match:
            if match[3] == 'out':
                raise ValueError('ACL sortante non prise en charge : appliquer la liste en entrée (in) sur l’interface d’arrivée.')
            if '.' in self.port:
                raise ValueError('ip access-group : sur un port physique.')
            ports = node.setdefault('acl_ports', {})
            if match[1]:
                ports.pop(self.port, None)
            else:
                ports[self.port] = command.split()[-2]
            return
        match = re.fullmatch(r'ip ospf (cost (\d+)|network (point-to-point|broadcast)|priority (\d+))', low)
        if match:
            settings = self.ospf_ports.setdefault(self.port, {})
            if match[2]:
                settings['cost'] = int(match[2])
            elif match[3]:
                settings['network_type'] = match[3]
            else:
                settings['priority'] = int(match[4])
            return
        if low == 'no ip address':
            return _set_address(node, self.port, '')
        if low.startswith('switchport') and not low.startswith('switchport port-security'):
            return self._switchport(low)
        if low.startswith('switchport port-security') and node['role'] == 'switch' and node.get('runtime') == 'firecracker':
            self._port_security(low)  # IOS's checks; the line is then kept (ios_store) and acts through port_guard
        match = re.fullmatch(r'(no )?channel-group(?: (\d+) mode (\S+))?', low)
        if match and node['role'] == 'switch' and node.get('runtime') == 'firecracker':
            return self._channel_group(bool(match[1]), match[2], match[3])
        if low in ('shutdown', 'no shutdown') and self.port in (node.get('port_channels') or {}):
            members = node['port_channels'][self.port]['members']  # a Port-channel's shutdown is its members'
            rest = [p for p in node.get('shutdown') or [] if p not in members]
            node['shutdown'] = sorted(rest + (members if low == 'shutdown' else []))
            return
        match = re.fullmatch(r'(no )?spanning-tree (cost|port-priority)(?: (\d+))?', low)
        if match and node['role'] == 'switch' and node.get('runtime') == 'firecracker':
            if not match[1] and match[3] is None:
                raise ValueError('Incomplete command.')
            from .spanning_tree import ios_port
            ios_port(node, self.port, 'cost' if match[2] == 'cost' else 'priority', None if match[1] else int(match[3]))
            ios_store.store(node, 'config-if', f'no spanning-tree {match[2]}' if match[1] else f'spanning-tree {match[2]} {match[3]}',
                            port=self.port)
            return
        if low in ('no shutdown', 'shutdown'):
            # shutdown brings the port's link down for real (a micro-VM too, a switch port included), no shutdown up.
            down = [p for p in node.get('shutdown', []) if p != self.port]
            node['shutdown'] = sorted(down + [self.port]) if low == 'shutdown' else down
            return
        if low == 'no shutdown':
            return  # a micro-VM switch's ports are always up: the habit of typing it is kept
        if ios_store.store(node, 'config-if', command, port=self.port):
            return
        if ios_store.store(node, 'config', command):
            self.port, self.range = None, None  # a global command leaves the interface, as on IOS
            return
        raise ValueError('Commande d’interface non prise en charge (ip address, ip ospf, switchport, description).')

    def _switch_route(self, low, words):
        """« ip route NET MASK NEXT-HOP » on a Layer 3 switch: kept as the IOS line, used once ip routing is on (svi)."""
        from .svi import layer3, store_route
        if not layer3(self.node):
            raise ValueError('Network LABS : un switch de niveau 2 n’a pas de table de routage ; ip default-gateway donne sa '
                             'passerelle (un Catalyst 9200L route, avec ip routing).')
        self.port, self.range = None, None
        values = words[3:] if low.startswith('no') else words[2:]
        if len(values) < (2 if low.startswith('no') else 3):
            raise ValueError('Incomplete command.')
        network = ipaddress.IPv4Network(_network(values[0], values[1]))
        if low.startswith('no'):
            return store_route(self.node, network, ipaddress.IPv4Address(values[2]) if len(values) > 2 else None, remove=True)
        if not _is_ipv4(values[2]):
            raise ValueError('Network LABS : sur un switch de niveau 3, ip route NET MASK ADRESSE-DU-SAUT-SUIVANT.')
        store_route(self.node, network, ipaddress.IPv4Address(values[2]))

    def _port_security(self, low):
        """IOS refuses port security on a port that is not a plain access port, and a maximum below the addresses set."""
        from . import ios_store
        from .etherchannel import bundle_of
        from .native_models import port_names
        from .port_guard import MAXIMUM, MAC
        node, port = self.node, self.port
        name = ios_name(port_names(node).get(port, port))
        if port not in node['interfaces'] or bundle_of(node, port) != port \
                or ((node.get('switchports') or {}).get(port) or {}).get('mode', 'access') != 'access':
            raise ValueError(f'Command rejected: {name} is a dynamic port.')
        if low.startswith('no '):
            return
        current = [' '.join(line.lower().split()) for line in ios_store.config(node)['interfaces'].get(port, [])]
        match = re.fullmatch(r'switchport port-security maximum (\d+)', low)
        addresses = [l for l in current if l.startswith('switchport port-security mac-address') and MAC.search(l)]
        if match and not 1 <= int(match[1]) <= MAXIMUM:
            raise ValueError(f'Network LABS : maximum de 1 à {MAXIMUM} adresses par port dans le lab.')
        if match and int(match[1]) < len(addresses):
            raise ValueError(f'Maximum is less than number of currently secured mac-addresses on {name}')
        if MAC.search(low) and not any(MAC.search(low)[0] in l for l in addresses):
            limit = next((int(l.split()[-1]) for l in current if re.fullmatch(r'switchport port-security maximum \d+', l)), 1)
            if len(addresses) >= limit:
                raise ValueError(f'Total secure mac-addresses on interface {name} has reached maximum limit.')

    def _port_channel(self, number):
        """« interface port-channel N »: the switch's Port-channel N (its bond), created empty as on IOS."""
        if not 1 <= number <= 8:
            raise ValueError('Network LABS : Port-channel 1 à 8 sur un switch micro-VM.')
        bond = f'bond{number}'
        self.node.setdefault('port_channels', {}).setdefault(bond, {'members': [], 'mode': 'active', 'min_links': 1})
        from .spanning_tree import sync_ports
        sync_ports(self.node)
        return bond

    def _channel_group(self, negative, number, mode):
        """« channel-group N mode active|passive » on a port: it joins Port-channel N (LACP), its switchport settings
        becoming the bundle's when the bundle has none; « no channel-group » takes it out with the bundle's settings."""
        from .etherchannel import bundle_of
        from .spanning_tree import sync_ports
        node, port = self.node, self.port
        channels = node.setdefault('port_channels', {})
        if port in channels or port not in node['interfaces']:
            raise ValueError('channel-group : sur un port physique (interface fa0/1, interface range fa0/1 - 2).')
        ports = node.setdefault('switchports', {})
        current = bundle_of(node, port)
        if current != port:  # leaving its bundle (to another, or none): it keeps the bundle's settings
            channels[current]['members'].remove(port)
            ports[port] = dict(ports.get(current) or {'mode': 'access', 'vlan': 1})
        if not negative:
            if number is None:
                raise ValueError('Incomplete command.')
            if mode not in ('active', 'passive'):
                raise ValueError('Network LABS : EtherChannel en LACP sur les switchs micro-VM : mode active ou passive '
                                 '(pas de mode on, desirable ou auto).')
            bond = self._port_channel(int(number))
            channel = channels[bond]
            if channel['members'] and channel['mode'] != mode:
                raise ValueError(f'Le groupe {number} est en mode {channel["mode"]} : tous ses ports ont le même mode.')
            if not channel['members'] and port in ports:
                ports[bond] = ports[port]  # the first member's settings become the bundle's, as IOS copies them
            ports.pop(port, None)
            channel['mode'] = mode
            channel['members'].append(port)
        sync_ports(node)

    def _drop_port_channel(self, bond):
        """« no interface port-channel N »: its members leave it, each with the bundle's settings."""
        node = self.node
        channel = (node.get('port_channels') or {}).pop(bond, None)
        if channel is None:
            return
        ports = node.setdefault('switchports', {})
        settings = ports.pop(bond, None) or {'mode': 'access', 'vlan': 1}
        for member in channel['members']:
            ports[member] = dict(settings)
        from .spanning_tree import sync_ports
        sync_ports(node)

    def _stp_priority(self, match):
        """« spanning-tree vlan N priority X » and « … root primary|secondary » (stored as the priority line it writes, as
        IOS does); « spanning-tree vlan N » turns the switch's tree on; « no spanning-tree vlan N » is refused here."""
        from .spanning_tree import ROOT, ios_priority, turn_on
        node, negative, vlans, value, root = self.node, match[1], match[2], match[3], match[4]
        if len(match[0].split()) == (4 if negative else 3):  # « spanning-tree vlan N » alone
            if negative:
                raise ValueError('Network LABS : ce switch garde son spanning tree (une boucle sans lui sature le réseau) ; '
                                 f'« no spanning-tree vlan {vlans} priority » rend la priorité par défaut.')
            turn_on(node)
            return
        if negative:
            ios_priority(node, vlans, None)
            current = ios_store.config(node)
            current['global'] = [line for line in current['global']
                                 if not re.fullmatch(rf'spanning-tree vlan {re.escape(vlans)} priority \d+', line.strip().lower())]
            node['cli_config'] = current
            return
        if root is None and value is None:
            raise ValueError('Incomplete command.')
        priority = ROOT[root] if root else int(value)
        ios_priority(node, vlans, priority)
        ios_store.store(node, 'config', f'spanning-tree vlan {vlans} priority {priority}')

    def _bgp(self, low, words):
        """One 'router bgp' sub-command; False for a global command, which leaves the BGP section."""
        node = self.node
        match = re.fullmatch(r'bgp router-id (\S+)', low)
        if match:
            _bgp_policy(node)['router_id'] = str(ipaddress.IPv4Address(match[1]))
            return True
        match = re.fullmatch(r'(no )?neighbor (\S+) remote-as (\d+)', low) or re.fullmatch(r'(no )?neighbor (\S+)()', low)
        if match:
            _bgp_neighbor(node, match[2], match[3] or None, remove=bool(match[1]))
            return True
        match = re.fullmatch(r'(no )?network (\S+)(?: mask (\S+))?', low)
        if match:
            if '/' in match[2]:
                prefix = match[2]  # EOS: network A.B.C.D/N
            elif match[3]:
                prefix = _network(match[2], match[3])
            else:
                first = int(match[2].split('.')[0])  # IOS without a mask: the classful network
                prefix = f'{match[2]}/{8 if first < 128 else 16 if first < 192 else 24}'
            _bgp_network(node, prefix, remove=bool(match[1]))
            return True
        if low.startswith(('address-family ipv4', 'exit-address-family', 'bgp log-neighbor-changes', 'no bgp default ipv4-unicast',
                           'no synchronization', 'no auto-summary')):
            return True
        if low.startswith(('ip ', 'no ip ', 'hostname ', 'vlan ', 'no vlan ', 'router ')):
            return False
        raise ValueError('router bgp : bgp router-id, neighbor A.B.C.D remote-as N, network A.B.C.D mask M.')

    def _numbered_acl(self, low, words):
        """access-list N …: 1-99 and 1300-1999 standard (a source), 100-199 and 2000-2699 extended; no access-list N."""
        node, name = self.node, words[2] if low.startswith('no ') else words[1]
        number = int(name)
        if not (1 <= number <= 199 or 1300 <= number <= 2699):
            raise ValueError('access-list : 1-99 ou 1300-1999 (standard), 100-199 ou 2000-2699 (étendue).')
        if low.startswith('no '):
            node.get('acls', {}).pop(name, None)
            node['acl_ports'] = {p: n for p, n in (node.get('acl_ports') or {}).items() if n != name}
            return
        if node['role'] != 'router':
            raise ValueError('Listes d’accès : sur un routeur.')
        rest, lowered = words[2:], [w.lower() for w in words[2:]]
        node.setdefault('acls', {}).setdefault(name, [])
        if lowered[:1] == ['remark']:
            return
        if number <= 99 or 1300 <= number <= 1999:
            if not lowered or lowered[0] not in ('permit', 'deny') or len(lowered) not in (2, 3):
                raise ValueError('access-list N permit|deny any | host A.B.C.D | A.B.C.D JOKER')
            if lowered[1] == 'any':
                source = '0.0.0.0/0'
            elif lowered[1] == 'host':
                source = str(ipaddress.IPv4Network(lowered[2] + '/32'))
            else:
                source = _network(lowered[1], _mask_of_wildcard(lowered[2]) if len(lowered) == 3 else '255.255.255.255')
            entry = {'action': lowered[0], 'protocol': 'ip', 'source': source, 'destination': '0.0.0.0/0'}
            if entry not in node['acls'][name]:  # IOS keeps an identical entry once
                node['acls'][name].append(entry)
            return
        previous, self.acl = self.acl, name
        try:
            if not self._acl_entry(' '.join(lowered), rest):
                raise ValueError('access-list N permit|deny PROTO SOURCE DESTINATION [eq PORT]')
        finally:
            self.acl = previous
        entries = node['acls'][name]
        if entries and entries[-1] in entries[:-1]:
            entries.pop()

    def _acl_entry(self, low, words):
        """One line of 'ip access-list extended': [SEQ] permit|deny PROTO SRC DST [eq PORT], no SEQ, remark.
        False for a global command, which leaves the list."""
        entries = self.node['acls'][self.acl]
        if low.startswith('remark'):
            return True
        match = re.fullmatch(r'no (\d+)', low)
        if match:
            index = int(match[1]) // 10 - 1
            if int(match[1]) % 10 or not 0 <= index < len(entries):
                raise ValueError(f'Entrée {match[1]} absente de la liste {self.acl}.')
            entries.pop(index)
            return True
        rest = words[1:] if words[0].isdigit() else words
        if not rest or rest[0].lower() not in ('permit', 'deny'):
            return False
        sequence = int(words[0]) if words[0].isdigit() else None
        entry = {'action': rest[0].lower(), 'protocol': rest[1].lower()}
        tokens = [w.lower() for w in rest[2:]]
        for field in ('source', 'destination'):
            if not tokens:
                raise ValueError('ACL : permit|deny PROTO SOURCE DESTINATION [eq PORT] (any, host A.B.C.D, ou A.B.C.D masque).')
            if tokens[0] == 'any':
                entry[field], tokens = '0.0.0.0/0', tokens[1:]
            elif tokens[0] == 'host':
                entry[field], tokens = str(ipaddress.IPv4Network(tokens[1] + '/32')), tokens[2:]
            else:
                entry[field], tokens = _network(tokens[0], _mask_of_wildcard(tokens[1])), tokens[2:]
        if tokens[:1] == ['eq'] and len(tokens) == 2:
            entry['dport'] = int(tokens[1])
        elif tokens:
            raise ValueError('ACL : seul « eq PORT » est accepté après la destination.')
        if sequence is None:
            entries.append(entry)
        elif sequence % 10 or sequence < 10:
            raise ValueError('ACL : numéros de séquence 10, 20, 30…')
        elif sequence // 10 - 1 < len(entries):
            entries[sequence // 10 - 1] = entry
        elif sequence // 10 - 1 == len(entries):
            entries.append(entry)
        else:
            raise ValueError(f'ACL : la prochaine entrée de {self.acl} est {10 * (len(entries) + 1)}.')
        return True

    def _ospf(self, low, words):
        """One 'router ospf' sub-command; False for a global command, which leaves the OSPF section."""
        node = self.node
        match = re.fullmatch(r'router-id (\S+)', low)
        if match:
            _ospf_policy(node)['router_id'] = str(ipaddress.IPv4Address(match[1]))
            return True
        match = re.fullmatch(r'(no )?network (\S+) (?:(\S+) )?area (\S+)', low)
        if match:
            _ospf_area(match[4])
            if '/' not in match[2] and not match[3]:
                raise ValueError('network <adresse> <masque générique> area 0')
            _ospf_network(node, match[2], match[3], remove=bool(match[1]))
            return True
        match = re.fullmatch(r'(no )?passive-interface (\S+)', low)
        if match:
            self.ospf_ports.setdefault(_port(node, words[-1]), {})['passive'] = not match[1]
            return True
        if low.startswith(('log-adjacency-changes', 'auto-cost ')):
            return True
        if low.startswith(('ip ', 'no ip ', 'hostname ', 'vlan ', 'no vlan ', 'router ')):
            return False
        raise ValueError('router ospf : router-id, network … area 0, passive-interface.')

    def _dhcp(self, low, words):
        """IOS DHCP server: one pool; its range is the pool network minus excluded addresses and the router's own."""
        node = self.node
        if node['role'] == 'switch':
            raise ValueError('Serveur DHCP : sur un routeur, un pare-feu ou un poste.')
        if low.startswith('ip dhcp excluded-address '):
            first = ipaddress.IPv4Address(words[3])
            last = ipaddress.IPv4Address(words[4]) if len(words) > 4 else first
            self.excluded = (self.excluded or []) + [(first, last)]
            return
        if low.startswith('no ip dhcp pool'):
            node['dhcp_server'] = None
            self.pool = None
            return
        if low.startswith('ip dhcp pool '):
            self.pool = {'open': True, 'name': words[3]}  # IOS shows the pool under the name typed
            return
        if self.pool is None or not self.pool.get('open'):
            raise ValueError('ip dhcp pool <nom> d’abord.')
        if low.startswith('network '):
            self.pool['network'] = _network(words[1]) if '/' in words[1] else _network(words[1], words[2])
        elif low.startswith('default-router '):
            self.pool['router'] = str(ipaddress.IPv4Address(words[1]))
        elif low.startswith('dns-server '):
            self.pool['dns'] = [str(ipaddress.IPv4Address(w)) for w in words[1:4]]
        elif low.startswith('lease '):
            days, hours, minutes = (list(map(int, words[1:4])) + [0, 0, 0])[:3]
            self.pool['lease'] = days * 86400 + hours * 3600 + minutes * 60
        else:
            raise ValueError('ip dhcp pool : network, default-router, dns-server, lease.')

    def finish(self):
        _ospf_finish(self.node, self.ospf_ports)
        _bgp_finish(self.node)
        if self.pool is None:
            return
        node, pool = self.node, self.pool
        current = node.get('dhcp_server') or {}
        network = ipaddress.IPv4Network(pool['network']) if 'network' in pool else None
        if network is None and current.get('network'):
            network = ipaddress.IPv4Network(current['network'])  # editing the existing relayed pool
        if network is None and node['interfaces'].get(current.get('interface')):
            network = ipaddress.IPv4Interface(node['interfaces'][current['interface']]).network  # editing the existing pool
        if network is None:
            raise ValueError('ip dhcp pool : « network » d’abord.')
        port = next((p for p, a in node['interfaces'].items() if a and ipaddress.IPv4Interface(a).network == network), None)
        relayed = port is None
        if relayed:  # a remote LAN (ip helper-address on its router): served on the port the relayed requests arrive by
            from .ios_relay import toward
            port = toward(node, network) or next((p for p, a in node['interfaces'].items() if a), None)
            if port is None:
                raise ValueError('ip dhcp pool : donnez d’abord une adresse à un port du routeur.')
        router = pool.get('router', current.get('router'))
        # Never offered: the router's own address, or for a relayed pool its LAN's default router (IOS pings it first).
        own = (ipaddress.IPv4Address(router) if router else None) if relayed else ipaddress.IPv4Interface(node['interfaces'][port]).ip
        excluded = self.excluded if self.excluded is not None else []
        free = (h for h in network.hosts() if h != own and not any(a <= h <= b for a, b in excluded))  # lazy: a /8 is 16M hosts
        start = end = next(free, None)
        if start is None:
            raise ValueError('ip dhcp pool : aucune adresse libre hors des exclusions.')
        for host in itertools.islice(free, 255):
            if int(host) != int(end) + 1:
                break
            end = host
        if self.excluded is None and current.get('interface') == port and current.get('network') == (str(network) if relayed else None):
            # A block that edits the pool without restating exclusions keeps the existing range.
            start, end = current['start'], current['end']
        server = {'interface': port, 'start': str(start), 'end': str(end), 'router': pool.get('router', current.get('router', '')),
                  'dns': pool.get('dns', current.get('dns', [])), 'lease_seconds': pool.get('lease', current.get('lease_seconds', 86400)),
                  **({'network': str(network)} if relayed else {})}
        name = pool.get('name') or current.get('name')
        if name and name != 'LAN':  # the default name stays implicit
            server['name'] = name
        if node['runtime'] == 'firecracker':
            server['lease_seconds'] = min(server['lease_seconds'], 604800)
        node['dhcp_server'] = server

    def _vlan(self, vid, remove):
        if self.node['role'] != 'switch':
            raise ValueError('vlan : uniquement sur un switch.')
        vlans = set(self.node.get('vlans') or [1])
        self.node['vlans'] = sorted(vlans - {vid} if remove else vlans | {vid})

    def _switchport(self, low):
        if self.node['role'] != 'switch':
            raise ValueError('switchport : uniquement sur un switch.')
        ports = self.node.setdefault('switchports', {})
        from .etherchannel import bundle_of
        port = bundle_of(self.node, self.port)  # on an EtherChannel member, IOS configures the whole bundle
        current = ports.get(port, {'mode': 'access', 'vlan': 1})
        match = re.fullmatch(r'switchport (mode (access|trunk)|access vlan (\d+)|trunk native vlan (\d+)|'
                             r'trunk allowed vlan (all|[\d,\-]+))', low)
        if not match:
            raise ValueError('switchport : mode access|trunk, access vlan N, trunk native vlan N, trunk allowed vlan L.')
        if match[2] == 'access':
            current = {'mode': 'access', 'vlan': current.get('vlan', 1)}
        elif match[2] == 'trunk':
            current = {'mode': 'trunk', 'native_vlan': current.get('native_vlan', 1), 'allowed': current.get('allowed', 'all')}
        elif match[3]:
            current = {'mode': 'access', 'vlan': int(match[3])}
        elif current['mode'] != 'trunk':
            raise ValueError('Passer le port en « switchport mode trunk » d’abord.')
        elif match[4]:
            current['native_vlan'] = int(match[4])
        else:
            current['allowed'] = 'all' if match[5] == 'all' else _vlan_list(match[5])
        ports[port] = current
        self._vlan(current.get('vlan') or current.get('native_vlan'), False)


def _port_range(node, text):
    """The ports of « interface range fa0/1 - 4 , fa0/6 »: those the node has (a micro-VM holds up to four)."""
    found = []
    for part in text.split(','):
        match = re.fullmatch(r'\s*(\S*?)(\d+)\s*(?:-\s*(\d+))?\s*', part)
        if not match:
            raise ValueError('interface range PORT - N [, PORT]')
        stem, first, last = match[1], int(match[2]), int(match[3] or match[2])
        for number in range(first, last + 1):
            try:
                port = _port(node, f'{stem}{number}')
            except ValueError:
                continue
            if port not in found:
                found.append(port)
    if not found:
        raise ValueError('interface range : aucun de ces ports sur cet équipement (' + ', '.join(port_names(node).values()) + ').')
    return found


def _vlan_list(text):
    values = []
    for part in text.split(','):
        low, _, high = part.partition('-')
        values += range(int(low), int(high or low) + 1)
    return sorted(set(values))


class VRP(IOS):
    """Huawei VRP commands, translated to the IOS subset they share."""
    comment = '#'

    def line(self, command):
        low, words = command.lower(), command.split()
        if low in ('system-view', 'return', 'save', 'commit'):
            self.port = None
            return
        if low == 'quit':
            # One level up, as on VRP: an OSPF area returns to its process, the BGP address family to BGP, the rest to system.
            if self.ospf and getattr(self, 'in_area', False):
                self.in_area = False
                return None
            if self.bgp and getattr(self, 'in_family', False):
                self.in_family = False
                return None
            self.in_area = self.in_family = False
            return super().line('exit')
        if words[0].lower() == 'sysname':
            return super().line('hostname ' + words[1])
        match = re.fullmatch(r'(undo )?bgp (\d+)', low)
        if match:
            return super().line(('no ' if match[1] else '') + f'router bgp {match[2]}')
        if self.bgp:
            match = re.fullmatch(r'router-id (\S+)', low)
            if match:
                return super().line('bgp router-id ' + match[1])
            match = re.fullmatch(r'(undo )?peer (\S+) as-number (\d+)', low)
            if match:
                return super().line(('no ' if match[1] else '') + f'neighbor {match[2]} remote-as {match[3]}')
            match = re.fullmatch(r'undo peer (\S+)', low)
            if match:
                return super().line(f'no neighbor {match[1]}')
            if low in ('ipv4-family unicast', 'ipv4-family'):
                self.in_family = True
                return None
            match = re.fullmatch(r'(undo )?network (\S+)(?: (\S+))?', low)
            if match:
                mask = match[3]
                prefix = f'{match[2]}/{mask}' if mask and mask.isdigit() else match[2]
                suffix = f' mask {mask}' if mask and not mask.isdigit() else ''
                return super().line(('no ' if match[1] else '') + f'network {prefix}' + suffix)
        match = re.fullmatch(r'(undo )?ospf (\d+)(?: router-id (\S+))?', low)
        if match:
            super().line(('no ' if match[1] else '') + f'router ospf {match[2]}')
            if match[3]:
                super().line('router-id ' + match[3])
            return
        if self.ospf:
            match = re.fullmatch(r'area (\S+)', low)
            if match:
                self.in_area = True
                return _ospf_area(match[1])
            match = re.fullmatch(r'(undo )?network (\S+) (\S+)', low)
            if match:
                return super().line(('no ' if match[1] else '') + f'network {match[2]} {match[3]} area 0')
            match = re.fullmatch(r'(undo )?silent-interface (.+)', low)
            if match:
                return super().line(('no ' if match[1] else '') + 'passive-interface ' + command.split()[-1])
        translations_ospf = [(r'ospf cost (\d+)', 'ip ospf cost {}'), (r'ospf dr-priority (\d+)', 'ip ospf priority {}'),
                             (r'ospf network-type (p2p|broadcast)', 'ip ospf network {}')]
        for pattern, template in translations_ospf:
            match = re.fullmatch(pattern, low)
            if match and self.port is not None:
                value = 'point-to-point' if match[1] == 'p2p' else match[1]
                return super().line(template.format(value))
        if low.startswith('vlan batch '):
            for vid in _vlan_list(','.join(words[2:]).replace(',to,', '-')):
                super().line(f'vlan {vid}')
            return
        translations = [(r'undo vlan (\d+)', 'no vlan {}'), (r'undo ip address', 'no ip address'),
                        (r'ip route-static (.+)', 'ip route {}'), (r'undo ip route-static (.+)', 'no ip route {}'),
                        (r'port link-type (access|trunk)', 'switchport mode {}'), (r'port default vlan (\d+)', 'switchport access vlan {}'),
                        (r'port trunk pvid vlan (\d+)', 'switchport trunk native vlan {}'), (r'undo shutdown', 'no shutdown')]
        for pattern, template in translations:
            match = re.fullmatch(pattern, low)
            if match:
                return super().line(template.format(*match.groups()))
        match = re.fullmatch(r'port trunk allow-pass vlan (.+)', low)
        if match:
            allowed = 'all' if match[1] == 'all' else ','.join(match[1].replace(' to ', '-').split())
            return super().line('switchport trunk allowed vlan ' + allowed)
        if low.startswith(('interface ', 'ip address ', 'description ')) or low == 'shutdown':
            return super().line(command)
        raise ValueError('Sous-ensemble VRP : sysname, interface, ip address, ip route-static, vlan batch, port link-type, '
                         'port default vlan, port trunk, ospf (area 0, network, silent-interface, ospf cost).')


class PANOS:
    """PAN-OS set commands. Zones map to ports: each zone used by a rule must hold exactly one port."""
    comment = '#'

    def __init__(self, node):
        self.node = node
        shown = port_names(node)
        self.zones = {_zone(name): [port] for port, name in shown.items()}
        self.routes, self.rules = {}, {}
        self.existing = {_route_name(network): network for network, _ in routes(node)}

    def line(self, command):
        words = shlex.split(command)
        if command in ('configure', 'commit', 'exit'):
            return
        verb, rest = words[0], words[1:]
        if verb not in ('set', 'delete'):
            raise ValueError('Commandes PAN-OS prises en charge : set, delete, commit.')
        if rest[:3] == ['deviceconfig', 'system', 'hostname']:
            return _check_hostname(self.node, rest[3]) if verb == 'set' else None
        if rest[:3] == ['network', 'interface', 'ethernet']:
            port = _port(self.node, rest[3])
            if rest[4:6] != ['layer3', 'ip']:
                raise ValueError('set network interface ethernet <port> layer3 ip <a.b.c.d/n>')
            return _set_address(self.node, port, '' if verb == 'delete' else _prefix(rest[6]))
        if rest[:1] == ['zone']:
            if verb == 'delete':
                self.zones.pop(rest[1], None)
                return
            if rest[2:4] != ['network', 'layer3']:
                raise ValueError('set zone <nom> network layer3 <port> …')
            self.zones[rest[1]] = [_port(self.node, name) for name in rest[4:]]
            return
        if rest[:6] == ['network', 'virtual-router', 'default', 'routing-table', 'ip', 'static-route']:
            return self._route(verb, rest[6], rest[7:])
        if rest[:3] == ['rulebase', 'security', 'rules']:
            return self._rule(verb, rest[3], rest[4:])
        raise ValueError('Sous-ensemble PAN-OS : deviceconfig system hostname, network interface, zone, '
                         'virtual-router default static-route, rulebase security rules.')

    def _route(self, verb, name, values):
        if verb == 'delete':
            network = self.routes.pop(name, {}).get('destination') or self.existing.get(name)
            if network is None:
                raise ValueError('Route absente : ' + name)
            return _delete_route(self.node, network)
        entry = self.routes.setdefault(name, {})
        pairs = iter(values)
        for key in pairs:
            if key == 'destination':
                entry['destination'] = _network(next(pairs))
            elif key == 'nexthop' and next(pairs) == 'ip-address':
                entry['gateway'] = next(pairs)
            elif key not in ('interface', 'metric'):
                raise ValueError('static-route <nom> destination <réseau/n> nexthop ip-address <a.b.c.d>')
            else:
                next(pairs)
        if {'destination', 'gateway'} <= set(entry):
            _upsert_route(self.node, entry['destination'], entry['gateway'])

    def _rule(self, verb, name, values):
        rules = _policy(self.node)['rules']
        if verb == 'delete':
            kept = [r for r in rules if r['name'] != name]
            if len(kept) == len(rules):
                raise ValueError('Règle absente : ' + name)
            rules[:] = kept
            return
        rule = next((r for r in rules if r['name'] == name), None)
        if rule is None:
            rule = {'name': name, 'action': 'drop'}
            rules.append(rule)
        pairs = iter(values)
        for key in pairs:
            value = next(pairs)
            if key in ('from', 'to'):
                field = 'in' if key == 'from' else 'out'
                rule.pop(field, None)
                if value != 'any':
                    ports = self.zones.get(value)
                    if not ports or len(ports) != 1:
                        raise ValueError(f'Zone {value} : une zone doit contenir exactement un port.')
                    rule[field] = ports[0]
            elif key in ('source', 'destination'):
                rule.pop(key, None)
                if value != 'any':
                    rule[key] = _network(value)
            elif key == 'service':
                rule.pop('dport', None)
                rule['protocol'], port = _panos_protocol(value)
                if port:
                    rule['dport'] = port
            elif key == 'action':
                if value not in ('allow', 'deny', 'drop'):
                    raise ValueError('action : allow, deny ou drop.')
                rule['action'] = 'accept' if value == 'allow' else 'drop'
            elif key == 'application':
                if value != 'any':
                    raise ValueError('application : any uniquement (pas d’identification applicative sur ce nœud Linux).')
            else:
                raise ValueError('Règle : from, to, source, destination, application any, service, action.')

    def finish(self):
        incomplete = [name for name, entry in self.routes.items() if not {'destination', 'gateway'} <= set(entry)]
        if incomplete:
            raise ValueError('Route incomplète (destination et nexthop) : ' + ', '.join(incomplete))


def _panos_protocol(value):
    named = {'any': ('any', None), 'application-default': ('any', None), 'service-http': ('tcp', 80),
             'service-https': ('tcp', 443), 'icmp': ('icmp', None)}
    if value in named:
        return named[value]
    match = re.fullmatch(r'(tcp|udp)-(\d+)', value)
    if match:
        return match[1], int(match[2])
    raise ValueError('service : any, application-default, service-http, service-https, icmp, tcp-<port>, udp-<port>.')


class FortiOS:
    comment = '#'

    def __init__(self, node):
        self.node, self.section, self.entry = node, None, None
        self.order = []  # static routes as rendered: the 'edit N' of 'config router static' is a position
        self.sub = self.sub_entry = None  # 'config ip-range' nested inside a DHCP server entry

    def line(self, command):
        words = shlex.split(command)
        verb = words[0].lower()
        if self.section == 'system dhcp server' and self.entry is not None and (self.sub or words[:2] == ['config', 'ip-range']):
            return self._ip_range(verb, words)
        if verb == 'config':
            self.section = ' '.join(words[1:]).lower()
            if self.section not in ('system global', 'system interface', 'router static', 'firewall policy', 'firewall vip',
                                    'system dhcp server'):
                raise ValueError('Sections prises en charge : system global, system interface, router static, '
                                 'firewall policy, firewall vip, system dhcp server.')
            if self.section == 'router static':
                self.order = routes(self.node)
            return
        if self.section is None:
            raise ValueError('Commencer par « config <section> ».')
        if verb == 'end':
            self.section = None
            return
        if verb == 'edit':
            if self.section == 'system interface':
                _port(self.node, words[1])  # refuse an unknown port on its own line
            elif self.section == 'firewall vip':
                if not re.fullmatch(r'[A-Za-z0-9_.-]{1,40}', words[1]):
                    raise ValueError('Nom de Virtual IP : lettres, chiffres, « _ », « - », « . ».')
            elif not words[1].isdigit():
                raise ValueError('edit <numéro> attendu.')
            self.entry = {'id': words[1], 'fields': {}}
            return
        if verb == 'next':
            self._commit()
            self.entry = None
            return
        if verb == 'delete':
            return self._delete(words[1])
        if verb in ('set', 'unset'):
            if self.section == 'system global':
                if words[1] != 'hostname':
                    raise ValueError('system global : set hostname uniquement.')
                return _check_hostname(self.node, words[2])
            if self.entry is None:
                raise ValueError('« edit » attendu avant « set ».')
            self.entry['fields'][words[1].lower()] = None if verb == 'unset' else words[2:]
            return
        raise ValueError('Commande FortiOS non prise en charge : config, edit, set, unset, next, delete, end.')

    def _commit(self):
        if self.entry is None:
            raise ValueError('« next » sans « edit ».')
        fields = self.entry['fields']
        if self.section == 'system interface':
            port = _port(self.node, self.entry['id'])
            for key, value in fields.items():
                if key == 'ip':
                    _set_address(self.node, port, '' if value is None else _prefix(*value[:2]) if len(value) > 1 else _prefix(value[0]))
                elif key not in ('alias', 'description', 'allowaccess', 'role', 'mode'):
                    raise ValueError('system interface : set ip (et alias, description, allowaccess, role, mode ignorés).')
        elif self.section == 'router static':
            self._route(fields)
        elif self.section == 'firewall vip':
            self._vip(fields)
        elif self.section == 'system dhcp server':
            self._dhcp(fields)
        else:
            self._rule(fields)

    def _ip_range(self, verb, words):
        if verb == 'config':
            self.sub = 'ip-range'
        elif verb == 'edit':
            self.sub_entry = {}
        elif verb == 'set' and self.sub_entry is not None and words[1] in ('start-ip', 'end-ip'):
            self.sub_entry[words[1]] = words[2]
        elif verb == 'next' and self.sub_entry is not None:
            if self.entry.get('range'):
                raise ValueError('Un seul ip-range par serveur DHCP dans ce laboratoire.')
            self.entry['range'] = self.sub_entry
            self.sub_entry = None
        elif verb == 'end':
            self.sub = None
        else:
            raise ValueError('ip-range : edit, set start-ip, set end-ip, next, end.')

    def _dhcp(self, fields):
        """The node's DHCP server: one pool on one port (what the lab's guests and containers serve)."""
        if self.entry['id'] != '1':
            raise ValueError('Un seul serveur DHCP par équipement : edit 1.')
        allowed = {'interface', 'default-gateway', 'netmask', 'lease-time', 'dns-service', 'dns-server1', 'dns-server2',
                   'dns-server3', 'status'}
        if set(fields) - allowed:
            raise ValueError('system dhcp server : interface, default-gateway, netmask, dns-server1..3, lease-time, config ip-range.')
        current = dict(self.node.get('dhcp_server') or {})
        text = lambda key: (fields.get(key) or [''])[0]
        if 'interface' in fields:
            current['interface'] = _port(self.node, text('interface'))
        if 'default-gateway' in fields:
            current['router'] = text('default-gateway')
        if 'lease-time' in fields:
            current['lease_seconds'] = int(text('lease-time'))
        dns = [text(f'dns-server{i}') for i in (1, 2, 3) if text(f'dns-server{i}')]
        if dns or any(f'dns-server{i}' in fields for i in (1, 2, 3)):
            current['dns'] = dns
        if self.entry.get('range'):
            current['start'], current['end'] = self.entry['range'].get('start-ip'), self.entry['range'].get('end-ip')
        if not {'interface', 'start', 'end'} <= set(current):
            raise ValueError('Serveur DHCP : interface et ip-range (start-ip, end-ip) obligatoires.')
        current.setdefault('lease_seconds', 86400 if self.node['runtime'] == 'oci' else 600)
        if text('status') == 'disable':
            self.node['dhcp_server'] = None
            return
        self.node['dhcp_server'] = current

    def _vip(self, fields):
        """A Virtual IP is a destination NAT: traffic to extip on extintf goes to mappedip (optionally port-forwarded)."""
        unknown = set(fields) - {'extip', 'mappedip', 'extintf', 'portforward', 'protocol', 'extport', 'mappedport', 'comment', 'type'}
        if unknown:
            raise ValueError('firewall vip : extip, mappedip, extintf, portforward, protocol, extport, mappedport.')
        nat = _policy(self.node)['nat']
        name = self.entry['id']
        entry = next((r for r in nat if r['name'] == name), None)
        if entry is None:
            entry = {'name': name, 'type': 'dnat'}
            nat.append(entry)
        elif entry['type'] != 'dnat':
            raise ValueError(f'{name} est une traduction source, pas une Virtual IP.')
        text = lambda key: (fields.get(key) or [''])[0]
        if 'extip' in fields:
            entry['destination'] = _network(text('extip').split('-')[0] + '/32')
        if 'mappedip' in fields:
            entry['to'] = str(ipaddress.IPv4Address(text('mappedip').split('-')[0]))
        if 'extintf' in fields:
            entry.pop('in', None)
            if text('extintf').lower() != 'any':
                entry['in'] = _port(self.node, text('extintf'))
        if fields.get('portforward') and text('portforward') == 'enable' or 'extport' in fields:
            entry['protocol'] = text('protocol') or entry.get('protocol', 'tcp')
            if entry['protocol'] not in ('tcp', 'udp'):
                raise ValueError('Port forwarding : protocol tcp ou udp.')
            entry['dport'] = int(text('extport'))
            if text('mappedport'):
                entry['to_port'] = int(text('mappedport'))
        elif fields.get('portforward') and text('portforward') == 'disable':
            for key in ('dport', 'to_port'):
                entry.pop(key, None)
            if entry.get('protocol') in ('tcp', 'udp'):
                entry['protocol'] = 'any'
        if not {'in', 'destination', 'to'} <= set(entry):
            raise ValueError('Virtual IP : extip, mappedip et extintf sont obligatoires.')

    def _route(self, fields):
        unknown = set(fields) - {'dst', 'gateway', 'device', 'comment', 'status'}
        if unknown or not fields.get('gateway'):
            raise ValueError('router static : set dst, set gateway (obligatoire), set device.')
        dst = fields.get('dst')
        network = _network(*dst[:2]) if dst and len(dst) > 1 else _network(dst[0]) if dst else '0.0.0.0/0'
        index = int(self.entry['id']) - 1
        if 0 <= index < len(self.order) and self.order[index][0] != network:
            _delete_route(self.node, self.order[index][0])
        _upsert_route(self.node, network, fields['gateway'][0])
        self.order = routes(self.node)

    def _rule(self, fields):
        policy = _policy(self.node)
        rules = policy['rules']
        index = int(self.entry['id']) - 1
        rule = dict(rules[index]) if 0 <= index < len(rules) else {'name': f'policy-{self.entry["id"]}', 'action': 'drop'}
        previous = rule['name']
        for key, value in fields.items():
            text = value[0] if value else None
            if key == 'name':
                rule['name'] = text
            elif key in ('srcintf', 'dstintf'):
                field = 'in' if key == 'srcintf' else 'out'
                rule.pop(field, None)
                if text and text.lower() != 'any':
                    rule[field] = _port(self.node, text)
            elif key in ('srcaddr', 'dstaddr'):
                field = 'source' if key == 'srcaddr' else 'destination'
                rule.pop(field, None)
                if text and text.lower() != 'all':
                    rule[field] = _network(text)
            elif key == 'action':
                if text not in ('accept', 'deny'):
                    raise ValueError('action : accept ou deny.')
                rule['action'] = 'accept' if text == 'accept' else 'drop'
            elif key == 'service':
                rule.pop('dport', None)
                rule['protocol'], port = _fortios_service(text)
                if port:
                    rule['dport'] = port
            elif key == 'nat':
                if text not in ('enable', 'disable', None):
                    raise ValueError('nat : enable ou disable.')
            elif key not in ('schedule', 'logtraffic', 'comments', 'status'):
                raise ValueError('firewall policy : name, srcintf, dstintf, srcaddr, dstaddr, action, service, nat, schedule.')
        if 0 <= index < len(rules):
            rules[index] = rule
        else:
            rules.append(rule)
        # Policy NAT: the policy's outgoing traffic leaves with the outgoing port's address (a masquerade entry).
        nat = policy['nat']
        had = any(r['name'] == previous + '-nat' for r in nat)
        enable = (fields['nat'][0] == 'enable') if fields.get('nat') else had and 'nat' not in fields
        nat[:] = [r for r in nat if r['name'] not in (previous + '-nat', rule['name'] + '-nat')]
        if enable:
            if not rule.get('out'):
                raise ValueError('NAT de politique : choisir une interface de sortie (dstintf).')
            entry = {'name': rule['name'] + '-nat', 'type': 'masquerade', 'out': rule['out']}
            if rule.get('source'):
                entry['source'] = rule['source']
            nat.append(entry)

    def _delete(self, key):
        if self.section == 'firewall policy':
            policy = _policy(self.node)
            rules = policy['rules']
            index = int(key) - 1
            if not 0 <= index < len(rules):
                raise ValueError('Politique absente : ' + key)
            name = rules.pop(index)['name']
            policy['nat'][:] = [r for r in policy['nat'] if r['name'] != name + '-nat']
        elif self.section == 'system dhcp server':
            if key != '1' or not self.node.get('dhcp_server'):
                raise ValueError('Serveur DHCP absent : ' + key)
            self.node['dhcp_server'] = None
        elif self.section == 'firewall vip':
            nat = _policy(self.node)['nat']
            if not any(r['name'] == key and r['type'] == 'dnat' for r in nat):
                raise ValueError('Virtual IP absente : ' + key)
            nat[:] = [r for r in nat if r['name'] != key]
        elif self.section == 'router static':
            index = int(key) - 1
            if not 0 <= index < len(self.order):
                raise ValueError('Route absente : ' + key)
            _delete_route(self.node, self.order[index][0])
            self.order = routes(self.node)
        else:
            raise ValueError('delete : firewall policy, firewall vip ou router static.')

    def finish(self):
        if self.section is not None:
            raise ValueError('Bloc « config » non fermé : « end » manquant.')


def _fortios_service(text):
    name = (text or 'ALL').upper()
    if name in SERVICES:
        return SERVICES[name]
    match = re.fullmatch(r'(TCP|UDP)-(\d+)', name)
    if match:
        return match[1].lower(), int(match[2])
    if name in ('ICMP', 'ANY'):
        return name.lower(), None
    raise ValueError('service : ' + ', '.join(SERVICES) + ', TCP-<port> ou UDP-<port>.')


class Junos:
    comment = '#'

    def __init__(self, node):
        self.node = node
        self.router_id = None  # routing-options router-id: OSPF's and BGP's, set at the end
        # BGP as Junos holds it: groups of peers and export policies. It starts from the router's current BGP, so a
        # block that only adds a neighbour keeps the rest.
        bgp = node.get('bgp')
        self.asn = bgp['asn'] if bgp else None
        self.groups = {'EBGP': {'neighbors': {n['address']: n['remote_as'] for n in bgp['neighbors']}, 'peer_as': None,
                                'exports': ['ANNONCE-BGP']}} if bgp else {}
        self.policies = {'ANNONCE-BGP': list(bgp['networks'])} if bgp else {}
        self.bgp_touched = False

    def line(self, command):
        node, words = self.node, command.split()
        if command in ('configure', 'commit', 'commit and-quit', 'exit', 'top') or words[0] in ('show', 'edit'):
            return
        verb, rest = words[0], words[1:]
        if verb not in ('set', 'delete'):
            raise ValueError('Commandes Junos prises en charge : set, delete, commit.')
        if rest[:2] == ['system', 'host-name']:
            return _check_hostname(node, rest[2]) if verb == 'set' else None
        if rest[:1] == ['interfaces']:
            port = _port(node, rest[1])
            tail = rest[2:]
            if verb == 'delete' and (not tail or tail[:4] == ['unit', '0', 'family', 'inet']):
                return _set_address(node, port, '')
            if tail[:5] != ['unit', '0', 'family', 'inet', 'address'] or len(tail) != 6:
                raise ValueError('set interfaces <port> unit 0 family inet address <a.b.c.d/n>')
            return _set_address(node, port, _prefix(tail[5]))
        if rest[:3] == ['routing-options', 'static', 'route']:
            network = _network(rest[3])
            if verb == 'delete':
                return _delete_route(node, network)
            if rest[4:5] != ['next-hop'] or len(rest) != 6:
                raise ValueError('set routing-options static route <réseau/n> next-hop <a.b.c.d>')
            return _upsert_route(node, network, rest[5])
        if rest[:2] == ['routing-options', 'router-id'] and len(rest) == 3:
            self.router_id = '' if verb == 'delete' else str(ipaddress.IPv4Address(rest[2]))
            return
        if rest[:2] == ['routing-options', 'autonomous-system'] and len(rest) == 3:
            self.asn, self.bgp_touched = (None if verb == 'delete' else int(rest[2])), True
            return
        if rest[:2] == ['protocols', 'bgp']:
            return self._bgp(verb, rest[2:])
        if rest[:2] == ['policy-options', 'policy-statement'] and len(rest) >= 3:
            return self._policy(verb, rest[2:])
        if rest[:2] == ['protocols', 'ospf']:
            return self._ospf(verb, rest[2:])
        if rest[:1] == ['security']:
            raise ValueError('Les politiques de sécurité Junos ne sont pas encore prises en charge : utiliser le formulaire pare-feu.')
        raise ValueError('Sous-ensemble Junos : system host-name, interfaces … family inet address, routing-options static route, '
                         'protocols ospf area 0.0.0.0 interface.')

    def _ospf(self, verb, rest):
        node = self.node
        if not rest and verb == 'delete':
            node['ospf'] = None
            return
        if len(rest) < 4 or rest[0] != 'area' or rest[2] != 'interface':
            raise ValueError('set protocols ospf area 0.0.0.0 interface <port>.0 [passive | metric N | interface-type p2p]')
        _ospf_area(rest[1])
        name, option = rest[3], rest[4:]
        port = _port(node, name[:-2] if name.endswith('.0') else name)
        if verb == 'delete' and not option:
            return _ospf_port(node, port, remove=True)
        _ospf_port(node, port)
        settings = _ospf_policy(node)['interfaces'][port]
        if not option:
            return
        if option == ['passive']:
            settings['passive'] = verb == 'set'
        elif option[0] == 'metric' and len(option) == 2:
            settings['cost'] = int(option[1]) if verb == 'set' else 10
        elif option[0] == 'priority' and len(option) == 2:
            settings['priority'] = int(option[1]) if verb == 'set' else 1
        elif option[0] == 'interface-type' and option[1:] in (['p2p'], ['broadcast']):
            settings['network_type'] = 'point-to-point' if option[1] == 'p2p' and verb == 'set' else 'broadcast'
        else:
            raise ValueError('Option OSPF Junos : passive, metric N, priority N, interface-type p2p.')

    def _bgp(self, verb, rest):
        self.bgp_touched = True
        if not rest:
            if verb == 'delete':
                self.groups, self.asn = {}, None
                return
            raise ValueError('set protocols bgp group NOM …')
        if rest[0] != 'group' or len(rest) < 2:
            raise ValueError('set protocols bgp group NOM type external | peer-as N | neighbor A.B.C.D [peer-as N] | export POLITIQUE')
        name, option = rest[1], rest[2:]
        if verb == 'delete' and not option:
            self.groups.pop(name, None)
            return
        group = self.groups.setdefault(name, {'neighbors': {}, 'peer_as': None, 'exports': []})
        if option == ['type', 'external']:
            return
        if option[:1] == ['type']:
            raise ValueError('BGP Junos : type external uniquement (iBGP pas encore).')
        if option[:1] == ['peer-as'] and len(option) == 2:
            group['peer_as'] = None if verb == 'delete' else int(option[1])
            return
        if option[:1] == ['neighbor'] and len(option) in (2, 4):
            address = str(ipaddress.IPv4Address(option[1]))
            if verb == 'delete':
                group['neighbors'].pop(address, None)
            elif len(option) == 4 and option[2] == 'peer-as':
                group['neighbors'][address] = int(option[3])
            else:
                group['neighbors'][address] = None  # the group's peer-as
            return
        if option[:1] == ['export'] and len(option) == 2:
            group['exports'] = [e for e in group['exports'] if e != option[1]] + ([] if verb == 'delete' else [option[1]])
            return
        raise ValueError('Option BGP Junos : type external, peer-as N, neighbor A.B.C.D [peer-as N], export POLITIQUE.')

    def _policy(self, verb, rest):
        """policy-statement NAME term T from route-filter PREFIX exact | then accept: the prefixes BGP announces."""
        name, option = rest[0], rest[1:]
        self.bgp_touched = True
        if verb == 'delete' and not option:
            self.policies.pop(name, None)
            return
        prefixes = self.policies.setdefault(name, [])
        if len(option) >= 2 and option[0] == 'term':
            option = option[2:]
        if option[:2] == ['from', 'route-filter'] and len(option) == 4 and option[3] == 'exact':
            prefix = _network(option[2])
            self.policies[name] = [p for p in prefixes if p != prefix] + ([] if verb == 'delete' else [prefix])
            return
        if option == ['then', 'accept']:
            return
        raise ValueError('Politique Junos : term T from route-filter A.B.C.D/N exact, puis term T then accept.')

    def finish(self):
        node = self.node
        if self.bgp_touched:
            if not self.groups or not any(g['neighbors'] for g in self.groups.values()):
                node['bgp'] = None
            else:
                if self.asn is None:
                    raise ValueError('BGP Junos : set routing-options autonomous-system N.')
                neighbors = []
                for group in self.groups.values():
                    for address, remote in group['neighbors'].items():
                        if (remote or group['peer_as']) is None:
                            raise ValueError(f'BGP Junos : peer-as manquant pour {address}.')
                        neighbors.append({'address': address, 'remote_as': remote or group['peer_as']})
                exported = {e for g in self.groups.values() for e in g['exports']}
                networks = sorted({p for name, prefixes in self.policies.items() if name in exported for p in prefixes})
                current = node.get('bgp') or {}
                node['bgp'] = {'asn': self.asn, 'router_id': current.get('router_id', ''), 'neighbors': neighbors,
                               'networks': networks}
        if self.router_id is not None:
            for key in ('ospf', 'bgp'):
                if node.get(key) is not None:
                    node[key]['router_id'] = self.router_id
        _bgp_finish(node)
        _ospf_finish(node, {})


class RouterOS:
    comment = '#'

    def __init__(self, node):
        self.node, self.menu = node, None

    def line(self, command):
        words = shlex.split(command.lstrip('/'))
        if command.startswith('/'):
            # '/ip address add ...' and '/ip address' followed by 'add ...' are both RouterOS.
            verbs = [i for i, word in enumerate(words) if word in ('add', 'set', 'remove', 'print', 'export')]
            split = verbs[0] if verbs else len(words)
            self.menu, words = ' '.join(words[:split]), words[split:]
            if not words:
                return
        if self.menu not in ('system identity', 'ip address', 'ip route', 'ip firewall filter'):
            raise ValueError('Menus pris en charge : /system identity, /ip address, /ip route, /ip firewall filter.')
        verb, values = words[0], self._values(words[1:])
        if self.menu == 'system identity':
            if verb != 'set' or 'name' not in values:
                raise ValueError('/system identity set name=<nom>')
            return _check_hostname(self.node, values['name'])
        if verb == 'add':
            return {'ip address': self._address, 'ip route': self._route, 'ip firewall filter': self._filter}[self.menu](values)
        if verb == 'remove':
            return self._remove(values)
        raise ValueError('Commandes : add, remove [find …], set (identity).')

    @staticmethod
    def _values(words):
        values = {}
        for word in words:
            if word.startswith('[find') or word == ']':
                continue
            key, sign, value = word.partition('=')
            if not sign:
                raise ValueError('Paramètre attendu sous la forme clé=valeur : ' + word)
            values[key.strip('[]')] = value.strip('"]')
        return values

    def _address(self, values):
        if set(values) - {'address', 'interface', 'comment', 'network'} or not {'address', 'interface'} <= set(values):
            raise ValueError('/ip address add address=<a.b.c.d/n> interface=<port>')
        _set_address(self.node, _port(self.node, values['interface']), _prefix(values['address']))

    def _route(self, values):
        if set(values) - {'dst-address', 'gateway', 'comment', 'distance'} or 'gateway' not in values:
            raise ValueError('/ip route add dst-address=<réseau/n> gateway=<a.b.c.d>')
        _upsert_route(self.node, _network(values.get('dst-address', '0.0.0.0/0')), values['gateway'])

    def _filter(self, values):
        rules = _policy(self.node)['rules']
        if values.get('chain') != 'forward' or values.get('action') not in ('accept', 'drop'):
            raise ValueError('/ip firewall filter add chain=forward action=accept|drop …')
        rule = {'name': values.get('comment') or f'filter-{len(rules) + 1}', 'action': values['action']}
        fields = {'in-interface': 'in', 'out-interface': 'out', 'src-address': 'source', 'dst-address': 'destination',
                  'protocol': 'protocol', 'dst-port': 'dport'}
        for key, value in values.items():
            if key in ('in-interface', 'out-interface'):
                rule[fields[key]] = _port(self.node, value)
            elif key in ('src-address', 'dst-address'):
                rule[fields[key]] = _network(value)
            elif key == 'protocol':
                rule['protocol'] = value
            elif key == 'dst-port':
                rule['dport'] = int(value)
            elif key not in ('chain', 'action', 'comment'):
                raise ValueError('Paramètre de filtre non pris en charge : ' + key)
        position = next((i for i, r in enumerate(rules) if r['name'] == rule['name']), None)
        if position is None:
            rules.append(rule)
        else:
            rules[position] = rule

    def _remove(self, values):
        if self.menu == 'ip address' and 'interface' in values:
            return _set_address(self.node, _port(self.node, values['interface']), '')
        if self.menu == 'ip route' and 'dst-address' in values:
            return _delete_route(self.node, _network(values['dst-address']))
        if self.menu == 'ip firewall filter' and 'comment' in values:
            rules = _policy(self.node)['rules']
            kept = [r for r in rules if r['name'] != values['comment']]
            if len(kept) == len(rules):
                raise ValueError('Règle absente : ' + values['comment'])
            rules[:] = kept
            return
        raise ValueError('remove [find interface=…] | [find dst-address=…] | [find comment=…]')

    def finish(self):
        pass
