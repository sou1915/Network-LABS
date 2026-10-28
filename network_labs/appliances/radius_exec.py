"""Declared authorization and RADIUS-gated non-root diagnostics."""
import json
import subprocess
import tempfile

from .radius import probe
from .radius_access import authorize
from .runtime import RuntimeFailure

ACTIONS = {'identity': ['/bin/busybox', 'id'],
           'hostname': ['/bin/busybox', 'hostname'],
           'security-context': ['/bin/busybox', 'cat', '/proc/self/status']}


def execute(manager, source, server, *, action, username, password, secret, timeout=3):
    if action not in ACTIONS:
        raise ValueError('RADIUS execution requires a supported diagnostic action.')
    refusal = authorize(manager, source, server, username, action)
    if refusal:
        return {'status': 'blocked', 'action': action, 'node': source, 'authentication': None,
                'executed': False, 'returncode': None, 'error': refusal}
    authentication = probe(manager, source, server, username=username, password=password,
                           secret=secret, timeout=timeout)
    decision = authentication.get('authentication') or {}
    result = {'status': 'blocked', 'action': action, 'node': source,
              'authentication': authentication, 'executed': False, 'returncode': None,
              'scope': 'One locally authorized diagnostic after a verified Access-Accept; UID/GID 65532, empty capabilities, no new privileges. No SSH/Telnet policy, shell, per-user roles, accounting or persistent session.'}
    if not (authentication.get('status') == 'passed' and decision.get('response_verified') is True
            and decision.get('response_code') == 2 and decision.get('decision') == 'accepted'):
        return result
    process = {'terminal': False, 'user': {'uid': 65532, 'gid': 65532, 'additionalGids': []},
               'args': list(ACTIONS[action]), 'cwd': '/', 'env': ['PATH=/bin:/usr/bin'],
               'noNewPrivileges': True,
               'capabilities': {key: [] for key in ('bounding', 'effective', 'permitted', 'inheritable', 'ambient')}}
    try:
        # Private process file contains no credentials; keep it alive only for exec.
        with tempfile.NamedTemporaryFile(mode='w+', prefix='radius-exec-', suffix='.json',
                                         dir=manager.directory) as output:
            json.dump(process, output); output.flush()
            result['executed'] = True
            completed = manager.crun('exec', '--process', output.name, source,
                                     check=False, timeout=5, input_text='')
        result.update(status='passed' if completed.returncode == 0 else 'failed',
                      returncode=completed.returncode, stdout=completed.stdout[:4096],
                      output_truncated=len(completed.stdout) > 4096)
    except (OSError, RuntimeFailure, subprocess.TimeoutExpired):
        result.update(status='unknown', error='EXECUTION_UNAVAILABLE')
    return result
