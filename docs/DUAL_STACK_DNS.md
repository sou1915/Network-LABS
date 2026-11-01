# Static dual-stack DNS service

This bounded profile adds a real local dnsmasq service over IPv4 and IPv6,
with UDP and TCP listeners on exactly its declared addresses. The reference
has two static routers between PC1 and PC2; both families have independent
forwarding policy and return routes. PC2 serves A and AAAA for server.lab.test.

```bash
# Use a trusted BusyBox rootfs with the existing --dnsmasq builder option.
python3 -m network_labs.appliances example --dual-stack-dns --rootfs /absolute/rootfs > dual-stack-dns.json
sudo python3 -m network_labs.appliances start dual-stack-dns.json
sudo python3 -m network_labs.appliances verify dual-stack-dns-lan PC1 PC2 --family ipv4
sudo python3 -m network_labs.appliances verify dual-stack-dns-lan PC1 PC2 --family ipv6
sudo python3 -m network_labs.appliances probe dual-stack-dns-lan PC1 server.lab.test --protocol dns --dns-transport tcp
```

The last command still exercises the existing IPv4 A probe. It does not select
AAAA or an IPv6 resolver. General probe IPv6 support is separate work. Guest
DNS tools that support explicit IPv6 servers can query 2001:db8:20::20 directly;
the dedicated native test uses an independent source-bound stdlib socket client
for both record types over both address families and UDP/TCP.

A server policy can include:

```json
{
  "interface": "eth0",
  "zone": "lab.test",
  "records": {"server.lab.test": "198.51.100.20"},
  "records_ipv6": {"server.lab.test": "2001:db8:20::20"},
  "listen_ipv6": true
}
```

`records` retains its required 1..256 A records. Optional `records_ipv6` adds
at most 256 local AAAA records, normalized to canonical ASCII names and IPv6
addresses. Names must belong to the local zone; duplicate normalized names
or duplicate addresses within a family are rejected for deterministic PTRs.
Link-local, scoped, multicast, unspecified, loopback and IPv4-mapped IPv6
addresses are excluded. A name can have one address of each family; IPv6-only
names in records_ipv6 are also allowed. The generated configuration must fit
64 KiB. dnsmasq host-record supplies the A/AAAA/PTR data described in its
[official manual](https://dnsmasq.org/docs/dnsmasq-man.html).

`listen_ipv6` defaults to false without adding a field to old manifests. True
requires a single-interface OCI host with declared static IPv4 and IPv6 on
eth0, and the service bound to eth0. Startup waits for DAD completion before
launching dnsmasq. IPv4-only DNS configurations retain their existing generated
configuration. No upstream resolver, host hosts-file inheritance, recursion
service, DNSSEC or dynamic registration is introduced.

DNS/resolver coexistence in an IPv6 lab requires IPv4 plus static IPv6 on every
physical host/router port. DNS and static resolver declarations are limited to
single-interface hosts; resolver files still contain IPv4 nameservers only.
RA/SLAAC/DHCPv6, OSPFv3, SVIs, subinterfaces, RA Guard and IPv6 firewall profiles
are excluded from this service composition, as are the other previously
unvalidated service/security combinations. This does not infer IPv6 security
from IPv4 policy. It is not IPv6-only DNS deployment or automatic DNS discovery.

Managed config and resolver files are audited alongside IPv4/IPv6 state before
save. Live changes require recreation. Restore starts a fresh daemon from the
saved declarations; DNS cache or connection snapshots are not persisted.

The dedicated native job checks A/AAAA and NXDOMAIN over both families and
transports, exact listener scope, actual packet captures, independent forwarding
outages, DNS outage with working ICMP in both families, service recovery,
config/resolver drift refusal, cold restore and host cleanup. CI results are
recorded in LAN_NEXT_STEPS.md after completion.

The explicit [combined DNS/AAA profile](DUAL_STACK_SERVICES.md) also validates
separate DNS and RADIUS nodes with a managed dual-stack SSH NAS.
