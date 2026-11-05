"""Passive network-namespace observation of IPv4/IPv6 UDP socket bindings."""
import ipaddress
import re
import socket
import struct
import subprocess

from .runtime import RuntimeFailure


def parse_udp_table(text, port=123, family='ipv4'):
    if family not in ('ipv4','ipv6'):raise ValueError('UDP table family must be ipv4 or ipv6.')
    lines = text.splitlines()
    if not lines or 'local_address' not in lines[0] or 'st' not in lines[0].split():
        raise ValueError('UDP table header unavailable or malformed.')
    found = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 4 or not parts[0].endswith(':'):
            raise ValueError('Malformed UDP table row.')
        local = parts[1].split(':')
        if (len(local) != 2 or not re.fullmatch(r'[0-9A-Fa-f]{32}' if family=='ipv6' else r'[0-9A-Fa-f]{8}', local[0]) or
                not re.fullmatch(r'[0-9A-Fa-f]{4}', local[1]) or not re.fullmatch(r'[0-9A-Fa-f]{2}', parts[3])):
            raise ValueError('Malformed UDP local endpoint.')
        try:
            if family=='ipv6':
                addr=str(ipaddress.IPv6Address(b''.join(struct.pack('=I',int(local[0][offset:offset+8],16)) for offset in range(0,32,8))))
            else:addr = str(ipaddress.IPv4Address(socket.inet_ntoa(struct.pack('=I', int(local[0], 16)))))
            observed_port, state = int(local[1], 16), int(parts[3], 16)
        except (ValueError, OverflowError, struct.error) as error:
            raise ValueError('Invalid UDP socket fields.') from error
        if observed_port == port:
            found.append({'address': addr, 'state': state})
    return found


def observe_socket(manager, node, address, port=123):
    evidence = {'status': 'unknown', 'address': address, 'port': port, 'bindings': [], 'detail': None}
    try:
        index = next(i for i, n in enumerate(manager.read()['spec']['nodes']) if n['name'] == node['name'])
        family='ipv6' if ipaddress.ip_address(address).version==6 else 'ipv4'
        result = manager.ns(index, 'cat', '/proc/net/udp6' if family=='ipv6' else '/proc/net/udp', check=False, timeout=3)
        if result.returncode or len(result.stdout) > 1048576:
            raise ValueError('UDP table unavailable or too large.')
        bindings = parse_udp_table(result.stdout, port,family=family)
        evidence.update(status='observed' if any(row['address'] == address and row['state'] == 7 for row in bindings) else 'absent',
                        bindings=bindings)
    except (OSError, RuntimeFailure, subprocess.TimeoutExpired, UnicodeError, ValueError, KeyError, TypeError, StopIteration) as error:
        evidence['detail'] = str(error)[:300]
    return evidence
