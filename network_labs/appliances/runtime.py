"""Native runtime adapters and an isolated veth/TAP fabric.

No host default route, physical interface, firewall or sysctl is changed.
Only explicitly requested start/stop commands create host resources.
"""
from contextlib import contextmanager
import fcntl
import copy
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
CONFIG_ROOT = Path('/var/lib/network-labs')


class RuntimeFailure(RuntimeError):
    pass


def run(args, *, check=True, timeout=30, log=None, input_text=None):
    command = [str(a) for a in args]
    if log is None:
        options = {'input': input_text} if input_text is not None else {}
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, **options)
    else:
        if input_text is not None:
            raise ValueError('Stdin payloads cannot be combined with persistent command logs.')
        # Detached init processes and daemons can inherit stdout/stderr. Pipes
        # would keep communicate() waiting for the lifetime of the container.
        with Path(log).open('a') as output:
            child = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT, text=True, timeout=timeout)
        result = subprocess.CompletedProcess(command, child.returncode, '', '')
    if check and result.returncode:
        detail = Path(log).read_text(errors='replace')[-4000:] if log else result.stderr.strip() or result.stdout.strip()
        raise RuntimeFailure(f'{args[0]}: {detail or result.returncode}')
    return result


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


def oci_config(spec, node, index, rootfs):
    caps = ['CAP_CHOWN', 'CAP_DAC_OVERRIDE', 'CAP_FOWNER', 'CAP_SETGID', 'CAP_SETUID',
            'CAP_KILL', 'CAP_NET_ADMIN', 'CAP_NET_RAW', 'CAP_NET_BIND_SERVICE']
    if node.get('lldp') is not None:
        caps.append('CAP_SYS_CHROOT')
    management_mounts = []
    management = node.get('management') or {}
    if management.get('ssh_keys') or management.get('telnet_password_hash'):
        management_mounts.append({'destination': '/etc/passwd', 'type': 'bind', 'source': str(Path(rootfs).parent / 'files/management-passwd'), 'options': ['bind', 'ro', 'nosuid', 'nodev']})
        management_mounts.append({'destination': '/etc/group', 'type': 'bind', 'source': str(Path(rootfs).parent / 'files/management-group'), 'options': ['bind', 'ro', 'nosuid', 'nodev']})
    if management.get('ssh_keys'):
        management_mounts.append({'destination': '/home/lab/.ssh/authorized_keys', 'type': 'bind', 'source': str(Path(rootfs).parent / 'files/authorized_keys'), 'options': ['bind', 'ro', 'nosuid', 'nodev']})
    return {
        'ociVersion': '1.0.2', 'hostname': node['name'],
        'root': {'path': str(rootfs), 'readonly': False},
        'process': {'terminal': False, 'user': {'uid': 0, 'gid': 0}, 'args': node['command'],
                    'env': ['PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'TERM=xterm'],
                    'cwd': '/', 'noNewPrivileges': True,
                    'capabilities': {key: caps for key in ('bounding', 'effective', 'permitted')}},
        'mounts': management_mounts + ([{'destination': '/etc/resolv.conf', 'type': 'bind',
                     'source': str(Path(rootfs).parent / 'files' / 'resolv.conf'),
                     'options': ['bind', 'ro', 'nosuid', 'nodev']}] if node.get('resolvers') else []) + [
            {'destination': '/lab', 'type': 'bind', 'source': str(Path(rootfs).parent / 'files'),
             'options': ['bind', 'ro', 'nosuid', 'nodev']},
            {'destination': '/proc', 'type': 'proc', 'source': 'proc', 'options': ['nosuid', 'noexec', 'nodev']},
            {'destination': '/dev', 'type': 'tmpfs', 'source': 'tmpfs', 'options': ['nosuid', 'strictatime', 'mode=755', 'size=4m']},
            {'destination': '/dev/pts', 'type': 'devpts', 'source': 'devpts', 'options': ['nosuid', 'noexec', 'newinstance', 'ptmxmode=0666', 'mode=0620']},
            {'destination': '/tmp', 'type': 'tmpfs', 'source': 'tmpfs', 'options': ['nosuid', 'nodev', 'mode=1777', 'size=8m']},
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
                       'No automatic vendor firmware or complete vendor GUI/CLI replication.',
                       'VLAN access/trunk, dot1Q, LACP and classic kernel STP are native; RSTP/PVST/MSTP are not implemented.',
                       'Wasm, libkrun, Unikraft, Hyperlight and netkit do not join this native fabric yet.']}


def static_busybox_rootfs(binary, target, *, dnsmasq=None, lldpd=None, lldpcli=None, openvswitch=False, bird=None, birdc=None, dropbear=None, ssh_relay=None, rsyslog=None, rsyslog_modules=None, snmpd=None, snmptrapd=None, chronyd=None, chronyc=None, freeradius=None, freeradius_modules=None, freeradius_dictionaries=None):
    """Build from static BusyBox, optionally adding trusted dnsmasq and its ELF libraries."""
    binary, target = Path(binary), Path(target).resolve()
    raw = binary.read_bytes()
    if len(raw) < 64 or raw[:4] != b'\x7fELF' or raw[4] not in (1, 2) or raw[5] not in (1, 2):
        raise ValueError('Static BusyBox ELF binary required.')
    endian = '<' if raw[5] == 1 else '>'
    is64 = raw[4] == 2
    offset = struct.unpack_from(endian + ('Q' if is64 else 'I'), raw, 32 if is64 else 28)[0]
    size, count = struct.unpack_from(endian + 'HH', raw, 54 if is64 else 42)
    if size < 4 or offset + count * size > len(raw):
        raise ValueError('Malformed ELF program header table.')
    if any(struct.unpack_from(endian + 'I', raw, offset + i * size)[0] == 3 for i in range(count)):
        raise ValueError('BusyBox is dynamically linked; install busybox-static.')
    if target.exists():
        raise ValueError('Rootfs destination must not already exist.')
    from .dns_rootfs import assets as dns_assets
    additions = dns_assets(dnsmasq) if dnsmasq is not None else []
    if (lldpd is None) != (lldpcli is None):
        raise ValueError('Provide both --lldpd and --lldpcli.')
    lldp_additions = []
    if lldpd is not None:
        from .lldp import rootfs_assets
        lldp_additions = rootfs_assets(lldpd, lldpcli)
    ovs_additions = []
    if openvswitch:
        from .ovs import rootfs_assets as ovs_assets
        ovs_additions = ovs_assets()
    if (bird is None) != (birdc is None):
        raise ValueError('Provide both --bird and --birdc.')
    bird_additions = []
    if bird is not None:
        from .ospf import rootfs_assets
        bird_additions = rootfs_assets(bird, birdc)
    management_additions = []
    if dropbear is not None:
        from .management import rootfs_assets
        management_additions = rootfs_assets(dropbear)
    if ssh_relay is not None:
        if dropbear is None: raise ValueError('SSH relay rootfs assets require --dropbear.')
        from .ssh_access import relay_assets
        management_additions += relay_assets(ssh_relay)
    collector_additions = []
    if rsyslog_modules is not None and rsyslog is None:
        raise ValueError('--rsyslog-modules requires --rsyslog.')
    if rsyslog is not None:
        from .syslog_server import rootfs_assets
        collector_additions = rootfs_assets(rsyslog, rsyslog_modules)
    snmp_additions = []
    if snmpd is not None:
        from .snmp import rootfs_assets
        snmp_additions = rootfs_assets(snmpd)
    notification_additions = []
    if snmptrapd is not None:
        from .snmp_notifications import rootfs_assets
        notification_additions = rootfs_assets(snmptrapd)
    ntp_additions = []
    if chronyc is not None and chronyd is None:
        raise ValueError('--chronyc requires --chronyd.')
    if chronyd is not None:
        from .ntp_server import rootfs_assets
        ntp_additions = rootfs_assets(chronyd)
    if chronyc is not None:
        from .ntp_server import client_rootfs_assets
        ntp_additions += client_rootfs_assets(chronyc)
    radius_additions = []
    if any(value is not None for value in (freeradius, freeradius_modules, freeradius_dictionaries)):
        if not all(value is not None for value in (freeradius, freeradius_modules, freeradius_dictionaries)):
            raise ValueError('--freeradius requires matching --freeradius-modules and --freeradius-dictionaries.')
        from .radius_rootfs import rootfs_assets as radius_assets
        radius_additions = radius_assets(freeradius, freeradius_modules, freeradius_dictionaries)
    target.mkdir(parents=True)
    for name in ('bin', 'sbin', 'etc', 'proc', 'sys', 'dev/pts', 'tmp', 'run', 'root', 'home/lab/.ssh', 'etc/dropbear'):
        (target / name).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(binary, target / 'bin/busybox'); (target / 'bin/busybox').chmod(0o755)
    for applet in ('sh', 'sleep', 'ping', 'ip', 'cat', 'ls', 'ps', 'hostname', 'httpd', 'wget', 'nc', 'echo', 'mkdir', 'kill', 'udhcpc', 'udhcpd', 'ipcalc', 'nslookup', 'login', 'telnet', 'logger'):
        (target / 'bin' / applet).symlink_to('busybox')
    (target / 'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n')
    (target / 'etc/group').write_text('root:x:0:\n')
    for source, destination in additions + lldp_additions + ovs_additions + bird_additions + management_additions + collector_additions + snmp_additions + notification_additions + ntp_additions + radius_additions:
        path = target / str(destination).lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
        path.chmod(0o755)
    if ovs_additions:
        write_json(target / 'etc/network-labs-ovs-assets.json', {'files': [str(p) for _, p in ovs_additions]})
    if lldp_additions:
        with (target / 'etc/passwd').open('a') as account:
            account.write('_lldpd:x:65534:65534:LLDP:/run/lldpd:/bin/sh\n')
        with (target / 'etc/group').open('a') as account:
            account.write('_lldpd:x:65534:\n')
        write_json(target / 'etc/network-labs-lldp-assets.json', {'files': [str(path) for _, path in lldp_additions]})
    if notification_additions:
        write_json(target / 'etc/network-labs-snmp-notification-assets.json', {'binary': '/usr/lib/network-labs/snmptrapd', 'files': [str(destination) for _, destination in notification_additions]})
    if snmp_additions:
        write_json(target / 'etc/network-labs-snmp-assets.json', {'binary': '/usr/lib/network-labs/snmpd', 'files': [str(destination) for _, destination in snmp_additions]})
    if collector_additions:
        write_json(target / 'etc/network-labs-syslog-assets.json', {'files': [str(destination) for _, destination in collector_additions]})
    if management_additions:
        write_json(target / 'etc/network-labs-management-assets.json', {'binary': '/usr/sbin/dropbear', 'files': [str(destination) for _, destination in management_additions]})
    if additions:
        write_json(target / 'etc/network-labs-dns-assets.json', {'binary': '/usr/sbin/dnsmasq', 'files': [str(destination) for _, destination in additions]})
    if radius_additions:
        write_json(target / 'etc/network-labs-radius-assets.json', {'files': [str(destination) for _, destination in radius_additions]})
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
            try:
                raw = (self.directory / 'state.json').read_text()
            except FileNotFoundError as error:
                if self.directory.exists():
                    raise RuntimeFailure(
                        f'Lab {self.name}: répertoire présent mais state.json absent. '
                        'État incomplet ; ne supprimez pas le répertoire et ne recréez pas '
                        'le lab avant de vérifier ses ressources existantes.'
                    ) from error
                message = (
                    f'Lab {self.name}: aucun état actif trouvé. '
                    'Le lab doit être démarré avant cette commande.\n'
                    'Depuis le dossier du projet, listez les manifestes disponibles :\n'
                    '  python3 -m network_labs.appliances manifests\n'
                    f'Puis démarrez le fichier associé au lab "{self.name}".'
                )
                if (CONFIG_ROOT / self.name / 'startup.json').is_file():
                    message += (
                        '\nUne configuration startup enregistrée est disponible. '
                        'Pour la restaurer :\n'
                        f'  sudo python3 -m network_labs.appliances restore {self.name}'
                    )
                raise RuntimeFailure(message) from error
            self.state = json.loads(raw)
            self.state['spec'] = validate(self.state['spec'])
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
        for node in spec['nodes']:
            if node.get('ntp_server') and not (Path(node['rootfs']) / 'usr/lib/network-labs/chronyd').is_file():
                raise RuntimeFailure(node['name'] + ': NTP requires a rootfs built with --chronyd.')
            if node.get('radius_server') and any(not (Path(node['rootfs']) / path).is_file() for path in
                    ('usr/lib/network-labs/freeradius/server', 'usr/lib/network-labs/freeradius/modules/rlm_pap.so',
                     'usr/lib/network-labs/freeradius/dictionary/dictionary', 'etc/network-labs-radius-assets.json')):
                raise RuntimeFailure(node['name'] + ': RADIUS requires a rootfs built with --freeradius and matching modules/dictionaries.')
            if (node.get('radius_server') or {}).get('accounting') and not (Path(node['rootfs']) / 'usr/lib/network-labs/freeradius/modules/rlm_exec.so').is_file():
                raise RuntimeFailure(node['name'] + ': RADIUS accounting requires rebuilding the rootfs with the trusted rlm_exec module.')
            if (node.get('radius_server') or {}).get('accounting') and not (Path(node['rootfs']) / 'usr/lib/network-labs/freeradius/flock').is_file():
                raise RuntimeFailure(node['name'] + ': RADIUS accounting requires rebuilding the rootfs with trusted util-linux flock.')
            if node.get('snmp_receiver') and not (Path(node['rootfs']) / 'usr/lib/network-labs/snmptrapd').is_file():
                raise RuntimeFailure(node['name'] + ': SNMP receiver requires a rootfs built with --snmptrapd.')
            if node.get('snmp_agent') and not (Path(node['rootfs']) / 'usr/lib/network-labs/snmpd').is_file():
                raise RuntimeFailure(node['name'] + ': SNMP requires a rootfs built with --snmpd.')
            if node.get('syslog_server') and any(not (Path(node['rootfs']) / path).is_file() for path in ('usr/lib/network-labs/rsyslogd', 'usr/lib/network-labs/rsyslog/imudp.so', 'usr/lib/network-labs/rsyslog/lmnet.so')):
                raise RuntimeFailure(node['name'] + ': Syslog collector requires a rootfs built with --rsyslog.')
            if 'shell' in ((node.get('management') or {}).get('ssh_actions') or []) and not (Path(node['rootfs']) / 'usr/lib/network-labs/ssh-radius-client').is_file():
                raise RuntimeFailure(node['name'] + ': RADIUS SSH shell requires a rootfs built with the trusted --ssh-relay executable.')
            if (node.get('management') or {}).get('ssh_keys') and not (Path(node['rootfs']) / 'usr/sbin/dropbear').is_file():
                raise RuntimeFailure(node['name'] + ': SSH requires a trusted rootfs built with --dropbear.')
            if (node.get('ospf') is not None or node.get('ospfv3') is not None or node.get('dhcpv6_relay') is not None) and any(not (Path(node['rootfs']) / path).is_file() for path in ('usr/sbin/bird', 'usr/sbin/birdc')):
                raise RuntimeFailure(node['name'] + ': Managed BIRD routing/RA requires a rootfs built with --bird and --birdc.')
            if (node.get('dns_server') is not None or node.get('tftp_server') is not None or node.get('dhcp_relay') is not None or node.get('dhcp_pools') is not None or node.get('router_advertisements') or node.get('dhcpv6_relay') or node.get('dhcpv6_remote_server')) and not (Path(node['rootfs']) / 'usr/sbin/dnsmasq').is_file():
                raise RuntimeFailure(node['name'] + ': DNS/DHCP/RA/TFTP requires a rootfs built with --dnsmasq or an explicitly supplied compatible /usr/sbin/dnsmasq.')
        for node in spec['nodes']:
            if node.get('lldp') is not None and any(not (Path(node['rootfs']) / path).is_file() for path in ('usr/sbin/lldpd', 'usr/sbin/lldpcli', 'etc/network-labs-lldp-assets.json')):
                raise RuntimeFailure(node['name'] + ': LLDP requires a rootfs built with --lldpd and --lldpcli.')
        if any(n.get('switch_backend') == 'ovs' for n in spec['nodes']):
            if not Path('/sys/module/openvswitch').exists():
                raise RuntimeFailure('OVS requires a preloaded openvswitch module: sudo modprobe openvswitch. No module is auto-loaded.')
            for node in spec['nodes']:
                if node.get('switch_backend') == 'ovs' and not (Path(node['rootfs']) / 'etc/network-labs-ovs-assets.json').is_file():
                    raise RuntimeFailure(node['name'] + ': OVS requires a rootfs built with --openvswitch.')
        if any(n.get('firewall') is not None or n.get('port_security') or (n.get('dhcp_snooping') or {}).get('enabled') for n in spec['nodes']) and not shutil.which('nft'):
            raise RuntimeFailure('Managed firewall/port security/DHCP snooping requires host nftables (nft).')
        if any(n['port_channels'] for n in spec['nodes']) and not Path('/sys/module/bonding').exists():
            raise RuntimeFailure('LACP requires a preloaded bonding driver. Run sudo modprobe bonding max_bonds=0 first; the manager will not auto-load it.')
        if any((n.get('snmp_agent') or {}).get('link_events') for n in spec['nodes']) and not shutil.which('nft'):
            raise RuntimeFailure('SNMP link events require host nftables for the owned-node source policy.')
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
        self.state = {'spec': spec, 'startup_spec': copy.deepcopy(spec), 'revision': 0,
                      'phase': 'starting', 'namespaces': [], 'mounts': [],
                      'containers': [], 'vms': [], 'host_links': [], 'firewall_fingerprints': {}}
        self.save()
        try:
            for i, node in enumerate(spec['nodes']):
                ns = namespace(spec, i)
                run(['ip', 'netns', 'add', ns]); self.state['namespaces'].append(ns); self.save()
                self.ns(i, 'ip', 'link', 'set', 'lo', 'up')
                if node.get('firewall') is not None:
                    from .firewall import apply
                    self.state['firewall_fingerprints'][node['name']] = apply(self, i, node)
                    self.save()
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
                    if node['runtime'] == 'firecracker':
                        self.ns(j, 'ip', 'link', 'set', port, 'up')
                        self.ns(j, 'ip', 'link', 'set', port, 'master', 'vmbr0')
            connected = {tuple(e) for link in spec['links'] for e in link}
            for i, node in enumerate(spec['nodes']):
                if node['runtime'] == 'oci':
                    for port in node['interfaces']:
                        if (node['name'], port) not in connected:
                            self.ns(i, 'ip', 'link', 'add', port, 'type', 'dummy')
                            self.ns(i, 'ip', 'link', 'set', port, 'up')
                    from .lan import configure
                    configure(self, i, node)
                    self.start_oci(spec, node, i)
                else:
                    self.start_vm(node, i)
            from .ipv6 import install_routes as install_ipv6_routes
            install_ipv6_routes(self)
            from .slaac import start_servers as start_ra_servers
            start_ra_servers(self)
            from .dhcpv6_relay import start_servers as start_dhcpv6_relay
            start_dhcpv6_relay(self)
            from .dhcpv6 import start_clients as start_dhcpv6_clients
            start_dhcpv6_clients(self)
            from .ovs import start_servers as start_ovs
            start_ovs(self)
            from .dns import start_servers as start_dns
            start_dns(self)
            from .tftp_server import start_servers as start_tftp
            start_tftp(self)
            from .lldp import start_servers as start_lldp
            start_lldp(self)
            from .dhcp import start_clients, start_servers
            start_servers(self)
            from .dhcp_multi import start_servers as start_pools
            start_pools(self)
            from .dhcp_relay import start_servers as start_relays
            start_relays(self)
            start_clients(self)
            from .ospf import start_servers as start_ospf
            start_ospf(self)
            from .ospfv3 import start_servers as start_ospfv3
            start_ospfv3(self)
            from .management import start_servers as start_management
            start_management(self)
            from .syslog_server import start_servers as start_collectors
            start_collectors(self)
            from .ntp_server import start_servers as start_ntp
            start_ntp(self)
            from .snmp_notifications import start_receivers as start_notification_receivers
            start_notification_receivers(self)
            from .snmp import start_servers as start_snmp
            start_snmp(self)
            from .radius_server import start_servers as start_radius
            start_radius(self)
            self.state['phase'] = 'running'; self.save()
        except BaseException:
            self.state['phase'] = 'failed'; self.save()
            self.stop()
            raise

    def start_oci(self, spec, node, index):
        bundle = self.directory / node['name']; bundle.mkdir()
        from .dhcp import prepare_files
        prepare_files(bundle, node)
        from .dns import prepare_files as prepare_dns
        prepare_dns(bundle, node)
        from .tftp_server import prepare_files as prepare_tftp
        prepare_tftp(bundle, node)
        from .dhcp_relay import prepare_files as prepare_relay
        prepare_relay(bundle, node)
        from .dhcp_multi import prepare_files as prepare_pools
        prepare_pools(bundle, node)
        from .ospf import prepare_files as prepare_ospf
        prepare_ospf(bundle, node)
        from .ospfv3 import prepare_files as prepare_ospfv3
        prepare_ospfv3(bundle, node)
        from .slaac import prepare_files as prepare_ra
        prepare_ra(bundle, node)
        from .dhcpv6 import prepare_files as prepare_dhcpv6
        prepare_dhcpv6(bundle, node)
        from .dhcpv6_relay import prepare_files as prepare_dhcpv6_relay
        prepare_dhcpv6_relay(bundle, node)
        from .management import prepare_files as prepare_management
        prepare_management(bundle, node)
        from .syslog_server import prepare_files as prepare_collector
        prepare_collector(bundle, node)
        from .ntp_server import prepare_files as prepare_ntp
        prepare_ntp(bundle, node)
        from .radius_server import prepare_files as prepare_radius
        prepare_radius(bundle, node)
        from .snmp import prepare_files as prepare_snmp
        prepare_snmp(bundle, node)
        from .snmp_notifications import prepare_files as prepare_notifications
        prepare_notifications(bundle, node)
        from .lldp import prepare_files as prepare_lldp
        prepare_lldp(bundle, node)
        for folder in ('upper', 'work', 'rootfs'):
            (bundle / folder).mkdir()
        options = f'lowerdir={Path(node["rootfs"]).resolve()},upperdir={bundle / "upper"},workdir={bundle / "work"}'
        run(['mount', '-t', 'overlay', 'overlay', '-o', options, bundle / 'rootfs'])
        self.state['mounts'].append(str(bundle / 'rootfs')); self.save()
        write_json(bundle / 'config.json', oci_config(spec, node, index, bundle / 'rootfs'))
        # Record before run: crun can create state before reporting a startup error.
        self.state['containers'].append(node['name']); self.save()
        self.crun('run', '--detach', '--bundle', bundle, node['name'], log=bundle / 'console.log')
        for command in node['startup']:
            self.crun('exec', node['name'], *command, log=bundle / 'console.log')

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
                if node.get('dhcp_clients'):
                    observed = self.inspect(node['name'])
                    report['dhcp'] = {port: [f'{a["local"]}/{a["prefixlen"]}' for item in observed['addresses']
                                            if item['ifname'] == port for a in item.get('addr_info', []) if a.get('scope') == 'global']
                                      for port in node['dhcp_clients']}
            else:
                vm = next((v for v in state['vms'] if v['name'] == node['name']), None)
                report['vmm_alive'] = bool(vm and vm['starttime'] and process_identity(vm['pid']) == vm['starttime'])
                report['guest_ready'] = 'unverified; inspect console.log and test packets'
                report['console'] = str(self.directory / node['name'] / 'console.log')
            nodes.append(report)
        return {'name': self.name, 'phase': state['phase'], 'revision': state.get('revision', 0), 'nodes': nodes,
                'memory_note': 'OCI cgroup memory only; not total app/VM/host usage.'}

    def inspect(self, name):
        from .lan import observe
        for index, node in enumerate(self.read()['spec']['nodes']):
            if node['name'] == name and node['runtime'] == 'oci':
                result = observe(self, index, node)
                if node.get('firewall') is not None:
                    from .firewall import observe as firewall_observe
                    result['firewall'] = firewall_observe(self, index)
                return result
        raise RuntimeFailure('Kernel inspection is available for existing OCI nodes only.')

    def configure_ios(self, name, text):
        from .ios import compile_config
        state = self.read()
        if state['phase'] != 'running':
            raise RuntimeFailure('Lab must be running before configuration.')
        candidate = compile_config(state['spec'], name, text)
        return self._configure_network(name, candidate, 'Linux namespaces; partial IOS-style adapter')

    def configure_multicast(self, name, policy):
        state = self.read()
        if state['phase'] != 'running':
            raise RuntimeFailure('Lab must be running before multicast configuration.')
        candidate = copy.deepcopy(state['spec'])
        node = next((n for n in candidate['nodes'] if n['name'] == name), None)
        if node is None or node['runtime'] != 'oci' or node['role'] != 'switch':
            raise ValueError('Multicast policy requires an existing OCI switch.')
        node['multicast'] = copy.deepcopy(policy)
        return self._configure_network(name, validate(candidate), 'Linux bridge multicast snooping/querier')

    def configure_spanning_tree(self, name, policy=None, *, priority=None):
        state = self.read()
        if state['phase'] != 'running':
            raise RuntimeFailure('Lab must be running before configuration.')
        candidate = copy.deepcopy(state['spec'])
        node = next((n for n in candidate['nodes'] if n['name'] == name and n['role'] == 'switch' and n['runtime'] == 'oci'), None)
        if node is None:
            raise ValueError('An existing OCI switch is required.')
        if priority is not None:
            if policy is not None:
                raise ValueError('Choose a policy or a priority update.')
            node['spanning_tree']['priority'] = priority
        else:
            node['spanning_tree'] = policy
        return self._configure_network(name, validate(candidate), 'Linux kernel common spanning tree (IEEE 802.1D)')

    def _configure_network(self, name, candidate, source):
        from .lan import configure
        state = self.read()
        index = next(i for i, n in enumerate(state['spec']['nodes']) if n['name'] == name)
        previous = copy.deepcopy(state['spec'])
        from .service_adapters import adapters
        selected = adapters(candidate['nodes'][index], previous['nodes'][index])
        for adapter in selected:
            adapter.preflight_change(self, candidate['nodes'][index], previous['nodes'][index])
        if (selected or previous['nodes'][index].get('lldp') is not None) and candidate['nodes'][index] == previous['nodes'][index]:
            return {'configured': name, 'revision': state.get('revision', 0), 'source': source, 'unchanged': True}
        if selected:
            configure = selected[0].apply_change
        if previous['nodes'][index].get('dhcp_pools') is not None or candidate['nodes'][index].get('dhcp_pools') is not None:
            raise ValueError('DHCP pool server live network edits require a service adapter; recreate the lab.')
        if previous['nodes'][index].get('switch_backend') == 'ovs' or candidate['nodes'][index].get('switch_backend') == 'ovs':
            raise ValueError('OVS live network edits are unsupported by this adapter; use a new manifest and recreate the lab.')
        old_macs = previous['nodes'][index].get('interface_macs', {})
        if set(old_macs) - set(candidate['nodes'][index].get('interface_macs', {})):
            raise ValueError('Live removal of an explicit interface MAC requires stopping and recreating the lab.')
        state['phase'] = 'configuring'; state['pending_spec'] = candidate; state['pending_node'] = name; self.save()
        try:
            applied = configure(self, index, candidate['nodes'][index], previous['nodes'][index])
        except (RuntimeFailure, OSError, subprocess.TimeoutExpired) as original:
            try:
                configure(self, index, previous['nodes'][index], candidate['nodes'][index])
            except (RuntimeFailure, OSError, subprocess.TimeoutExpired) as rollback:
                state['phase'] = 'configuration-failed'; self.save()
                raise RuntimeFailure(f'Apply failed: {original}; rollback failed: {rollback}. Use recover or stop.') from original
            state['phase'] = 'running'; state.pop('pending_spec'); state.pop('pending_node', None); self.save()
            raise RuntimeFailure(f'Configuration failed and was rolled back: {original}') from original
        state['spec'] = candidate; state['revision'] = state.get('revision', 0) + 1
        state['phase'] = 'running'; state.pop('pending_spec'); state.pop('pending_node', None); self.save()
        result = {'configured': name, 'revision': state['revision'], 'source': source}
        if isinstance(applied, dict) and applied.get('stp_recovery'):
            result['stp_recovery'] = applied['stp_recovery']
        return result

    def configure_firewall(self, name, policy):
        from .firewall import apply
        state = self.read()
        if state['phase'] != 'running':
            raise RuntimeFailure('Lab must be running before configuration.')
        index = next((i for i, n in enumerate(state['spec']['nodes']) if n['name'] == name), None)
        if index is None or state['spec']['nodes'][index].get('firewall') is None:
            raise ValueError('An existing managed firewall node is required.')
        candidate = copy.deepcopy(state['spec'])
        candidate['nodes'][index]['firewall'] = policy
        candidate = validate(candidate)
        previous = state['spec']['nodes'][index]
        state['phase'] = 'configuring'; state['pending_spec'] = candidate; state['pending_node'] = name; self.save()
        try:
            baseline = apply(self, index, candidate['nodes'][index])
        except (RuntimeFailure, OSError, subprocess.TimeoutExpired, ValueError) as original:
            try:
                state.setdefault('firewall_fingerprints', {})[name] = apply(self, index, previous)
            except (RuntimeFailure, OSError, subprocess.TimeoutExpired, ValueError) as rollback:
                state['phase'] = 'configuration-failed'; self.save()
                raise RuntimeFailure(f'Firewall apply failed: {original}; rollback failed: {rollback}. Use recover or stop.') from original
            state['phase'] = 'running'; state.pop('pending_spec'); state.pop('pending_node', None); self.save()
            raise RuntimeFailure(f'Firewall failed and was rolled back: {original}') from original
        state['spec'] = candidate; state['revision'] = state.get('revision', 0) + 1
        state.setdefault('firewall_fingerprints', {})[name] = baseline
        state['phase'] = 'running'; state.pop('pending_spec'); state.pop('pending_node', None); self.save()
        return {'configured': name, 'revision': state['revision'], 'note': 'Atomic IPv4 policy update; existing conntrack sessions retained.'}

    def sessions(self, name, clear=False):
        for index, node in enumerate(self.read()['spec']['nodes']):
            if node['name'] == name and node.get('firewall') is not None:
                result = self.ns(index, 'conntrack', '-F' if clear else '-L', '-f', 'ipv4')
                return {'node': name, 'cleared': clear, 'output': result.stdout, 'summary': result.stderr}
        raise ValueError('An existing managed firewall node is required.')

    def recover(self):
        from .lan import configure
        state = self.read()
        if state['phase'] not in ('configuring', 'configuration-failed') or 'pending_spec' not in state:
            raise RuntimeFailure('No interrupted network configuration to recover.')
        target = state.get('pending_node')
        if 'pending_node' in state:
            current, pending_nodes = state['spec']['nodes'], state['pending_spec']['nodes']
            if (not isinstance(target, str) or not any(n['name'] == target and n['runtime'] == 'oci' for n in current)
                    or {k: v for k, v in state['spec'].items() if k != 'nodes'} !=
                       {k: v for k, v in state['pending_spec'].items() if k != 'nodes'}
                    or len(current) != len(pending_nodes)
                    or any(n['name'] != p['name'] or (n['name'] != target and n != p)
                           for n, p in zip(current, pending_nodes))):
                raise RuntimeFailure('Invalid scoped recovery journal; no node configuration was applied.')
        for index, node in enumerate(state['spec']['nodes']):
            if node['runtime'] == 'oci' and (target is None or node['name'] == target):
                if node.get('firewall') is not None:
                    from .firewall import apply
                    state.setdefault('firewall_fingerprints', {})[node['name']] = apply(self, index, node)
                pending = state['pending_spec']['nodes'][index]
                from .service_adapters import adapters
                selected = adapters(node, pending)
                if selected:
                    for adapter in selected:
                        adapter.apply_change(self, index, node, pending)
                else:
                    configure(self, index, node, pending)
        state.pop('pending_spec'); state.pop('pending_node', None); state['phase'] = 'running'; self.save()

    def write_startup(self):
        state = self.read()
        if state['phase'] != 'running':
            raise RuntimeFailure('Save requires a running lab without pending configuration.')
        from .persistence import drift, save_startup
        differences = drift(self)
        if differences:
            raise RuntimeFailure('Unmanaged kernel changes detected; no stale configuration saved: ' + '; '.join(differences))
        spec = validate(state['spec'])
        save_startup(self.name, spec)
        state['startup_spec'] = copy.deepcopy(spec); self.save()
        return {'saved': str(CONFIG_ROOT / self.name / 'startup.json'),
                'note': 'Declarative network configuration only; no runtime filesystem snapshot, DHCP lease persistence or learned OSPF route snapshot.'}

    def stop(self):
        state = self.read(); errors = []
        from .ssh_radius import stop_worker as stop_ssh_radius
        for name in list(state.get('ssh_radius_workers', {})):
            stop_ssh_radius(self, name)
        from .snooping import stop_worker
        for name in list(state.get('snooping_workers', {})):
            stop_worker(self, name)
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
