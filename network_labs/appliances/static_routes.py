"""Bounded IOS-style static routes translated to the managed Linux route model."""
import ipaddress


def configure_route(node, command, resolve_interface):
    from .lan import addresses
    remove = command.startswith('no ')
    words = command.split()[3 if remove else 2:]
    if len(words) < 3:
        raise ValueError('Use ip route NETWORK NETMASK [INTERFACE] NEXT_HOP.')
    destination, mask, *hop = words
    # IOS uses a contiguous dotted netmask, not CIDR or wildcard masks.
    mask = str(ipaddress.IPv4Address(mask))
    network = ipaddress.IPv4Network(destination + '/' + mask, strict=True)
    if str(network.netmask) != mask:
        raise ValueError('Static route requires a contiguous subnet mask, not a wildcard.')
    gateway = ipaddress.IPv4Address(hop[-1])
    if gateway.is_unspecified or gateway.is_multicast or gateway.is_loopback or int(gateway) == 0xffffffff:
        raise ValueError('Static route next hop must be a usable on-link unicast peer.')
    if any(value and gateway == ipaddress.IPv4Interface(value).ip for value in addresses(node).values()):
        raise ValueError('Static route next hop cannot be a local address.')
    interface = None
    if len(hop) > 1:
        interface, _ = resolve_interface(node, ' '.join(hop[:-1]))
    candidates = []
    for name, value in addresses(node).items():
        if not value or (node['role'] == 'switch' and name not in node.get('svis', {})):
            continue
        local = ipaddress.IPv4Interface(value)
        if gateway in local.network and gateway != local.ip and (local.network.prefixlen >= 31 or gateway not in (local.network.network_address, local.network.broadcast_address)):
            candidates.append(name)
    if interface is not None:
        if interface not in candidates:
            raise ValueError('Static route interface must have the next-hop peer directly on-link.')
    elif len(candidates) != 1:
        raise ValueError('Static route needs exactly one on-link interface; specify an interface to disambiguate. Recursive next hops are unsupported.')
    else:
        interface = candidates[0]
    gateway = str(gateway)
    if network.prefixlen == 0:
        if len(hop) != 1:
            raise ValueError('Default routes support next-hop-only syntax; an explicit interface is unsupported.')
        if remove:
            if node.get('gateway') == gateway:
                node['gateway'] = ''
        elif node.get('gateway') and node['gateway'] != gateway:
            raise ValueError('Remove the existing default route before changing its next hop.')
        else:
            node['gateway'] = gateway
        return
    route = {'destination': str(network), 'gateway': gateway, 'interface': interface}
    existing = next((r for r in node['routes'] if r['destination'] == route['destination']), None)
    if remove:
        node['routes'] = [r for r in node['routes'] if r != route]
    elif existing is not None and existing != route:
        raise ValueError('One static route per prefix is supported; remove the existing route first. ECMP/distance/tracking are unsupported.')
    elif existing is None:
        node['routes'].append(route)
