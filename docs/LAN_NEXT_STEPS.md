# LAN work order

Current user direction: finish the essentials quickly, defer optional detail
and advanced extensions, then start native GUI integration. The frozen
[LAN core acceptance gate](LAN_CORE_ACCEPTANCE.md) is now the authoritative
first-release boundary. Do not extend that gate with new protocols or more
micro-increments. Its seven existing functional checks are now passed on the same revision;
fix only observed regressions in this scope. The historical roadmap below remains extension tracking,
not an instruction to finish the whole catalogue before GUI.

Static VXLAN mapping remains after LAN/GUI; EVPN/BGP and WAN are separate
later stages. See [PROJECT_STATUS.md](PROJECT_STATUS.md) and
[LAN_PROTOCOL_COVERAGE.md](LAN_PROTOCOL_COVERAGE.md) for bounded capabilities.

## Core closure and next phase — 2026-11-06

The [consolidated gate](https://github.com/sou1915/Network-LABS/actions/runs/42262198799/job/128047268789)
passed **7/7 essentials** at `16bce142fe312dc654ee404d726971cf825f2935`.
All ten selected jobs passed; 52 were intentionally skipped. The six existing
core packet scenarios passed in 166.885 seconds, alongside switching,
SSH/RADIUS, wired admission/managed peer, 20-node headless reference and
general regression. See [LAN_CORE_ACCEPTANCE.md](LAN_CORE_ACCEPTANCE.md)
for per-job evidence and exact limits. No runtime/test assertions were relaxed.

Proceed to native GUI integration. Do not resume advanced LAN implementation
or small validation refinements as prerequisites. Keep the remaining catalogue
tracked for later and repair only demonstrated core regressions.

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
BusyBox management sender remains the UDP default. The mutual TLS/trust
increment is described further below; durable retry remains separate work.
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

A later bounded mutual TLS profile is now described below. Remaining work
includes persistent HTTPS, broader DNS/file services and AAA/IPv6 coexistence.
Durable retries/RELP and queue-overflow behavior need separate validation.
The full native suite for the earlier plain-TCP collector `d07b96f` has also
subsequently completed successfully.


## Mutual TLS syslog increment

An explicit TLS profile now runs rsyslog gtls on TCP/6514 with mandatory
mode 1 and x509/name checks in both directions. The managed sender and
collector each present their own offline leaf identity and verify the
configured peer name against the explicit CA. SAN prioritization, extended
key purpose and TLS 1.2/1.3 priority are configured. The collector's managed
source-IP allowlist still applies; no 514 listener or plaintext downgrade
is created. Scope is one single-interface sender/collector identity pair.

`--rsyslog-tls` packages matching GnuTLS modules and three supplied offline
identity files. Example generation requires separate client/server rootfs
references and explicit peer names. The manifest stores public CA/local
certificate file pins, not private keys. Startup verifies the public pins,
key mode and matching key/certificate. Runtime audit checks public assets,
key permissions and a runtime-only private digest; drift blocks save.
Non-TLS OCI nodes mask identity assets if they share an identity-bearing base.
Cold restore reuses conforming supplied offline identities, without runtime
TLS sessions, queues or logs. Policy/certificate changes require recreation.

The [dedicated mutual TLS job](https://github.com/sou1915/Network-LABS/actions/runs/41204838147/job/124547706724)
passed at implementation commit `c27e6f0603154433a7c170246c71ebcbdd0fdf9d`
(13.851 seconds, Ubuntu 24.04): guest logger storage plus an independently
verified TLS client, wrong trust/name negative cases with working positive
controls, same-CA unauthorized-client rejection, plaintext rejection,
encrypted-marker packet checks, identity masking, CA/key-mode drift refusal,
post-suspension recovery, declarative cold restore and host invariants.
Local tests passed 781 cases with 121 environment-dependent skips. General CI
and existing plain TCP collector/forwarder jobs also passed; broader suites
were still running. See [SYSLOG_TLS.md](SYSLOG_TLS.md) for exact usage/limits.

Next services: persistent HTTPS, then broader DNS/file services and remaining
AAA/IPv6 coexistence work. Automatic certificate renewal/revocation, durable
retry/RELP and multi-identity TLS remain separately scoped work. All jobs for
the prior plain TCP forwarding checkpoint `61bf203`, including its full
native suite, subsequently completed successfully.


## Persistent HTTPS increment

A managed `https_server` now runs NGINX inside a standalone single-interface
OCI IPv4 host until lab stop. One master and one UID/GID-65531 worker handle
only the declared address on TLS/443; the fixed GET/HEAD `/` endpoint is 200,
unknown paths are 404 and other methods are 405. TLS 1.2/1.3, explicit offline
identity and existing client CA/name verification are used. No HTTP/80,
application login, reverse proxy, user uploads or vendor GUI is introduced.
The temporary `https-demo` remains separate.

`--nginx` packages a trusted HTTP-SSL-capable binary and its ELF dependencies
with three supplied HTTPS identity files. The builder creates the key with
mode 0600, startup applies root ownership inside the node overlay, and other
nodes sharing that image mask the identity directory. Public PEM file pins
enter the manifest; key bytes do not. Managed config/public pins and private
key digest/root permissions are audited before save, separately from daemon
liveness or TLS delivery. Edits require recreation; cold restore starts fresh
processes from conforming offline identity assets. Node resource budgets
remain in force; the reference reserves at least 32 MiB for its server.

The [dedicated native HTTPS job](https://github.com/sou1915/Network-LABS/actions/runs/41307135602/job/124849728937)
passed at implementation commit `8db923fedc81937844c2ed177e1cdbe648ff8998`
(7.637 seconds, Ubuntu 24.04): repeated verified HEAD, actual GET/body and
TLS version, encrypted response capture, 404/405, wrong CA and wrong-IP
certificate negative cases with a working identity positive control, non-root
worker and identity masking, configuration/CA/key-mode drift refusal,
service stop/restart, declarative cold restore and host cleanup. Local tests
passed 785 cases with 122 skips; general CI and all three dedicated Syslog
jobs also passed. Broader suites were still running. See [HTTPS_SERVER.md](HTTPS_SERVER.md).

Next: broader DNS/file services and remaining AAA/IPv6 service coexistence,
before GUI. Automatic certificate renewal/revocation, mutual HTTPS client
authentication, HTTP application policies and broader server combinations
remain separately scoped work. The earlier Syslog TLS checkpoint `c27e6f0`
also subsequently completed its full native-containers suite successfully.


## DNS transport increment

Probes now offer explicit `udp` (default), `tcp` and `auto` DNS transport.
Auto retries the same query over TCP only for a matched UDP TC response, using
one shared stage deadline and the same guest resolver. Timeout/malformed replies
never trigger fallback. Framed TCP reads accept segmentation and reject short,
oversized, mismatched or still-truncated responses without returning partial A
records. The budget remains 4096 bytes and direct IPv4 A only; no CNAME traversal,
EDNS/DNSSEC validation or alternate resolver. The real dnsmasq server is unchanged.
A dedicated native job separates real dnsmasq UDP/TCP and NXDOMAIN observations
from an explicitly owned responder that forces TC and framing failures. Validation
passed at `baaad333a2f203f59bb3449f7fd17f4c8157ac8c` in the
[dedicated DNS job](https://github.com/sou1915/Network-LABS/actions/runs/41319155688/job/124885472668)
(11.946 seconds, Ubuntu 24.04), including NXDOMAIN, layered HTTP name resolution,
packet evidence, configuration drift refusal, declarative cold restore and host
cleanup. Local tests passed 793 cases with 123 environment-dependent skips;
dedicated HTTPS and all three Syslog jobs also passed. General CI and broader
native suites were still running at this checkpoint. Next: broader file-service checks
and remaining AAA/IPv6 coexistence, before GUI.

## Tracked overlay milestone: VXLAN (planned)

VXLAN remains required after the LAN foundation and GUI milestones; it is not
implemented by the DNS/HTTPS work. Start with explicit static VTEP peers over an
IPv4 underlay, VNI and VLAN/VNI binding, then verify end-host L2 traffic, BUM
handling, tenant isolation, MTU/encapsulation, underlay loss/recovery and resource
budgets. Require native packet captures plus save/restart and host-cleanup checks.
EVPN/BGP control-plane support is a separate later milestone; static VXLAN must
not be described as EVPN. WAN work remains separately tracked.


## TFTP blocksize increment

Read-only TFTP gains explicit `--block-size 512..1428` negotiation; omission
keeps the existing option-free 512-byte mode. Valid OACK selects the bounded
size and transfer peer, with ACK-0 retry and identical OACK recovery. Ignored
options fall back to DATA-1/classic 512. Unknown, duplicate, oversized, changed,
late or unsolicited options fail without a completed digest; changed duplicate
DATA is also rejected. File size, datagram count and absolute deadline budgets
remain unchanged. This is not PMTU discovery or authenticated file transfer.
Native validation uses the existing real dnsmasq server, including binary
content/hash and empty/exact/max-size files, wire capture, drift refusal and
cold restore. The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41319989712/job/124887925287)
passed in 14.434 seconds on Ubuntu 24.04 at implementation commit
`125a1c7cbad1e9966e69a7ec5dfb157d35ea4137`. Local tests passed 800 cases
with 124 environment-dependent skips. Broader CI was still running at this
checkpoint. Remaining LAN work
includes AAA/IPv6 service coexistence before GUI; planned VXLAN remains tracked
above, with EVPN/BGP separately scoped.


## Static dual-stack DNS coexistence increment

An explicit `example --dual-stack-dns` now composes local DNS with static
physical IPv4/IPv6 routing across two routers. Optional `records_ipv6` supplies
AAAA data and `listen_ipv6:true` binds UDP/TCP DNS to the declared IPv6 address
alongside IPv4. DAD readiness precedes daemon startup. Existing IPv4-only DNS
configuration and probe defaults remain unchanged. The general probe still
supports IPv4 A only; native IPv6 DNS proof uses an independent socket client.
Dynamic IPv6, SVI/subinterface, RA Guard/firewall and other service/security
combinations remain excluded here. See [DUAL_STACK_DNS.md](DUAL_STACK_DNS.md).
The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41344735730/job/124962027968)
passed in 15.100 seconds on Ubuntu 24.04 at implementation commit
`a9a182f81d5ef5ff8891789357cb26b21330a991`. It verified A/AAAA over
IPv4/IPv6 UDP/TCP across two routers, exact listener addresses, NXDOMAIN,
packet captures, family-independent forwarding failures, DNS outage while both
families still carry ICMP, daemon recovery, config/resolver drift refusal,
declarative cold restore and host invariants. Local tests passed 807 cases with
125 environment-dependent skips. Existing DNS transport, TFTP blocksize and
HTTPS dedicated jobs also passed; general CI and broader native jobs were still
running at this checkpoint. All jobs for the earlier TFTP implementation
`125a1c7` subsequently completed successfully.
Next: further AAA/IPv6 service integration and combined failure/recovery checks
before GUI. VXLAN remains a planned later milestone.


## Routed dual-stack RADIUS-gated SSH increment

`example --radius --radius-ssh --radius-dual-stack` adds explicit IPv4/IPv6
SSH listeners on a static dual-stack host while keeping a separate managed
IPv4 RADIUS backend across two routers. SSH key authentication and the same
forced user/action policy apply on both transports; `management.ssh_ipv6:true`
is opt-in and startup waits for DAD. Backend unavailability must deny execution
even if IPv6 SSH still connects. This is fixed diagnostics only; RADIUS IPv6,
RadSec, shell/accounting, Telnet, DNS combination and dynamic/security service
compositions remain outside the increment. See [DUAL_STACK_RADIUS.md](DUAL_STACK_RADIUS.md).
The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41353429942/job/124988323041)
passed in 26.686 seconds on Ubuntu 24.04 at implementation commit
`1d88487fefc89c230cf56d6a378d83002d910581`. Both SSH families, per-user
positive/negative actions, wrong keys/passwords, UID/capabilities, arbitrary
command rejection, encrypted SSH captures, actual IPv4 RADIUS packets,
family-specific routing failures, backend outage/recovery, policy drift refusal,
cold restore, fresh supervisor tokens and host cleanup passed. General CI and
the dual-stack DNS job also passed. Local tests passed 813 cases with 126 skips.
Broader AAA and combined service work remains before GUI; planned VXLAN stays
separately tracked.

## DHCPv6 PD startup race repair

The earlier dual-stack DNS implementation's full CI exposed an independent
PD cold-restore failure: Kea logged a failed link-local bind and continued as a
process with no DHCPv6 sockets. A ready global IPv6 address did not imply ready
link-local DAD. PD server startup now waits up to eight seconds for a usable
server-port link-local address, rejects failed DAD, and requires both the owned
Kea process and an actual UDP/547 socket before returning ready. It does not
skip DAD or install an address to make the check pass.
The native PD scenario now deliberately recreates a tentative link-local
address before restarting Kea, then repeats actual delegation, SLAAC, expiry,
recovery and cold restore. The [dedicated native PD job](https://github.com/sou1915/Network-LABS/actions/runs/41353673264/job/124989049388)
passed in 52.310 seconds on Ubuntu 24.04 at repair commit
`f58c4c4e9d7239f5699c16b7f6d90826a9832663`, including the deliberately
tentative link-local restart and declarative cold restore. Local tests passed
816 cases with 126 environment-dependent skips. General CI and the routed
dual-stack AAA job also passed on that repair commit; broader native/switching
jobs were still running at this checkpoint. The earlier failed PD cold restore
at `a9a182f` is retained above as the observed cause, not a passing baseline.


## Combined static dual-stack DNS and AAA increment

`example --radius --radius-ssh --radius-dual-stack --radius-dns` now composes
five nodes: SSH NAS/DNS client, two routers, separate RADIUS server and separate
DNS server. DNS A/AAAA and UDP/TCP run over both families; protected diagnostics
use IPv4/IPv6 SSH and the existing literal IPv4 RADIUS backend. DNS server
co-location with AAA/management stays rejected. Static NAS resolvers are allowed.
Native validation independently removes DNS, RADIUS and the DNS-specific routes,
checks the surviving service and fail-closed AAA, and audits cold restore/cleanup.
The [dedicated combined native job](https://github.com/sou1915/Network-LABS/actions/runs/41356420727/job/124997326461)
passed in 24.409 seconds on Ubuntu 24.04 at implementation commit
`09efe039714c4e96ac680ab62f44749323ac204a`. See [DUAL_STACK_SERVICES.md](DUAL_STACK_SERVICES.md).
Local tests passed 821 cases with 127 environment-dependent skips. The prior
PD repair `f58c4c4` also subsequently completed all workflow jobs successfully.
A separate existing DNS scenario lost its first initial IPv6 echo while the
reverse direction succeeded. The static service tests now use a bounded
healthy-control readiness loop requiring complete bidirectional two-packet
verification; they do not seed neighbors or change production probe behavior.
At readiness-check commit `d7b426e254e38f02f3b733e5a919c6355e9a9413`,
the [combined scenario](https://github.com/sou1915/Network-LABS/actions/runs/41356644172/job/124998013391)
passed again in 39.409 seconds; the
[standalone DNS scenario](https://github.com/sou1915/Network-LABS/actions/runs/41356640261/job/124998001290)
passed in 26.385 seconds and the
[standalone AAA scenario](https://github.com/sou1915/Network-LABS/actions/runs/41356644172/job/124998013369)
passed in 36.382 seconds. General CI also passed at that commit. Other broader
native/switching jobs were still running at this checkpoint. The initial DNS
readiness failure is retained as observed evidence, not a passing baseline.
This supersedes the earlier DNS/AAA-combination exclusion only for the explicit
separate-node static profile. Shell/accounting, Telnet, dynamic/security service
compositions and broader LAN coverage remain before GUI; VXLAN stays planned.


## Explicit IPv6 service probe increment

`probe --family ipv6` adds direct AAAA resolution and source-bound IPv6 TCP,
HTTP(S) HEAD and SNTP observations. The default remains IPv4/A. Resolver
transport follows exactly one guest nameserver; it may differ from the target
family, and needs its own observed usable source. Optional static IPv6 resolvers
and `--dns-resolver-family ipv6` example selection are now available. No alternate
family, host resolver or implicit address choice is used. IPv6 HTTP Host syntax,
TLS name/IP verification, matched-TC retry and bounded AAAA parsing are checked.
Native validation uses real dnsmasq and explicit owned HTTP/TLS/SNTP fixtures;
it does not expand the persistent managed HTTPS/NTP server profiles.
See [PROBE_IPV6.md](PROBE_IPV6.md). The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41359596279/job/125006941953)
passed in 25.786 seconds on Ubuntu 24.04 at implementation commit
`468aa7c0af049edea28f6afa7e4ea06884df2206`. It checked both DNS record and
resolver transport families, HTTP status errors, explicit IPv6 TLS SAN and DNS
name verification, wrong CA/name rejection, SNTP and invalid originate replies,
NXDOMAIN/NODATA without A fallback, DNS/route/service outage, resolver drift,
cold restore and host cleanup. Local tests passed 829 cases with 128 skips.
General CI, existing DNS transport, dual-stack DNS, combined services and HTTPS
native jobs also passed. Broader native/switching suites were still running.
All jobs for the prior combined-readiness checkpoint `d7b426e` subsequently
completed successfully.
Combined/dynamic/security profiles and broader AAA remain separate work before
GUI; planned VXLAN remains tracked above.


## Bounded RADIUS accounting retransmission increment

An explicit `radius_access.accounting_retries:0..2` permits finite retransmission
inside each existing accounting deadline. The default still sends once. The
reference supports `--radius-accounting-retries` with enabled shell accounting.
Whole-second Acct-Delay-Time changes update Identifier/Request Authenticator;
identical packets retain them, and only verified replies matching actually sent
requests can confirm receipt. Start gating and Stop-after-cleanup remain in force.
This is volatile per-exchange retry, not durable delivery or exactly-once logging;
backend duplicate records remain possible. The IPv4 shell/accounting scope is
unchanged. See [RADIUS_ACCOUNTING.md](RADIUS_ACCOUNTING.md).
The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41360541418/job/125009768831)
passed in 19.115 seconds on Ubuntu 24.04 at implementation commit
`96f69bd28dd9784f2b37f05b912c767caa0e8594`. Real FreeRADIUS receipts,
deterministically lost accounting responses, three-send packet/authenticator
checks, dropped-response counters, one non-root shell launch after Start,
blocked launch with uncertain Start, uncertain Stop after confirmed cleanup,
explicit later receipt, saved retry policy and cold restore all passed.
Local tests passed 837 cases with 129 environment-dependent skips. General CI,
dual-stack AAA, combined services and IPv6 service-probe jobs also passed;
broader native/switching and RADIUS suites were still running at this checkpoint.
Durable accounting, broader AAA and dynamic/security combinations remain before
GUI as separately scoped work. VXLAN stays planned above.


## Private closed-session Stop outbox increment

An opt-in `radius_access.accounting_outbox:true` retains committed Stop intents
outside runtime state, only after confirmed session cleanup, and clears them
only on a verified receipt. It requires managed IPv4 accounting and pins the
NAS/backend/user/access policy without storing secret/password bytes. Private
bounded files, fsync, capacity checks and explicit pending/flush commands support
lab stop/recreation and fresh CLI processes; changed bindings refuse delivery.
There is no Start replay, background sender, live-session journal or exactly-once
backend guarantee. Earlier crash windows and full reconciliation remain separate.
See [RADIUS_OUTBOX.md](RADIUS_OUTBOX.md). The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41421057088/job/125196431274)
passed in 9.401 seconds on Ubuntu 24.04 at implementation commit
`b890800c75847a769c9217fb9cdb430ba34bd50c`. Real Stop receipt loss,
confirmed cleanup, private fsynced records, stopped-lab pending inspection,
actual recreation with a rotated secret and blocked replay, restoration of the
original policy, failed replay retention, Stop-only packet evidence with aged
Acct-Delay-Time and preserved duration/cause, no new shell, acknowledged deletion
and a healthy subsequent session all passed. Local tests passed 846 cases with
130 environment-dependent skips. General CI, existing RADIUS/accounting retry,
dual-stack AAA and IPv6 probe jobs also passed; broader native/switching suites
were still running at this checkpoint. Broader AAA and service/security
composition work remains before GUI; VXLAN stays planned above.


## Local pre-Start session journal increment

An explicit `accounting_journal:true` with the Stop outbox commits an intent
before accounting Start and an empty-cgroup checkpoint before removal. Local
CLI reconciliation pins the original supervisor/process, boot, namespace,
container and session cgroup identities. Live supervisors and occupied groups
without explicit `--terminate` are refused; missing/stale intent resources do
not imply cleanup. Verified orphan cleanup hands off only a compensating Stop
with zero unmeasured time and cause 9; no packet is sent until explicit flush.
Private bounded records survive runtime teardown, but no Start replay, exact
launch/receipt ledger, SSH crash profile or whole-host automatic recovery is
claimed. See [RADIUS_SESSION_JOURNAL.md](RADIUS_SESSION_JOURNAL.md).
The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41426122167/job/125213037988)
passed in 7.743 seconds on Ubuntu 24.04 at implementation commit
`b1ca18b60288c34f654b5962a0f6bb6b3da9cec5`. Actual supervisor SIGKILL,
nonblocking inventory, live-owner refusal, populated-orphan refusal without
explicit termination, verified cgroup cleanup, a silent reconciliation capture,
Stop-only explicit flush with zero duration/cause 9, stale runtime refusal after
lab recreation, and a healthy subsequent journaled login all passed. Local tests
passed 856 cases with 131 environment-dependent skips. General CI, existing
RADIUS/accounting retry/outbox, dual-stack AAA/services and IPv6 service-probe
jobs also passed; broader native/switching suites were still running at this
checkpoint.
Broader AAA/service/security combinations remain before GUI; VXLAN stays planned.


## SSH supervisor journal extension

The explicit accounting journal now also covers the existing bounded SSH shell
transport. The host worker receives the same configuration root as the CLI,
commits the pre-Start intent and empty cleanup checkpoint through the shared
session supervisor, and hands closed Stop events to the durable outbox. A dead
worker can be reconciled only with the original boot/runtime/cgroup identities;
no worker restart, new shell, Start replay or packet is part of reconciliation.
Short private accounting-store transactions serialize writes across workers and
CLI without holding a lock over shell execution or network I/O. Capacity and
unsafe-lock refusal have local concurrency tests. See
[RADIUS_SESSION_JOURNAL.md](RADIUS_SESSION_JOURNAL.md).
The [dedicated native SSH job](https://github.com/sou1915/Network-LABS/actions/runs/41428880147/job/125222128683)
passed in 9.999 seconds on Ubuntu 24.04 at implementation commit
`4c64817a5c16bdd4238aa5ca69574f9cda44ca80`. Real key-authenticated SSH and
RADIUS acceptance, host-worker-only SIGKILL with a populated guest session,
live-owner and no-termination refusal, verified orphan cleanup, silent local
reconciliation, one explicit compensating Stop packet, new worker token after
saved recreation, stale-runtime refusal, healthy subsequent SSH journal handoff
and host namespace/link/route/rule invariants all passed. Local tests passed
860 cases with 132 environment-dependent skips. General CI, existing managed
RADIUS/SSH/accounting and durable Stop-outbox jobs also passed. The local-CLI
journal native job was still queued and broader switching/native suites were
still running at this checkpoint. Broader AAA/service/security combinations
remain before GUI; static VXLAN and later EVPN/BGP stay separately planned.


## Local AAA role authorization increment

An opt-in `radius_access.roles` plus `user_roles` form adds reusable local grants
for existing CLI diagnostics, bounded shells and RADIUS-gated SSH. Effective
permissions are an explicit union; mixed direct/role policy, unknown role names,
empty/duplicate/unbounded declarations are refused. Local denials precede RADIUS
and process creation; verified Access-Accept, SSH node-wide action ceilings,
non-root execution and accounting cleanup rules remain mandatory. The full role
policy stays in durable Stop/journal bindings. `example --radius-roles` offers
the standalone reference; old direct lists remain the default. See
[RADIUS_ROLES.md](RADIUS_ROLES.md).
The [dedicated native role job](https://github.com/sou1915/Network-LABS/actions/runs/41430332566/job/125226998884)
passed in 16.302 seconds on Ubuntu 24.04 at implementation commit
`fe858f558b347a09bb4b07dd11ba09095ec67561`. Real CLI/SSH role unions,
reader/auditor/session separation, the independent SSH action ceiling, a
verified backend-only account refused locally, zero auth/accounting packets for
local-policy denials with a capture positive control, wrong-password rejection,
non-root shells with accounting/journal handoff, backend outage/recovery, saved
role retention, reduced grants after recreation and host isolation all passed.
Local tests passed 869 cases with 133 environment-dependent skips; general CI
also passed on the same implementation. Broader native/switching jobs were
still running at this checkpoint. These are local action roles, not central RADIUS reply
attribute authorization, Linux privilege elevation, per-command shell filtering
or vendor privilege levels. Broader AAA, Telnet and service/security work remain
before GUI; static VXLAN and later EVPN/BGP remain separately planned.


## OSPFv3 host-link observation repair

The preceding SSH-journal run's physical OSPFv3 scenario completed its functional
checks but failed its final exact host-link snapshot because a new interface
`enP59737s1` appeared. This is consistent with hosted-runner hardware hotplug;
the old job did not record that interface's sysfs device proof. At repair commit
`a5dff16d47d69afd72b45ef89b1682f1a77bcc37`, the OSPFv3 test now uses the existing
host invariant helper: only newly added interfaces with an actual sysfs
`device` entry may be ignored. Removed/replaced baseline links and every new
virtual interface still fail. Host routes/rules/forwarding checks are unchanged.
The helper's existing hardware/virtual-leak/baseline-change tests passed locally.
The [dedicated repaired OSPFv3 job](https://github.com/sou1915/Network-LABS/actions/runs/41430509194/job/125227600217)
passed both physical and tagged-SVI scenarios in 100.567 seconds on Ubuntu 24.04
at that repair commit. General CI and the role native scenario also passed.
The earlier failure is retained as observed evidence rather than called a
successful OSPFv3 job.


## Standalone RADIUS Telnet diagnostic increment

`example --radius --radius-telnet` adds actual BusyBox Telnet with a compiled
fixed login helper, optional local role grants and an independent Telnet action
ceiling. The helper drops UID/GID/groups and every capability set before
credential input, then requests one RADIUS-gated fixed diagnostic from its own
host bridge. It never invokes a local login/password fallback or shell. The
bridge has independent transport/generation identity and protected NAS-loopback
TCP/814; stop/recreate owns its worker lifecycle. Old local-password Telnet and
SSH profiles remain unchanged. See [TELNET_RADIUS.md](TELNET_RADIUS.md).
The [dedicated native Telnet job](https://github.com/sou1915/Network-LABS/actions/runs/41433708397/job/125238294335)
passed in 13.451 seconds on Ubuntu 24.04 at implementation commit
`39e1856d3f7bfe950ef7b1aa659610b610e9313e`. Actual BusyBox Telnet and
FreeRADIUS, pre-auth helper UID/GID 65532 with no supplementary groups and all
five capability sets empty, role/node ceilings, zero auth/accounting packets
for local denials with a successful capture control, backend outage without
fallback, stopped-worker refusal and protected low-port binding, drift refusal,
fresh saved worker generation and host namespace/link/route/rule isolation all
passed. Local tests passed 877 cases with 134 environment-dependent skips.
General CI passed, and the [existing role/SSH/accounting native job](https://github.com/sou1915/Network-LABS/actions/runs/41433716525/job/125238319347)
also passed on the same implementation. Other native/SSH/switching jobs were
still queued or running at this checkpoint. Telnet shell/accounting, broader AAA and service/security
composition remain before GUI; static VXLAN and later EVPN/BGP remain planned.


## Explicit bounded Telnet shell/accounting increment

A separate `--radius-telnet-shell` opts into a PTY shell through the shared
CLI/SSH session supervisor. User role/direct grants and the Telnet action
ceiling must both admit shell. Optional accounting gates launch on verified
Start and sends Stop only after confirmed subtree cleanup; the existing outbox
and journal retain their durable handoff rules. Diagnostic-only Telnet remains
the default, and older helpers are refused for shell use by a separate capability
check. Credential input remains bounded independently of the shell duration.
See [TELNET_RADIUS.md](TELNET_RADIUS.md). The
[dedicated native Telnet shell job](https://github.com/sou1915/Network-LABS/actions/runs/41436399344/job/125247095236)
passed in 12.180 seconds on Ubuntu 24.04 at implementation commit
`dd05de8253e18dfd472c709f560026bc8aae1806`. Actual PTY and non-root/no-capability
execution, denied users/passwords without shell effects, background subtree
cleanup after exit/expiry/disconnect, matched Start/Stop records and causes,
real accounting-response loss with no shell launch despite successful Access,
retained Stop followed by explicit flush, journal handoff, saved recreation and
host namespace/link/route/rule invariants all passed. Local tests passed 881
cases with 135 environment-dependent skips. General CI, diagnostic-only Telnet
and the existing role/SSH/accounting native scenario also passed on that
implementation; broader native/switching jobs were still queued or running.
Telnet worker crash coverage and broader AAA/service/security work remain before
GUI; static VXLAN and later EVPN/BGP stay separately tracked.


## Telnet supervisor crash-recovery validation

The existing pre-Start journal and identity-pinned reconciliation now have a
dedicated real Telnet SIGKILL scenario. A live Telnet PTY runs a HUP-ignoring
sleep so lost terminal connectivity cannot be mistaken for empty population.
The scenario checks live-owner refusal, occupied-orphan refusal without the
flag, explicit original-cgroup cleanup, no accounting traffic during local Stop
handoff, a separate Stop-only flush, refusal after unclosed runtime recreation,
and healthy new sessions while stale evidence remains. No recovery algorithm
or default session policy is changed by this validation increment. See
[TELNET_RADIUS.md](TELNET_RADIUS.md#explicit-recovery-after-telnet-worker-death).
The [dedicated native Telnet journal job](https://github.com/sou1915/Network-LABS/actions/runs/41440923131/job/125262282997)
passed in 9.361 seconds on Ubuntu 24.04 at validation commit
`93ae48ddc993d7f0e834f22f68ddc146175436ba`. Real PTY shell launch, killed original
worker with an occupied HUP-resistant payload, live-owner and no-termination
refusal, original-cgroup identity checks and confirmed cleanup, silent local
handoff, exactly one compensating Stop request on explicit flush (same SID,
zero unmeasured seconds, cause 9), fresh worker token, stale unclosed runtime
refusal, healthy new shell with old evidence preserved, and host namespace,
link, route, rule and low-port sysctl invariants all passed. Local tests passed
882 cases with 136 environment-dependent skips. General CI and the existing
Telnet shell/accounting lifecycle native job also passed; broader native and
switching jobs were still queued or running at this checkpoint. Broader AAA and
service/security compositions remain before GUI; static VXLAN and later
EVPN/BGP stay separately tracked.


## EAP-MD5/RADIUS protocol foundation

An explicit `radius-eap-md5` diagnostic adds bounded Identity/MD5 challenge/State
continuation, both RADIUS authenticators and matching final EAP outcomes. It
sends at most two requests inside one deadline, with no method/server fallback.
The optional managed backend uses matching EAP/MD5 assets and a private owned
password file pinned by the existing SHA-256 digest; password bytes do not enter
manifest/startup/rootfs images. Existing PAP behavior stays the default. See
[RADIUS_EAP_MD5.md](RADIUS_EAP_MD5.md). Local tests passed 890 cases with 137
environment-dependent skips; independent signed peers cover proof, State,
malformed methods/lengths, replay, early accepts and private assets. The initial
native run at `754101d2d4bcfc83fb14549147f992ea59ffcf37` reached a verified
challenge but rejected the correct proof: its Cleartext-Password string had
been assigned using the octet-style unquoted `0x` representation. Repair commit
`34ddbaf9a06d6dc1f1d3dedd2d0b3f774dcef321` uses an escaped, nonexpanding single-
quoted string and explicitly bounds the managed password asset to printable
ASCII. Its [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41444614658/job/125274523414)
passed in 6.658 seconds on Ubuntu 24.04. Real Identity/MD5/Success packets,
opaque State echo, exact MD5 proof and terminal identifiers, quotes/backslash/
expansion-like password bytes, verified wrong-password/user rejection, wrong
shared-secret timeout, PAP compatibility, CLI privacy, unchanged declared
configuration, password-asset drift/save refusal, backend outage/recovery,
failed pre-allocation recreation with a changed asset, healthy cold restore and
host namespace/link/route/rule isolation all passed. General CI also passed at
the repair commit; broader RADIUS/native/switching suites were still running.
The initial rejected run is retained as evidence rather than reported as passing.
This does not grant access or implement EAPOL/802.1X controlled ports. That wired
port milestone, stronger EAP methods and broader AAA/service/security work remain
before GUI; static VXLAN and later EVPN/BGP stay separately tracked.


## Finite wired EAPOL / controlled-port increment

An explicit three-node `--dot1x` reference adds one pinned wired peer, one Linux
bridge NAS/SVI and the separate EAP-MD5 backend. A default-closed nftables gate
is applied before ports join the bridge or become UP. One finite `dot1x-auth`
worker passes actual EAPOL to verified RADIUS challenge/State/Success, then
installs a kernel timeout admission element. The command releases the lab lock
so traffic can be observed concurrently; teardown owns its process group.
Logoff/normal completion close the gate, and kernel expiry bounds even SIGKILL
admission to at most the configured 1..30 seconds. Saved configuration never
restores an admission. See [DOT1X_WIRED.md](DOT1X_WIRED.md).
The original handoff passed 896 local cases with 138 environment-dependent
skips; it had no native admission proof. The validation and repair evidence
below supersedes that pending checkpoint. This finite single-port MD5 profile does not implement persistent
reauthentication, TLS, dynamic VLANs, multi-client ports or broader compositions.
Broader AAA/service/security work remains before GUI; static VXLAN and later
EVPN/BGP remain separately planned.


## Wired admission native validation and teardown repair

The finite wired profile now has successful
[dedicated native CI evidence](https://github.com/sou1915/Network-LABS/actions/runs/41860209419/job/126679612230)
at validation commit `4fafe9a02d69bc07fa8595a55bd6152ede252d05`:
one real native scenario passed in **43.829 seconds** on Ubuntu 24.04.
Unmodified wired wpa_supplicant and FreeRADIUS completed Identity/MD5/Success
with captured opaque RADIUS State. The scenario verified the uncontrolled
uplink, blocked data in both directions before authentication and after closure,
bidirectional admitted delivery, wrong password/identity, Logoff, worker SIGKILL
with kernel lease expiry, backend outage, cold restore starting closed,
separate-CLI stop during active admission with confirmed worker death and no
runtime resurrection, gate-drift refusal and host namespace/link/route/rule
isolation.

The original handoff commit `d1e6bfcaa135186d04b13464342c6549c4410de1`
[failed its native job](https://github.com/sou1915/Network-LABS/actions/runs/41857169910/job/126668804525)
after admission/data delivery: startup save through a cached Manager overwrote
the worker record registered by another CLI, invalidating the generation.
Repair `d4d725fb2507b97f8050e9b94ba1b68d9f96a6f8` reloads current state for
save/stop/authentication and confirms death after final SIGKILL before allowing
namespace teardown. Its first native scenario passed in 32.116 seconds;
the later validation above adds separate-process teardown and bidirectional
closed-port checks. Authenticator finalization also rechecks directory existence
inside the lock so concurrent stop cannot cause stale state resurrection.
The original failed run remains failed evidence.

Local tests passed **901 cases in 26.609 seconds**, with 137 environment-dependent
skips; these skips are not native proof. Syntax compilation and diff checks
passed. Added local regressions cover cached save preserving worker ownership,
unowned group refusal, confirmed/unconfirmed SIGKILL death, namespace/interface
and runtime generation changes, replayed Identity and queued Logoff taking
precedence over a backend Success. The general `tests` job also passed on
`4fafe9a`; broader native/switching jobs were still running at this checkpoint.

This completes this finite single-port wired EAP-MD5 increment only. Admission
is a 1..30-second kernel lease; SIGKILL permits the remaining lease, not instant
revocation. Persistent reauthentication, managed supplicants, stronger EAP,
dynamic VLANs, multiple clients, accounting and broader service/security
compositions remain separate LAN work. Continue the AAA/IPv6/switching/service
sequence above before GUI. Static VXLAN with explicit VTEP/VNI/VLAN mappings
remains required on the roadmap; EVPN/BGP is a later separate increment.


## Opt-in finite closed-port reauthentication

`dot1x.reauthentications:0..3` adds an explicit finite sequence of at most four
complete authentications to the existing one-peer wired profile. Omission or 0
retains one lease. At every boundary the worker confirms gate closure before
sending a fresh Identity, clears the previous RADIUS transaction and State,
and requires another verified MD5/Success before reopening. The first accepted
username and physical peer remain pinned; even another allowlisted identity
cannot replace that username within the command. Each exchange has its own
1..5-second deadline, each kernel lease remains 1..30 seconds, and the whole
command retains the shared 64-discard budget. No previous success authorizes
traffic through an outage or rejection in a later exchange.

Local tests passed 905 cases in 26.837 seconds with 137 environment-dependent
skips. Unit coverage includes the 0/1/3 finite budgets, fresh State boundaries,
closure before each new grant, timeout and verified rejection after earlier
success, and identity-change refusal. Syntax and diff checks passed.
Native validation of implementation `a6e20f9fdf164a0c832acb6d4998418ca23936b3`
is pending in the
[dedicated wired job](https://github.com/sou1915/Network-LABS/actions/runs/41864390885/job/126694713007).
The extended scenario requires two actual EAPOL/MD5/Success cycles and four
RADIUS requests, separate request authenticators/State, second-lease
bidirectional traffic, backend loss between cycles with closed timeout, and
cold restore/recovery of the declared budget. A queued or skipped job is not
native proof; the earlier single-lease evidence does not validate this extension.

This remains a finite foreground command with intentional closed intervals,
not a persistent supplicant/authenticator daemon or uninterrupted admission.
Managed supplicants, unbounded reauthentication, stronger EAP methods, dynamic
VLANs, multiple clients, accounting and broader LAN combinations remain separate.
Continue LAN before GUI. Static VXLAN with explicit VTEP/VNI/VLAN mappings and
later separate EVPN/BGP remain required roadmap work.


### Targeted native validation dispatch

CI commit `952d15442c731170efa5ffcb4ca5c055b5a0230a` adds manual scope
selection to the existing workflow. Push/PR still select every job. To validate
wired admission without launching the other 35 native/service jobs:

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=dot1x
```

The replacement [targeted run](https://github.com/sou1915/Network-LABS/actions/runs/41864390885)
selects `dot1x-wired-interop` and `tests`; the other 35 jobs were observed skipped
by the explicit manual selection. Both selected jobs remained queued with empty
steps and no runner assigned at the last check. No deployment approval was
pending. Superseded queued/full duplicate matrices were requested to cancel;
this does not supply native proof or indicate that the selected tests passed.
The runtime code remains the implementation at `a6e20f9`; validation is still
pending until the real selected native job executes successfully.


### Official Actions service incident observed

On 2026-11-04 the public GitHub Status API reported Actions as
`degraded_performance`. The unresolved
[Incident with Actions and Pages](https://stspg.io/pjgptg3cfc6n)
was investigating from 16:05:31 UTC; its 16:12:55 UTC update also included
Webhooks. This is consistent with the selected jobs remaining queued without
runners, but is not proof of an account-specific queue cause. Neither selected
check had annotations, and no deployment approval was pending. Reading repository
Actions settings through the configured integration returned HTTP 403; local
execution has no sudo or effective capabilities for native namespace tests.

Keep targeted run `41864390885` pending and follow its result when service
recovers; do not repeatedly dispatch duplicate matrices. Native validation is
still unconfirmed. No authentication/gate checks or native prerequisites were
relaxed to work around the incident.


## Finite reauthentication: successful native validation

This supersedes the pending/queue observations above. Validation commit
`b350281e625da65745725c726de57047cf88a02d` passed the
[dedicated native wired job](https://github.com/sou1915/Network-LABS/actions/runs/41873926458/job/126728123068)
in **97.788 seconds** on Ubuntu 24.04. The general `tests` job passed on the
same commit. Local tests passed 906 cases in 26.697 seconds, with 137
environment-dependent skips; compilation and diff checks passed. The 35 other
jobs were intentionally skipped in this targeted manual dispatch and are not
claimed as passing native coverage.

Real wpa_supplicant/FreeRADIUS completed two Identity/MD5/Success cycles with
four captured RADIUS requests, fresh request authenticators/State and two
captured EAPOL Success packets. Actual second-lease bidirectional traffic,
finite completion/closure, backend loss after the first lease with no fallback,
closed timeout and saved-budget cold restore/recovery passed. The original
single-lease wrong-credential/identity, Logoff, SIGKILL expiry, separate-CLI
teardown, drift refusal and host isolation scenarios also remained passing.

Failure history is retained:

- Run `41864390885`, job `126694713007`, failed with a gate
  `CalledProcessError` during the second verified RADIUS exchange. The original
  report did not contain a kernel errno, so the precise cause is unconfirmed.
  Diagnostic-only commit `c116c19` passed natively in 97.046 seconds; that retry
  alone was not treated as a repair of an intermittent failure.
- Commit `6bfdf12` now atomically replaces the verified gate with the identical
  policy and exactly one finite admission for every verified grant. This removes
  reliance on reclaiming previous timeout-set elements without increasing set
  capacity, extending a lease or accepting policy drift. Unit coverage checks
  the single transaction, retained size-one policy and pre-mutation drift refusal.
- Its native run `41873562663`, job `126726862756`, failed the first immediate
  positive ping after cold restore, before the added reauthentication scenario.
  The final test consistently uses the original bounded positive delivery
  criterion: actual traffic must succeed inside a verified admitted lease.
  Default-closed and bidirectional negative checks were not relaxed.

This completes the optional finite reauthentication increment only. Every
renewal deliberately closes before a new complete exchange; historical success
never authorizes traffic through later timeout/rejection. Persistent services,
managed supplicants, stronger EAP, dynamic VLANs, multi-client ports, accounting
and broader LAN compositions remain separate work. LAN remains ahead of GUI;
static VXLAN VTEP/VNI/VLAN mapping and later EVPN/BGP remain on the roadmap.


## Maximum-budget and later-lease crash validation extension

Test-only commit `d5fdba582c5c45e8972c8daee4d57758256a4beb` extends the wired
scenario to the maximum `reauthentications:3` with three-second leases. It
requires four real successful authentications, exactly eight captured RADIUS
requests, eight distinct Request Authenticators, four fresh State values with
matching continuation echoes, actual final-lease delivery and bounded completion
with no fifth grant. It then kills the original worker during its second lease
with renewal budget remaining and requires kernel expiry, blocked data in both
directions beyond expiry/another exchange interval, no live original worker
and no replacement worker record.

The [targeted native/general run](https://github.com/sou1915/Network-LABS/actions/runs/41878259282)
returned queued snapshots during earlier polling. Final logs/timestamps below
supersede those stale status reads; they do not establish actual queue duration.
Public GitHub Status reported Actions operational; no account-specific queue
cause was established. Syntax and diff checks and all
15 focused local dot1x tests passed. The earlier superseded test-only run
`41878221476` was requested to cancel after correcting the capture helper's
list-valued State comparison to use tuples.

Runtime behavior is unchanged from the successful `b350281` evidence above;
that two-cycle native proof remains valid. The completed boundary evidence
below now validates this test extension.
LAN remains ahead of GUI, with static VXLAN and separate EVPN/BGP tracked.


### Maximum-budget and renewed-lease SIGKILL: completed evidence

At `d5fdba582c5c45e8972c8daee4d57758256a4beb`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41878259282/job/126743630911)
passed in **128.898 seconds** on Ubuntu 24.04, finishing at 17:34 UTC on
2026-11-04. The general `tests` job also passed on that commit. The selected
manual dispatch intentionally skipped the other 35 jobs; no broader native
matrix result is claimed. Syntax/diff checks and 15 focused local tests passed.

The real maximum-budget scenario completed four verified authentications,
exactly eight captured requests with distinct Request Authenticators and four
fresh State values echoed only in their matching continuations, actual final-
lease delivery and finite closure with no fifth grant. Killing the original
worker during the second lease with budget remaining returned unknown, left no
live original worker or replacement record, and allowed only the remaining
three-second kernel lease before bidirectional traffic stayed blocked across
another exchange interval. All preceding native lifecycle, outage, restore,
drift and host-isolation checks in the same scenario also passed.

Earlier polling returned queued snapshots even after the actual completion
time. Those observations were stale; they are not evidence of an ongoing queue
or an account-specific runner problem. Use the final job/log timestamps above.
The superseded capture-comparison fixture run is not counted as validation.

This adds boundary/crash proof for the existing finite profile and changes no
runtime policy. It is not persistent reauthentication, broader EAP, dynamic
VLANs, multi-client admission or accounting. Remaining AAA/IPv6/switching/service
compositions continue before GUI; static VXLAN and separate EVPN/BGP stay tracked.


## IPv6-only DNS across static router subinterfaces

An explicit `example --ipv6-dns-subinterfaces` adds a separate IPv6-only DNS
host to the existing static ROAS/tagged-transit reference. `listen_ipv6:true`
on an IPv6-only single-interface host renders only its explicit IPv6 listener;
PC1's explicit IPv6 resolver reaches PC4 across VLAN 10, R1's VLAN 100 transit
and R2. Existing A-record policy remains required and AAAA records remain
optional: an A answer is DNS data, not an IPv4 connectivity claim. No non-loopback
IPv4 addresses or forwarding/routes are added. See
[IPV6_DNS_SUBINTERFACES.md](IPV6_DNS_SUBINTERFACES.md) for setup and limits.

At implementation/validation commit
`bb17f52207a33fc73887db4342775761214c747f`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41890023350/job/126784651019)
passed in **17.131 seconds** on Ubuntu 24.04. Real dnsmasq served A/AAAA over
IPv6 UDP/TCP, with only IPv6 DNS listener sockets and non-loopback addresses,
actual VLAN 10/100 DNS captures, NXDOMAIN, and a successful managed IPv6 TCP
DNS probe. DNS outage/recovery, independent same-VLAN delivery during service,
static-route and VLAN faults, route/VLAN/config drift refusal, declarative cold
restore and host namespace/link/route/rule/forwarding invariants passed.
The existing dual-stack DNS and static IPv6 subinterface native jobs, plus
general CI, also passed on the same commit. The other 34 jobs were intentionally
skipped in this targeted manual dispatch; no broader native coverage is claimed.
Local tests passed 910 cases in 26.539 seconds with 138 environment-dependent
skips; syntax and diff checks passed.

The first native run `41889505356`, job `126782818112`, passed its service/wire/
fault checks but failed save because the test restored a deleted route with the
kernel's default protocol instead of the engine's declared `proto static`.
Fixture repair `9fedba9` restores that exact protocol. Drift checks were retained;
the initial run remains failed evidence. The final implementation also explicitly
refuses RADIUS access in the IPv6-only DNS composition and tests that exclusion.

The broader mixed dual-stack profile retains full physical numbering and rejects
partially numbered networks. IPv6-only DNS permits static physical and existing
router dot1Q routing only; AAA, dynamic IPv6, SVIs and security/firewall
compositions remain separate work. This completes one tracked IPv6 subinterface
service composition, not all IPv6/LAN services. Continue the remaining
AAA/IPv6/switching/service sequence before GUI. Static VXLAN with explicit
VTEP/VNI/VLAN mappings and later separate EVPN/BGP remain required roadmap work.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-dns`.


## IPv6-only DNS with stateful forwarding firewall

`example --ipv6-dns-firewall` adds an explicit physical IPv6-only service/security
composition: PC1 queries a separate dnsmasq endpoint through FW1. The reference
allows UDP/TCP destination port 53 only between the declared /128 endpoints and
ports, plus client-originated echo; conntrack admits returns and default drop
covers other forwarded traffic. IPv6-only DNS can now coexist with the existing
static physical `firewall_ipv6` profile. Mixed dual-stack, subinterfaces, SVIs,
dynamic IPv6, AAA and other security combinations retain their exclusions.
See [IPV6_DNS_FIREWALL.md](IPV6_DNS_FIREWALL.md) for setup and precise scope.

At implementation/validation commit
`9df4670e82f600005136741a58e0705f92a0691a`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41893486552/job/126796720048)
passed in **21.408 seconds** on Ubuntu 24.04. Real dnsmasq UDP/TCP A/AAAA
responses and the managed IPv6 TCP DNS probe passed, with actual DNS packets
on both firewall interfaces, positive DNS/state/default-drop counters and
matching UDP/TCP conntrack observations. A proven local HTTP listener was
unreachable across forwarding, with ingress SYNs and no egress SYNs. DNS outage
left allowed echo working; disabling forwarding left local DNS working and
refused save. Extra-table drift refusal and declarative cold restore passed.

A separately recreated stateless policy with an explicit echo-return rule kept
routed echo working, but both DNS transports failed across forwarding while
both succeeded locally on the live server. Restoring the saved stateful policy
restored DNS. Host namespace/link/IPv4+IPv6 route/rule/forwarding/nftables
invariants passed. Existing IPv6 firewall and IPv6 DNS/subinterface native jobs,
plus general CI, all passed on the same commit. The other 35 jobs were skipped
by the explicit manual selection and are not claimed as validated here.
Local tests passed 914 cases in 26.738 seconds with 139 environment-dependent
skips; compilation and diff checks passed. No native failure preceded this
successful implementation checkpoint.

This is forwarding policy and service coexistence, not local-input filtering,
DNS server authentication, encrypted DNS, DNSSEC, NAT66 or dynamic/dual-stack/
subinterface firewall support. The A answer remains DNS data, not an IPv4
route or delivery claim. Remaining AAA/IPv6/switching/service compositions
continue before GUI. Static VXLAN with explicit VTEP/VNI/VLAN mappings remains
required; EVPN/BGP remains a separate later increment.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-dns-firewall`.


## Separately opted-in IPv6 local-input firewall

`example --ipv6-input-firewall` adds `firewall_ipv6.input` on the existing
static physical IPv6-only firewall. It has its own default/stateful/rules,
accepts the bounded forwarding rule fields except `out`, and refuses nested
input policies. Omission renders no input chain and retains forward-only
behavior. The forward chain and local output remain independent. The reference
permits PC1 to reach FW1's client-side address with echo and TCP/8080; it does
not create a persistent local HTTP service. DNS remains on the separate PC2.
See [IPV6_INPUT_FIREWALL.md](IPV6_INPUT_FIREWALL.md) for setup and scope.

Input always permits loopback and ICMPv6 Neighbor Solicitation/Advertisement
with immediate ICMPv6 next-header and hop limit 255 on declared physical ports,
before configurable filtering. These exceptions keep static DAD/NDP working;
they are not neighbor authentication, comprehensive fragment/extension handling,
RA Guard or dynamic/multicast service support. The combined table is installed
before physical links/services, fingerprinted as a whole, and restored from
declared startup policy without conntrack/fixture snapshots.

At implementation/validation commit
`bb4d071538ca6e9a43d8b81b38a2aa41921a41b1`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41902272895/job/126827572558)
passed in **33.861 seconds** on Ubuntu 24.04. Proven local listeners, allowed
client/port versus denied port/opposite-side client, actual ingress packets
without denied-port response packets, and positive loopback/NDP/state/allow/drop
input counters passed. Neighbor cache flush forced fresh NDP under the policy.
DNS forwarded through FW1 and DNS initiated by FW1 both worked; separately
recreated stateless input blocked FW1's DNS replies while forwarded DNS and
local HTTP allowance remained working with a proven live server.

External input-rule drift opened a proven denied listener and refused save;
cold restore restored denial. Omitting input restored the old forward-only
local-access behavior, followed by restoration of the protected policy. Host
namespace/link/IPv4+IPv6 route/rule/forwarding/nftables invariants passed.
Existing IPv6 forward-firewall and DNS/firewall native regressions plus general
CI all passed on the same commit. The other 36 jobs were skipped by this manual
selection and are not claimed as passing native coverage. Local tests passed
917 cases in 26.864 seconds with 140 environment-dependent skips; compilation
and diff checks passed.

The first run `41901966354`, job `126826500117`, passed input/state/drift checks
but failed the immediate DNS probe in its final legacy-policy recreation
control. Test repair `bb4d071` uses the same bounded actual-DNS readiness check
as the other recreated modes. No packet success is fabricated and no denial or
policy check was relaxed. That first run remains failed evidence.

This completes a bounded local-input increment on static physical firewalls,
not generic host ACLs, local-output policy, NAT66, dual-stack/subinterface/SVI/
dynamic/AAA security combinations or application authentication. Remaining LAN
AAA/IPv6/switching/services continue before GUI. Static VXLAN VTEP/VNI/VLAN
mapping remains required, with EVPN/BGP a separate later increment.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-input-firewall`.


## Explicit AAAA-only DNS zone increment

An explicit empty `dns_server.records:{}` is now accepted when valid
`records_ipv6` supplies at least one AAAA record. Omitted/null/non-map A data
and a zone with neither A nor AAAA remain refused. Existing 256-record-per-
family, 64 KiB config, name/zone/address/uniqueness bounds remain. Listener
selection is unchanged and independent of record family. The new
`example --ipv6-dns-aaaa` reference removes dummy A data from the static
IPv6 ROAS/tagged-transit DNS composition. See
[DNS_AAAA_ONLY.md](DNS_AAAA_ONLY.md) for usage and exact scope. This supersedes
the earlier requirement for a nonempty A map, not the other DNS bounds.

At implementation/validation commit
`9306d24d57f90949947a76aa9cd9c81e5ae92c47`, both extended native scenarios passed:

- [Physical dual-stack DNS](https://github.com/sou1915/Network-LABS/actions/runs/41903234244/job/126831053927),
  **43.186 seconds**: actual AAAA answers and A/NODATA over IPv4/IPv6 UDP/TCP,
  NXDOMAIN for missing names, captures on both transport families, explicit
  IPv6-family managed probe success through the selected IPv4 resolver, and
  IPv4-family probe failure rather than record-family fallback. Saved empty A
  maps and successful AAAA-only behavior after cold restore were verified.
- [IPv6-only subinterface DNS](https://github.com/sou1915/Network-LABS/actions/runs/41903234244/job/126831053243),
  **23.898 seconds**: AAAA-only UDP/TCP answers, A/NODATA, managed IPv6 TCP
  DNS probe, retained empty A map and cold restore across static tagged routing.

The previous A/AAAA service, fault, drift and host-isolation scenarios within
both native jobs remained passing. General CI also passed on the same commit;
the other 37 jobs were skipped by manual suite selection and are not claimed
as passing native coverage. Local tests passed 920 cases in 26.763 seconds,
with 140 environment-dependent skips. Compilation and diff checks passed.

No listener family, upstream resolver, cache persistence, CNAME traversal,
DNSSEC, DNS64 or dynamic registration is inferred from this record-data change.
IPv4-only and mixed-record defaults remain intact; routing/security combination
limits remain as documented for each profile. Remaining LAN services and
AAA/IPv6/switching work precede GUI. Static VXLAN with VTEP/VNI/VLAN mapping
and later separate EVPN/BGP remain required roadmap work.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=dns-aaaa`.


## Explicit IPv6 read-only TFTP increment — 2026-11-05

`example --ipv6-tftp` adds one separate IPv6-only dnsmasq TFTP server on the
existing static physical two-router reference. The server opts in through
`tftp_server.family:ipv6`; the client independently chooses
`tftp-read --family ipv6`. Omitted families retain IPv4 defaults. The client
validates literal addresses against the explicit family, performs a matching
route lookup with the observed IPv6 source, binds that source, and uses a
v6-only socket. No DNS or family fallback is added. Peer tuple/TID pinning,
65536-byte/256-datagram bounds, finite retries/deadline, blksize negotiation,
final-ACK dally and optional expected SHA-256 retain their existing semantics.
See [IPV6_TFTP.md](IPV6_TFTP.md) for setup and limits.

At implementation/validation commit
`cc2361876e6869e4e6674c721f027f3ba05b7891`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42028445357/job/127248456722)
passed in **26.111 seconds** on Ubuntu 24.04. Real dnsmasq served empty,
exact-block, binary-tail and 64-KiB content across the static IPv6 two-router
path with classic/negotiated blocks and verified hashes. Actual IPv6 UDP
captures contained the selected client/server addresses and blksize wire bytes.
Wrong expected hash and missing-file errors, unchanged declared runtime state,
service outage/recovery, forwarding failure with a successful local server
wire control, forwarding/file-drift save refusal, saved IPv6-family retention,
64-KiB cold restore and host namespace/link/IPv4+IPv6 route/rule/forwarding
invariants passed.

Existing IPv4 TFTP/blksize and static IPv6 subinterface native regressions,
plus general CI, all passed on the same commit. The other 37 jobs were skipped
by targeted manual selection and are not claimed as passing native coverage.
Local tests passed 925 cases in 28.157 seconds with 141 environment-dependent
skips. Added local IPv6 UDP wire coverage verified wrong-TID rejection,
duplicate final-DATA acknowledgement and unchanged binary length/hash. Syntax
and diff checks passed. No failed native run preceded this checkpoint.

The managed IPv6 server profile requires exactly one static IPv6-only
single-interface server, physical hosts/routers and static routes. It excludes
mixed/dual-stack, switches, SVIs/subinterfaces, dynamic IPv6, DNS/AAA/management
and firewall/security compositions. This is unauthenticated read-only TFTP,
not writes, encryption, generic external-server interoperability, path-MTU
coverage or confirmed final-ACK receipt. No received file is stored by the
managed client. Broader file services and remaining AAA/IPv6/switching/service
compositions continue before GUI. Static VXLAN with VTEP/VNI/VLAN mapping
remains required; EVPN/BGP remains separate later work.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-tftp`.


## Managed IPv6 isolated NTP reference — 2026-11-05

`example --ipv6-ntp` adds `ntp_server.family:ipv6` for one separate static
IPv6-only local reference, using chronyd `-6 -x`, an explicit bind address,
private Unix control socket and /128 client ACLs. The IPv6 profile requires
`local_stratum` and refuses upstream/hierarchy configurations. IPv4 defaults,
including upstream/relay support, retain their existing behavior. Passive
selected-family UDP socket observation now supports Linux /proc/net/udp6 with
native 32-bit word order while preserving /proc/net/udp behavior for IPv4.
See [IPV6_NTP.md](IPV6_NTP.md) for setup and scope.

At implementation/validation commit
`cdcd58c4213c5c7d495a017e8f2305d8b7cb54b8`, the
[dedicated IPv6 native job](https://github.com/sou1915/Network-LABS/actions/runs/42030027136/job/127253825568)
passed in **16.291 seconds** on Ubuntu 24.04. Actual managed chronyd stratum-10
SNTP replies passed origin/version/mode/stratum checks. Allowed and denied
client requests and allowed replies were captured on IPv6 UDP/123; the denied
client had an independently proven routed ICMPv6 path. Config/PID/argv and
exact UDP6 binding observations, fixed read-only tracking, no IPv4 UDP/123
listener and all five live capability sets without CAP_SYS_TIME were verified.
The fixture added one explicitly permitted R2 source for a successful independent
wire control while R1 forwarding was disabled. No clock-setting command or
client adjustment was invoked.

Service outage/recovery, truthful socket-absent versus config-conformant evidence,
stopped-control-socket refusal, forwarding/config drift save refusal, retained
IPv6 family/client policy, cold restore and host namespace/link/IPv4+IPv6 route/
rule/forwarding invariants passed. The existing IPv4 local-reference/relay/client
native scenario, IPv6 service-probe and IPv6 TFTP regressions, plus general CI,
all passed on the same commit. The other 38 jobs were skipped by the explicit
manual selection and are not claimed as passing native coverage. Local tests
passed 929 cases in 27.596 seconds with 142 environment-dependent skips;
compilation/diff checks passed. No failed native run preceded this checkpoint.

This is an isolated unauthenticated local reference, not accurate/external time,
NTS, an IPv6 upstream hierarchy or automatic clock synchronization. The managed
IPv6 profile excludes mixed dual-stack, switches, SVIs/subinterfaces, dynamic
IPv6 and DNS/TFTP/AAA/management/firewall/security compositions. Broader LAN
services and remaining AAA/IPv6/switching work continue before GUI. Static
VXLAN with explicit VTEP/VNI/VLAN mappings remains required; EVPN/BGP remains
a separate later increment.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-ntp`.


## Bounded managed IPv6 NTP relay — 2026-11-05

`example --ipv6-ntp-relay` adds one IPv6 relay following another managed local
reference. PC4 (`2001:db8:40::40`) serves local stratum 10 to PC2; PC2
(`2001:db8:20::20`) serves derived stratum 11 to PC1. PC1 cannot query the
source directly, and PC3 cannot query the relay. Upstream must be the bound
address of another managed IPv6 NTP server whose ACL permits the relay's
source. Self/unknown/non-NTP/unallowed upstreams, cycles, more than two servers
and two independent roots in a two-server profile are refused. One standalone
local reference remains supported. Relay acquisition binds its declared IPv6
address. Both servers retain `-6 -x`, no CAP_SYS_TIME and private read-only
control paths. See [IPV6_NTP_RELAY.md](IPV6_NTP_RELAY.md) for usage and limits.

At implementation/validation commit
`6db2e15853b357ab224012a47500cf17d1ea4888`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42032733623/job/127262984424)
passed in **35.755 seconds** on Ubuntu 24.04. Actual stratum-10 source and
stratum-11 relay/client responses, chronyc selected-source observation, upstream/
downstream IPv6 UDP/123 captures, independently reachable but denied clients,
PID/argv/socket evidence and all live capability sets without CAP_SYS_TIME
passed. Source loss followed by a fresh relay produced an explicit rejected
unsynchronised NTP response and `Not synchronised` tracking, not usable time or
local fallback. Restored source/restarted acquisition, config drift refusal,
declarative cold restore and host namespace/link/IPv4+IPv6 route/rule/forwarding
invariants passed.

Standalone IPv6 NTP, existing IPv4 reference/relay/client, IPv6 service-probe
regressions and general CI all passed on the same commit. The other 39 jobs
were skipped by explicit suite selection and are not claimed as passing native
coverage. Local tests passed 932 cases in 28.261 seconds with 143 environment-
dependent skips; compilation and diff checks passed.

The first native run `42032370786`, job `127261769688`, failed because the
fresh-source-loss control expected `failed` while the existing SNTP parser
classifies invalid/unsynchronised replies as `unknown`. Fixture repair
`6db2e15` requires `unknown`, `INVALID_RESPONSE`, an explicit `Unsynchronised`
detail and independent `Not synchronised` tracking. Runtime probe semantics
were not relaxed; the first run remains failed evidence.

A live chronyd relay may retain its previous estimate after source loss.
No immediate revocation or finite holdover timeout is claimed; only the fresh-
relay/no-local-fallback boundary above is validated. This remains local lab
reference behavior, not externally accurate time, clock adjustment, NTS,
arbitrary external/multi-hop NTP hierarchies or broader service/security/dynamic
compositions. Remaining LAN work precedes GUI; static VXLAN VTEP/VNI/VLAN
mapping remains required, with EVPN/BGP separate later work.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-ntp-relay`.


## IPv6 read-only TFTP over static dot1Q routing — 2026-11-05

`example --ipv6-tftp-subinterfaces` adds a separate PC4 IPv6 TFTP service
at `2001:db8:30::10` behind the existing ROAS VLANs 10/20 and tagged VLAN-100
static transit. The validation now permits Linux VLAN switches and static
router dot1Q children in the IPv6 TFTP profile. All routed host/router ports
must remain explicitly IPv6-numbered; dot1Q parents remain unnumbered.
Partial numbering, IPv4 physical/child addressing, dynamic services, SVIs,
other services/security and multiple TFTP servers remain refused. Existing
physical IPv6 and default IPv4 references retain their behavior. Public binary
imports, bounded octet reads, hashes, family/source/peer selection and transfer
limits are unchanged. See [IPV6_TFTP_SUBINTERFACES.md](IPV6_TFTP_SUBINTERFACES.md).

At implementation/validation commit
`c8ad4031512625b9b6471f11aa202e028816a725`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42035723814/job/127273252102)
passed in **33.705 seconds** on Ubuntu 24.04. Actual IPv6 UDP request and reply
packets were captured on the R1 parent with VLANs 10 and 100, alongside real
blksize bytes and successful hash-checked transfer. Clients on VLANs 10 and 20
both read successfully. Empty/exact-block/binary-tail/64-KiB transfers, classic
and negotiated block sizes, wrong-hash and missing-file failures, unchanged
runtime declarations, service outage/recovery, forwarding loss with an
independent successful local server wire control, deleted static route and
pruned transit VLAN with continued same-VLAN delivery all passed. Restored
routes retain the declared static protocol. Forwarding/route/VLAN/file drift
refused save; declarative cold restore retained service/family/topology and
passed a 64-KiB transfer. Host namespaces, links, IPv4/IPv6 routes/rules and
IPv6 forwarding invariants remained unchanged.

Physical IPv6 TFTP, IPv4 TFTP/blksize, static IPv6 subinterface and general CI
jobs also passed on the same commit. The other 40 jobs were skipped by the
explicit manual selection and are not claimed as passing native coverage.
Local tests passed 935 cases in 28.127 seconds with 144 environment-dependent
skips; compilation and diff checks passed. No failed native run preceded this
checkpoint.

This is static tagged routing with read-only unauthenticated TFTP, not dynamic
IPv6, SVIs, mixed/dual-stack service routing, STP/bundles, firewall/security,
other service coexistence, writes, encryption or generic path-MTU coverage.
Remaining LAN AAA/IPv6/switching/service work continues before GUI. Static
VXLAN with explicit VTEP/VNI/VLAN mapping remains required; EVPN/BGP remains
separate later work.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-tftp-subinterfaces`.


## Separate managed IPv6 DNS and TFTP services — 2026-11-05

`example --ipv6-dns-tftp` combines PC4 DNS (`2001:db8:30::10`) behind R2 and
PC3 read-only TFTP (`2001:db8:20::10`) on ROAS VLAN 20. PC1 on VLAN 10 uses
only PC4 as its declared resolver. The AAAA-only zone maps `files.lab.test`
to PC3; TFTP reads still use the explicit selected IPv6 literal. There is no
automatic name resolution, name-to-transfer binding, DNS cache or family
fallback. When DNS/resolvers coexist with IPv6 TFTP, validation requires one
separate managed IPv6 DNS server and refuses unknown/alternate client resolvers,
resolvers on the TFTP node and cohosted services. Static physical/dot1Q/Linux
VLAN scope, complete routed numbering and other exclusions remain. See
[IPV6_DNS_TFTP.md](IPV6_DNS_TFTP.md) for usage and topology.

At implementation/validation commit
`4a8cb132a9640d92ef6e99d3a16d119b75bb07ce`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42037833110/job/127280504290)
passed in **32.381 seconds** on Ubuntu 24.04. Real DNS UDP/TCP AAAA answers,
A/NODATA, NXDOMAIN, a managed DNS probe, separate DNS/TFTP listener observations,
concurrently scheduled DNS and TFTP operations, and actual request/reply captures
on VLANs 10/100 for DNS and 10/20 for TFTP passed. Empty, exact-block, binary-tail
and 64-KiB transfers with classic/negotiated blocks, lengths and SHA-256 checks
passed without changing runtime declarations.

Stopping DNS left explicit-literal TFTP working and made both DNS transports
and the managed name probe fail. Stopping TFTP left both DNS transports and
the managed DNS probe working. Deleting the static subnet-30 route isolated
DNS while TFTP remained healthy; pruning VLAN 20 isolated TFTP while DNS
remained healthy. Same-VLAN PC1/PC2 traffic continued through these controls.
Both service restarts and exact route/VLAN restoration recovered operation.
Route/VLAN and either service-config drift refused save. Declarative cold
restore retained the exact combined specification and both services, including
a successful 64-KiB transfer. Host namespaces, links, IPv4/IPv6 routes/rules
and IPv6 forwarding invariants remained unchanged.

Standalone tagged IPv6 DNS, tagged IPv6 TFTP and general CI also passed on
that commit. The other 42 jobs were skipped by explicit manual selection and
are not claimed as passing native coverage.

Local confirmation passed 938 tests in 28.277 seconds with 145 environment-
dependent skips; compilation and diff checks passed. The first full local run
failed one existing RADIUS retry socket case with a peer timeout. No accounting
or retry code/assertion changed: the seven-case retry module passed unchanged
in 1.514 seconds, then the full confirming run passed. The initial local failure
is retained here; its timing cause was not established. No failed native run
preceded this checkpoint.

This validates separate managed DNS/TFTP coexistence on static IPv6 paths,
not authenticated/encrypted DNS/files, TFTP name resolution or writes, DNS
recursion/CNAME/DNSSEC, mixed/dual-stack, dynamic IPv6, SVIs, AAA/NTP or firewall
combinations. Remaining LAN work precedes GUI. Static VXLAN with explicit
VTEP/VNI/VLAN mapping remains required; EVPN/BGP remains separate later work.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-dns-tftp`.


## Offline HTTPS identity validation and explicit replacement — 2026-11-05

HTTPS image build and startup now perform a bounded memory-BIO TLS self-check
against only the supplied CA bundle. OpenSSL validates local leaf/chain trust,
current host-clock validity and server purpose. Expired, future, untrusted and
client-only identities fail before lab allocation, even with matching public
file pins. No sockets, host roots or external CA fetching are used. Existing
private-key checks, public pins and recreate-only policy remain; live clients
still verify the actual peer and IP/DNS identity. Inspection does not become
continuous certificate monitoring or a live-handshake verdict. See
[HTTPS_IDENTITY_LIFECYCLE.md](HTTPS_IDENTITY_LIFECYCLE.md).

The explicit replacement workflow builds a new immutable image and generates
new manifest pins before stop/start. Leaf/key replacement under one CA retains
client CA choice; CA replacement requires an explicit new client trust bundle.
Stale pins refuse changed assets. Cold restore uses retained replacement
assets. Rollback is explicit recreation from the old manifest/image with its
corresponding client CA, without modifying retained base-image identities.
There is downtime; no live reload or automatic renewal is added.

At implementation/validation commit
`a0cac5c5a20cbe68647b0891a0ee7b077522ab8b`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42039875899/job/127287578185)
passed in **5.581 seconds** on Ubuntu 24.04. Correctly pinned expired/future/
client-only/untrusted offline identities refused startup before any lab state
or namespace allocation. Real verified TLS/HTTP and served-leaf DER SHA-256
matched the original certificate, a new leaf and private key under the same CA,
and a replacement CA/leaf/key. Repointing the old manifest at valid new assets
with stale pins refused startup. The replacement CA served successfully to a
client explicitly trusting it, while the old-only CA was rejected. Cold
restore retained the new image/pins and trust behavior. Explicit rollback to
the retained old manifest/image restored the old exact served-leaf fingerprint
and old CA acceptance, with the newer CA rejected. Client key isolation,
unchanged retained base-image CA/cert/key hashes and host namespace/link/
IPv4+IPv6 route/rule invariants passed.

The original persistent HTTPS native scenario and general CI also passed on
that commit. The other 44 jobs were intentionally skipped by manual selection
and are not claimed as passing coverage. No failed native run preceded this
checkpoint.

Local tests passed 941 cases in 29.014 seconds with 146 environment-dependent
skips; compilation and diff checks passed. Real local crypto fixtures verify
expired/future/client-only/untrusted refusals, leaf rekey and refusal of an
explicitly pinned expired rootfs identity. Socket creation is trapped during
the offline self-check to verify that it remains network-free.

Syslog TLS certificate lifecycle/durable retry and broader service work remain
separate. No ACME, revocation, CA/intermediate fetching, unattended rotation,
generic PKI interoperability, user website/application authentication or GUI
is added. Remaining LAN work precedes GUI. Static VXLAN with explicit
VTEP/VNI/VLAN mapping remains required; EVPN/BGP remains separate later work.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=https-identity-lifecycle`.


## Opted-in Syslog TLS peer validation and explicit replacement — 2026-11-05

`example --syslog-tls --syslog-tls-preflight` adds
`verify_peer_on_start:true` to both the sender and collector TLS policies.
Validation requires exactly one declared reciprocal TLS pair, both opted in.
Startup performs a bounded offline mutual TLS exchange with only the supplied
peer CA bundles. It checks current host-clock validity, collector serverAuth,
sender clientAuth and both exact DNS SANs before allocating lab resources.
There are no sockets, host trust roots, external CA fetches, wildcard or
legacy CN-only authorization in this opted-in profile. The default remains
runtime-handshake validation, including deliberate TLS name/trust failure labs.
Each CA bundle trusts the peer; it need not issue the local identity. Existing
pins, key checks and recreate-only edits remain. HTTPS now shares the same
bounded memory-BIO exchange helper without changing its identity-check scope.
See [SYSLOG_TLS_LIFECYCLE.md](SYSLOG_TLS_LIFECYCLE.md).

The explicit lifecycle builds fresh sender/collector images and public pins,
then stops/recreates the lab. Same-CA leaf/key replacement can retain trust;
CA replacement updates the corresponding reciprocal trust. Cold restore needs
the saved replacement assets; rollback requires retained old assets and the
old declaration. This adds downtime, not live reload or unattended renewal.

At implementation/validation commit
`9831449340f3f57571f8cf12cb946f22e12f9ed8`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42041335915/job/127292631585)
passed in **10.022 seconds** on Ubuntu 24.04. Correctly pinned expired/future
certificates on either role, swapped client/server purposes, wrong trust and
wrong peer names were refused before lab state/namespace allocation. Stale
pins on a valid replacement were also refused. Actual guest logger storage
and independent mutually verified octet-framed syslog messages passed with
original identities, new leaf/keys under the same CA, a new CA, cold restore,
distinct reciprocal issuing CAs and explicit rollback. Served collector leaf
DER SHA-256 matched the selected certificate at each stage; both renewed
private keys differed from the originals. Old-only client trust and old client
credentials were rejected by the healthy new-CA profile, with their markers
absent from stored logs. Rollback rejected the newer client credentials.

Service configuration/identity conformity, non-TLS switch key isolation,
unchanged retained image CA/certificate/key hashes and host namespace/link/
IPv4+IPv6 route/rule invariants passed. Cold restore did not restore earlier
volatile logs. This does not prove continuous observation of the sender's
live peer certificate or delivery acknowledgement; the independent wire
client presents the chosen fixture credentials and the guest sender's asset/
configuration conformity is checked separately.

Original Syslog TLS (including its default wrong-name/wrong-trust labs),
HTTPS lifecycle, persistent HTTPS and general CI all passed on that commit.
The other 43 jobs were intentionally skipped by manual selection and are not
claimed as passing native coverage.

Local tests passed 944 cases in 31.685 seconds with 147 environment-dependent
skips; compilation and diff checks passed. Local real-crypto controls include
both roles' validity/purpose/trust/name failures and distinct reciprocal CAs.
Socket creation is trapped during offline validation. No failed native run
preceded this checkpoint.

OpenSSL offline verification remains an extra local preflight; real rsyslog/
GnuTLS remains authoritative for live protocol behavior. Generic cross-library
PKI compatibility, runtime expiry monitoring, ACME, CRL/OCSP, live reload,
unattended renewal, durable sender retry and delivery acknowledgements remain
separate. Remaining LAN work precedes GUI. Static VXLAN with explicit
VTEP/VNI/VLAN mapping remains required; EVPN/BGP remains separate later work.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=syslog-tls-lifecycle`.


## Opt-in node-overlay Syslog disk action queue — 2026-11-05

`--syslog-disk-queue` / `management.syslog_disk_queue:true` adds a pure disk
action queue for existing TCP/TLS forwarding. Defaults remain volatile; UDP
refuses the field. The fixed spool lives at `/var/spool/network-labs-syslog`
on the owned node overlay, outside `/run` tmpfs. Startup refuses imported
base-image spool paths, including symlinks. Directory ownership/mode is
root:root/0700; private umask 0077 yields native-checked root-owned 0600 queue
files. The queue requests max disk space 1 MiB, max segment size 64 KiB,
checkpoint interval one, synchronous queue files, one worker/batch one,
zero enqueue timeout and save-on-shutdown. These are rsyslog settings with
record/metadata/segment overshoot, not a filesystem quota. Full queues and
resource failures can discard messages. See [SYSLOG_DISK_QUEUE.md](SYSLOG_DISK_QUEUE.md).

At implementation/validation commit
`5068997708973ea70b752982918ba92e127115ae`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42045057015/job/127305646601)
passed in **21.711 seconds** on Ubuntu 24.04 / rsyslog 8.2312.0. Both TCP and
mutually authenticated TLS profiles completed real guest logger delivery,
fresh collector suspension, three fixture markers observed in queue records,
actual directory/file permissions, exact sender PID/argv observation, SIGKILL
and observed process death. Queue records remained in place. The fixture
removed only the verified dead PID file and volatile local output, invoked
the existing sender start function, and verified the same container init PID
survived with a new sender PID. Without re-emitting markers or copying queue
bytes, collector recovery stored all three markers. Actual replay packets
contained the TCP marker while TLS captures contained packets but no plaintext
markers. New automatic delivery continued and declared runtime state remained
unchanged.

Spool permission and generated-config drift refused save. A second confirmed
spooled marker was absent from exported declarations, queue files and logs
after lab stop/cold restore; new delivery then worked. Host namespaces, links,
IPv4/IPv6 routes and rules remained unchanged. Inspection stayed conformant
while the sender was dead, explicitly demonstrating that file conformity is
not daemon liveness or delivery evidence.

Default plain-TCP forwarding, default mutual-TLS forwarding and general CI
also passed on that commit. The other 45 jobs were intentionally skipped by
manual selection and are not claimed as passing native coverage.

The first native run `42044564699`, job `127303904974`, failed actual daemon
config validation because rsyslog 8.2312.0 has no `queue.fileCreateMode`
parameter. Repair `5068997` uses supported private `$umask 0077` and adds an
actual mode-0600 check on all observed queue files. No SIGKILL, replay,
permission or restore control was removed. The original run remains failed
evidence; no fallback daemon or memory queue was substituted.

Local tests passed 949 cases in 30.025 seconds with 148 environment-dependent
skips; compilation and diff checks passed. Local coverage also refuses imported
base-image queue records/symlinks and invalid policy/UDP combinations, preserves
default queue rendering and checks conservative spool observations.

Only the action spool has this sender-process recovery boundary. Main queue,
Unix socket buffering, local logs and in-flight network data remain volatile;
logger success is not a durable-enqueue or collector acknowledgement. TCP/TLS
still permits duplicates/loss around in-flight/dequeue/disconnect boundaries.
Spool records are plaintext at rest. No automatic supervisor/restart command,
lab-stop queue retention, host power-loss/filesystem durability proof, corrupt
queue repair or certificate-migration guarantee is added. Broader durable
retry/RELP remains separate work. Remaining LAN work precedes GUI; static
VXLAN with explicit VTEP/VNI/VLAN mapping and later separate EVPN/BGP remain
required roadmap work.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=syslog-disk-queue`.


## Guarded operator recovery for a dead Syslog sender — 2026-11-05

`syslog-forward-recover LAB NODE` makes sender-process recovery an explicit
public CLI operation for an opted-in disk-queue TCP/TLS sender in a retained
running OCI node. It refreshes state under the existing lab lock, refuses
pending configuration or the wrong node/profile, requires managed config/TLS/
spool conformity and reapplies opted-in peer checks with pinned offline assets.
An in-container bounded process census detects a live PID owner or rsyslog
executable even with a missing PID file. Malformed/non-regular/symlink PID files,
unavailable evidence, excess process count and changed PID/inode snapshots
refuse recovery. A second census and comparison precede removal of only the
unchanged dead/zombie/absent process's regular stale PID file. No process is
signalled. The existing start function tests config and launches the fixed
sender; bounded live PID/argv observations are required before returning
`status:started`. No policy or queue/log contents are rewritten by the helper.
See [SYSLOG_FORWARD_RECOVERY.md](SYSLOG_FORWARD_RECOVERY.md).

At implementation/validation commit
`c68850c3070aae41473771348d9fd91ec8fa265a`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42048879065/job/127319255687)
passed in **21.454 seconds** on Ubuntu 24.04. Both TCP and TLS exercised the
public CLI in separate processes. A live sender with its PID file was refused;
with the file missing, the process census specifically identified live rsyslog
and still refused. PID 1, malformed PID and symlink cases were refused with
the supplied file/link intact and the original sender alive. After actual
SIGKILL and observed death, config/spool drift refused before stale-file
cleanup. TCP recovered a stale PID file; TLS recovered without a PID file.
Both returned the actual new sender PID, and duplicate calls refused without
replacing it.

The original disk-queue protocol scenario remains shared, with its original
manual-restart implementation separately selected as a regression. New CLI
recovery preserved the same container init PID and on-disk fixture records,
with exact new PID/argv observations. The fixture removed volatile local
output but did not resubmit markers or rewrite queue bytes; collector recovery
stored all three queued markers. Actual TCP replay contained plaintext while
TLS captures contained packets without plaintext markers. New automatic
delivery, unchanged declared state, permission/config drift-save refusal,
cold-restore non-retention and host network invariants all passed.

Original disk-queue, default TCP forwarding, default mutual-TLS forwarding and
general CI all passed on that commit. The other 45 jobs were intentionally
skipped by manual selection and are not claimed as passing native coverage.
Local tests passed 952 cases in 30.346 seconds with 149 environment-dependent
skips; compilation and diff checks passed. No failed native run preceded this
checkpoint. Local checks also refuse invalid profile/state/drift before any
container mutations and reject ambiguous census output.

The lab lock serializes cooperating CLI actors, not a malicious root process
racing arbitrary in-node changes. Failed readiness verification after a start
request can leave an unverified daemon present; operators must inspect before
retrying. Started is process evidence, not a delivery receipt. No automatic
supervisor, delivery acknowledgement, exactly-once semantics or queue retention
across lab stop/recreation is added. Remaining LAN work precedes GUI; static
VXLAN with explicit VTEP/VNI/VLAN mapping remains required, with EVPN/BGP
separate later work.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=syslog-recover`.


## IPv6 DNS over a physical OSPFv3 pair — 2026-11-05

`example --ipv6-dns-ospfv3` combines one separate managed IPv6 DNS server
with exactly two physical OSPFv3 routers. Router static-route lists remain
empty; hosts retain explicit default gateways. Every numbered router port
participates, with one directly paired active transit and passive LAN ports.
Router IDs differ and hello/dead timers match. Clients use only the managed
IPv6 resolver. Mixed/AAA, switches/SVIs/subinterfaces, security, TFTP/NTP and
dynamic addressing remain excluded. The reference zone is AAAA-only, with
A/NODATA and NXDOMAIN behavior. See [IPV6_DNS_OSPFV3.md](IPV6_DNS_OSPFV3.md).

At implementation/validation commit
`d320b987b0a75e84a2899a480e0dc7996e69398a`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42052137810/job/127330744403)
passed in **40.685 seconds** on Ubuntu 24.04. Full adjacencies, both remote
LAN kernel routes with BIRD protocol/link-local gateways, actual OSPFv3 and
bidirectional UDP/TCP DNS packets, AAAA/A-NODATA/NXDOMAIN and managed DNS probes
passed. No non-loopback IPv4 addresses were present. DNS shutdown left both
OSPF routes/adjacencies and routed echo working. Stopping R2 BIRD withdrew R1's
remote route and broke routed DNS, while both DNS transports still succeeded
from R2's directly connected LAN to the independently live server. Restart
reconverged both directions and restored DNS without inserting a static service
route.

Unmanaged static-route injection and DNS/BIRD config drift refused save.
Cold restore retained exact declarations, empty router static-route lists and
freshly learned routes/DNS behavior. Host namespaces, links, IPv4/IPv6 routes/
rules and IPv6 forwarding invariants remained unchanged. Local tests passed
956 cases in 31.056 seconds with 150 environment-dependent skips; compilation
and diff checks passed. No failed native run preceded this checkpoint.

Standalone physical/SVI OSPFv3, static tagged IPv6 DNS, physical dual-stack
DNS and general CI all passed on that commit. The other 46 jobs were
intentionally skipped by manual selection and are not claimed as passing
native coverage.

This physical dynamic-routing/service composition does not enable DNS over
OSPFv3 subinterfaces/SVIs, alternative-path failover, redistribution, authenticated
OSPF, encrypted DNS, DNSSEC or dynamic registration. Remaining LAN work precedes
GUI. Static VXLAN with explicit VTEP/VNI/VLAN mapping remains required; EVPN/BGP
remains separate later work.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-dns-ospfv3`.


## Costed parallel OSPFv3 transits for IPv6 DNS — 2026-11-05

`example --ipv6-dns-ospfv3-failover` extends the same two-router physical
DNS profile with primary subnet-100 transit cost 10 and backup subnet-200
transit cost 100. Validation now permits one or two directly paired active
transits, every numbered port in OSPF and passive LAN ports. Two-link profiles
require symmetric per-link costs and a distinct preferred link. Existing
single-link endpoint costs remain independently configurable. Router IDs/timers,
managed resolver and other composition bounds remain. No router static fallback
or ECMP is added. See [IPV6_DNS_OSPFV3_FAILOVER.md](IPV6_DNS_OSPFV3_FAILOVER.md).

At implementation/validation commit
`8c2978f05f324662665e5e9a3dfa06c6f31555d3`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42055074653/job/127341141821)
passed in **51.123 seconds** on Ubuntu 24.04. Both Full adjacencies and
bidirectional lower-cost FIB selection passed. Temporary ingress IPv6 drops
on both ends of the primary caused automatic backup selection with working
UDP/TCP DNS and managed probes. Actual simultaneous captures on both R1
transits required request/reply DNS packets only on the selected path. Removing
primary drops restored preference for the primary. Dropping both transits
withdrew both remote LAN prefixes and broke routed DNS while direct R2-to-DNS
UDP/TCP controls remained successful. Restoring only the backup recovered
service while the primary remained blocked.

Admin/carrier stayed UP, and positive drop counters were required at both
ends of each blocked link. Router/DNS PIDs stayed unchanged and alive through
the faults, with declared runtime state unchanged. No address/route injection
or daemon restart repaired connectivity. BIRD-file drift and unrelated static
route injection refused save. External tc faults remain outside managed/save
audit; saving with DNS on the backup exported only exact declarations and
empty router static-route lists. Cold restore created fresh namespaces,
relearned two adjacencies, selected the primary, passed DNS wire checks and
restored baseline qdiscs. Host namespaces, links, IPv4/IPv6 routes/rules and
IPv6 forwarding invariants remained unchanged.

Single-transit DNS/OSPFv3, standalone physical/SVI OSPFv3 and general CI also
passed on that commit. The other 48 jobs were intentionally skipped by manual
selection and are not claimed as passing native coverage.

Local tests passed 959 cases in 30.380 seconds with 151 environment-dependent
skips; compilation and diff checks passed. Local controls refuse equal-cost,
asymmetric-cost, unpaired/half-active or third-transit profiles, while retaining
the prior single-link behavior. No failed native run preceded this checkpoint.

This proves one two-link virtual graph with carrier-up bidirectional IPv6
blackholes, not physical cable-pull, every-kernel/one-way coverage, zero-loss
or fixed-time convergence, ECMP, a larger routing graph, redistribution or
OSPF authentication. Other service/security/SVI/subinterface combinations
remain separate. Remaining LAN work precedes GUI; static VXLAN with explicit
VTEP/VNI/VLAN mapping and later separate EVPN/BGP remain required roadmap work.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-dns-ospfv3-failover`.

## LAN readiness regression and current inventory — 2026-11-05

The full audit at `f3146a0912fb77f59cd12bd3f20c87dc929d5f14`
([run 42056055804](https://github.com/sou1915/Network-LABS/actions/runs/42056055804))
completed with 50 successful jobs and two setup cancellations. The native
container suite passed 51 test cases in 1600.113 seconds; dedicated wired
802.1X passed in 112.327 seconds. Strict LACP exercised the positive
STRICT_VERIFIED path on kernel 7.0.0-1017-azure with pinned iproute2 7.1.0
and passed its scenario in 701.725 seconds.

Tagged IPv6 TFTP and reverse STP/LACP control loss never reached tests in
that attempt: Ubuntu Azure mirror package indexes stalled until setup/job
timeouts. Repair `c145a9e0962178ab7ede0093f32b08d086d329aa` adds a CI-only
official HTTPS Ubuntu archive helper with bounded APT retries/timeouts to
those two jobs. It also corrects stale runtime-plan wording about optional
OVS RSTP; no protocol implementation or test assertions were relaxed.

The [targeted repaired replay](https://github.com/sou1915/Network-LABS/actions/runs/42059320195)
passed all three selected jobs at that repair commit: tagged IPv6 TFTP
(one native scenario, 33.669 seconds), reverse STP/LACP control loss
(one native scenario, 165.158 seconds), and general CI. Its other 49 jobs
were intentionally skipped. All 52 workflow job profiles therefore have
passing evidence across the baseline and replay, not in one green attempt.

Local full tests passed 959 cases in 31.021 seconds with 151 environment
skips. After the wording correction, runtime-plan tests passed 13 cases with
one environment skip. Compilation, shell syntax, documentation link and
diff checks passed. Skipped local cases are not native evidence.

[PROJECT_STATUS.md](PROJECT_STATUS.md) records the current working inventory,
remaining scope and explicitly approximate estimates: native LAN about 80%
(75–85 range), whole product about 45–50%. Its checklist and assumed phase
weights are planning aids, not measured coverage, elapsed effort or an ETA.
[LAN_PROTOCOL_COVERAGE.md](LAN_PROTOCOL_COVERAGE.md) now distinguishes recent
implemented profiles from the old unimplemented entries. Complete remaining
LAN scope/acceptance before full native GUI integration. Static VXLAN mapping,
then separate EVPN/BGP and later WAN remain tracked.

## Managed static IPv6 HTTPS — 2026-11-05

At implementation commit `81ba8ba63e1b844142e670f75a27a55645ba4895`,
`example --ipv6-https` adds one persistent NGINX server behind two numbered
static IPv6 physical routers. Distinct client/server rootfs images keep the
identity on its server; explicit `https_server.family: ipv6` renders only
the declared IPv6 eth0 listener with `ipv6only=on`. Omitted family retains
the IPv4 policy. No wildcard/plaintext listener or IPv4 fallback is added.

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42073646773/job/127407962710)
passed in 13.213 seconds. It verified trusted IPv6 IP SAN/CA and DNS-name
connections, wrong CA/name rejection, fixed GET body and HEAD, 404/405,
IPv6-only addressing/listener and actual encrypted wire traffic. Disabling
R1 forwarding broke the remote client while a direct R2 TLS control worked
and the server PID stayed unchanged. Restoring forwarding recovered service.
Stopping NGINX broke HTTPS while routed ICMPv6 still worked; inspection stayed
explicitly config-only and an explicit restart recovered service. Forwarding/
config drift refused save. Exact declarations and public pins survived saved
cold restore, fresh TLS passed, and host namespaces/links/routes/rules/IPv6
forwarding invariants remained unchanged.

Existing IPv4 HTTPS server and identity-lifecycle jobs passed in 7.943 and
5.090 seconds. General CI also passed in run 42073646773: four selected jobs
succeeded, 49 other jobs intentionally skipped. Local tests passed
962 cases in 30.469 seconds with 152 environment-dependent skips after
allowing existing loopback test sockets; compilation/diff checks passed.
No failed native run preceded this result.

The [guide](IPV6_HTTPS.md) documents the bounded one-server IPv6-only profile.
Dual-stack, dynamic routing/addressing, DNS/other services, firewall/security,
SVI/subinterfaces and multiple-server compositions remain refused. Mutual
TLS, automatic identity lifecycle, application content and automatic process
supervision remain separate work. Remaining LAN work precedes native GUI;
static VXLAN mapping, then separate EVPN/BGP and WAN remain tracked.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-https`.

## Managed IPv6 HTTPS with forwarding firewall — 2026-11-05

Implementation `8ce6321df0e06cee37bc5413478d7e20253288c3` adds
`example --ipv6-https-firewall`. A distinct default-deny FW1 routes PC1 to
the managed IPv6 HTTPS PC2. Its explicit source/destination/interface rules
allow TCP/443 and echo requests, with invalid-state rejection and
established/related return acceptance. Local-input and broader service,
dynamic, dual-stack and VLAN/SVI/subinterface compositions remain refused.

The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42079365366/job/127428042126)
passed in 22.128 seconds. It verified trusted TLS and GET body, wrong CA
rejection, real IPv6 TLS on both firewall ports without plaintext body,
positive HTTPS/state/default-drop counters and IPv6 TCP conntrack. A separate
live TCP/8080 listener was reachable on PC2 but blocked remotely, with actual
ingress packets and no egress packets. Forwarding loss broke remote HTTPS
while direct FW1-to-PC2 TLS worked and server PID stayed unchanged; restoring
forwarding recovered service. NGINX outage left independent allowed echo
working, and explicit restart restored TLS. Forwarding/extra nftables table
drift refused save. Exact saved policy/identity cold-restored with verified
TLS. A stateless variant kept outbound HTTPS permission and explicit echo
return but broke remote HTTPS while direct TLS/echo worked. Restoring the
stateful saved profile recovered service. Host namespaces, links, IPv4/IPv6
routes/rules, forwarding and nftables invariants remained unchanged.

Baseline IPv6 HTTPS (12.919 seconds), standalone IPv6 firewall (20.469
seconds), DNS/firewall (22.223 seconds) and general CI also passed in
run 42079365366. Five selected jobs passed; 49 other jobs were intentionally
skipped, not new native evidence. Local tests passed 965 cases in 32.219
seconds with 153 environment-dependent skips; compilation/diff/link checks
passed. No failed native run preceded this result.

See [IPV6_HTTPS_FIREWALL.md](IPV6_HTTPS_FIREWALL.md) for commands and scope.
The firewall allows ports, not trusted TLS identities; certificate checking
remains a separate client action. This reference does not claim a complete
production PMTU/error-traffic policy. Remaining LAN work precedes native GUI;
static VXLAN mapping and separate EVPN/BGP/WAN remain tracked.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-https-firewall`.

## Same-port HTTPS source-isolation proof — 2026-11-05

At test/validation commit `72b0732f90be9a93dd9075f42071486dae4b0e1a`,
the existing IPv6 HTTPS/firewall native scenario adds a same-port negative
source control. The temporary `2001:db8:10::99` address shares PC1's interface,
destination and TCP/443. Completed DAD, source-bound gateway echo and the
expected default route prove a usable source. A source-bound HTTPS connect
must time out before TLS, with actual ingress SYNs and no egress packets,
plus increasing default-drop counters. Authorized client and direct verified
TLS controls stay successful with the same server PID. Extra addressing is
observed as drift and refuses save, then is removed before normal save.
The same source-isolation control passes after cold restore.

The [expanded native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42086361238/job/127452432140)
passed in 35.461 seconds. Baseline IPv6 HTTPS, standalone IPv6 firewall,
DNS/firewall and general CI also passed: five selected jobs succeeded;
49 other jobs were intentionally skipped. Four focused local policy/CLI
tests and compilation/diff/link checks passed. No failed native run preceded
this checkpoint. This is added evidence for the existing bounded profile,
not new protocol behavior, authenticated client identity or anti-spoofing.

Remaining broader AAA/switching/service compositions and resource acceptance
stay ahead of full native GUI integration. Static VXLAN mapping and separate
EVPN/BGP/WAN remain tracked. Planning estimates remain LAN about 80%, whole
product about 45–50%; added negative coverage does not justify a measured
completion increase.

## Separate IPv6 DNS and named HTTPS — 2026-11-05

At implementation commit `05953899d1187f73a177e8e632704d5ab0cb6f90`,
`example --ipv6-dns-https` adds a separate DNS PC3 at `2001:db8:30::30`
and HTTPS PC2 at `2001:db8:20::20`, behind two physical routers. PC1 uses
only the managed resolver and requests AAAA for `secure.lab.test`; HTTPS
verifies that original DNS identity against only the explicit CA. No
IPv4, host resolver, alternate resolver or literal-address fallback is added.

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42087775672/job/127457432669)
passed in 15.027 seconds. It verified named HTTPS using both UDP/TCP IPv6
DNS, actual DNS and encrypted TLS packets, GET body and wrong CA/name/unknown
DNS-name controls. Stopping DNS broke named HTTPS while literal verified TLS
and the same HTTPS PID remained live. Explicit DNS restart recovered service.
Stopping HTTPS preserved live DNS answers and its PID; explicit HTTPS restart
recovered service. Resolver/DNS/HTTPS config drift refused save; exact
declarations/public pins survived cold restore and verified named HTTPS
returned. Host namespace/link/IPv4/IPv6 route/rule/forwarding invariants passed.

Baseline IPv6 HTTPS, tagged IPv6 DNS, dual-stack DNS and general CI also
passed in run 42087775672: five selected jobs succeeded; 50 other jobs
were intentionally skipped, not new native proof. Local tests passed 968 cases in 30.478 seconds with 154 environment-dependent skips;
compilation/diff checks passed. No failed native run preceded this result.
The [guide](IPV6_DNS_HTTPS.md) documents scope and required DNS SAN/assets.
Firewall+DNS+HTTPS, service co-location, external/service-node resolvers,
dynamic, dual-stack, VLAN/SVI/subinterfaces and broader service compositions
remain refused. DNS address resolution does not establish certificate trust.
Remaining LAN work precedes full native GUI; static VXLAN and separate
EVPN/BGP/WAN remain tracked.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-dns-https`.

## Explicit SSH host identity and cold restore — 2026-11-05

At implementation commit `1ac714da5e0e6dceef004e4fda98d3d9a9777340`,
optional `management.ssh_host_key` references an offline Dropbear ed25519
private key and declares its public identity. The generator option
`example --management --ssh-host-key-file PATH --ssh-authorized-key PUB
--ssh-action identity` creates a standalone restricted IPv4 SSH profile
without its usual syslog sender. Missing/invalid assets fail pre-allocation.
A bounded mode-0600 snapshot is parsed by host `dropbearkey`, compared to
the public declaration and installed only in the selected node's fresh
`/run` as root/mode 0600. Explicit `-r` replaces default `-R` generation only
when selected. Save exports public identity/path references, not raw private
bytes; source assets remain a restore prerequisite. Runtime file type, mode,
ownership and digest drift refuse save. Wider AAA/IPv6/co-location and
automatic key lifecycle remain separate work.

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42089486906/job/127463481874)
passed in 2.703 seconds. Strict known_hosts provisioned from the declared
public identity worked without keyscan and stayed identical across cold
restore. Restricted command and uid-65532 unreadability checks passed.
Runtime content/mode/symlink drift refused save; missing/malformed/changed/
symlink/mode-invalid offline assets refused startup before allocation.
Explicit new identity refused old trust, worked after explicit client trust
update, then cold-restored. Other nodes had no key copy; host namespaces,
links and IPv4/IPv6 routes/rules remained unchanged.

SSH access, RADIUS/SSH and general CI regressions also passed in run
42089486906: all four selected jobs succeeded; 52 other jobs were intentionally
skipped, not new native proof. Local tests passed 972 cases in 30.003 seconds
with 155 environment skips; compilation/diff checks passed. No failed native
run preceded this result. See [SSH_HOST_IDENTITY.md](SSH_HOST_IDENTITY.md).
Remaining LAN precedes native GUI; static VXLAN mapping and separate
EVPN/BGP/WAN remain tracked. Planning estimates remain LAN about 80%,
whole product about 45–50%, not measured test coverage or an ETA.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ssh-host-key`.

## Pinned SSH host identity with RADIUS diagnostics — 2026-11-05

At implementation commit `19c853f6c504d6f137d756aa64624aeb5c717aaf`,
the IPv4 `--radius --radius-ssh` generator accepts `--ssh-host-key-file`
for fixed diagnostics. Host public identity, client SSH key and fresh
verified RADIUS authorization remain separate checks. Direct-user and
reusable-role declarations are allowed, but shell grants anywhere in the
access policy, accounting, Telnet, syslog, IPv6 and NAS server co-location
remain refused. Existing standalone pinned and ephemeral AAA defaults remain.

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42091389971/job/127470040092)
passed in 5.793 seconds. It reuses the SSH/FreeRADIUS reference suite with
pre-provisioned pinned known_hosts and no keyscan. Wrong host trust and
wrong client key denied access; valid client transport still required correct
RADIUS credentials and per-user action permission. Unknown/malformed/
incomplete credentials, shell/SCP/SFTP/injection, backend outage, dead bridge
and unprivileged bridge impersonation controls passed. Private host-key
unreadability/conformity passed. Cold restore preserved the exact trust file,
created a fresh bridge token and recovered authorized diagnostics. Host
namespace/link/IPv4/IPv6 route/rule invariants passed. The native grants are
direct-user; local role checks do not prove every native role combination.

All three selected native jobs passed in run 42091389971, but general CI
failed the new CLI fixture: password/secret files inherited mode 0644 with
runner umask 022, so the CLI correctly refused them. Fixture-only repair
`72ae65a79fb4c8eb8576997344c80201d000e2f1` creates those files with
mode 0600 from creation. Protocol/runtime checks and assertions are unchanged.
The [repaired replay](https://github.com/sou1915/Network-LABS/actions/runs/42125394285)
passed all four selected jobs: pinned RADIUS SSH, standalone pinned SSH,
existing RADIUS/SSH and general CI. The other 53 jobs were intentionally
skipped, not new native proof. The new native scenario passed again in
6.174 seconds ([job](https://github.com/sou1915/Network-LABS/actions/runs/42125394285/job/127588151990)).
Local full tests under explicit umask 022 passed 976 cases in 30.301 seconds
with 156 environment skips; compilation/diff/link checks passed. No native
scenario failed; the first general-CI fixture failure remains recorded.
See [SSH_RADIUS_HOST_IDENTITY.md](SSH_RADIUS_HOST_IDENTITY.md).
Remaining LAN work precedes native GUI; static VXLAN and separate
EVPN/BGP/WAN remain tracked. Planning estimates remain LAN about 80%, whole
product about 45–50%, not measured coverage or an ETA.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ssh-radius-host-key`.

## Pinned dual-stack SSH with IPv4 RADIUS — 2026-11-05

At implementation commit `8c776020e21b88d57a6cb3d7e4c2730216f36949`,
`--radius --radius-ssh --radius-dual-stack --ssh-host-key-file PATH` uses
the declared offline ed25519 host identity on both IPv4 and IPv6 SSH listeners.
RADIUS remains a separate IPv4 backend. Strict known_hosts can be provisioned
for both literal addresses before the first connection and reused unchanged
after cold restore. Standalone IPv6 pinned SSH, shell grants/accounting,
DNS coexistence, dynamic protocols and broader service combinations remain
refused. The IPv6 validator explicitly refuses combined DNS with pinned SSH;
existing unpinned DNS/AAA coexistence remains separate.

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42126484317/job/127591903712)
passed in 37.598 seconds. It reuses the native routed dual-stack RADIUS suite
with pinned host identity: both SSH families verify the same declared key,
wrong host trust/client keys fail, and RADIUS credentials/actions stay enforced.
Captures showed actual IPv4/IPv6 SSH and IPv4 RADIUS, with no plaintext
credentials on TCP/22. Disabling IPv4 forwarding broke RADIUS authorization
over reachable IPv6 SSH while IPv6 echo remained healthy. Disabling IPv6
forwarding broke IPv6 SSH while verified IPv4 diagnostics continued. Backend
loss/recovery, management/backend/forwarding drift refusal, exact declarative
cold restore with unchanged known_hosts and a fresh bridge token passed.
Host namespaces/links/IPv4/IPv6 routes/rules, forwarding and unprivileged-port
invariants remained unchanged.

Pinned IPv4 RADIUS SSH, old unpinned dual-stack RADIUS and general CI also
passed in run 42126484317: all four selected jobs succeeded; 54 other jobs
were intentionally skipped, not new native proof. Local full tests under
umask 022 passed 980 cases in 30.981 seconds with 157 environment skips;
compilation/diff/link checks passed. No failed native run preceded this
checkpoint. See [DUAL_STACK_SSH_HOST_IDENTITY.md](DUAL_STACK_SSH_HOST_IDENTITY.md).
Remaining LAN precedes full native GUI; static VXLAN mapping and separate
EVPN/BGP/WAN stay tracked. Planning estimates remain LAN about 80%, whole
product about 45–50%, not measured test coverage or an ETA.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=dual-stack-ssh-host-key`.

## Kernel memory peak and 20-node headless checkpoint — 2026-11-05

At implementation commit `1ad4241d651fa3ebf6e70d3b10017aa028100712`,
benchmark report v2 adds the optional kernel cgroup lifetime `memory.peak`
beside phase samples, explicit fresh/prior-parent provenance and current-run
assessment only when a fresh parent/kernel counter is available. Unsupported
is null, not zero; inaccessible/corrupt counters fail. Populated pre-existing
parents refuse before allocation, and no peak counter is reset. Parent OOM
events now complement per-node events. Full app acceptance stays unverified.

The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42129277749/job/127601472273)
passed two new scenarios in 29.601 seconds. A 12 MiB allocation freed before
sampling was caught by a 14.965 MiB kernel peak versus a 2.098 MiB idle sample
peak. The fresh 20-node reference ran 10 seconds idle and 10 seconds ICMP,
12 clients/100 requests each. All 1,200 requests returned; all nodes stayed
running and no OOM kill was observed. Kernel peak was 9,588,736 bytes
(9.145 MiB), versus idle/load sampled peaks of 5.449/9.141 MiB. Kernel was
7.0.0-1017-azure, x86_64, four logical CPUs. Host namespace/link/route/rule/
forwarding/nftables invariants and stopped-runtime cleanup passed. The old
enterprise benchmark plus actual HTTP/NAT/return-route/save-restore test
also passed in 21.131 seconds, and general CI passed. Both selected jobs
passed; 57 other jobs were intentionally skipped, not new native evidence.

The artifact ZIP matched GitHub SHA-256 metadata. Exact JSON copies and
per-member/source provenance are committed in docs/benchmarks; see
[BENCHMARK_KERNEL_PEAK.md](BENCHMARK_KERNEL_PEAK.md). Local full tests under
umask 022 passed 985 cases in 30.977 seconds with 159 environment skips;
compilation/diff/link checks passed. No failed native run preceded this result.

This closes a cgroup measurement blind spot, not GUI/heavy-service/full-app
or 8-GB-laptop 2 GiB acceptance. Broader LAN/AAA/switching combinations remain
before native GUI; static VXLAN mapping and separate EVPN/BGP/WAN stay tracked.
Planning estimates stay LAN about 80%, whole product about 45–50%.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=benchmark-kernel-peak`.

## Pinned IPv4 SSH shell with full journaled accounting — 2026-11-06

At implementation commit `9146031a8cddcb11a5987fa1d3a5ff02162f3fc9`,
the explicit host identity is permitted with an IPv4 RADIUS SSH shell only
when accounting, durable Stop outbox and session journal are all enabled.
The CLI requires the complete lifecycle explicitly. Diagnostics-only profiles
still refuse unselected shell grants/accounting. IPv6 pinned shells, partial
lifecycles, Telnet, syslog and NAS service co-location remain refused.

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42173268692/job/127745802977)
passed in 10.636 seconds. It reuses the real journaled SSH shell reference
with pre-provisioned strict known_hosts and no keyscan. Wrong-host trust
failed without a second intent; an authenticated shell left a live payload
after supervisor SIGKILL. Live-owner and populated-session cleanup refused.
Explicit reconciliation terminated the payload and durably queued Stop
without sending network traffic. A bounded explicit flush sent one observed
Stop with the expected session/status/cause and real backend records.
Restarts preserved host trust but created fresh bridge tokens; stale-runtime
reconciliation still refused. Healthy completion followed Stop acknowledgement.
Host namespace/link/IPv4/IPv6 route/rule invariants passed. Native grants are
direct-user; wider role/topology combinations remain unproven.

The suite reuses `ssh-radius-host-key`, now selecting new pinned shell,
old unpinned journal, pinned diagnostics, standalone pinned SSH, RADIUS/SSH
and general CI. All six selected jobs passed in run 42173268692; 54 other
jobs were intentionally skipped, not new native evidence.
Local full tests under umask 022 passed 989 cases in 31.490 seconds with
160 environment skips; compilation/diff checks passed. No failed native run
preceded this result. See [SSH_SHELL_HOST_IDENTITY.md](SSH_SHELL_HOST_IDENTITY.md).
Remaining LAN precedes GUI; static VXLAN mapping and separate EVPN/BGP/WAN
stay tracked. Estimates remain LAN about 80%, whole product about 45–50%.

Targeted command: `gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ssh-radius-host-key`.

## Pinned shell PTY, expiry, disconnect and complete accounting — 2026-11-06

At test/validation commit `91997a938d33eb54b48428dca9db981abd455caa`,
the real shell lifecycle reference also runs with pinned host identity and
the full accounting/outbox/journal profile. No protocol or manifest-scope
change is claimed. Wrong RADIUS credentials/actions created no payload;
explicit exit status 7 propagated. Real PTY, no-new-privileges, empty
capabilities and no password echo passed. Normal exit, duration expiry and
client disconnect removed background payloads and transport directories.
Healthy completions left journal/outbox empty. Backend records contained
four Start/four Stop entries with matching session IDs and cause set 1/5/6/9.
Cold restore reused exact known_hosts without keyscan and executed a verified
shell. Host namespace/link/IPv4/IPv6 route/rule/forwarding/unprivileged-port
invariants remained unchanged.

The [expanded native job](https://github.com/sou1915/Network-LABS/actions/runs/42203206143/job/127843341125)
passed the lifecycle scenario in 7.773 seconds and repeated orphan-journal
controls in 9.935 seconds. All six selected jobs in run 42203206143 passed;
54 other jobs were intentionally skipped. Local full tests under umask 022
passed 990 cases in 30.036 seconds with 161 environment skips; compilation,
diff and link checks passed. No failed native run preceded this validation.
See [SSH_SHELL_HOST_IDENTITY.md](SSH_SHELL_HOST_IDENTITY.md). Remaining LAN
precedes GUI; static VXLAN and separate EVPN/BGP/WAN remain tracked. Planning
estimates remain LAN about 80%, whole product about 45–50%.

## Pinned shell accounting ACK loss — 2026-11-06

Corrected test commit `3a5b15a85e3a8ee051f1103ee2c4d69c8ab66b6b`
adds native packet-loss validation without runtime or protocol scope changes.
Lost Start ACK prevented payload execution (SSH 126) and durably queued a
zero-duration compensating Stop/cause 9. Lost Stop ACK after an admitted
shell returned uncertainty (125), retained Stop/cause 1 and recovered only
through explicit flush. Captures/session IDs, actual backend duplicate Stops,
empty journal/session groups, exact host trust through cold restore and
host namespace/link/IPv4/IPv6 route/rule/nftables invariants passed. Duplicate
delivery is expected; this does not claim exactly-once accounting.

The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42209558186/job/127864535740)
passed ACK-loss in 20.104 seconds, orphan-journal in 9.479 seconds and pinned
lifecycle in 7.596 seconds. All six selected jobs passed; 54 intentionally
skipped. Local tests passed 991 cases in 30.594 seconds with 162 environment
skips. Initial run 42209349058 at `504371a` passed the loss/recovery checks
but failed final saved-spec equality because the expanded fixture lacked
default canonicalization. The corrected fixture uses the standard validator
before startup and retains the exact equality assertion; no runtime behavior
or acceptance assertion was relaxed.

See [SSH_SHELL_HOST_IDENTITY.md](SSH_SHELL_HOST_IDENTITY.md). Remaining LAN
precedes native GUI; static VXLAN and separate EVPN/BGP/WAN remain tracked.
Planning estimates stay LAN about 80%, whole product about 45–50%.

## Wired 802.1X controlled-link revocation — 2026-11-06

Implementation `73a3c56497d95b58dafd8998c598d8151fb0a0f7` adds
controlled-link revocation to the existing finite wired EAP-MD5 profile.
The live worker subscribes to pinned-namespace Linux link events before
sampling flags, checks administrative/carrier state around its bounded wait
and before granting backend Success, and remembers queued down/up loss.
Observed link loss terminates the command with `blocked/LINK_LOST`, closes
the verified gate and discards unused reauthentication cycles. Historical
`authenticated:true` does not mean the peer remains admitted. Link return
requires a new explicit authentication. Truncated/overrun/excessive events
fail closed with an unknown result; runtime/interface generation and gate
closure checks still apply. Scheduling/cleanup latency and the independent
kernel lease after worker death remain explicit limits.

The [dedicated wired native job](https://github.com/sou1915/Network-LABS/actions/runs/42232715325/job/127942385678)
passed the full extended scenario in 128.714 seconds. Real supplicant/RADIUS
admission with a 30-second lease and unused renewals was revoked after both
sustained peer-down and rapid down/up, before lease expiry. Both returned
LINK_LOST with one completed admission/two RADIUS requests and confirmed
closure; neither resumed authorization on link return. The uncontrolled
NAS/backend path survived. Saved recreation started closed; a new explicit
exchange captured two Access-Requests and Challenge/Accept and restored
bidirectional traffic, then Logoff closed the gate. Existing expiry, denial,
reauthentication, worker-kill, teardown, drift and host-isolation checks passed.
Both selected jobs passed, including general CI; 58 others were intentionally
skipped. Local tests passed 998 cases in 30.643 seconds with 162 environment
skips; compilation, diff and documentation-link checks passed. No failed
native run preceded this result.

See [DOT1X_WIRED.md](DOT1X_WIRED.md). Persistent authenticators/supplicants,
stronger EAP/TLS, multi-client/dynamic VLAN/accounting and wider switching
remain open. LAN precedes native GUI; static VXLAN and separate EVPN/BGP/WAN
remain tracked. Planning estimates stay LAN about 80%, whole product 45–50%.

## Wired 802.1X verified backend session duration — 2026-11-06

Implementation `d71a8ba7c2e95fbfaa3040aab6c96db9b0aae185` and
correction `78b44e1acbac047a2aa5fe7cb1e6246e781b814f` add verified
RADIUS Session-Timeout enforcement to finite wired admission. EAP-enabled
backend users may declare a positive uint32 `session_timeout`; the managed
server emits the standard attribute. Only after authenticated Access-Accept
and EAP Success does the NAS grant `min(local seconds, server timeout)`.
Presence of the attribute ends the finite command after that admission,
discarding unused renewals. Results report effective/server seconds and
SERVER_SESSION_TIMEOUT or the earlier local LEASE_EXPIRED. Missing attributes
preserve existing finite reauthentication. Zero/duplicate/malformed durations
and unsupported or ambiguous Termination-Action are refused before admission.
PAP-only server user configuration rejects the new field.

The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42240831488/job/127970370968)
passed the extended real supplicant/FreeRADIUS scenario in 160.962 seconds at
`78b44e1`. Captured Access-Accept carried timeout 3; the kernel element used
3 seconds under a 30-second NAS bound, before and after cold restore. Each
command completed only one admission/two requests despite unused renewals.
SIGKILL still expired the shortened kernel lease. A 20-second backend limit
could not extend a 2-second NAS limit. A foreign 10-second element under that
2-second policy invalidated observation and refused save/new authentication.
Existing denial/reauthentication/carrier/expiry/Logoff/drift/teardown controls
and host namespace/link/IPv4/IPv6 route/rule invariants passed. Both selected
jobs passed; 58 others were intentionally skipped. Local full tests passed
1003 cases in 30.905 seconds with 162 environment skips; compile/diff/link
checks passed.

Initial run 42239853939 at `d71a8ba` failed the new native assertion expecting
3000 where nft JSON returned 3. Review of libnftables documentation/source
confirmed whole-second timeout/expiration output. Correction `78b44e1` fixes
both the test and pre-existing runtime inspection's milliseconds assumption,
checks strict integer bounds, and uses the actual set default when an element
omits its timeout. The new real oversized-element refusal verifies the runtime
repair. JSON whole-second precision does not certify fractional edits by an
external privileged writer; managed leases use explicit integer seconds.

See [DOT1X_WIRED.md](DOT1X_WIRED.md). Persistent authenticator/supplicant
service, stronger EAP/TLS, multi-client/dynamic VLAN/accounting and wider
switching remain open. LAN precedes native GUI; static VXLAN and separate
EVPN/BGP/WAN remain tracked. Planning estimates stay LAN about 80%, whole
product about 45–50%.

## Wired 802.1X bounded server-requested reauthentication — 2026-11-06

Implementation `9329910fd9fd4b61a4c6ad8ab4e6f01d0aa9e9aa` adds
verified Termination-Action=RADIUS-Request (1) to the finite wired EAP-MD5
profile. EAP-enabled backend users may declare `termination_action` 0/1
alongside required `session_timeout`. Action 1 permits fresh authentication
after the effective lease expires, within the existing local 0..3 renewal
budget only. Each old gate closes before a fresh EAP exchange; request/State
and per-exchange policy reset, with identity pinned. Action 0/default keeps
one admission when Session-Timeout is present. Missing duration with action 1,
unsupported values and malformed/duplicate policy attributes refuse admission.
The result also reports `server_termination_action`; there is no grace lease,
implicit worker restart or fallback to a previous success.

The [dedicated wired native job](https://github.com/sou1915/Network-LABS/actions/runs/42243831204/job/127980741652)
passed the full extended scenario in 196.309 seconds. Real wpa_supplicant and
FreeRADIUS produced two MD5/Success cycles and exactly four Access-Requests
with four distinct request authenticators and two fresh State values. Both
Accepts carried Session-Timeout 3 and Termination-Action 1 under a 30-second
NAS ceiling and local budget 1. Second-lease bidirectional data worked; budget
exhaustion completed closed after two admissions. Backend loss after the first
grant returned unknown/AUTH_TIMEOUT with one admission, three requests,
historical authenticated=true and confirmed closure. Saved recreation started
closed, retained both policy fields/budget and completed two healthy admissions
with four requests. Previous duration/SIGKILL/carrier/denial/reauthentication/
drift/teardown controls and host namespace/link/IPv4/IPv6 route/rule invariants
passed. Both selected jobs passed; 58 others were intentionally skipped.
Local full tests passed 1006 cases in 30.862 seconds with 162 environment
skips; compile/diff/link checks passed. Unit coverage includes budgets 0/1/3,
fresh State/closed transitions, backend outage/rejection and identity changes.
No failed native run preceded this increment.

See [DOT1X_WIRED.md](DOT1X_WIRED.md). Persistent authenticator/supplicant
service, stronger EAP/TLS, multi-client/dynamic VLAN/accounting and wider
switching remain open. LAN precedes native GUI; static VXLAN and separate
EVPN/BGP/WAN stay tracked. Planning estimates remain LAN about 80%, whole
product about 45–50%.

## Wired 802.1X engine-owned supplicant peer — 2026-11-06

Implementation `f4ebb509df3d901ec3265b1665287a852d1783ab` adds an
optional `dot1x_supplicant` policy to the existing wired PC1 peer. A trusted
foreground host wpa_supplicant runs in that peer's namespace across finite
NAS commands. The schema pins identity/interface and a private password-file
hash; preflight rejects invalid assets before allocation. Configuration is
passed through a sealed mode-0600 memfd, with no secret in argv, runtime peer
files or startup JSON. Inspection checks owned process, namespace/interface,
control readiness and original handoff/asset pins; save refuses dead or
unverifiable peers. Normal CLI hash redaction is added by `22a0844`.
Teardown stops the NAS first, then signals the owned peer group and confirms
peer process death before namespace removal. PID reuse/foreign groups do not authorize signalling.
Cold restore preserves policy only and starts a new peer with the gate closed.
The authenticator remains explicit/finite; there is no automatic peer restart
or persistent NAS authentication service.

At final validation commit `ff4b08a7d96d62ce81dfe027ef1383b57b58a704`,
the [dedicated wired job](https://github.com/sou1915/Network-LABS/actions/runs/42253373302/job/128014020814)
passed the new managed-peer scenario in 45.443 seconds and the existing full
authenticator scenario in 193.528 seconds. The new reference verified two real
EAPOL Success/four RADIUS requests, data in both directions, active save,
a second CLI auth reusing the same peer, peer SIGKILL followed by closed
authentication timeout/save refusal, changed-asset refusal before allocation,
cold restore, separate-CLI teardown during admission and actual wrong-password
rejection while the peer stayed running. Host namespace/link/IPv4/IPv6
route/rule invariants passed. Both selected jobs passed; 58 others were
intentionally skipped. Local full tests passed 1015 cases in 30.441 seconds
with 163 environment skips; compile/diff/link checks passed.

Initial run 42252777315 at `f4ebb50` passed both jobs (managed peer 44.769
seconds, old authenticator 219.613 seconds). Run 42253118016 at `22a0844`
passed general CI but failed the first admitted ping in the new fixture.
Fixture-only correction `ff4b08a` uses the existing reference's bounded data/
ARP readiness pattern: real traffic must succeed within two seconds and a
verified admitted lease, otherwise it fails. Duration, packet, credential and
cleanup assertions were retained; no admission/runtime policy was relaxed.

See [DOT1X_MANAGED_PEER.md](DOT1X_MANAGED_PEER.md). Persistent NAS supervision,
automatic peer recovery, stronger EAP/TLS, multi-client/dynamic VLAN/accounting
and wider switching remain open. LAN precedes native GUI; static VXLAN and
separate EVPN/BGP/WAN remain tracked. Planning estimates stay LAN about 80%,
whole product about 45–50%.

## Wired 802.1X guarded in-place peer recovery — 2026-11-06

Implementation `af6723cac8613278bfc921b191db58b8ac2bcd20` adds
`dot1x-peer-recover LAB PC1 --json` for explicit in-place recovery of a dead
recorded supplicant. It requires a stable running lab, no authenticator worker
and a verified closed NAS gate. Original namespace/interface/MAC, credential/
handoff and control directory/socket ownership identities must match. Live
peers, active auth, drift, foreign entries/replaced sockets and responsive
sockets without a matching owner are refused before replacement. Legacy
active state without the new startup ownership metadata requires recreation.
Only verified stale control objects are removed; namespaces, backend and
policy remain. Startup uses the same sealed private handoff and ends with
confirmed closure and authentication_required=true. Fresh explicit auth is
still required. A failed restart retains recovering-peer phase and any
recorded resources; auth/save refuse it until explicit stop/restore. Known dead
children are reaped without waiting for or signalling a live reused PID.

The [dedicated wired native job](https://github.com/sou1915/Network-LABS/actions/runs/42257561787/job/128028719091)
passed the extended managed-peer/recovery scenario in 56.219 seconds and
repeated the full independent-supplicant authenticator scenario in 193.355
seconds. Recovery refused a live peer, active auth, changed credentials and
a foreign regular file replacing the old socket, preserving records/files.
A separate CLI then replaced only the dead peer: its namespace identity,
all lab namespace names and the actual backend PID remained unchanged. The
gate stayed closed until a new finite authentication produced four fresh
RADIUS requests and bidirectional data; save retained the original manifest.
Existing peer death, wrong-password, cold restore, teardown and host namespace/
link/IPv4/IPv6 route/rule invariants passed. Both selected jobs passed; 58 others
were intentionally skipped. Local full tests passed 1024 cases in 30.440
seconds with 163 environment skips; the 17 focused peer cases, compile/diff/
link checks passed. Unit coverage includes failed-restart auth/save refusal,
missing clean-exit control paths and live reused-PID cache isolation. No failed
native run preceded this increment.

See [DOT1X_MANAGED_PEER.md](DOT1X_MANAGED_PEER.md). Recovery remains explicit;
automatic peer recovery/persistent NAS supervision, stronger EAP/TLS,
multi-client/dynamic VLAN/accounting and wider switching remain open. LAN
precedes native GUI; static VXLAN and separate EVPN/BGP/WAN remain tracked.
Planning estimates stay LAN about 80%, whole product about 45–50%.
