"""Conservative access-port RA admission; no SEND, trunk or general EH support."""
import json
from .spec import keys
from .firewall import fingerprint, observe as read_ruleset

TABLE = 'network_labs_ra_guard'


def validate_node(node):
    policy = node.setdefault('ra_guard', None)
    if policy is None: return
    keys(policy, ('trusted',), 'RA Guard')
    if (node['runtime'] != 'oci' or node['role'] != 'switch' or node.get('switch_backend', 'linux') != 'linux' or
            node.get('startup') or node['port_channels'] or node['subinterfaces'] or node['svis'] or node['ipv6'] or node['shutdown'] or
            not 2 <= len(node['interfaces']) <= 64 or
            any(port not in node['interfaces'] or value['mode'] != 'access' for port, value in node['switchports'].items()) or
            len({value['vlan'] for value in node['switchports'].values()}) != 1):
        raise ValueError('RA Guard requires an UP OCI Linux switch with 2..64 physical access ports in one VLAN, without SVI/LAG/startup.')
    trusted = policy.setdefault('trusted', [])
    if (not isinstance(trusted, list) or any(not isinstance(port, str) or port not in node['interfaces'] for port in trusted) or
            len(trusted) != len(set(trusted))):
        raise ValueError('RA Guard trusted ports must be unique declared physical access ports.')
    policy['trusted'] = sorted(trusted)


def validate_lab(spec):
    guards = [n for n in spec['nodes'] if n.get('ra_guard') is not None]
    if not guards: return
    if len(guards) != 1 or not any(n['ipv6'] or n['slaac'] for n in spec['nodes']):
        raise ValueError('Initial RA Guard requires one guarded switch in an IPv6 lab.')
    forbidden = ('svis', 'subinterfaces', 'ospfv3', 'firewall_ipv6', 'dhcpv6_clients', 'dhcpv6_server',
                 'dhcpv6_relay', 'dhcpv6_remote_server', 'dhcpv6_pd_client', 'dhcpv6_pd_server')
    if any(any(n.get(key) for key in forbidden) or any(n['interfaces'].values()) or n['forwarding'] or
           n.get('gateway') or n['routes'] for n in spec['nodes']):
        raise ValueError('Initial RA Guard lab supports static IPv6/SLAAC and RA, without IPv4, dynamic routing, DHCPv6 or other security compositions.')


def render(node, replace=False):
    lines = [f'delete table bridge {TABLE}'] if replace else []
    lines += [f'table bridge {TABLE} {{', 'chain ingress {', 'type filter hook prerouting priority -320; policy accept;']
    trusted = node['ra_guard']['trusted']
    for port in sorted(node['interfaces']):
        base = f'iifname "{port}"'
        lines.append(f'{base} ether type {{ 0x8100, 0x88a8 }} counter drop comment "tag:{port}";')
        if port in trusted:
            lines.append(f'{base} ether type ip6 icmpv6 type nd-router-advert counter accept comment "trusted:{port}";')
        else:
            # Deliberately constrain the access profile, rather than assuming a
            # bounded parser can classify every possible extension/fragment chain.
            lines.append(f'{base} ether type ip6 ip6 nexthdr != {{ tcp, udp, ipv6-icmp }} counter drop comment "opaque:{port}";')
            lines.append(f'{base} ether type ip6 icmpv6 type nd-router-advert counter drop comment "ra:{port}";')
        lines.append(f'{base} ether type ip6 counter accept comment "pass:{port}";')
    lines += ['}', '}']
    return '\n'.join(lines) + '\n'


def apply(manager, index, node):
    tables = json.loads(manager.ns(index, 'nft', '-j', 'list', 'tables').stdout)
    exists = any(item.get('table', {}).get('family') == 'bridge' and item['table'].get('name') == TABLE for item in tables['nftables'])
    target = manager.directory / (node['name'] + '-ra-guard.nft')
    target.write_text(render(node, replace=exists), encoding='utf-8'); target.chmod(0o600)
    manager.ns(index, 'nft', '-c', '-f', str(target))
    manager.ns(index, 'nft', '-f', str(target))
    manager.state.setdefault('ra_guard_fingerprints', {})[node['name']] = fingerprint(read_ruleset(manager, index))


def observe(manager, index, node):
    ruleset = read_ruleset(manager, index)
    baseline = manager.read().get('ra_guard_fingerprints', {}).get(node['name'])
    ports = {port: {'configured_trusted': port in node['ra_guard']['trusted'], 'counters': {}} for port in node['interfaces']}
    for item in ruleset.get('nftables', []):
        rule = item.get('rule', {})
        if rule.get('table') != TABLE or rule.get('family') != 'bridge': continue
        action, _, port = rule.get('comment', '').partition(':')
        if port not in ports: continue
        for expr in rule.get('expr', []):
            if 'counter' in expr: ports[port]['counters'][action] = expr['counter']
    return {'source': 'Actual nftables bridge prerouting; conservative access-port RA admission',
            'policy_verified': baseline is not None and fingerprint(ruleset) == baseline,
            'ports': ports, 'ruleset': ruleset,
            'note': 'Untrusted IPv6 extension headers/fragments/opaque protocols and tagged ingress are outside this access profile and dropped. No router authentication or general IPv6 security claim.'}
