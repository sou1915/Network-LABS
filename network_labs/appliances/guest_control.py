"""Bounded, typed guest operations over Firecracker's local vsock socket."""
import ipaddress
import re
import socket
import time

OPERATIONS = {'ready': 'READY', 'addresses': 'ADDRESSES', 'routes': 'ROUTES', 'ping': 'PING', 'link': 'LINK', 'address-add': 'ADDR_ADD', 'address-delete': 'ADDR_DEL', 'route-add': 'ROUTE_ADD', 'route-delete': 'ROUTE_DEL', 'forwarding': 'FORWARDING', 'forward': 'FORWARD', 'kernel': 'KERNEL',
              'bridge-ports': 'BRIDGE_PORTS', 'bridge-add': 'BRIDGE_ADD',
              'firewall-list': 'FW_LIST', 'firewall-flush': 'FW_FLUSH', 'firewall-policy': 'FW_POLICY', 'firewall-state': 'FW_STATE', 'firewall-rule': 'FW_RULE',
              'firewall-nat-list': 'FW_NAT_LIST', 'firewall-sessions': 'FW_SESSIONS',
              'dhcp-serve': 'DHCP_SERVE',
              'vlan-add': 'VLAN_ADD', 'vlan-delete': 'VLAN_DEL',
              'bridge-vlans': 'BRIDGE_VLANS', 'bridge-vlan-filtering': 'BRIDGE_VLAN_FILTERING',
              'bridge-vlan-add': 'BRIDGE_VLAN_ADD', 'bridge-vlan-delete': 'BRIDGE_VLAN_DEL',
              'dhcp-client': 'DHCP_CLIENT', 'dhcp-leases': 'DHCP_LEASES',
              'firewall-nat-flush': 'FW_NAT_FLUSH', 'firewall-nat-rule': 'FW_NAT',
              'ospf-render': 'OSPF_RENDER', 'ospf-start': 'OSPF_START', 'ospf-stop': 'OSPF_STOP', 'ospf-show': 'OSPF_SHOW',
              'bgp-render': 'BGP_RENDER', 'bgp-start': 'BGP_START', 'bgp-stop': 'BGP_STOP', 'bgp-show': 'BGP_SHOW',
              'rip-render': 'RIP_RENDER', 'rip-start': 'RIP_START', 'rip-stop': 'RIP_STOP', 'rip-show': 'RIP_SHOW',
              'trace': 'TRACE', 'dhcp-relay-start': 'DHCP_RELAY_START', 'dhcp-relay-stop': 'DHCP_RELAY_STOP',
              'dhcp-relay-show': 'DHCP_RELAY_SHOW'}
RIP_SHOW = ('config', 'routes')


def rip_fields(rip):
    """'ROUTER_ID VERSION PORT:a|p,...' for one RIP process; the guest checks it again."""
    if not isinstance(rip, dict) or set(rip) != {'router_id', 'version', 'interfaces'}:
        raise ValueError('Guest RIP requires router_id, version and interfaces.')
    if rip['version'] not in (1, 2) or not isinstance(rip['interfaces'], list) or not 1 <= len(rip['interfaces']) <= 4:
        raise ValueError('Guest RIP: version 1 or 2, on 1..4 ports.')
    items = []
    for port in rip['interfaces']:
        if not isinstance(port, dict) or set(port) != {'port', 'passive'} or port['port'] not in ('eth0', 'eth1', 'eth2', 'eth3'):
            raise ValueError('Guest RIP port: eth0..eth3 and passive.')
        items.append(f"{port['port']}:{'p' if port['passive'] else 'a'}")
    if len(set(items)) != len(items):
        raise ValueError('Guest RIP: each port once.')
    return f"{ipaddress.IPv4Address(rip['router_id'])} {rip['version']} {','.join(items)}"
OSPF_SHOW = ('neighbors', 'interfaces', 'routes', 'config')
BGP_SHOW = ('summary', 'routes', 'config')


def bgp_fields(bgp):
    """'ASN ROUTER_ID ADDRESS:REMOTE_AS,... PREFIX,...|-' for one eBGP process; the guest checks it again."""
    if not isinstance(bgp, dict) or set(bgp) != {'asn', 'router_id', 'neighbors', 'networks'}:
        raise ValueError('Guest BGP requires asn, router_id, neighbors and networks.')
    asn = bgp['asn']
    if type(asn) is not int or not 1 <= asn <= 4294967295:
        raise ValueError('Guest BGP AS number: 1..4294967295.')
    peers = bgp['neighbors']
    if not isinstance(peers, list) or not 1 <= len(peers) <= 4:
        raise ValueError('Guest BGP: 1..4 neighbours.')
    items = []
    for peer in peers:
        remote = peer.get('remote_as') if isinstance(peer, dict) else None
        if type(remote) is not int or not 1 <= remote <= 4294967295 or remote == asn:
            raise ValueError('Guest BGP neighbour: another AS, 1..4294967295.')
        items.append(f"{ipaddress.IPv4Address(peer['address'])}:{remote}")
    networks = bgp['networks']
    if not isinstance(networks, list) or len(networks) > 8:
        raise ValueError('Guest BGP: at most 8 networks.')
    announced = ','.join(str(ipaddress.IPv4Network(n, strict=True)) for n in networks) or '-'
    return f"{asn} {ipaddress.IPv4Address(bgp['router_id'])} {','.join(items)} {announced}"


def ospf_fields(ospf):
    """'ROUTER_ID HELLO DEAD PORT:COST:STUB:TYPE:PRIORITY,...' for one area-0 OSPF process; the guest checks it again."""
    if not isinstance(ospf, dict) or set(ospf) != {'router_id', 'hello', 'dead', 'interfaces'}:
        raise ValueError('Guest OSPF requires router_id, hello, dead and interfaces.')
    hello, dead, ports = ospf['hello'], ospf['dead'], ospf['interfaces']
    if type(hello) is not int or type(dead) is not int or not 1 <= hello <= 60 or not 2 <= dead <= 240 or dead <= hello:
        raise ValueError('Guest OSPF timers: hello 1..60, dead 2..240 and above hello.')
    if not isinstance(ports, list) or not 1 <= len(ports) <= 4:
        raise ValueError('Guest OSPF runs on 1..4 ports.')
    items = []
    for port in ports:
        if not isinstance(port, dict) or set(port) != {'port', 'cost', 'passive', 'type', 'priority'}:
            raise ValueError('Guest OSPF port requires port, cost, passive, type and priority.')
        if port['port'] not in ('eth0', 'eth1', 'eth2', 'eth3') or port['type'] not in ('point-to-point', 'broadcast'):
            raise ValueError('Guest OSPF port: eth0..eth3, point-to-point or broadcast.')
        if type(port['cost']) is not int or not 1 <= port['cost'] <= 65535 or type(port['passive']) is not bool:
            raise ValueError('Guest OSPF port: cost 1..65535 and passive true or false.')
        if type(port['priority']) is not int or not 0 <= port['priority'] <= 255:
            raise ValueError('Guest OSPF port priority: 0..255.')
        items.append(f"{port['port']}:{port['cost']}:{'y' if port['passive'] else 'n'}:{port['type'][0]}:{port['priority']}")
    return f"{ipaddress.IPv4Address(ospf['router_id'])} {hello} {dead} {','.join(items)}"


def _firewall_command(operation, state, rule):
    """Typed forward-filter requests; the guest validates every field again."""
    command = OPERATIONS[operation]
    choices = {'firewall-policy': ('accept', 'drop'), 'firewall-state': ('invalid', 'established')}.get(operation)
    if choices:
        if state not in choices or rule is not None:
            raise ValueError(f'Guest {operation} requires state ' + ' or '.join(choices) + '.')
        return command + ' ' + state
    if operation == 'firewall-nat-rule':
        return command + ' ' + _nat_fields(state, rule)
    if operation != 'firewall-rule':
        if state is not None or rule is not None:
            raise ValueError(f'Guest {operation} accepts no arguments.')
        return command
    if state is not None or not isinstance(rule, dict) or set(rule) - {'action', 'in', 'out', 'protocol', 'source', 'destination', 'dport'}:
        raise ValueError('Guest firewall rule requires action and optional in/out/protocol/source/destination/dport.')
    protocol = rule.get('protocol', 'any')
    if rule.get('action') not in ('accept', 'drop') or protocol not in ('any', 'tcp', 'udp', 'icmp'):
        raise ValueError('Guest firewall rule: action accept/drop and protocol any/tcp/udp/icmp.')
    fields = [rule['action']]
    for key in ('in', 'out'):
        if key in rule and rule[key] not in ('eth0', 'eth1', 'eth2', 'eth3'):
            raise ValueError('Guest firewall interface must be eth0..eth3.')
        fields.append(rule.get(key, '-'))
    fields.append(protocol)
    for key in ('source', 'destination'):
        fields.append(str(ipaddress.IPv4Network(rule[key], strict=True)) if key in rule else '-')
    if 'dport' in rule:
        if type(rule['dport']) is not int or not 1 <= rule['dport'] <= 65535 or protocol not in ('tcp', 'udp'):
            raise ValueError('Guest firewall dport requires tcp or udp and 1..65535.')
        fields.append(str(rule['dport']))
    else:
        fields.append('-')
    return command + ' ' + ' '.join(fields)


def _nat_fields(state, rule):
    if state is not None or not isinstance(rule, dict) or set(rule) - {'type', 'in', 'out', 'protocol', 'source', 'destination', 'dport', 'to', 'to_port'}:
        raise ValueError('Guest NAT rule requires type and optional in/out/protocol/source/destination/dport/to/to_port.')
    kind, protocol = rule.get('type'), rule.get('protocol', 'any')
    if kind not in ('masquerade', 'snat', 'dnat') or protocol not in ('any', 'tcp', 'udp', 'icmp'):
        raise ValueError('Guest NAT rule: type masquerade/snat/dnat and protocol any/tcp/udp/icmp.')
    if (kind == 'dnat') != ('in' in rule) or (kind == 'dnat') == ('out' in rule):
        raise ValueError('Guest destination NAT matches in only; source NAT matches out only.')
    if (kind == 'masquerade') == ('to' in rule):
        raise ValueError('Guest SNAT and DNAT need to; masquerade chooses its own address.')
    fields = [kind]
    for key in ('in', 'out'):
        if key in rule and rule[key] not in ('eth0', 'eth1', 'eth2', 'eth3'):
            raise ValueError('Guest NAT interface must be eth0..eth3.')
        fields.append(rule.get(key, '-'))
    fields.append(protocol)
    for key in ('source', 'destination'):
        fields.append(str(ipaddress.IPv4Network(rule[key], strict=True)) if key in rule else '-')
    for key in ('dport', 'to_port'):
        if key in rule and (type(rule[key]) is not int or not 1 <= rule[key] <= 65535 or protocol not in ('tcp', 'udp')):
            raise ValueError(f'Guest NAT {key} requires tcp or udp and 1..65535.')
    if 'to_port' in rule and (kind != 'dnat' or 'dport' not in rule):
        raise ValueError('Guest NAT to_port requires dnat with dport.')
    fields.append(str(rule['dport']) if 'dport' in rule else '-')
    fields.append(nat_to(rule['to'], kind) if 'to' in rule else '-')
    fields.append(str(rule['to_port']) if 'to_port' in rule else '-')
    return ' '.join(fields)


def relay_fields(relay):
    """« SERVER PORT[,PORT…] » for DHCP_RELAY_START: the helper address and the ports it relays for (1..4)."""
    if not isinstance(relay, dict) or set(relay) != {'server', 'clients'} or not isinstance(relay['clients'], list) \
            or not 1 <= len(relay['clients']) <= 4 or not all(guest_interface(p) for p in relay['clients']):
        raise ValueError('Guest DHCP relay: a server address and 1..4 client ports.')
    return f'{ipaddress.IPv4Address(relay["server"])} ' + ','.join(relay['clients'])


def nat_to(value, kind):
    """A NAT target address; source NAT also takes an ascending range A-B (an IOS pool without overload)."""
    first, dash, last = str(value).partition('-')
    if not dash:
        return str(ipaddress.IPv4Address(first))
    if kind != 'snat' or ipaddress.IPv4Address(last) <= ipaddress.IPv4Address(first):
        raise ValueError('Guest NAT range: source NAT only, A-B ascending.')
    return f'{ipaddress.IPv4Address(first)}-{ipaddress.IPv4Address(last)}'


def _dhcp_command(operation, interface, server):
    if interface not in ('eth0', 'eth1', 'eth2', 'eth3'):
        raise ValueError('Guest DHCP requires interface eth0..eth3.')
    command = OPERATIONS[operation] + ' ' + interface
    if operation != 'dhcp-serve':
        if server is not None:
            raise ValueError(f'Guest {operation} accepts only an interface.')
        return command
    if not isinstance(server, dict) or set(server) != {'start', 'end', 'netmask', 'router', 'lease_seconds', 'dns'}:
        raise ValueError('Guest dhcp-serve requires start, end, netmask, router, lease_seconds and dns.')
    start, end = ipaddress.IPv4Address(server['start']), ipaddress.IPv4Address(server['end'])
    if not start <= end or int(end) - int(start) >= 256:
        raise ValueError('Guest DHCP pool: 1..256 addresses.')
    if type(server['lease_seconds']) is not int or not 60 <= server['lease_seconds'] <= 604800:
        raise ValueError('Guest DHCP lease_seconds: 60..604800.')
    if not isinstance(server['dns'], list) or len(server['dns']) > 3:
        raise ValueError('Guest DHCP dns: up to three IPv4 addresses.')
    router = str(ipaddress.IPv4Address(server['router'])) if server['router'] else '-'
    dns = ','.join(str(ipaddress.IPv4Address(a)) for a in server['dns']) or '-'
    netmask = str(ipaddress.IPv4Network('0.0.0.0/' + str(server['netmask'])).netmask)
    return ' '.join([command, str(start), str(end), netmask, router, str(server['lease_seconds']), dns])


def guest_interface(name):
    """A guest port eth0..eth3, or one of its 802.1Q subinterfaces eth0.1 .. eth3.4094."""
    match = re.fullmatch(r'eth[0-3](?:\.([1-9][0-9]{0,3}))?', name) if isinstance(name, str) else None
    return bool(match) and (match[1] is None or int(match[1]) <= 4094)


def _bridge_vlan_command(operation, interface, vlan, state):
    command = OPERATIONS[operation]
    if operation in ('bridge-vlans', 'bridge-vlan-filtering'):
        if interface is not None or vlan is not None or state is not None:
            raise ValueError(f'Guest {operation} accepts no arguments.')
        return command
    if interface not in ('eth0', 'eth1', 'eth2', 'eth3') or type(vlan) is not int or not 1 <= vlan <= 4094:
        raise ValueError('Guest bridge VLAN change requires interface eth0..eth3 and a VLAN 1..4094.')
    if operation == 'bridge-vlan-add':
        if state not in ('pvid', 'tagged'):
            raise ValueError('Guest bridge-vlan-add requires state pvid (untagged, ingress default) or tagged.')
        return f'{command} {interface} {vlan} {state}'
    if state is not None:
        raise ValueError('Guest bridge-vlan-delete accepts no state.')
    return f'{command} {interface} {vlan}'


def request(path, operation, *, destination=None, interface=None, state=None, cidr=None, network=None, gateway=None, rule=None, dhcp=None,
            vlan=None, ospf=None, bgp=None, rip=None, ttl=None, relay=None, timeout=6):
    if operation not in OPERATIONS:
        raise ValueError('Unsupported guest operation.')
    if operation.startswith('dhcp-relay-'):  # IOS « ip helper-address »: the agent's own relay
        if any(value is not None for value in (destination, interface, state, cidr, network, gateway, rule, dhcp, vlan, ospf, bgp, rip, ttl)) \
                or (relay is None) != (operation != 'dhcp-relay-start'):
            raise ValueError('Guest dhcp-relay-start takes only the relay; stop and show take nothing.')
        return _exchange(path, operation, OPERATIONS[operation] + (' ' + relay_fields(relay) if relay else ''), timeout)
    if relay is not None:
        raise ValueError('Only dhcp-relay-start accepts a relay.')
    if operation == 'trace':  # one traceroute hop: a UDP probe at TTL
        if any(value is not None for value in (interface, state, cidr, network, gateway, rule, dhcp, vlan, ospf, bgp, rip)) \
                or type(ttl) is not int or not 1 <= ttl <= 30:
            raise ValueError('Guest trace requires a destination and a TTL 1..30.')
        return _exchange(path, operation, f'TRACE {ttl} {ipaddress.IPv4Address(destination)}', timeout)
    if ttl is not None:
        raise ValueError('Only trace accepts a TTL.')
    if operation.startswith('rip-'):
        if any(value is not None for value in (destination, interface, cidr, network, gateway, rule, dhcp, vlan, ospf, bgp)):
            raise ValueError('Guest RIP operations accept only the process (render, start) or what to show.')
        if operation in ('rip-render', 'rip-start'):
            if state is not None:
                raise ValueError(f'Guest {operation} accepts only the RIP process.')
            return _exchange(path, operation, OPERATIONS[operation] + ' ' + rip_fields(rip), timeout)
        if rip is not None or (operation == 'rip-stop') != (state is None) or (state is not None and state not in RIP_SHOW):
            raise ValueError('Guest rip-show requires config or routes; rip-stop takes nothing.')
        return _exchange(path, operation, OPERATIONS[operation] + ('' if state is None else ' ' + state), timeout)
    if rip is not None:
        raise ValueError('Only rip-render and rip-start accept a RIP process.')
    if operation.startswith('bgp-'):
        if any(value is not None for value in (destination, interface, cidr, network, gateway, rule, dhcp, vlan, ospf)):
            raise ValueError('Guest BGP operations accept only the process (render, start) or what to show.')
        if operation in ('bgp-render', 'bgp-start'):
            if state is not None:
                raise ValueError(f'Guest {operation} accepts only the BGP process.')
            return _exchange(path, operation, OPERATIONS[operation] + ' ' + bgp_fields(bgp), timeout)
        if bgp is not None or (operation == 'bgp-stop') != (state is None) or (state is not None and state not in BGP_SHOW):
            raise ValueError('Guest bgp-show requires one of ' + ', '.join(BGP_SHOW) + '; bgp-stop takes nothing.')
        return _exchange(path, operation, OPERATIONS[operation] + ('' if state is None else ' ' + state), timeout)
    if bgp is not None:
        raise ValueError('Only bgp-render and bgp-start accept a BGP process.')
    if operation.startswith('ospf-'):
        if any(value is not None for value in (destination, interface, cidr, network, gateway, rule, dhcp, vlan)):
            raise ValueError('Guest OSPF operations accept only the process (render, start) or what to show.')
        if operation in ('ospf-render', 'ospf-start'):
            if state is not None:
                raise ValueError(f'Guest {operation} accepts only the OSPF process.')
            return _exchange(path, operation, OPERATIONS[operation] + ' ' + ospf_fields(ospf), timeout)
        if ospf is not None or (operation == 'ospf-stop') != (state is None) or (state is not None and state not in OSPF_SHOW):
            raise ValueError('Guest ospf-show requires one of ' + ', '.join(OSPF_SHOW) + '; ospf-stop takes nothing.')
        return _exchange(path, operation, OPERATIONS[operation] + ('' if state is None else ' ' + state), timeout)
    if ospf is not None:
        raise ValueError('Only ospf-render and ospf-start accept an OSPF process.')
    if operation in ('vlan-add', 'vlan-delete'):
        if any(value is not None for value in (destination, state, cidr, network, gateway, rule, dhcp)):
            raise ValueError('Guest VLAN interface operations accept only an interface and, to add one, a VLAN.')
        if operation == 'vlan-add':
            if interface not in ('eth0', 'eth1', 'eth2', 'eth3') or type(vlan) is not int or not 1 <= vlan <= 4094:
                raise ValueError('Guest vlan-add requires a parent port eth0..eth3 and a VLAN 1..4094.')
            return _exchange(path, operation, f'VLAN_ADD {interface} {vlan}', timeout)
        if not guest_interface(interface) or '.' not in interface or vlan is not None:
            raise ValueError('Guest vlan-delete requires a subinterface such as eth0.10 and no VLAN.')
        return _exchange(path, operation, f'VLAN_DEL {interface}', timeout)
    if operation.startswith('bridge-vlan'):
        if any(value is not None for value in (destination, cidr, network, gateway, rule, dhcp)):
            raise ValueError('Guest bridge VLAN operations accept only an interface, a VLAN and a state.')
        return _exchange(path, operation, _bridge_vlan_command(operation, interface, vlan, state), timeout)
    if vlan is not None:
        raise ValueError('Only bridge VLAN operations accept a VLAN.')
    if operation.startswith('dhcp-'):
        if any(value is not None for value in (destination, state, cidr, network, gateway, rule)):
            raise ValueError('Guest DHCP operations accept only an interface and, for dhcp-serve, the pool.')
        return _exchange(path, operation, _dhcp_command(operation, interface, dhcp), timeout)
    if dhcp is not None:
        raise ValueError('Only dhcp-serve accepts a DHCP pool.')
    if operation.startswith('firewall-'):
        if any(value is not None for value in (destination, interface, cidr, network, gateway)):
            raise ValueError('Guest firewall operations accept only state or rule.')
        return _exchange(path, operation, _firewall_command(operation, state, rule), timeout)
    if rule is not None:
        raise ValueError('Only firewall-rule accepts a rule.')
    command = OPERATIONS[operation]
    if operation == 'ping':
        command += ' ' + str(ipaddress.IPv4Address(destination))
    elif destination is not None:
        raise ValueError('Only ping accepts a destination.')
    if operation == 'link':
        if not guest_interface(interface) or state not in ('up', 'down'):
            raise ValueError('Guest link requires interface eth0..eth3 (or a subinterface) and state up or down.')
        command += ' ' + interface + ' ' + state
    elif operation == 'bridge-add':
        if interface not in ('eth0', 'eth1', 'eth2', 'eth3') or state is not None:
            raise ValueError('Guest bridge-add requires interface eth0..eth3 and no state.')
        command += ' ' + interface
    elif operation == 'forward':
        if interface is not None or state not in ('on', 'off'):
            raise ValueError('Guest forwarding requires state on or off and no interface.')
        command += ' ' + state
    elif state is not None or (interface is not None and operation not in ('address-add', 'address-delete', 'route-add', 'route-delete')):
        raise ValueError('Only link, address and route operations accept an interface; only link accepts a state.')
    if operation in ('address-add', 'address-delete'):
        if not isinstance(cidr, str) or '/' not in cidr:
            raise ValueError('Guest address requires explicit IPv4/prefix.')
        if interface is not None:
            if not guest_interface(interface):
                raise ValueError('Guest address interface must be eth0..eth3 or a subinterface.')
            command = ('IF_ADD' if operation == 'address-add' else 'IF_DEL') + ' ' + interface
        command += ' ' + str(ipaddress.IPv4Interface(cidr))
    elif cidr is not None:
        raise ValueError('Only address operations accept CIDR.')
    if operation in ('route-add', 'route-delete'):
        if not isinstance(network, str) or '/' not in network:
            raise ValueError('Guest route requires an explicit IPv4 network/prefix.')
        if interface is not None:
            if not guest_interface(interface):
                raise ValueError('Guest route interface must be eth0..eth3 or a subinterface.')
            command = ('IF_ROUTE_ADD' if operation == 'route-add' else 'IF_ROUTE_DEL') + ' ' + interface
        command += ' ' + str(ipaddress.IPv4Network(network, strict=True)) + ' ' + str(ipaddress.IPv4Address(gateway))
    elif network is not None or gateway is not None:
        raise ValueError('Only route operations accept network/gateway.')
    return _exchange(path, operation, command, timeout)


def _exchange(path, operation, command, timeout):
    if not 0 < timeout <= 30:
        raise ValueError('Guest timeout must be between 0 and 30 seconds.')
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        def receive(size):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Guest response deadline exceeded.')
            connection.settimeout(remaining)
            data = connection.recv(size)
            if not data:
                raise ValueError('Truncated guest response.')
            return data
        def line():
            data = b''
            while len(data) < 80:
                part = receive(1)
                if part == b'\n':
                    return data.decode('ascii')
                data += part
            raise ValueError('Guest response header too long.')
        connection.settimeout(timeout)
        connection.connect(str(path))
        connection.sendall(b'CONNECT 19001\n')
        handshake = line().split()
        if len(handshake) != 2 or handshake[0] != 'OK' or not handshake[1].isdigit():
            raise ValueError('Firecracker vsock connection rejected.')
        connection.sendall(('NL1 ' + command + '\n').encode('ascii'))
        fields = line().split()
        if len(fields) != 3 or fields[0] != 'NL1' or not all(v.isdecimal() for v in fields[1:]):
            raise ValueError('Invalid guest response header.')
        code, length = map(int, fields[1:])
        if not 0 <= code <= 255 or not 0 <= length <= 32768:
            raise ValueError('Guest response exceeds protocol limits.')
        body = bytearray()
        while len(body) < length:
            body.extend(receive(length - len(body)))
        return {'operation': operation, 'exit_code': code, 'output': body.decode('utf-8', errors='replace')}
