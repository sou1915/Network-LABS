"""Bounded SSH shell transport using the existing RADIUS session supervisor."""
import base64
import errno
import fcntl
import os
import pty
import select
import socket
import struct
import subprocess
import termios
import time

from .radius_login import login
from .runtime import RuntimeFailure

BUFFER = 65536
MAX_OUTPUT = 1024 * 1024


def frame(data):
    return b'D' + base64.b64encode(data) + b'\n'


def relay(connection, process, reader, writer, *, terminal, seconds):
    deadline = time.monotonic() + seconds
    incoming = bytearray(); outgoing = bytearray()
    input_eof = output_eof = False
    output_bytes = 0
    connection.setblocking(False)
    os.set_blocking(reader, False); os.set_blocking(writer, False)
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise subprocess.TimeoutExpired('SSH RADIUS shell', seconds)
            code = process.poll()
            if code is not None:
                # Drain data already queued by the main process, without
                # waiting for background jobs which may keep stdout open.
                connection.settimeout(min(1, remaining))
                if outgoing: connection.sendall(outgoing)
                while not output_eof:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0: raise subprocess.TimeoutExpired('SSH RADIUS shell', seconds)
                    try: data = os.read(reader, 2048)
                    except BlockingIOError: break
                    except OSError as error:
                        if error.errno != errno.EIO: raise
                        break
                    if not data: break
                    output_bytes += len(data)
                    if output_bytes > MAX_OUTPUT: raise RuntimeFailure('SSH shell output limit reached')
                    connection.settimeout(min(1, remaining)); connection.sendall(frame(data))
                return code
            if input_eof and not incoming and not terminal and not process.stdin.closed:
                process.stdin.close()
            reads = ([] if input_eof or len(incoming) >= BUFFER else [connection])
            if not output_eof and len(outgoing) <= BUFFER - 4096: reads.append(reader)
            writes = ([connection] if outgoing else []) + ([writer] if incoming else [])
            readable, writable, _ = select.select(reads, writes, [], min(.1, remaining))
            if connection in readable:
                data = connection.recv(min(4096, BUFFER - len(incoming)))
                if data: incoming.extend(data)
                elif terminal:
                    raise KeyboardInterrupt  # Real TTY Ctrl-D arrives as data.
                else: input_eof = True
            if reader in readable:
                try: data = os.read(reader, 2048)
                except OSError as error:
                    if error.errno != errno.EIO: raise
                    data = b''
                if data:
                    output_bytes += len(data)
                    if output_bytes > MAX_OUTPUT: raise RuntimeFailure('SSH shell output limit reached')
                    outgoing.extend(frame(data))
                else: output_eof = True
            if writer in writable:
                try: count = os.write(writer, incoming)
                except BrokenPipeError:
                    incoming.clear(); input_eof = True
                else: del incoming[:count]
            if connection in writable:
                count = connection.send(outgoing)
                del outgoing[:count]
    finally:
        connection.settimeout(1)


def serve_shell(manager, source, connection, username, password, *, terminal, audit=None):
    node = next(n for n in manager.read()['spec']['nodes'] if n['name'] == source)
    policy = node.get('management') or {}
    if policy.get('ssh_radius') is not True or 'shell' not in (policy.get('ssh_actions') or []):
        connection.sendall(b'DENY\n'); return
    from .ssh_radius import managed_secret
    address, secret = managed_secret(manager.state['spec'], node)
    processes = []
    started = False
    def launch(args, *, timeout):
        nonlocal started
        manager.current()  # Reject a stale lab generation immediately before exec.
        master = slave = None
        process = None
        try:
            if terminal:
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
                process = subprocess.Popen(args, stdin=slave, stdout=slave, stderr=slave)
                os.close(slave); slave = None
                reader = writer = master
            else:
                process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                reader = process.stdout.fileno(); writer = process.stdin.fileno()
            processes.append(process)
            connection.sendall(b'SHELL\n'); started = True
            return relay(connection, process, reader, writer, terminal=terminal, seconds=timeout)
        finally:
            if slave is not None: os.close(slave)
            if master is not None: os.close(master)
            if process is not None:
                for stream in (process.stdin, process.stdout):
                    if stream is not None: stream.close()
    try:
        result = login(manager, source, address, username=username, password=password, secret=secret,
                       timeout=2, terminal=terminal, launcher=launch, handle_signals=False)
        if audit: audit('SHELL_' + result['status'].upper())
        if not started:
            connection.sendall(b'DENY\n'); return
        # Final status is sent only after cgroup cleanup and optional Stop.
        code = {'passed': 0, 'expired': 124, 'interrupted': 130, 'unknown': 125}.get(result['status'])
        if code is None:
            code = result.get('returncode')
            code = code if type(code) is int and 1 <= code <= 255 else 125
        connection.sendall(b'E' + str(code).encode() + b'\n')
    finally:
        # The session supervisor runs its cgroup cleanup before we reap/kill
        # any remaining host crun transport helper.
        for process in processes:
            if process.poll() is None:
                try: process.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=1)
