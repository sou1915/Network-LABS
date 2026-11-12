# Authoritative project vision — clarified by the user, 2026-11-12

Network LABS builds lightweight network appliances. **Each final node owns a
Linux micro-VM**, with an independent guest kernel, RAM allocation, vCPU(s),
disk and network interfaces. Resource allocation, configured limits and actual
consumption must be distinguished. Linux OCI containers and Wasm experiments
are useful existing implementations, but do not satisfy this isolation goal.

The project implements the device experience over its Linux networking engine:

- Router/switch command dialects translate to actual guest Linux configuration.
- A Windows-like node reproduces networking settings and terminal semantics;
  a full Windows installation is not required or claimed.
- Linux endpoints expose the necessary Linux network tools and terminal.
- Web-managed devices target the selected product's layout and network-option
  behavior, backed by working guest operations. Unsupported features remain
  explicit until implemented; visual resemblance alone is not acceptance.
- VMware and VirtualBox machines can eventually attach to the same lab fabric
  through an explicit external-network adapter.

Running original proprietary firmware is **not** the required implementation
strategy. Earlier advice to replace this architecture with vendor VM images
was a misunderstanding. Existing translators, Linux packet behavior and UI
work remain reusable; moving execution into each micro-VM is the central gap.

The supplied GUI reference remains authoritative. The previous LAN 7/7 gate
certifies a bounded Linux/OCI implementation, not completion of this whole
project or its per-node micro-VM requirement. Earlier overall percentages are
estimates without an acceptance denominator and must not be treated as proof.
VXLAN remains tracked after the essential guest execution and LAN integration.

## Implementation sequence and acceptance

1. **Micro-VM resource contract and reference endpoints.** Firecracker is already
   wired to isolated TAP/network namespaces with a per-node disk copy. Add
   explicit vCPU/RAM configuration, a two-micro-VM reference manifest and
   resource controls. Current scope is a single-interface static IPv4 host.
2. **Managed minimal Linux guest and typed guest control.** Build reproducible
   kernel/rootfs assets with the required network tools; establish a versioned
   guest-agent transport (for example vsock), bounded operations and actual
   readiness. Verify two guests boot and exchange packets, and that stopping
   them cleans up host resources. Process survival is not guest readiness.
3. **Move node operations behind the guest executor.** Carry existing command
   translators and validated operations into the guest. Add multiple NICs and
   actual switch/router/firewall behavior, then protocol-specific tests. Do not
   merely change runtime labels on existing OCI nodes.
4. **Resource observation and interactive operation.** Report actual VMM/guest
   usage separately; provide guest consoles, capture and persistence. Enforce
   CPU scheduling limits if fractional CPU budgets are offered; a vCPU count
   is not a dedicated physical-core reservation.
5. **Device experience.** Complete command dialects, Windows networking views
   and product-specific web workflows against named/versioned targets, keeping
   the real guest state as the authority.
6. **External machines.** Add explicit VMware/VirtualBox attachment and test
   bidirectional traffic, VLAN boundaries, ownership and cleanup.

## Current usable foundation

`microvm-example` generates two independent Firecracker host nodes. It does not
read assets, boot guests or change host networking:

```sh
python3 -m network_labs.appliances microvm-example \
  --kernel /absolute/path/to/vmlinux --disk /absolute/path/to/rootfs.ext4 \
  --memory-mib 128 --vcpus 1 > microvm-pair.json
python3 -m network_labs.appliances plan microvm-pair.json
```

Open the manifest in the native GUI. The web manager exposes **Ressources
micro-VM** for these nodes; edits validate the entire RAM budget. Networking
forms and OCI console/capture remain unavailable for guests without an adapter.
Each guest gets a separate writable copy of the supplied base disk on start.
The guest image builder below supplies minimal userspace. A compatible kernel
is still required, and no guest control agent is installed yet.

The new `vcpus` field is Firecracker-only (1..32, default 1 for old manifests).
It reaches `machine-config.vcpu_count`; RAM reaches `mem_size_mib`. Planning
reports aggregate VM vCPU allocation and RAM, not measured use. OCI retains
its existing distinct cgroup quota and rejects a misleading `vcpus` setting.

The current workspace has no `/dev/kvm`. Schema, generated VMM configuration,
HTTP atomicity and real browser interaction can be tested here; guest boot,
packet delivery and CPU/RAM consumption require a KVM-capable host and assets.

## Minimal guest image checkpoint (2026-11-12)

Install `busybox-static` and `e2fsprogs`, then build without root or mounts:

```sh
python3 -m network_labs.appliances microvm-rootfs \
  --busybox /bin/busybox --output /tmp/network-labs.ext4 --size-mib 64
```

The command refuses existing destinations, stages the complete disk before
publication, normalizes guest inode ownership to root and returns SHA-256.
PID1 mounts proc/sysfs/devtmpfs/devpts and starts BusyBox init without a login
shell or management listener. Root login is locked. The kernel must match the
BusyBox architecture and include virtio block/network, ext4, devtmpfs (including
auto-mount for initial console), proc/sysfs/devpts and `CONFIG_IP_PNP` for the
existing static `ip=` boot argument. This is not a vendor firmware image.

Local evidence: a real 64 MiB ext4 was built; six focused tests passed including
actual ext4 inspection of init, root ownership, executable/private/sticky modes,
non-overwrite behavior and failure cleanup. CI suite `microvm-image` repeats
these checks. Neither this test nor `NETWORK_LABS_GUEST_INIT_COMPLETE` certifies
VM boot, usable networking or guest control. Next: boot on KVM, typed guest
control/readiness, then multi-NIC and network-role translation inside guests.
VMware/VirtualBox integration and deferred VXLAN remain on the roadmap.
