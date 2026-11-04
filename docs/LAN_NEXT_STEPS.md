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
4. Services: broader DNS/file services, service coexistence, and HTTPS/Syslog certificate lifecycle/durable retry;
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
