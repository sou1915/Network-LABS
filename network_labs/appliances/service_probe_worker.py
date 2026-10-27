"""Standard-library wire probes, executed using host Python in an owned netns.

No host resolver, environment proxy, redirects, shell, or guest Python dependency.
"""
import ipaddress
import json
import re
import secrets
import socket
import struct
import sys
import time

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
            'round_trip_seconds': (t4 - t1) - (t3 - t2), 'server_unix_seconds': t3}


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


def dns_answers(packet, ident, name):
    if len(packet) < 12:
        raise ValueError('Truncated DNS header')
    rid, flags, qd, an, _, _ = struct.unpack('!6H', packet[:12])
    if rid != ident or not flags & 0x8000 or flags & 0x7800 or qd != 1:
        raise ValueError('Unmatched DNS response')
    if flags & 0x0200:
        raise ValueError('Truncated response; TCP DNS is not supported by this probe')
    question, pos = dns_name(packet, 12)
    if question != name or packet[pos:pos + 4] != b'\x00\x01\x00\x01':
        raise ValueError('Unmatched DNS question')
    pos += 4
    addresses = []
    for _ in range(an):
        owner, pos = dns_name(packet, pos)
        if pos + 10 > len(packet):
            raise ValueError('Truncated DNS record')
        kind, cls, ttl, size = struct.unpack('!HHIH', packet[pos:pos + 10]); pos += 10
        if pos + size > len(packet):
            raise ValueError('Truncated DNS data')
        if owner == name and kind == cls == 1 and size == 4:
            addresses.append(str(ipaddress.IPv4Address(packet[pos:pos + 4])))
        pos += size
    return flags & 15, sorted(set(addresses))


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
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if stage in ('dns', 'sntp') else socket.SOCK_STREAM) as sock:
            sock.bind((request['source'], 0))
            bounded(sock)
            if stage == 'dns':
                ident = secrets.randbelow(65536)
                name = request['target']
                wire = b''.join(bytes([len(label)]) + label.encode('ascii') for label in name.split('.')) + b'\x00'
                packet = struct.pack('!6H', ident, 0x0100, 1, 0, 0, 0) + wire + b'\x00\x01\x00\x01'
                sock.connect((request['server'], 53)); sock.send(packet)
                bounded(sock)
                code, addresses = dns_answers(sock.recv(4096), ident, name)
                result.update(status='passed' if code == 0 and addresses else 'failed', rcode=code, addresses=addresses,
                              detail='A response' if addresses else 'No direct A answer; CNAME chains are not followed')
            elif stage == 'sntp':
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
                if stage == 'http':
                    result['status'] = 'unknown'
                    host = request['target'] + (':' + str(request['port']) if request['port'] != 80 else '')
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
    except (TimeoutError, ConnectionError, OSError) as error:
        result.update(status='failed', error=type(error).__name__, errno=getattr(error, 'errno', None), detail=str(error)[:300])
    except (ValueError, UnicodeError, struct.error) as error:
        result.update(status='unknown', error='INVALID_RESPONSE', detail=str(error)[:300])
    return result


if __name__ == '__main__':
    print(json.dumps(run_probe(json.loads(sys.argv[1]))))
