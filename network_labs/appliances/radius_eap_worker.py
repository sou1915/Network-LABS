"""Two-request EAP-MD5 over RADIUS diagnostic, with bounded verified continuation."""
import hashlib
import hmac
import json
import secrets
import socket
import struct
import sys
import time
from network_labs.appliances.radius_worker import response_code


def attribute(kind, value):
    if not 1 <= len(value) <= 253: raise ValueError('Attribute bounds')
    return bytes((kind, len(value) + 2)) + value


def access_request(request, eap, state=None, previous_id=None):
    identifier = secrets.randbelow(256)
    if identifier == previous_id: identifier = (identifier + 1) % 256
    authenticator = secrets.token_bytes(16)
    attributes = attribute(80, bytes(16)) + attribute(1, request['username'].encode('ascii'))
    attributes += attribute(4, socket.inet_aton(request['source'])) + attribute(79, eap)
    if state is not None: attributes += attribute(24, state)
    packet = struct.pack('!BBH', 1, identifier, 20 + len(attributes)) + authenticator + attributes
    mac = hmac.digest(request['secret'].encode('ascii'), packet, 'md5')
    return packet[:22] + mac + packet[38:]


def eap_packet(code, identifier, payload=b''):
    return struct.pack('!BBH', code, identifier, 4 + len(payload)) + payload


def inner(packet):
    """Parse only already-authenticated RADIUS attributes; expose no raw data."""
    eap = bytearray(); states = []; offset = 20; eap_started = eap_ended = False
    while offset < len(packet):
        kind, size = packet[offset:offset+2]; value = packet[offset+2:offset+size]; offset += size
        if kind == 79:
            if eap_ended: raise ValueError('Nonconsecutive EAP fragments')
            eap_started = True; eap.extend(value)
        else:
            if eap_started: eap_ended = True
            if kind == 24: states.append(value)
    if not 4 <= len(eap) <= 1024 or int.from_bytes(eap[2:4], 'big') != len(eap): raise ValueError('EAP length')
    if len(states) > 1 or any(not value for value in states): raise ValueError('State bounds')
    return bytes(eap), states[0] if states else None


def authenticate(request):
    result = {'status':'unknown', 'decision':None, 'response_verified':False,
              'challenge_verified':False, 'requests_sent':0, 'discarded_responses':0}
    deadline = time.monotonic() + request['timeout']
    eap_id = secrets.randbelow(256)
    eap = eap_packet(2, eap_id, b'\x01' + request['username'].encode('ascii'))
    state = None; previous_id = None
    try:
        peer = (request['address'], request['port']); secret = request['secret'].encode('ascii')
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((request['source'], 0))
            for stage in range(2):
                if time.monotonic() >= deadline: raise TimeoutError
                packet = access_request(request, eap, state, previous_id); previous_id = packet[1]
                sock.sendto(packet, peer); result['requests_sent'] += 1
                while True:
                    if result['discarded_responses'] >= 64:
                        return {**result, 'error':'PACKET_LIMIT'}
                    remaining = deadline - time.monotonic()
                    if remaining <= 0: raise TimeoutError
                    sock.settimeout(remaining); received, sender = sock.recvfrom(4097)
                    code = response_code(received, packet, secret) if sender == peer else None
                    if code is None:
                        result['discarded_responses'] += 1; continue
                    received_eap, received_state = inner(received)
                    if code == 3:
                        if received_eap != eap_packet(4, eap_id) or received_state is not None: raise ValueError('EAP reject mismatch')
                        return {**result, 'status':'failed', 'decision':'rejected', 'response_verified':True, 'response_code':3}
                    if stage == 1:
                        if code != 2 or received_eap != eap_packet(3, eap_id) or received_state is not None: raise ValueError('EAP terminal mismatch')
                        return {**result, 'status':'passed', 'decision':'accepted', 'response_verified':True, 'response_code':2}
                    # Exactly one verified 16-byte MD5 request and opaque State.
                    if (code != 11 or len(received_eap) < 22 or received_eap[0] != 1
                            or received_eap[4:6] != b'\x04\x10' or received_state is None):
                        raise ValueError('Unsupported challenge')
                    eap_id = received_eap[1]; challenge = received_eap[6:22]; state = received_state
                    proof = hashlib.md5(bytes([eap_id]) + request['password'].encode('utf-8') + challenge).digest()
                    eap = eap_packet(2, eap_id, b'\x04\x10' + proof + request['username'].encode('ascii'))
                    result['challenge_verified'] = True
                    break
    except TimeoutError: result['error'] = 'TIMEOUT'
    except OSError: result['error'] = 'TRANSPORT_ERROR'
    except (ValueError, IndexError, struct.error): result['error'] = 'PROTOCOL_ERROR'
    return result


def main():
    try: result = authenticate(json.loads(sys.stdin.read(4097)))
    except (ValueError, KeyError, TypeError, UnicodeError): result = {'status':'unknown','error':'INVALID_REQUEST'}
    print(json.dumps(result))


if __name__ == '__main__': main()
