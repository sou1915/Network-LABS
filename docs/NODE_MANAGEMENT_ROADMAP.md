# Native node management coverage

The user clarified the execution architecture: see
[PROJECT_VISION.md](PROJECT_VISION.md). Product-like CLI/web experiences must
control Linux inside one micro-VM per node; original vendor firmware is not
required. The OCI coverage below describes reusable functionality, not the
completed target architecture. Prioritize the guest executor and guest image.


The user requests rich, functional management for every node, using the supplied
FortiGate-style reference as the current visual target. The previous minimal
interface form is not functional or visual completion. Do not call this a full
FortiOS/PAN-OS implementation: the current native nodes run Linux OCI workloads.
Every displayed editor must map to an existing validated backend capability.
Keep expanding management without reopening the accepted LAN core gate.

## Implemented web editors

All editors share the Tk project draft, full-lab validation, revision checks
and atomic replacement. Save, stop and start apply changes to the kernel.
They do not silently reconfigure a running lab. The equipment selector reaches
all native nodes and the navigation adapts to the selected role.

| Role | Current native management editors | Existing backend capabilities still needing dedicated web controls |
| --- | --- | --- |
| Firewall | Physical interfaces/admin, 802.1Q subinterfaces, IPv4 filtering with ordered named rules, default accept/drop, stateful mode, source/destination CIDR and interfaces, TCP/UDP destination ports; masquerade/SNAT/DNAT and DNAT port translation; routes/gateway/forwarding, DNS resolver, DHCP client/server, DNS server, LLDP on compatible nodes | IPv6 firewall/input policy, conntrack observations, diagnostics/capture; richer supported service/security compositions |
| Router | Interfaces/admin, 802.1Q, IPv4 routes/gateway/forwarding, static IPv6 /64 and routes, DNS resolver, DHCP client/server, DNS server, LLDP on compatible nodes | OSPF/OSPFv3, RA/SLAAC/DHCPv6 and prefix delegation, relay, richer runtime diagnostics |
| Switch | VLAN declarations, access/trunk ports with native/allowed VLANs, SVI creation/addressing, static routes and forwarding, static IPv6 on supported SVIs; STP/RSTP settings, BPDU/Root Guard, paired LACP, LLDP, static MAC admission, DHCP snooping, DAI and IP Source Guard/shared static bindings, IGMPv2 snooping/querier and per-port multicast policy; existing wired 802.1X identity/lease/renewal policy | Wired profile provisioning/authentication actions and runtime tables |
| Host / server | Interface/admin, gateway/routes, static IPv6, DNS resolver and DHCP client; DHCP server pools/leases/reservations; local DNS zones, A/AAAA records, TTL and IPv6 listen option; LLDP on compatible nodes | Dedicated HTTPS/TFTP/NTP/SNMP/syslog/SSH service controls and native interactive consoles/traffic views |
| Firecracker microVM | Declared RAM/vCPU resource editor with full-lab budget validation; basic network settings remain read-only | Guest image/agent, multi-NIC roles, interactive guest management and measured resource usage |

IPv6, DNS and service profiles have real combination restrictions enforced by
the backend. For example, adding IPv6 to the IPv4 campus with dot1Q routing is
not an arbitrary supported mixed profile. Rootfs binaries are prerequisites:
BusyBox udhcpd for DHCP and dnsmasq for DNS. A saved service configuration does
not establish that a daemon is running or that DNS/DHCP packets succeeded.

The dashboard counts declared settings, not live packets/sessions. Current
runtime labels are snapshots requested by the desktop. Do not manufacture
live charts, logs, counters, firmware pages or licensed feature support.

## Commercial-firewall parity still open

A commercial device also offers vendor/version-specific object groups,
policy workflow, VPN, IPS/antivirus/web filtering, identity/SSO, HA, SD-WAN,
certificates, monitoring and administration. The current engine is not a full
commercial appliance implementation, and these must not become decorative
working-looking controls. Track implemented backend versus missing backend
versus missing GUI separately. Interface fidelity requires an explicitly chosen product/version and working
translations to our Linux guest engine; original firmware is not the target.

Prioritize richer native configuration and observations, then polish their
workflows against the supplied image. Static VXLAN stays on the roadmap after
LAN/GUI; EVPN/BGP and WAN remain separate later work.


## Switching management semantics

STP changes can apply mode/timers to the actual connected switch component in
one validated transaction. Only the selected switch's priority/port protection
settings are replaced; other switch priorities/port policies remain intact.
Classic Linux STP remains 802.1D. RSTP appears only on existing OVS backends.

Paired LACP requires 2..8 existing physical links to the same managed Linux
switch. Both endpoints are edited atomically. The UI supports active/passive,
min-links, explicit lacp_strict and the shared logical access/trunk policy.
Removal restores physical bridge ports; parallel unbundled links require STP.
No synthetic cables, negotiation, MLAG or PAgP are introduced.

LLDP edits declared physical ports and transmit/hold settings. Its rootfs must
contain lldpd/lldpcli, and the current engine disallows LLDP alongside LACP.
Port security configures static source-MAC admission on physical access ports,
with exactly the configured maximum addresses and restrict behavior. Dynamic
learning, sticky MACs and synthetic errdisable modes are not exposed.


## Access admission editors

Three sections now expose DHCP snooping, DAI and IP Source Guard. The current
engine requires physical access ports throughout the switch; trunks/LACP and
OVS are outside this profile. **Fichier → LAN sécurité access** creates a
five-node/four-link static-IP template compatible with these controls, without
enabling any protection or claiming DHCP leases by default.

Snooping controls monitored VLANs and trusted DHCP ports. DAI controls inspected
VLANs, its separate trusted ports and static IP/MAC/VLAN/port bindings. Source
guard selects off/IP/IP+MAC per access port and edits the same binding table.
DAI inspection can be disabled while bindings continue to support source guard.
Disabling snooping while dependent protections are active is rejected unless
explicitly opting to disable both; bindings are preserved. Edits are atomic
and stale revisions, duplicate bindings and trusted-client guard conflicts are
rejected. Dynamic leases are backend observations, never fabricated web rows.

## Access-security acceptance

Source 271303a passed native run 42364702892: HTTP-configured DAI and IP Source
Guard rejected the intended peers while the valid static binding passed.
Linux policy fingerprints and actual accept/drop counters were checked.
Snooping policy installation was verified; this static-IP fixture does not
exercise DHCP lease acquisition. See [native evidence](NATIVE_GUI_FLOW.md).

## Multicast web management

The seventeenth section exposes the existing Linux bridge IGMPv2 policy:
snooping, querier, router-port off/auto/permanent, unknown multicast flooding
and fast leave. It requires physical access ports in one VLAN and is hidden
for OVS. The LAN sécurité access template is compatible. Querier without
snooping and incompatible topology edits are rejected atomically. Removing the
explicit policy restores engine defaults; it does not mean disabling snooping.
Fast leave is intended for a single receiver per port. Actual MDB membership,
packet delivery and query observations remain runtime data, not draft rows.

## Wired admission web scope

The eighteenth section is available only on an existing validated wired 802.1X
NAS. It edits allowed identities, the 1..30-second local authorization ceiling
and the 0..3 renewal budget. Controlled port, peer, backend address and NAS SVI
are readable and preserved; private RADIUS and supplicant assets are neither
returned nor editable. Adding an allowed identity does not create a RADIUS
account. Whole-lab validation protects the existing managed peer identity.

This is the finite Linux EAP-MD5 profile, not arbitrary switch 802.1X, TLS or
multi-client admission. Import/provision the dedicated native profile first.
Applying edits changes the draft; save/stop/start applies policy, while native
authentication remains explicit. No browser login, background authentication,
credential editor or observed authorization status is introduced.

## Read-only Linux observations

Observations Linux displays the desktop's most recent successful inspection:
physical/logical link state, MAC/MTU, IPv4 routes and allowlisted MAC-admission,
DHCP snooping, DAI and IP Source Guard policy verification/counters. Read the
UTC timestamp as snapshot time, not continuous monitoring. Select the device
in the desktop, use Inspecter le réseau, then refresh the browser. No HTTP
backend-command endpoint is added.

Missing counters remain unavailable. Tokens and arbitrary inspection fields
are omitted. An operation in progress, another result/device/lab or a changed
draft invalidates the displayed snapshot. Draft equality is not proof that
saved settings are active in Linux. Live tables, session counters and
authentication status remain further work; configuration-section count stays 18.

## Firewall and MAC snapshot counters

The observation page now projects the managed IPv4 nftables table only:
chain/hook/default policy and rule/NAT comment, packet and byte counters.
Other tables, IPv6 rulesets and raw nft expressions are excluded. Missing,
negative or boolean counters remain unavailable, not zero. These cumulative
counters do not establish throughput, session totals or draft-policy equality;
NAT counters normally count only packets traversing its connection setup path.

MAC admission now reads the engine's actual per-port accepted/dropped metrics
and available/fingerprint_matches fields. Its prior generic projection did
not match that schema and displayed no counters. Static bindings and raw
rulesets are not exported by this observation page. A failed fingerprint is
shown explicitly rather than interpreted as a verified policy.

## Native console entry

The desktop device panel now has a CLI tab and a real external-terminal shell
entry for OCI nodes observed running. It uses the existing native `exec --tty`
path with a fixed `/bin/sh`; sudo authentication and all guest I/O stay on the
terminal descriptors. The browser cannot launch it. Missing/stopped/non-OCI
selection, pending operations and mismatched lab names are refused. Terminal
launch is recorded as requested, never as a confirmed guest connection.

Close the shell with exit before another native operation: the existing CLI
holds its lab lock for the session. Active shell changes do not edit the draft.
An embedded terminal, shell session supervision and packet viewing remain open.

## Native PCAP entry

The scrollable desktop PCAP tab selects a declared interface, duration (1..60 s),
packet limit and optional BPF filter. The snapshot length is fixed at 2048 bytes;
the engine's 16 MiB limit also bounds the maximum packet count. A running OCI
node and matching observed lab are required. A new output path is selected;
existing files and symlinks are refused before sudo, with O_EXCL/NOFOLLOW enforced
again by the native engine. Paths and filters stay separate argv values.

The terminal authenticates and invokes the existing bounded namespace-pinned
capture engine. It displays the real JSON result, then waits for Enter to close.
The UI records a request only; capture progress/completion is not fabricated.
Other lab commands remain usable during capture. The caller owns the mode-0600
PCAP. Integrated packet decoding, capture lifecycle/result presentation and
in-app export management remain open. No browser capture endpoint is exposed.
