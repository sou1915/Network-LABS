"""Bounded, read-only configuration-file evidence from a container's mount namespace."""
import subprocess


def observe_config(manager, name, path, expected):
    detail, content = None, None
    try:
        result = manager.crun('exec', name, '/bin/busybox', 'head', '-c', '65537', path, check=False)
        available = result.returncode == 0 and len(result.stdout.encode('utf-8')) <= 65536
        if available:
            content = result.stdout
        else:
            detail = 'Config read failed or exceeded 64 KiB.'
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        available = False
        detail = str(exc)[:1024]
    return {'configuration_verified': available and content == expected,
            'configuration_available': available, 'detail': detail}
