# IPv6-only DNS through a stateful forwarding firewall

`example --ipv6-dns-firewall` composes the existing physical IPv6 firewall with
a separate dnsmasq endpoint. PC1 (`2001:db8:10::10`) uses its explicit resolver
on PC2 (`2001:db8:20::20`) through FW1. Every non-loopback address is IPv6.
The reference permits client-to-server UDP/TCP destination port 53 and ICMPv6
echo requests, then uses conntrack for replies. Other forwarded traffic is
subject to default drop. The DNS rules pin both /128 endpoints and ingress/
egress ports. These are explicit local forwarding rules, not DNS authentication.

Build the existing trusted BusyBox/dnsmasq rootfs; the host needs nftables:

```bash
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --dnsmasq /usr/sbin/dnsmasq --output /absolute/rootfs-dns
python3 -m network_labs.appliances example --ipv6-dns-firewall \
  --rootfs /absolute/rootfs-dns > ipv6-dns-firewall.json
sudo python3 -m network_labs.appliances start ipv6-dns-firewall.json
sudo python3 -m network_labs.appliances probe ipv6-dns-firewall-lan PC1 \
  server.lab.test --protocol dns --family ipv6 --dns-transport tcp --json
```

DNS listens only at the declared IPv6 address. A and AAAA are DNS record types,
independent of transport: `192.0.2.20` is the example A answer, not a declared
IPv4 address or an IPv4 connectivity claim. Local static records, explicit
resolver selection, no upstream and no cache snapshot retain their existing
DNS scope. This profile adds no recursion, DNSSEC, DNS64 or encrypted DNS.

The firewall filters IPv6 forwarding only. Local input/output, NDP, traffic to
FW1 itself, application authentication and RA Guard are outside this profile.
There is no NAT66, dynamic IPv6, mixed dual-stack firewall, SVI, subinterface,
AAA or other security composition implied by this increment. Policy edits use
saved-manifest recreation, and unmanaged rules/tables/forwarding state refuse
save rather than being silently adopted. Save/restore retains configuration,
not learned conntrack flows or DNS runtime state.

The dedicated native scenario requires real UDP/TCP A/AAAA replies and a managed
IPv6 TCP DNS probe, DNS packet captures on both firewall ports, positive rule/
state/drop counters and UDP/TCP conntrack observations. A proven local HTTP
listener is denied across the firewall, with ingress SYNs and no egress SYNs.
DNS outage must leave permitted echo working. Forwarding outage must leave local
server DNS working. A separately recreated stateless policy permits echo with
an explicit return rule but blocks DNS replies despite a proven live local DNS
listener. Cold restore, drift refusal and host nftables/network invariants are
also required. Exact successful or pending evidence belongs in LAN_NEXT_STEPS.md.

Run this composition, existing IPv6 firewall and DNS/subinterface native
regressions, plus general CI, without an unrelated full native matrix:

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-dns-firewall
```
