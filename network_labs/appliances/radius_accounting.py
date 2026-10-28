"""Bounded accounting for authorized local shell sessions; no delivery queue."""
import json
from pathlib import Path
import re
import subprocess
import sys

from .radius import validate_credentials
from .radius_access import authorize
from .runtime import RuntimeFailure
from .spec import integer
from .verify import _endpoint
from .route_lookup import _json_read


def send(manager, source, server, *, username, secret, session_id, event, session_seconds=0,
         terminate_cause=1, timeout=3):
    validate_credentials(username, 'accounting', secret)
    if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', session_id):
        raise ValueError('Accounting session ID requires 1..64 ASCII identifier characters.')
    if event not in ('start', 'stop'): raise ValueError('Accounting event must be start or stop.')
    integer(session_seconds, 0, 0xffffffff, 'Accounting session seconds')
    integer(terminate_cause, 1, 18, 'Accounting termination cause')
    integer(timeout, 1, 5, 'Accounting deadline seconds')
    if authorize(manager, source, server, username, 'shell'):
        raise ValueError('Accounting requires the declared shell user and server.')
    index, node = next((i, n) for i, n in enumerate(manager.read()['spec']['nodes']) if n['name'] == source)
    if node['radius_access'].get('accounting') is not True:
        raise ValueError('Session accounting must be explicitly enabled in the node policy.')
    report = {'status': 'unknown', 'event': event, 'session_id': session_id, 'response_verified': False,
              'requests_sent': 0, 'discarded_responses': 0, 'response_code': None, 'error': None}
    endpoint = _endpoint(manager, index, node)
    if endpoint['status'] != 'ready': return {**report, 'error': 'ENDPOINT_UNAVAILABLE'}
    route = _json_read(manager, index, 'ip', '-j', '-4', 'route', 'get', server)
    if server == endpoint['address'] or any(row.get('type') in ('local', 'broadcast', 'multicast') or
            row.get('dev') == 'lo' for row in route['records'] or []):
        return {**report, 'error': 'REMOTE_TARGET_REQUIRED'}
    request = dict(source=endpoint['address'], address=server, port=1813, username=username, secret=secret,
                   session_id=session_id, event=event, session_seconds=session_seconds,
                   terminate_cause=terminate_cause, timeout=timeout)
    worker = Path(__file__).with_name('radius_accounting_worker.py').read_text()
    try:
        process = manager.ns(index, sys.executable, '-I', '-c', worker, input_text=json.dumps(request),
                             check=False, timeout=timeout + 2)
        value = json.loads(process.stdout)
        if process.returncode or not isinstance(value, dict): raise ValueError
        value = {key: value[key] for key in ('status', 'response_verified', 'requests_sent',
                 'discarded_responses', 'response_code', 'error')}
        if (value['status'] not in ('passed', 'unknown') or type(value['response_verified']) is not bool or
                type(value['requests_sent']) is not int or value['requests_sent'] not in (0, 1) or
                type(value['discarded_responses']) is not int or not 0 <= value['discarded_responses'] <= 64 or
                value['error'] not in (None, 'TIMEOUT', 'PACKET_LIMIT', 'TRANSPORT_ERROR')): raise ValueError
        if value['status'] == 'passed':
            if (not value['response_verified'] or value['requests_sent'] != 1 or
                    type(value['response_code']) is not int or value['response_code'] != 5 or value['error'] is not None):
                raise ValueError
        elif value['response_verified'] or value['response_code'] is not None: raise ValueError
        return {**report, **value}
    except (OSError, RuntimeFailure, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return {**report, 'requests_sent': None, 'error': 'WORKER_UNAVAILABLE'}
