"""Select one bounded service transaction without touching co-located services."""


def adapters(node, previous):
    if any(node.get(k) or previous.get(k) for k in ('ipv6', 'dhcpv6_clients', 'dhcpv6_server', 'slaac', 'router_advertisements')):
        if node != previous:
            raise ValueError('IPv6/SLAAC/RA live configuration changes require lab recreation.')
    from . import ospf, dhcp_relay
    services = {'ospf': ospf, 'dhcp_relay': dhcp_relay}
    active = [key for key in services if node.get(key) is not None or previous.get(key) is not None]
    if node.get('lldp') != previous.get('lldp'):
        raise ValueError('Live LLDP policy changes require lab recreation.')
    if (node.get('lldp') is not None or previous.get('lldp') is not None) and not active and node != previous:
        raise ValueError('LLDP nodes allow only separate OSPF or DHCP relay service edits; recreate for network changes.')
    changed = [key for key in active if node.get(key) != previous.get(key)]
    if len(changed) > 1:
        raise ValueError('Change OSPF and DHCP relay in separate service transactions.')
    selected = [services[key] for key in (changed or active)]
    for adapter in selected:
        adapter.validate_change(node, previous)
    return selected
