"""Standard-library wire probes, executed using host Python in an owned netns.

No host resolver, environment proxy, redirects, shell, or guest Python dependency.
"""
import ipaddress
from contextlib import ExitStack
import json
import re
import secrets
import socket
import ssl
import struct
import sys
import time

DNS_PORT = 53

NTP_EPOCH = 2208988800
NTP_ERA = 1 << 32


def ntp_encode(timestamp):
    seconds = timestamp + NTP_EPOCH
    whole = int(seconds)
    return struct.pack('!II', whole % NTP_ERA, int((seconds - whole) * NTP_ERA))


def ntp_decode(value, near):
    seconds, fraction = struct.unpack('!II', value)
    # Resolve the 32-bit era nearest the local receive time, including 2036.
    era = round((near + NTP_EPOCH - seconds) / NTP_ERA)
    return era * NTP_ERA + seconds + fraction / NTP_ERA - NTP_EPOCH


def sntp_response(packet, sent, t1, t4):
    if len(packet) != 48:
        raise ValueError('Expected a 48-byte unauthenticated NTP response')
    leap, version, mode = packet[0] >> 6, (packet[0] >> 3) & 7, packet[0] & 7
    stratum = packet[1]
    if leap == 3 or version not in (3, 4) or mode != 4 or not 1 <= stratum <= 15:
        raise ValueError('Unsynchronised or unsupported NTP server response')
    if packet[24:32] != sent or packet[32:40] == bytes(8) or packet[40:48] == bytes(8):
        raise ValueError('Unmatched or missing NTP timestamps')
    t2, t3 = ntp_decode(packet[32:40], t4), ntp_decode(packet[40:48], t4)
    if t3 < t2:
        raise ValueError('Server transmit precedes receive')
    return {'stratum': stratum, 'version': version, 'offset_seconds': ((t2 - t1) + (t3 - t4)) / 2,
            'round_trip_seconds': (t4 - t1) - (t3 - t2), 'server_unix_seconds': t3,
            'timestamps_unix_seconds': {'client_send': t1, 'server_receive': t2, 'server_send': t3, 'client_receive': t4}}


def dns_name(packet, offset):
    labels, seen, end = [], set(), None
    while True:
        if offset in seen or offset >= len(packet):
            raise ValueError('Invalid DNS name pointer')
        seen.add(offset)
        size = packet[offset]
        if size & 0xc0 == 0xc0:
            if offset + 1 >= len(packet):
                raise ValueError('Truncated DNS pointer')
            if end is None:
                end = offset + 2
            offset = ((size & 63) << 8) | packet[offset + 1]
            continue
        if size & 0xc0 or offset + 1 + size > len(packet):
            raise ValueError('Invalid DNS label')
        offset += 1
        if not size:
            return '.'.join(labels).lower(), end or offset
        labels.append(packet[offset:offset + size].decode('ascii'))
        if sum(map(len, labels)) + len(labels) > 254:
            raise ValueError('DNS name too long')
        offset += size


def dns_header(packet, ident, name):
    if len(packet) < 12: raise ValueError('Truncated DNS header')
    rid, flags, qd, an, ns, ar = struct.unpack('!6H', packet[:12])
    if rid != ident or not flags & 0x8000 or flags & 0x7800 or qd != 1:
        raise ValueError('Unmatched DNS response')
    question, pos = dns_name(packet, 12)
    if question != name or packet[pos:pos + 4] != b'\x00\x01\x00\x01':
        raise ValueError('Unmatched DNS question')
    return flags, an, ns, ar, pos + 4


def dns_answers(packet, ident, name):
    flags, answers, authority, additional, pos = dns_header(packet, ident, name)
    if flags & 0x0200: raise ValueError('Truncated DNS response; no complete answer')
    addresses = []
    for index in range(answers + authority + additional):
        owner, pos = dns_name(packet, pos)
        if pos + 10 > len(packet): raise ValueError('Truncated DNS record')
        kind, cls, ttl, size = struct.unpack('!HHIH', packet[pos:pos + 10]); pos += 10
        if pos + size > len(packet): raise ValueError('Truncated DNS data')
        if index < answers and owner == name and kind == cls == 1:
            if size != 4: raise ValueError('Invalid IPv4 A record size')
            addresses.append(str(ipaddress.IPv4Address(packet[pos:pos + 4])))
        pos += size
    if pos != len(packet): raise ValueError('Trailing DNS data outside declared sections')
    return flags & 15, sorted(set(addresses))


def dns_exchange(request, bounded, result):
    transport = request.get('transport', 'udp')
    if transport not in ('udp', 'tcp', 'auto'): raise ValueError('Unsupported DNS transport')
    ident = secrets.randbelow(65536); name = request['target']
    wire = b''.join(bytes([len(label)]) + label.encode('ascii') for label in name.split('.')) + b'\x00'
    query = struct.pack('!6H', ident, 0x0100, 1, 0, 0, 0) + wire + b'\x00\x01\x00\x01'
    result.update(attempts=[], fallback=False)
    def exchange(mode):
        attempt = {'transport': mode, 'response_received': False}; result['attempts'].append(attempt)
        result['transport'] = mode
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if mode == 'udp' else socket.SOCK_STREAM) as channel:
            channel.bind((request['source'], 0)); bounded(channel); channel.connect((request['server'], DNS_PORT))
            bounded(channel)
            if mode == 'udp':
                channel.send(query); bounded(channel); packet = channel.recv(4097)
                if len(packet) > 4096: raise ValueError('DNS response exceeds 4096-byte probe budget')
            else:
                channel.sendall(struct.pack('!H', len(query)) + query)
                def exact(size):
                    data = b''
                    while len(data) < size:
                        bounded(channel); part = channel.recv(size - len(data))
                        if not part: raise ValueError('Short DNS TCP frame')
                        data += part
                    return data
                size = struct.unpack('!H', exact(2))[0]
                if not 12 <= size <= 4096: raise ValueError('DNS TCP frame outside 12..4096-byte probe budget')
                packet = exact(size)
            flags, *_ = dns_header(packet, ident, name)
            attempt.update(response_received=True, truncated=bool(flags & 0x0200))
            return packet, flags
    packet, flags = exchange('tcp' if transport == 'tcp' else 'udp')
    if transport == 'auto' and flags & 0x0200:
        result['fallback'] = True
        packet, flags = exchange('tcp')
    code, addresses = dns_answers(packet, ident, name)
    result.update(status='passed' if code == 0 and addresses else 'failed', rcode=code, addresses=addresses,
                  detail='Direct A response; CNAME chains are not followed')


def run_probe(request):
    """Every operation has a deadline; no response bodies are downloaded."""
    stage = request['stage']
    result = {'stage': stage, 'status': 'unknown'}
    deadline = time.monotonic() + request['timeout']
    def bounded(sock):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Probe deadline reached')
        sock.settimeout(remaining)
    try:
        with ExitStack() as resources:
            if stage == 'dns':
                dns_exchange(request, bounded, result)
                return result
            sock = resources.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM if stage == 'sntp' else socket.SOCK_STREAM))
            sock.bind((request['source'], 0))
            bounded(sock)
            if stage == 'sntp':
                sock.connect((request['address'], 123))
                t1 = time.time(); monotonic_start = time.monotonic(); sent = ntp_encode(t1)
                sock.send(b'\x23' + bytes(39) + sent)
                bounded(sock)
                packet = sock.recv(1024); t4 = time.time(); monotonic_end = time.monotonic()
                if abs((t4 - t1) - (monotonic_end - monotonic_start)) > 0.1:
                    raise ValueError('Local wall clock changed during observation')
                result.update(status='passed', **sntp_response(packet, sent, t1, t4))
            else:
                sock.connect((request['address'], request['port']))
                result.update(status='passed', connected=True)
                if stage in ('http', 'https'):
                    result['status'] = 'unknown'
                    if stage == 'https':
                        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                        context.minimum_version = ssl.TLSVersion.TLSv1_2
                        context.load_verify_locations(cadata=request['ca_pem'])
                        bounded(sock)
                        sock = resources.enter_context(context.wrap_socket(sock, server_hostname=request['target']))
                        result.update(certificate_verified=True, tls_version=sock.version(), cipher=sock.cipher()[0])
                    default_port = 443 if stage == 'https' else 80
                    host = request['target'] + (':' + str(request['port']) if request['port'] != default_port else '')
                    bounded(sock)
                    sock.sendall(('HEAD ' + request['path'] + ' HTTP/1.0\r\nHost: ' + host + '\r\nConnection: close\r\n\r\n').encode('ascii'))
                    line = b''
                    while b'\r\n' not in line and len(line) < 4096:
                        bounded(sock)
                        part = sock.recv(min(512, 4096 - len(line)))
                        if not part:
                            break
                        line += part
                    first = line.split(b'\r\n', 1)[0]
                    match = re.fullmatch(rb'HTTP/1\.[01] ([1-5][0-9]{2})(?: [\x20-\x7e]*)?', first)
                    if b'\r\n' not in line or not match:
                        raise ValueError('Missing or unsupported HTTP/1.x status line')
                    code = int(match[1])
                    result.update(status='passed' if 200 <= code < 300 else 'failed', http_status=code,
                                  detail='HEAD response; redirects are not followed')
    except ssl.SSLCertVerificationError as error:
        result.update(status='failed', certificate_verified=False, error='CERTIFICATE_VERIFY_FAILED', detail=str(error)[:300])
    except (TimeoutError, ConnectionError, OSError) as error:
        result.update(status='failed', error=type(error).__name__, errno=getattr(error, 'errno', None), detail=str(error)[:300])
    except (ValueError, UnicodeError, struct.error) as error:
        result.update(status='unknown', error='INVALID_RESPONSE', detail=str(error)[:300])
    return result


if __name__ == '__main__':
    print(json.dumps(run_probe(json.loads(sys.argv[1]))))
