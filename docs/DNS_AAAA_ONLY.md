# Explicit AAAA-only local DNS zones

A managed DNS server may now declare `records: {}` when `records_ipv6` contains
at least one valid local AAAA record. No artificial IPv4 A answer is needed.
The A map remains explicit: omission, null, arrays and a zone with no A or AAAA
records are refused. The existing bounds remain 256 records per family and
64 KiB of observable configuration, with canonical zone/name/address checks.
Existing mixed A/AAAA and IPv4-only defaults remain unchanged.

```json
{
  "interface": "eth0",
  "zone": "lab.test",
  "records": {},
  "records_ipv6": {"server.lab.test": "2001:db8:30::10"},
  "listen_ipv6": true
}
```

`example --ipv6-dns-aaaa` creates the static IPv6 ROAS/tagged-transit reference
with this AAAA-only zone on the separate server. Build the existing BusyBox /
dnsmasq rootfs as described in IPV6_DNS_SUBINTERFACES.md, then:

```bash
python3 -m network_labs.appliances example --ipv6-dns-aaaa \
  --rootfs /absolute/rootfs-dns > ipv6-dns-aaaa.json
sudo python3 -m network_labs.appliances start ipv6-dns-aaaa.json
sudo python3 -m network_labs.appliances probe ipv6-dns-aaaa-lan PC1 \
  server.lab.test --protocol dns --family ipv6 --dns-transport tcp --json
```

DNS record family and transport are independent. An AAAA-only zone may also
use an existing IPv4 or dual-stack listener: no listener is implicitly added or
removed when the A map becomes empty. UDP/TCP AAAA queries return the declared
IPv6 address; an A query for that existing name returns NOERROR with no address
answers (NODATA), whereas an unknown local name returns NXDOMAIN. A managed
IPv4-family probe fails on NODATA rather than substituting an AAAA answer.
An explicit IPv6-family probe resolves AAAA through the selected guest resolver,
even when that resolver uses IPv4 transport.

The configuration still uses explicit local dnsmasq host records, no host
resolver, no upstream, no cache snapshot and no record-family fallback.
This increment adds no CNAME traversal, DNS64, DNSSEC, recursion, dynamic
registration or broader routing/security combinations. Save/restore retains
the empty A map and declared AAAA records, not live DNS state.

Native coverage extends the existing physical dual-stack and IPv6-only
subinterface jobs: real AAAA answers and A/NODATA over UDP/TCP, transport-family
independence, NXDOMAIN, managed probe family separation, wire captures and
cold restore. Exact validation evidence belongs in LAN_NEXT_STEPS.md.

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=dns-aaaa
```
