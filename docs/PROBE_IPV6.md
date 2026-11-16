# Explicit IPv6 service probes

`probe --family ipv6` selects IPv6 destinations and a directly matched AAAA
query for DNS names. The default stays `--family ipv4` and A. Literal addresses
must match the selected family. There is no Happy Eyeballs, alternate-address
selection or fallback between address families.

```bash
python3 -m network_labs.appliances example --dual-stack-dns --dns-resolver-family ipv6 --rootfs /absolute/rootfs > dual-stack-dns.json
sudo python3 -m network_labs.appliances start dual-stack-dns.json
sudo python3 -m network_labs.appliances probe dual-stack-dns-lan PC1 server.lab.test --family ipv6 --protocol dns --dns-transport tcp
sudo python3 -m network_labs.appliances probe dual-stack-dns-lan PC1 2001:db8:20::20 --family ipv6 --protocol tcp --port 53
```

The reference creates DNS, not HTTP/HTTPS/SNTP servers. Those probe protocols
also accept `--family ipv6` when a suitable remote service is actually listening.
HTTPS still requires `--ca-file`; it verifies the original DNS name or the
unbracketed IPv6 address against that CA, with TLS 1.2 minimum. IPv6 literal HTTP
Host headers use brackets, and include a non-default port. HEAD accepts only
2xx, does not follow redirects and does not validate/download the body. TCP
connection establishment remains separate from HTTP(S) application success.
SNTP validates its existing bounded unauthenticated response and never sets clocks.

A DNS-name probe reads exactly one nameserver from the guest resolver file.
Its transport family follows that address independently of the target family:
AAAA can travel over IPv4 DNS; A can travel over IPv6 DNS. The worker binds to
an observed usable source address of the resolver's family. A missing usable
source blocks the DNS stage; neither the host resolver nor another family is
tried. For target connection stages it binds the selected target-family source.
JSON includes `address_family`, the main endpoint, `dns_endpoint` when used,
`record_type`, and the actual source/server/transport in each stage request.

Static `resolvers` declarations now accept canonical unscoped IPv6 literals on
numbered single-interface IPv6 hosts. Composition validation requires one of
the separately supported managed DNS/resolver profiles. The original reference
here uses static dual-stack physical routing; later profiles also cover
[IPv6-only tagged DNS](IPV6_DNS_SUBINTERFACES.md),
[DNS/firewall](IPV6_DNS_FIREWALL.md), [DNS/TFTP](IPV6_DNS_TFTP.md) and
[physical OSPFv3 DNS](IPV6_DNS_OSPFV3.md).
`example --dual-stack-dns --dns-resolver-family ipv6`, or the same option with
`--radius-dns`, chooses an IPv6 resolver explicitly. Omitting it retains IPv4.
The existing maximum-three resolver policy remains, but this diagnostic refuses
multiple nameservers rather than silently choosing one or failing over.
No DHCPv6 DNS discovery is added by this diagnostic.

UDP, TCP and matched-TC-only `auto` share the existing DNS rules for A and AAAA:
matching ID/question/type/class, one stage deadline, at most 4096 response bytes,
exact framed reads, and no use of partial truncated answers. A malformed or timed
out UDP reply never causes TCP retry. NXDOMAIN and a valid answer without the
selected direct address type fail resolution. Malformed packets remain unknown.
Only complete direct records are returned; CNAME chains, EDNS and DNSSEC remain
unsupported. Multiple address answers block subsequent transport selection.

Literal loopback, multicast, unspecified, link-local/scoped and IPv4-mapped IPv6
targets are rejected; local routes/addresses are rejected for transport checks.
Route evidence includes the bound IPv6 source. Endpoints still require an
observed usable unique address on a running single-interface OCI host and no
pending configuration. There is no implicit protocol or family fallback.
Timeouts remain 1..5 seconds per wire stage, with a bounded parent worker.
Observed failures do not identify a routing/filter/service root cause.

The native job uses real routed dnsmasq and the managed probe command API for
DNS A/AAAA over IPv6, AAAA over an IPv4 resolver, TCP, HTTP, TLS and SNTP.
HTTP/TLS/SNTP listeners are explicitly test-owned stdlib processes in the remote
namespace, reaped before teardown. They prove client behavior; this original
probe increment did not add persistent managed IPv6 servers. A separate
[IPv6 NTP reference](IPV6_NTP.md), [relay](IPV6_NTP_RELAY.md) and
[static IPv6 HTTPS server](IPV6_HTTPS.md) now exist separately; those
managed servers are not supplied by this probe fixture. Wrong CA/name, 404/302, NXDOMAIN,
NODATA without A fallback, malformed SNTP, DNS outage with working literal HTTP,
IPv6 route loss with working IPv4, drift refusal, cold restore and packet evidence
are checked. Results are recorded in LAN_NEXT_STEPS.md.
