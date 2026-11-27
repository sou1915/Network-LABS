"""Vendor-style configuration for modelled native nodes: IOS, EOS, VRP, FortiOS, Junos, RouterOS and PAN-OS subsets.

render() prints a node's lab configuration in its vendor's syntax; apply() reads commands in that syntax
and writes them into the lab draft, which is then validated like any other edit. Nothing here runs vendor
firmware: the commands drive the same Linux configuration (addresses, static routes, firewall policy,
switch VLAN ports) that the workbench forms edit. Commands outside the subset are refused with their line.

This module holds what the dialects share (the draft's ports, routes, OSPF and BGP policy, names) and the two entry
points; each dialect's printer and reader is in its own module: vendor_ios (IOS, EOS, VRP), vendor_fortios,
vendor_junos, vendor_routeros, vendor_panos.
"""
import copy
import ipaddress
import re

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


def _ios_pools(node):
    """« ip dhcp excluded-address » lines (global on IOS, printed first), then one « ip dhcp pool » block per pool."""
    from .dhcp import pools
    from .lan import addresses
    held, excluded, blocks = addresses(node), [], []
    for server in pools(node):
        if not held.get(server['interface']):
            continue
        relayed = 'network' in server  # a remote LAN's pool: its own network, no router address inside it
        own = None if relayed else ipaddress.IPv4Interface(held[server['interface']]).ip
        network = ipaddress.IPv4Network(server['network']) if relayed else ipaddress.IPv4Interface(held[server['interface']]).network
        start, end = ipaddress.IPv4Address(server['start']), ipaddress.IPv4Address(server['end'])
        first, last = network.network_address + 1, network.broadcast_address - 1
        for low, high in ((first, start - 1), (end + 1, last)):
            if low <= high and not (low == high == own):
                excluded.append(f'ip dhcp excluded-address {low}' + (f' {high}' if high != low else ''))
        lease = int(server.get('lease_seconds', 86400))
        blocks += [f'ip dhcp pool {server.get("name", "LAN")}', f' network {network.network_address} {network.netmask}']
        if server.get('router'):
            blocks.append(f' default-router {server["router"]}')
        if server.get('dns'):
            blocks.append(' dns-server ' + ' '.join(server['dns']))
        blocks += [f' lease {lease // 86400} {lease % 86400 // 3600} {lease % 3600 // 60}', '!']
    return excluded + (['!'] if excluded else []) + blocks


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
    from .vendor_fortios import _render_fortios
    from .vendor_ios import _render_ios, _render_vrp
    from .vendor_junos import _render_junos
    from .vendor_panos import _render_panos
    from .vendor_routeros import _render_routeros
    node = _node(spec, name)
    return {'ios': _render_ios, 'fortios': _render_fortios, 'junos': _render_junos, 'routeros': _render_routeros,
            'eos': lambda n: _render_ios(n, eos=True), 'vrp': _render_vrp, 'panos': _render_panos}[dialect(node)](node)


def _zone(name):
    """The zone the PAN-OS view gives each port: one zone per port ('l3-ethernet1-1')."""
    return 'l3-' + name.replace('/', '-')


# ---- applying ----

def apply(spec, name, text):
    """Apply vendor commands to a copy of the lab draft; returns the validated draft or raises ValueError('Ligne N : ...')."""
    if not isinstance(text, str) or len(text) > 65536:
        raise ValueError('Configuration : texte de 64 Kio au plus.')
    from .vendor_fortios import FortiOS
    from .vendor_ios import IOS, VRP
    from .vendor_junos import Junos
    from .vendor_panos import PANOS
    from .vendor_routeros import RouterOS
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


