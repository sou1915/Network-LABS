"""Single common spanning tree, driven by the Linux IEEE 802.1D engine.

RSTP is accepted only for the explicit OVS backend. Kernel stp_state=1
remains classic STP. Never infer a tree from the topology.
"""
import copy
import json
import os
import re

from .spec import integer, keys

TIMERS = ('hello_time', 'max_age', 'forward_delay')
TICKS = os.sysconf('SC_CLK_TCK')


def validate_tree(node):
    policy = node.setdefault('spanning_tree', {})
    keys(policy, ('mode', 'priority', *TIMERS, 'ports', 'carrier_recovery'), 'spanning_tree')
    mode = policy.setdefault('mode', 'off')
    if mode not in ('off', 'stp', 'rstp') or (mode == 'rstp' and node.get('switch_backend') != 'ovs'):
        raise ValueError('Linux bridge supports off/classic STP; RSTP requires the explicit OVS backend.')
    recovery = policy.setdefault('carrier_recovery', False)
    if type(recovery) is not bool or (recovery and (mode != 'stp' or node.get('switch_backend') == 'ovs' or len(node['port_channels']) != 1 or node.get('shutdown') or
            any(len(c['members']) != 2 for c in node['port_channels'].values()) or
            any(node.get(k) for k in ('svis', 'port_security', 'dhcp_snooping', 'arp_inspection', 'ip_source_guard', 'multicast', 'ra_guard')))):
        raise ValueError('Carrier recovery requires classic Linux STP with LACP and no co-located admission/SVI/multicast profiles.')
    priority = integer(policy.setdefault('priority', 32768), 0, 61440, 'Bridge priority')
    if priority % 4096:
        raise ValueError('Bridge priority must be a multiple of 4096.')
    hello = integer(policy.setdefault('hello_time', 2), 1, 10, 'hello_time')
    age = integer(policy.setdefault('max_age', 20), 6, 40, 'max_age')
    delay = integer(policy.setdefault('forward_delay', 15), 4, 30, 'forward_delay')
    if not 2 * (hello + 1) <= age <= 2 * (delay - 1):
        raise ValueError('STP timers require 2*(hello_time+1) <= max_age <= 2*(forward_delay-1).')
    ports = policy.setdefault('ports', {})
    if not isinstance(ports, dict) or set(ports) - set(node['switchports']):
        raise ValueError('STP ports must be effective bridge ports, not physical bond members.')
    if (mode != 'off' or ports) and (node['role'] != 'switch' or node['runtime'] != 'oci'):
        raise ValueError('Spanning tree requires OCI switch nodes.')
    if mode == 'off' and ports:
        raise ValueError('STP port parameters require enabled STP.')
    if mode in ('stp', 'rstp'):
        for name in node['switchports']:
            port = copy.deepcopy(ports.setdefault(name, {}))
            ports[name] = port
            keys(port, ('cost', 'priority', 'bpdu_guard', 'root_guard'), 'STP port')
            for flag in ('bpdu_guard', 'root_guard'):
                if type(port.setdefault(flag, False)) is not bool:
                    raise ValueError(flag + ': boolean required.')
            integer(port.setdefault('cost', 100), 1, 65535, 'STP port cost')
            value = integer(port.setdefault('priority', 128), 0, 240, 'STP port priority')
            if value % 16:
                raise ValueError('STP port priority must be a multiple of 16.')


def validate_components(spec, edges):
    switches = {n['name']: n for n in spec['nodes'] if n['role'] == 'switch'}
    if sum(bool(n['spanning_tree'].get('carrier_recovery')) for n in switches.values()) not in (0, 2):
        raise ValueError('Initial carrier recovery supports exactly two enabled switches with one paired two-member LACP channel each.')
    adjacency = {n: set() for n in switches}
    switch_edges = [(a, b) for a, b in edges if a in switches and b in switches]
    for a, b in switch_edges:
        adjacency[a].add(b); adjacency[b].add(a)
    visited = set()
    for start in switches:
        if start in visited:
            continue
        component, pending = set(), [start]
        while pending:
            item = pending.pop()
            if item not in component:
                component.add(item); pending.extend(adjacency[item] - component)
        visited.update(component)
        policies = [switches[n]['spanning_tree'] for n in component]
        modes = {p['mode'] for p in policies}
        if len(modes) > 1:
            raise ValueError('Initial common-tree backend requires the same STP mode on every switch in a connected component.')
        count = sum(a in component and b in component for a, b in switch_edges)
        if count >= len(component) and modes not in ({'stp'}, {'rstp'}):
            raise ValueError('Layer-2 switch loop requires STP on every switch in the component.')
        if len({p.get('carrier_recovery', False) for p in policies}) > 1:
            raise ValueError('Carrier recovery must agree across the connected STP component.')
        if modes in ({'stp'}, {'rstp'}) and len({tuple(p[k] for k in TIMERS) for p in policies}) > 1:
            raise ValueError('Initial common-tree backend requires matching STP timers across connected switches.')


def bridge_options(node, previous, initial):
    policy = node['spanning_tree']
    old = previous.get('spanning_tree', {})
    result = ['stp_state', '1' if policy['mode'] == 'stp' else '0',
              'vlan_filtering', '1', 'vlan_default_pvid', '0']
    if policy['mode'] == 'stp':
        if initial or policy['priority'] != old.get('priority') or old.get('mode') != 'stp':
            result += ['priority', str(policy['priority'])]
        for key in TIMERS:
            if initial or policy[key] != old.get(key) or old.get('mode') != 'stp':
                result += [key, str(policy[key] * TICKS)]
    return result


def verify_kernel(manager, index, node):
    if node['spanning_tree']['mode'] == 'stp':
        data = json.loads(manager.ns(index, 'ip', '-j', '-d', 'link', 'show', 'dev', 'br0').stdout)
        if len(data) != 1 or data[0].get('linkinfo', {}).get('info_data', {}).get('stp_state') != 1:
            from .runtime import RuntimeFailure
            raise RuntimeFailure('Classic STP requires actual kernel STP state 1; refusing another controller or disabled STP.')


def configure_ports(manager, index, node, previous, initial, recreated):
    policy = node['spanning_tree']
    for port, settings in policy['ports'].items():
        old = previous.get('spanning_tree', {}).get('ports', {}).get(port)
        if initial or port in recreated or settings != old:
            manager.ns(index, 'bridge', 'link', 'set', 'dev', port, 'cost', str(settings['cost']),
                       'priority', str(settings['priority'] // 4),
                       'guard', 'on' if settings.get('bpdu_guard', False) else 'off',
                       'root_block', 'on' if settings.get('root_guard', False) else 'off')
    if not initial and policy['mode'] == 'stp' and policy != previous.get('spanning_tree'):
        # Explicit path-policy edits invalidate learned MAC destinations on
        # this bridge. Keep static/permanent entries; physical failover alone
        # remains the kernel STP/TCN engine's responsibility.
        manager.ns(index, 'bridge', 'fdb', 'flush', 'dev', 'br0', 'dynamic')


def kernel_ids(manager, index):
    # Some iproute2 JSON versions print the local ID in root_id as well.
    # Read both identifiers directly from this namespace's kernel sysfs.
    result = {}
    for field in ('bridge_id', 'root_id'):
        value = manager.ns(index, 'cat', '/sys/class/net/br0/bridge/' + field, timeout=3).stdout.strip().lower()
        if not re.fullmatch(r'[0-9a-f]{4}\.[0-9a-f]{12}', value):
            raise ValueError('Unexpected kernel STP bridge identifier: ' + value)
        result[field] = value
    return result


def observe(node, links, bridge_ids=None):
    bridge = next((r.get('linkinfo', {}).get('info_data', {}) for r in links if r['ifname'] == 'br0'), {})
    if node['spanning_tree']['mode'] == 'stp' and bridge_ids is None:
        raise ValueError('Kernel bridge IDs are required for STP inspection.')
    ids = bridge_ids or bridge
    root, own = ids.get('root_id'), ids.get('bridge_id')
    ports = {r['ifname']: r.get('linkinfo', {}).get('info_slave_data', {}) for r in links if r['ifname'] in node['switchports']}
    root_port = next((name for name, data in ports.items() if data.get('no') is not None
                      and int(str(data['no']), 0) == bridge.get('root_port')), None)
    active = [r for r in links if r['ifname'] in ports and 'UP' in r.get('flags', []) and 'LOWER_UP' in r.get('flags', [])]
    settled = bool(active) and all(ports[r['ifname']].get('state') in ('forwarding', 'blocking') for r in active)
    return {'source': 'Linux kernel sysfs IDs and netlink state; no computed topology tree',
            'protocol': 'stp' if bridge.get('stp_state') == 1 else 'off' if bridge.get('stp_state') == 0 else 'unmanaged-userspace',
            'bridge_id': own, 'root_id': root, 'is_root': bool(root and own and root == own and bridge.get('stp_state') == 1),
            'root_port': root_port, 'root_port_number': bridge.get('root_port'), 'root_path_cost': bridge.get('root_path_cost'),
            'topology_change': bridge.get('topology_change'), 'local_state_settled': settled,
            'ports': {p: {**{k: data.get(k) for k in ('state', 'cost', 'no', 'designated_cost', 'root_id', 'bridge_id')},
                          'bpdu_guard': data.get('guard'), 'root_guard': data.get('root_block'),
                          'kernel_priority': data.get('priority'),
                          'priority': data['priority'] * 4 if isinstance(data.get('priority'), int) else None}
                      for p, data in ports.items()}}


def drift(node, links):
    policy = node['spanning_tree']
    bridge = next((r.get('linkinfo', {}).get('info_data', {}) for r in links if r['ifname'] == 'br0'), {})
    errors = []
    if bridge.get('stp_state') != (1 if policy['mode'] == 'stp' else 0):
        errors.append(node['name'] + ': spanning-tree controller differs')
    if bridge.get('vlan_filtering') != 1 or bridge.get('vlan_default_pvid') != 0:
        errors.append(node['name'] + ': bridge VLAN filtering defaults differ')
    if policy['mode'] == 'stp':
        if bridge.get('priority') != policy['priority'] or any(bridge.get(k) != policy[k] * TICKS for k in TIMERS):
            errors.append(node['name'] + ': spanning-tree bridge parameters differ')
        ports = {r['ifname']: r.get('linkinfo', {}).get('info_slave_data', {}) for r in links}
        for name, settings in policy['ports'].items():
            expected = {'cost': settings['cost'], 'priority': settings['priority'] // 4,
                        'guard': settings.get('bpdu_guard', False), 'root_block': settings.get('root_guard', False)}
            if any(ports.get(name, {}).get(k) != v for k, v in expected.items()):
                errors.append(node['name'] + '/' + name + ': spanning-tree port parameters differ')
    return errors
