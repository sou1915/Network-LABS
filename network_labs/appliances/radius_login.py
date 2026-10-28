"""Explicit RADIUS-authenticated local CLI shell, not SSH/Telnet integration."""
import json
import subprocess
import tempfile

from .radius import probe
from .radius_access import authorize
from .radius_exec import process_config, verified_accept
from .runtime import RuntimeFailure


def login(manager, source, server, *, username, password, secret, timeout=3, terminal=False):
    if type(terminal) is not bool: raise ValueError('Terminal selection must be boolean.')
    result = {'status': 'blocked', 'node': source, 'session_attempted': False,
              'returncode': None, 'authentication': None}
    refusal = authorize(manager, source, server, username, 'shell')
    if refusal:
        return {**result, 'error': refusal}
    authentication = probe(manager, source, server, username=username, password=password,
                           secret=secret, timeout=timeout)
    result['authentication'] = authentication
    if not verified_accept(authentication): return result
    process = process_config(['/bin/busybox', 'sh', *(['-i'] if terminal else [])], terminal=terminal)
    try:
        with tempfile.NamedTemporaryFile(mode='w+', prefix='radius-login-', suffix='.json',
                                         dir=manager.directory) as output:
            json.dump(process, output); output.flush()
            result['session_attempted'] = True
            code = subprocess.call(['crun', '--root', str(manager.directory / 'crun'),
                                    'exec', '--process', output.name, source])
        result.update(status='passed' if code == 0 else 'failed', returncode=code)
    except KeyboardInterrupt:
        result.update(status='interrupted', returncode=130)
    except (OSError, RuntimeFailure):
        result.update(status='unknown', error='SESSION_UNAVAILABLE')
    return result
