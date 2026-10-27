"""Passive network-namespace observation of IPv4 UDP/123 socket bindings."""
import ipaddress
import re
import socket
import struct
import subprocess

from .runtime import RuntimeFailure


def parse_udp_table(text):
    lines = text.splitlines()
    if not lines or 'local_address' not in lines[0] or 'st' not in lines[0].split():
        raise ValueError('IPv4 UDP table header unavailable or malformed.')
    found = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 4 or not parts[0].endswith(':'):
            raise ValueError('Malformed IPv4 UDP table row.')
        local = parts[1].split(':')
        if (len(local) != 2 or not re.fullmatch(r'[0-9A-Fa-f]{8}', local[0]) or
                not re.fullmatch(r'[0-9A-Fa-f]{4}', local[1]) or not re.fullmatch(r'[0-9A-Fa-f]{2}', parts[3])):
            raise ValueError('Malformed IPv4 UDP local endpoint.')
        try:
            addr = str(ipaddress.IPv4Address(socket.inet_ntoa(struct.pack('=I', int(local[0], 16)))))
            port, state = int(local[1], 16), int(parts[3], 16)
        except (ValueError, OverflowError, struct.error) as error:
            raise ValueError('Invalid IPv4 UDP socket fields.') from error
        if port == 123:
            found.append({'address': addr, 'state': state})
    return found


def observe_socket(manager, node, address):
    evidence = {'status': 'unknown', 'address': address, 'port': 123, 'bindings': [], 'detail': None}
    try:
        index = next(i for i, n in enumerate(manager.read()['spec']['nodes']) if n['name'] == node['name'])
        result = manager.ns(index, 'cat', '/proc/net/udp', check=False, timeout=3)
        if result.returncode or len(result.stdout) > 1048576:
            raise ValueError('IPv4 UDP table unavailable or too large.')
        bindings = parse_udp_table(result.stdout)
        evidence.update(status='observed' if any(row['address'] == address and row['state'] == 7 for row in bindings) else 'absent',
                        bindings=bindings)
    except (OSError, RuntimeFailure, subprocess.TimeoutExpired, UnicodeError, ValueError, KeyError, TypeError, StopIteration) as error:
        evidence['detail'] = str(error)[:300]
    return evidence
