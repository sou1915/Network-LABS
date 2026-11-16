"""Bounded, typed guest operations over Firecracker's local vsock socket."""
import ipaddress
import socket
import time

OPERATIONS = {'ready': 'READY', 'addresses': 'ADDRESSES', 'routes': 'ROUTES', 'ping': 'PING', 'link': 'LINK', 'address-add': 'ADDR_ADD', 'address-delete': 'ADDR_DEL', 'route-add': 'ROUTE_ADD', 'route-delete': 'ROUTE_DEL', 'forwarding': 'FORWARDING', 'forward': 'FORWARD', 'kernel': 'KERNEL',
              'bridge-ports': 'BRIDGE_PORTS', 'bridge-add': 'BRIDGE_ADD',
              'firewall-list': 'FW_LIST', 'firewall-flush': 'FW_FLUSH', 'firewall-policy': 'FW_POLICY', 'firewall-state': 'FW_STATE', 'firewall-rule': 'FW_RULE',
              'firewall-nat-list': 'FW_NAT_LIST', 'firewall-sessions': 'FW_SESSIONS',
              'dhcp-serve': 'DHCP_SERVE', 'dhcp-client': 'DHCP_CLIENT', 'dhcp-leases': 'DHCP_LEASES', 'firewall-nat-flush': 'FW_NAT_FLUSH', 'firewall-nat-rule': 'FW_NAT'}


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
    fields.append(str(ipaddress.IPv4Address(rule['to'])) if 'to' in rule else '-')
    fields.append(str(rule['to_port']) if 'to_port' in rule else '-')
    return ' '.join(fields)


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


def request(path, operation, *, destination=None, interface=None, state=None, cidr=None, network=None, gateway=None, rule=None, dhcp=None, timeout=6):
    if operation not in OPERATIONS:
        raise ValueError('Unsupported guest operation.')
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
        if interface not in ('eth0', 'eth1', 'eth2', 'eth3') or state not in ('up', 'down'):
            raise ValueError('Guest link requires interface eth0..eth3 and state up or down.')
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
            if interface not in ('eth0', 'eth1', 'eth2', 'eth3'):
                raise ValueError('Guest address interface must be eth0..eth3.')
            command = ('IF_ADD' if operation == 'address-add' else 'IF_DEL') + ' ' + interface
        command += ' ' + str(ipaddress.IPv4Interface(cidr))
    elif cidr is not None:
        raise ValueError('Only address operations accept CIDR.')
    if operation in ('route-add', 'route-delete'):
        if not isinstance(network, str) or '/' not in network:
            raise ValueError('Guest route requires an explicit IPv4 network/prefix.')
        if interface is not None:
            if interface not in ('eth0', 'eth1', 'eth2', 'eth3'):
                raise ValueError('Guest route interface must be eth0..eth3.')
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
