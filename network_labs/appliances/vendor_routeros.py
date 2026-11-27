"""MikroTik RouterOS: the commands printed from the lab draft (addresses, routes, firewall filter), and read back
into it (vendor_config.render and vendor_config.apply pick them by the node's brand)."""
import shlex

from .native_models import port_names
from .vendor_config import (
    _check_hostname, _delete_route, _network, _policy, _port, _prefix, _set_address, _upsert_route, routes)


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
