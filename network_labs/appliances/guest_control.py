"""Bounded, typed guest operations over Firecracker's local vsock socket."""
import ipaddress
import socket
import time

OPERATIONS = {'ready': 'READY', 'addresses': 'ADDRESSES', 'routes': 'ROUTES', 'ping': 'PING', 'link': 'LINK'}


def request(path, operation, *, destination=None, interface=None, state=None, timeout=6):
    if operation not in OPERATIONS:
        raise ValueError('Unsupported guest operation.')
    command = OPERATIONS[operation]
    if operation == 'ping':
        command += ' ' + str(ipaddress.IPv4Address(destination))
    elif destination is not None:
        raise ValueError('Only ping accepts a destination.')
    if operation == 'link':
        if interface != 'eth0' or state not in ('up', 'down'):
            raise ValueError('Guest link requires interface eth0 and state up or down.')
        command += ' ' + interface + ' ' + state
    elif interface is not None or state is not None:
        raise ValueError('Only link accepts interface/state arguments.')
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
