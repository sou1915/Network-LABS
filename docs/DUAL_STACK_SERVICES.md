# Static dual-stack DNS and AAA coexistence

The `--radius-dns` extension combines the separately validated DNS and AAA
profiles with explicit routing and separate DNS/RADIUS service nodes. It
adds no new authentication fallback, daemon implementation or runtime image.
Use a trusted rootfs containing BusyBox, dnsmasq, Dropbear and FreeRADIUS with
matching modules/dictionaries, as described in the individual service guides.

| Node | Role | Service address |
| --- | --- | --- |
| PC1 | SSH NAS and DNS client | 192.0.2.10; 2001:db8:10::10 |
| R1 | Static dual-stack router | PC1 LAN and inter-router transit |
| R2 | Static dual-stack router | Transit, RADIUS LAN and separate DNS LAN |
| PC2 | Separate RADIUS server; native test SSH client | 198.51.100.20; 2001:db8:20::20 |
| DNS1 | Separate DNS server | 203.0.113.53; 2001:db8:30::53 |

R1 declares routes to both the RADIUS LAN and DNS LAN through R2; all hosts
have explicit return paths in both families. DNS serves A/AAAA for nas.lab.test
and listens on the DNS1 addresses over UDP/TCP. PC1's managed resolver file
contains DNS1's IPv4 address. General `probe` remains IPv4 A only; explicit
IPv6 DNS clients can query the IPv6 listener independently.

```bash
umask 077
python3 -m network_labs.appliances example --radius --radius-ssh --radius-dual-stack --radius-dns \
  --rootfs /absolute/rootfs --ssh-authorized-key /absolute/id_ed25519.pub \
  --radius-user learner --radius-password-file /absolute/password \
  --radius-secret-file /absolute/shared-secret > dual-stack-services.json
sudo python3 -m network_labs.appliances start dual-stack-services.json
sudo python3 -m network_labs.appliances verify dual-stack-services-lan PC1 DNS1 --family ipv4
sudo python3 -m network_labs.appliances verify dual-stack-services-lan PC1 DNS1 --family ipv6
sudo python3 -m network_labs.appliances probe dual-stack-services-lan PC1 nas.lab.test --protocol dns --dns-transport tcp
```

Credential-file rules are unchanged from [DUAL_STACK_RADIUS.md](DUAL_STACK_RADIUS.md).
SSH still uses explicit IPv4/IPv6 addresses and a public-key transport gate,
then freshly verified IPv4 RADIUS PAP plus local action authorization before
fixed non-root diagnostics. Its backend address is a declared IPv4 literal;
it is not selected by DNS. A DNS failure therefore need not stop literal-address
SSH/AAA. A RADIUS failure still denies all protected diagnostics even when
DNS and both SSH listeners remain available. No cached-accept fallback appears.

DNS servers must be on separate nodes without management, radius_access or
radius_server. The existing RADIUS service-node separation remains enforced.
A NAS may use static DNS resolvers. Other bounds remain: static physical
IPv4/IPv6 routing, single-interface service hosts, no dynamic IPv6, SVIs,
subinterfaces, RA Guard/firewall combinations, shells/accounting, Telnet,
RadSec or RADIUS-over-IPv6. This is one supported combined profile, not all
LAN services enabled together or a full vendor AAA implementation.

The native job checks A/AAAA over both families and DNS transports, NXDOMAIN,
real SSH/RADIUS and wrong-password/action denials, packet evidence, DNS outage
with successful SSH/AAA, RADIUS outage with successful DNS and denied execution,
withdrawal of only the DNS routes with successful AAA, drift refusal across
all service files/routes, cold restore, fresh supervisor tokens and host
cleanup. The test addresses SSH by literal IP deliberately so DNS availability
is measured independently. Details and CI results are in LAN_NEXT_STEPS.md.
