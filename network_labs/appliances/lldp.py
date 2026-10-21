"""Real lldpd/lldpcli inside OCI; neighbor evidence is never inferred from links."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from .spec import keys, integer
from .service_config import observe_config

DAEMON = '/usr/sbin/lldpd'
CLIENT = '/usr/sbin/lldpcli'
LIMIT = 1048576


def rootfs_assets(daemon, client):
    from .dns_rootfs import assets
    # Support the distro privilege-separation profile explicitly, without
    # guessing arbitrary users/paths or importing host account databases.
    result = subprocess.run([str(daemon), '-vv'], text=True, capture_output=True, timeout=5)
    fields = dict(re.findall(r'^Privilege separation (user|group|chroot):\s*(\S+)\s*$', result.stdout, re.MULTILINE))
    if result.returncode or fields.get('user') != '_lldpd' or fields.get('group') != '_lldpd' or fields.get('chroot') not in ('/run/lldpd', '/var/run/lldpd'):
        raise ValueError('LLDP requires the Debian/Ubuntu _lldpd account and /run/lldpd privilege-separation build profile; observed: ' + repr(fields))
    planned = assets(daemon, destination=DAEMON, identity='lldpd ', version_args=('-v',))
    planned += assets(client, destination=CLIENT, identity='lldpcli ', version_args=('-v',))
    return sorted(set(planned), key=lambda item: str(item[1]))


def validate_lldp(node):
    policy = node.setdefault('lldp', None)
    if policy is None:
        return
    keys(policy, ('ports', 'tx_interval', 'tx_hold'), 'LLDP')
    if node['runtime'] != 'oci' or node.get('startup') or node.get('port_channels'):
        raise ValueError('LLDP requires an OCI node without untracked startup or LACP bundles.')
    ports = policy.get('ports')
    if not isinstance(ports, list) or not ports or len(ports) > 16 or any(not isinstance(p, str) or p not in node['interfaces'] for p in ports) or len(set(ports)) != len(ports):
        raise ValueError('LLDP ports require 1..16 unique declared physical interfaces.')
    if node['role'] == 'switch' and any(node['switchports'][p]['mode'] != 'access' for p in ports):
        raise ValueError('Initial LLDP switch profile supports physical access ports only.')
    policy['ports'] = sorted(ports)
    integer(policy.setdefault('tx_interval', 2), 1, 60, 'LLDP transmit interval')
    integer(policy.setdefault('tx_hold', 3), 2, 10, 'LLDP transmit hold')


def config(node):
    p = node['lldp']
    return (f'configure system hostname {node["name"]}\n'
            'configure system description Network-LABS\n'
            'configure lldp portidsubtype ifname\n'
            f'configure lldp tx-interval {p["tx_interval"]}\n'
            f'configure lldp tx-hold {p["tx_hold"]}\n')


def prepare_files(bundle, node):
    if node.get('lldp') is not None:
        (Path(bundle) / 'files/lldpd.conf').write_text(config(node))


def read_cli(manager, name, what, fmt='json0'):
    if what not in ('neighbors details', 'configuration', 'interfaces') or fmt not in ('json0', 'keyvalue'):
        raise ValueError('Unsupported read-only LLDP observation.')
    try:
        # Literal commands, no user shell interpolation. A closed pipe bounds
        # output inside the node even for a large/hostile neighbor table.
        result = manager.crun('exec', name, '/bin/sh', '-c',
                              f'{CLIENT} -u /run/lldpd.socket -f {fmt} show {what} | /bin/busybox head -c {LIMIT + 1}', check=False, timeout=5)
        if result.returncode or len(result.stdout.encode()) > LIMIT:
            return None
        if fmt == 'keyvalue':
            if not result.stdout.strip():
                return None
            return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        value = json.loads(result.stdout)
        return value if isinstance(value, dict) and value else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def global_fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest() if value else None


def port_status(values):
    if values is None:
        return None
    return {parts[1]: value for key, value in values.items()
            if len(parts := key.split('.')) == 3 and parts[0] == 'lldp' and parts[2] == 'status'}


def start_servers(manager):
    from .runtime import RuntimeFailure
    for node in manager.state['spec']['nodes']:
        if node.get('lldp') is None:
            continue
        log = manager.directory / node['name'] / 'lldp.log'
        # Explicit path/pattern/identity and no default configuration imports.
        manager.crun('exec', node['name'], '/bin/mkdir', '-p', '/run/lldpd')
        manager.crun('exec', '--detach', node['name'], DAEMON, '-dd', '-l', '-k', '-i',
                     '-I', ','.join('!!' + p for p in node['lldp']['ports']) + ',!*',
                     '-C', '!*', '-m', '!*', '-u', '/run/lldpd.socket', '-p', '/run/lldpd.pid', '-L', '', log=log)
        deadline = time.monotonic() + 8
        while read_cli(manager, node['name'], 'configuration') is None:
            if time.monotonic() >= deadline:
                raise RuntimeFailure(node['name'] + ': LLDP control socket unavailable: ' + log.read_text(errors='replace')[-2000:])
            time.sleep(0.1)
        manager.crun('exec', node['name'], CLIENT, '-u', '/run/lldpd.socket', '-c', '/lab/lldpd.conf', log=log)
        manager.crun('exec', node['name'], CLIENT, '-u', '/run/lldpd.socket', 'resume', log=log)
        deadline = time.monotonic() + 8
        while True:
            actual = read_cli(manager, node['name'], 'configuration')
            statuses = port_status(read_cli(manager, node['name'], 'interfaces', 'keyvalue'))
            if actual and statuses and set(statuses) == set(node['lldp']['ports']):
                break
            if time.monotonic() >= deadline:
                raise RuntimeFailure(node['name'] + ': LLDP interface/configuration observation unavailable: ' + repr(statuses) + '; ' + json.dumps(actual)[:1000] + '\n' + log.read_text(errors='replace')[-2000:])
            time.sleep(0.1)
        manager.state.setdefault('lldp_baselines', {})[node['name']] = {
            'global': global_fingerprint(actual), 'port_status': statuses}
        manager.save()


def observe(manager, node):
    file = observe_config(manager, node['name'], '/lab/lldpd.conf', config(node))
    actual = read_cli(manager, node['name'], 'configuration')
    statuses = port_status(read_cli(manager, node['name'], 'interfaces', 'keyvalue'))
    baseline = manager.state.get('lldp_baselines', {}).get(node['name'], {})
    global_ok = actual is not None and global_fingerprint(actual) == baseline.get('global')
    statuses_ok = statuses is not None and all(baseline.get('port_status', {}).get(p) == s for p, s in statuses.items())
    return {**file, 'source': 'Actual container lldpcli queries; not declared topology discovery',
            'policy_verified': file['configuration_verified'] and global_ok and statuses_ok,
            'global_configuration_verified': global_ok, 'port_status': statuses,
            'neighbors': read_cli(manager, node['name'], 'neighbors details'),
            'note': 'Neighbor advertisements are unauthenticated observations, not packet delivery or endpoint health. Missing/down interfaces may be absent; no inferred neighbors, CDP, LLDP-MED, or persistent neighbor cache.'}
