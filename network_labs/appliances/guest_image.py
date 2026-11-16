"""Build a minimal Linux guest disk without mounts or host root privileges."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .runtime import static_busybox_rootfs

INIT = '''#!/bin/sh
set -eux
# Keep PID1 alive on bootstrap failure so the serial error is not lost to panic.
trap 'echo NETWORK_LABS_GUEST_INIT_FAILED; while :; do /bin/busybox sleep 3600; done' EXIT
/bin/busybox mount -t proc proc /proc
/bin/busybox mount -t sysfs sysfs /sys
# Ubuntu busybox-static omits mountpoint; use shell built-ins instead.
dev_mounted=0
while read -r source target filesystem rest; do
    if [ "$target" = /dev ] && [ "$filesystem" = devtmpfs ]; then dev_mounted=1; fi
done < /proc/mounts
if [ "$dev_mounted" = 0 ]; then /bin/busybox mount -t devtmpfs devtmpfs /dev; fi
/bin/busybox mkdir -p /dev/pts /run
/bin/busybox mount -t devpts devpts /dev/pts
/bin/busybox ip link set lo up
# eth0 is configured by the kernel ip= argument (CONFIG_IP_PNP required).
# This marker certifies init only, never networking or management readiness.
echo NETWORK_LABS_GUEST_INIT_COMPLETE
exec /bin/busybox init
'''
INITTAB = '''# No unauthenticated shell or network management listener.
::respawn:/bin/busybox sleep 3600
::ctrlaltdel:/bin/busybox reboot
::shutdown:/bin/busybox umount -a -r
'''


FIREWALL_MODULES = ('libxt_conntrack.so', 'libxt_tcp.so', 'libxt_udp.so', 'libipt_icmp.so')


def install_iptables(root, program):
    """Copy the legacy iptables program, its shared libraries and the match modules a policy can use."""
    program = Path(program).resolve()
    listing = subprocess.run(['ldd', str(program)], capture_output=True, text=True, timeout=30)
    if listing.returncode:
        raise ValueError('Guest firewall program is not a dynamic executable that ldd can read: ' + listing.stderr.strip())
    libraries = []
    for line in listing.stdout.splitlines():
        words = line.split()
        path = words[2] if '=>' in words and len(words) >= 3 else words[0] if words and words[0].startswith('/') else None
        if '=>' in words and (path is None or not path.startswith('/')):
            raise ValueError('Guest firewall program has an unresolved library: ' + line.strip())
        if path:
            libraries.append(Path(path))
    modules = next((folder for folder in sorted({library.parent / 'xtables' for library in libraries})
                    if all((folder / name).is_file() for name in FIREWALL_MODULES)), None)
    if modules is None:
        raise ValueError('Guest firewall match modules not found next to the iptables libraries.')
    for source in [*libraries, *(modules / name for name in FIREWALL_MODULES)]:
        # The host may reach one file through /lib and /usr/lib; the image has no such link, and iptables
        # looks for its modules under the path it was built with. Provide both spellings as plain files.
        for location in {source, source.resolve()}:
            target = root / location.relative_to('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copyfile(source, target); target.chmod(0o755)
    target = root / 'sbin/xtables-legacy-multi'
    shutil.copyfile(program, target); target.chmod(0o755)


def build(busybox, output, *, size_mib=64, mke2fs='mke2fs', debugfs='debugfs', with_agent=False, cc='gcc', with_firewall=False, iptables=None):
    """Publish a complete ext4 image exclusively; never overwrite an existing path."""
    if type(size_mib) is not int or not 16 <= size_mib <= 1024:
        raise ValueError('Guest disk size must be an integer between 16 and 1024 MiB.')
    output = Path(output).absolute()
    if os.path.lexists(output):
        raise ValueError('Guest image destination must not already exist.')
    with tempfile.TemporaryDirectory(prefix='.guest-image-', dir=output.parent) as temporary:
        work = Path(temporary)
        root = static_busybox_rootfs(busybox, work / 'root')
        (root / 'sbin/init').write_text(INIT)
        (root / 'sbin/init').chmod(0o755)
        inittab = INITTAB
        if with_agent:
            agent = root / 'sbin/network-labs-agent'
            compiled = subprocess.run([str(cc), '-static', '-Os', '-Wall', '-Wextra', '-Werror',
                                       '-o', str(agent), str(Path(__file__).parent / 'guest/agent.c')],
                                      capture_output=True, text=True, timeout=120)
            if compiled.returncode:
                raise ValueError('Guest agent compilation failed: ' + compiled.stderr.strip())
            # A native compiler must match the supplied BusyBox guest architecture.
            if agent.read_bytes()[4:6] != (root / 'bin/busybox').read_bytes()[4:6] or agent.read_bytes()[18:20] != (root / 'bin/busybox').read_bytes()[18:20]:
                raise ValueError('Guest agent and BusyBox architectures differ.')
            agent.chmod(0o755)
            inittab = inittab.replace('::respawn:/bin/busybox sleep 3600',
                                      '::respawn:/sbin/network-labs-agent')
        if with_firewall:
            if not with_agent:
                raise ValueError('A firewall guest image needs the agent; add --with-agent.')
            program = iptables or shutil.which('xtables-legacy-multi') or shutil.which('iptables-legacy')
            if not program:
                raise ValueError('Guest firewall needs legacy iptables on this machine (package iptables).')
            install_iptables(root, program)
        (root / 'etc/inittab').write_text(inittab)
        (root / 'etc/shadow').write_text('root:!:0:0:99999:7:::\n')
        (root / 'etc/shadow').chmod(0o600)
        (root / 'tmp').chmod(0o1777)
        disk = work / 'rootfs.ext4'
        with disk.open('xb') as stream:
            stream.truncate(size_mib * 1024 * 1024)
        def run(argv):
            result = subprocess.run(argv, capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise ValueError('Guest image tool failed: ' + result.stderr.strip())
            return result
        run([str(mke2fs), '-q', '-t', 'ext4', '-F', '-L', 'network-labs',
             '-E', 'root_owner=0:0,lazy_itable_init=0,lazy_journal_init=0',
             '-d', str(root), str(disk)])
        # mke2fs -d preserves host ownership: explicitly normalize every guest inode.
        commands = work / 'ownership.txt'
        commands.write_text(''.join(
            f'set_inode_field /{path.relative_to(root).as_posix()} {field} 0\n'
            for path in sorted(root.rglob('*')) for field in ('uid', 'gid')))
        result = run([str(debugfs), '-w', '-f', str(commands), str(disk)])
        # debugfs can report command errors with a successful process exit.
        if any(line and not line.startswith('debugfs ') for line in result.stderr.splitlines()):
            raise ValueError('Guest inode ownership failed: ' + result.stderr.strip())
        with disk.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        os.link(disk, output)  # Atomic and fails closed if destination appeared meanwhile.
    return {'disk': str(output), 'size_mib': size_mib, 'sha256': digest,
            'guest_boot_verified': False, 'guest_control_available': False, 'guest_agent_installed': bool(with_agent), 'guest_firewall_installed': bool(with_firewall)}
