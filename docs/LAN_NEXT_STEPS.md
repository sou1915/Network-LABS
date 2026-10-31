# LAN work order

Agreed order: complete the bounded AAA, IPv6 and switching profiles, polish
the other LAN services, then integrate the native engine into the GUI.
WAN work remains later. Each feature needs packet/service evidence and
failure/recovery coverage appropriate to its scope.

1. AAA: RADIUS-gated execution and declared per-node action policy, then
   Interactive SSH/Telnet login integration, richer role enforcement, durable accounting/retry and 802.1X/EAP. TACACS+
   and protected transports require their own implementations and validation.
2. IPv6: the bounded SVI/subinterface, OSPFv3, relay/PD, forwarding-firewall
   and RA Guard increments below have dedicated evidence. Remaining work is
   broader IPv4/IPv6 and service/security coexistence, subinterface service
   combinations and separately scoped local-input firewall behavior.
3. Switching: physical/carrier failure coverage, remaining kernel validation,
   broader topology/security interactions and separately scoped MSTP/PVST.
4. Services: persistent HTTPS, Syslog TLS/durable retry, broader DNS and file services;
   improve diagnostics, lifecycle, save/restore and documentation.
5. GUI: connect the native lifecycle, configuration and observations to the UI
   after the above profiles are ready.

## Current IPv6 sequence

Physical OSPFv3, static IPv6 SVIs and OSPFv3 over a tagged SVI transit now have
successful dedicated native CI evidence. Physical DHCPv6 relay/remote IA_NA allocation
with separate managed RA has dedicated native CI evidence. A single-/64 Kea
Prefix Delegation profile now adds finite downstream gateway installation and
SLAAC, with successful [dedicated native CI evidence](https://github.com/sou1915/Network-LABS/actions/runs/40873755093/job/123447186902)
at implementation commit `87a8d9283d5994158f2bc308dc4a5e4f14cbc205`.
That job verified real IA_PD SARR/Renew/Release packets without IA_NA,
downstream RA/SLAAC and routed delivery, finite gateway expiry after Kea
shutdown, recovery, drift refusal and saved restart. The general `tests` job
also passed on that commit; broader switching/native suites were still running
when this checkpoint was recorded. PD-only unicast renewal/release requires
the pinned BusyBox build in `tools/build_pd_busybox.py`; the stock 1.36.1
client has a null IA_NA source bug. Server shutdown uses Kea's fixed local
Unix control socket.

Static IPv6 router subinterfaces now have successful [dedicated native CI evidence](https://github.com/sou1915/Network-LABS/actions/runs/40885193904/job/123486899870)
at implementation commit `d0249ef9113c9e94a1171e7b2eff38b70b93892d`.
The scenario verified two ROAS VLANs plus a tagged static-route transit,
actual 802.1Q packets, one-/two-router hop limits, forwarding/pruning/carrier
failure isolation and recovery, wrong-VID/address drift refusal, and saved
restart. External local parent admin DOWN/UP is separately tested as drift
requiring recreation from the saved manifest, since Linux may flush static
IPv6 state. The general `tests` job passed on the same commit; broader
switching/native suites were still running when this checkpoint was recorded.

Static physical IPv6 forwarding filtering now has successful
[dedicated native CI evidence](https://github.com/sou1915/Network-LABS/actions/runs/40892432671/job/123512527185)
at implementation checkpoint `a5db2d3d8a42d702c32da3fa4393529f7e6fd664`.
The separate `firewall_ipv6` profile verified ordered allow/default-deny rules,
actual ICMPv6 and TCP packets, IPv6 conntrack/counters, stateful returns versus
explicit stateless ICMP return, blocked TCP to a proven listener, rule/extra-table
drift refusal and cold restore. It filters forwarding only; local input/output,
RA Guard, NAT66 and dynamic/dual-stack/subinterface combinations remain outside
this increment. Policy edits require recreation.

The same checkpoint passed the general `tests`, PD, relay, IPv6 SVI,
subinterface, OSPFv3, SSH and RADIUS jobs. PD readiness now requires a preferred
SLAAC address and live RA default, asking the real router with RS while waiting;
it no longer treats a stale deprecated address as restored connectivity. The
SVI cleanup check now uses the existing hardware-hotplug-aware invariant while
still rejecting removed/replaced links and leaked virtual interfaces. Broader
switching/native suites were still running when this checkpoint was recorded.

Conservative access-port RA Guard now has successful
[dedicated native CI evidence](https://github.com/sou1915/Network-LABS/actions/runs/40900403159/job/123540804816)
at implementation commit `dedfdd9276042c40bb051fb4aa30415ced15843e`.
The job verified trusted RA/SLAAC/default-route acquisition and NDP/routed echo,
valid untrusted RA ingress with no corresponding client egress, and blocked
plain, extension-header, fragment, dot1Q and QinQ cases. A recreated trust
positive control learned the same plain rogue RA's prefix/default, establishing
that the protected result was not just an invalid wire fixture. Counters, whole
ruleset drift refusal, cold restore and host invariants were checked.

This is one Linux access switch with one access VLAN. On untrusted ports the
profile intentionally drops all IPv6 extension headers/fragments and protocols
other than immediate TCP/UDP/ICMPv6, including benign traffic of those forms.
It is not full RFC 7113 interoperability, router authentication or a trunk/LAG
profile. Changing trust requires recreation. See NATIVE_LAN_CORE.md for the
explicit limits. The general `tests`, firewall, SVI, SSH and RADIUS jobs also
passed; other jobs were still running at this checkpoint. All jobs for the
previous firewall checkpoint `a5db2d3` subsequently completed successfully.

The first explicit service/security coexistence profile, local IA_NA DHCPv6
plus managed RA across RA Guard, now has successful
[dedicated native CI evidence](https://github.com/sou1915/Network-LABS/actions/runs/40956758575/job/123738737230)
at implementation commit `94492d89b670614af0bea97e792ac467265415e7`.
Exactly one client and one local server are directly paired to untrusted and
trusted guard ports respectively. The test verified matched SARR/Renew/Release
identities, finite /128 allocation, RA M=1/A=0 and gateway separation, continued
routed traffic, rogue RA ingress without client egress, and a recreated trust
positive control that learns the rogue default even with autoconf disabled.
It also exercised local service outage/no-allocation/default expiry, recovery,
script/config/sysctl/guard drift refusal and cold save/restore without learned
address/default snapshots. This is RA admission alongside DHCPv6, not DHCPv6
snooping, server authentication, or validation of relay/PD/multiple-client
combinations. Existing conservative guard restrictions remain unchanged.

This commit retains the concurrent `7aada04` link-local DAD readiness fix for
real Router Solicitations. The general `tests` and all dedicated IPv6, SSH and
RADIUS jobs passed at this checkpoint; switching/native suites were still
running. Other service/security combinations remain separately scoped work.

Peer-induced STP/LACP carrier recovery now has successful
[dedicated native CI evidence](https://github.com/sou1915/Network-LABS/actions/runs/40960722168/job/123752453718)
at implementation commit `c5b7caabd35ecc3116731e15f77991fec2a7dc5d`, on
`7.0.0-1017-azure`. The first natural min-links-1 run exposed a real packet
blackhole after partial aggregate return despite settled control state and
old spare-path FDB learning. The optional `spanning_tree.carrier_recovery`
worker now waits for two equal settled control observations with one root
and a ready selected aggregate before repairing dynamic FDB on both bridges.
It preserves static/permanent entries and does not edit addresses/routes or
interface state. Partial repair remains incomplete and retries; stale/dead
worker state is separately reported and refused by save.

The `--stp-lacp` reference opts in exactly two Linux common-STP switches, one
two-member LACP channel each, initially UP, with a more expensive spare trunk.
Other profiles default off and opted-in component edits require recreation.
The test completed two cycles at min-links 1 and 2, actual tagged traffic on
selected paths with IPv4 TTL 64, static-marker preservation, stable declared
revision/configuration, worker repair evidence, cold restore and worker cleanup.
There is no test-helper FDB repair. This is a virtual peer-induced carrier
case with an explicit runtime worker, not natural recovery on every kernel or
a physical cable/one-way loss test. See STP_LACP_VALIDATION.md for the matrix.

General tests, the older managed STP/LACP job and all dedicated IPv6/AAA jobs
passed on the same commit; the full native suite subsequently completed
successfully. The newer one-way control-loss increment is described below.
Broader AAA, IPv6 coexistence and subinterface service gaps remain tracked;
GUI/WAN stay later. These bounded increments do not complete the entire LAN.

## One-way control-loss increment

The new dedicated scenario suppresses SW2-to-SW1 Slow Protocol multicast
on one, then both LACP members without changing their physical carrier or
admin state. The initial test exposed a real min-links-1 limitation: both
peers reported no negotiated members, but Linux retained bond carrier and
STP kept selecting the bundle. The existing worker only repairs FDB after
path changes and cannot force a spare when the kernel keeps that path.

`inspect` now exposes `carrier_without_ready_lacp`, alongside the existing
`ready:false` and actual member states. The revised test distinguishes
min-links-2 automatic spare-path failover from the min-links-1 fallback
boundary, and requires positive drop counters, intact physical carrier,
restored qdiscs, normal traffic after recovery and cold restore. This adds
no runtime link/STP override. See STP_LACP_VALIDATION.md for the exact scope.
The revised scenario has successful
[dedicated native CI evidence](https://github.com/sou1915/Network-LABS/actions/runs/41036997483/job/124000165427)
at implementation commit `b234b9a294298d1e4fec4f82054b4f726d866f2a` on
`7.0.0-1017-azure` with iproute2 6.1.0 (293 seconds). Both threshold-1 boundary
cycles and the threshold-2 failover/recovery, tagged traffic, static marker,
saved restart and cleanup completed. General tests, older switching, peer
carrier, all dedicated IPv6 jobs and SSH/RADIUS also passed; the full
`native-containers` suite subsequently completed successfully. The local
suite passed 762 tests with 116 environment-dependent skips.

A newer optional strict policy now maps optional `lacp_strict` directly
to native Linux bonding. Installed iproute2 help is checked before allocating
a lab, the kernel must return the requested option through netlink before
members are enslaved, and rejected/ignored options abort with cleanup.
Save rejects missing/changed actual policy; explicit-policy edits require
recreation. `--stp-lacp-strict` generates the reference manifest. Omission
retains the legacy behavior; no userspace link/STP override is substituted.

Dedicated CI now separates active-to-passive min-links-2 silent-loss coverage
from strict capability testing with a pinned newer iproute2. The strict job
must distinguish verified strict packet-path tests from clean unsupported
refusal; only a verified host runs both directions at min-links 1 and 2.
Positive strict native evidence now exists at implementation commit
`f090de33b2751128e668dd95a7b4a19d25fe3e04`:
[strict job](https://github.com/sou1915/Network-LABS/actions/runs/41173134745/job/124455117420),
630.853 seconds, `7.0.0-1017-azure` and pinned iproute2 7.1.0.
It reported STRICT_VERIFIED and completed both directions at thresholds 1/2,
with tagged packet recovery, static markers, policy persistence and worker
cleanup. CI now requires the positive path and cannot pass by silently
switching to unsupported refusal. The independent reverse legacy threshold-2
job also passed with stock iproute2 6.1.0. All other dedicated jobs and general
tests passed; the full native-containers suite was still running. Local tests
passed 768 cases with 118 environment-dependent skips. See STP_LACP_VALIDATION.md.

The explicit strict profile now covers threshold-1 silent-control loss on
this tested kernel/tool combination. Broader kernel/topology coverage remains;
the legacy omitted-option profile retains its documented threshold-1 fallback.
Next: LAN service polish and the remaining AAA/IPv6 coexistence gaps above,
before GUI integration. Generic vendor/physical-fault coverage remains separate.

## Current AAA increment

`radius-exec LAB SOURCE SERVER --username USER --password-file FILE
--secret-file FILE --action identity --json` requires a verified RADIUS
Access-Accept before invoking a fixed diagnostic in SOURCE's OCI container.
Available actions are `identity`, `hostname` and `security-context`.
Credential-file rules are the same as [radius-auth](NATIVE_RADIUS.md).
Reject, Challenge and unavailable authentication do not reach the executor.

The process runs as UID/GID 65532 with no supplementary groups, empty Linux
capability sets and `noNewPrivileges`, using a private temporary OCI process
file. Credentials are not placed in that file or the execution environment.
Execution has a five-second deadline; no arbitrary command or shell is exposed.

Each source node now requires an explicit `radius_access` policy. Missing
policy, a different server, an undeclared user or a disallowed action is
blocked before any authentication request or process creation:

```json
"radius_access": {
  "server": "192.0.2.20",
  "users": {
    "learner": ["identity", "hostname"],
    "auditor": ["security-context"]
  }
}
```

Only single-interface OCI hosts are supported, with 1..16 users, three fixed
diagnostic actions and an optional explicit `shell` permission. The RADIUS example declares its learner's permissions on PC1.
Existing manifests must add this field and recreate the lab to use
`radius-exec`; `radius-auth` remains an independent diagnostic without it.
The policy has no credentials and survives declarative save/restore. Updating
it requires editing the manifest and recreating the lab; no live policy editor
is implemented.

A locally allowed action still requires a verified Access-Accept. Returned
RADIUS authorization attributes are not applied. All accepted identities map
to the same non-root UID; the user/action allowlist is local authorization,
not a hierarchy of device roles. Existing admin exec, SSH and Telnet paths
are unchanged and are not protected by this policy. Fixed diagnostics do not send accounting packets; optional shell accounting
is described below. No persistent session registry exists yet. The lab lock remains held throughout
authorization, authentication and execution.

Unit tests cover denied/unverified decisions, unknown actions and process
privileges. The managed FreeRADIUS native test also checks real execution,
UID, effective capabilities, no-new-privileges and denied-password behavior;
that opt-in test requires successful CI before claiming native validation.

Process configuration follows the
[OCI specification](https://github.com/opencontainers/runtime-spec/blob/main/config.md)
and [crun process option](https://github.com/containers/crun/blob/main/crun.1.md).


An optional [RADIUS-authenticated local CLI shell](RADIUS_LOGIN.md) now uses
its own `shell` permission and the same unprivileged process configuration.
The reference example requires `--radius-shell` to grant this broader access.
This does not change SSH/Telnet authentication.


Optional [RADIUS session accounting](RADIUS_ACCOUNTING.md) adds a verified
Start receipt gate and Stop after confirmed session cleanup. The managed
server can write private ephemeral accounting records. SSH/Telnet AAA,
richer roles, durable accounting/retry and 802.1X remain later work.


Optional [restricted SSH actions](SSH_ACCESS_POLICY.md) now enforce a node-wide
fixed diagnostic allowlist in Dropbear's forced-command path. This prepares
server-side authorization. Optional [RADIUS-gated SSH diagnostics](SSH_RADIUS.md)
now add a fresh credential check per fixed action through a host supervisor.
An explicitly permitted [bounded SSH shell](SSH_RADIUS_SHELL.md) now reuses
the RADIUS session supervisor and optional accounting. Telnet AAA, richer roles,
SSH-handshake password authentication and durable accounting remain separate work.


## Plain TCP syslog collector increment

An optional `syslog_server.transport:"tcp"` now runs persistent node-local
rsyslog imptcp on the declared IPv4 address and TCP/514, with no UDP listener.
The rootfs builder's `--rsyslog-tcp` flag packages its matching input module.
`example --syslog-tcp` creates the collector/client profile. Omitted transport
preserves UDP. Collector edits continue to require recreation.

`syslog-send LAB SOURCE COLLECTOR --message TEXT --json` submits one bounded
ASCII message using octet-counted framing from the observed source address,
then independently checks exact fresh message/source storage at the collector.
TCP submission alone cannot pass; missing storage is unknown, while failed
transport is failed. This is a finite host-Python diagnostic, not a persistent
TCP sender, application acknowledgement, TLS or a durable delivery guarantee.

The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41175172265/job/124461114710)
passed at implementation commit `d07b96fcf4ce77b0a52f11edcf5f3de833430905`
(7.922 seconds): allowed storage versus transmitted/rejected source, actual
TCP packets, split/coalesced octet-counted and LF frames, log rotation,
configuration drift refusal, outage/restart, cold restore without old logs
and host cleanup. Local tests passed 772 cases with 119 environment-dependent
skips. See [SYSLOG_TCP.md](SYSLOG_TCP.md) for usage and limits.

A later optional persistent TCP forwarder is described below. The existing
BusyBox management sender remains the UDP default; TLS/trust and durable
retry remain separately scoped work.
HTTPS persistence, broader DNS/file services and AAA/IPv6 coexistence remain.
All jobs for the earlier strict-LACP implementation `f090de3`, including the
full native-containers suite, subsequently completed successfully.


## Persistent TCP syslog forwarding increment

Optional `management.syslog_transport:"tcp"` now selects an actual rsyslog
sender inside a single-interface OCI host. Guest logger writes to its local
Unix `/dev/log` input, local logs continue, and omfwd forwards automatically
to an explicitly admitting managed TCP collector using octet-counted frames.
`--rsyslog-forward` packages the matching input/network modules, while
`example --syslog-tcp --syslog-tcp-forward` opts the reference client in.
Omission keeps the BusyBox UDP sender. Co-located sender/collector and
router/multi-interface sender combinations are refused in this increment.

Fixed-array main/action queues hold 256 configured messages each, with one
worker and zero enqueue wait; full queues may discard. Remote retries
continue while the daemon runs, with one-second resume interval capped at
five seconds. No disk queue/save-on-shutdown is configured. Save retains
only declared policy, and generated-config drift is refused. Inspection
reports managed conformity and selected transport, not liveness or queue
contents. TCP has no application acknowledgement or durable delivery claim.

The [dedicated native forwarding job](https://github.com/sou1915/Network-LABS/actions/runs/41186199336/job/124493509259)
passed at implementation commit `61bf203c48075d00a5f35bf49535abd8cac7d7a1`
(9.227 seconds, rsyslog 8.2312.0): real guest logger, TCP packets, local
logging during a stopped collector, a freshly observed retry suspension,
post-suspension marker delivery after restart, config drift refusal, save
during a second outage, cold restore without queued/local/remote snapshots
and host invariants. Local tests passed 776 cases with 120 skips; the separate
TCP collector job also passed. See [SYSLOG_FORWARD.md](SYSLOG_FORWARD.md).

Next: Syslog TLS with explicit trust/identity policy, then the remaining
persistent HTTPS, broader DNS/file services and AAA/IPv6 coexistence gaps.
Durable retries/RELP and queue-overflow behavior need separate validation.
The full native suite for the earlier plain-TCP collector `d07b96f` has also
subsequently completed successfully.
