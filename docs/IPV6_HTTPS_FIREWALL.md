# Managed IPv6 HTTPS behind a forwarding firewall

`example --ipv6-https-firewall` creates PC1, FW1 and PC2. PC2 runs the
[managed IPv6 HTTPS server](IPV6_HTTPS.md) at `2001:db8:20::20`; PC1 is
`2001:db8:10::10`. FW1 routes between those two static IPv6 /64 networks.

The example uses default-drop forwarding with invalid-state rejection and
stateful established/related acceptance. Its explicit outbound rules allow
only PC1-to-PC2 TCP/443 and ICMPv6 echo requests on the declared interfaces.
There is no TCP/80 or TCP/8080 allow rule. This is an address/interface/port
policy, not TLS inspection: the client must separately verify CA and identity.
Allowed ICMPv6 echo is an independent path control; this profile does not
claim a complete production PMTU/error-traffic policy.

Build separate server/client images as in [HTTPS_SERVER.md](HTTPS_SERVER.md).
The server leaf needs IP SAN `2001:db8:20::20` for the literal-address probe,
and its matching unencrypted private key must have mode 0600.

```bash
python3 -m network_labs.appliances example --ipv6-https-firewall \
  --rootfs /path/to/server-rootfs \
  --https-client-rootfs /path/to/client-rootfs > ipv6-https-firewall.json
sudo python3 -m network_labs.appliances start ipv6-https-firewall.json
sudo python3 -m network_labs.appliances probe ipv6-https-firewall-lan PC1 \
  2001:db8:20::20 --family ipv6 --protocol https \
  --ca-file /path/to/ca.pem --json
```

The server remains a distinct single-interface OCI host with explicit
`https_server.family: ipv6`. The optional firewall is separately managed;
HTTPS is not co-located on FW1. Only static IPv6 physical addressing/routing
is supported. Local-input policy with HTTPS, dynamic protocols/addressing,
dual-stack, DNS/other service co-location, VLAN/SVI/subinterfaces and multiple
HTTPS servers remain refused. This permits forwarding-rule declarations
within the existing IPv6 firewall schema; it does not add live policy edits.

TLS identity/conformity, explicit restart and declarative cold restore retain
their existing scope. Firewall inspection/counters and HTTPS config inspection
do not independently prove an authorized TLS response. Save refuses observed
forwarding/ruleset drift and stores declarations, not conntrack/TLS sessions.

## Validation

`ipv6-https-firewall-interop` checks real trusted TLS/GET, wrong CA rejection,
both-interface IPv6 TLS capture, independently live but blocked TCP/8080,
positive accept/state/default-drop counters and IPv6 conntrack entries.
It separates routing and service outages with direct TLS/allowed echo
controls, checks drift refusal, and recreates exact saved policy/identity.
A stateless variant preserves outbound HTTPS permission and explicit echo
return but omits TCP return permission; remote HTTPS must fail while direct
TLS and echo work. Restoring the stateful saved profile must recover service.
Host namespace/link/route/rule/forwarding/nftables invariants are checked.

Native validation is pending for this implementation checkpoint. The selector
also runs baseline IPv6 HTTPS, standalone IPv6 firewall, DNS/firewall and
general CI regressions:
`gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-https-firewall`.
