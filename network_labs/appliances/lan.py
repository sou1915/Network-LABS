"""Declarative LAN validation and real Linux bridge/802.1Q configuration.

No topology path computation is used for packet delivery. All operations target
an owned node namespace; the kernel makes forwarding and VLAN decisions.
"""
import ipaddress
import copy
import json
import re

from .spec import integer, keys

LAN_FIELDS = ('vlans', 'switchports', 'subinterfaces', 'shutdown', 'forwarding',
              'dhcp_server', 'dhcp_clients', 'dialect', 'interface_aliases', 'routes', 'port_channels', 'spanning_tree')


def addresses(node):
    return {**node['interfaces'], **{name: '' for name in node.get('port_channels', {})}, **{name: sub['address'] for name, sub in node.get('subinterfaces', {}).items()}}


def validate_lan(node):
    role = node['role']
    from .lacp import validate_channels
    members = validate_channels(node)
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
    shutdown = node.setdefault('shutdown', [])
    all_interfaces = addresses(node)
    if not isinstance(shutdown, list) or any(not isinstance(p, str) or p not in all_interfaces for p in shutdown):
        raise ValueError('shutdown: array of known interfaces.')
    if len(shutdown) != len(set(shutdown)):
        raise ValueError('Duplicate shutdown interface.')
    forwarding = node.setdefault('forwarding', role in ('router', 'firewall'))
    if type(forwarding) is not bool or (forwarding and role not in ('router', 'firewall')):
        raise ValueError('Only routers/firewalls can enable IPv4 forwarding.')
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
        if interface not in node['interfaces'] or alias in canonical or '.' in alias:
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
        keys(server, ('interface', 'start', 'end', 'router', 'dns', 'lease_seconds'), 'DHCP server')
        interface = server.get('interface')
        if interface not in all_interfaces or not all_interfaces[interface] or role == 'switch':
            raise ValueError('DHCP server requires a numbered interface on a host/router/firewall.')
        network = ipaddress.IPv4Interface(all_interfaces[interface])
        start, end = ipaddress.IPv4Address(server.get('start')), ipaddress.IPv4Address(server.get('end'))
        if not (network.network.network_address < start <= end < network.network.broadcast_address) or int(end) - int(start) >= 256:
            raise ValueError('DHCP pool: 1..256 usable addresses in the server subnet.')
        if start <= network.ip <= end:
            raise ValueError('DHCP pool overlaps its server address.')
        router = server.setdefault('router', '')
        if router:
            gateway = ipaddress.IPv4Address(router)
            if gateway not in network.network or gateway in (network.network.network_address, network.network.broadcast_address) or start <= gateway <= end:
                raise ValueError('DHCP router must be usable, in subnet and outside the pool.')
        dns = server.setdefault('dns', [])
        if not isinstance(dns, list) or len(dns) > 3:
            raise ValueError('DHCP dns: array of up to three IPv4 addresses.')
        for address in dns:
            ipaddress.IPv4Address(address)
        integer(server.setdefault('lease_seconds', 3600), 60, 604800, 'DHCP lease_seconds')
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
        if role == 'switch' or interface not in all_interfaces or not all_interfaces[interface]:
            raise ValueError('Static route requires a numbered non-switch interface.')
        local = ipaddress.IPv4Interface(all_interfaces[interface])
        gateway = ipaddress.IPv4Address(route.get('gateway'))
        if gateway not in local.network or gateway == local.ip or (local.network.prefixlen < 31 and gateway in (local.network.network_address, local.network.broadcast_address)):
            raise ValueError('Static route gateway must be a usable on-link peer.')
        if any(address and network == ipaddress.IPv4Interface(address).network for address in all_interfaces.values()):
            raise ValueError('Static route cannot replace a directly connected subnet.')
        route['gateway'] = str(gateway)
    from .spanning_tree import validate_tree
    validate_tree(node)
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
    initial = previous is None
    previous = previous or node
    # A port edit must not flap unrelated links or flush unrelated addresses.
    for interface in node['interfaces']:
        changed = (node['interfaces'][interface] != previous['interfaces'][interface]
                   or node['switchports'].get(interface) != previous['switchports'].get(interface)
                   or (interface in node['shutdown']) != (interface in previous['shutdown']))
        if initial or changed:
            ns('ip', 'link', 'set', 'dev', interface, 'down')
    if node['role'] == 'switch':
        from .lacp import configure as configure_channels
        recreated = configure_channels(manager, index, node, previous)
        if ns('ip', 'link', 'show', 'dev', 'br0', check=False).returncode:
            ns('ip', 'link', 'add', 'br0', 'type', 'bridge', 'stp_state', '0', 'vlan_filtering', '1', 'vlan_default_pvid', '0')
        from .spanning_tree import bridge_options, configure_ports, verify_kernel
        ns('ip', 'link', 'set', 'dev', 'br0', 'type', 'bridge', *bridge_options(node, previous, initial))
        verify_kernel(manager, index, node)
        ns('ip', 'link', 'set', 'dev', 'br0', 'up')
        for interface, port in node['switchports'].items():
            if not initial and interface not in recreated and port == previous['switchports'].get(interface):
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
        if interface not in node['dhcp_clients'] and (initial or address != addresses(previous).get(interface)
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


def observe(manager, index, node):
    result = {'name': node['name'], 'source': 'Linux kernel, not the educational model',
              'links': json.loads(manager.ns(index, 'ip', '-j', '-d', 'link', 'show').stdout),
              'addresses': json.loads(manager.ns(index, 'ip', '-j', '-4', 'addr', 'show').stdout),
              'routes': json.loads(manager.ns(index, 'ip', '-j', '-4', 'route', 'show').stdout),
              'forwarding': manager.ns(index, 'sysctl', '-n', 'net.ipv4.ip_forward').stdout.strip() == '1'}
    if node['role'] == 'switch':
        from .spanning_tree import observe as observe_tree
        result['spanning_tree'] = observe_tree(node, result['links'])
        if node['port_channels']:
            from .lacp import observe as observe_channels
            result['port_channels'] = observe_channels(manager, index, node, result['links'])
        result['vlans'] = json.loads(manager.ns(index, 'bridge', '-j', 'vlan', 'show').stdout)
        result['fdb'] = json.loads(manager.ns(index, 'bridge', '-j', 'fdb', 'show').stdout)
    return result
