"""Opt-in common-tree dynamic FDB repair after observed carrier/path changes."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

from .runtime import RuntimeFailure, process_identity, run, write_json
from .spec import namespace
from .snooping import alive

_PROCESSES = {}


def sample(manager, peers):
    from .spanning_tree import kernel_ids, observe
    from .lacp import observe as observe_lacp
    roots = set(); path = []; settled = True
    for index, node in peers:
        links = json.loads(manager.ns(index, 'ip', '-j', '-d', 'link', 'show', timeout=3).stdout)
        tree = observe(node, links, kernel_ids(manager, index)); roots.add(tree['root_id'])
        bundles = observe_lacp(manager, index, node, links)
        settled = settled and tree['protocol'] == 'stp' and tree['local_state_settled']
        if tree['root_port'] in bundles: settled = settled and bundles[tree['root_port']]['ready']
        path.append((node['name'], tree['root_id'], tree['root_port'],
                     tuple(sorted((name, p['state']) for name, p in tree['ports'].items()))))
    return tuple(path), bool(settled and None not in roots and len(roots) == 1)


class Tracker:
    def __init__(self):
        self.last = None; self.candidate = None; self.dirty = False

    def update(self, path, settled):
        if not settled:
            self.candidate = None; return False
        if self.candidate != path:
            self.candidate = path; return False
        if self.last is None:
            self.last = path; return self.dirty
        return self.dirty or self.last != path

    def committed(self, path):
        self.last = path; self.dirty = False


def components(spec):
    nodes = {n['name']: (i, n) for i, n in enumerate(spec['nodes']) if n['spanning_tree'].get('carrier_recovery')}
    pending = set(nodes); result = []
    adjacency = {name: set() for name in nodes}
    for (left, _), (right, _) in spec['links']:
        if left in nodes and right in nodes: adjacency[left].add(right); adjacency[right].add(left)
    while pending:
        seen = set(); todo = [min(pending)]
        while todo:
            name = todo.pop()
            if name in seen: continue
            seen.add(name); todo.extend(adjacency[name] - seen)
        pending -= seen; result.append([nodes[name] for name in sorted(seen)])
    return result


def worker(config_path):
    config = json.loads(Path(config_path).read_text()); spec = config['spec']; scopes = config['scopes']
    output = Path(config['output']); groups = components(spec); trackers = [Tracker() for _ in groups]
    report = {'token': config['token'], 'status': 'ready', 'repairs': 0, 'last_event': None, 'error': None}
    def ns(index, *args, **options):
        scope = scopes[str(index)]; path = Path('/run/netns') / scope['name']
        if path.stat().st_ino != scope['inode']: raise RuntimeFailure('Owned carrier namespace identity changed')
        return run(['ip', 'netns', 'exec', scope['name'], *args], timeout=min(options.get('timeout', 3), 3))
    adapter = SimpleNamespace(ns=ns)
    while True:
        try:
            for peers, tracker in zip(groups, trackers):
                path, settled = sample(adapter, peers)
                if tracker.update(path, settled):
                    flushed = []
                    try:
                        for index, node in peers:
                            ns(index, 'bridge', 'fdb', 'flush', 'dev', 'br0', 'dynamic'); flushed.append(node['name'])
                    except Exception:
                        tracker.dirty = True
                        report['last_event'] = {'complete': False, 'flushed': flushed}; raise
                    tracker.committed(path); report['repairs'] += 1
                    report['last_event'] = {'complete': True, 'bridges': flushed, 'dynamic_only': True, 'path': path}
            report['status'] = 'recovering' if any(t.dirty for t in trackers) else 'ready'; report['error'] = None
        except (RuntimeFailure, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
            for tracker in trackers: tracker.candidate = None
            report['status'] = 'degraded'; report['error'] = str(error)[-2000:]
        report['paths'] = [tracker.last for tracker in trackers]
        report['observed_monotonic'] = time.monotonic(); write_json(output, report)
        time.sleep(.5)


def start(manager):
    groups = components(manager.state['spec'])
    if not groups: return
    if manager.state.get('stp_carrier_worker'): raise RuntimeFailure('Carrier worker already recorded; refusing duplicate start')
    token = uuid.uuid4().hex; config = manager.directory / 'stp-carrier-config.json'
    scopes = {str(index): {'name': namespace(manager.state['spec'], index),
               'inode': (Path('/run/netns') / namespace(manager.state['spec'], index)).stat().st_ino}
              for peers in groups for index, _ in peers}
    config.write_text(json.dumps({'spec': manager.state['spec'], 'scopes': scopes, 'token': token,
                                 'output': str(manager.directory / 'stp-carrier.json')})); config.chmod(0o600)
    with (manager.directory / 'stp-carrier.log').open('ab') as log:
        process = subprocess.Popen([sys.executable, '-m', __name__, str(config)], stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, start_new_session=True)
    identity = process_identity(process.pid)
    if identity is None:
        process.kill(); process.wait(); raise RuntimeFailure('Cannot identify STP carrier worker')
    _PROCESSES[process.pid] = process
    manager.state['stp_carrier_worker'] = {'pid': process.pid, 'starttime': identity, 'token': token}; manager.save()
    until = time.monotonic() + 8
    while process.poll() is None and time.monotonic() < until:
        if observe(manager)['available']: return
        time.sleep(.05)
    stop(manager); raise RuntimeFailure('STP carrier worker did not become ready; see stp-carrier.log')


def stop(manager):
    record = manager.state.get('stp_carrier_worker')
    if not record: return
    if alive(record):
        if os.getpgid(record['pid']) != record['pid']: raise RuntimeFailure('Carrier worker process group changed; refusing signal')
        for sig, seconds in ((signal.SIGTERM, 2), (signal.SIGKILL, 1)):
            try: os.killpg(record['pid'], sig)
            except ProcessLookupError: pass
            until = time.monotonic() + seconds
            while alive(record) and time.monotonic() < until: time.sleep(.02)
            if not alive(record): break
        if alive(record): raise RuntimeFailure('Carrier worker remains alive; cleanup retained')
    child = _PROCESSES.pop(record['pid'], None)
    if child is not None: child.wait(timeout=1)
    else:
        try: os.waitpid(record['pid'], os.WNOHANG)
        except ChildProcessError: pass
    manager.state.pop('stp_carrier_worker', None); manager.save()


def observe(manager):
    record = manager.read().get('stp_carrier_worker'); result = {'available': False, 'source': 'Carrier/path observer and scoped dynamic FDB repair; no packet-delivery verdict'}
    try:
        report = json.loads((manager.directory / 'stp-carrier.json').read_text())
        if alive(record) and report.get('token') == record['token'] and 0 <= time.monotonic() - report['observed_monotonic'] <= 15:
            result.update(report); result.pop('token', None); result['available'] = report['status'] == 'ready'
    except (OSError, ValueError, KeyError, TypeError): pass
    return result


if __name__ == '__main__':
    worker(sys.argv[1])
