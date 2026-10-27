"""One-shot educational NTP responder; executed in a managed network namespace."""
import json
import socket
import struct
import sys
import time


def timestamp(offset):
    seconds = time.time() + offset + 2208988800
    whole = int(seconds)
    return struct.pack('!II', whole % (1 << 32), int((seconds - whole) * (1 << 32)))


def serve(address, allowed, port=123, offset=0):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((address, port))
        sock.settimeout(8)
        print(json.dumps({'status': 'ready', 'port': sock.getsockname()[1]}), flush=True)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            sock.settimeout(max(.001, deadline - time.monotonic()))
            request, peer = sock.recvfrom(1024)
            if peer[0] != allowed or len(request) != 48 or request[0] & 7 != 3 or (request[0] >> 3) & 7 not in (3, 4):
                continue
            received = timestamp(offset)
            reply = bytearray(48)
            reply[0] = 0x24  # NTPv4 server, educational clock based on the host.
            reply[1] = 2  # Illustrative stratum, not an independently verified upstream.
            reply[12:16] = b'LAB\0'
            reply[24:32] = request[40:48]
            reply[32:40] = received
            reply[40:48] = timestamp(offset)
            sock.sendto(reply, peer)
            print(json.dumps({'status': 'responded'}), flush=True)
            return


if __name__ == '__main__':
    try:
        serve(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
    except (OSError, ValueError) as error:
        print(json.dumps({'status': 'error', 'detail': str(error)[:300]}), flush=True)
        sys.exit(1)
