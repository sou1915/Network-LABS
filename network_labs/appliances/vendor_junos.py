"""Juniper Junos: the set commands printed from the lab draft (interfaces, routes, OSPF, BGP, security policies), and
read back into it (vendor_config.render and vendor_config.apply pick them by the node's brand)."""
import ipaddress

from .native_models import port_names
from .vendor_config import (
    _bgp_finish, _check_hostname, _delete_route, _network, _ospf_area, _ospf_enabled, _ospf_finish,
    _ospf_policy, _ospf_port, _port, _prefix, _set_address, _upsert_route, routes)


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
