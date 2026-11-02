"""One bounded RFC 2866 exchange with opt-in finite retries; secret on stdin."""
import hashlib
import hmac
import json
import secrets
import socket
import struct
import sys
import time


def accounting_request(request, *, identifier=None, delay_seconds=0):
    def attribute(kind, value): return bytes((kind, len(value) + 2)) + value
    def number(kind, value): return attribute(kind, struct.pack('!I', value))
    attrs = (attribute(1, request['username'].encode('ascii')) +
             attribute(4, socket.inet_aton(request['source'])) + number(40, 1 if request['event'] == 'start' else 2) +
             number(41, delay_seconds) + attribute(44, request['session_id'].encode('ascii')) + number(45, 1))
    if request['event'] == 'stop':
        attrs += number(46, request['session_seconds']) + number(49, request['terminate_cause'])
    header = struct.pack('!BBH', 4, secrets.randbelow(256) if identifier is None else identifier, 20 + len(attrs))
    authenticator = hashlib.md5(header + b'\0' * 16 + attrs + request['secret'].encode('ascii')).digest()
    return header + authenticator + attrs


def verified_response(packet, request, secret):
    if not 20 <= len(packet) <= 4096: return False
    code, identifier, size = struct.unpack('!BBH', packet[:4])
    if code != 5 or identifier != request[1] or size != len(packet): return False
    position = 20
    while position < size:
        if position + 2 > size: return False
        kind, length = packet[position:position + 2]
        if kind == 0 or length < 2 or position + length > size: return False
        position += length
    expected = hashlib.md5(packet[:4] + request[4:20] + packet[20:] + secret).digest()
    return hmac.compare_digest(packet[4:20], expected)


def account(request):
    result = {'status': 'unknown', 'response_verified': False, 'requests_sent': 0,
              'discarded_responses': 0, 'response_code': None, 'error': None}
    started = time.monotonic(); deadline = started + request['timeout']
    maximum = request.get('retries', 0)
    if type(maximum) is not int or not 0 <= maximum <= 2: raise ValueError('Accounting retries must be 0..2')
    try:
        delay = request.get('delay_seconds', 0)
        if type(delay) is not int or not 0 <= delay <= 0xffffffff: raise ValueError('Invalid initial accounting delay')
        base_delay = delay
        packet = accounting_request(request, delay_seconds=delay); packets = [packet]
        initial_id = packet[1]; peer = (request['address'], request['port'])
        interval = request['timeout'] / (2 ** (maximum + 1) - 1)
        retry_at = started + interval
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((request['source'], 0))
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise TimeoutError
            sock.settimeout(remaining); sock.sendto(packet, peer)
            result['requests_sent'] = 1
            while result['discarded_responses'] < 64:
                now = time.monotonic()
                if now >= deadline: raise TimeoutError
                if now >= retry_at and result['requests_sent'] <= maximum:
                    current_delay = min(0xffffffff, base_delay + int(max(0, now - started)))
                    if current_delay != delay:
                        delay = current_delay
                        packet = accounting_request(request, identifier=(initial_id + result['requests_sent']) % 256,
                                                    delay_seconds=delay)
                        packets.append(packet)
                    sock.sendto(packet, peer); result['requests_sent'] += 1
                    interval *= 2; retry_at = min(deadline, time.monotonic() + interval)
                    continue
                sock.settimeout(min(deadline, retry_at) - now if result['requests_sent'] <= maximum else deadline - now)
                try: received, sender = sock.recvfrom(4097)
                except socket.timeout: continue
                if sender != peer or not any(verified_response(received, sent, request['secret'].encode('ascii')) for sent in packets):
                    result['discarded_responses'] += 1; continue
                result.update(status='passed', response_verified=True, response_code=5)
                return result
            result['error'] = 'PACKET_LIMIT'
    except TimeoutError: result['error'] = 'TIMEOUT'
    except OSError: result['error'] = 'TRANSPORT_ERROR'
    return result


if __name__ == '__main__':
    try: result = account(json.loads(sys.stdin.read(4097)))
    except (ValueError, KeyError, TypeError, UnicodeError): result = {'status': 'unknown', 'error': 'INVALID_REQUEST'}
    print(json.dumps(result))
