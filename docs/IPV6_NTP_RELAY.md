# Bounded managed IPv6 NTP relay

`example --ipv6-ntp-relay` extends the isolated IPv6 local reference into one
managed source plus one relay. PC4 (`2001:db8:40::40`) advertises local stratum
10 only to PC2. PC2 (`2001:db8:20::20`) follows that source and advertises
stratum 11 to PC1 (`2001:db8:10::10`). PC1 cannot query PC4 directly, and PC3
(`2001:db8:30::30`) is not granted access to PC2. R1/R2 supply static IPv6 routing;
ACL denials are independent of the otherwise working routed paths.

```bash
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --chronyd /usr/sbin/chronyd --chronyc /usr/bin/chronyc \
  --output /absolute/rootfs-ntp
python3 -m network_labs.appliances example --ipv6-ntp-relay \
  --rootfs /absolute/rootfs-ntp > ipv6-ntp-relay.json
sudo python3 -m network_labs.appliances start ipv6-ntp-relay.json
sudo python3 -m network_labs.appliances probe ipv6-ntp-relay-lan PC1 \
  2001:db8:20::20 --protocol sntp --family ipv6 --json
```

The relay declares an explicit IPv6 `upstream` instead of `local_stratum`.
Validation requires that upstream to be the bound address of another managed
IPv6 NTP server, whose clients explicitly include the relay's declared address.
Self/unknown/non-NTP/unallowed upstreams, cycles, more than two servers and
multiple independent roots in the two-server profile are refused. One
standalone local reference remains supported. The source's local stratum is
2..14, so its single relay remains within the valid server stratum range.
There is no arbitrary external or multi-hop NTP hierarchy implied here.

Both processes retain `-6 -x`, no CAP_SYS_TIME, fixed binding, a private Unix
control socket and no network command port. The relay's acquisition socket
also binds its declared IPv6 address. The probe reads NTP measurements only;
this does not set system/client clocks, authenticate time or establish accuracy
against an external reference. IPv4 defaults and their existing relay remain
unchanged. Dynamic/dual-stack/SVI/subinterface/security/other-service
composition limits remain unchanged.

A running chronyd relay may retain its last estimate after losing its source.
This profile promises no immediate revocation or finite holdover timeout.
A freshly restarted relay with its only source unavailable has no local fallback
and must not provide a synchronized measurement. Native validation tests that
fresh-start boundary, then restores the source and reacquires it. Startup saves
only declared topology/policy, not chronyd source estimates or live state.

The dedicated native scenario requires real upstream acquisition and selected
source observation, stratum-10 source and stratum-11 client replies, captured
upstream/downstream IPv6 UDP/123, independently reachable but denied clients,
exact process/socket observations, all live capability sets without
CAP_SYS_TIME, source-loss/fresh-relay negative control, recovery, drift refusal,
cold restore and host network invariants. Exact evidence is recorded in
LAN_NEXT_STEPS.md.

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-ntp-relay
```
