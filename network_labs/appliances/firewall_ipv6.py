"""Bounded IPv6 forward filtering in an owned node namespace; no NAT or input ACL."""
import ipaddress
import json

from .firewall import fingerprint, observe
from .spec import identifier, integer, keys

TABLE = 'network_labs_ipv6'
ICMP_TYPES = ('destination-unreachable', 'packet-too-big', 'time-exceeded', 'parameter-problem', 'echo-request', 'echo-reply')


def validate_node(node):
    policy = node.setdefault('firewall_ipv6', None)
    if policy is None: return
    if (node['runtime'] != 'oci' or node['role'] != 'firewall' or not node['ipv6_forwarding'] or
            not 2 <= len(node['interfaces']) <= 16 or set(node['ipv6']) != set(node['interfaces']) or
            node['forwarding'] or any(node['interfaces'].values()) or node.get('gateway') or node['routes'] or
            node.get('firewall') is not None or node.get('startup') or node['shutdown']):
        raise ValueError('IPv6 firewall requires an UP IPv6-only OCI firewall with 2..16 numbered physical ports, IPv6 forwarding and no IPv4 policy/startup.')
    keys(policy, ('default', 'stateful', 'rules'), 'firewall_ipv6')
    if policy.setdefault('default', 'drop') not in ('accept', 'drop'):
        raise ValueError('firewall_ipv6.default: accept or drop required.')
    if type(policy.setdefault('stateful', True)) is not bool:
        raise ValueError('firewall_ipv6.stateful: boolean required.')
    rules = policy.setdefault('rules', [])
    if not isinstance(rules, list) or len(rules) > 256:
        raise ValueError('firewall_ipv6.rules: up to 256 entries required.')
    names = set()
    for rule in rules:
        keys(rule, ('name', 'action', 'in', 'out', 'source', 'destination', 'protocol', 'dport', 'icmp_type'), 'IPv6 firewall rule')
        name = identifier(rule.get('name'))
        if name in names: raise ValueError('Duplicate IPv6 firewall rule: ' + name)
        names.add(name)
        if rule.get('action') not in ('accept', 'drop'): raise ValueError('IPv6 firewall action: accept or drop.')
        for field in ('in', 'out'):
            if field in rule and (not isinstance(rule[field], str) or rule[field] not in node['interfaces']):
                raise ValueError('IPv6 firewall rule requires a declared physical interface.')
        for field in ('source', 'destination'):
            if field in rule:
                if not isinstance(rule[field], str) or '%' in rule[field]: raise ValueError('IPv6 firewall prefixes require unscoped strings.')
                network = ipaddress.IPv6Network(rule[field], strict=False)
                if network.network_address.ipv4_mapped: raise ValueError('IPv4-mapped prefixes are outside this IPv6 firewall profile.')
                rule[field] = str(network)
        protocol = rule.setdefault('protocol', 'any')
        if protocol not in ('any', 'tcp', 'udp', 'icmpv6'): raise ValueError('IPv6 firewall protocol: any, tcp, udp or icmpv6.')
        if 'dport' in rule:
            integer(rule['dport'], 1, 65535, 'IPv6 dport')
            if protocol not in ('tcp', 'udp'): raise ValueError('IPv6 dport requires tcp or udp.')
        if 'icmp_type' in rule and (protocol != 'icmpv6' or rule['icmp_type'] not in ICMP_TYPES):
            raise ValueError('icmp_type requires icmpv6 and a supported echo/error type.')


def validate_lab(spec):
    firewalls = [node for node in spec['nodes'] if node.get('firewall_ipv6') is not None]
    if not firewalls: return
    if len(firewalls) != 1: raise ValueError('Initial IPv6 firewall profile supports one managed firewall.')
    forbidden = ('svis', 'subinterfaces', 'ospfv3', 'slaac', 'router_advertisements', 'dhcpv6_clients', 'dhcpv6_server',
                 'dhcpv6_relay', 'dhcpv6_remote_server', 'dhcpv6_pd_client', 'dhcpv6_pd_server')
    if any(any(node.get(k) for k in forbidden) or any(node['interfaces'].values()) or node['forwarding'] or
           node.get('gateway') or node['routes'] for node in spec['nodes']):
        raise ValueError('Initial IPv6 firewall lab requires static physical IPv6 without IPv4, SVIs/subinterfaces or dynamic services.')


def render(policy, replace=False):
    lines = [f'delete table ip6 {TABLE}'] if replace else []
    lines += [f'table ip6 {TABLE} {{', 'chain forward {',
              f'type filter hook forward priority filter; policy {policy["default"]};',
              'ct state invalid counter drop comment "invalid";']
    if policy['stateful']: lines.append('ct state established,related counter accept comment "state";')
    for rule in policy['rules']:
        parts = []
        for key, expr in (('in', 'iifname'), ('out', 'oifname')):
            if key in rule: parts.append(f'{expr} "{rule[key]}"')
        for key, expr in (('source', 'saddr'), ('destination', 'daddr')):
            if key in rule: parts.append(f'ip6 {expr} {rule[key]}')
        if rule['protocol'] != 'any': parts.append('meta l4proto ' + ('ipv6-icmp' if rule['protocol'] == 'icmpv6' else rule['protocol']))
        if 'dport' in rule: parts.append(f'{rule["protocol"]} dport {rule["dport"]}')
        if 'icmp_type' in rule: parts.append('icmpv6 type ' + rule['icmp_type'])
        parts.append(f'counter {rule["action"]} comment "rule:{rule["name"]}";')
        lines.append(' '.join(parts))
    lines += [f'counter {policy["default"]} comment "default";', '}', '}']
    return '\n'.join(lines) + '\n'


def apply(manager, index, node):
    tables = json.loads(manager.ns(index, 'nft', '-j', 'list', 'tables').stdout)
    exists = any(item.get('table', {}).get('family') == 'ip6' and item['table'].get('name') == TABLE for item in tables['nftables'])
    target = manager.directory / (node['name'] + '-ipv6.nft')
    target.write_text(render(node['firewall_ipv6'], replace=exists), encoding='utf-8'); target.chmod(0o600)
    manager.ns(index, 'nft', '-c', '-f', str(target))
    manager.ns(index, 'nft', '-f', str(target))
    return fingerprint(observe(manager, index))
