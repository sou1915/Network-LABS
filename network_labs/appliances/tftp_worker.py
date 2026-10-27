"""Bounded TFTP octet-mode read; runs inside the source network namespace."""
import hashlib
import json
import socket
import struct
import sys
import time

MAX_BYTES = 65536


def read(request):
    result = {'status': 'unknown', 'bytes_received': 0, 'sha256': None}
    deadline = time.monotonic() + request['timeout']
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((request['source'], 0))
            sock.sendto(b'\x00\x01' + request['filename'].encode('ascii') + b'\x00octet\x00',
                        (request['address'], request['port']))
            peer = None; expected = 1; digest = hashlib.sha256()
            for _ in range(256):
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise TimeoutError('TFTP deadline reached')
                sock.settimeout(remaining)
                packet, sender = sock.recvfrom(517)
                if sender[0] != request['address'] or (peer is not None and sender != peer):
                    continue
                if len(packet) < 4: raise ValueError('Truncated TFTP packet')
                opcode, number = struct.unpack('!HH', packet[:4])
                if opcode == 5:
                    if len(packet) < 5 or not packet.endswith(b'\x00'):
                        raise ValueError('Malformed TFTP error')
                    result.update(status='failed', error='SERVER_ERROR', error_code=number)
                    return result
                if opcode != 3 or len(packet) > 516:
                    raise ValueError('Unsupported or oversized TFTP packet')
                if peer is None:
                    if number != 1: raise ValueError('First DATA block must be 1')
                    peer = sender
                if number == expected - 1:
                    sock.sendto(struct.pack('!HH', 4, number), peer)
                    continue
                if number != expected: raise ValueError('Unexpected TFTP block number')
                data = packet[4:]
                if result['bytes_received'] + len(data) > MAX_BYTES:
                    result.update(status='failed', error='SIZE_LIMIT')
                    return result
                digest.update(data); result['bytes_received'] += len(data)
                sock.sendto(struct.pack('!HH', 4, number), peer)
                if len(data) < 512:
                    result.update(status='passed', sha256=digest.hexdigest(), blocks=expected)
                    return result
                expected += 1
            result.update(status='failed', error='PACKET_LIMIT')
    except (TimeoutError, OSError) as error:
        result.update(status='failed', error=type(error).__name__, detail=str(error)[:300])
    except (ValueError, UnicodeError, struct.error) as error:
        result.update(status='unknown', error='INVALID_RESPONSE', detail=str(error)[:300])
    return result


if __name__ == '__main__':
    print(json.dumps(read(json.loads(sys.argv[1]))))
