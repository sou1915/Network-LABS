# Native node management coverage

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
| Firewall | Physical interfaces/admin, 802.1Q subinterfaces, IPv4 filtering with ordered named rules, default accept/drop, stateful mode, source/destination CIDR and interfaces, TCP/UDP destination ports; masquerade/SNAT/DNAT and DNAT port translation; routes/gateway/forwarding, DNS resolver, DHCP client/server, DNS server, LLDP on compatible nodes | IPv6 firewall/input policy, actual policy counters/conntrack observations, diagnostics/capture; richer supported service/security compositions |
| Router | Interfaces/admin, 802.1Q, IPv4 routes/gateway/forwarding, static IPv6 /64 and routes, DNS resolver, DHCP client/server, DNS server, LLDP on compatible nodes | OSPF/OSPFv3, RA/SLAAC/DHCPv6 and prefix delegation, relay, richer runtime diagnostics |
| Switch | VLAN declarations, access/trunk ports with native/allowed VLANs, SVI creation/addressing, static routes and forwarding, static IPv6 on supported SVIs; STP/RSTP settings, BPDU/Root Guard, paired LACP, LLDP, static MAC admission, DHCP snooping, DAI and IP Source Guard/shared static bindings | Wired 802.1X, multicast and runtime tables |
| Host / server | Interface/admin, gateway/routes, static IPv6, DNS resolver and DHCP client; DHCP server pools/leases/reservations; local DNS zones, A/AAAA records, TTL and IPv6 listen option; LLDP on compatible nodes | Dedicated HTTPS/TFTP/NTP/SNMP/syslog/SSH service controls and native interactive consoles/traffic views |
| Firecracker microVM | Read current declared basic configuration | Rich forms remain disabled; current editors target OCI |

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
versus missing GUI separately. Actual vendor firmware parity would require
an explicitly chosen vendor/version and a compatible actual appliance runtime.

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
