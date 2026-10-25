"""Static IPv6 host/router profiles on an isolated Linux LAN fabric."""
import ipaddress
import json
import time


def validate_node(node):
    values = node.setdefault('ipv6', {})
    if not isinstance(values, dict) or len(values) > 16:
        raise ValueError('ipv6: object of at most 16 physical host interfaces required.')
    if values and (node['runtime'] != 'oci' or node['role'] not in ('host', 'router') or set(values) - set(node['interfaces'])):
        raise ValueError('Initial IPv6 addresses require physical interfaces of OCI hosts/routers.')
    for port, value in values.items():
        if not isinstance(value, str) or '%' in value or '/' not in value:
            raise ValueError('IPv6 requires explicit unicast /64 CIDR without a zone.')
        address = ipaddress.IPv6Interface(value)
        ip = address.ip
        if address.network.prefixlen != 64 or ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.ipv4_mapped or ip == address.network.network_address:
            raise ValueError('Initial IPv6 profile requires a usable static unicast /64 address.')
        values[port] = str(address)

    forwarding = node.setdefault('ipv6_forwarding', False)
    if type(forwarding) is not bool or (forwarding and (node['role'] != 'router' or not values)):
        raise ValueError('ipv6_forwarding requires a numbered OCI router and a boolean.')
    networks = [ipaddress.IPv6Interface(v).network for v in values.values()]
    if len(set(networks)) != len(networks):
        raise ValueError('IPv6 interfaces on one node require disjoint /64 networks.')
    routes = node.setdefault('ipv6_routes', [])
    if not isinstance(routes, list) or len(routes) > 32 or (routes and not values):
        raise ValueError('ipv6_routes: up to 32 routes on a numbered IPv6 node required.')
    destinations = set()
    for route in routes:
        if not isinstance(route, dict) or set(route) != {'destination', 'gateway', 'interface'}:
            raise ValueError('IPv6 route requires destination, gateway and physical interface.')
        if not all(isinstance(v, str) for v in route.values()) or any('%' in v for v in route.values()):
            raise ValueError('IPv6 routes require unscoped string values.')
        network = ipaddress.IPv6Network(route['destination'], strict=True)
        gateway = ipaddress.IPv6Address(route['gateway'])
        port = route['interface']
        if port not in values:
            raise ValueError('IPv6 route requires a numbered local interface.')
        local = ipaddress.IPv6Interface(values[port])
        if (gateway not in local.network or gateway == local.ip or gateway == local.network.network_address or
                gateway.is_multicast or gateway.is_link_local or gateway.is_unspecified or gateway.is_loopback or gateway.ipv4_mapped):
            raise ValueError('IPv6 next hop must be a remote on-link unicast address; link-local next hops are not in this profile.')
        if network.prefixlen and (network.network_address.is_unspecified or network.network_address.is_multicast or network.network_address.is_link_local or
                                  network.network_address.is_loopback or network.network_address.ipv4_mapped):
            raise ValueError('IPv6 destination must be a unicast prefix or ::/0.')
        if str(network) in destinations or network in networks:
            raise ValueError('Duplicate IPv6 route or route replacing a connected network.')
        route.update(destination=str(network), gateway=str(gateway))
        destinations.add(str(network))

    from .dhcpv6 import validate_node as validate_dhcpv6
    validate_dhcpv6(node)
    from .slaac import validate_node as validate_slaac
    validate_slaac(node)


def validate_lab(spec):
    from .dhcpv6 import validate_lab as validate_dhcpv6_lab
    validate_dhcpv6_lab(spec)
    if not any(n['ipv6'] or n['slaac'] or n['router_advertisements'] or n['dhcpv6_clients'] for n in spec['nodes']):
        return
    seen = set()
    for node in spec['nodes']:
        # Deliberately do not imply IPv6 firewall/security coverage from IPv4 policy.
        forbidden = ('startup', 'gateway', 'routes', 'subinterfaces', 'svis', 'port_channels', 'firewall',
                     'dhcp_server', 'dhcp_clients', 'dhcp_pools', 'dhcp_relay', 'dns_server', 'resolvers',
                     'ospf', 'lldp', 'port_security', 'dhcp_snooping', 'arp_inspection', 'ip_source_guard', 'multicast')
        if (node['runtime'] != 'oci' or node['role'] not in ('host', 'switch', 'router') or node['forwarding'] or
                node.get('switch_backend') == 'ovs' or any(node.get(key) for key in forbidden) or
                node.get('spanning_tree', {}).get('mode', 'off') != 'off'):
            raise ValueError('Initial IPv6 lab supports plain OCI hosts/physical routers and Linux L2 VLAN switches only; no IPv4 routing, services, security, STP or bundles.')
        for value in node['ipv6'].values():
            address = str(ipaddress.IPv6Interface(value).ip)
            if address in seen:
                raise ValueError('Duplicate declared IPv6 address in lab.')
            seen.add(address)


def configure(manager, index, node):
    manager.ns(index, 'sysctl', '-w', 'net/ipv6/conf/all/forwarding=' + str(int(node['ipv6_forwarding'])))
    for port, address in node['ipv6'].items():
        base = 'net/ipv6/conf/' + port + '/'
        for key, value in {'disable_ipv6': 0, 'accept_ra': 0, 'autoconf': 0, 'forwarding': int(node['ipv6_forwarding']), 'accept_dad': 1}.items():
            manager.ns(index, 'sysctl', '-w', base + key + '=' + str(value))
        manager.ns(index, 'ip', '-6', 'addr', 'add', address, 'dev', port)



def install_routes(manager):
    # Every veth peer must already be configured/up. Waiting during per-node
    # creation can deadlock DAD on a link whose peer has not been raised yet.
    for index, node in enumerate(manager.state['spec']['nodes']):
        if not node.get('ipv6_routes'):
            continue
        wait_addresses(manager, index, node)
        for route in node['ipv6_routes']:
            manager.ns(index, 'ip', '-6', 'route', 'add', route['destination'], 'via', route['gateway'],
                       'dev', route['interface'], 'proto', 'static')


def observe(manager, index):
    return json.loads(manager.ns(index, 'ip', '-j', '-6', 'addr', 'show', timeout=3).stdout)


def wait_addresses(manager, index, node):
    from .runtime import RuntimeFailure
    expected = {(p, str(ipaddress.IPv6Interface(v).ip)) for p, v in node['ipv6'].items()}
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        ready = set()
        for row in observe(manager, index):
            for a in row.get('addr_info', []):
                if (row.get('ifname'), a.get('local')) not in expected:
                    continue
                flags = a.get('flags', [])
                if a.get('dadfailed') or 'dadfailed' in flags:
                    raise RuntimeFailure(node['name'] + ': IPv6 DAD failed before route installation')
                if not a.get('tentative') and 'tentative' not in flags:
                    ready.add((row['ifname'], a['local']))
        if ready == expected:
            return
        time.sleep(.1)
    raise RuntimeFailure(node['name'] + ': IPv6 addresses not ready before route installation')


def drift(manager, index, node):
    if not node['ipv6']:
        return []
    records = observe(manager, index)
    expected = {(port, value) for port, value in node['ipv6'].items()}
    actual, errors = set(), []
    for row in records:
        for address in row.get('addr_info', []):
            if address.get('family') != 'inet6' or address.get('scope') != 'global':
                continue
            value = str(ipaddress.IPv6Interface(str(address['local']) + '/' + str(address['prefixlen'])))
            actual.add((row['ifname'], value))
            if address.get('tentative') or address.get('dadfailed') or any(f in address.get('flags', []) for f in ('tentative', 'dadfailed')):
                errors.append(node['name'] + ': IPv6 DAD incomplete or failed')
    if actual != expected:
        errors.append(node['name'] + ': IPv6 addresses differ')
    for port in node['ipv6']:
        for key, value in {'disable_ipv6': '0', 'accept_ra': '0', 'autoconf': '0', 'forwarding': str(int(node['ipv6_forwarding'])), 'accept_dad': '1'}.items():
            observed = manager.ns(index, 'sysctl', '-n', 'net/ipv6/conf/' + port + '/' + key, timeout=3).stdout.strip()
            if observed != value:
                errors.append(node['name'] + '/' + port + ': IPv6 ' + key + ' differs')
    all_forwarding = manager.ns(index, 'sysctl', '-n', 'net/ipv6/conf/all/forwarding', timeout=3).stdout.strip()
    if all_forwarding != str(int(node['ipv6_forwarding'])):
        errors.append(node['name'] + ': IPv6 global forwarding differs')
    routes = json.loads(manager.ns(index, 'ip', '-j', '-6', 'route', 'show', 'table', 'main', timeout=3).stdout)
    desired = {(r['destination'], r['gateway'], r['interface']) for r in node['ipv6_routes']}
    observed_routes, connected = set(), set()
    for route in routes:
        destination = route.get('dst')
        if destination is None:
            raise ValueError('IPv6 route observation lacks destination')
        destination = '::/0' if destination == 'default' else str(ipaddress.IPv6Network(destination))
        if route.get('protocol') == 'kernel':
            if not ipaddress.IPv6Network(destination).network_address.is_link_local:
                connected.add((destination, route.get('dev')))
        else:
            observed_routes.add((destination, route.get('gateway'), route.get('dev')))
            if route.get('protocol') != 'static':
                errors.append(node['name'] + ': unmanaged IPv6 route protocol')
    expected_connected = {(str(ipaddress.IPv6Interface(v).network), p) for p, v in node['ipv6'].items() if p not in node['shutdown']}
    if observed_routes != desired or connected != expected_connected:
        errors.append(node['name'] + ': IPv6 routes differ')
    return errors
