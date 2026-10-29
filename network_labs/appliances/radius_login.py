"""Shared bounded RADIUS shell supervisor for local CLI and SSH transports."""
import json
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager, nullcontext

from .radius import probe
from .radius_access import authorize
from .radius_exec import process_config, verified_accept
from .runtime import RuntimeFailure
from .radius_session import SessionGroup, shell_args
from .spec import integer
from .radius_accounting import send as account


@contextmanager
def session_signals():
    def interrupted(*_): raise KeyboardInterrupt
    previous = signal.signal(signal.SIGTERM, interrupted)
    try: yield
    finally: signal.signal(signal.SIGTERM, previous)


def login(manager, source, server, *, username, password, secret, timeout=3, terminal=False, seconds=None, launcher=None, handle_signals=True):
    if type(terminal) is not bool: raise ValueError('Terminal selection must be boolean.')
    if type(handle_signals) is not bool: raise ValueError('Signal handling selection must be boolean.')
    if launcher is not None and not callable(launcher): raise ValueError('Session launcher must be callable.')
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
    accounting = node['radius_access'].get('accounting') is True
    result['accounting'] = {'enabled': accounting, 'start': None, 'stop': None}
    authentication = probe(manager, source, server, username=username, password=password,
                           secret=secret, timeout=timeout)
    result['authentication'] = authentication
    if not verified_accept(authentication): return result
    group = None
    launched_at = None
    try:
        with SessionGroup(manager, source) as group:
            result['session_id'] = group.name
            if accounting:
                start = account(manager, source, server, username=username, secret=secret, session_id=group.name,
                                event='start', timeout=timeout)
                result['accounting']['start'] = start
                if start['status'] != 'passed':
                    result.update(status='blocked', error='ACCOUNTING_START_UNCONFIRMED')
                    return result
            process = process_config(shell_args(group.name, terminal), terminal=terminal)
            with tempfile.NamedTemporaryFile(mode='w+', prefix='radius-login-', suffix='.json',
                                             dir=manager.directory) as output:
                json.dump(process, output); output.flush()
                with (session_signals() if handle_signals else nullcontext()):
                    result['session_attempted'] = True
                    launched_at = time.monotonic()
                    code = (launcher or subprocess.call)(['crun', '--root', str(manager.directory / 'crun'),
                                            'exec', '--process', output.name, '--cgroup', group.name, source], timeout=duration)
        result.update(status='passed' if code == 0 else 'failed', returncode=code)
    except subprocess.TimeoutExpired:
        result.update(status='expired', returncode=124)
    except KeyboardInterrupt:
        result.update(status='interrupted', returncode=130)
    except SystemExit:
        result.update(status='interrupted', returncode=130)
        raise
    except (OSError, RuntimeFailure, ValueError):
        result.update(status='unknown', error='SESSION_UNAVAILABLE')
    finally:
        if group is not None:
            result['cleanup_complete'] = group.closed
            if not group.closed:
                result.update(status='unknown', error='SESSION_CLEANUP_UNCONFIRMED')
            start = result['accounting']['start']
            if accounting and start is not None and start.get('requests_sent') != 0:
                if not group.closed:
                    result['accounting']['stop'] = {'status': 'withheld', 'error': 'SESSION_CLEANUP_UNCONFIRMED'}
                else:
                    elapsed = int(max(0, time.monotonic() - launched_at)) if launched_at is not None else 0
                    cause = {'passed': 1, 'expired': 5, 'interrupted': 6}.get(result['status'], 9)
                    try:
                        stop = account(manager, source, server, username=username, secret=secret, session_id=group.name,
                                       event='stop', session_seconds=elapsed, terminate_cause=cause, timeout=timeout)
                    except (OSError, RuntimeFailure, ValueError, subprocess.TimeoutExpired, KeyboardInterrupt):
                        stop = {'status': 'unknown', 'error': 'ACCOUNTING_WORKER_UNAVAILABLE'}
                    result['accounting']['stop'] = stop
                    if stop['status'] != 'passed' and result['session_attempted']:
                        result.update(status='unknown', error='ACCOUNTING_STOP_UNCONFIRMED')
    return result
