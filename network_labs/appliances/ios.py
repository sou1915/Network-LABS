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
    alias = port_name(value)
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
    if node.get('dhcp_clients') or node.get('dhcp_server'):
        raise ValueError('IOS-style live configuration of DHCP service nodes is not supported yet.')
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
            match = re.fullmatch(r'interface (\S+)', command)
            if match and mode in ('config', 'interface', 'vlan'):
                interface, parent = resolve_interface(node, match[1])
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
            if command in ('ip routing', 'no ip routing') and mode == 'config' and node['role'] == 'router':
                node['forwarding'] = command == 'ip routing'; continue
            if mode == 'interface':
                if command in ('shutdown', 'no shutdown'):
                    if command == 'shutdown' and interface not in node['shutdown']:
                        node['shutdown'].append(interface)
                    elif command == 'no shutdown' and interface in node['shutdown']:
                        node['shutdown'].remove(interface)
                    continue
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
