"""Small, explicit IOS-style configuration adapter. No Cisco firmware is run.

Parse a whole block before applying it; reject unknown commands with line
numbers. The resulting manifest drives Linux, not a synthetic ping model.
"""
import copy
import ipaddress
import re

from ..engine import port_name, vlan_list
from .spec import validate


def resolve_interface(node, value):
    match = re.fullmatch(r'vlan\s*(\d+)', value.strip().lower())
    if match:
        if node['role'] != 'switch' or node.get('switch_backend', 'linux') != 'linux':
            raise ValueError('SVI interfaces require a Linux-bridge switch.')
        from .spec import integer
        return 'vlan' + str(integer(int(match[1]), 1, 4094, 'SVI VLAN')), None
    alias = port_name(value)
    if alias.startswith('po'):
        bond = 'bond' + alias[2:]
        if bond not in node.get('port_channels', {}):
            raise ValueError('Declare port-channel membership in the manifest before live configuration.')
        return bond, None
    if '.' in alias:
        physical, suffix = alias.split('.', 1)
        parent = node['interface_aliases'].get(physical, physical)
        if parent not in node['interfaces']:
            raise ValueError('Unknown physical interface: ' + value)
        return parent + '.' + suffix, parent
    interface = node['interface_aliases'].get(alias, alias)
    if interface not in node['interfaces']:
        raise ValueError('Unknown interface: ' + value)
    return interface, None


def compile_config(spec, name, text):
    candidate = copy.deepcopy(spec)
    node = next((node for node in candidate['nodes'] if node['name'] == name), None)
    if node is None or node.get('dialect') != 'ios-basic' or node['runtime'] != 'oci':
        raise ValueError('An OCI node with dialect ios-basic is required. This is not Cisco IOS firmware.')
    if node.get('switch_backend') == 'ovs':
        raise ValueError('OVS configuration uses its real native tools; IOS-style edits are unsupported.')
    if node.get('dhcp_clients') or node.get('dhcp_server') or node.get('dns_server') or node.get('lldp') is not None:
        raise ValueError('IOS-style live configuration of DHCP/DNS/LLDP service nodes is not supported yet.')
    if not isinstance(text, str) or len(text) > 65536:
        raise ValueError('Configuration block must be text, at most 64 KiB.')
    mode, interface = 'priv', None
    for line_number, source in enumerate(text.splitlines(), 1):
        command = source.strip().lower()
        if not command or command.startswith('!'):
            continue
        try:
            if command == 'enable' and mode == 'priv':
                continue
            if command in ('configure terminal', 'conf t') and mode == 'priv':
                mode = 'config'; continue
            if command == 'end':
                mode = 'priv'; interface = None; continue
            if command == 'exit':
                mode = 'config' if mode in ('interface', 'vlan') else 'priv'
                interface = None; continue
            match = re.fullmatch(r'no interface (vlan\s*\d+)', command)
            if match and mode == 'config':
                name, _ = resolve_interface(node, match[1])
                node.setdefault('svis', {}).pop(name, None)
                node['shutdown'] = [p for p in node['shutdown'] if p != name]
                continue
            match = re.fullmatch(r'interface (vlan\s*\d+|\S+)', command)
            if match and mode in ('config', 'interface', 'vlan'):
                interface, parent = resolve_interface(node, match[1])
                if re.fullmatch(r'vlan\d+', interface):
                    node.setdefault('svis', {}).setdefault(interface, {'vlan': int(interface[4:]), 'address': ''})
                if parent:
                    if node['role'] != 'router':
                        raise ValueError('Only router dot1Q subinterfaces are supported.')
                    node['subinterfaces'].setdefault(interface, {'parent': parent, 'vlan': None, 'address': ''})
                mode = 'interface'; continue
            match = re.fullmatch(r'vlan (\d+)', command)
            if match and mode in ('config', 'interface', 'vlan') and node['role'] == 'switch':
                vid = int(match[1])
                if vid not in node['vlans']:
                    node['vlans'].append(vid)
                mode = 'vlan'; interface = None; continue
            if mode == 'config' and node['role'] == 'switch' and command in ('ip igmp snooping', 'no ip igmp snooping', 'ip igmp snooping querier', 'no ip igmp snooping querier'):
                if node.get('multicast') is None:
                    node['multicast'] = {'snooping': True, 'querier': False, 'ports': {}}
                policy = node['multicast']
                policy['querier' if command.endswith('querier') else 'snooping'] = not command.startswith('no ')
                continue
            if mode == 'config' and node['role'] == 'switch' and command.startswith(('ip arp inspection', 'no ip arp inspection', 'ip source binding', 'no ip source binding')):
                policy = node.get('arp_inspection')
                if policy is None:
                    policy = node['arp_inspection'] = {'vlans': [], 'trusted': [], 'bindings': []}
                match = re.fullmatch(r'(no )?ip arp inspection vlan (\S+)', command)
                if match:
                    values = vlan_list(match[2])
                    policy['vlans'] = sorted(set(policy['vlans']) - set(values) if match[1] else set(policy['vlans']) | set(values))
                    continue
                match = re.fullmatch(r'(no )?ip source binding (\S+) vlan (\d+) (\S+) interface (\S+)', command)
                if match:
                    from .port_security import mac_address
                    from .arp_inspection import valid_ip
                    port, parent = resolve_interface(node, match[5])
                    if parent:
                        raise ValueError('Static source binding requires a physical access port.')
                    entry = {'port': port, 'mac': mac_address(match[2]), 'vlan': int(match[3]), 'address': valid_ip(match[4])}
                    if match[1]:
                        policy['bindings'] = [b for b in policy['bindings'] if b != entry]
                    elif entry not in policy['bindings']:
                        policy['bindings'].append(entry)
                    continue
                raise ValueError('ARP inspection supports vlan selection and static ip source binding; validate/rate limiting/ARP ACL syntax not implemented.')
            if mode == 'config' and node['role'] == 'switch' and command.startswith(('ip dhcp snooping', 'no ip dhcp snooping')):
                policy = node.get('dhcp_snooping')
                if policy is None:
                    policy = node['dhcp_snooping'] = {'enabled': False, 'vlans': [], 'trusted': []}
                if command in ('ip dhcp snooping', 'no ip dhcp snooping'):
                    policy['enabled'] = command == 'ip dhcp snooping'; continue
                match = re.fullmatch(r'(no )?ip dhcp snooping vlan (\S+)', command)
                if match:
                    values = vlan_list(match[2])
                    policy['vlans'] = sorted(set(policy['vlans']) - set(values) if match[1] else set(policy['vlans']) | set(values))
                    continue
                raise ValueError('DHCP snooping supports enable and vlan selection; relay/Option 82/rate limiting are not implemented.')
            if command in ('ip routing', 'no ip routing') and mode == 'config' and node['role'] in ('router', 'switch'):
                node['forwarding'] = command == 'ip routing'; continue
            if command.startswith(('ip route ', 'no ip route ')) and mode == 'config' and node['role'] in ('router', 'switch'):
                from .static_routes import configure_route
                configure_route(node, command, resolve_interface)
                continue
            if mode == 'interface':
                if command in ('shutdown', 'no shutdown'):
                    if command == 'shutdown' and interface not in node['shutdown']:
                        node['shutdown'].append(interface)
                    elif command == 'no shutdown' and interface in node['shutdown']:
                        node['shutdown'].remove(interface)
                    continue
                if interface in node.get('svis', {}):
                    match = re.fullmatch(r'ip address (\S+) (\S+)', command)
                    if match:
                        node['svis'][interface]['address'] = str(ipaddress.IPv4Interface(match[1] + '/' + match[2]))
                        continue
                    if command == 'no ip address':
                        node['svis'][interface]['address'] = ''
                        continue
                    raise ValueError('SVI supports ip address/no ip address and shutdown/no shutdown only.')
                if node['role'] == 'router':
                    sub = node['subinterfaces'].get(interface)
                    match = re.fullmatch(r'encapsulation dot1q (\d+)', command)
                    if match and sub is not None:
                        sub['vlan'] = int(match[1]); continue
                    match = re.fullmatch(r'ip address (\S+) (\S+)', command)
                    if match:
                        address = str(ipaddress.IPv4Interface(match[1] + '/' + match[2]))
                        if sub is not None:
                            sub['address'] = address
                        else:
                            node['interfaces'][interface] = address
                        continue
                    if command == 'no ip address':
                        if sub is not None:
                            sub['address'] = ''
                        else:
                            node['interfaces'][interface] = ''
                        continue
                if node['role'] == 'switch':
                    if command in ('ip verify source', 'ip verify source port-security', 'no ip verify source', 'no ip verify source port-security'):
                        if node.get('ip_source_guard') is None:
                            node['ip_source_guard'] = {}
                        if command.startswith('no '):
                            node['ip_source_guard'].pop(interface, None)
                        else:
                            node['ip_source_guard'][interface] = 'ip-mac' if command.endswith('port-security') else 'ip'
                        continue
                    if command in ('ip arp inspection trust', 'no ip arp inspection trust'):
                        if interface not in node['switchports']:
                            raise ValueError('ARP trust requires a switch port.')
                        if node.get('arp_inspection') is None:
                            node['arp_inspection'] = {'vlans': [], 'trusted': [], 'bindings': []}
                        trusted = node['arp_inspection']['trusted']
                        if command == 'ip arp inspection trust' and interface not in trusted:
                            trusted.append(interface)
                        elif command == 'no ip arp inspection trust' and interface in trusted:
                            trusted.remove(interface)
                        continue
                    if command in ('ip dhcp snooping trust', 'no ip dhcp snooping trust'):
                        if interface not in node['switchports']:
                            raise ValueError('DHCP snooping trust requires a logical switch port.')
                        if node.get('dhcp_snooping') is None:
                            node['dhcp_snooping'] = {'enabled': False, 'vlans': [], 'trusted': []}
                        trusted = node['dhcp_snooping']['trusted']
                        if command == 'ip dhcp snooping trust' and interface not in trusted:
                            trusted.append(interface)
                        elif command == 'no ip dhcp snooping trust' and interface in trusted:
                            trusted.remove(interface)
                        continue
                    if command.startswith(('switchport port-security', 'no switchport port-security')):
                        if interface not in node['interfaces'] or node['switchports'].get(interface, {}).get('mode') != 'access':
                            raise ValueError('Port security requires a physical access port.')
                        policies = node['port_security']
                        if command == 'no switchport port-security':
                            policies.pop(interface, None); continue
                        if interface not in policies:
                            policies[interface] = {'maximum': 1, 'mac_addresses': [], 'violation': 'restrict'}
                        policy = policies[interface]
                        if command == 'switchport port-security':
                            continue
                        match = re.fullmatch(r'switchport port-security maximum (\d+)', command)
                        if match:
                            policy['maximum'] = int(match[1]); continue
                        if command == 'switchport port-security violation restrict':
                            policy['violation'] = 'restrict'; continue
                        match = re.fullmatch(r'(no )?switchport port-security mac-address (\S+)', command)
                        if match:
                            from .port_security import mac_address
                            address = mac_address(match[2])
                            if match[1]:
                                if address in policy['mac_addresses']:
                                    policy['mac_addresses'].remove(address)
                            elif address not in policy['mac_addresses']:
                                policy['mac_addresses'].append(address)
                            continue
                        raise ValueError('Static-only port security: maximum, mac-address and violation restrict supported; dynamic/sticky/shutdown are not implemented.')
                    if command in ('spanning-tree bpduguard enable', 'spanning-tree bpduguard disable',
                                   'no spanning-tree bpduguard enable', 'spanning-tree guard root',
                                   'spanning-tree guard none', 'no spanning-tree guard root'):
                        tree = node['spanning_tree']
                        if tree['mode'] != 'stp' or interface not in tree['ports']:
                            raise ValueError('STP protection requires an enabled logical bridge port.')
                        if 'bpduguard' in command:
                            tree['ports'][interface]['bpdu_guard'] = command == 'spanning-tree bpduguard enable'
                        else:
                            tree['ports'][interface]['root_guard'] = command == 'spanning-tree guard root'
                        continue
                    match = re.fullmatch(r'spanning-tree (cost|port-priority) (\d+)', command)
                    if match:
                        tree = node['spanning_tree']
                        if tree['mode'] != 'stp' or interface not in tree['ports']:
                            raise ValueError('Configure common STP on this logical bridge port first; per-VLAN STP is not implemented.')
                        tree['ports'][interface]['cost' if match[1] == 'cost' else 'priority'] = int(match[2]); continue
                    match = re.fullmatch(r'channel-group (\d+) mode (active|passive)', command)
                    if match:
                        channel = node['port_channels'].get('bond' + str(int(match[1])))
                        if channel is None or interface not in channel['members']:
                            raise ValueError('Live channel-group changes apply to existing manifest members only.')
                        channel['mode'] = match[2]; continue
                    match = re.fullmatch(r'port-channel min-links (\d+)', command)
                    if match and interface in node['port_channels']:
                        node['port_channels'][interface]['min_links'] = int(match[1]); continue
                    if command == 'no port-channel min-links' and interface in node['port_channels']:
                        node['port_channels'][interface]['min_links'] = 1; continue
                    if interface not in node['switchports']:
                        raise ValueError('Configure switchport settings on the logical port-channel, not its members.')
                    port = node['switchports'][interface]
                    match = re.fullmatch(r'switchport mode (access|trunk)', command)
                    if match:
                        # Mode-specific attributes are intentionally explicit;
                        # unused IOS settings are not retained by this subset.
                        if match[1] != port['mode']:
                            node['switchports'][interface] = ({'mode': 'access', 'vlan': 1} if match[1] == 'access'
                                                             else {'mode': 'trunk', 'native_vlan': 1, 'allowed': 'all'})
                        continue
                    match = re.fullmatch(r'switchport access vlan (\d+)', command)
                    if match and port['mode'] == 'access':
                        port['vlan'] = int(match[1]); continue
                    match = re.fullmatch(r'switchport trunk native vlan (\d+)', command)
                    if match and port['mode'] == 'trunk':
                        port['native_vlan'] = int(match[1]); continue
                    match = re.fullmatch(r'switchport trunk allowed vlan (\S+)', command)
                    if match and port['mode'] == 'trunk':
                        port['allowed'] = 'all' if match[1] == 'all' else vlan_list(match[1]); continue
            raise ValueError('Unsupported command or context: ' + source.strip())
        except (ValueError, KeyError, IndexError) as error:
            raise ValueError(f'Line {line_number}: {error}') from error
    return validate(candidate)
