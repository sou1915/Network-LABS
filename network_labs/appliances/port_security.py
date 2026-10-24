"""Static source-MAC admission on owned access ports, not vendor firmware."""
import json
import re
import shutil

from .spec import integer, keys

TABLE = 'network_labs_port_security'


def mac_address(value):
    if not isinstance(value, str):
        raise ValueError('Secure MAC must be text.')
    if re.fullmatch(r'[0-9a-fA-F]{4}(\.[0-9a-fA-F]{4}){2}', value):
        value = value.replace('.', '')
        value = ':'.join(value[i:i + 2] for i in range(0, 12, 2))
    if not re.fullmatch(r'[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}', value):
        raise ValueError('Secure MAC: aa:bb:cc:dd:ee:ff or aabb.ccdd.eeff required.')
    value = value.lower()
    if value == '00:00:00:00:00:00' or int(value[:2], 16) & 1:
        raise ValueError('Secure MAC must be nonzero and unicast.')
    return value


def validate_security(node):
    policies = node.setdefault('port_security', {})
    if not isinstance(policies, dict):
        raise ValueError('port_security must be an object.')
    if not policies:
        return
    if node['runtime'] != 'oci' or node['role'] != 'switch' or node.get('startup'):
        raise ValueError('Port security requires an OCI switch without untracked startup commands.')
    used = set()
    for port, policy in policies.items():
        if port not in node['interfaces'] or node['switchports'].get(port, {}).get('mode') != 'access':
            raise ValueError('Port security supports physical access ports only, not trunks or LAG members.')
        keys(policy, ('maximum', 'mac_addresses', 'violation'), 'Port security')
        maximum = integer(policy.setdefault('maximum', 1), 1, 64, 'Secure MAC maximum')
        if policy.setdefault('violation', 'restrict') != 'restrict':
            raise ValueError('Port security currently supports restrict only; no synthetic shutdown/protect mode.')
        addresses = policy.get('mac_addresses')
        if not isinstance(addresses, list) or len(addresses) != maximum:
            raise ValueError('Static-only port security: configure exactly maximum MAC addresses (1..64); dynamic/sticky learning is not supported.')
        addresses = sorted(mac_address(value) for value in addresses)
        if len(set(addresses)) != len(addresses):
            raise ValueError('Duplicate secure MAC on a port.')
        policy['mac_addresses'] = addresses
        vlan = node['switchports'][port]['vlan']
        for address in addresses:
            if (vlan, address) in used:
                raise ValueError('A secure MAC cannot be assigned to two secure ports in the same VLAN.')
            used.add((vlan, address))


def render(policies, replace=False):
    lines = [f'delete table bridge {TABLE}'] if replace else []
    if policies:
        lines += [f'table bridge {TABLE} {{', 'chain ingress {',
                  'type filter hook prerouting priority -300; policy accept;']
        for port, policy in sorted(policies.items()):
            addresses = ', '.join(policy['mac_addresses'])
            lines += [f'iifname "{port}" ether saddr {{ {addresses} }} counter accept comment "allow:{port}";',
                      f'iifname "{port}" counter drop comment "deny:{port}";']
        lines += ['}', '}']
    return '\n'.join(lines) + '\n'


def read_table(manager, index):
    tables = json.loads(manager.ns(index, 'nft', '-j', 'list', 'tables').stdout)
    exists = any(t.get('table', {}).get('family') == 'bridge' and t['table'].get('name') == TABLE
                 for t in tables['nftables'])
    return json.loads(manager.ns(index, 'nft', '-j', '-n', 'list', 'table', 'bridge', TABLE).stdout) if exists else None


def apply(manager, index, node, previous=None):
    policies = node.get('port_security', {})
    if previous is not None and policies == previous.get('port_security', {}):
        return
    if not policies and not (previous or {}).get('port_security'):
        return
    from .runtime import RuntimeFailure
    from .firewall import fingerprint
    if not shutil.which('nft'):
        raise RuntimeFailure('Port security requires host nftables (nft).')
    current = read_table(manager, index)
    if policies or current is not None:
        target = manager.directory / (node['name'] + '.port-security.nft')
        target.write_text(render(policies, replace=current is not None), encoding='utf-8')
        target.chmod(0o600)
        manager.ns(index, 'nft', '-c', '-f', str(target))
        manager.ns(index, 'nft', '-f', str(target))
    baselines = manager.state.setdefault('port_security_fingerprints', {})
    if policies:
        baselines[node['name']] = fingerprint(read_table(manager, index))
    else:
        baselines.pop(node['name'], None)


def observe(manager, index, node):
    from .firewall import fingerprint
    ruleset = read_table(manager, index)
    baseline = manager.read().get('port_security_fingerprints', {}).get(node['name'])
    ports = {p: {'configured': policy, 'accepted_packets': None, 'accepted_bytes': None,
                 'dropped_packets': None, 'dropped_bytes': None} for p, policy in node['port_security'].items()}
    for entry in (ruleset or {}).get('nftables', []):
        rule = entry.get('rule', {})
        action, _, port = rule.get('comment', '').partition(':')
        if port not in ports or action not in ('allow', 'deny'):
            continue
        for expr in rule.get('expr', []):
            counter = expr.get('counter') if isinstance(expr, dict) else None
            if isinstance(counter, dict):
                for metric in ('packets', 'bytes'):
                    value = counter.get(metric)
                    ports[port][('accepted_' if action == 'allow' else 'dropped_') + metric] = value if type(value) is int and value >= 0 else None
    return {'source': 'Linux nftables bridge prerouting; static source-MAC admission only',
            'available': ruleset is not None, 'fingerprint_matches': (fingerprint(ruleset) == baseline) if baseline is not None and ruleset is not None else None,
            'ports': ports, 'ruleset': ruleset}
