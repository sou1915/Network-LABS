"""Bounded, typed guest operations over Firecracker's local vsock socket."""
import ipaddress
import socket
import time

OPERATIONS = {'ready': 'READY', 'addresses': 'ADDRESSES', 'routes': 'ROUTES', 'ping': 'PING', 'link': 'LINK', 'address-add': 'ADDR_ADD', 'address-delete': 'ADDR_DEL', 'route-add': 'ROUTE_ADD', 'route-delete': 'ROUTE_DEL', 'forwarding': 'FORWARDING', 'forward': 'FORWARD'}


def request(path, operation, *, destination=None, interface=None, state=None, cidr=None, network=None, gateway=None, timeout=6):
    if operation not in OPERATIONS:
        raise ValueError('Unsupported guest operation.')
    command = OPERATIONS[operation]
    if operation == 'ping':
        command += ' ' + str(ipaddress.IPv4Address(destination))
    elif destination is not None:
        raise ValueError('Only ping accepts a destination.')
    if operation == 'link':
        if interface not in ('eth0', 'eth1', 'eth2', 'eth3') or state not in ('up', 'down'):
            raise ValueError('Guest link requires interface eth0..eth3 and state up or down.')
        command += ' ' + interface + ' ' + state
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
