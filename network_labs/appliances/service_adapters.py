"""Select one bounded service transaction without touching co-located services."""


def adapters(node, previous):
    from . import ospf, dhcp_relay
    services = {'ospf': ospf, 'dhcp_relay': dhcp_relay}
    active = [key for key in services if node.get(key) is not None or previous.get(key) is not None]
    changed = [key for key in active if node.get(key) != previous.get(key)]
    if len(changed) > 1:
        raise ValueError('Change OSPF and DHCP relay in separate service transactions.')
    selected = [services[key] for key in (changed or active)]
    for adapter in selected:
        adapter.validate_change(node, previous)
    return selected
