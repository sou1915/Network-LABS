"""Optional single-access-VLAN multicast policy using the actual Linux bridge."""
import json

from .spec import keys

DEFAULT_PORT = {'router': 'auto', 'flood': True, 'fast_leave': False}
ROUTER = {'off': 0, 'auto': 1, 'permanent': 2}


def validate_multicast(node):
    policy = node.setdefault('multicast', None)
    if policy is None:
        return
    keys(policy, ('snooping', 'querier', 'ports'), 'multicast')
    if node['runtime'] != 'oci' or node['role'] != 'switch' or node.get('startup'):
        raise ValueError('Multicast policy requires an OCI switch without untracked startup commands.')
    for flag, default in (('snooping', True), ('querier', False)):
        if type(policy.setdefault(flag, default)) is not bool:
            raise ValueError('Multicast ' + flag + ' must be boolean.')
    if policy['querier'] and not policy['snooping']:
        raise ValueError('Multicast querier requires snooping enabled.')
    ports = node['switchports']
    if not ports or node['port_channels'] or any(p not in node['interfaces'] or v['mode'] != 'access' for p, v in ports.items()) or len({v['vlan'] for v in ports.values()}) != 1:
        raise ValueError('Initial multicast policy requires physical access ports in one common VLAN; no trunks/LACP.')
    settings = policy.setdefault('ports', {})
    keys(settings, ports, 'multicast ports')
    for port in ports:
        item = settings.setdefault(port, {})
        keys(item, DEFAULT_PORT, 'multicast port')
        for flag, default in DEFAULT_PORT.items():
            item.setdefault(flag, default)
        if not isinstance(item['router'], str) or item['router'] not in ROUTER:
            raise ValueError('Multicast router port must be off, auto or permanent.')
        if any(type(item[f]) is not bool for f in ('flood', 'fast_leave')):
            raise ValueError('Multicast flood/fast_leave must be boolean.')


def bridge_options(policy):
    policy = policy or {'snooping': True, 'querier': False}
    return ['mcast_snooping', str(int(policy['snooping'])), 'mcast_querier', str(int(policy['querier'])),
            'mcast_igmp_version', '2', 'mcast_query_use_ifaddr', '0', 'mcast_vlan_snooping', '0']


def configure(manager, index, node, previous, initial):
    policy, old = node.get('multicast'), previous.get('multicast')
    if policy is None and old is None:
        return
    # Reassert declared settings, without flushing learned memberships or
    # restarting the querier on unrelated edits. No timers are accelerated.
    if initial or policy != old:
        manager.ns(index, 'ip', 'link', 'set', 'dev', 'br0', 'type', 'bridge', *bridge_options(policy))
    for port in node['switchports']:
        settings = policy['ports'][port] if policy else DEFAULT_PORT
        before = old['ports'].get(port) if old else None
        if initial or settings != before or node['switchports'][port] != previous['switchports'].get(port):
            manager.ns(index, 'bridge', 'link', 'set', 'dev', port, 'mcast_router', str(ROUTER[settings['router']]),
                       'mcast_flood', 'on' if settings['flood'] else 'off',
                       'fastleave', 'on' if settings['fast_leave'] else 'off')


def drift(node, links):
    policy = node.get('multicast')
    if policy is None:
        return []
    bridge = next((r.get('linkinfo', {}).get('info_data', {}) for r in links if r.get('ifname') == 'br0'), {})
    options = bridge_options(policy)
    errors = []
    for key, value in zip(options[::2], options[1::2]):
        if bridge.get(key) != int(value):
            errors.append(node['name'] + ': multicast ' + key + ' differs or unavailable')
    ports = {r.get('ifname'): r.get('linkinfo', {}).get('info_slave_data', {}) for r in links}
    for port, settings in policy['ports'].items():
        expected = {'mcast_router': ROUTER[settings['router']], 'mcast_flood': settings['flood'], 'fastleave': settings['fast_leave']}
        if any(ports.get(port, {}).get(k) != v for k, v in expected.items()):
            errors.append(node['name'] + '/' + port + ': multicast port settings differ or unavailable')
    return errors


def observe(manager, index, node, links):
    return {'source': 'Linux bridge IGMPv2 snooping and actual multicast database',
            'policy_verified': not drift(node, links),
            'bridge': next((r.get('linkinfo', {}).get('info_data', {}) for r in links if r.get('ifname') == 'br0'), {}),
            'ports': {r['ifname']: r.get('linkinfo', {}).get('info_slave_data', {}) for r in links if r.get('ifname') in node['switchports']},
            'mdb': json.loads(manager.ns(index, 'bridge', '-j', '-s', '-d', 'mdb', 'show', 'dev', 'br0').stdout),
            'note': 'Observed memberships, not delivery proof. Unnumbered querier uses 0.0.0.0; convergence and host compatibility matter. Unknown groups may flood according to port flags. Kernel snooping/flood flags also affect IPv6/MLD; no independent IPv6 policy or SSM/PIM is implemented.'}
