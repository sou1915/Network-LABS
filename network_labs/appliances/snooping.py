"""Kernel DHCPv4 trust filtering plus owned, volatile packet observations."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from .spec import integer, keys, namespace

TABLE = 'network_labs_dhcp_snooping'
_PROCESSES = {}  # Reap children owned by this invocation; never serialized.


def validate_snooping(node):
    policy = node.setdefault('dhcp_snooping', None)
    if policy is None:
        return
    keys(policy, ('enabled', 'vlans', 'trusted'), 'DHCP snooping')
    if node['role'] != 'switch' or node['runtime'] != 'oci' or node.get('startup'):
        raise ValueError('DHCP snooping requires an OCI switch without untracked startup commands.')
    if type(policy.setdefault('enabled', False)) is not bool:
        raise ValueError('DHCP snooping enabled must be boolean.')
    vlans = policy.setdefault('vlans', [])
    trusted = policy.setdefault('trusted', [])
    if not isinstance(vlans, list) or len(vlans) > 256:
        raise ValueError('DHCP snooping VLANs: array required.')
    for vid in vlans:
        integer(vid, 1, 4094, 'DHCP snooping VLAN')
    if len(set(vlans)) != len(vlans) or set(vlans) - set(node['vlans']):
        raise ValueError('DHCP snooping VLANs must be unique and declared.')
    if not isinstance(trusted, list) or any(not isinstance(p, str) or p not in node['switchports'] for p in trusted) or len(set(trusted)) != len(trusted):
        raise ValueError('DHCP snooping trusted ports must be unique logical switch ports.')
    if policy['enabled'] and vlans:
        for port, setting in node['switchports'].items():
            # First backend is deliberately access-only, without tag/relay ambiguity.
            if setting['mode'] != 'access' or port not in node['interfaces']:
                raise ValueError('Enabled DHCP snooping currently requires physical access ports only; trunks/LACP are not supported.')
    policy['vlans'] = sorted(vlans); policy['trusted'] = sorted(trusted)


def effective(node):
    policy = node.get('dhcp_snooping')
    if not policy or not policy['enabled'] or not policy['vlans']:
        return None
    return {'ports': {p: v['vlan'] for p, v in node['switchports'].items() if v['vlan'] in policy['vlans']},
            'trusted': policy['trusted']}


def render(policy, replace=False):
    lines = [f'delete table bridge {TABLE}'] if replace else []
    if policy is not None:
        lines += [f'table bridge {TABLE} {{', 'chain ingress {', 'type filter hook prerouting priority -310; policy accept;']
        for port in sorted(policy['ports']):
            # Unsupported tagged traffic is refused, rather than bypassing trust.
            lines.append(f'iifname "{port}" ether type {{ 0x8100, 0x88a8 }} counter drop comment "tag:{port}";')
            if port in policy['trusted']:
                continue
            lines += [f'iifname "{port}" ip protocol udp ip frag-off & 0x3fff != 0 counter drop comment "fragment:{port}";',
                      f'iifname "{port}" ip protocol udp udp sport 67 counter drop comment "server:{port}";',
                      f'iifname "{port}" ip protocol udp udp dport {{ 67, 68 }} @th,64,8 2 counter drop comment "bootreply:{port}";']
        lines += ['}', '}']
    return '\n'.join(lines) + '\n'


def read_table(manager, index):
    tables = json.loads(manager.ns(index, 'nft', '-j', 'list', 'tables').stdout)
    exists = any(t.get('table', {}).get('family') == 'bridge' and t['table'].get('name') == TABLE for t in tables['nftables'])
    return json.loads(manager.ns(index, 'nft', '-j', '-n', 'list', 'table', 'bridge', TABLE).stdout) if exists else None


def apply(manager, index, node, previous=None):
    policy, old = effective(node), effective(previous) if previous else None
    if previous is not None and policy == old or policy is None and old is None:
        return
    from .firewall import fingerprint
    current = read_table(manager, index)
    if policy is not None or current is not None:
        target = manager.directory / (node['name'] + '.snooping.nft')
        target.write_text(render(policy, replace=current is not None)); target.chmod(0o600)
        manager.ns(index, 'nft', '-c', '-f', str(target)); manager.ns(index, 'nft', '-f', str(target))
    baselines = manager.state.setdefault('snooping_fingerprints', {})
    if policy is not None:
        baselines[node['name']] = fingerprint(read_table(manager, index))
    else:
        baselines.pop(node['name'], None)


def alive(record):
    from .runtime import process_identity
    if not record or process_identity(record['pid']) != record.get('starttime'):
        return False
    try:
        return Path(f"/proc/{record['pid']}/stat").read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except OSError:
        return False


def stop_worker(manager, name):
    from .runtime import RuntimeFailure
    record = manager.state.setdefault('snooping_workers', {}).get(name)
    if alive(record):
        try:
            os.kill(record['pid'], signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 2
        while alive(record) and time.monotonic() < deadline:
            time.sleep(0.02)
        if alive(record):
            try:
                os.kill(record['pid'], signal.SIGKILL)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 1
            while alive(record) and time.monotonic() < deadline:
                time.sleep(0.02)
        if alive(record):
            raise RuntimeFailure('DHCP observer still alive; cleanup retained.')
    if record:
        child = _PROCESSES.pop(record['pid'], None)
        if child is not None:
            child.wait(timeout=1)
        else:
            try:
                os.waitpid(record['pid'], os.WNOHANG)
            except ChildProcessError:
                pass
    manager.state['snooping_workers'].pop(name, None)
    manager.save()


def reconcile(manager, index, node, previous=None):
    from .runtime import RuntimeFailure, process_identity
    policy = effective(node)
    record = manager.state.get('snooping_workers', {}).get(node['name'])
    if previous is not None and policy == effective(previous) and (policy is None or alive(record)):
        return
    if record:
        stop_worker(manager, node['name'])
    if policy is None:
        return
    token = uuid.uuid4().hex
    ns = Path('/run/netns') / namespace(manager.state['spec'], index)
    output = manager.directory / (node['name'] + '.snooping.json')
    config = manager.directory / (node['name'] + '.snooping-config.json')
    config.write_text(json.dumps({**policy, 'node': node['name'], 'token': token, 'namespace': str(ns),
                                 'namespace_inode': ns.stat().st_ino, 'state': str(manager.directory / 'state.json'), 'output': str(output)}))
    config.chmod(0o600)
    with (manager.directory / (node['name'] + '.snooping.log')).open('ab') as log:
        process = subprocess.Popen(['ip', 'netns', 'exec', ns.name, sys.executable, '-m',
                                    'network_labs.appliances.snooping_worker', str(config)],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    start = process_identity(process.pid)
    if start is None:
        process.kill(); process.wait()
        raise RuntimeFailure('Cannot identify DHCP observer process.')
    _PROCESSES[process.pid] = process
    record = {'pid': process.pid, 'starttime': start, 'token': token}
    manager.state.setdefault('snooping_workers', {})[node['name']] = record; manager.save()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and process.poll() is None:
        try:
            observation = json.loads(output.read_text())
            if observation.get('token') == token and observation.get('status') == 'ready':
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.02)
    stop_worker(manager, node['name'])
    detail = (manager.directory / (node['name'] + '.snooping.log')).read_text(errors='replace')[-2000:]
    raise RuntimeFailure('DHCP observer failed readiness: ' + detail)


def observe(manager, index, node):
    from .firewall import fingerprint
    ruleset = read_table(manager, index)
    baseline = manager.read().get('snooping_fingerprints', {}).get(node['name'])
    conform = fingerprint(ruleset) == baseline if ruleset is not None and baseline else False
    record = manager.state.get('snooping_workers', {}).get(node['name'])
    result = {'source': 'Kernel DHCPv4 trust filter and passive request/ACK correlations',
              'policy_verified': conform, 'ruleset': ruleset, 'observer_available': False, 'bindings': None,
              'counters': [], 'note': 'Observed leases only; not proof of packet forwarding or endpoint installation. No DAI/IP Source Guard enforcement.'}
    for entry in (ruleset or {}).get('nftables', []):
        rule = entry.get('rule', {})
        for expr in rule.get('expr', []):
            if isinstance(expr, dict) and isinstance(expr.get('counter'), dict):
                result['counters'].append({'rule': rule.get('comment'), **expr['counter']})
    try:
        snapshot = json.loads((manager.directory / (node['name'] + '.snooping.json')).read_text())
        now = time.monotonic()
        if alive(record) and snapshot.get('token') == record['token'] and snapshot.get('status') == 'ready' and 0 <= now - snapshot['observed_monotonic'] <= 2:
            result.update(observer_available=True, capture_packets=snapshot.get('capture_packets'), capture_drops=snapshot['capture_drops'], events=snapshot['events'])
            if conform:
                result['bindings'] = [{**b, 'remaining_seconds': b['until'] - now} for b in snapshot['bindings'] if b['until'] > now]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return result
