# Managed IPv6 isolated NTP reference

`example --ipv6-ntp` provides a managed chronyd local reference on PC2
(`2001:db8:20::20`), an explicitly allowed PC1 (`2001:db8:10::10`) over a static
two-router path, and a separate denied PC3 (`2001:db8:30::30`). The server opts
in with `ntp_server.family: "ipv6"`; omission preserves the IPv4 profile,
including its existing upstream/relay behavior.

```bash
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --chronyd /usr/sbin/chronyd --chronyc /usr/bin/chronyc \
  --output /absolute/rootfs-ntp
python3 -m network_labs.appliances example --ipv6-ntp \
  --rootfs /absolute/rootfs-ntp > ipv6-ntp.json
sudo python3 -m network_labs.appliances start ipv6-ntp.json
sudo python3 -m network_labs.appliances probe ipv6-ntp-lan PC1 \
  2001:db8:20::20 --protocol sntp --family ipv6 --json
```

IPv6 requires a separate single-interface IPv6-only host, one declared
`local_stratum` from 2 through 14, and 1..16 explicit unicast managed peer
addresses. Each client becomes a /128 chronyd allow rule. The local reference
has stratum 10 in the example. The standalone example uses no upstream. A separate bounded managed IPv6
relay profile is described in [IPV6_NTP_RELAY.md](IPV6_NTP_RELAY.md). No
Internet reference, DNS, NTS or authenticated time is implied.
This local reference supplies protocol observations, not a claim of accurate
or externally synchronized time. The SNTP probe reads a measurement and does
not set client or host clocks.

chronyd runs with explicit `-6 -x`, binds the declared IPv6 address, disables
network command port 323, and retains the private Unix control socket. The OCI
capability sets exclude CAP_SYS_TIME. Startup waits for IPv6 DAD. PID/argv,
file conformity and exact selected-family UDP/123 bindings remain separate
sequential observations; none alone proves successful time delivery or attributes
a socket to a process. IPv6 observations read /proc/net/udp6 using Linux's native
32-bit word order, while the unchanged IPv4 path reads /proc/net/udp. Fixed
chronyc tracking/sources commands remain read-only.

The profile permits static IPv6-only physical hosts/routers and static routes.
It excludes mixed dual-stack, switches, SVIs/subinterfaces, dynamic IPv6,
DNS/TFTP/AAA/management and firewall/security combinations. Normal IPv6 routing
and other allowed traffic are independent from chronyd's client ACL. A failed
SNTP probe alone does not identify an ACL or routing failure.

The native test requires real chronyd stratum-10 responses and origin-matching
SNTP validation, allowed and denied request packets, a positive independent
route check for the denied client, exact IPv6 UDP binding and PID/argv evidence,
read-only tracking, and all five live daemon capability sets without
CAP_SYS_TIME. Its fixture explicitly adds an allowed R2 source as an independent
wire control while the R1 path is disabled. It also requires service outage /
recovery, configuration and forwarding drift refusal, saved-family retention,
cold restore and host network invariants. No fixture changes a clock.

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-ntp
```

This selects the new IPv6 job, the existing IPv4 reference/relay/client native
scenario, IPv6 service-probe and TFTP native regressions, and general CI. Exact
results and remaining LAN scope are recorded in LAN_NEXT_STEPS.md.
