"""Bounded tcpdump capture, pinned to an owned node's network namespace."""
import json
import os
from pathlib import Path
import select
import shutil
import signal
import struct
import subprocess
import time

from .runtime import RuntimeFailure
from .spec import integer, namespace

MAX_BYTES = 16 * 1024 * 1024
NETNS_ROOT = Path('/run/netns')


def limits(seconds, packets, snaplen, expression):
    integer(seconds, 1, 60, 'Capture seconds')
    integer(packets, 1, 10000, 'Capture packets')
    integer(snaplen, 64, 65535, 'Capture snaplen')
    if 24 + packets * (16 + snaplen) > MAX_BYTES:
        raise ValueError('Capture packet/snaplen budget exceeds 16 MiB; reduce --packets or --snaplen.')
    if not isinstance(expression, str) or len(expression) > 512 or '\0' in expression:
        raise ValueError('BPF filter must be text of at most 512 characters without NUL.')


def pcap_summary(handle):
    """Validate a classic PCAP without loading packet payloads into memory."""
    handle.flush(); handle.seek(0)
    size = os.fstat(handle.fileno()).st_size
    header = handle.read(24)
    endian = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>',
              b'\x4d\x3c\xb2\xa1': '<', b'\xa1\xb2\x3c\x4d': '>'}.get(header[:4])
    if len(header) != 24 or endian is None or size > MAX_BYTES:
        raise RuntimeFailure('Capture is not a complete bounded classic PCAP.')
    major, minor, _, _, snaplen, linktype = struct.unpack(endian + 'HHIIII', header[4:])
    if (major, minor) != (2, 4) or not 1 <= snaplen <= 65535:
        raise RuntimeFailure('Unexpected PCAP version or snapshot length.')
    packets = 0
    while handle.tell() < size:
        record = handle.read(16)
        if len(record) != 16:
            raise RuntimeFailure('Truncated PCAP packet header.')
        _, _, included, original = struct.unpack(endian + 'IIII', record)
        if included > snaplen or included > original or handle.tell() + included > size:
            raise RuntimeFailure('Truncated or invalid PCAP packet payload.')
        handle.seek(included, 1); packets += 1
    return {'captured_packets': packets, 'snapshot_length': snaplen, 'linktype': linktype, 'bytes': size}


def _finish(process):
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        return process.communicate(timeout=2)[1]
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=2)[1]


def _ready(process, deadline):
    """tcpdump uses the C locale; only announce readiness after opening capture."""
    log = b''
    until = min(deadline, time.monotonic() + 5)
    while time.monotonic() < until:
        readable, _, _ = select.select([process.stderr], [], [], max(0, until - time.monotonic()))
        if not readable:
            break
        chunk = os.read(process.stderr.fileno(), 4096)
        log += chunk
        if b'listening on ' in log:
            return log
        if not chunk:
            raise RuntimeFailure('Capture startup failed: ' + log.decode(errors='replace').strip())
    raise RuntimeFailure('tcpdump did not report capture readiness within the startup deadline.')


def capture(manager, name, interface, output, *, seconds=10, packets=1000, snaplen=2048, expression='', ready=None):
    limits(seconds, packets, snaplen, expression)
    tcpdump, nsenter = shutil.which('tcpdump'), shutil.which('nsenter')
    if not tcpdump or not nsenter:
        raise RuntimeFailure('Capture requires host tcpdump and nsenter (util-linux); no fallback is used.')
    output = Path(output).absolute()
    process = handle = None
    try:
        with manager.locked():
            state = manager.read()
            if state['phase'] != 'running':
                raise RuntimeFailure('Lab must be running before capture.')
            match = next(((i, n) for i, n in enumerate(state['spec']['nodes']) if n['name'] == name), None)
            if match is None or match[1]['runtime'] != 'oci':
                raise ValueError('Capture requires an existing OCI node; guest VM capture has no adapter.')
            index, node = match
            allowed = set(node['interfaces']) | set(node['port_channels']) | {'lo'}
            allowed.update(p for p, sub in node['subinterfaces'].items() if sub['vlan'] is not None)
            if node['role'] == 'switch':
                allowed.add('br0')
            if interface not in allowed:
                raise ValueError('Capture interface must belong to this node; any/host interfaces are not accepted.')
            status = manager.crun('state', name, check=False)
            if status.returncode or json.loads(status.stdout).get('status') != 'running':
                raise RuntimeFailure('Node container must be running before capture.')
            manager.ns(index, 'ip', 'link', 'show', 'dev', interface)
            nsname = namespace(state['spec'], index)
            # Open while holding the lab lock. The inherited descriptor pins
            # this namespace even if stop removes its name after lock release.
            with (NETNS_ROOT / nsname).open('rb') as netns:
                fd = os.open(output, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                handle = os.fdopen(fd, 'w+b')
                uid, gid = os.environ.get('SUDO_UID', ''), os.environ.get('SUDO_GID', '')
                if uid.isdecimal() and gid.isdecimal():
                    os.fchown(handle.fileno(), int(uid), int(gid))
                command = [nsenter, '--net=/proc/self/fd/' + str(netns.fileno()), '--', tcpdump,
                           '-p', '-n', '-U', '-i', interface, '-s', str(snaplen), '-c', str(packets), '-w', '-']
                if expression:
                    command += ['--', expression]
                started = time.monotonic(); deadline = started + seconds
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.PIPE,
                                           pass_fds=(netns.fileno(),), env={**os.environ, 'LC_ALL': 'C'},
                                           start_new_session=True, bufsize=0)
        # Do not retain the lab lock during recording: exec/configure/stop must
        # remain usable from a second terminal. nsenter never falls back to host.
        reason = 'completed'
        try:
            log = _ready(process, deadline)
            if ready:
                ready()
            try:
                log += process.communicate(timeout=max(0, deadline - time.monotonic()))[1]
            except subprocess.TimeoutExpired:
                reason = 'duration'; log += _finish(process)
        except KeyboardInterrupt:
            reason = 'interrupted'; log = _finish(process)
        if process.returncode != 0:
            raise RuntimeFailure('tcpdump failed: ' + log.decode(errors='replace').strip())
        summary = pcap_summary(handle)
        if summary['captured_packets'] > packets or summary['snapshot_length'] > snaplen:
            raise RuntimeFailure('Capture exceeded its requested packet/snapshot bounds.')
        return {'lab': manager.name, 'node': name, 'interface': interface, 'namespace': nsname,
                'file': str(output), 'format': 'pcap', **summary, 'filter': expression,
                'seconds_limit': seconds, 'packet_limit': packets, 'max_file_bytes': MAX_BYTES,
                'duration_seconds': round(time.monotonic() - started, 3), 'stop_reason': reason,
                'source': 'tcpdump/libpcap in the node network namespace', 'promiscuous_requested': False,
                'note': 'Observed packets only; capture point/offloads/filter/snaplen may affect visibility. No connectivity or zero-loss claim.'}
    finally:
        try:
            if process is not None and process.poll() is None:
                _finish(process)
        finally:
            if process is not None and process.stderr is not None:
                process.stderr.close()
            if handle is not None:
                handle.close()
