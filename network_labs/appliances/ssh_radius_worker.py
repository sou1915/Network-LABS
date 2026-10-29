"""Host supervisor with a node-local socket and host runtime control."""
import json
import ctypes
import os
from pathlib import Path
import signal
import socket
import sys
import time

from . import runtime
from .ssh_radius import PORT, dispatch


def request(connection, *, audit=None):
    deadline = time.monotonic() + 2
    fields = []
    try:
        for limit in (6, 32, 64, 128):
            raw = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise ValueError('Request deadline')
                connection.settimeout(remaining)
                byte = connection.recv(1)
                if not byte: raise ValueError('Incomplete request')
                if byte == b'\n': break
                raw.extend(byte)
                if len(raw) > limit: raise ValueError('Request field limit')
            fields.append(bytes(raw).decode('utf-8'))
    except (OSError, ValueError):
        if audit: audit('FRAMING_FIELD_' + str(len(fields)))
        raise
    if fields[0] != 'NLSSH1': raise ValueError('Protocol version')
    return fields[1:]


class BridgeManager(runtime.Manager):
    def __init__(self, config):
        super().__init__(config['name']); self.config = config

    def current(self):
        # Do not take the lab lock: an SSH client may itself be running inside
        # an administrative console holding it. Teardown stops this owned
        # process group before deleting containers; each runtime call also
        # rejects stale generations or transitional lab phases.
        self.state = None
        state = self.read()
        record = state.get('ssh_radius_workers', {}).get(self.config['node'], {})
        if state['phase'] != 'running' or record.get('token') != self.config['token']:
            raise runtime.RuntimeFailure('SSH RADIUS lab generation unavailable.')
        return state

    def ns(self, *args, **kwargs):
        self.current(); return super().ns(*args, **kwargs)

    def crun(self, *args, **kwargs):
        self.current(); return super().crun(*args, **kwargs)


def namespace_socket(config):
    # ip netns exec also remounts sysfs in a new mount namespace, hiding the
    # host cgroup mount needed by crun state/exec. Move only this thread's
    # network namespace for socket creation, then restore the host context.
    if Path(config['namespace']).stat().st_ino != config['namespace_inode']:
        raise ValueError('Network namespace differs')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.setns.argtypes = (ctypes.c_int, ctypes.c_int)
    libc.setns.restype = ctypes.c_int
    def enter(fd):
        if libc.setns(fd, 0x40000000) != 0:  # CLONE_NEWNET
            raise OSError(ctypes.get_errno(), 'Network namespace switch failed')
    original = os.open('/proc/self/ns/net', os.O_RDONLY | os.O_CLOEXEC)
    target = None
    listener = None
    try:
        target = os.open(config['namespace'], os.O_RDONLY | os.O_CLOEXEC)
        if os.fstat(target).st_ino != config['namespace_inode']: raise ValueError('Network namespace changed')
        enter(target)
        try:
            if Path('/proc/self/ns/net').stat().st_ino != config['namespace_inode']:
                raise ValueError('Network namespace switch differs')
            protected = Path('/proc/sys/net/ipv4/ip_unprivileged_port_start')
            protected.write_text('1024')
            if protected.read_text().strip() != '1024': raise ValueError('Unprotected bridge endpoint')
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', PORT)); listener.listen(4); listener.settimeout(.25)
        finally:
            enter(original)
    except BaseException:
        if listener is not None: listener.close()
        raise
    finally:
        if target is not None: os.close(target)
        os.close(original)
    return listener


def serve(config):
    if os.geteuid() != 0: raise ValueError('Host supervisor requires root')
    listener = namespace_socket(config)
    runtime.STATE_ROOT = Path(config['state_root'])
    with listener:
        output = Path(config['output'])
        output.write_text(json.dumps({'status': 'ready', 'token': config['token']})); output.chmod(0o600)
        audit_count = 0
        def audit(code):
            nonlocal audit_count
            if audit_count < 32:
                print('SSH_RADIUS_' + code, flush=True)
                audit_count += 1
        while True:
            try: connection, _ = listener.accept()
            except socket.timeout: continue
            with connection:
                stage = 'framing'
                try:
                    action, username, password = request(connection, audit=audit)
                    stage = 'state'
                    manager = BridgeManager(config); manager.current()
                    stage = 'dispatch'
                    if action in ('shell', 'shell-tty'):
                        from .ssh_radius_shell import serve_shell
                        serve_shell(manager, config['node'], connection, username, password,
                                    terminal=action == 'shell-tty', audit=audit)
                        password = None
                        continue
                    result = dispatch(manager, config['node'], action, username, password,
                                      audit=audit)
                    password = None
                    stage = 'reply'
                    connection.settimeout(1)
                    connection.sendall(b'DENY\n' if result is None else b'OK\n' + result.encode())
                except (OSError, ValueError, RuntimeError, KeyError, StopIteration) as error:
                    audit(stage.upper() + '_' + type(error).__name__)
                    try: connection.sendall(b'DENY\n')
                    except OSError: pass


def main():
    def stop(*_): raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    try:
        serve(json.loads(Path(sys.argv[1]).read_text()))
    except (OSError, ValueError, RuntimeError, KeyError):
        # Never print request data, state contents or exception representations.
        print('SSH RADIUS supervisor unavailable.', file=sys.stderr)
        raise SystemExit(1)
