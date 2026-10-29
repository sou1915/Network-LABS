"""Declarative LAN validation and real Linux bridge/802.1Q configuration.

No topology path computation is used for packet delivery. All operations target
an owned node namespace; the kernel makes forwarding and VLAN decisions.
"""
import ipaddress
import copy
import json
import re

from .spec import integer, keys

LAN_FIELDS = ('radius_access', 'radius_server', 'tftp_server', 'ntp_server', 'snmp_receiver', 'snmp_agent', 'syslog_server', 'management', 'dhcpv6_clients', 'dhcpv6_server', 'dhcpv6_relay', 'dhcpv6_remote_server', 'dhcpv6_pd_client', 'dhcpv6_pd_server', 'slaac', 'router_advertisements', 'ipv6', 'ipv6_routes', 'ipv6_forwarding', 'vlans', 'switchports', 'subinterfaces', 'shutdown', 'forwarding',
              'dhcp_server', 'dhcp_clients', 'dialect', 'interface_aliases', 'routes', 'port_channels', 'spanning_tree', 'port_security', 'interface_macs', 'dhcp_snooping', 'arp_inspection', 'ip_source_guard', 'multicast', 'dns_server', 'resolvers', 'lldp', 'switch_backend', 'svis', 'dhcp_relay', 'dhcp_pools', 'ospf', 'ospfv3')


def addresses(node):
    return {**node['interfaces'], **{name: '' for name in node.get('port_channels', {})}, **{name: sub['address'] for name, sub in node.get('subinterfaces', {}).items()},
            **{name: svi['address'] for name, svi in node.get('svis', {}).items()}}


def validate_lan(node):
    from .ipv6 import validate_node
    validate_node(node)
    role = node['role']
    from .port_security import mac_address
    macs = node.setdefault('interface_macs', {})
    if not isinstance(macs, dict) or set(macs) - set(node['interfaces']) or (macs and node['runtime'] != 'oci'):
        raise ValueError('interface_macs: object of physical OCI interfaces required.')
    node['interface_macs'] = {p: mac_address(value) for p, value in macs.items()}
    from .lacp import validate_channels
    members = validate_channels(node)
    if set(node['interface_macs']) & members:
        raise ValueError('Explicit interface MAC addresses are not supported on LACP members; bonding owns their MAC.')
    bridge_ports = (set(node['interfaces']) - members) | set(node['port_channels'])
    vlans = node.setdefault('vlans', [1] if role == 'switch' else [])
    if not isinstance(vlans, list) or len(vlans) > 256:
        raise ValueError('vlans: array of at most 256 VLAN IDs required.')
    for vid in vlans:
        integer(vid, 1, 4094, 'VLAN')
    if len(vlans) != len(set(vlans)):
        raise ValueError('Duplicate VLAN ID.')
    ports = node.setdefault('switchports', {})
    subs = node.setdefault('subinterfaces', {})
    if not isinstance(ports, dict) or not isinstance(subs, dict) or len(subs) > 32:
        raise ValueError('switchports/subinterfaces must be objects; at most 32 subinterfaces.')
    if (vlans or ports) and role != 'switch':
        raise ValueError('VLAN table and switchports belong to switch nodes.')
    if subs and (role not in ('router', 'firewall') or node['runtime'] != 'oci'):
        raise ValueError('802.1Q subinterfaces require an OCI router/firewall.')
    if role == 'switch':
        if set(ports) - bridge_ports:
            raise ValueError('Unknown switchport.')
        for interface in sorted(bridge_ports):
            port = copy.deepcopy(ports.setdefault(interface, {'mode': 'access', 'vlan': 1}))
            ports[interface] = port
            mode = port.get('mode') if isinstance(port, dict) else None
            if mode == 'access':
                keys(port, ('mode', 'vlan'), 'Access port')
                vid = integer(port.setdefault('vlan', 1), 1, 4094, 'Access VLAN')
                if vid not in vlans:
                    raise ValueError('Access VLAN must be declared in vlans.')
            elif mode == 'trunk':
                keys(port, ('mode', 'native_vlan', 'allowed'), 'Trunk port')
                integer(port.setdefault('native_vlan', 1), 1, 4094, 'Native VLAN')
                allowed = port.setdefault('allowed', 'all')
                if allowed != 'all':
                    if not isinstance(allowed, list) or len(allowed) > 4094:
                        raise ValueError('Trunk allowed: all or array of VLAN IDs.')
                    for vid in allowed:
                        integer(vid, 1, 4094, 'Allowed VLAN')
                    if len(set(allowed)) != len(allowed):
                        raise ValueError('Duplicate allowed VLAN.')
            else:
                raise ValueError('Switchport mode: access or trunk.')
    combinations = set()
    for name, sub in subs.items():
        if not isinstance(name, str) or not re.fullmatch(r'eth\d{1,2}\.\d{1,4}', name):
            raise ValueError('Subinterface name: eth0.10, maximum 15 characters.')
        keys(sub, ('parent', 'vlan', 'address'), 'Subinterface')
        if sub.get('parent') not in node['interfaces'] or name.split('.')[0] != sub['parent']:
            raise ValueError('Unknown/mismatched subinterface parent.')
        vid = sub.setdefault('vlan', None)
        address = sub.setdefault('address', '')
        if not isinstance(address, str):
            raise ValueError('Subinterface address must be a string.')
        if address:
            ipaddress.IPv4Interface(address)
        if vid is None:
            if address:
                raise ValueError('Configure dot1Q encapsulation before the IP address.')
        else:
            integer(vid, 1, 4094, 'Subinterface VLAN')
            pair = (sub['parent'], vid)
            if pair in combinations:
                raise ValueError('Duplicate parent/VLAN encapsulation.')
            combinations.add(pair)
    from .svi import validate_svis
    validate_svis(node)
    shutdown = node.setdefault('shutdown', [])
    all_interfaces = addresses(node)
    if not isinstance(shutdown, list) or any(not isinstance(p, str) or p not in all_interfaces for p in shutdown):
        raise ValueError('shutdown: array of known interfaces.')
    if len(shutdown) != len(set(shutdown)):
        raise ValueError('Duplicate shutdown interface.')
    forwarding = node.setdefault('forwarding', role in ('router', 'firewall'))
    if type(forwarding) is not bool or (forwarding and role not in ('router', 'firewall') and not node['svis']):
        raise ValueError('IPv4 forwarding requires a router/firewall or a Linux switch with declared SVIs.')
    dialect = node.setdefault('dialect', 'linux')
    if dialect not in ('linux', 'ios-basic') or (dialect == 'ios-basic' and role not in ('router', 'switch')):
        raise ValueError('ios-basic is a partial CLI for OCI routers/switches only.')
    aliases = node.setdefault('interface_aliases', {})
    if not isinstance(aliases, dict) or len(aliases) > 64:
        raise ValueError('interface_aliases must be an object.')
    from ..engine import port_name
    canonical = {}
    for alias, interface in aliases.items():
        alias = port_name(alias)
        if interface not in node['interfaces'] or alias in canonical or '.' in alias or re.fullmatch(r'vlan\d+', alias):
            raise ValueError('Interface alias must identify a physical interface uniquely.')
        canonical[alias] = interface
    if len(set(canonical.values())) != len(canonical):
        raise ValueError('Only one alias per physical interface.')
    node['interface_aliases'] = canonical
    clients = node.setdefault('dhcp_clients', [])
    if not isinstance(clients, list) or len(clients) > 1:
        raise ValueError('Initial DHCP client support: at most one interface per node.')
    for interface in clients:
        if interface not in all_interfaces or all_interfaces[interface] or node.get('gateway'):
            raise ValueError('DHCP client interface requires an empty address and no static gateway.')
        if interface in subs and subs[interface]['vlan'] is None:
            raise ValueError('DHCP requires configured dot1Q encapsulation.')
    server = node.setdefault('dhcp_server', None)
    if server is not None:
        from .dhcp import validate_server
        validate_server(node)
    routes = node.setdefault('routes', [])
    if not isinstance(routes, list) or len(routes) > 128:
        raise ValueError('routes: array of at most 128 static IPv4 routes.')
    destinations = set()
    for route in routes:
        keys(route, ('destination', 'gateway', 'interface'), 'Static route')
        network = ipaddress.IPv4Network(route.get('destination'), strict=False)
        route['destination'] = str(network)
        if network.prefixlen == 0 or route['destination'] in destinations:
            raise ValueError('Static routes must have unique non-default prefixes; use gateway for default.')
        destinations.add(route['destination'])
        interface = route.get('interface')
        if (role == 'switch' and interface not in node['svis']) or interface not in all_interfaces or not all_interfaces[interface]:
            raise ValueError('Static route requires a numbered routed interface or SVI.')
        local = ipaddress.IPv4Interface(all_interfaces[interface])
        gateway = ipaddress.IPv4Address(route.get('gateway'))
        if gateway not in local.network or gateway == local.ip or (local.network.prefixlen < 31 and gateway in (local.network.network_address, local.network.broadcast_address)):
            raise ValueError('Static route gateway must be a usable on-link peer.')
        if any(address and network == ipaddress.IPv4Interface(address).network for address in all_interfaces.values()):
            raise ValueError('Static route cannot replace a directly connected subnet.')
        route['gateway'] = str(gateway)
    from .port_security import validate_security
    validate_security(node)
    from .snooping import validate_snooping
    validate_snooping(node)
    from .arp_inspection import validate_inspection
    validate_inspection(node)
    from .source_guard import validate_guard
    validate_guard(node)
    from .multicast import validate_multicast
    validate_multicast(node)
    from .dns import validate_dns
    validate_dns(node)
    from .lldp import validate_lldp
    validate_lldp(node)
    from .dhcp_relay import validate_relay
    validate_relay(node)
    from .dhcp_multi import validate_pools
    validate_pools(node)
    from .ospf import validate_ospf
    validate_ospf(node)
    from .ospfv3 import validate_node as validate_ospfv3
    validate_ospfv3(node)
    from .spanning_tree import validate_tree
    validate_tree(node)
    from .ovs import validate_ovs
    validate_ovs(node)
    from .management import validate_node as validate_management
    validate_management(node)
    from .syslog_server import validate_node as validate_collector
    validate_collector(node)
    from .ntp_server import validate_node as validate_ntp
    validate_ntp(node)
    from .snmp import validate_node as validate_snmp
    validate_snmp(node)
    from .snmp_notifications import validate_node as validate_snmp_receiver
    validate_snmp_receiver(node)
    from .tftp_server import validate_node as validate_tftp_server
    validate_tftp_server(node)
    from .radius_server import validate_node as validate_radius_server
    validate_radius_server(node)
    from .radius_access import validate_node as validate_radius_access
    validate_radius_access(node)
    from .dhcpv6_relay import validate_node as validate_dhcpv6_relay
    validate_dhcpv6_relay(node)
    from .dhcpv6_pd import validate_node as validate_pd
    validate_pd(node)
    if node['runtime'] != 'oci' and any((ports, subs, clients, server, shutdown, aliases, routes, dialect != 'linux')):
        raise ValueError('Native LAN configuration extensions require OCI; Firecracker remains single-NIC/static.')


def memberships(node, port):
    """(VID, PVID, egress untagged) for configured active VLANs only."""
    if port['mode'] == 'access':
        return [(port['vlan'], True, True)]
    allowed = node['vlans'] if port['allowed'] == 'all' else sorted(set(node['vlans']) & set(port['allowed']))
    return [(vlan, vlan == port['native_vlan'], vlan == port['native_vlan']) for vlan in allowed]


def configure(manager, index, node, previous=None):
    """Apply one node's managed network state; caller owns rollback and journal."""
    ns = lambda *args, **kwargs: manager.ns(index, *args, **kwargs)
    created_svis = set()
    initial = previous is None
    previous = previous or node
    # A port edit must not flap unrelated links or flush unrelated addresses.
    for interface in node['interfaces']:
        changed = (node['interfaces'][interface] != previous['interfaces'][interface]
                   or node['switchports'].get(interface) != previous['switchports'].get(interface)
                   or node.get('interface_macs', {}).get(interface) != previous.get('interface_macs', {}).get(interface)
                   or (interface in node['shutdown']) != (interface in previous['shutdown']))
        if initial or changed:
            ns('ip', 'link', 'set', 'dev', interface, 'down')
    for interface, address in node.get('interface_macs', {}).items():
        if initial or address != previous.get('interface_macs', {}).get(interface):
            ns('ip', 'link', 'set', 'dev', interface, 'address', address)
    if node['role'] == 'switch' and node.get('switch_backend') != 'ovs':
        from .port_security import apply as apply_security
        apply_security(manager, index, node, None if initial else previous)
        from .snooping import apply as apply_snooping
        apply_snooping(manager, index, node, None if initial else previous)
        from .arp_inspection import apply as apply_arp_inspection
        apply_arp_inspection(manager, index, node, None if initial else previous)
        from .source_guard import apply as apply_guard
        apply_guard(manager, index, node, None if initial else previous)
        from .lacp import configure as configure_channels
        recreated = configure_channels(manager, index, node, previous)
        if ns('ip', 'link', 'show', 'dev', 'br0', check=False).returncode:
            ns('ip', 'link', 'add', 'br0', 'type', 'bridge', 'stp_state', '0', 'vlan_filtering', '1', 'vlan_default_pvid', '0')
        from .spanning_tree import bridge_options, configure_ports, verify_kernel
        ns('ip', 'link', 'set', 'dev', 'br0', 'type', 'bridge', *bridge_options(node, previous, initial))
        verify_kernel(manager, index, node)
        ns('ip', 'link', 'set', 'dev', 'br0', 'up')
        for interface, port in node['switchports'].items():
            old_port = previous['switchports'].get(interface)
            # A VLAN declaration can activate an unchanged all/reserved trunk
            # list; rollback must also remove those effective memberships.
            if (not initial and interface not in recreated and port == old_port
                    and memberships(node, port) == memberships(previous, old_port)):
                continue
            ns('ip', 'link', 'set', 'dev', interface, 'master', 'br0')
            current = json.loads(ns('bridge', '-j', 'vlan', 'show', 'dev', interface).stdout)
            for record in current:
                for entry in record.get('vlans', []):
                    vid = str(entry['vlan'])
                    if entry.get('vlanEnd'):
                        vid += '-' + str(entry['vlanEnd'])
                    ns('bridge', 'vlan', 'del', 'dev', interface, 'vid', vid)
            for vid, pvid, untagged in memberships(node, port):
                ns('bridge', 'vlan', 'add', 'dev', interface, 'vid', str(vid),
                   *(['pvid'] if pvid else []), *(['untagged'] if untagged else []))
        configure_ports(manager, index, node, previous, initial, recreated)
        from .multicast import configure as configure_multicast
        configure_multicast(manager, index, node, previous, initial)
        from .svi import configure as configure_svis
        created_svis = configure_svis(manager, index, node, {} if initial else previous)
    # Recreate only VLAN devices whose encapsulation changed, preserving others.
    old_subs = previous.get('subinterfaces', {})
    for name, old in old_subs.items():
        new = node['subinterfaces'].get(name)
        if old['vlan'] is not None and (new is None or (old['vlan'], old['parent']) != (new['vlan'], new['parent'])):
            if ns('ip', 'link', 'show', 'dev', name, check=False).returncode == 0:
                ns('ip', 'link', 'delete', 'dev', name)
    for name, sub in node['subinterfaces'].items():
        if sub['vlan'] is None:
            continue
        if ns('ip', 'link', 'show', 'dev', name, check=False).returncode:
            ns('ip', 'link', 'add', 'link', sub['parent'], 'name', name, 'type', 'vlan', 'id', str(sub['vlan']))
    if initial or node['forwarding'] != previous['forwarding']:
        ns('sysctl', '-w', 'net.ipv4.ip_forward=' + str(int(node['forwarding'])))
    for interface, address in addresses(node).items():
        if interface in node['subinterfaces'] and node['subinterfaces'][interface]['vlan'] is None:
            continue
        if interface not in node['dhcp_clients'] and (initial or interface in created_svis or address != addresses(previous).get(interface)
                                                     or node['subinterfaces'].get(interface) != previous['subinterfaces'].get(interface)):
            ns('ip', '-4', 'addr', 'flush', 'dev', interface, 'scope', 'global')
            if address:
                ns('ip', 'addr', 'add', address, 'dev', interface)
        ns('ip', 'link', 'set', 'dev', interface, 'down' if interface in node['shutdown'] else 'up')
    if not node['dhcp_clients'] and (initial or node.get('gateway') != previous.get('gateway')
                                    or addresses(node) != addresses(previous)):
        ns('ip', '-4', 'route', 'flush', 'default')
        if node.get('gateway'):
            ns('ip', 'route', 'add', 'default', 'via', node['gateway'])
    # Address/admin changes may remove kernel routes; always reassert declared routes.
    desired = {r['destination']: r for r in node['routes']}
    removed = [r for r in previous.get('routes', []) if r['destination'] not in desired]
    if removed:
        current = json.loads(ns('ip', '-j', '-4', 'route', 'show').stdout)
        for old in removed:
            if any(r.get('dst') != 'default' and str(ipaddress.IPv4Network(r['dst'], strict=False)) == old['destination'] for r in current):
                ns('ip', '-4', 'route', 'del', old['destination'])
    for route in node['routes']:
        ns('ip', '-4', 'route', 'replace', route['destination'], 'via', route['gateway'],
           'dev', route['interface'], 'proto', 'static')

    if initial and (node['slaac'] or node['dhcpv6_clients']):
        from .slaac import configure_client
        configure_client(manager, index, node)
    if initial and node['ipv6']:
        from .ipv6 import configure as configure_ipv6
        configure_ipv6(manager, index, node)
    if initial and node['dhcpv6_pd_client']:
        from .dhcpv6_pd import configure as configure_pd
        configure_pd(manager, index, node)

    from .svi import configure_arp as configure_svi_arp
    configure_svi_arp(manager, index, node)
    if node.get('dhcp_snooping') is not None or previous.get('dhcp_snooping') is not None:
        from .snooping import reconcile
        reconcile(manager, index, node, None if initial else previous)
    if not initial:
        from .stp_recovery import reconcile as reconcile_stp
        recovery = reconcile_stp(manager, index, node, previous)
        if recovery: return {'stp_recovery': recovery}


def observe(manager, index, node):
    result = {'name': node['name'], 'source': 'Linux kernel, not the educational model',
              'links': json.loads(manager.ns(index, 'ip', '-j', '-s', '-d', 'link', 'show').stdout),
              'addresses': json.loads(manager.ns(index, 'ip', '-j', '-4', 'addr', 'show').stdout),
              'routes': json.loads(manager.ns(index, 'ip', '-j', '-4', 'route', 'show').stdout),
              'forwarding': manager.ns(index, 'sysctl', '-n', 'net.ipv4.ip_forward').stdout.strip() == '1'}
    if node['ipv6'] or node['slaac'] or node['dhcpv6_clients']:
        from .ipv6 import observe as observe_ipv6
        result['addresses_ipv6'] = observe_ipv6(manager, index)
        result['routes_ipv6'] = json.loads(manager.ns(index, 'ip', '-j', '-6', 'route', 'show', 'table', 'main', timeout=3).stdout)
        result['forwarding_ipv6'] = manager.ns(index, 'sysctl', '-n', 'net/ipv6/conf/all/forwarding', timeout=3).stdout.strip()
    if node['router_advertisements']:
        from .slaac import observe_server as observe_ra
        result['router_advertisements'] = observe_ra(manager, node)
    if node['dhcpv6_clients']:
        from .dhcpv6 import observe_client
        result['dhcpv6_client'] = observe_client(manager, node)
    if node['dhcpv6_server']:
        result['dhcpv6_server'] = {'policy': node['dhcpv6_server'], 'note': 'Declared pool; observed RA/server config is separate. No lease snapshot or liveness certification.'}
    if node['dhcpv6_relay'] or node['dhcpv6_remote_server']:
        from .dhcpv6_relay import observe as observe_dhcpv6_relay
        result['dhcpv6_relay' if node['dhcpv6_relay'] else 'dhcpv6_remote_server'] = observe_dhcpv6_relay(manager, node)
    if node['dhcpv6_pd_client'] or node['dhcpv6_pd_server']:
        from .dhcpv6_pd import observe as observe_pd
        result['dhcpv6_pd'] = observe_pd(manager, node)
    if node['slaac']:
        result['slaac'] = {'interfaces': node['slaac'], 'note': 'Kernel RA acceptance policy; address/default route acquisition must be observed separately.'}
    if node.get('snmp_receiver'):
        from .snmp_notifications import observe as observe_snmp_receiver
        result['snmp_receiver'] = observe_snmp_receiver(manager, node)
    if node.get('snmp_agent'):
        from .snmp import observe as observe_snmp
        result['snmp_agent'] = observe_snmp(manager, node)
    if node.get('syslog_server'):
        from .syslog_server import observe as observe_collector
        result['syslog_server'] = observe_collector(manager, node)
    if node.get('ntp_server'):
        from .ntp_server import observe as observe_ntp
        result['ntp_server'] = observe_ntp(manager, node)
    if node.get('tftp_server'):
        from .tftp_server import observe as observe_tftp
        result['tftp_server'] = observe_tftp(manager, node)
    if node.get('radius_server'):
        from .radius_server import observe as observe_radius
        result['radius_server'] = observe_radius(manager, node)
    if node['management']:
        from .management import observe as observe_management
        result['management'] = observe_management(manager, node)
    from .route_lookup import ipv4_settings
    result['ipv4_settings'] = ipv4_settings(manager, index, node)
    if node['role'] == 'switch' and node.get('switch_backend') != 'ovs':
        from .spanning_tree import kernel_ids, observe as observe_tree
        ids = kernel_ids(manager, index) if node['spanning_tree']['mode'] == 'stp' else None
        result['spanning_tree'] = observe_tree(node, result['links'], ids)
        if node['port_channels']:
            from .lacp import observe as observe_channels
            result['port_channels'] = observe_channels(manager, index, node, result['links'])
        result['vlans'] = json.loads(manager.ns(index, 'bridge', '-j', 'vlan', 'show').stdout)
        result['fdb'] = json.loads(manager.ns(index, 'bridge', '-j', 'fdb', 'show').stdout)
        if node.get('multicast') is not None:
            from .multicast import observe as observe_multicast
            result['multicast'] = observe_multicast(manager, index, node, result['links'])
        if node.get('port_security'):
            from .port_security import observe as observe_security
            result['port_security'] = observe_security(manager, index, node)
    if node.get('svis'):
        from .svi import observe as observe_svis
        result['svis'] = observe_svis(manager, index, node, result['links'])
    if node.get('switch_backend') == 'ovs':
        from .ovs import observe as observe_ovs, tree as ovs_tree
        result['ovs'] = observe_ovs(manager, node)
        result['spanning_tree'] = ovs_tree(result['ovs'])
        result['vlans'] = []  # Linux bridge audit is unavailable for this backend.
    if node.get('lldp') is not None:
        from .lldp import observe as observe_lldp
        result['lldp'] = observe_lldp(manager, node)
    if node.get('dns_server') is not None:
        from .dns import observe_server as observe_dns
        result['dns_server'] = observe_dns(manager, index, node)
    if node.get('resolvers'):
        from .dns import observe_resolver
        result['resolver'] = observe_resolver(manager, node)
    if node.get('dhcp_server') is not None:
        from .dhcp import observe_server
        result['dhcp_server'] = observe_server(manager, node)
    if node.get('ospf') is not None:
        from .ospf import observe as observe_ospf
        result['ospf'] = observe_ospf(manager, node)
    if node.get('ospfv3') is not None:
        from .ospfv3 import observe as observe_ospfv3
        result['ospfv3'] = observe_ospfv3(manager, node)
    if node.get('dhcp_pools') is not None:
        from .dhcp_multi import observe as observe_pools
        result['dhcp_pools'] = observe_pools(manager, index, node)
    if node.get('dhcp_relay') is not None:
        from .dhcp_relay import observe as observe_relay
        result['dhcp_relay'] = observe_relay(manager, index, node)
    from .snooping import effective, observe as observe_snooping
    if effective(node) is not None:
        result['dhcp_snooping'] = observe_snooping(manager, index, node)
    from .arp_inspection import effective as arp_effective, observe as observe_arp
    if arp_effective(node) is not None:
        result['arp_inspection'] = observe_arp(manager, index, node)
    from .source_guard import effective as guard_effective, observe as observe_guard
    if guard_effective(node) is not None:
        result['ip_source_guard'] = observe_guard(manager, index, node)
    return result
