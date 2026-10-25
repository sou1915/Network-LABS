"""Initial static IPv6 host profile on an isolated Linux L2 VLAN fabric."""
import ipaddress
import json


def validate_node(node):
    values = node.setdefault('ipv6', {})
    if not isinstance(values, dict) or len(values) > 16:
        raise ValueError('ipv6: object of at most 16 physical host interfaces required.')
    if values and (node['runtime'] != 'oci' or node['role'] != 'host' or set(values) - set(node['interfaces'])):
        raise ValueError('Initial IPv6 addresses require physical interfaces of OCI hosts.')
    for port, value in values.items():
        if not isinstance(value, str) or '%' in value or '/' not in value:
            raise ValueError('IPv6 requires explicit unicast /64 CIDR without a zone.')
        address = ipaddress.IPv6Interface(value)
        ip = address.ip
        if address.network.prefixlen != 64 or ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.ipv4_mapped or ip == address.network.network_address:
            raise ValueError('Initial IPv6 profile requires a usable static unicast /64 address.')
        values[port] = str(address)


def validate_lab(spec):
    if not any(n['ipv6'] for n in spec['nodes']):
        return
    seen = set()
    for node in spec['nodes']:
        # Deliberately do not imply IPv6 firewall/security coverage from IPv4 policy.
        forbidden = ('startup', 'gateway', 'routes', 'subinterfaces', 'svis', 'port_channels', 'firewall',
                     'dhcp_server', 'dhcp_clients', 'dhcp_pools', 'dhcp_relay', 'dns_server', 'resolvers',
                     'ospf', 'lldp', 'port_security', 'dhcp_snooping', 'arp_inspection', 'ip_source_guard', 'multicast')
        if (node['runtime'] != 'oci' or node['role'] not in ('host', 'switch') or node['forwarding'] or
                node.get('switch_backend') == 'ovs' or any(node.get(key) for key in forbidden) or
                node.get('spanning_tree', {}).get('mode', 'off') != 'off'):
            raise ValueError('Initial IPv6 lab supports plain OCI hosts and Linux L2 VLAN switches only; no services, security, routing, STP or bundles.')
        for value in node['ipv6'].values():
            address = str(ipaddress.IPv6Interface(value).ip)
            if address in seen:
                raise ValueError('Duplicate declared IPv6 address in lab.')
            seen.add(address)


def configure(manager, index, node):
    for port, address in node['ipv6'].items():
        base = 'net/ipv6/conf/' + port + '/'
        for key, value in {'disable_ipv6': 0, 'accept_ra': 0, 'autoconf': 0, 'forwarding': 0, 'accept_dad': 1}.items():
            manager.ns(index, 'sysctl', '-w', base + key + '=' + str(value))
        manager.ns(index, 'ip', '-6', 'addr', 'add', address, 'dev', port)


def observe(manager, index):
    return json.loads(manager.ns(index, 'ip', '-j', '-6', 'addr', 'show', timeout=3).stdout)


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
        for key, value in {'disable_ipv6': '0', 'accept_ra': '0', 'autoconf': '0', 'forwarding': '0', 'accept_dad': '1'}.items():
            observed = manager.ns(index, 'sysctl', '-n', 'net/ipv6/conf/' + port + '/' + key, timeout=3).stdout.strip()
            if observed != value:
                errors.append(node['name'] + '/' + port + ': IPv6 ' + key + ' differs')
    return errors
