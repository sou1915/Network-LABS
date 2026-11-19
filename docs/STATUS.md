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
| eBGP on router guests (FRR zebra + bgpd in the guest) | `--bgp` | Image built `microvm-rootfs --with-routing` (BIRD and FRR); one-hop eBGP, up to 4 peers and 8 networks; networks announced only when held exactly (FRR's import check); not yet with OSPF on the same router |
| IOS extended access lists on router guests, inbound | — (mission « Filtrer le Wi-Fi invités ») | Compiled into the guest forward chain (image with iptables); entries in order, implicit deny, stateless; live with the routing change |
| Node terminal on micro-VMs | — (CLI tab › « Ouvrir le terminal de … », or `node-console LAB NODE`) | One sudo; vendor prompt and modes (enable / configure terminal … end, system-view … return, configure … commit), show, ping, configuration applied live; hosts get ping, ip addr, ip route. Typed requests only, no guest shell |
| Command catalogue per node | — (« 📖 Catalogue de commandes » under the terminal button; « ? », « MOT ? », « help SUJET », Tab in the terminal) | Every command the node's terminal accepts for its vendor and role (IOS, EOS, VRP, Junos, PAN-OS, FortiOS, RouterOS, host shell): mode, syntax, role, example written with the node's own ports and addresses. Tests apply every example through the vendor parser and check every show command. Sub-mode prompts (R1(config-if)#, [R1-ospf-1-area-0.0.0.0]) |
| Packet Tracer-style workflow | Library click/drag adds a micro-VM (setup's kernel and disk, model's ports, unnumbered); cable tool joins first free ports (Ctrl for the dialog); blank new project; Start saves to the projects folder; double-click opens the terminal | Unnumbered ports allowed on micro-VMs; port addresses change live (IOS `ip address`, host `ip addr add/del`, `ip route add/del`); IOS abbreviations and port-name forms; `do`; a block applies at `exit` and before `do`. Real-KVM test `test_native_microvm_quick` configures unaddressed guests only from their terminals |
| In-app CLI | Double-click a running micro-VM, or the CLI tab's terminal button: a CLI window per device inside the workbench | console_server.py: one root server per lab, started by the bridge after start/status with the sudo just given (« consoles » re-activates it), Unix socket 0600 owned by the user and SO_PEERCRED-checked, typed Console lines only (no shell), sessions per window, leaves with the lab. Window: history, Tab, IOS-style « ? ». OCI nodes keep their Linux shell in a terminal emulator |
| IOS as in Packet Tracer | CLI window: Press RETURN, typed after the prompt, `?` next words / `<cr>`, Tab, Ctrl+Z, `--More--` | Real port `shutdown` on micro-VMs (link down, routes re-added on `no shutdown`, model and read-back aware); new routers start shut; each IOS line applied at once onto the block since `conf t` (an incomplete block waits); IOS errors with `^`, `% Incomplete command.`, ambiguity, unknown EXEC words; `%LINK`/`%LINEPROTO`/`%SYS` messages; `wr`, `copy run start`; `show running-config` and `show ip interface brief` as IOS prints them (full port names, administratively down) |
| CLI before the lab runs | Double-click any micro-VM device, lab stopped: the same CLI on the project (header says so) | draft_lab.DraftLab stands in for the running lab: configuration lines change the device in the project (applied at Start), show is computed from the configuration and the network model (addresses, shut ports, static/OSPF/BGP routes, VLANs, OSPF neighbours, BGP sessions), ping is the model's verdict. Nothing touches a micro-VM |
| CCNA IOS command set | Every Cisco device's CLI | ios_store.py keeps ~60 CCNA configuration commands IOS takes (global, interface, line con/vty, router rip/eigrp blocks) in node['cli_config'] and shows them where IOS does; effects: hostname (prompt), banner motd, enable secret/password and console login (asked, three tries), service password-encryption (real type 7), description; stored only (said in the catalogue): SSH, users, NTP, logging, SNMP, NAT, RIP, EIGRP, port-security, spanning tree, VTP. Numbered ACLs (standard and extended) filter for real; interface range; ios_exec.py: show version, cdp neighbors, interfaces, startup-config, history, clock, users, privilege, ip protocols, interfaces trunk; copy run start / wr / erase startup-config; output filters include, exclude, begin, section |
| IOS RIP and PAT for real | router rip / version / network / passive-interface; ip nat inside/outside + ip nat inside source list N interface X overload | rip.py: classful networks select the RIP ports, passive ports announced without updates, version 2 by default; the guest agent's RIP_RENDER/START/STOP/SHOW run BIRD 2 RIP (not with OSPF on the same router), routes shown as R [120/hops]; the network model computes them by hop count. ios_nat.py compiles PAT into masquerade entries of the router's guest firewall (only with inside and outside ports marked, as IOS), show ip nat translations/statistics from the guest's conntrack. Real-KVM tests: test_native_microvm_rip_ios, test_native_microvm_nat_ios. Static NAT (`ip nat inside source static L G`: DNAT and SNAT on each outside port; R1 holds G as a /32 on the outside port so it answers ARP, never saved in the profile) and pools (`ip nat pool`, `… list N pool P [overload]`: SNAT to the pool's first address with overload, to the range without; 16 addresses at most) run too: test_native_microvm_static_nat_ios |
| Live routing change (static routes, gateway, OSPF) | — (CLI tab › « ⚡ Appliquer au lab en marche ») | Only what differs changes; BIRD restarts if OSPF changed; read back, rolled back on failure |
| Firewall sessions view | — (`sessions LAB NODE`) | Read-only; `clear-sessions` refused on guests |
| Switch guest, one untagged VLAN | `--switch` | 2–4 unnumbered ports bridged in the guest; runs on any guest kernel |
| Switch guest VLANs: access and trunk ports | `--switch-vlans` | Bridge VLAN filtering in the guest; needs the Network LABS kernel (`tools/guest_kernel`) |
| IOS DHCP relay (`ip helper-address`) | — (R1 LAN port `ip helper-address 10.0.12.2`; R2 `ip dhcp pool` with the remote LAN's `network`) | The guest agent's own relay (`--dhcp-relay`; busybox-static has no dhcprelay): giaddr set to the helper port's address, sent to the server through the kernel's routes, replies broadcast back on the port; started at boot and live. A pool whose network is on none of the server's ports is a relayed pool (`dhcp_server.network`), served on the port toward that LAN (static route, else the only OSPF/RIP port). `show ip dhcp binding` from the guest's lease file. One server per relay router. The relayed pool itself is set before ▶ (the DHCP server does not change live). Real-KVM test `test_native_microvm_relay_ios` |
| traceroute / tracert | — (router terminal `traceroute A.B.C.D`, Huawei `tracert`, PC `traceroute` or `tracert`) | Real probes from the micro-VM, one hop per guest request (BusyBox traceroute, 1 s wait), three per hop; IOS, VRP, BusyBox and Windows (Packet Tracer PC) output. Stops after 3 silent hops in a row (IOS would go on to 30). A stopped lab answers from the network model. Real-KVM proof in `test_native_microvm_rip_ios` (four hops) |
| Switch management SVI | — (switch terminal: `interface vlan 1`, `ip address`, `no shutdown`, `ip default-gateway`) | One SVI per switch micro-VM, its address on the guest bridge (with VLAN filtering, the bridge itself joins the SVI's VLAN untagged); shut when created, as on a Catalyst; the default gateway comes from the stored `ip default-gateway` line when it lies in the SVI's subnet (so it may be typed first); live; the network model puts the SVI on its VLAN's segment; `sh ip int br` lists Vlan1. Real-KVM proof in `test_native_microvm_switch_live` |
| Switch changes on a running lab | — (switch terminal: `vlan N` / `name`, `switchport …`, `shutdown`) | Typed IOS lines change the running bridge: VLAN filtering turns on with the first VLAN, ports move untagged, shut ports go link-down; `show vlan brief`, `show interfaces status` as on a Catalyst. Real-KVM test `test_native_microvm_switch_live` (Network LABS kernel). `no vlan N` while ports still use N keeps the VLAN (IOS would make those ports inactive) |
| Router-on-a-stick: 802.1Q subinterfaces on router/firewall guests | `--router-on-a-stick` | Unnumbered trunk port with `ethN.VID` subinterfaces; needs the Network LABS kernel |
| DHCP server and client in guests | `--dhcp` | Local pool only; leases via `microvm-dhcp-leases` |
| OSPFv2 area 0 on router guests (BIRD 2 in the guest) | `--ospf` | Image built `microvm-rootfs --with-routing`; no static routes on OSPF routers; process-wide hello/dead; learned routes are never saved |
| Capture on a guest port | — (`capture LAB NODE ethN`) | Recorded on the host-side TAP |
| Isolation and limits | — | Jailer chroot, per-lab uid block, cgroup memory/CPU caps, vCPU and memory budgets |

## Micro-VM guests — not yet

- Routed SVIs on switch guests (a management SVI works), and firewall rules on subinterfaces (guest firewall
  rules name physical ports only). Static routes through a subinterface are unit-tested only.
- STP, LACP and switch security features on guests.
- OSPF areas other than 0, OSPF on subinterfaces or switch guests, iBGP and route policies beyond announced networks, OSPF and BGP on one router (OSPF moves to FRR next), other routing protocols; DNS, RADIUS, SNMP, Syslog, NTP, TFTP and HTTPS inside guests
  (these exist on containers only).
- DHCP remote pools and reservations on guests.
- IPv6 on guests.
- Device-style CLI/web management on guests (only resources and firewall pages today).
- Live changes other than firewall policy, static routes, gateway and OSPF (addresses, VLAN ports, DHCP apply on restart), and a guest console.
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

Tk desktop app (`python3 -m network_labs`) that opens the native lab workbench directly (the old
« Switching Studio » canvas window was removed; its engine and example labs stay, in `demo_labs.py`): the
workbench (topology editing, lifecycle, inspection, capture and console
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

**Guided missions (Scénarios tab).** Each mission loads a real micro-VM lab with vendor models,
a story, goals and hints (`appliances/missions.py`): *La route manquante* (troubleshooting,
Cisco ISR + Juniper MX), *Isoler un poste dans un VLAN* (Catalyst, needs the Network LABS
kernel) and *Publier un serveur derrière le pare-feu* (FortiGate VIP and policy). The student
configures with any tool (forms, vendor CLI, vendor web pages). **Vérifier la configuration**
grades the draft (routes, switchports, trunks, Virtual IPs, and packets run through the
firewall policy: DNAT, then first matching rule, then the default). **Tester sur le lab**
sends the mission's pings from the running guests (one sudo-confirmed request) and grades what
the network did. Two more missions: *Routage inter-VLAN sur un seul lien* (router-on-a-stick
troubleshooting: a subinterface tagged with the wrong VLAN) and *Distribuer les adresses avec
DHCP* (an IOS DHCP pool with excluded addresses). The IOS subset now covers 802.1Q
subinterfaces (`interface gi0/0/0.20`, `encapsulation dot1Q 20`) and DHCP pools (`ip dhcp
pool`, `network`, `default-router`, `dns-server`, `lease`, `ip dhcp excluded-address`). Each
student's best score, solved missions, hints used and micro-VM paths are kept in a private
`~/.config/network-labs/progress.json` (badges and a progression count on the mission list). Real-KVM tested: the broken route lab fails its pings, the IOS fix passes.

**OSPF between three vendors.** Router guests run real OSPFv2 (area 0) with BIRD 2 inside the guest:
the agent writes BIRD's configuration from typed fields only (`OSPF_START router-id hello dead
port:cost:stub:type:priority,...`), byte-identical to the lab's own rendering, which the startup and
the save read back. The guest's BusyBox `ip route` never prints a route's protocol, so BIRD's
routes are told apart by the metric BIRD's kernel protocol gives them (32). The vendor CLIs configure it: IOS and EOS `router ospf`, `router-id`, `network …
area 0`, `passive-interface`, `ip ospf cost|network|priority`; VRP `ospf 1 router-id`, `area 0.0.0.0`,
`network`, `silent-interface`, `ospf cost|network-type|dr-priority`; Junos `set protocols ospf area
0.0.0.0 interface … [passive | metric N | interface-type p2p]` and `routing-options router-id`. Live
`show ip ospf neighbor` (IOS, EOS), `show ospf neighbor` (Junos), `display ospf peer brief` (VRP) read
the guest's BIRD, and the route tables show OSPF routes with BIRD's metric. Mission *OSPF entre trois
constructeurs*: R2 (Juniper MX204) and R3 (Huawei AR6120) already run OSPF; the student brings R1
(Cisco ISR 4331) in, LAN passive; a real check reads R1's neighbour table (2.2.2.2 Full), then pings
cross the three routers. The workbench staggers three or more routers in a row and draws their
cables as L-shapes, clear of the titles. Mode panne gains an OSPF lab (same three routers) with three faults: OSPF
removed from R1, R2's link toward R3 made passive, R3 no longer advertising its LAN; each is repaired
from its own vendor's CLI and graded by comparing OSPF behaviour, not text. The device page's live relevé lists OSPF-learned
routes as « Apprise OSPF » (with BIRD's cost; never an écart), the OSPF interfaces (active or passive,
cost, Full neighbours) and the neighbour table, with a verdict when an active interface has no Full
neighbour.

**Generated scenarios (Mode panne › Scénarios générés, 1 200 réseaux).** Each number builds the same
micro-VM network (`appliances/scenarios.py`): one of four families (sites in a chain, a star around a core
router, a VLAN campus with or without router-on-a-stick, an Internet exit behind a FortiGate or Palo Alto
with NAT), with random size, addressing, names, vendor models and routing (static or OSPF), and one
random fault among 14 kinds: missing static route, route through the wrong neighbour, gateway or transit
address, host gateway, OSPF passive / unannounced network / removed, access VLAN, trunk VLAN, subinterface
tag, swapped cables, firewall rule, NAT. A network model (`appliances/network_model.py`: Ethernet segments
through access/trunk ports and plain bridges, connected networks, gateways, static and OSPF routes, DHCP
leases, firewall policy, masquerade and DNAT with replies tracked back) keeps only faults that change what
the network does, fixes what each probe (pings between hosts, up to 12) should give, and grades a repair
by behaviour: any correct fix passes. The student gets only a user ticket; « Un peu d’aide » reveals one
step per click (the probes in error, where the packet stops, the device, the kind of fault, the
solution), each counted in the progress file. Generated labs open in a tree layout (sites side by side,
LANs under their router, hosts grouped by VLAN) zoomed to fit; a VLAN box covers one island of cabled
switches, so VLAN 1 at two sites is two LANs. The model agrees with every lab tested on
real guests; all 1 200 scenarios are distinct and generated in about 15 s by the unit tests.

**Unique scenarios and « Mes scénarios gardés ».** « ✨ Nouveau » draws a scenario from a random 40-bit seed
outside the catalogue, shown as a code (`NL-XXXX-XXXX`, Crockford base 32; the code rebuilds it). Every
scenario a student is given leaves a fingerprint (its network without the micro-VM paths, and its fault) in
the private progress file, and a new one is drawn again if it matches one already seen: the same network and
fault never come twice. « ★ Garder ce scénario » saves the whole scenario (broken and working labs, pings,
expected results, fault, ticket) as a private JSON file under `~/.config/network-labs/scenarios/`, so it comes
back identical even if the generator changes, with today's kernel and disk paths; the list reopens or deletes
it. Real pings for a generated or saved scenario carry the scenario's own probes in the privileged mission
request (validated: node names, IPv4 addresses, at most 12), since the backend cannot rebuild it.

**Packet replay (PCAP tab › Suivre un paquet).** From the selected running node, one real ping is
sent while every link of the lab is recorded at once (`appliances/packet_trace.py`, one bounded
capture per link, no lab lock held while recording). The workbench then replays the packet on the
topology, cable by cable in time order: request in orange, reply in green, with the addresses
seen on each wire, the 802.1Q tag and a NAT mark where the addresses change, plus a hop table.
Real-KVM tested on the NAT firewall: VM2's request leaves as 192.0.2.20 and crosses FW1's
outside link as 198.51.100.1.

**Troubleshooting mode (Mode panne).** Three working labs (two routed sites, two VLAN
switches, a NAT firewall) each get one hidden fault drawn at random from ten
(`appliances/faults.py`): a missing route, a wrong router address, a wrong host gateway, a
port in the wrong VLAN, a trunk without its VLAN, a removed or denied firewall policy, a
removed Virtual IP. Only the user's symptom is shown; hints end with the solution. Grading
checks the repair (by behaviour for firewall policies) without naming the fault before it is
repaired, and runs each lab's health probes on the running guests. Real-KVM tested: the
firewall lab's probes hold on the working lab and the inbound-deny fault fails the
publication probe.

**Device pages.** The GUI tab opens with a device header (drawing, name, brand · model, role,
status, port count, runtime, CLI syntax). The browser management page (**Gestion web**) shows
a product header, a front panel with every model port (declared ports with link LED, details
and neighbour; switch ports coloured by VLAN; undeclared model ports dimmed) and a dashboard per
role: firewall security policy and NAT tables, router interfaces (with 802.1Q subinterfaces)
and declared routing table, switch VLAN membership and port modes. Tables use vendor port
names; switches show no address fields. All values come from the lab draft
(`appliances/device_view.py`, `native_device_view.js`).
On a running lab, **Relever l’état réel** on the dashboard reads the node (one sudo-confirmed
`show` request: interfaces and addresses, routes, the switch bridge's VLAN entries, and a
firewall's tracked connections) and compares it row by row with the draft: each interface,
static route and VLAN entry is marked conforming, missing or undeclared. Real-KVM tested on
the NAT firewall (its ports and the masqueraded ICMP session).

**FortiOS-style pages (Fortinet models).** Gestion web opens on a page organised like FortiOS
(Dashboard › Status; Network › Interfaces, Static Routes; Policy & Objects › Firewall Policy,
Virtual IPs; System › Settings) with its terms, table columns and Create New → form → OK flow,
in a neutral look (no vendor logo, colours or assets). Each form shows the FortiOS CLI block it
sends, applied to the draft by the CLI tab's parser (`/api/cli`). Policy NAT (`set nat enable`)
and Virtual IPs (`config firewall vip`, with port forwarding) are part of the FortiOS subset.
The page carries FortiOS's whole menu tree; items the lab cannot back (security profiles, VPN,
SD-WAN, HA, FortiGuard, …) are shown greyed with the reason instead of forms that would do
nothing. The interface form includes the DHCP server (`config system dhcp server` with
`config ip-range`), served by the node's real DHCP daemon.
"Vue Network LABS" returns to the standard device page.

**Vendor configuration console (CLI tab).** Cisco, Fortinet, Juniper, MikroTik, Arista, Huawei and
Palo Alto models show their lab configuration in IOS, FortiOS, Junos, RouterOS, EOS, VRP or PAN-OS syntax
(`network_labs/appliances/vendor_config.py`), and commands typed there are written to the
lab draft and validated like the forms; a refused command is reported with its line.
Subsets: interface addresses and static routes in all four; firewall policies in FortiOS
(`config firewall policy`) and RouterOS (`/ip firewall filter`, chain forward); VLANs and
access/trunk switchports in IOS, EOS and VRP (`vlan batch`, `port link-type`); PAN-OS zones
(one port per zone), static routes and security rules (`application any` only; route names are not kept). They work for micro-VMs and containers alike because they
edit the draft; the change reaches the guests on the next start (or the live firewall
action). This is configuration syntax, not the vendor's operating system: there is no
live state beyond the read-only commands below, and other brands keep the forms only.

**Live vendor `show` commands (CLI tab, running lab).** The same brands print the running node's
state in their vendor's layout (`network_labs/appliances/vendor_show.py`): IOS `show ip interface
brief`, `show ip route`, `show vlan brief` (switches; abbreviations such as `sh ip ro` work);
FortiOS `get system interface`, `get router info routing-table all`; Junos `show interfaces terse`,
`show route`; RouterOS `/interface print`, `/ip address print`, `/ip route print`; EOS `show ip
interface brief`, `show ip route`, `show vlan`; VRP `display ip interface brief`, `display ip
routing-table`, `display vlan`; OSPF neighbours on router guests running OSPF (see above); PAN-OS `show interface all`, `show routing route`. One sudo-confirmed
`show` request reads the node (micro-VM agent read-only requests, or `ip -j` in a container); later
commands format that observation locally until **Relire**. Vendor `ping` (`ping`, `execute ping`, `/ping`,
`ping host`) sends five real one-second echo requests from the running node (guest agent or the
container's namespace) and prints them in the vendor's layout; each ping is its own sudo-confirmed
request. This gives micro-VM nodes a GUI ping. Values come from Linux only: no counters,
timers or hardware fields a Linux node does not have. Real-KVM tested in the router-chain test.

## How to run

```bash
python3 -m network_labs                                   # desktop app
python3 -m network_labs.appliances doctor                 # what this host can run
python3 -m network_labs.appliances setup --download      # first launch: verified Firecracker + kernel, one full disk
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
