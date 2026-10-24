"""Owned passive DHCP observer. Kernel filtering continues if observation fails."""
import ctypes
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import socket
import struct
import sys
import subprocess
import time

from .snooping_packets import Bindings


def attach_filter(sock):
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte), ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint32)]
    class Program(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ushort), ('instructions', ctypes.POINTER(Filter))]
    # Ethernet IPv4 UDP, no fragments, both ports in {67,68}. No promiscuity.
    rows = [(0x28, 0, 0, 12), (0x15, 0, 12, 0x0800),
            (0x30, 0, 0, 23), (0x15, 0, 10, 17), (0x28, 0, 0, 20), (0x45, 8, 0, 0x3fff),
            (0xb1, 0, 0, 14), (0x48, 0, 0, 14), (0x15, 1, 0, 67), (0x15, 0, 4, 68),
            (0x48, 0, 0, 16), (0x15, 1, 0, 67), (0x15, 0, 1, 68), (0x06, 0, 0, 2048), (0x06, 0, 0, 0)]
    instructions = (Filter * len(rows))(*(Filter(*r) for r in rows))
    program = Program(len(rows), instructions)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.setsockopt(sock.fileno(), socket.SOL_SOCKET, 26, ctypes.byref(program), ctypes.sizeof(program)):
        raise OSError(ctypes.get_errno(), 'SO_ATTACH_FILTER failed')


def serve(config):
    running = True
    def stop(*unused):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    target = Path(config['output'])
    table = Bindings(config['ports'], config['trusted'])
    started = time.monotonic()
    drops, packets = 0, 0
    identity = {p: socket.if_nametoindex(p) for p in config['ports']}
    error = None
    arp_status = None
    guard_status = None
    def publish(status):
        value = {'version': 1, 'token': config['token'], 'pid': os.getpid(), 'status': status,
                 'observed_monotonic': time.monotonic(), 'capture_packets': packets,
                 'capture_drops': drops, 'error': error, 'arp_inspection': arp_status, 'ip_source_guard': guard_status, **table.snapshot()}
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(value)); temporary.chmod(0o600); temporary.replace(target)
    try:
        with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003)) as sock:
            attach_filter(sock)
            sock.setsockopt(263, 8, 1)  # PACKET_AUXDATA: refuse VLAN-offloaded observations
            sock.setblocking(False)
            from .arp_inspection import refresh
            from .source_guard import refresh as refresh_guard
            arp_status = refresh(config, [], time.monotonic())
            guard_status = refresh_guard(config, [], time.monotonic())
            next_refresh = time.monotonic() + 0.5
            publish('ready')
            next_publish = time.monotonic()
            while running:
                if select.select([sock], [], [], 0.1)[0]:
                    # Bound each drain so traffic cannot starve shutdown/heartbeat.
                    for _ in range(128):
                        try:
                            frame, ancillary, flags, addr = sock.recvmsg(2048, 128)
                        except BlockingIOError:
                            break
                        tagged = any(level == 263 and kind == 8 and len(data) >= 4 and struct.unpack_from('I', data)[0] & 16
                                     for level, kind, data in ancillary)
                        if addr[2] != socket.PACKET_OUTGOING and not tagged and not flags & socket.MSG_TRUNC:
                            offloaded = any(level == 263 and kind == 8 and len(data) >= 4 and struct.unpack_from('I', data)[0] & (8 | 128)
                                            for level, kind, data in ancillary)
                            table.feed(addr[0], frame, checksum_offloaded=offloaded)
                now = time.monotonic()
                if now < next_publish:
                    continue
                path = Path(config['namespace'])
                if path.stat().st_ino != config['namespace_inode']:
                    raise RuntimeError('Namespace identity changed')
                state = json.loads(Path(config['state']).read_text())
                record = state.get('snooping_workers', {}).get(config['node'], {})
                if now - started > 2 and record.get('token') != config['token']:
                    raise RuntimeError('Observer ownership record removed or replaced')
                for port, index in identity.items():
                    if socket.if_nametoindex(port) != index:
                        raise RuntimeError('Observed interface identity changed')
                    flags = struct.unpack_from('H', fcntl.ioctl(sock, 0x8913, struct.pack('256s', port.encode())), 16)[0]
                    if not flags & 1 or not flags & 0x40:
                        table.client_port_down(port)
                received, lost = struct.unpack('II', sock.getsockopt(263, 6, 8))  # PACKET_STATISTICS, resets on read
                packets += received; drops += lost
                if lost:
                    # Never retain correlations across known capture loss.
                    table.bindings.clear(); table.pending.clear()
                table.expire(now)
                if now >= next_refresh:
                    arp_status = refresh(config, list(table.bindings.values()), now)
                    guard_status = refresh_guard(config, list(table.bindings.values()), time.monotonic())
                    next_refresh = time.monotonic() + 0.5
                publish('ready')
                next_publish = now + 0.2
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        error = str(exc)
    finally:
        table.bindings.clear(); table.pending.clear()
        from .arp_inspection import refresh
        from .source_guard import refresh as refresh_guard
        for clear_policy in (refresh, refresh_guard):
            try:
                clear_policy(config, [], time.monotonic(), clear=True)
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired):
                pass
        try:
            publish('failed' if error else 'stopped')
        except OSError:
            pass
    return 1 if error else 0


if __name__ == '__main__':
    raise SystemExit(serve(json.loads(Path(sys.argv[1]).read_text())))
