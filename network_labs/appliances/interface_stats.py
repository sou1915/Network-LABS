"""Shared, lossless decoding of observed standard interface counters."""
FIELDS = tuple(d + '_' + m for d in ('rx', 'tx') for m in ('packets', 'bytes', 'errors', 'dropped'))


def managed_ports(node):
    ports = set(node['interfaces']) | set(node.get('port_channels', {}))
    ports.update(node.get('svis', {}))
    ports.update(p for p, sub in node.get('subinterfaces', {}).items() if sub['vlan'] is not None)
    if node['role'] == 'switch':
        ports.add('br0')
    return ports


def decode(link):
    raw, width = link.get('stats64'), 64
    if not isinstance(raw, dict):
        raw, width = link.get('stats'), 32
    if not isinstance(raw, dict):
        raw, width = {}, None
    values = {}
    for field in FIELDS:
        direction, metric = field.split('_', 1)
        counters = raw.get(direction, {})
        value = counters.get(metric) if isinstance(counters, dict) else None
        values[field] = value if type(value) is int and value >= 0 else None
    return {'ifindex': link.get('ifindex'), 'width_bits': width, 'counters': values}
