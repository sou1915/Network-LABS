"""Vendor-style configuration for modelled native nodes: IOS, FortiOS, Junos and RouterOS subsets.

render() prints a node's lab configuration in its vendor's syntax; apply() reads commands in that syntax
and writes them into the lab draft, which is then validated like any other edit. Nothing here runs vendor
firmware: the commands drive the same Linux configuration (addresses, static routes, firewall policy,
switch VLAN ports) that the workbench forms edit. Commands outside the subset are refused with their line.
"""
import copy
import ipaddress
import re
import shlex

from .native_models import MODELS, port_names
from .spec import validate

DIALECTS = {'Cisco': 'ios', 'Fortinet': 'fortios', 'Juniper': 'junos', 'MikroTik': 'routeros', 'Arista': 'eos',
            'Huawei': 'vrp', 'Palo Alto': 'panos'}
TITLES = {'ios': 'Cisco IOS', 'fortios': 'FortiOS', 'junos': 'Junos', 'routeros': 'RouterOS', 'eos': 'Arista EOS',
          'vrp': 'Huawei VRP', 'panos': 'PAN-OS'}
HINTS = {'ios': 'Sous-ensemble IOS : hostname, interface, ip address, ip route, vlan, switchport.',
         'fortios': 'Sous-ensemble FortiOS : system interface (ip), router static, firewall policy.',
         'junos': 'Sous-ensemble Junos : set/delete interfaces … family inet address, routing-options static route.',
         'routeros': 'Sous-ensemble RouterOS : /ip address, /ip route, /ip firewall filter (chain=forward).',
         'eos': 'Sous-ensemble EOS : hostname, interface, ip address a.b.c.d/n, ip route, vlan, switchport.',
         'vrp': 'Sous-ensemble VRP : sysname, interface, ip address, ip route-static, vlan batch, port link-type.',
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


def _port(node, name):
    """A vendor port name (any case) or an eth name -> the eth port."""
    shown = port_names(node)
    for port, label in shown.items():
        if name.lower() in (label.lower(), port.lower()):
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


# ---- rendering ----

def render(spec, name):
    node = _node(spec, name)
    return {'ios': _render_ios, 'fortios': _render_fortios, 'junos': _render_junos, 'routeros': _render_routeros,
            'eos': lambda n: _render_ios(n, eos=True), 'vrp': _render_vrp, 'panos': _render_panos}[dialect(node)](node)


def _render_ios(node, eos=False):
    """IOS, or Arista EOS (same structure, prefix-length addresses and routes)."""
    shown = port_names(node)
    system = 'Arista EOS' if eos else 'Cisco IOS'
    lines = [f'! Network LABS · sous-ensemble {system.split()[-1]}', f'! le nœud exécute Linux, pas {system}', '!',
             'hostname ' + node['name'], '!']
    for vid in node.get('vlans', []):
        if vid != 1:
            lines += [f'vlan {vid}', '!']
    for port, address in node['interfaces'].items():
        lines.append('interface ' + shown[port])
        switchport = node.get('switchports', {}).get(port)
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
        lines.append('!')
    for network, gateway in routes(node):
        net = ipaddress.IPv4Network(network)
        lines.append(f'ip route {network} {gateway}' if eos else f'ip route {net.network_address} {net.netmask} {gateway}')
    return '\n'.join(lines + ['end']) + '\n'


def _render_vrp(node):
    shown = port_names(node)
    lines = ['# Network LABS · sous-ensemble VRP', '# le nœud exécute Linux, pas Huawei VRP', f'sysname {node["name"]}', '#']
    vlans = [vid for vid in node.get('vlans', []) if vid != 1]
    if vlans:
        lines += ['vlan batch ' + ' '.join(map(str, vlans)), '#']
    for port, address in node['interfaces'].items():
        lines.append('interface ' + shown[port])
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
        lines.append('#')
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

    def line(self, command):
        node, low = self.node, command.lower()
        if low in ('enable', 'configure terminal', 'conf t', 'write memory', 'wr'):
            return
        if low in ('end', 'exit'):
            self.port = None
            return
        words = command.split()
        if words[0].lower() == 'hostname':
            return _check_hostname(node, words[1])
        if low.startswith('interface '):
            self.port = _port(node, command.split(None, 1)[1])
            return
        if re.fullmatch(r'(no )?vlan \d+', low):
            return self._vlan(int(words[-1]), low.startswith('no '))
        if low.startswith(('ip route ', 'no ip route ')):
            values = words[3:] if low.startswith('no') else words[2:]
            # 'ip route 10.0.0.0 255.0.0.0 GW' (IOS) or 'ip route 10.0.0.0/8 GW' (EOS).
            if '/' in values[0]:
                network, rest = _network(values[0]), values[1:]
            else:
                network, rest = _network(values[0], values[1]), values[2:]
            return _delete_route(node, network) if low.startswith('no') else _upsert_route(node, network, rest[0])
        if self.port is None:
            raise ValueError('Commande non prise en charge ici (sous-ensemble : hostname, interface, ip route, vlan).')
        if low.startswith('ip address '):
            return _set_address(node, self.port, _prefix(words[2]) if '/' in words[2] else _prefix(words[2], words[3]))
        if low == 'no ip address':
            return _set_address(node, self.port, '')
        if low.startswith('switchport'):
            return self._switchport(low)
        if low in ('no shutdown', 'shutdown') and node['runtime'] == 'oci':
            down = [p for p in node.get('shutdown', []) if p != self.port]
            node['shutdown'] = down + [self.port] if low == 'shutdown' else down
            return
        if low.startswith('description '):
            return
        raise ValueError('Commande d’interface non prise en charge (ip address, switchport, description).')

    def _vlan(self, vid, remove):
        if self.node['role'] != 'switch':
            raise ValueError('vlan : uniquement sur un switch.')
        vlans = set(self.node.get('vlans') or [1])
        self.node['vlans'] = sorted(vlans - {vid} if remove else vlans | {vid})

    def _switchport(self, low):
        if self.node['role'] != 'switch':
            raise ValueError('switchport : uniquement sur un switch.')
        ports = self.node.setdefault('switchports', {})
        current = ports.get(self.port, {'mode': 'access', 'vlan': 1})
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
        ports[self.port] = current
        self._vlan(current.get('vlan') or current.get('native_vlan'), False)

    def finish(self):
        pass


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
            return super().line('exit')
        if words[0].lower() == 'sysname':
            return super().line('hostname ' + words[1])
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
                         'port default vlan, port trunk.')


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
        if rest[:1] == ['security']:
            raise ValueError('Les politiques de sécurité Junos ne sont pas encore prises en charge : utiliser le formulaire pare-feu.')
        raise ValueError('Sous-ensemble Junos : system host-name, interfaces … family inet address, routing-options static route.')

    def finish(self):
        pass


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
