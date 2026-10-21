"""Bounded real UDP multicast probes in a descriptor-pinned owned namespace."""
import ipaddress
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .runtime import RuntimeFailure
from .spec import integer, namespace
from .capture import NETNS_ROOT, _finish


def validate_probe(group, port, seconds, count, text):
    address = ipaddress.IPv4Address(group)
    if address not in ipaddress.IPv4Network('239.0.0.0/8'):
        raise ValueError('Multicast probes require an administratively scoped IPv4 group in 239.0.0.0/8.')
    integer(port, 1024, 65535, 'UDP port')
    integer(seconds, 1, 30, 'Multicast probe seconds')
    integer(count, 1, 100, 'Multicast send count')
    if text is not None and (not isinstance(text, str) or not 1 <= len(text.encode('utf-8')) <= 1200):
        raise ValueError('Multicast payload must contain 1..1200 UTF-8 bytes.')
    return str(address)


def worker(config):
    group, port, interface, local = (config[k] for k in ('group', 'port', 'interface', 'local'))
    group = validate_probe(group, port, config['seconds'], config['count'], config['text'])
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode() + b'\0')
        if config['text'] is None:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IP, 49, 0)  # Linux IP_MULTICAST_ALL=0.
            sock.bind(('', port))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                            socket.inet_aton(group) + socket.inet_aton(local))
        else:
            sock.bind((local, 0))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
        print(json.dumps({'ready': True}), flush=True)
        started = time.monotonic(); received = 0; samples = []
        if config['text'] is None:
            deadline = started + config['seconds']
            while received < 1000:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(remaining)
                try:
                    packet, peer = sock.recvfrom(1401)
                except socket.timeout:
                    break
                received += 1
                if len(samples) < 8:
                    samples.append({'source': peer[0], 'source_port': peer[1], 'bytes_read': len(packet),
                                    'may_be_truncated': len(packet) == 1401, 'first_64_bytes_hex': packet[:64].hex()})
            result = {'received_packets': received, 'samples': samples, 'packet_limit': 1000}
        else:
            payload = config['text'].encode('utf-8')
            for i in range(config['count']):
                sock.sendto(payload, (group, port))
                if i + 1 < config['count']:
                    time.sleep(0.01)
            result = {'sent_packets': config['count'], 'payload_bytes': len(payload), 'ttl': 1}
        print(json.dumps({**result, 'duration_seconds': round(time.monotonic() - started, 3)}), flush=True)
    # Closing the last membership socket sends the real IGMP leave.


def probe(manager, name, interface='eth0', *, group='239.10.10.10', port=5000, seconds=10, count=3, text=None, ready=None):
    group = validate_probe(group, port, seconds, count, text)
    nsenter, watchdog = (shutil.which(tool) for tool in ('nsenter', 'timeout'))
    if not nsenter or not watchdog:
        raise RuntimeFailure('Multicast probes require host nsenter and GNU timeout; no host-network fallback.')
    process = None
    with tempfile.TemporaryFile('w+b') as output, tempfile.TemporaryFile('w+b') as error:
        try:
            with manager.locked():
                state = manager.read()
                if state['phase'] != 'running':
                    raise RuntimeFailure('Multicast probe requires a running lab.')
                match = next(((i, n) for i, n in enumerate(state['spec']['nodes']) if n['name'] == name), None)
                if match is None or match[1]['runtime'] != 'oci':
                    raise ValueError('Multicast probe requires an existing OCI node.')
                index, node = match
                from .lan import addresses
                if interface not in addresses(node):
                    raise ValueError('Multicast probe interface must belong to the node.')
                status = manager.crun('state', name, check=False)
                if status.returncode or json.loads(status.stdout).get('status') != 'running':
                    raise RuntimeFailure('Multicast probe requires a running container.')
                actual = json.loads(manager.ns(index, 'ip', '-j', '-4', 'addr', 'show', 'dev', interface).stdout)
                local = next((a['local'] for r in actual for a in r.get('addr_info', []) if a.get('scope') == 'global'), None)
                if local is None:
                    raise RuntimeFailure('Multicast probe requires an actual IPv4 address on its interface.')
                config = {'group': group, 'port': port, 'interface': interface, 'local': local,
                          'seconds': seconds, 'count': count, 'text': text}
                nsname = namespace(state['spec'], index)
                with (NETNS_ROOT / nsname).open('rb') as netns:
                    command = [watchdog, '--signal=TERM', '--kill-after=2s', str(seconds + 3) + 's',
                               nsenter, '--net=/proc/self/fd/' + str(netns.fileno()), '--', sys.executable,
                               '-m', 'network_labs.appliances.multicast_probe', json.dumps(config)]
                    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=error,
                                               pass_fds=(netns.fileno(),), start_new_session=True)
            # The namespace is pinned, but the lab lock is released throughout
            # joining/receiving. Concurrent send, inspect/configure/stop work.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if b'"ready": true' in os.pread(output.fileno(), 512, 0):
                    if ready:
                        ready()
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.02)
            process.communicate(timeout=seconds + 6)
            if process.returncode:
                raise RuntimeFailure('Multicast worker failed: ' + os.pread(error.fileno(), 4096, 0).decode(errors='replace'))
            lines = os.pread(output.fileno(), 8192, 0).decode().splitlines()
            if len(lines) != 2 or json.loads(lines[0]).get('ready') is not True:
                raise RuntimeFailure('Multicast worker returned incomplete observations.')
            return {'lab': manager.name, 'node': name, 'interface': interface, 'namespace': nsname,
                    'group': group, 'port': port, **json.loads(lines[-1]),
                    'source': 'Actual UDP socket in pinned node network namespace; host Python helper outside OCI cgroup',
                    'note': 'Send success is not delivery proof. Receive counts describe this socket/time window; no zero-loss or current-generation claim after a concurrent stop/restore.'}
        finally:
            if process is not None and process.poll() is None:
                _finish(process)


if __name__ == '__main__':
    worker(json.loads(sys.argv[1]))
