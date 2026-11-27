"""Cisco IOS and Arista EOS (one subset) and Huawei VRP: their configuration printed from the lab draft, and their
commands read back into it (vendor_config.render and vendor_config.apply pick them by the node's brand)."""
import ipaddress
import itertools
import re

from . import ios_store
from .native_models import port_names
from .vendor_config import (
    _acl_address, _bgp_finish, _bgp_neighbor, _bgp_network, _bgp_policy, _delete_route, _ios_pools, _is_ipv4,
    _mask_of_wildcard, _network, _ospf_area, _ospf_enabled, _ospf_finish, _ospf_network, _ospf_policy, _port,
    _prefix, _set_address, _upsert_route, _wildcard, ios_name, routes)


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
    lines += [] if eos else _ios_pools(node)
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


def _set_pools(node, every):
    """The first pool in node['dhcp_server'], the others in node['dhcp_extra'] (a router micro-VM's other LANs)."""
    node['dhcp_server'] = every[0] if every else None
    if every[1:]:
        node['dhcp_extra'] = every[1:]
    else:
        node.pop('dhcp_extra', None)


class IOS:
    comment = '!'

    def __init__(self, node):
        self.node, self.port = node, None
        self.pool = None  # 'ip dhcp pool' being configured: {'network', 'router', 'dns', 'lease'}
        self.pools = {}  # every « ip dhcp pool NAME » block of the text, by name
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
        if low.split()[:1] == ['vrrp'] or low.split()[:2] == ['no', 'vrrp']:
            from .vrrp import configure as vrrp  # VRRP: a router port's or subinterface's vrrp groups (acts in the guest)
            return vrrp(node, self.port, ' '.join(command.split()))
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
            self._drop_pool(words[4] if len(words) > 4 else None)
            return
        if low.startswith('ip dhcp pool '):
            self.pool = self.pools.setdefault(words[3], {'name': words[3]})  # IOS shows the pool under the name typed
            self.pool['open'] = True
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

    def _several(self):
        """A router micro-VM serves one pool per LAN or VLAN; other nodes keep one pool, as before."""
        return self.node.get('runtime') == 'firecracker' and self.node.get('role') == 'router'

    def _drop_pool(self, name):
        """« no ip dhcp pool NAME »: that pool goes (on a node with one pool, the pool)."""
        from .dhcp import pools
        self.pool = None
        if name:
            self.pools.pop(name, None)
        if not self._several() or name is None:
            self.node['dhcp_server'] = None
            self.node.pop('dhcp_extra', None)
            return
        _set_pools(self.node, [p for p in pools(self.node) if p.get('name', 'LAN') != name])

    def finish(self):
        _ospf_finish(self.node, self.ospf_ports)
        _bgp_finish(self.node)
        for pool in self.pools.values():
            self._finish_pool(pool)

    def _finish_pool(self, pool):
        from .dhcp import pools
        from .lan import addresses
        node, several, every = self.node, self._several(), pools(self.node)
        named = next((p for p in every if p.get('name', 'LAN') == pool['name']), None)
        if named is not None:
            current = named  # « ip dhcp pool NAME » again: that pool, edited
        elif not several or ('network' not in pool and len(every) == 1):
            current = node.get('dhcp_server') or {}  # one pool: the block edits it (and may rename it)
        else:
            current = {}  # a router micro-VM's new pool, for another LAN or VLAN
        held = {p: a for p, a in addresses(node).items() if a}  # ports and router-on-a-stick subinterfaces
        network = ipaddress.IPv4Network(pool['network']) if 'network' in pool else None
        if network is None and current.get('network'):
            network = ipaddress.IPv4Network(current['network'])  # editing the existing relayed pool
        if network is None and held.get(current.get('interface')):
            network = ipaddress.IPv4Interface(held[current['interface']]).network  # editing the existing pool
        if network is None:
            raise ValueError('ip dhcp pool : « network » d’abord.')
        port = next((p for p, a in held.items() if ipaddress.IPv4Interface(a).network == network), None)
        relayed = port is None
        if relayed:  # a remote LAN (ip helper-address on its router): served on the port the relayed requests arrive by
            from .ios_relay import toward
            port = toward(node, network) or next((p for p, a in node['interfaces'].items() if a), None)
            if port is None:
                raise ValueError('ip dhcp pool : donnez d’abord une adresse à un port du routeur.')
        router = pool.get('router', current.get('router'))
        # Never offered: the router's own address, or for a relayed pool its LAN's default router (IOS pings it first).
        own = (ipaddress.IPv4Address(router) if router else None) if relayed else ipaddress.IPv4Interface(held[port]).ip
        excluded = self.excluded if self.excluded is not None else []
        free = (h for h in network.hosts() if h != own and not any(a <= h <= b for a, b in excluded))  # lazy: a /8 is 16M hosts
        start = end = next(free, None)
        if start is None:
            raise ValueError('ip dhcp pool : aucune adresse libre hors des exclusions.')
        for host in itertools.islice(free, 255):
            if int(host) != int(end) + 1:
                break
            end = host
        if not any(int(network.network_address) <= int(b) and int(a) <= int(network.broadcast_address) for a, b in excluded) \
                and current.get('interface') == port and current.get('network') == (str(network) if relayed else None):
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
        if not several:
            node['dhcp_server'] = server
            return
        target = next((p for p in every if p is current), None)
        clash = next((p for p in every if p is not target and p['interface'] == port), None)
        if clash is not None and (target is not None or clash.get('name', 'LAN') in self.pools):
            raise ValueError(f'ip dhcp pool : {server.get("name", "LAN")} serait servi sur la même interface que le pool '
                             f'{clash.get("name", "LAN")} ; un pool par interface ou sous-interface.')
        target = target if clash is None else clash  # a new name for a LAN that has a pool: it replaces that pool
        place = next((i for i, p in enumerate(every) if p is target), None)
        _set_pools(node, every[:place] + [server] + every[place + 1:] if place is not None else every + [server])


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
