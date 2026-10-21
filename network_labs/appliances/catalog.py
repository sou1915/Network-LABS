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
    tools = {name: shutil.which(name) for name in ('ip', 'bridge', 'sysctl', 'crun', 'firecracker', 'busybox', 'nft', 'conntrack', 'tcpdump', 'nsenter', 'timeout')}
    return {
        'host': {'linux': linux, 'root': os.geteuid() == 0 if linux else False,
                 'bonding_driver_loaded': Path('/sys/module/bonding').exists(), 'cgroup_v2': cgroup, 'kvm_access': kvm, 'tools': tools},
        'runtimes': [
            {'id': 'oci', 'implementation': 'experimental',
             'prerequisites_detected': bool(linux and cgroup and tools['ip'] and tools['bridge'] and tools['sysctl'] and tools['crun']),
             'scope': 'Persistent Linux containers; VLAN access/trunk, LACP port-channels and classic common STP, dot1Q routing, BusyBox DHCP, optional nftables IPv4 firewall/NAT and static access-port source-MAC security, access-only DHCPv4 trust filtering with volatile request/ACK bindings, partial IOS-style configuration and saved startup manifests. Shared host kernel.'},
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
