# Release 1 — scope (draft for the owner to confirm)

Release 1 is the smallest product a student can use end to end: build a small
LAN in the desktop app, run it on real Linux micro-VMs, configure it, test it,
save it and reopen it. Anything not listed here waits for a later release.
Current progress against this list is tracked in [STATUS.md](STATUS.md).

## User stories

1. **Build.** In the desktop app, place hosts, one switch, one router and one
   firewall, cable their ports and save the lab file.
   *Done when:* a five-node lab (two VLANs, router, firewall, two hosts) can be
   drawn and saved without editing JSON.
2. **Run.** Press Start: every node boots as its own micro-VM; Stop removes
   everything. *Done when:* start and stop work from the GUI on a laptop with
   KVM, and `status` shows each guest alive with its memory use.
3. **Configure.** Select a node and edit its addresses, routes, VLAN ports,
   firewall rules (with NAT) and DHCP server from forms; changes apply to the
   running guest or are refused with a clear reason.
   *Done when:* each of those forms changes a running micro-VM lab.
4. **Test.** Ping between nodes, open a console on a node, and capture packets
   on a port, all from the GUI. *Done when:* the three actions work on the
   reference lab and show their results in the app.
5. **Keep.** Save the running configuration and reopen the lab later with the
   same behaviour. *Done when:* a saved lab cold-restores and its pings,
   firewall decisions and DHCP leases behave as before.

## Required engineering (derived from the stories)

| Need | State (updated 2026-11-16) |
| --- | --- |
| Micro-VM host, router, firewall (NAT), DHCP guests | Done, real-KVM tested |
| Switch guest with access and trunk VLANs | Done, real-KVM tested on the Network LABS kernel; router-on-a-stick too |
| GUI start/stop/status for micro-VM labs | Done |
| GUI forms writing to running guests | Draft forms for every guest role; live apply for the firewall policy only |
| GUI ping, console and capture for guests | Capture done; ping is container-only; no guest console by design (decision needed) |
| Installable on Ubuntu 24.04 with documented KVM prerequisites | Partial; guest kernel and image must be provided by the user |

## Out of scope for release 1

- OSPF and other routing protocols; static routes only.
- DNS, RADIUS/802.1X, SNMP, Syslog, NTP, TFTP and HTTPS inside guests.
- STP, LACP, port security and other switch security features on guests.
- IPv6 on guests.
- Vendor-style (IOS/FortiOS) CLIs on guests; Linux shell console only.
- VMware/VirtualBox attachment, VXLAN/EVPN, WAN.
- New features on the container (OCI) runtime; it stays available as is.

## Rules while release 1 is open

- New features target micro-VMs only.
- Every feature lands with a real-KVM test and a line in STATUS.md.
- `main` is the only long-lived branch; pull requests target `main`.
