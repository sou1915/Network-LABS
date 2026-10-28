"""Explicit, bounded RADIUS PAP authentication observation; no login policy changes."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from .runtime import RuntimeFailure
from .service_probe import unicast
from .spec import integer
from .verify import _endpoint
from .route_lookup import _json_read


def validate_credentials(username, password, secret):
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}', username):
        raise ValueError('RADIUS username requires 1..64 ASCII login characters.')
    if (not isinstance(password, str) or not 1 <= len(password.encode('utf-8')) <= 128 or
            any(c in password for c in '\0\r\n')):
        raise ValueError('RADIUS password requires 1..128 UTF-8 bytes without NUL or newlines.')
    if not isinstance(secret, str) or not re.fullmatch(r'[!-~]{16,128}', secret):
        raise ValueError('RADIUS secret requires 16..128 printable ASCII characters without spaces.')


def load_credential(path):
    # Nonblocking open lets us reject FIFOs instead of waiting on them.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError('RADIUS credential files must be regular private files (chmod 600).')
        data = source.read(130)
    if data.endswith(b'\n'):
        data = data[:-1]
    if not 1 <= len(data) <= 128:
        raise ValueError('RADIUS credential file exceeds 128 bytes or is empty.')
    return data.decode('utf-8')


def probe(manager, source, address, *, username, password, secret, timeout=3):
    validate_credentials(username, password, secret)
    integer(timeout, 1, 5, 'RADIUS deadline seconds')
    if not isinstance(address, str):
        raise ValueError('RADIUS requires a literal remote IPv4 server.')
    address = unicast(address)
    state = manager.read()
    if state['phase'] != 'running' or 'pending_spec' in state or 'pending_node' in state:
        raise RuntimeFailure('RADIUS requires a running lab without pending configuration.')
    match = next(((i, n) for i, n in enumerate(state['spec']['nodes']) if n['name'] == source), None)
    if (match is None or match[1]['runtime'] != 'oci' or match[1]['role'] != 'host' or
            set(match[1]['interfaces']) != {'eth0'} or match[1].get('subinterfaces') or match[1].get('port_channels')):
        raise ValueError('RADIUS requires a managed single-interface OCI host.')
    index, node = match; endpoint = _endpoint(manager, index, node)
    report = {'lab': manager.name, 'node': source, 'server': address, 'port': 1812,
              'started_at': datetime.now(timezone.utc).isoformat(), 'endpoint': endpoint,
              'status': endpoint['status'], 'authentication': None, 'configuration_changed': False,
              'scope': 'One RADIUS PAP Access-Request from host Python in the source network namespace. Response and Message-Authenticator are both required. Credentials pass through stdin, not argv or reports. Accept observes a server decision; it does not grant access or configure node AAA. No TLS, EAP/802.1X, accounting, retries or challenge continuation.'}
    def finish(status):
        report.update(status=status, finished_at=datetime.now(timezone.utc).isoformat())
        return report
    if endpoint['status'] != 'ready':
        return finish(endpoint['status'])
    route = _json_read(manager, index, 'ip', '-j', '-4', 'route', 'get', address)
    report['route'] = route
    if address == endpoint['address'] or any(row.get('type') in ('local', 'broadcast', 'multicast') or row.get('dev') == 'lo' for row in route['records'] or []):
        report['error'] = 'REMOTE_TARGET_REQUIRED'
        return finish('blocked')
    request = dict(source=endpoint['address'], address=address, port=1812, username=username,
                   password=password, secret=secret, timeout=timeout)
    worker = Path(__file__).with_name('radius_worker.py').read_text()
    try:
        process = manager.ns(index, sys.executable, '-I', '-c', worker, input_text=json.dumps(request),
                             check=False, timeout=timeout + 2)
        result = json.loads(process.stdout)
        if process.returncode or not isinstance(result, dict):
            raise ValueError
        # Do not echo arbitrary worker text, attributes or stderr into reports.
        allowed = ('status', 'decision', 'response_verified', 'requests_sent', 'discarded_responses', 'response_code', 'error')
        result = {key: result[key] for key in allowed if key in result}
        code = result.get('response_code')
        if result.get('status') not in ('passed', 'failed', 'blocked', 'unknown'):
            raise ValueError
        if (type(result.get('requests_sent')) is not int or result['requests_sent'] not in (0, 1) or
                type(result.get('discarded_responses')) is not int or not 0 <= result['discarded_responses'] <= 64 or
                type(result.get('response_verified')) is not bool or
                result.get('error') not in (None, 'TIMEOUT', 'PACKET_LIMIT', 'TRANSPORT_ERROR')):
            raise ValueError
        if result['status'] == 'unknown' and (result['response_verified'] or code is not None or result.get('decision') is not None):
            raise ValueError
        if result['status'] != 'unknown' and (result.get('response_verified') is not True or
                result['requests_sent'] != 1 or result.get('error') is not None or type(code) is not int or
                (result['status'], code, result.get('decision')) not in
                (('passed', 2, 'accepted'), ('failed', 3, 'rejected'), ('blocked', 11, 'challenge'))):
            raise ValueError
    except (OSError, RuntimeFailure, ValueError, subprocess.TimeoutExpired):
        report['error'] = 'WORKER_UNAVAILABLE'
        return finish('unknown')
    report['authentication'] = result
    return finish(result['status'])


def render(report):
    result = report.get('authentication') or {}
    return '\n'.join(['RADIUS PAP : ' + report['status'].upper() + ' | ' + report['node'] + ' → ' + report['server'],
                      'Décision vérifiée : ' + str(result.get('decision') or 'indisponible'),
                      'Un Accept ne configure pas les accès du node. Aucun suivi de challenge ni accounting.'])
