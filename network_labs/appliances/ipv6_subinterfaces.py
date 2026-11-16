"""Observe router VLAN encapsulation separately from IPv6 address/route state."""
import json


def observe(node, links):
    records = {row['ifname']: row for row in links}
    result = {}
    for name, policy in node['subinterfaces'].items():
        row = records.get(name, {}); parent = records.get(policy['parent'], {})
        info = row.get('linkinfo', {}); data = info.get('info_data', {})
        parent_index = parent.get('ifindex')
        parent_ok = parent_index is not None and (row.get('link_index') == parent_index or
                    row.get('link') in (policy['parent'], parent_index))
        result[name] = {'source': 'Actual Linux VLAN link; no forwarding claim',
                        'vlan': data.get('id'), 'protocol': data.get('protocol'),
                        'parent': row.get('link'), 'parent_ifindex': row.get('link_index'),
                        'encapsulation_verified': bool(parent_ok and info.get('info_kind') == 'vlan' and
                                                      data.get('protocol') == '802.1Q' and data.get('id') == policy['vlan']),
                        'flags': row.get('flags'), 'operstate': row.get('operstate')}
    return result


def drift(manager, index, node):
    if not node.get('subinterfaces'): return []
    links = json.loads(manager.ns(index, 'ip', '-j', '-d', 'link', 'show', timeout=3).stdout)
    return [node['name'] + '/' + name + ': IPv6 subinterface encapsulation differs or is unavailable'
            for name, value in observe(node, links).items() if not value['encapsulation_verified']]
