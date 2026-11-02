"""One PAP RADIUS request; credentials arrive on stdin, never argv."""
import hashlib
import hmac
import json
import secrets
import socket
import struct
import sys
import time


def hide_password(password, secret, authenticator):
    padded = password + b'\0' * ((16 - len(password) % 16) % 16)
    previous = authenticator; encrypted = b''
    for offset in range(0, len(padded), 16):
        mask = hashlib.md5(secret + previous).digest()
        previous = bytes(a ^ b for a, b in zip(padded[offset:offset + 16], mask))
        encrypted += previous
    return encrypted


def access_request(request):
    secret = request['secret'].encode('ascii')
    authenticator = secrets.token_bytes(16); identifier = secrets.randbelow(256)
    def attribute(kind, value):
        return bytes((kind, len(value) + 2)) + value
    attributes = (attribute(80, b'\0' * 16) + attribute(1, request['username'].encode('ascii')) +
                  attribute(2, hide_password(request['password'].encode('utf-8'), secret, authenticator)) +
                  attribute(4, socket.inet_aton(request['source'])))
    packet = struct.pack('!BBH', 1, identifier, 20 + len(attributes)) + authenticator + attributes
    mac = hmac.digest(secret, packet, 'md5')
    return packet[:22] + mac + packet[38:]


def response_code(packet, request, secret):
    """Return a decision code only after both authenticators verify."""
    if not 20 <= len(packet) <= 4096:
        return None
    code, identifier, length = struct.unpack('!BBH', packet[:4])
    if code not in (2, 3, 11) or identifier != request[1] or length != len(packet):
        return None
    position = 20; mac_position = None
    while position < length:
        if position + 2 > length:
            return None
        kind, size = packet[position:position + 2]
        if kind == 0 or size < 2 or position + size > length:
            return None
        if kind == 80:
            if size != 18 or mac_position is not None:
                return None
            mac_position = position + 2
        position += size
    if mac_position is None:
        return None
    authenticator = request[4:20]
    expected = hashlib.md5(packet[:4] + authenticator + packet[20:] + secret).digest()
    if not hmac.compare_digest(expected, packet[4:20]):
        return None
    unsigned = (packet[:4] + authenticator + packet[20:mac_position] +
                b'\0' * 16 + packet[mac_position + 16:])
    expected_mac = hmac.digest(secret, unsigned, 'md5')
    if not hmac.compare_digest(expected_mac, packet[mac_position:mac_position + 16]):
        return None
    return code


def authenticate(request):
    result = {'status': 'unknown', 'decision': None, 'response_verified': False,
              'requests_sent': 0, 'discarded_responses': 0}
    deadline = time.monotonic() + request['timeout']
    try:
        packet = access_request(request); secret = request['secret'].encode('ascii')
        peer = (request['address'], request['port'])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((request['source'], 0)); sock.sendto(packet, peer)
            result['requests_sent'] = 1
            for _ in range(64):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                sock.settimeout(remaining)
                received, sender = sock.recvfrom(4097)
                code = response_code(received, packet, secret) if sender == peer else None
                if code is None:
                    result['discarded_responses'] += 1
                    continue
                result.update(response_verified=True, response_code=code,
                              decision={2: 'accepted', 3: 'rejected', 11: 'challenge'}[code],
                              status={2: 'passed', 3: 'failed', 11: 'blocked'}[code])
                return result
            result['error'] = 'PACKET_LIMIT'
    except TimeoutError:
        result['error'] = 'TIMEOUT'
    except OSError:
        result['error'] = 'TRANSPORT_ERROR'
    return result


if __name__ == '__main__':
    try:
        value = authenticate(json.loads(sys.stdin.read(4097)))
    except (ValueError, KeyError, TypeError, UnicodeError):
        value = {'status': 'unknown', 'error': 'INVALID_REQUEST'}
    print(json.dumps(value))
