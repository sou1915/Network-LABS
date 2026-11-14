# Authoritative project vision — clarified by the user, 2026-11-12

## Guest IPv4 address control — 2026-11-14

`microvm-address --socket /private/node/guest.vsock --cidr 192.0.2.11/24 add`
(or `delete`) changes an explicit IPv4 address on guest eth0 using fixed argv.
Both sides validate input; stdio diagnostics reject mutations. Errors propagate
to the CLI. Changes are live only, not saved to manifests/startup. A duplicate
add/delete can return a Linux error; this operation is not claimed idempotent.
After a transport timeout, inspect addresses before deciding whether to retry.

Expanded native acceptance adds a secondary address, verifies peer ping, removes
it, verifies packet failure, and verifies original-address connectivity throughout.
UI terminology now says runtime instead of OCI for the shared node status table.
Screenshots show the current draft GUI, not a locally booted guest; network
mutation controls are not yet bound to this UI. Native validation is pending.


## Guest interface control — 2026-11-14

`microvm-link --socket /private/node/guest.vsock down` (or `up`) changes the
live guest eth0 through vsock using fixed BusyBox `ip link set dev eth0` argv.
Only eth0/up/down are accepted in the client and guest. Diagnostic stdio mode
rejects mutations. A failed guest command returns a failing CLI status.

This is transient guest state: no manifest/startup persistence or GUI binding.
A transport timeout leaves the outcome unknown; inspect `addresses` before
retrying. Setting the same desired state is idempotent. Expanded `microvm-kvm`
checks guest down/up, duplicate requests, retained vsock access, unaffected host
fabric, failed peer ping while down and restored bidirectional delivery.
Native acceptance **PASS** at source `563f99f64f0743dfec01d86a05a24323943f3dfc`:
[Actions run](https://github.com/sou1915/Network-LABS/actions/runs/43595151867/job/132447966413).
The real two-guest test completed in 3.883 seconds, including guest eth0 down/up,
repeated requests, retained vsock control and host fabric, and traffic recovery.
Evidence: [results](evidence/microvm-link-2026-11-14/result.json),
[provenance](evidence/microvm-link-2026-11-14/provenance.json), and console/cleanup
logs in the same directory. Local tests: 28 passing, one GUI test skipped.
Next: typed guest IP/route configuration and persistence, followed by multi-NIC
and role translation. This does not certify every node or overall LAN completion.


## Real two-guest KVM acceptance — PASS (2026-11-13)

Source `e96bb7f685442aa693092524bcdc8fcc0d643f3a` passed the dedicated
[Actions run](https://github.com/sou1915/Network-LABS/actions/runs/43456371572/job/131991482785).
Two independent Firecracker guests booted our built image with 128 MiB/1 vCPU
configured per guest. Both vsock agents replied and reported their own static
IPv4 addresses; bidirectional ping passed. Link-down produced 100% loss and
link-up restored delivery. Base-image immutability and process/namespace/bundle
cleanup passed. The native test completed in 2.991 seconds (job: 46 seconds).

Retained evidence: [results](evidence/microvm-kvm-2026-11-13/result.json),
[cleanup](evidence/microvm-kvm-2026-11-13/cleanup.txt),
[provenance](evidence/microvm-kvm-2026-11-13/provenance.json),
and both guest console logs in that directory. Image build flags and READY's
`network_verified: false` describe their narrower stages; the subsequent live
packet probes establish this run's networking result.

The first native runs exposed kernel-auto-mounted devtmpfs and Ubuntu BusyBox's
missing mountpoint applet. Bootstrap now detects `/dev` through `/proc/mounts`
using shell built-ins and retains serial diagnostics on failure.

This validates two static IPv4 host guests, not every node role or overall LAN
completion. Next: typed guest network configuration, multi-NIC support and
router/switch/firewall role translation; then GUI integration and external
VMware/VirtualBox attachment. VXLAN remains deferred. Actual resource consumption
and broader isolation/security hardening are not certified by this smoke test.


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

## Guest diagnostics checkpoint (2026-11-13)

The image build CI from `bd9ccb0` passed:
https://github.com/sou1915/Network-LABS/actions/runs/43308396376/job/131497652171

`microvm-rootfs --with-agent` now compiles a static C agent into the guest
(requires native gcc/static libc matching BusyBox). BusyBox init supervises it.
Firecracker config exposes a separate `guest.vsock` socket in each private
mode-0700 node bundle. CID 3 is scoped to each VMM; guest port 19001 accepts only
host CID 2. The kernel additionally needs `CONFIG_VSOCKETS` and
`CONFIG_VIRTIO_VSOCKETS` built in. No TCP management listener is installed.

```sh
python3 -m network_labs.appliances microvm-rootfs \
  --busybox /bin/busybox --output /tmp/guest-with-agent.ext4 --with-agent
# After booting the lab on a KVM-capable host, using its actual private bundle:
python3 -m network_labs.appliances microvm-diagnostic \
  --socket /path/to/private/lab/VM1/guest.vsock ready
# Other operations: addresses, routes
```

Protocol NL1 accepts only READY, ADDRESSES and ROUTES. Diagnostics execute fixed
`/bin/busybox ip address show` or `ip route show` argument arrays, without a
shell. Replies preserve command exit status. Requests, responses and execution
time are bounded (63-byte request, 32 KiB response, five-second worker deadline).
The host client validates the Firecracker handshake and response framing with
an overall deadline. The private socket is an administrative interface: do not
expose its enclosing directory or forward it to untrusted clients.

READY proves only that the agent replied, explicitly not network readiness.
The default image still omits the agent. Images with it report installation,
not operational guest control. Local tests exercise the compiled protocol,
malformed input, timeout, Unix transport, actual ext4 placement/permissions and
VMM socket separation. Linux diagnostics run on the test host when BusyBox is
installed; those are not VM traffic tests. The dedicated `microvm-image` CI
includes these tests. No guest boot is certified in the current workspace,
which still has no `/dev/kvm`. Next: actual KVM boot/diagnostic/traffic smoke,
then typed network mutations and role translation. VMware/VirtualBox attachment
and VXLAN remain tracked, not implemented by this checkpoint.

## Real KVM acceptance harness (2026-11-13)

Agent/image CI passed at `e2e2eb6`: run `43442607192`, job `131943786083`.
The agent now accepts `PING <IPv4>` with strict address validation and fixed
one-packet/one-second BusyBox arguments. Host CLI operation `ping` requires
`--destination IPv4`; no command strings or arbitrary options are accepted.

Dedicated Actions selection `microvm-kvm` runs only on explicit dispatch. It
requires real `/dev/kvm` and fails rather than skipping if unavailable. It pins
Firecracker 1.10.1 and official CI kernel 5.10.223 by SHA-256, builds our image,
boots two independent guests, checks vsock readiness and assigned addresses,
then verifies bidirectional ping, link-down failure and link-up recovery.
It also verifies base-image immutability and cleanup of VMMs/namespaces/bundles.
Console logs and structured results are retained as `microvm-kvm-evidence`.
Configured resources are checked; actual resource consumption is not measured.

To run on a disposable host with the required tools and compatible kernel:

```sh
sudo env NETWORK_LABS_MICROVM_TESTS=1 NETWORK_LABS_MICROVM_KERNEL=/path/to/vmlinux \
  python3 -m unittest tests.test_native_microvm -v
```

The default test suite skips this privileged test; explicit selection never
substitutes mocked guests. Creation of this harness is not a passing boot claim:
consult the Actions result and artifacts before certifying VM networking.
