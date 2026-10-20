"""Native runtime adapters and an isolated veth/TAP fabric.

No host default route, physical interface, firewall or sysctl is changed.
Only explicitly requested start/stop commands create host resources.
"""
from contextlib import contextmanager
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import time

from .catalog import capabilities
from .spec import MIB, identifier, namespace, prefix, validate

STATE_ROOT = Path('/run/network-labs')


class RuntimeFailure(RuntimeError):
    pass


def run(args, *, check=True, timeout=30):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeFailure(f'{args[0]}: {result.stderr.strip() or result.stdout.strip() or result.returncode}')
    return result


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


def oci_config(spec, node, index, rootfs):
    caps = ['CAP_CHOWN', 'CAP_DAC_OVERRIDE', 'CAP_FOWNER', 'CAP_SETGID', 'CAP_SETUID',
            'CAP_KILL', 'CAP_NET_ADMIN', 'CAP_NET_RAW', 'CAP_NET_BIND_SERVICE']
    return {
        'ociVersion': '1.0.2', 'hostname': node['name'],
        'root': {'path': str(rootfs), 'readonly': False},
        'process': {'terminal': False, 'user': {'uid': 0, 'gid': 0}, 'args': node['command'],
                    'env': ['PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'TERM=xterm'],
                    'cwd': '/', 'noNewPrivileges': True,
                    'capabilities': {key: caps for key in ('bounding', 'effective', 'permitted')}},
        'mounts': [
            {'destination': '/proc', 'type': 'proc', 'source': 'proc', 'options': ['nosuid', 'noexec', 'nodev']},
            {'destination': '/dev', 'type': 'tmpfs', 'source': 'tmpfs', 'options': ['nosuid', 'strictatime', 'mode=755', 'size=4m']},
            {'destination': '/dev/pts', 'type': 'devpts', 'source': 'devpts', 'options': ['nosuid', 'noexec', 'newinstance', 'ptmxmode=0666', 'mode=0620']},
            {'destination': '/tmp', 'type': 'tmpfs', 'source': 'tmpfs', 'options': ['nosuid', 'nodev', 'size=8m']},
            {'destination': '/run', 'type': 'tmpfs', 'source': 'tmpfs', 'options': ['nosuid', 'nodev', 'size=8m']},
        ],
        'linux': {
            'namespaces': [{'type': n} for n in ('pid', 'mount', 'uts', 'ipc', 'cgroup')] +
                          [{'type': 'network', 'path': '/run/netns/' + namespace(spec, index)}],
            'cgroupsPath': f'/network-labs/{prefix(spec)}/{node["name"]}',
            'resources': {'memory': {'limit': node['memory_mib'] * MIB, 'swap': node['memory_mib'] * MIB},
                          'cpu': {'quota': 100000, 'period': 100000}, 'pids': {'limit': 128},
                          'devices': [{'allow': False, 'access': 'rwm'},
                                      {'allow': True, 'type': 'c', 'major': 1, 'minor': 3, 'access': 'rwm'},
                                      {'allow': True, 'type': 'c', 'major': 1, 'minor': 5, 'access': 'rwm'},
                                      {'allow': True, 'type': 'c', 'major': 1, 'minor': 8, 'access': 'rwm'},
                                      {'allow': True, 'type': 'c', 'major': 1, 'minor': 9, 'access': 'rwm'},
                                      {'allow': True, 'type': 'c', 'major': 5, 'minor': 0, 'access': 'rwm'},
                                      {'allow': True, 'type': 'c', 'major': 5, 'minor': 2, 'access': 'rwm'},
                                      {'allow': True, 'type': 'c', 'major': 136, 'access': 'rwm'}]},
            'maskedPaths': ['/proc/kcore', '/proc/keys', '/proc/timer_list', '/proc/sysrq-trigger'],
            'readonlyPaths': ['/proc/sys', '/proc/irq', '/proc/bus'],
        },
    }


def firecracker_config(node, kernel, disk):
    interface = ipaddress.IPv4Interface(node['interfaces']['eth0'])
    gateway = node.get('gateway', '')
    return {
        'boot-source': {'kernel_image_path': str(kernel),
                        'boot_args': f'console=ttyS0 reboot=k panic=1 pci=off root=/dev/vda rw ip={interface.ip}::{gateway}:{interface.netmask}:{node["name"]}:eth0:off'},
        'drives': [{'drive_id': 'rootfs', 'path_on_host': str(disk), 'is_root_device': True, 'is_read_only': False}],
        'machine-config': {'vcpu_count': 1, 'mem_size_mib': node['memory_mib']},
        'network-interfaces': [{'iface_id': 'eth0', 'host_dev_name': 'tap0'}],
    }


def plan(data):
    spec = validate(data)
    return {'name': spec['name'], 'budget_mib': spec['budget_mib'],
            'allocated_node_mib': sum(n['memory_mib'] for n in spec['nodes']),
            'reserve_mib': spec['reserve_mib'],
            'note': 'Allocation check, not measured total RAM. VM host overhead and GUI are not hard capped.',
            'nodes': [{'name': n['name'], 'runtime': n['runtime'], 'role': n['role'],
                       'namespace': namespace(spec, i), 'memory_mib': n['memory_mib'],
                       'interfaces': n['interfaces'], 'exec': n['runtime'] == 'oci'}
                      for i, n in enumerate(spec['nodes'])],
            'links': spec['links'],
            'limits': ['Native lab is separate from the model/Wasm canvas.',
                       'No automatic vendor firmware, CLI translation, VLAN/STP configuration or GUI replication.',
                       'Switch role is an untagged Linux bridge with STP off. Configure advanced features explicitly.',
                       'Wasm, libkrun, Unikraft, Hyperlight and netkit do not join this native fabric yet.']}


def static_busybox_rootfs(binary, target):
    """Build offline, and reject dynamically linked ELF before copying it."""
    binary, target = Path(binary), Path(target).resolve()
    raw = binary.read_bytes()
    if raw[:4] != b'\x7fELF' or raw[4] not in (1, 2) or raw[5] not in (1, 2):
        raise ValueError('Static BusyBox ELF binary required.')
    endian = '<' if raw[5] == 1 else '>'
    is64 = raw[4] == 2
    offset = struct.unpack_from(endian + ('Q' if is64 else 'I'), raw, 32 if is64 else 28)[0]
    size, count = struct.unpack_from(endian + 'HH', raw, 54 if is64 else 42)
    if any(struct.unpack_from(endian + 'I', raw, offset + i * size)[0] == 3 for i in range(count)):
        raise ValueError('BusyBox is dynamically linked; install busybox-static.')
    if target.exists():
        raise ValueError('Rootfs destination must not already exist.')
    target.mkdir(parents=True)
    for name in ('bin', 'sbin', 'etc', 'proc', 'sys', 'dev/pts', 'tmp', 'run', 'root'):
        (target / name).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(binary, target / 'bin/busybox'); (target / 'bin/busybox').chmod(0o755)
    for applet in ('sh', 'sleep', 'ping', 'ip', 'cat', 'ls', 'ps', 'hostname', 'httpd', 'wget', 'nc', 'echo', 'mkdir', 'kill'):
        (target / 'bin' / applet).symlink_to('busybox')
    (target / 'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n')
    return target


def process_identity(pid):
    try:
        # Process names can contain spaces and parentheses; field 22 is starttime.
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


class Manager:
    def __init__(self, name):
        self.name = identifier(name)
        self.directory = STATE_ROOT / self.name
        self.state = None

    @contextmanager
    def locked(self):
        if os.geteuid() != 0:
            raise RuntimeFailure('Native lifecycle requires sudo. Keep the desktop GUI unprivileged.')
        if STATE_ROOT.is_symlink():
            raise RuntimeFailure('Refusing symlink state directory.')
        STATE_ROOT.mkdir(mode=0o700, exist_ok=True)
        stat = STATE_ROOT.stat()
        if stat.st_uid != 0 or stat.st_mode & 0o022:
            raise RuntimeFailure('State directory must be owned by root and not writable by other users.')
        with (STATE_ROOT / (self.name + '.lock')).open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield self

    def save(self):
        write_json(self.directory / 'state.json', self.state)

    def read(self):
        if self.state is None:
            self.state = json.loads((self.directory / 'state.json').read_text())
        return self.state

    def crun(self, *args, **options):
        return run(['crun', '--root', self.directory / 'crun', *args], **options)

    def ns(self, index, *args, **options):
        return run(['ip', 'netns', 'exec', namespace(self.state['spec'], index), *args], **options)

    def preflight(self, spec):
        report = capabilities()
        installed = {r['id']: r['prerequisites_detected'] for r in report['runtimes']}
        if not report['host']['linux']:
            raise RuntimeFailure('Native fabric requires Linux.')
        for node in spec['nodes']:
            if not installed[node['runtime']]:
                raise RuntimeFailure(f'{node["runtime"]}: missing prerequisite. Run doctor; no fallback is used.')
            assets = ('rootfs',) if node['runtime'] == 'oci' else ('kernel', 'disk')
            for key in assets:
                asset = Path(node[key])
                if (key == 'rootfs' and not asset.is_dir()) or (key != 'rootfs' and not asset.is_file()):
                    raise RuntimeFailure(f'{node["name"]}: missing {key}: {asset}')
        existing = {line.split()[0] for line in run(['ip', 'netns', 'list']).stdout.splitlines() if line.strip()}
        if any(namespace(spec, i) in existing for i in range(len(spec['nodes']))):
            raise RuntimeFailure('A lab namespace already exists; refusing to adopt or delete it.')

    def start(self, data):
        spec = validate(data)
        if spec['name'] != self.name:
            raise ValueError('Manager/lab name mismatch.')
        if self.directory.exists():
            raise RuntimeFailure('Lab state already exists. Inspect status or stop it before restarting.')
        self.preflight(spec)
        self.directory.mkdir(mode=0o700)
        self.state = {'spec': spec, 'phase': 'starting', 'namespaces': [], 'mounts': [],
                      'containers': [], 'vms': [], 'host_links': []}
        self.save()
        try:
            for i, node in enumerate(spec['nodes']):
                ns = namespace(spec, i)
                run(['ip', 'netns', 'add', ns]); self.state['namespaces'].append(ns); self.save()
                self.ns(i, 'ip', 'link', 'set', 'lo', 'up')
                if node['runtime'] == 'firecracker':
                    self.ns(i, 'ip', 'tuntap', 'add', 'tap0', 'mode', 'tap')
                    self.ns(i, 'ip', 'link', 'add', 'vmbr0', 'type', 'bridge', 'stp_state', '0')
                    self.ns(i, 'ip', 'link', 'set', 'tap0', 'master', 'vmbr0')
                    self.ns(i, 'ip', 'link', 'set', 'tap0', 'up')
                    self.ns(i, 'ip', 'link', 'set', 'vmbr0', 'up')
            byname = {n['name']: (i, n) for i, n in enumerate(spec['nodes'])}
            for i, link in enumerate(spec['links']):
                peers = [f'{prefix(spec)}l{i}{side}' for side in ('a', 'b')]
                if any(run(['ip', 'link', 'show', 'dev', p], check=False).returncode == 0 for p in peers):
                    raise RuntimeFailure('Host link name collision; refusing to replace it.')
                run(['ip', 'link', 'add', peers[0], 'type', 'veth', 'peer', 'name', peers[1]])
                self.state['host_links'].extend(peers); self.save()
                for peer, (name, port) in zip(peers, link):
                    j, node = byname[name]
                    run(['ip', 'link', 'set', peer, 'netns', namespace(spec, j)])
                    self.ns(j, 'ip', 'link', 'set', peer, 'name', port)
                    self.ns(j, 'ip', 'link', 'set', port, 'up')
                    if node['runtime'] == 'firecracker':
                        self.ns(j, 'ip', 'link', 'set', port, 'master', 'vmbr0')
            connected = {tuple(e) for link in spec['links'] for e in link}
            for i, node in enumerate(spec['nodes']):
                if node['runtime'] == 'oci':
                    for port in node['interfaces']:
                        if (node['name'], port) not in connected:
                            self.ns(i, 'ip', 'link', 'add', port, 'type', 'dummy')
                            self.ns(i, 'ip', 'link', 'set', port, 'up')
                    if node['role'] == 'switch':
                        self.ns(i, 'ip', 'link', 'add', 'br0', 'type', 'bridge', 'stp_state', '0')
                        self.ns(i, 'ip', 'link', 'set', 'br0', 'up')
                        for port in node['interfaces']:
                            self.ns(i, 'ip', 'link', 'set', port, 'master', 'br0')
                    if node['role'] in ('router', 'firewall'):
                        self.ns(i, 'sysctl', '-w', 'net.ipv4.ip_forward=1')
                    for port, address in node['interfaces'].items():
                        if address:
                            self.ns(i, 'ip', 'addr', 'add', address, 'dev', port)
                    if node.get('gateway'):
                        self.ns(i, 'ip', 'route', 'add', 'default', 'via', node['gateway'])
                    self.start_oci(spec, node, i)
                else:
                    self.start_vm(node, i)
            self.state['phase'] = 'running'; self.save()
        except BaseException:
            self.state['phase'] = 'failed'; self.save()
            self.stop()
            raise

    def start_oci(self, spec, node, index):
        bundle = self.directory / node['name']; bundle.mkdir()
        for folder in ('upper', 'work', 'rootfs'):
            (bundle / folder).mkdir()
        options = f'lowerdir={Path(node["rootfs"]).resolve()},upperdir={bundle / "upper"},workdir={bundle / "work"}'
        run(['mount', '-t', 'overlay', 'overlay', '-o', options, bundle / 'rootfs'])
        self.state['mounts'].append(str(bundle / 'rootfs')); self.save()
        write_json(bundle / 'config.json', oci_config(spec, node, index, bundle / 'rootfs'))
        # Record before run: crun can create state before reporting a startup error.
        self.state['containers'].append(node['name']); self.save()
        self.crun('run', '--detach', '--bundle', bundle, node['name'])
        for command in node['startup']:
            self.crun('exec', node['name'], *command)

    def start_vm(self, node, index):
        bundle = self.directory / node['name']; bundle.mkdir()
        shutil.copyfile(node['disk'], bundle / 'rootfs.ext4')
        write_json(bundle / 'firecracker.json', firecracker_config(node, Path(node['kernel']).resolve(), bundle / 'rootfs.ext4'))
        with (bundle / 'console.log').open('ab') as log:
            process = subprocess.Popen(['ip', 'netns', 'exec', namespace(self.state['spec'], index),
                                        'firecracker', '--no-api', '--config-file', str(bundle / 'firecracker.json')],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        record = {'name': node['name'], 'pid': process.pid, 'starttime': process_identity(process.pid)}
        if record['starttime'] is None:
            process.kill(); process.wait()
            raise RuntimeFailure('Cannot record VMM process identity; launch cancelled.')
        self.state['vms'].append(record); self.save()
        # Surviving launch is not guest readiness; status explicitly preserves this distinction.
        try:
            code = process.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            return
        tail = (bundle / 'console.log').read_text(errors='replace')[-4000:]
        raise RuntimeFailure(f'Firecracker exited ({code}): {tail}')

    def execute(self, name, command, tty=False):
        state = self.read()
        node = next((n for n in state['spec']['nodes'] if n['name'] == name), None)
        if node is None or node['runtime'] != 'oci':
            raise RuntimeFailure('exec is available only for OCI nodes; Firecracker has no guest agent.')
        if state['phase'] != 'running':
            raise RuntimeFailure('Lab is not running.')
        from .spec import argv
        argv(command)
        return subprocess.call(['crun', '--root', str(self.directory / 'crun'), 'exec',
                                *(['--tty'] if tty else []), name, *command])

    def status(self):
        state = self.read(); nodes = []
        for node in state['spec']['nodes']:
            report = {'name': node['name'], 'runtime': node['runtime']}
            if node['runtime'] == 'oci':
                result = self.crun('state', node['name'], check=False)
                report['state'] = json.loads(result.stdout) if result.returncode == 0 else {'status': 'unavailable', 'detail': result.stderr.strip()}
                memory = Path('/sys/fs/cgroup/network-labs') / prefix(state['spec']) / node['name'] / 'memory.current'
                report['memory_current_bytes'] = int(memory.read_text()) if memory.exists() else None
            else:
                vm = next((v for v in state['vms'] if v['name'] == node['name']), None)
                report['vmm_alive'] = bool(vm and vm['starttime'] and process_identity(vm['pid']) == vm['starttime'])
                report['guest_ready'] = 'unverified; inspect console.log and test packets'
                report['console'] = str(self.directory / node['name'] / 'console.log')
            nodes.append(report)
        return {'name': self.name, 'phase': state['phase'], 'nodes': nodes,
                'memory_note': 'OCI cgroup memory only; not total app/VM/host usage.'}

    def stop(self):
        state = self.read(); errors = []
        for vm in state['vms']:
            if vm['starttime'] and process_identity(vm['pid']) == vm['starttime']:
                try:
                    os.kill(vm['pid'], signal.SIGKILL)
                    for _ in range(50):
                        if process_identity(vm['pid']) != vm['starttime']:
                            break
                        # Reap direct children, if stop follows a failed start in this process.
                        try:
                            os.waitpid(vm['pid'], os.WNOHANG)
                        except ChildProcessError:
                            pass
                        time.sleep(0.02)
                except ProcessLookupError:
                    pass
        for name in reversed(state['containers']):
            result = self.crun('delete', '--force', name, check=False)
            if result.returncode and self.crun('state', name, check=False).returncode == 0:
                errors.append(result.stderr.strip())
        if errors:
            raise RuntimeFailure('Containers still exist; cleanup state retained: ' + '; '.join(errors))
        for ns in reversed(state['namespaces']):
            result = run(['ip', 'netns', 'delete', ns], check=False)
            existing = {line.split()[0] for line in run(['ip', 'netns', 'list']).stdout.splitlines() if line.strip()}
            if result.returncode and ns in existing:
                errors.append(result.stderr.strip())
        for peer in state['host_links']:
            if run(['ip', 'link', 'show', 'dev', peer], check=False).returncode == 0:
                result = run(['ip', 'link', 'delete', peer], check=False)
                if result.returncode:
                    errors.append(result.stderr.strip())
        for mount in reversed(state['mounts']):
            if os.path.ismount(mount):
                result = run(['umount', mount], check=False)
                if result.returncode:
                    errors.append(result.stderr.strip())
        if errors:
            state['phase'] = 'cleanup-failed'; self.save()
            raise RuntimeFailure('Cleanup incomplete; state retained: ' + '; '.join(errors))
        shutil.rmtree(self.directory)
