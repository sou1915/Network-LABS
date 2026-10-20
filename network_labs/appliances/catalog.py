"""Report implementation separately from installed host dependencies."""
import importlib.util
import os
import platform
import shutil
from pathlib import Path


def capabilities():
    linux = platform.system() == 'Linux'
    cgroup = Path('/sys/fs/cgroup/cgroup.controllers').is_file()
    kvm = os.access('/dev/kvm', os.R_OK | os.W_OK)
    tools = {name: shutil.which(name) for name in ('ip', 'crun', 'firecracker', 'busybox')}
    return {
        'host': {'linux': linux, 'root': os.geteuid() == 0 if linux else False,
                 'cgroup_v2': cgroup, 'kvm_access': kvm, 'tools': tools},
        'runtimes': [
            {'id': 'oci', 'implementation': 'experimental',
             'prerequisites_detected': bool(linux and cgroup and tools['ip'] and tools['crun']),
             'scope': 'Persistent Linux containers; isolated net/PID/mount/UTS/IPC; shared host kernel. Trusted rootfs required.'},
            {'id': 'firecracker', 'implementation': 'experimental',
             'prerequisites_detected': bool(linux and tools['ip'] and tools['firecracker'] and kvm),
             'scope': 'One Ethernet NIC, dedicated guest kernel and disk. Guest console log; no exec agent.'},
            {'id': 'wasm', 'implementation': 'existing',
             'prerequisites_detected': importlib.util.find_spec('wasmtime') is not None,
             'scope': 'Existing Wasm LAN backend; separate fabric, instances recreated per test.'},
            {'id': 'libkrun', 'implementation': 'research', 'prerequisites_detected': False,
             'scope': 'No adapter yet; validate guest Ethernet transport before integration.'},
            {'id': 'unikraft', 'implementation': 'research', 'prerequisites_detected': False,
             'scope': 'No image builder or compatible hypervisor adapter yet.'},
            {'id': 'hyperlight-nanvix', 'implementation': 'research', 'prerequisites_detected': False,
             'scope': 'POSIX compatibility and persistent L2 networking require validation.'},
            {'id': 'wasi-0.3', 'implementation': 'research', 'prerequisites_detected': False,
             'scope': 'Current guest ABI is not a WASI 0.3 component.'},
            {'id': 'netkit-ebpf', 'implementation': 'research', 'prerequisites_detected': False,
             'scope': 'Fabric uses veth/TAP; no netkit or eBPF datapath installed.'},
        ],
        'note': 'Detection is not a successful boot test. No automatic installation, download or fallback.',
    }
