"""Managed IPv4 forwarding policy in an owned Linux network namespace."""
import hashlib
import ipaddress
import json

from .lan import addresses
from .spec import identifier, integer, keys

TABLE = 'network_labs'


def validate_firewall(node):
    policy = node.get('firewall')
    if policy is None:
        return
    if node['runtime'] != 'oci' or node['role'] != 'firewall':
        raise ValueError('Managed firewall requires an OCI firewall node.')
    if node.get('startup'):
        raise ValueError('Managed firewall cannot mix policy with untracked startup commands.')
    keys(policy, ('default', 'stateful', 'rules', 'nat'), 'firewall')
    if policy.setdefault('default', 'drop') not in ('accept', 'drop'):
        raise ValueError('firewall.default: accept or drop required.')
    if type(policy.setdefault('stateful', True)) is not bool:
        raise ValueError('firewall.stateful: boolean required.')
    available = addresses(node)
    for section in ('rules', 'nat'):
        entries = policy.setdefault(section, [])
        if not isinstance(entries, list) or len(entries) > 256:
            raise ValueError(f'firewall.{section}: at most 256 entries required.')
        names = set()
        for entry in entries:
            common = ('name', 'in', 'out', 'source', 'destination', 'protocol', 'dport')
            keys(entry, (*common, 'action') if section == 'rules' else (*common, 'type', 'to', 'to_port'), section)
            name = identifier(entry.get('name'))
            if name in names:
                raise ValueError('Duplicate firewall entry: ' + name)
            names.add(name)
            for field in ('in', 'out'):
                if field in entry and (entry[field] not in available or
                                      (entry[field] in node['subinterfaces'] and node['subinterfaces'][entry[field]]['vlan'] is None)):
                    raise ValueError('Unknown firewall interface: ' + str(entry[field]))
            for field in ('source', 'destination'):
                if field in entry:
                    entry[field] = str(ipaddress.IPv4Network(entry[field], strict=False))
            protocol = entry.setdefault('protocol', 'any')
            if protocol not in ('any', 'tcp', 'udp', 'icmp'):
                raise ValueError('IPv4 firewall protocol: any, tcp, udp or icmp.')
            if 'dport' in entry:
                integer(entry['dport'], 1, 65535, 'dport')
                if protocol not in ('tcp', 'udp'):
                    raise ValueError('dport requires tcp or udp.')
            if section == 'rules':
                if entry.get('action') not in ('accept', 'drop'):
                    raise ValueError('Firewall rule action: accept or drop required.')
                continue
            kind = entry.get('type')
            if kind not in ('masquerade', 'snat', 'dnat'):
                raise ValueError('NAT type: masquerade, snat or dnat required.')
            if kind == 'dnat':
                if not all(f in entry for f in ('in', 'destination', 'to')) or 'out' in entry:
                    raise ValueError('DNAT needs in, destination and to; out is unavailable before routing.')
            else:
                if 'out' not in entry or 'to_port' in entry:
                    raise ValueError('Source NAT needs out and does not translate ports.')
                if kind == 'masquerade' and 'to' in entry:
                    raise ValueError('Masquerade chooses its own source address.')
                if not available[entry['out']] and entry['out'] not in node['dhcp_clients']:
                    raise ValueError('Source NAT needs a numbered outbound interface.')
            if kind in ('dnat', 'snat'):
                entry['to'] = str(ipaddress.IPv4Address(entry.get('to')))
            if kind == 'snat' and (not available[entry['out']] or entry['to'] != str(ipaddress.IPv4Interface(available[entry['out']]).ip)):
                raise ValueError('SNAT currently requires the configured outbound interface address.')
            if 'to_port' in entry:
                integer(entry['to_port'], 1, 65535, 'to_port')
                if protocol not in ('tcp', 'udp') or 'dport' not in entry:
                    raise ValueError('DNAT to_port requires tcp/udp and dport.')


def match(entry):
    parts = []
    for field, expression in (('in', 'iifname'), ('out', 'oifname')):
        if field in entry:
            parts.append(f'{expression} "{entry[field]}"')
    for field, expression in (('source', 'saddr'), ('destination', 'daddr')):
        if field in entry:
            parts.append(f'ip {expression} {entry[field]}')
    if entry['protocol'] != 'any':
        parts.append('meta l4proto ' + entry['protocol'])
    if 'dport' in entry:
        parts.append(f'{entry["protocol"]} dport {entry["dport"]}')
    return ' '.join(parts)


def render(policy, replace=False):
    lines = [f'delete table ip {TABLE}'] if replace else []
    lines += [f'table ip {TABLE} {{', 'chain forward {',
              f'type filter hook forward priority filter; policy {policy["default"]};',
              'ct state invalid counter drop comment "invalid";']
    if policy['stateful']:
        lines.append('ct state established,related counter accept comment "state";')
    for entry in policy['rules']:
        lines.append(f'{match(entry)} counter {entry["action"]} comment "rule:{entry["name"]}";')
    lines += [f'counter {policy["default"]} comment "default";', '}']
    for chain, kind in (('prerouting', 'dstnat'), ('postrouting', 'srcnat')):
        lines += [f'chain {chain} {{', f'type nat hook {chain} priority {kind}; policy accept;']
        for entry in policy['nat']:
            if (entry['type'] == 'dnat') != (chain == 'prerouting'):
                continue
            action = entry['type']
            if action != 'masquerade':
                action += ' to ' + entry['to']
                if 'to_port' in entry:
                    action += ':' + str(entry['to_port'])
            lines.append(f'{match(entry)} counter {action} comment "nat:{entry["name"]}";')
        lines.append('}')
    lines.append('}')
    return '\n'.join(lines) + '\n'


def fingerprint(ruleset):
    """Ignore counters/handles/metadata, retain policy, expression and rule order."""
    def normalize(value, counter=False):
        if isinstance(value, dict):
            return {k: normalize(v, k == 'counter') for k, v in value.items() if k not in ('handle', 'index', 'metainfo')
                    and not (counter and k in ('packets', 'bytes'))}
        if isinstance(value, list):
            return [normalize(v) for v in value if not (isinstance(v, dict) and 'metainfo' in v)]
        return value
    return hashlib.sha256(json.dumps(normalize(ruleset), sort_keys=True).encode()).hexdigest()


def observe(manager, index):
    return json.loads(manager.ns(index, 'nft', '-j', '-n', 'list', 'ruleset').stdout)


def apply(manager, index, node):
    tables = json.loads(manager.ns(index, 'nft', '-j', 'list', 'tables').stdout)
    exists = any(item.get('table', {}).get('family') == 'ip' and item['table'].get('name') == TABLE
                 for item in tables['nftables'])
    target = manager.directory / (node['name'] + '.nft')
    target.write_text(render(node['firewall'], replace=exists), encoding='utf-8')
    target.chmod(0o600)
    manager.ns(index, 'nft', '-c', '-f', str(target))
    manager.ns(index, 'nft', '-f', str(target))
    return fingerprint(observe(manager, index))
