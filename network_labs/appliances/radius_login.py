"""Shared bounded RADIUS shell supervisor for local CLI and SSH transports."""
import json
import ipaddress
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager, nullcontext

from .radius import probe
from .radius_access import authorize, authorization
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
    result['authorization'] = authorization(node['radius_access'], username)
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
    if node['radius_access'].get('accounting_outbox'):
        from .radius_outbox import binding, prepare
        try:
            address, expected, _ = binding(manager, source, username)
            if address != server or expected != secret or (authentication.get('endpoint') or {}).get('address') != str(ipaddress.IPv4Interface(node['interfaces']['eth0']).ip):
                raise ValueError('Outbox session source/backend differs.')
        except (OSError, RuntimeFailure, ValueError, StopIteration):
            return {**result, 'error': 'ACCOUNTING_OUTBOX_BINDING_UNAVAILABLE'}
        try:
            prepare(manager)
            if node['radius_access'].get('accounting_journal'):
                from .radius_journal import prepare as prepare_journal
                prepare_journal(manager)
        except (OSError, RuntimeFailure, ValueError):
            return {**result, 'error': 'ACCOUNTING_OUTBOX_UNAVAILABLE'}
    group = None
    journal_record = None
    launched_at = None
    try:
        with SessionGroup(manager, source) as group:
            result['session_id'] = group.name
            if node['radius_access'].get('accounting_journal'):
                from . import radius_journal
                journal_record = radius_journal.begin(manager, source, username, group)
                result['accounting']['journal'] = {'status': 'intent', 'session_id': group.name}
                def checkpoint_empty():
                    nonlocal journal_record
                    journal_record = radius_journal.mark_empty(manager, journal_record)
                group.on_empty = checkpoint_empty
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
            if journal_record is not None and group.closed and start is not None and start.get('requests_sent') == 0:
                from .radius_journal import handoff
                try:
                    handoff(manager, journal_record)
                    result['accounting']['journal']['status'] = 'retired_unsent'
                except (OSError, RuntimeFailure, ValueError):
                    result['accounting']['journal'] = {'status': 'pending', 'error': 'JOURNAL_HANDOFF_UNCONFIRMED'}
            if accounting and start is not None and start.get('requests_sent') != 0:
                if not group.closed:
                    result['accounting']['stop'] = {'status': 'withheld', 'error': 'SESSION_CLEANUP_UNCONFIRMED'}
                else:
                    elapsed = int(max(0, time.monotonic() - launched_at)) if launched_at is not None else 0
                    cause = {'passed': 1, 'expired': 5, 'interrupted': 6}.get(result['status'], 9)
                    queued = None
                    if node['radius_access'].get('accounting_outbox'):
                        from .radius_outbox import enqueue
                        try:
                            queued = enqueue(manager, source, server, username, secret, group.name, elapsed, cause,
                                             int(time.time()), cleanup_complete=group.closed)
                            result['accounting']['outbox'] = {'status': 'pending', 'session_id': group.name}
                        except (OSError, RuntimeFailure, ValueError, StopIteration):
                            result['accounting']['outbox'] = {'status': 'unavailable', 'error': 'OUTBOX_WRITE_UNCONFIRMED'}
                    if queued is not None and journal_record is not None:
                        from .radius_journal import handoff
                        try:
                            handoff(manager, journal_record)
                            result['accounting']['journal']['status'] = 'handed_off'
                        except (OSError, RuntimeFailure, ValueError):
                            result['accounting']['journal'] = {'status': 'pending', 'error': 'JOURNAL_HANDOFF_UNCONFIRMED'}
                            result.update(status='unknown', error='ACCOUNTING_JOURNAL_UNCONFIRMED')
                    try:
                        stop = account(manager, source, server, username=username, secret=secret, session_id=group.name,
                                       event='stop', session_seconds=elapsed, terminate_cause=cause, timeout=timeout)
                    except (OSError, RuntimeFailure, ValueError, subprocess.TimeoutExpired, KeyboardInterrupt):
                        stop = {'status': 'unknown', 'error': 'ACCOUNTING_WORKER_UNAVAILABLE'}
                    result['accounting']['stop'] = stop
                    if queued is not None and stop.get('status') == 'passed' and stop.get('response_verified') is True:
                        from .radius_outbox import acknowledge
                        try:
                            acknowledge(manager, queued)
                            result['accounting']['outbox']['status'] = 'cleared'
                        except (OSError, RuntimeFailure, ValueError):
                            result['accounting']['outbox'] = {'status': 'pending', 'error': 'OUTBOX_DELETE_UNCONFIRMED'}
                            result.update(status='unknown', error='ACCOUNTING_OUTBOX_UNCONFIRMED')
                    if stop['status'] != 'passed' and result['session_attempted']:
                        result.update(status='unknown', error='ACCOUNTING_STOP_UNCONFIRMED')
    return result
