# IPv6-only DNS across static router subinterfaces

`example --ipv6-dns-subinterfaces` composes the existing static IPv6 ROAS
reference with a separate dnsmasq endpoint. PC1 uses the explicit IPv6 resolver
on PC4 across VLAN 10, R1's tagged VLAN 100 transit, and R2's physical server
LAN. PC3 remains on VLAN 20. All non-loopback addresses and routes are IPv6;
router parents remain unnumbered, and IPv6 forwarding is explicit.

Build a trusted BusyBox rootfs with dnsmasq, then generate the reference:

```bash
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --dnsmasq /usr/sbin/dnsmasq --output /absolute/rootfs-dns
python3 -m network_labs.appliances example --ipv6-dns-subinterfaces \
  --rootfs /absolute/rootfs-dns > ipv6-dns.json
sudo python3 -m network_labs.appliances start ipv6-dns.json
sudo python3 -m network_labs.appliances probe ipv6-dns-subinterfaces-lan PC1 \
  server.lab.test --protocol dns --family ipv6 --dns-transport tcp --json
```

The DNS policy opts into `listen_ipv6:true` on a statically numbered
single-interface host. Without an IPv4 interface address it renders only the
explicit IPv6 listener, with no wildcard/IPv4 listener or upstream resolver.
An explicit A-record map remains required; it may be empty if valid AAAA
records exist (see [DNS_AAAA_ONLY.md](DNS_AAAA_ONLY.md)). Both empty remain
refused. The example A value `192.0.2.10` is DNS answer
data, not an IPv4 route or a connectivity claim. Both record types can be
queried through IPv6 UDP/TCP; `server.lab.test` has AAAA `2001:db8:30::10`.
There is no DNS64, DNSSEC, recursion, dynamic registration or cache persistence.

This composition is restricted to static IPv6-only physical hosts, existing
static router dot1Q subinterfaces, and Linux VLAN switching. It does not enable
mixed/partially numbered dual-stack subinterfaces, AAA, DHCP/RA/SLAAC, OSPFv3,
SVIs or forwarding firewall/security combinations. Existing physical dual-stack
DNS behavior stays in place, including refusal of partially numbered profiles.

The dedicated native scenario requires real dnsmasq A/AAAA answers over IPv6
UDP/TCP, IPv6-only sockets/address observations, VLAN 10/100 DNS captures,
NXDOMAIN, service outage/recovery, static-route and VLAN failure isolation,
configuration/route/VLAN drift refusal, declarative cold restore and host
namespace/link/route/rule/forwarding invariants. Exact results are recorded in
LAN_NEXT_STEPS.md; local skips are not native proof.

For targeted validation (plus general tests and existing physical dual-stack
DNS/static IPv6 subinterface native regressions):

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-dns
```
