"""Optional real Open vSwitch/RSTP inside owned OCI namespaces."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

PROGRAMS = {'ovsdb-server': '/usr/sbin/ovsdb-server', 'ovs-vswitchd': '/usr/sbin/ovs-vswitchd',
            'ovsdb-tool': '/usr/bin/ovsdb-tool', 'ovs-vsctl': '/usr/bin/ovs-vsctl', 'ovs-appctl': '/usr/bin/ovs-appctl'}
SCHEMA = '/usr/share/openvswitch/vswitch.ovsschema'
DB = 'unix:/run/ovs/db.sock'


def rootfs_assets():
    from .dns_rootfs import assets
    result = []
    for program, destination in PROGRAMS.items():
        source = shutil.which(program)
        if not source:
            raise ValueError('Open vSwitch rootfs requires installed trusted ' + program)
        result += assets(source, destination=destination, identity=program + ' (open vswitch)', version_args=('--version',))
    path = Path(SCHEMA)
    if path.stat().st_size > 1048576 or json.loads(path.read_text()).get('name') != 'Open_vSwitch':
        raise ValueError('Compatible trusted Open_vSwitch schema required.')
    result.append((path, Path(SCHEMA)))
    return sorted(set(result), key=lambda item: str(item[1]))


def validate_ovs(node):
    backend = node.setdefault('switch_backend', 'linux')
    if backend not in ('linux', 'ovs'):
        raise ValueError('switch_backend must be linux or ovs.')
    if backend == 'linux':
        return
    if node['role'] != 'switch' or node['runtime'] != 'oci' or node['spanning_tree']['mode'] != 'rstp':
        raise ValueError('OVS initial profile requires an OCI switch with mode rstp.')
    if node.get('startup') or node['dialect'] != 'linux' or node['port_channels'] or node['subinterfaces'] or node['shutdown']:
        raise ValueError('OVS requires Linux dialect, initially UP physical ports, and no startup, LACP or subinterfaces.')
    if any(node.get(key) for key in ('port_security', 'dhcp_snooping', 'arp_inspection', 'ip_source_guard', 'multicast', 'lldp', 'firewall')):
        raise ValueError('Linux-bridge security/multicast/LLDP policies are not integrated with OVS yet.')
    if not node['switchports'] or any(p['mode'] != 'access' for p in node['switchports'].values()):
        raise ValueError('Initial OVS RSTP profile accepts physical access ports only.')
    if node['spanning_tree']['hello_time'] != 2:
        raise ValueError('OVS RSTP profile uses its fixed 2-second hello interval.')
    if node['memory_mib'] < 64:
        raise ValueError('OVS requires a memory allocation of at least 64 MiB.')
    if any(p['bpdu_guard'] or p['root_guard'] for p in node['spanning_tree']['ports'].values()):
        raise ValueError('Kernel BPDU/Root Guard flags are not OVS RSTP features.')


def vsctl(manager, name, *args, **options):
    return manager.crun('exec', name, PROGRAMS['ovs-vsctl'], '--db=' + DB, '--timeout=3', *args, **options)


def value(cell):
    if isinstance(cell, list) and len(cell) == 2 and cell[0] == 'map':
        return dict(cell[1])
    if isinstance(cell, list) and len(cell) == 2 and cell[0] == 'set':
        return cell[1]
    return cell


def table(manager, name, kind, columns):
    # Constant schema columns; bound stdout in the node, not after allocation.
    command = (PROGRAMS['ovs-vsctl'] + ' --db=' + DB + ' --timeout=3 --format=json --columns=' + columns +
               ' list ' + kind + ' | /bin/busybox head -c 1048577')
    try:
        result = manager.crun('exec', name, '/bin/sh', '-c', command, check=False, timeout=5)
        if result.returncode or len(result.stdout.encode()) > 1048576:
            return None
        data = json.loads(result.stdout)
        if data['headings'] != columns.split(',') or len(data['data']) > 256:
            return None
        return [dict(zip(data['headings'], map(value, row), strict=True)) for row in data['data']]
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return None


def snapshot(manager, name):
    bridge = table(manager, name, 'Bridge', 'name,datapath_type,stp_enable,rstp_enable,fail_mode,controller,other_config,rstp_status')
    ports = table(manager, name, 'Port', 'name,tag,trunks,vlan_mode,other_config,rstp_status,rstp_statistics')
    try:
        alive = manager.crun('exec', name, PROGRAMS['ovs-appctl'], '-t', '/run/ovs/vswitchd.ctl', 'version', check=False, timeout=4).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        alive = False
    return {'bridges': bridge, 'ports': ports, 'controller_available': alive}


def fingerprint(actual):
    if not actual.get('controller_available') or actual.get('bridges') is None or actual.get('ports') is None:
        return None
    # Exclude protocol runtime state/counters; never persist learned state.
    clean = {kind: sorted(({k: v for k, v in row.items() if k not in ('rstp_status', 'rstp_statistics')}
                           for row in actual[kind]), key=lambda row: row['name']) for kind in ('bridges', 'ports')}
    return hashlib.sha256(json.dumps(clean, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def transaction(node):
    p = node['spanning_tree']
    args = ['--', 'add-br', 'br0', '--', 'set', 'Bridge', 'br0', 'datapath_type=system',
            'fail_mode=standalone', 'stp_enable=false', 'rstp_enable=true',
            'other_config:rstp-priority=' + str(p['priority']), 'other_config:rstp-force-protocol-version=2',
            'other_config:rstp-max-age=' + str(p['max_age']), 'other_config:rstp-forward-delay=' + str(p['forward_delay'])]
    for port, membership in node['switchports'].items():
        settings = p['ports'][port]
        args += ['--', 'add-port', 'br0', port, '--', 'set', 'Port', port, 'vlan_mode=access',
                 'tag=' + str(membership['vlan']), 'other_config:rstp-enable=true',
                 'other_config:rstp-port-priority=' + str(settings['priority']),
                 'other_config:rstp-path-cost=' + str(settings['cost'])]
    return args


def _start_servers(manager):
    from .runtime import RuntimeFailure
    for node in manager.state['spec']['nodes']:
        if node.get('switch_backend') != 'ovs':
            continue
        name = node['name']; log = manager.directory / name / 'ovs.log'
        manager.crun('exec', name, '/bin/mkdir', '-p', '/run/ovs')
        manager.crun('exec', name, PROGRAMS['ovsdb-tool'], 'create', '/run/ovs/conf.db', SCHEMA, log=log)
        manager.crun('exec', '--detach', name, PROGRAMS['ovsdb-server'], '/run/ovs/conf.db',
                     '--remote=punix:/run/ovs/db.sock', '--unixctl=/run/ovs/db.ctl', '--pidfile=/run/ovs/db.pid', '--no-chdir', log=log)
        deadline = time.monotonic() + 10
        while vsctl(manager, name, '--no-wait', 'init', check=False).returncode:
            if time.monotonic() >= deadline:
                raise RuntimeFailure('Owned OVSDB did not become ready: ' + log.read_text(errors='replace')[-2000:])
            time.sleep(0.1)
        vsctl(manager, name, '--no-wait', 'set', 'Open_vSwitch', '.', 'other_config:n-handler-threads=1', 'other_config:n-revalidator-threads=1')
        manager.crun('exec', '--detach', name, PROGRAMS['ovs-vswitchd'], DB, '--unixctl=/run/ovs/vswitchd.ctl',
                     '--pidfile=/run/ovs/vswitchd.pid', '--no-chdir', log=log)
        vsctl(manager, name, *transaction(node))
        index = next(i for i, n in enumerate(manager.state['spec']['nodes']) if n['name'] == name)
        manager.ns(index, 'ip', 'link', 'set', 'br0', 'up')
        actual = snapshot(manager, name)
        digest = fingerprint(actual)
        if not digest:
            raise RuntimeFailure('Owned OVS state unavailable: ' + log.read_text(errors='replace')[-2000:])
        manager.state.setdefault('ovs_baselines', {})[name] = digest
        manager.save()


def observe(manager, node):
    actual = snapshot(manager, node['name'])
    actual.update(source='Actual container OVSDB/RSTP status and daemon control socket',
                  policy_verified=fingerprint(actual) is not None and fingerprint(actual) == manager.state.get('ovs_baselines', {}).get(node['name']))
    return actual


def tree(actual):
    bridge = next((row for row in actual.get('bridges') or [] if row['name'] == 'br0'), {})
    status = bridge.get('rstp_status', {})
    ports = {row['name']: {'state': row.get('rstp_status', {}).get('rstp_port_state', '').lower() or None,
                           'role': row.get('rstp_status', {}).get('rstp_port_role'),
                           'status': row.get('rstp_status'), 'statistics': row.get('rstp_statistics')}
             for row in actual.get('ports') or [] if row['name'] != 'br0'}
    root, own = status.get('rstp_root_id'), status.get('rstp_bridge_id')
    return {'source': 'Open vSwitch RSTP status; no kernel STP or computed topology tree',
            'protocol': 'rstp' if actual['controller_available'] and bridge.get('rstp_enable') is True and status else 'unavailable',
            'bridge_id': own, 'root_id': root, 'is_root': bool(root and own and root == own and actual['controller_available']),
            'root_port': next((p for p, data in ports.items() if data['role'] == 'Root'), None),
            'root_path_cost': status.get('rstp_root_path_cost'), 'ports': ports,
            'note': 'Sequential daemon reports, not packet-delivery proof, a runtime snapshot or global convergence certificate.'}


def start_servers(manager):
    from .runtime import RuntimeFailure
    try:
        _start_servers(manager)
    except Exception as exc:
        details = []
        for node in manager.state['spec']['nodes']:
            if node.get('switch_backend') == 'ovs':
                log = manager.directory / node['name'] / 'ovs.log'
                if log.exists():
                    details.append(node['name'] + ': ' + log.read_text(errors='replace')[-3000:])
        raise RuntimeFailure(str(exc) + '\n' + '\n'.join(details)) from exc
