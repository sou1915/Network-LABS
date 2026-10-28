"""Explicit RADIUS-authenticated local CLI shell, not SSH/Telnet integration."""
import json
import signal
import subprocess
import tempfile
from contextlib import contextmanager

from .radius import probe
from .radius_access import authorize
from .radius_exec import process_config, verified_accept
from .runtime import RuntimeFailure
from .radius_session import SessionGroup, shell_args
from .spec import integer


@contextmanager
def session_signals():
    def interrupted(*_): raise KeyboardInterrupt
    previous = signal.signal(signal.SIGTERM, interrupted)
    try: yield
    finally: signal.signal(signal.SIGTERM, previous)


def login(manager, source, server, *, username, password, secret, timeout=3, terminal=False, seconds=None):
    if type(terminal) is not bool: raise ValueError('Terminal selection must be boolean.')
    if seconds is not None: integer(seconds, 1, 3600, 'Session seconds')
    result = {'status': 'blocked', 'node': source, 'session_attempted': False,
              'returncode': None, 'authentication': None, 'session_id': None, 'cleanup_complete': None}
    refusal = authorize(manager, source, server, username, 'shell')
    if refusal:
        return {**result, 'error': refusal}
    node = next(node for node in manager.read()['spec']['nodes'] if node['name'] == source)
    ceiling = node['radius_access'].get('session_seconds', 300)
    duration = ceiling if seconds is None else seconds
    if duration > ceiling: raise ValueError('Session duration exceeds the node policy limit.')
    result['session_seconds'] = duration
    authentication = probe(manager, source, server, username=username, password=password,
                           secret=secret, timeout=timeout)
    result['authentication'] = authentication
    if not verified_accept(authentication): return result
    group = None
    try:
        with SessionGroup(manager, source) as group:
            result['session_id'] = group.name
            process = process_config(shell_args(group.name, terminal), terminal=terminal)
            with tempfile.NamedTemporaryFile(mode='w+', prefix='radius-login-', suffix='.json',
                                             dir=manager.directory) as output:
                json.dump(process, output); output.flush()
                with session_signals():
                    result['session_attempted'] = True
                    code = subprocess.call(['crun', '--root', str(manager.directory / 'crun'),
                                            'exec', '--process', output.name, '--cgroup', group.name, source], timeout=duration)
        result.update(status='passed' if code == 0 else 'failed', returncode=code)
    except subprocess.TimeoutExpired:
        result.update(status='expired', returncode=124)
    except KeyboardInterrupt:
        result.update(status='interrupted', returncode=130)
    except (OSError, RuntimeFailure, ValueError):
        result.update(status='unknown', error='SESSION_UNAVAILABLE')
    finally:
        if group is not None:
            result['cleanup_complete'] = group.closed
            if not group.closed:
                result.update(status='unknown', error='SESSION_CLEANUP_UNCONFIRMED')
    return result
