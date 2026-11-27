"""Fortinet FortiOS: the config blocks printed from the lab draft (interfaces, policies, VIPs, static routes), and
read back into it (vendor_config.render and vendor_config.apply pick them by the node's brand)."""
import ipaddress
import re
import shlex

from .native_models import port_names
from .vendor_config import (
    SERVICES, _check_hostname, _delete_route, _network, _on_port, _policy, _port, _prefix, _set_address,
    _upsert_route, routes)


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
