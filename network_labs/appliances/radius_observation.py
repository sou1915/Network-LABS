"""Passive process observations; neither liveness nor successful authentication."""
import re
import subprocess

from .runtime import RuntimeFailure

PIDFILE = '/run/network-labs-radius.pid'


def observe_process(manager, node):
    from .radius_server import command
    result = {'status': 'unknown', 'pid': None}
    try:
        read = manager.crun('exec', node['name'], '/bin/busybox', 'cat', PIDFILE, check=False, timeout=3)
        if read.returncode or not re.fullmatch(r'[0-9]{1,10}\s*', read.stdout): return result
        pid = int(read.stdout.strip())
        if not 1 <= pid <= 2147483647: return result
        result['pid'] = pid
        read = manager.crun('exec', node['name'], '/bin/busybox', 'cat', '/proc/' + str(pid) + '/cmdline',
                            check=False, timeout=3)
        if read.returncode or not read.stdout or len(read.stdout) > 4096: return result
        args = read.stdout.split('\0')
        if args[-1] == '': args.pop()
        result['status'] = 'observed' if args == command() else 'mismatch'
    except (OSError, RuntimeFailure, subprocess.TimeoutExpired, UnicodeError, ValueError):
        pass
    return result
