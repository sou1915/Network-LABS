"""IPv4 ingress source admission on physical access ports, backed by Linux nftables.

Static source bindings share arp_inspection.bindings for manifest compatibility;
ARP inspection need not be enabled. This is not Cisco firmware or Option 82.
"""
import json

from .arp_inspection import LIFETIME_MS, eligible_bindings, fingerprint

TABLE = 'network_labs_ip_source_guard'


def validate_guard(node):
    ports = node.setdefault('ip_source_guard', {})
    if not isinstance(ports, dict):
        raise ValueError('IP Source Guard must map access ports to ip or ip-mac.')
    if not ports:
        return
    if node['runtime'] != 'oci' or node['role'] != 'switch' or node.get('startup'):
        raise ValueError('IP Source Guard requires an OCI switch without untracked startup commands.')
    snoop = node.get('dhcp_snooping') or {}
    for port, mode in ports.items():
        setting = node['switchports'].get(port, {})
        if port not in node['interfaces'] or setting.get('mode') != 'access':
            raise ValueError('IP Source Guard requires a physical access port.')
        if not isinstance(mode, str) or mode not in ('ip', 'ip-mac'):
            raise ValueError('IP Source Guard mode must be ip or ip-mac.')
        if not snoop.get('enabled') or setting['vlan'] not in snoop.get('vlans', []):
            raise ValueError('IP Source Guard requires active DHCP snooping on its access VLAN.')
        if port in snoop.get('trusted', []):
            raise ValueError('IP Source Guard is for untrusted client access ports, not DHCP server ports.')


def effective(node):
    modes = node.get('ip_source_guard')
    if not modes:
        return None
    vlans = {node['switchports'][p]['vlan'] for p in modes}
    # Include all same-VLAN static owners when checking conflicting dynamic IPs.
    bindings = (node.get('arp_inspection') or {}).get('bindings', [])
    return {'ports': {p: node['switchports'][p]['vlan'] for p in modes}, 'modes': dict(modes),
            'trusted': [], 'bindings': [b for b in bindings if b['vlan'] in vlans]}


def render(policy, replace=False):
    lines = [f'delete table bridge {TABLE}'] if replace else []
    if policy is None:
        return '\n'.join(lines) + '\n'
    lines.append(f'table bridge {TABLE} {{')
    for port, mode in sorted(policy['modes'].items()):
        kind = 'ether_addr . ipv4_addr' if mode == 'ip-mac' else 'ipv4_addr'
        lines += [f'set dhcp_{port} {{ type {kind}; flags timeout; timeout {LIFETIME_MS}ms; size 2048; }}']
    lines += ['chain ingress {', 'type filter hook prerouting priority -280; policy accept;']
    for port in sorted(policy['ports']):
        lines.append(f'iifname "{port}" ether type ip jump verify_{port};')
    lines.append('}')
    for port, mode in sorted(policy['modes'].items()):
        lines += [f'chain verify_{port} {{',
                  # Only zero-source initial DHCP, not an exemption for arbitrary
                  # UDP/68 traffic or nonzero spoofed client addresses. Offsets
                  # are relative to UDP header, including its eight bytes.
                  'ip saddr 0.0.0.0 ip daddr 255.255.255.255 ip protocol udp ip frag-off & 0x3fff == 0 '
                  'udp sport 68 udp dport 67 udp length >= 248 @th,64,32 0x01010600 @th,1952,32 0x63825363 '
                  f'counter accept comment "bootstrap:{port}";']
        for binding in policy['bindings']:
            if binding['port'] == port:
                mac = f'ether saddr {binding["mac"]} ' if mode == 'ip-mac' else ''
                lines.append(f'{mac}ip saddr {binding["address"]} counter accept comment "static:{port}";')
        match = 'ether saddr . ip saddr' if mode == 'ip-mac' else 'ip saddr'
        lines += [f'{match} @dhcp_{port} counter accept comment "dynamic:{port}";',
                  f'counter drop comment "deny:{port}";', '}']
    return '\n'.join(lines + ['}']) + '\n'


def authorization_script(policy, bindings, now):
    entries = {p: [] for p in policy['ports']}
    authorized = eligible_bindings(policy, bindings, now)
    for binding, remaining in authorized:
        port = binding['port']
        value = (binding['mac'] + ' . ' if policy['modes'][port] == 'ip-mac' else '') + binding['address']
        entries[port].append(f'{value} timeout {remaining}ms')
    lines = []
    for port, values in sorted(entries.items()):
        lines.append(f'flush set bridge {TABLE} dhcp_{port}')
        if values:
            lines.append(f'add element bridge {TABLE} dhcp_{port} {{ ' + ', '.join(values) + ' }')
    return '\n'.join(lines) + '\n', len(authorized)


def refresh(config, bindings, now, clear=False):
    from .arp_inspection import refresh as refresh_grants
    return refresh_grants(config, bindings, now, clear, policy_key='ip_source_guard', table_name=TABLE,
                          fingerprint_key='guard_fingerprint', authorize=authorization_script)


def read_table(manager, index):
    tables = json.loads(manager.ns(index, 'nft', '-j', 'list', 'tables').stdout)
    if any(e.get('table', {}).get('family') == 'bridge' and e['table'].get('name') == TABLE for e in tables['nftables']):
        return json.loads(manager.ns(index, 'nft', '-j', '-n', 'list', 'table', 'bridge', TABLE).stdout)
    return None


def apply(manager, index, node, previous=None):
    policy, old = effective(node), effective(previous) if previous else None
    if (previous is not None and policy == old) or (policy is None and old is None):
        return
    current = read_table(manager, index)
    if policy is not None or current is not None:
        target = manager.directory / (node['name'] + '.source-guard.nft')
        target.write_text(render(policy, replace=current is not None)); target.chmod(0o600)
        manager.ns(index, 'nft', '-c', '-f', str(target)); manager.ns(index, 'nft', '-f', str(target))
    baselines = manager.state.setdefault('source_guard_fingerprints', {})
    if policy is not None:
        baselines[node['name']] = fingerprint(read_table(manager, index))
    else:
        baselines.pop(node['name'], None)


def observe(manager, index, node):
    raw = read_table(manager, index)
    baseline = manager.read().get('source_guard_fingerprints', {}).get(node['name'])
    result = {'source': 'Linux nftables IPv4 ingress source admission', 'ports': node['ip_source_guard'],
              'policy_verified': raw is not None and baseline is not None and fingerprint(raw) == baseline,
              'ruleset': raw, 'counters': [], 'dynamic_sets': [], 'maximum_dynamic_grant_ms': LIFETIME_MS,
              'note': 'IPv4 only; IP or IP+MAC by access port/VLAN. Initial broadcast DHCP from 0.0.0.0 is permitted. Dynamic grants expire within 2 s without refresh; static rules persist. Not Cisco firmware, Option 82, or IPv6 source guard.'}
    for entry in (raw or {}).get('nftables', []):
        if 'set' in entry:
            result['dynamic_sets'].append(entry['set'])
        rule = entry.get('rule', {})
        for expression in rule.get('expr', []):
            if isinstance(expression, dict) and isinstance(expression.get('counter'), dict):
                result['counters'].append({'rule': rule.get('comment'), **expression['counter']})
    return result
