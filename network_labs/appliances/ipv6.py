"""Static IPv6 on physical ports, router dot1Q subinterfaces and Linux switch SVIs."""
import ipaddress
import json
import time


def validate_node(node):
    values = node.setdefault('ipv6', {})
    if not isinstance(values, dict) or len(values) > 16:
        raise ValueError('ipv6: object of at most 16 routed interfaces required.')
    switch = node['role'] == 'switch' and node.get('switch_backend', 'linux') == 'linux'
    svis = node.get('svis', {})
    if switch and not isinstance(svis, dict):
        raise ValueError('IPv6 switch SVIs must be declared as an object.')
    subs = node.get('subinterfaces', {})
    if not isinstance(subs, dict):
        raise ValueError('Subinterfaces must be declared as an object.')
    ports = svis if switch else set(node['interfaces']) | (set(subs) if node['role'] == 'router' else set())
    if values and (node['runtime'] != 'oci' or node['role'] not in ('host', 'router', 'switch') or
                   (node['role'] == 'switch' and not switch) or set(values) - set(ports)):
        raise ValueError('IPv6 addresses require physical OCI host/router ports, router subinterfaces or declared Linux switch SVIs.')
    for port, value in values.items():
        if not isinstance(value, str) or '%' in value or '/' not in value:
            raise ValueError('IPv6 requires explicit unicast /64 CIDR without a zone.')
        address = ipaddress.IPv6Interface(value)
        ip = address.ip
        if address.network.prefixlen != 64 or ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.ipv4_mapped or ip == address.network.network_address:
            raise ValueError('Initial IPv6 profile requires a usable static unicast /64 address.')
        values[port] = str(address)

    forwarding = node.setdefault('ipv6_forwarding', False)
    if type(forwarding) is not bool or (forwarding and ((node['role'] != 'router' and not switch) or not values)):
        raise ValueError('ipv6_forwarding requires a numbered OCI router or Linux switch SVI and a boolean.')
    networks = [ipaddress.IPv6Interface(v).network for v in values.values()]
    if len(set(networks)) != len(networks):
        raise ValueError('IPv6 interfaces on one node require disjoint /64 networks.')
    routes = node.setdefault('ipv6_routes', [])
    if not isinstance(routes, list) or len(routes) > 32 or (routes and not values):
        raise ValueError('ipv6_routes: up to 32 routes on a numbered IPv6 node required.')
    destinations = set()
    for route in routes:
        if not isinstance(route, dict) or set(route) != {'destination', 'gateway', 'interface'}:
            raise ValueError('IPv6 route requires destination, gateway and routed interface.')
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
    from .dhcpv6_relay import validate_lab as validate_dhcpv6_relay_lab
    validate_dhcpv6_relay_lab(spec)
    from .dhcpv6_pd import validate_lab as validate_pd_lab
    validate_pd_lab(spec)
    if not any(n['ipv6'] or n['slaac'] or n['router_advertisements'] or n['dhcpv6_clients'] for n in spec['nodes']):
        return
    if (any(n['forwarding'] or n.get('gateway') or n['routes'] for n in spec['nodes']) and
            any(n['slaac'] or n['router_advertisements'] or n['dhcpv6_clients'] for n in spec['nodes'])):
        raise ValueError('Initial dual-stack routing requires static IPv6; RA/SLAAC/DHCPv6 coexistence is not in this profile.')
    seen = set()
    for node in spec['nodes']:
        # Deliberately do not imply IPv6 firewall/security coverage from IPv4 policy.
        forbidden = ('radius_server', 'tftp_server', 'ntp_server', 'snmp_receiver', 'snmp_agent', 'syslog_server', 'management', 'startup', 'port_channels', 'firewall',
                     'dhcp_server', 'dhcp_clients', 'dhcp_pools', 'dhcp_relay', 'dns_server', 'resolvers',
                     'ospf', 'lldp', 'port_security', 'dhcp_snooping', 'arp_inspection', 'ip_source_guard', 'multicast')
        if (node['runtime'] != 'oci' or node['role'] not in ('host', 'switch', 'router') or
                node.get('switch_backend') == 'ovs' or any(node.get(key) for key in forbidden) or
                node.get('spanning_tree', {}).get('mode', 'off') != 'off'):
            raise ValueError('IPv6 lab supports OCI hosts, static dot1Q routers and Linux VLAN switches; no IPv4 services, security, STP or bundles.')
        if node['subinterfaces']:
            if (node['role'] != 'router' or not node['ipv6'] or node['forwarding'] or node['routes'] or node.get('gateway') or
                    any(node['interfaces'].values()) or any(sub['address'] for sub in node['subinterfaces'].values()) or
                    any(name not in node['ipv6'] or sub['vlan'] is None or sub['parent'] in node['ipv6'] or
                        name in node['shutdown'] or sub['parent'] in node['shutdown']
                        for name, sub in node['subinterfaces'].items()) or
                    any(node.get(key) for key in ('ospfv3', 'slaac', 'router_advertisements', 'dhcpv6_clients', 'dhcpv6_server',
                                                 'dhcpv6_relay', 'dhcpv6_remote_server', 'dhcpv6_pd_client', 'dhcpv6_pd_server'))):
                raise ValueError('IPv6 subinterfaces require UP numbered static dot1Q router ports, UP unnumbered parents and no IPv4 or dynamic services.')
        if node.get('svis') and (not node['ipv6'] or any(svi['address'] for svi in node['svis'].values()) or
                                 any(node.get(key) for key in ('forwarding', 'gateway', 'routes'))):
            raise ValueError('IPv6 switch SVIs require explicit static IPv6 and exclude IPv4 SVI addressing/routing.')
        if node['forwarding'] and (node['role'] != 'router' or not any(node['interfaces'].values())):
            raise ValueError('Dual-stack IPv4 forwarding requires a numbered physical OCI router.')
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
    from .ipv6_subinterfaces import drift as subinterface_drift
    sub_errors = subinterface_drift(manager, index, node)
    expected = {(port, value) for port, value in node['ipv6'].items()}
    actual, errors = set(), sub_errors
    dynamic_connected = set()
    from .dhcpv6_pd import dynamic_address
    for row in records:
        for address in row.get('addr_info', []):
            if address.get('family') != 'inet6' or address.get('scope') != 'global':
                continue
            value = str(ipaddress.IPv6Interface(str(address['local']) + '/' + str(address['prefixlen'])))
            if dynamic_address(node, row['ifname'], value, address):
                dynamic_connected.add((str(ipaddress.IPv6Interface(value).network), row['ifname']))
            else:
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
            from .ospfv3 import dynamic_route
            if dynamic_route(node, route):
                continue
            observed_routes.add((destination, route.get('gateway'), route.get('dev')))
            if route.get('protocol') != 'static':
                errors.append(node['name'] + ': unmanaged IPv6 route protocol')
    expected_connected = {(str(ipaddress.IPv6Interface(v).network), p) for p, v in node['ipv6'].items() if p not in node['shutdown']}
    if observed_routes != desired or connected != expected_connected | dynamic_connected:
        errors.append(node['name'] + ': IPv6 routes differ')
    return errors
