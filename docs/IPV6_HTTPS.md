# Managed HTTPS over static IPv6

`example --ipv6-https` places one persistent NGINX HTTPS server at
`2001:db8:20::20`, beyond two physical OCI routers. PC1 uses
`2001:db8:10::10`. All ports use static IPv6 /64 addresses and explicit
routes; no non-loopback IPv4 addresses or IPv4 fallback are configured.

Build distinct client and server rootfs images as in
[HTTPS_SERVER.md](HTTPS_SERVER.md), supplying the server's public CA,
leaf/chain and matching mode-0600 unencrypted key. For the literal-address
probe, the leaf needs IP SAN `2001:db8:20::20`; a DNS SAN alone cannot verify
that address. No CA signing key is copied into the image.

```bash
python3 -m network_labs.appliances example --ipv6-https \
  --rootfs /path/to/server-rootfs \
  --https-client-rootfs /path/to/client-rootfs > ipv6-https.json
sudo python3 -m network_labs.appliances start ipv6-https.json
sudo python3 -m network_labs.appliances probe ipv6-https-lan PC1 \
  2001:db8:20::20 --family ipv6 --protocol https \
  --ca-file /path/to/ca.pem --json
```

The server policy adds explicit `"family":"ipv6"` to the existing
`interface`, `ca_sha256` and `certificate_sha256` fields. Omission keeps the
IPv4 behavior. Rendering uses `listen [2001:db8:20::20]:443 ssl ipv6only=on`;
there is no wildcard, IPv4 or plaintext HTTP listener. Existing TLS 1.2/1.3,
fixed GET/HEAD `/` response, 404/405 behavior, worker privilege drop, offline
identity checks, exact public pins and runtime private-key conformity apply.
Inspection reports conformity, not process liveness or delivered traffic.

The supported composition has exactly one HTTPS server and static IPv6-only
physical hosts/routers. Dual-stack, DNS/other managed services, dynamic
addressing/routing, SVI/subinterfaces, firewall/security compositions and
multiple HTTPS servers are refused. Mutual TLS, automatic renewal/revocation,
live reload, application content and automatic service supervision remain
outside this profile. Save/cold restore stores declarations and requires the
original conforming offline identity assets; it does not snapshot TLS sessions.

## Validation

The dedicated `ipv6-https-interop` job exercises real IPv6 TLS across both
routers, explicit CA/IP verification, wrong CA/DNS-name rejection, GET body,
404/405, encrypted packet capture, independent routing and daemon outages,
local live-server controls, explicit restart, drift refusal and cold restore.
It checks host namespaces, links, IPv4/IPv6 routes/rules and forwarding state.
The `ipv6-https` workflow selector also runs existing IPv4 HTTPS server,
identity-lifecycle and general CI regression jobs.

At implementation commit `81ba8ba63e1b844142e670f75a27a55645ba4895`,
the [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42073646773/job/127407962710)
passed its scenario in 13.213 seconds. Existing IPv4 HTTPS server and
identity-lifecycle scenarios passed in 7.943 and 5.090 seconds, respectively.
General CI also passed. All four selected jobs succeeded; the other 49
workflow jobs were intentionally skipped and are not new native proof. Local tests passed 962 cases in
30.469 seconds with 152 environment-dependent skips; skips are not native
proof. Compilation and diff checks passed. The initial sandboxed local run
could not open existing loopback test sockets; rerunning with socket access
passed without changing assertions. No failed native run preceded this result.

Run with:
`gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-https`.
