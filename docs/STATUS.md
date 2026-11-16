# Network LABS — current status

This is the one place that says what works **now**. Update it in the same commit
as any feature change. The dated development log is kept unchanged in
[history/CODEX_HANDOFF.md](history/CODEX_HANDOFF.md); older planning estimates are in
[PROJECT_STATUS.md](PROJECT_STATUS.md). The first-release scope is
[RELEASE_1.md](RELEASE_1.md).

Last updated: 2026-11-16.

## Target

One Linux micro-VM (Firecracker) per network node, real packets between them,
device-style configuration from the GUI, CLI and web pages. See
[PROJECT_VISION.md](PROJECT_VISION.md). **New features target micro-VMs only**;
the container (OCI) runtime is kept working and fixed, but not extended.

## Runtimes

| Runtime | Role today | State |
| --- | --- | --- |
| Micro-VM (Firecracker, KVM) | Target runtime | Host, router, firewall, switch and DHCP guests work; see below |
| Container (OCI/crun) | Existing LAN feature set | Broad LAN coverage; maintenance only |
| Educational canvas / Wasm | Teaching views | Separate engine; not the native fabric |

## Micro-VM guests — what works

Each item has a real-KVM acceptance test in `tests/test_native_microvm*.py`,
run by the manual `microvm-kvm` CI job under the Firecracker jailer and with
the direct launch.

| Feature | Lab example (`microvm-example ...`) | Notes |
| --- | --- | --- |
| Host guests, 1–4 ports, static addresses and routes | default, `--multinic` | Save captures live addresses/routes; cold restore replays them |
| Router guest, IPv4 forwarding | `--router`, `--router-chain`, `--router-quad` | Up to four ports; static routes through any port |
| Firewall guest, stateful IPv4 filtering | `--firewall` | iptables in the guest; installed and read back before forwarding |
| Firewall NAT (masquerade, SNAT, DNAT) | `--firewall-nat` | Source NAT matches the outbound port only |
| Live firewall policy change | — (`firewall LAB NODE --file`) | Rebuilt with forwarding paused; rollback and `recover` |
| Firewall sessions view | — (`sessions LAB NODE`) | Read-only; `clear-sessions` refused on guests |
| Switch guest, one untagged VLAN | `--switch` | 2–4 unnumbered ports bridged in the guest; runs on any guest kernel |
| Switch guest VLANs: access and trunk ports | `--switch-vlans` | Bridge VLAN filtering in the guest; needs the Network LABS kernel (`tools/guest_kernel`) |
| Router-on-a-stick: 802.1Q subinterfaces on router/firewall guests | `--router-on-a-stick` | Unnumbered trunk port with `ethN.VID` subinterfaces; needs the Network LABS kernel |
| DHCP server and client in guests | `--dhcp` | Local pool only; leases via `microvm-dhcp-leases` |
| Capture on a guest port | — (`capture LAB NODE ethN`) | Recorded on the host-side TAP |
| Isolation and limits | — | Jailer chroot, per-lab uid block, cgroup memory/CPU caps, vCPU and memory budgets |

## Micro-VM guests — not yet

- SVIs (an address on a switch VLAN) on switch guests, and firewall rules on subinterfaces (guest firewall
  rules name physical ports only). Static routes through a subinterface are unit-tested only.
- STP, LACP and switch security features on guests.
- Routing protocols (OSPF), DNS, RADIUS, SNMP, Syslog, NTP, TFTP and HTTPS inside guests
  (these exist on containers only).
- DHCP remote pools and reservations on guests.
- IPv6 on guests.
- Device-style CLI/web management on guests (only resources and firewall pages today).
- Live changes from the GUI other than the firewall policy (addresses, VLAN ports, DHCP apply on restart), and a guest console.
- VMware/VirtualBox attachment, VXLAN/EVPN, WAN.

## Containers (OCI) — what works

Bounded, tested profiles; see [LAN_PROTOCOL_COVERAGE.md](LAN_PROTOCOL_COVERAGE.md)
for exact limits of each.

- Switching: access/trunk VLANs, SVIs, common STP and scoped RSTP, LACP, port security,
  DHCP snooping, DAI, IP Source Guard, IGMP snooping, received LLDP.
- Routing: static IPv4/IPv6, OSPFv2 and OSPFv3 subsets (BIRD), router-on-a-stick.
- Addressing: DHCP (leases, reservations, relay, multiple pools), SLAAC, DHCPv6 IA_NA,
  relay and prefix delegation.
- Services: DNS (A/AAAA, UDP/TCP), HTTPS, Syslog (UDP/TCP/TLS), SNMP v2c/v3 with
  traps and informs, NTP, TFTP.
- Security and access: nftables filtering and NAT, IPv6 filtering, RA Guard,
  RADIUS (PAP/EAP-MD5) for SSH/Telnet, wired 802.1X.
- Lifecycle: start/stop, declarative save and cold restore, drift refusal, capture,
  `verify`/`probe` diagnostics, IOS-style `show` aliases.

## GUI

Tk desktop app (`python3 -m network_labs`) with the educational canvas, a native
lab workbench (topology editing, lifecycle, inspection, capture and console
entries) and browser-based management pages. For micro-VMs the workbench can add
host, router, firewall and switch nodes (kernel, disk, 1–4 ports, static addresses
or `dhcp`), start and stop the lab, show each node as running while its VMM is
alive, and capture on its ports. The interface form edits a micro-VM's name, port
addresses and gateway in the draft, and the browser management pages offer each guest
role what it supports (VLAN ports on switches, subinterfaces on routers and firewalls,
DHCP server, firewall policy, resources). Draft changes apply on the next start.
**Appliquer le pare-feu au lab actif** sends a saved firewall policy to the running lab,
for containers and micro-VMs, with rollback on failure. A micro-VM has no console by
design (its agent takes typed requests only).

**Vendor models.** The workbench library lists 56 manufacturer models from 36 brands
(`network_labs/appliances/native_models.py`): routers, switches, firewalls, client
workstations, servers and storage, and network peripherals. A model sets the node's
brand and model name, a default port count from the model's layout and the drawing;
containers also take the model's port names as aliases of their eth ports. The model
is checked against the node's role when the lab is validated. A modelled node still
runs Linux networking: no vendor firmware, logo or proprietary interface is loaded,
and vendor consoles stay as listed in `device_identity` (an IOS-style subset for Cisco
routers and switches in containers only).

Modelled nodes show their vendor's port names (FortiGate `port1`, Junos `ge-0/0/0` /
`xe-0/0/0`, RouterOS `ether1`, Catalyst `gi1/0/1`, Palo Alto `ethernet1/1`…) on the
canvas and in the port table, next to the Linux port they stand for.

**Vendor configuration console (CLI tab).** Cisco, Fortinet, Juniper and MikroTik models
show their lab configuration in IOS, FortiOS, Junos or RouterOS syntax
(`network_labs/appliances/vendor_config.py`), and commands typed there are written to the
lab draft and validated like the forms; a refused command is reported with its line.
Subsets: interface addresses and static routes in all four; firewall policies in FortiOS
(`config firewall policy`) and RouterOS (`/ip firewall filter`, chain forward); VLANs and
access/trunk switchports in IOS. They work for micro-VMs and containers alike because they
edit the draft; the change reaches the guests on the next start (or the live firewall
action). This is configuration syntax, not the vendor's operating system: there is no
live state beyond the read-only commands below, and other brands keep the forms only.

**Live vendor `show` commands (CLI tab, running lab).** The same brands print the running node's
state in their vendor's layout (`network_labs/appliances/vendor_show.py`): IOS `show ip interface
brief`, `show ip route`, `show vlan brief` (switches; abbreviations such as `sh ip ro` work);
FortiOS `get system interface`, `get router info routing-table all`; Junos `show interfaces terse`,
`show route`; RouterOS `/interface print`, `/ip address print`, `/ip route print`. One sudo-confirmed
`show` request reads the node (micro-VM agent read-only requests, or `ip -j` in a container); later
commands format that observation locally until **Relire**. Values come from Linux only: no counters,
timers or hardware fields a Linux node does not have. Real-KVM tested in the router-chain test.

## How to run

```bash
python3 -m network_labs                                   # desktop app
python3 -m network_labs.appliances doctor                 # what this host can run
python3 -m network_labs.appliances microvm-rootfs --busybox "$(command -v busybox)" \
    --with-agent --with-firewall --output guest.ext4      # guest disk image
python3 -m network_labs.appliances microvm-example --dhcp --kernel vmlinux --disk guest.ext4 > lab.json
sudo python3 -m network_labs.appliances start lab.json
sudo python3 -m network_labs.appliances status microvm-dhcp
sudo python3 -m network_labs.appliances stop microvm-dhcp
```

Micro-VMs need Linux with `/dev/kvm`, `firecracker` (and optionally `jailer`) and a
guest kernel; the CI job pins Firecracker v1.10.1 and its CI kernel 5.10.

## Tests

- Unit tests: `python3 -m unittest discover -s tests` (privileged and KVM cases skip
  without root, containers or `/dev/kvm`).
- CI: `.github/workflows/tests.yml` runs about 60 jobs on push and pull request;
  `microvm-kvm` runs only when dispatched manually with `suite: microvm-kvm`.
- Ubuntu 26.04 runners are not supported yet; jobs are pinned to 24.04.

## Known limits

- A live firewall change on a guest briefly pauses forwarding (containers change atomically).
- Guest DHCP and NAT depend on the guest kernel; the current one supports both.
- `main` now holds the full history; new work branches from `main`.
- Pull requests must pass `tools/check_added_lines.py`: no joined statements and no lines
  over 140 characters on the lines they add (existing code is not checked).
