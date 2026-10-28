"""Host supervisor for RADIUS-gated SSH diagnostics; no guest shared secret."""
import ipaddress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

PORT = 813
_PROCESSES = {}
CLIENT = r'''#!/bin/sh
PATH=/bin:/usr/bin
LC_ALL=C
export PATH LC_ALL
unset ENV BASH_ENV CDPATH username password
# Two credential lines arrive only on SSH stdin, never argv or environment.
IFS= read -r -n 65 username || exit 126
IFS= read -r -n 129 password || exit 126
[ "${#username}" -le 64 ] && [ "${#password}" -le 128 ] || exit 126
{
    printf 'NLSSH1\n%s\n%s\n%s\n' "$1" "$username" "$password"
    unset password
} | /bin/busybox nc -w 10 127.0.0.1 813 | {
    IFS= read -r status || exit 126
    case "$status" in
        OK) /bin/busybox cat; exit $?;;
        *) printf 'SSH RADIUS request denied or unavailable.\n' >&2; exit 126;;
    esac
}
'''


def managed_secret(spec, node):
    policy = node.get('radius_access') or {}
    local = str(ipaddress.IPv4Interface(node['interfaces']['eth0']).ip)
    for server in spec['nodes']:
        service = server.get('radius_server')
        if not service: continue
        address = str(ipaddress.IPv4Interface(server['interfaces'][service['interface']]).ip)
        if address == policy.get('server'):
            matches = [c for c in service['clients'] if c['address'] == local]
            if len(matches) == 1: return address, matches[0]['secret']
    raise ValueError('SSH RADIUS requires a managed server with a matching NAS client.')


def dispatch(manager, source, action, username, password, *, audit=None):
    from .radius_exec import execute, verified_accept
    from .ssh_access import ACTIONS
    node = next(n for n in manager.read()['spec']['nodes'] if n['name'] == source)
    management = node.get('management') or {}
    if (management.get('ssh_radius') is not True or action not in ACTIONS or
            action not in (management.get('ssh_actions') or [])):
        if audit: audit('POLICY_DENIED')
        return None
    address, secret = managed_secret(manager.state['spec'], node)
    result = execute(manager, source, address, action=action, username=username, password=password, secret=secret, timeout=2)
    if (result.get('status') == 'passed' and result.get('executed') is True and result.get('returncode') == 0
            and verified_accept(result.get('authentication') or {})):
        output = result.get('stdout')
        if isinstance(output, str) and len(output.encode()) <= 4096:
            if audit: audit('VERIFIED_ACCEPT_EXECUTED')
            return output
    if audit:
        authentication = result.get('authentication') or {}
        audit('AUTHENTICATION_' + (authentication.get('status') if authentication.get('status') in
              ('passed', 'failed', 'blocked', 'unknown', 'ready', 'unavailable') else 'unavailable').upper())
        error = authentication.get('error')
        if error in ('WORKER_UNAVAILABLE', 'REMOTE_TARGET_REQUIRED'): audit('AUTH_ERROR_' + error)
        decision = authentication.get('authentication') or {}
        if decision.get('error') in ('TIMEOUT', 'PACKET_LIMIT', 'TRANSPORT_ERROR'): audit('WIRE_' + decision['error'])
        endpoint = authentication.get('endpoint') or {}
        if endpoint.get('status') in ('ready', 'unknown', 'unavailable', 'stopped'): audit('ENDPOINT_' + endpoint['status'].upper())
    return None


def alive(record):
    from .snooping import alive as observed_alive
    return observed_alive(record)


def stop_worker(manager, name):
    from .runtime import RuntimeFailure
    record = manager.state.setdefault('ssh_radius_workers', {}).get(name)
    if alive(record):
        # All subprocesses are in this new, owned session. Stop the bridge
        # before container teardown, including an in-flight auth subprocess.
        if os.getpgid(record['pid']) != record['pid']:
            raise RuntimeFailure('SSH RADIUS worker process group differs; cleanup retained.')
        try: os.killpg(record['pid'], signal.SIGTERM)
        except ProcessLookupError: pass
        deadline = time.monotonic() + 3
        while alive(record) and time.monotonic() < deadline: time.sleep(.02)
        if alive(record):
            try: os.killpg(record['pid'], signal.SIGKILL)
            except ProcessLookupError: pass
            deadline = time.monotonic() + 1
            while alive(record) and time.monotonic() < deadline: time.sleep(.02)
        if alive(record): raise RuntimeFailure('SSH RADIUS worker still alive; cleanup retained.')
    if record:
        child = _PROCESSES.pop(record['pid'], None)
        if child is not None: child.wait(timeout=1)
        else:
            try: os.waitpid(record['pid'], os.WNOHANG)
            except ChildProcessError: pass
    manager.state['ssh_radius_workers'].pop(name, None); manager.save()


def start_worker(manager, index, node):
    from .runtime import RuntimeFailure, process_identity
    from .spec import namespace
    if not (node.get('management') or {}).get('ssh_radius'): return
    token = uuid.uuid4().hex
    ns = Path('/run/netns') / namespace(manager.state['spec'], index)
    output = manager.directory / (node['name'] + '.ssh-radius-ready.json')
    config = manager.directory / (node['name'] + '.ssh-radius-config.json')
    config.write_text(json.dumps({'name': manager.name, 'node': node['name'], 'token': token,
                                 'namespace': str(ns), 'namespace_inode': ns.stat().st_ino,
                                 'state_root': str(manager.directory.parent), 'output': str(output)}))
    config.chmod(0o600)
    # -I ignores user Python environment; only this trusted checkout is added.
    code = 'import sys; sys.path.insert(0, ' + repr(str(Path(__file__).resolve().parents[2])) + '); from network_labs.appliances.ssh_radius_worker import main; main()'
    log = manager.directory / (node['name'] + '.ssh-radius.log'); log.touch(mode=0o600)
    with log.open('ab') as handle:
        process = subprocess.Popen(['ip', 'netns', 'exec', ns.name, sys.executable, '-I', '-c', code, str(config)],
                                   stdin=subprocess.DEVNULL, stdout=handle, stderr=handle, start_new_session=True)
    start = process_identity(process.pid)
    if start is None:
        process.kill(); process.wait(); raise RuntimeFailure('SSH RADIUS worker identity unavailable.')
    _PROCESSES[process.pid] = process
    manager.state.setdefault('ssh_radius_workers', {})[node['name']] = {'pid': process.pid, 'starttime': start, 'token': token}
    manager.save()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and process.poll() is None:
        try:
            ready = json.loads(output.read_text())
            if ready.get('token') == token and ready.get('status') == 'ready': return
        except (OSError, ValueError): pass
        time.sleep(.02)
    stop_worker(manager, node['name'])
    raise RuntimeFailure('SSH RADIUS bridge failed readiness; private log not echoed.')
