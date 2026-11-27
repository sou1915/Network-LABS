"""Palo Alto PAN-OS: the set commands printed from the lab draft (zones, interfaces, security and NAT rules, routes),
and read back into it (vendor_config.render and vendor_config.apply pick them by the node's brand)."""
import re
import shlex

from .native_models import port_names
from .vendor_config import (
    _check_hostname, _delete_route, _network, _policy, _port, _prefix, _set_address, _upsert_route, _zone,
    routes)


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
