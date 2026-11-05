# Separate IPv6 DNS and named HTTPS

`example --ipv6-dns-https` creates five static IPv6-only OCI nodes:
PC1, R1, R2, HTTPS PC2 and DNS PC3. DNS uses its own R2-facing network
(`2001:db8:30::/64`), separate from HTTPS (`2001:db8:20::/64`). PC1's only
managed resolver is `2001:db8:30::30`; its `secure.lab.test` AAAA record
points to HTTPS at `2001:db8:20::20`. There is no A record or IPv4 fallback.

Build separate images as in [HTTPS_SERVER.md](HTTPS_SERVER.md). The server
image needs NGINX and the supplied public CA/leaf chain/matching mode-0600
key. The client image needs dnsmasq (`rootfs --dnsmasq /usr/sbin/dnsmasq`)
because PC3 uses it to run the managed resolver. This image on the client
and routers does not automatically start a DNS server on those nodes.
The leaf must include DNS SAN `secure.lab.test`; add IP SAN
`2001:db8:20::20` if literal-address verified probes are also desired.

```bash
python3 -m network_labs.appliances example --ipv6-dns-https \
  --rootfs /path/to/server-rootfs \
  --https-client-rootfs /path/to/client-dns-rootfs > ipv6-dns-https.json
sudo python3 -m network_labs.appliances start ipv6-dns-https.json
sudo python3 -m network_labs.appliances probe ipv6-dns-https-lan PC1 \
  secure.lab.test --family ipv6 --protocol https --dns-transport tcp \
  --ca-file /path/to/ca.pem --json
```

The probe requests AAAA over explicit UDP or TCP from the managed IPv6
resolver, then verifies the original DNS name against only the supplied CA.
DNS resolving an address is not certificate trust. There is no host resolver,
alternate nameserver, IPv4 or literal-address fallback on DNS failure.
The HTTPS service retains its fixed endpoint and exact IPv6-only listener;
this adds service composition, not application content or a browser GUI.

One separately managed IPv6 DNS server is required when using resolvers
with IPv6 HTTPS. Clients must use exactly that resolver; service-node
resolvers and DNS/HTTPS co-location are refused. Both DNS/HTTPS and the
separate [HTTPS/firewall](IPV6_HTTPS_FIREWALL.md) profiles remain supported,
but their three-service combination is refused. Dynamic addressing/routing,
dual-stack, VLAN/SVI/subinterfaces and other services remain outside this
composition. DNSSEC, encrypted DNS, mutual TLS and automatic certificate
lifecycle remain separate work.

## Validation

The dedicated native scenario checks named certificate-verified HTTPS with
UDP/TCP DNS, actual DNS/TLS packets, fixed GET body, wrong CA/name and unknown
DNS-name controls. DNS outage must break named HTTPS while literal verified
TLS and the same HTTPS process remain live. HTTPS outage must preserve DNS
answers and its process. It checks explicit recovery, resolver/DNS/HTTPS
config drift refusal, exact saved declarations, cold restore and host
namespace/link/IPv4/IPv6 route/rule/forwarding invariants.

Native validation is pending for this implementation checkpoint. Run with:
`gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-dns-https`.
The selector also runs baseline IPv6 HTTPS, IPv6 tagged DNS, dual-stack DNS
and general CI regressions; intentionally skipped jobs are not new proof.
