"""Root host worker in one node's network namespace, never its filesystem."""
import json
import os
from pathlib import Path
import signal
import socket
import sys
import time

from . import runtime
from .ssh_radius import PORT, dispatch


def request(connection):
    deadline = time.monotonic() + 2
    fields = []
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


def serve(config):
    if os.geteuid() != 0: raise ValueError('Host supervisor requires root')
    if (Path('/proc/self/ns/net').stat().st_ino != config['namespace_inode'] or
            Path(config['namespace']).stat().st_ino != config['namespace_inode']):
        raise ValueError('Network namespace differs')
    # A low internal port must stay root-only even on hosts whose network
    # namespace defaults permit unprivileged low-port binds. This sysctl is
    # namespaced, applied only after the exact node namespace is verified.
    protected = Path('/proc/sys/net/ipv4/ip_unprivileged_port_start')
    protected.write_text('1024')
    if protected.read_text().strip() != '1024': raise ValueError('Unprotected bridge endpoint')
    runtime.STATE_ROOT = Path(config['state_root'])
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', PORT)); listener.listen(4); listener.settimeout(.25)
        output = Path(config['output'])
        output.write_text(json.dumps({'status': 'ready', 'token': config['token']})); output.chmod(0o600)
        while True:
            try: connection, _ = listener.accept()
            except socket.timeout: continue
            with connection:
                stage = 'framing'
                try:
                    action, username, password = request(connection)
                    stage = 'state'
                    manager = BridgeManager(config); manager.current()
                    stage = 'dispatch'
                    result = dispatch(manager, config['node'], action, username, password,
                                      audit=lambda code: print('SSH_RADIUS_' + code, flush=True))
                    password = None
                    stage = 'reply'
                    connection.settimeout(1)
                    connection.sendall(b'DENY\n' if result is None else b'OK\n' + result.encode())
                except (OSError, ValueError, RuntimeError, KeyError, StopIteration) as error:
                    print('SSH_RADIUS_' + stage.upper() + '_' + type(error).__name__, flush=True)
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
