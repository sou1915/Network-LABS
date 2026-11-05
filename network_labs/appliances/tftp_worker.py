"""Bounded TFTP octet-mode read; runs inside the source network namespace."""
import hashlib
import json
import socket
import struct
import sys
import time

MAX_BYTES = 65536
RETRY_SECONDS = 0.5
MAX_RETRIES = 3
DALLY_SECONDS = 1.0


def dally(sock, peer, final_packet, ack, deadline, received):
    """Re-ACK an identical final DATA; never extend either time/packet budget."""
    evidence = {'status': 'elapsed', 'duplicate_acks': 0}
    end = min(deadline, time.monotonic() + DALLY_SECONDS)
    while received < 256:
        remaining = end - time.monotonic()
        if remaining <= 0:
            evidence['status'] = 'deadline' if time.monotonic() >= deadline else 'elapsed'
            return evidence
        try:
            sock.settimeout(remaining)
            packet, sender = sock.recvfrom(1433)
            received += 1
            if sender == peer and packet == final_packet:
                sock.sendto(ack, peer)
                evidence['duplicate_acks'] += 1
        except socket.timeout:
            continue
        except OSError:
            # Content and the first final ACK were already processed. Preserve
            # that local read result, while exposing incomplete dally evidence.
            evidence['status'] = 'socket_error'
            return evidence
    evidence['status'] = 'packet_limit'
    return evidence


def read(request):
    result = {'status': 'unknown', 'bytes_received': 0, 'sha256': None, 'retransmissions': 0}
    deadline = time.monotonic() + request['timeout']
    try:
        family=socket.AF_INET6 if request.get('family','ipv4')=='ipv6' else socket.AF_INET
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            if family==socket.AF_INET6:sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
            sock.bind((request['source'], 0))
            pending = b'\x00\x01' + request['filename'].encode('ascii') + b'\x00octet\x00'
            destination = (request['address'], request['port'])
            requested = request.get('block_size')
            if requested is not None:
                if type(requested) is not int or not 512 <= requested <= 1428:
                    raise ValueError('Requested block size outside 512..1428')
                pending += b'blksize\x00' + str(requested).encode('ascii') + b'\x00'
            result.update(block_size=512, option_negotiated=False)
            sock.sendto(pending, destination)
            retries = 0; retry_at = time.monotonic() + RETRY_SECONDS; received = 0
            peer = None; expected = 1; oack = None; last_data = None; digest = hashlib.sha256()
            while received < 256:
                now = time.monotonic()
                if now >= deadline: raise TimeoutError('TFTP deadline reached')
                if now >= retry_at:
                    if retries >= MAX_RETRIES:
                        result.update(status='failed', error='RETRY_LIMIT')
                        return result
                    sock.sendto(pending, destination)
                    retries += 1; result['retransmissions'] += 1
                    retry_at = time.monotonic() + RETRY_SECONDS * (2 ** retries)
                    continue
                sock.settimeout(min(deadline, retry_at) - now)
                try:
                    packet, sender = sock.recvfrom(1433)
                except socket.timeout:
                    continue
                received += 1
                if sender[0] != request['address'] or (peer is not None and sender != peer):
                    continue
                if len(packet) < 4: raise ValueError('Truncated TFTP packet')
                opcode, number = struct.unpack('!HH', packet[:4])
                if opcode == 5:
                    if len(packet) < 5 or not packet.endswith(b'\x00'):
                        raise ValueError('Malformed TFTP error')
                    result.update(status='failed', error='SERVER_ERROR', error_code=number)
                    return result
                if opcode == 6:
                    parts = packet[2:].split(b'\x00')
                    valid = (requested is not None and last_data is None and len(parts) == 3 and
                             parts[0].lower() == b'blksize' and parts[2] == b'' and
                             1 <= len(parts[1]) <= 4 and parts[1].isdigit() and
                             512 <= int(parts[1]) <= requested and (oack is None or packet == oack))
                    if not valid:
                        sock.sendto(struct.pack('!HH', 5, 8) + b'Invalid option negotiation\x00', sender)
                        raise ValueError('Invalid or changed TFTP OACK')
                    if oack is None:
                        oack = packet; peer = sender; destination = peer
                        result.update(block_size=int(parts[1]), option_negotiated=True)
                        pending = struct.pack('!HH', 4, 0)
                        retries = 0; retry_at = time.monotonic() + RETRY_SECONDS
                    sock.sendto(pending, peer)
                    continue
                if opcode != 3 or len(packet) > result['block_size'] + 4:
                    raise ValueError('Unsupported or oversized TFTP packet')
                if peer is None:
                    if number != 1: raise ValueError('First DATA block must be 1')
                    peer = sender
                if number == expected - 1:
                    if packet != last_data: raise ValueError('Changed duplicate TFTP DATA')
                    sock.sendto(struct.pack('!HH', 4, number), peer)
                    continue
                if number != expected: raise ValueError('Unexpected TFTP block number')
                data = packet[4:]
                if result['bytes_received'] + len(data) > MAX_BYTES:
                    result.update(status='failed', error='SIZE_LIMIT')
                    return result
                last_data = packet
                digest.update(data); result['bytes_received'] += len(data)
                pending = struct.pack('!HH', 4, number); destination = peer
                sock.sendto(pending, destination)
                if len(data) < result['block_size']:
                    result.update(status='passed', sha256=digest.hexdigest(), blocks=expected)
                    result['final_ack'] = dally(sock, peer, packet, pending, deadline, received)
                    return result
                expected += 1
                # Only a new block advances the transfer. Unrelated traffic
                # and duplicate DATA must not postpone retries or the deadline.
                retries = 0; retry_at = time.monotonic() + RETRY_SECONDS
            result.update(status='failed', error='PACKET_LIMIT')
    except (TimeoutError, OSError) as error:
        result.update(status='failed', error=type(error).__name__, detail=str(error)[:300])
    except (ValueError, UnicodeError, struct.error) as error:
        result.update(status='unknown', error='INVALID_RESPONSE', detail=str(error)[:300])
    return result


if __name__ == '__main__':
    print(json.dumps(read(json.loads(sys.argv[1]))))
