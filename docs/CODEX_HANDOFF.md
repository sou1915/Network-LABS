# Network-LABS: Codex handoff — 2026-11-04

## Latest LAN increment: pinned IPv4 journaled SSH shell — 2026-11-06

Implementation `9146031a8cddcb11a5987fa1d3a5ff02162f3fc9` permits the
explicit SSH host identity with an IPv4 RADIUS shell only when accounting,
durable Stop outbox and session journal are all selected. Generator flags
are `--radius --radius-ssh --radius-ssh-shell --radius-accounting
--radius-accounting-outbox --radius-accounting-journal --ssh-host-key-file`.
Client-key/RADIUS/action/Start gates remain unchanged. Diagnostics cannot
silently acquire shell grants; partial accounting, IPv6 pinned shells,
Telnet/syslog and NAS managed-server co-location remain refused. The suite
reuses `ssh-radius-host-key`; selector choices stay at 25.
See [SSH_SHELL_HOST_IDENTITY.md](SSH_SHELL_HOST_IDENTITY.md).

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42173268692/job/127745802977)
passed in 10.636 seconds. The real SSH journal reference ran with pinned,
pre-provisioned strict known_hosts and no keyscan. Wrong host trust created
no additional session intent. Live-owner cleanup refusal, supervisor SIGKILL
with orphan payload, nonempty-session refusal, explicit termination, durable
Stop handoff without network delivery, one explicit Stop transmission with
backend records, stale-runtime cleanup refusal and healthy acknowledged
completion passed. Cold restore kept the exact trust file and used a fresh
bridge token. Host namespace/link/IPv4/IPv6 route/rule invariants passed.
Native grants are direct-user; not every role/topology combination is claimed.

All six selected jobs passed in run 42173268692: pinned shell, old SSH
journal, pinned diagnostics, standalone pinned SSH, RADIUS/SSH and general CI.
The other 54 jobs were intentionally skipped. Local full tests under
umask 022 passed 989 cases in 31.490 seconds with 160 environment skips;
compilation/diff checks passed. No native failure preceded this result.
Continue LAN before native GUI; static VXLAN and separate EVPN/BGP/WAN
remain tracked. Estimates stay LAN about 80%, whole product about 45–50%.

## Latest LAN acceptance measurement: kernel memory peak — 2026-11-05

Implementation `1ad4241d651fa3ebf6e70d3b10017aa028100712` adds benchmark
report version 2 with optional kernel cgroup-v2 `memory.peak`, parent history
provenance, a fresh-parent current-run verdict and parent OOM events. Missing
support is null, corrupt/inaccessible counters fail, populated parents refuse
before allocation, and empty parents retain explicit prior-history scope.
No counters are reset. The post-load snapshot covers charged startup/load
memory, not all host work or total application RAM. Existing phase sampling
and historical v1 reports remain separate. See [BENCHMARK_KERNEL_PEAK.md](BENCHMARK_KERNEL_PEAK.md).

The [native job](https://github.com/sou1915/Network-LABS/actions/runs/42129277749/job/127601472273)
passed the real presampling transient and 20-node scenarios in 29.601 seconds,
then the existing enterprise HTTP/NAT/return-route/save-restore regression in
21.131 seconds. The 20-node fresh-parent kernel peak was 9,588,736 bytes
(9.145 MiB), with 10s idle and 10s ICMP from 12 clients, 100 requests each;
all 1,200 requests returned, all nodes stayed running and no OOM kill was
observed. The 12 MiB presampling allocation produced a 14.965 MiB kernel
peak while idle sampling saw only 2.098 MiB. Host invariants and stopped-node
cleanup passed. These remain headless cgroup references, not a whole-app,
GUI/heavy-service or laptop 2 GiB certification.

Both selected jobs (native benchmark and general CI) passed in run
42129277749; 57 other jobs were intentionally skipped. Exact artifact JSON
and source/digest provenance are committed under docs/benchmarks; ZIP SHA-256
matched GitHub metadata. Local full tests under umask 022 passed 985 cases in
30.977 seconds with 159 environment skips; compilation/diff/link checks passed.
No native failure preceded this checkpoint. Remaining LAN precedes native
GUI; static VXLAN and separate EVPN/BGP/WAN remain tracked. Planning estimates
stay LAN about 80%, whole product about 45–50%.

Workflow maintenance: the manual selector now has 25 choices. Reuse/group
selectors or adjust the input schema before adding another choice; preserve
the default all scope and unconditional push/PR selection of every job.

## Latest LAN increment: pinned dual-stack SSH with IPv4 RADIUS — 2026-11-05

Implementation `8c776020e21b88d57a6cb3d7e4c2730216f36949` permits the
explicit host identity in `--radius --radius-ssh --radius-dual-stack`
diagnostics. One Dropbear daemon uses the same key for both literal IPv4/IPv6
listeners. Pre-provisioned strict known_hosts keeps both entries unchanged
through cold restore. RADIUS stays IPv4 and still gates each diagnostic;
host trust does not bypass client-key authentication or RADIUS action policy.
Standalone IPv6 pinned SSH, shell/accounting, DNS coexistence, dynamic
addressing/routing and other NAS service co-location remain refused.
See [DUAL_STACK_SSH_HOST_IDENTITY.md](DUAL_STACK_SSH_HOST_IDENTITY.md).

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42126484317/job/127591903712)
passed in 37.598 seconds. Both SSH families verified the declared identity,
rejected wrong host trust/client keys and enforced RADIUS credential/action
denials. Real IPv4/IPv6 SSH and IPv4 RADIUS packets were captured without
plaintext credentials on TCP/22. IPv4 forwarding loss denied diagnostics on
still-reachable IPv6 SSH; IPv6 forwarding loss broke IPv6 SSH while IPv4
diagnostics continued. Backend loss/recovery, drift refusal, unchanged trust
after cold restore, a fresh bridge token and host invariants passed.

All four selected jobs in run 42126484317 passed: new scenario, pinned IPv4
RADIUS SSH, old unpinned dual-stack RADIUS and general CI. The other 54 jobs
were intentionally skipped. Local full tests under umask 022 passed 980 cases
in 30.981 seconds with 157 environment skips; compilation/diff/link checks
passed. No native failure preceded this checkpoint. Continue remaining LAN
before native GUI. Static VXLAN and separate EVPN/BGP/WAN remain tracked;
planning estimates stay LAN about 80%, whole product about 45–50%.

## Latest LAN increment: pinned SSH identity with RADIUS diagnostics — 2026-11-05

Implementation `19c853f6c504d6f137d756aa64624aeb5c717aaf` permits
`management.ssh_host_key` with explicit IPv4 `ssh_radius` diagnostics and
adds `--ssh-host-key-file` to the corresponding generator. Fixed diagnostics
remain behind client-key authentication and fresh RADIUS user/action checks.
Standalone pinned identity remains supported. Shell grants (including grants
not selected through SSH), accounting, Telnet, syslog, IPv6 and other server
co-location on the NAS remain refused. This is not RADIUS authentication
inside the SSH handshake. See [SSH_RADIUS_HOST_IDENTITY.md](SSH_RADIUS_HOST_IDENTITY.md).

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42091389971/job/127470040092)
passed in 5.793 seconds. It reuses the real SSH/FreeRADIUS reference with
pinned host identity enabled, pre-provisioned strict known_hosts and no
keyscan. Wrong host trust/client key, wrong/unknown RADIUS credentials,
per-user action denial, malformed credentials, shell/SCP/SFTP/injection,
backend outage, dead bridge and bridge impersonation controls passed.
Host-key unreadability and conformity passed; cold restore preserved the
exact trust file, used a fresh bridge token and restored authorized actions.
Host namespace/link/IPv4/IPv6 route/rule invariants passed. Native grants are
direct-user; reusable-role validation has local evidence, not every native
role/AAA combination. All three native jobs passed in that first attempt;
general CI failed a new CLI fixture because its credential files inherited
mode 0644 under umask 022 and the CLI correctly rejected them.

Fixture-only repair `72ae65a79fb4c8eb8576997344c80201d000e2f1` creates
those files mode 0600 from creation; protocol/runtime checks and assertions
are unchanged. [Replay 42125394285](https://github.com/sou1915/Network-LABS/actions/runs/42125394285)
passed all four selected jobs: pinned RADIUS SSH, standalone pinned SSH,
existing RADIUS/SSH and general CI; 53 other jobs intentionally skipped.
The new native scenario passed again in 6.174 seconds (job 127588151990).
Local full tests under explicit umask 022 passed 976 cases in 30.301 seconds
with 156 environment skips; compilation/diff/link checks passed. No native
scenario failed; retain the first general-CI fixture failure in the history.

Continue remaining LAN before native GUI. Static VXLAN and separate
EVPN/BGP/WAN remain tracked. Planning estimates remain LAN about 80%, whole
product about 45–50%; this bounded combination does not close the LAN gate.

## Latest LAN increment: explicit SSH host identity — 2026-11-05

Implementation `1ac714da5e0e6dceef004e4fda98d3d9a9777340` adds optional
`management.ssh_host_key` with absolute offline file reference and canonical
public ed25519 identity. The standalone restricted IPv4 SSH generator accepts
`--ssh-host-key-file`; it omits the usual syslog sender in this profile.
Host `dropbearkey` validates a mode-0600 bounded snapshot before allocation;
only the selected node receives the private snapshot in fresh `/run`, root
owned mode 0600. Dropbear uses explicit `-r`, with no `-R` fallback. Raw key
bytes never enter declarations/startup JSON, command arguments or persistent
command logs. Runtime conformity checks file type/mode/owner/hash. Source
assets must still conform at cold restore; they are referenced, not backed up.
RADIUS, Telnet, syslog, IPv6 and other server co-location remain refused for
this opt-in profile; existing ephemeral defaults remain unchanged.

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42089486906/job/127463481874)
passed in 2.703 seconds. Pre-provisioned strict known_hosts worked on the
first connection and unchanged after cold restore, without keyscan. Real SSH
verified restricted actions, uid-65532 key unreadability, no copies on other
nodes, runtime content/mode/symlink drift refusal and pre-allocation rejection
of missing/malformed/mismatched/symlink/mode-invalid assets. Explicit identity
replacement rejected old trust, worked after an explicit trust update and
cold-restored again. Host namespace/link/IPv4/IPv6 route/rule invariants passed.
Existing SSH access, RADIUS/SSH and general CI jobs also passed: all four
selected jobs succeeded; 52 other jobs were intentionally skipped.
Local tests passed 972 cases in 30.003 seconds with 155 environment skips;
compilation/diff checks passed. No native failure preceded this result.
See [SSH_HOST_IDENTITY.md](SSH_HOST_IDENTITY.md). Continue remaining LAN before
full native GUI; static VXLAN and separate EVPN/BGP/WAN remain tracked.
Planning estimates stay LAN about 80%, whole product about 45–50%.

## Latest LAN increment: separate IPv6 DNS and named HTTPS — 2026-11-05

Implementation `05953899d1187f73a177e8e632704d5ab0cb6f90` adds
`example --ipv6-dns-https --https-client-rootfs PATH`. Five static IPv6-only
nodes put DNS PC3 and HTTPS PC2 on distinct R2-facing networks behind two
routers. PC1 uses only the managed DNS resolver; AAAA resolves
`secure.lab.test` and TLS verifies the original DNS name against the supplied
CA. DNS/HTTPS co-location, external/service-node resolvers, combined firewall,
dynamic, dual-stack and logical-interface compositions remain refused.
Existing HTTPS/firewall and standalone DNS profiles remain separate.

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42087775672/job/127457432669)
passed in 15.027 seconds. UDP/TCP DNS plus named HTTPS, real DNS/TLS wire,
GET body, wrong CA/name and unknown-name controls passed. DNS outage broke
named HTTPS while literal verified TLS/the same HTTPS process stayed live;
HTTPS outage preserved DNS answers and its process. Explicit recovery,
resolver/DNS/HTTPS config drift refusal, exact declarative cold restore and
host invariants passed. Baseline IPv6 HTTPS, tagged IPv6 DNS, dual-stack DNS
and general CI also passed: five selected jobs succeeded; 50 other jobs were
intentionally skipped, not new proof. Local tests passed 968 cases in 30.478
seconds with 154 environment skips; compilation/diff checks passed. No
failed native run preceded this result. See [IPV6_DNS_HTTPS.md](IPV6_DNS_HTTPS.md).

Continue remaining LAN before full native GUI integration. Static VXLAN and
separate EVPN/BGP/WAN remain tracked; planning estimates stay LAN about 80%,
whole product about 45–50%, not measured coverage or an ETA.

## Latest LAN validation: same-port HTTPS source isolation — 2026-11-05

Test commit `72b0732f90be9a93dd9075f42071486dae4b0e1a` strengthens the
existing IPv6 HTTPS/firewall scenario without changing protocol behavior,
manifest scope or the example. A temporary alternate source `2001:db8:10::99`
uses the same interface, destination and TCP/443 as the authorized client.
Completed DAD, source-bound gateway reachability and the expected route prove
it can transmit. Its HTTPS connect times out, with actual ingress SYNs,
absent egress, and increasing default-drop counters. Authorized and direct
verified TLS remain successful, and the server PID stays unchanged. The
extra address is observed as drift and refuses save; it is removed before
successful save. The control passes again after cold restore. This is source
address filtering, not authenticated client identity or anti-spoofing.

The [expanded native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42086361238/job/127452432140)
passed in 35.461 seconds. All five selected jobs in run 42086361238 passed,
including baseline IPv6 HTTPS, standalone IPv6 firewall, DNS/firewall and
general CI. Other 49 jobs were intentionally skipped. Four focused local
policy/CLI tests, compilation/diff/link checks passed. No native failure
preceded this validation. See [IPV6_HTTPS_FIREWALL.md](IPV6_HTTPS_FIREWALL.md).
Planning estimates stay LAN about 80%, whole product about 45–50%.
Remaining LAN work still precedes full native GUI; static VXLAN and separate
EVPN/BGP/WAN remain tracked.

## Latest LAN increment: IPv6 HTTPS forwarding firewall — validated 2026-11-05

Implementation `8ce6321df0e06cee37bc5413478d7e20253288c3` adds
`example --ipv6-https-firewall --https-client-rootfs PATH`: PC1, a separate
default-deny FW1, and the existing managed IPv6 HTTPS PC2. Explicit rules
allow client-to-server TCP/443 and echo requests, with stateful returns.
HTTPS composition now permits one managed forwarding-only IPv6 firewall;
local-input, other service/security, dynamic, dual-stack and VLAN/SVI/logical
interface compositions remain refused. See [IPV6_HTTPS_FIREWALL.md](IPV6_HTTPS_FIREWALL.md).

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42079365366/job/127428042126)
passed in 22.128 seconds. Trusted TLS/GET, wrong CA rejection, positive
allow/state/default-drop counters, IPv6 conntrack and real two-interface
captures passed. A live TCP/8080 control was reachable on the server but
blocked across the firewall: ingress packets appeared without egress packets.
Routing/service outages had independent direct-TLS/echo controls; save
refused forwarding/ruleset drift. Exact declarations cold-restored with
working HTTPS. A stateless variant kept outbound TCP/443 and explicit echo
return but blocked remote TLS while direct TLS/echo worked; restoring the
stateful profile recovered service. Host invariants, including nftables,
passed. This is port-based forwarding, not TLS inspection or a production
PMTU/error-policy guarantee.

All five selected jobs in run 42079365366 passed: new scenario, baseline
IPv6 HTTPS, standalone IPv6 firewall, DNS/firewall and general CI. The other
49 jobs were intentionally skipped. Local tests passed 965 cases in 32.219
seconds with 153 environment-dependent skips; compilation/diff/link checks
passed. No native failure preceded this checkpoint. Planning estimates remain
approximately LAN 80% and whole product 45–50%. Continue LAN before full
native GUI integration; static VXLAN and separate EVPN/BGP/WAN stay tracked.

## Latest LAN increment: static IPv6 HTTPS — validated 2026-11-05

Implementation `81ba8ba63e1b844142e670f75a27a55645ba4895` adds
`example --ipv6-https --https-client-rootfs PATH`, one managed NGINX server
behind two static physical IPv6 routers. Explicit server `family: ipv6`
selects its numbered IPv6 eth0 address and `ipv6only=on`; existing IPv4
defaults remain unchanged. Other services/security, dual-stack, dynamic
addressing/routing, SVI/subinterfaces and multiple-server combinations remain
refused. See [IPV6_HTTPS.md](IPV6_HTTPS.md) for commands and boundaries.

Native run 42073646773/job 127407962710 passed in 13.213 seconds. It verified
real trusted TLS/GET/HEAD, wrong CA/name refusal, HTTP 404/405, IPv6-only
listener/wire, independent routing and service outages with local controls,
unchanged server PID through routing loss, drift refusal, explicit restart,
declarative cold restore and host invariants. Existing IPv4 HTTPS server and
identity-lifecycle jobs and general CI also passed. All four selected jobs
succeeded; 49 other jobs were intentionally skipped, not newly validated.

Local tests passed 962 cases in 30.469 seconds with 152 environment-dependent
skips after allowing the suite's existing loopback sockets. Compilation/diff
checks passed; no native failure preceded this checkpoint. LAN remains before
native GUI integration. Planning estimates remain approximately LAN 80% and
whole product 45–50%; one bounded profile does not justify a measured increase.
Static VXLAN, then separate EVPN/BGP and later WAN remain roadmap work.

## Current LAN readiness audit — completed 2026-11-05

The user requested continued work followed by a concrete progress percentage,
working-feature inventory and remaining work. Full suite run 42056055804 is
pinned to `f3146a0912fb77f59cd12bd3f20c87dc929d5f14`. It completed with
50 successful jobs and two setup-cancelled jobs. The comprehensive native
suite passed 51 test cases in 1600.113 seconds. The dedicated wired 802.1X
scenario passed in 112.327 seconds. Both cancellations were Ubuntu Azure mirror index-download
stalls before tests, not protocol assertions. Strict LACP completed positive
STRICT_VERIFIED on kernel 7.0.0-1017-azure/iproute2 7.1.0 in 701.725 seconds.

Repair `c145a9e0962178ab7ede0093f32b08d086d329aa` adds a CI-only bounded APT
helper using the official HTTPS Ubuntu archive for the two affected jobs,
a `lan-readiness-retry` selector and a correction to stale OVS RSTP scope text.
Targeted run 42059320195 retried those two native jobs plus general CI. Do not
claim one 52/52 green attempt: final evidence must distinguish the full baseline
and repaired retries. Protocol assertions were not changed.

The repaired replay completed successfully: all three selected jobs passed,
49 intentionally skipped. Tagged IPv6 TFTP passed its native scenario in
33.669 seconds; reverse STP/LACP control loss passed in 165.158 seconds.
Across the baseline and repaired replay, all 52 workflow job profiles now
have passing evidence; this is not one fully green original attempt.

PROJECT_STATUS.md records user-requested planning estimates: LAN about 80%
(75–85 range), overall about 45–50%, with explicit checklist/weight assumptions.
These are not measured test coverage, engineering effort or an ETA. The coverage
table and outdated guide cross-references have been refreshed. Local full tests
passed 959 cases in 31.021 seconds with 151 skips; read-only runtime-plan tests
passed 13 cases with one environment skip after the wording-only correction.
Keep LAN before GUI, with static VXLAN and separate EVPN/BGP/WAN still tracked.

## Latest LAN increment: costed OSPFv3 DNS failover validated — 2026-11-05

At implementation/validation commit
`8c2978f05f324662665e5e9a3dfa06c6f31555d3`,
`example --ipv6-dns-ospfv3-failover` adds two directly paired physical transits
between the same routers, with symmetric per-link and distinct path costs.
Single-link behavior remains available. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42055074653/job/127341141821)
passed in 51.123 seconds. Both Full adjacencies, preferred FIB selection,
carrier-up bidirectional primary blackhole with backup DNS/wire selection,
failback, total withdrawal with local live-DNS controls, backup-only recovery,
unchanged live daemon PIDs/declarations, drift refusal and fresh cold restore
with primary DNS/wire and baseline qdiscs passed. Single-transit DNS/OSPFv3,
standalone physical/SVI OSPFv3 and general CI also passed on that commit; 48
other jobs were intentionally skipped by manual selection.

Local tests passed 959 cases in 30.380 seconds with 151 environment-dependent
skips; compilation/diff checks passed. No failed native run preceded this
checkpoint. See IPV6_DNS_OSPFV3_FAILOVER.md and the final LAN_NEXT_STEPS
section for scope. External tc faults remain outside managed/save audit;
there is no zero-loss/fixed-time SLA, ECMP, larger graph or arbitrary physical/
one-way failure claim. Remaining LAN work precedes GUI; static VXLAN mapping
and later separate EVPN/BGP remain required roadmap work.

## Latest LAN increment: IPv6 DNS over OSPFv3 validated — 2026-11-05

At implementation/validation commit
`d320b987b0a75e84a2899a480e0dc7996e69398a`,
`example --ipv6-dns-ospfv3` adds one managed IPv6 DNS host behind exactly two
physical OSPFv3 routers, without router static routes. Active ports pair
directly; IDs differ, timers match, every numbered port participates and LAN
ports are passive. Clients use only the managed resolver. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42052137810/job/127330744403)
passed in 40.685 seconds. Full adjacencies, bidirectional BIRD kernel routes,
actual OSPFv3/DNS packets, AAAA/A-NODATA/NXDOMAIN, managed probes, independent
DNS-service versus learned-route loss, local live-DNS controls, reconvergence,
drift refusal, declarative cold restore and host invariants passed. Standalone
physical/SVI OSPFv3, tagged IPv6 DNS, dual-stack DNS and general CI also passed
on that commit; 46 other jobs were intentionally skipped by manual selection.

Local tests passed 956 cases in 31.056 seconds with 150 environment-dependent
skips; compilation/diff checks passed. No failed native run preceded this
checkpoint. See IPV6_DNS_OSPFV3.md and the final LAN_NEXT_STEPS section for
exact scope. Mixed/AAA, SVI/subinterface, firewall, other services and dynamic
addressing remain excluded. Remaining LAN work precedes GUI; static VXLAN
mapping and later separate EVPN/BGP remain required roadmap work.

## Latest LAN increment: guarded Syslog sender recovery validated — 2026-11-05

At implementation/validation commit
`c68850c3070aae41473771348d9fd91ec8fa265a`,
`syslog-forward-recover LAB NODE` explicitly starts a confirmed dead opted-in
disk-queue sender in its retained running node. It refreshes state under the
lab lock, requires config/TLS/spool conformity, reapplies optional offline peer
checks, uses bounded in-container process censuses and PID/inode comparisons,
and refuses live or ambiguous state. No signals, manual queue rewrite or
local-log replay. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42048879065/job/127319255687)
passed in 21.454 seconds. Both TCP and TLS verified live/missing-PID process
refusal, unrelated live PID refusal, malformed/symlink preservation, drift
refusal before cleanup, stale/absent PID recovery through separate CLI calls,
duplicate refusal, matching new PID/argv, same retained container, real queued
replay and TCP/TLS packets, continued delivery and cold-restore non-retention.
Original disk-queue, default TCP/TLS and general CI also passed on that commit;
45 other jobs were intentionally skipped by manual suite selection.

Local tests passed 952 cases in 30.346 seconds with 149 environment-dependent
skips; compilation/diff checks passed. No failed native run preceded this
checkpoint. See SYSLOG_FORWARD_RECOVERY.md and the final LAN_NEXT_STEPS
section for exact scope. Started is process evidence, not collector delivery.
No supervisor or cross-lab-stop queue retention is added. Remaining LAN work
precedes GUI; static VXLAN mapping and later separate EVPN/BGP remain required.

## Latest LAN increment: node-overlay Syslog disk queue validated — 2026-11-05

At implementation/validation commit
`5068997708973ea70b752982918ba92e127115ae`, optional
`--syslog-disk-queue` / `management.syslog_disk_queue:true` adds a private pure
disk action queue for TCP/TLS on the owned node overlay. Defaults remain
volatile; imported base-image spools are refused. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42045057015/job/127305646601)
passed in 21.711 seconds. Both transports verified real guest delivery,
fresh suspension, three on-disk markers, actual root-owned 0700 directory/
0600 files, exact PID/argv, sender SIGKILL/death, replay inside the same surviving
container without marker resubmission/local-log replay, actual TCP/TLS packets,
continued delivery, drift refusal and cold-restore non-retention. Default TCP
forwarding, default Syslog TLS and general CI also passed on that commit; 45
other jobs were intentionally skipped by manual selection.

Local tests passed 949 cases in 30.025 seconds with 148 environment-dependent
skips; compilation/diff checks passed. First native run 42044564699 / job
127303904974 failed because queue.fileCreateMode is unsupported in rsyslog
8.2312.0. The repair uses supported private umask 0077 and adds actual queue
file-mode checks; failed evidence is retained and recovery assertions remain.
See SYSLOG_DISK_QUEUE.md and the final LAN_NEXT_STEPS section for exact scope.
Only sender-process recovery is validated: lab stop/recreation removes the
spool, and host power-loss durability, broader durable retry/RELP, supervisors
and exactly-once delivery remain separate. Main/input/in-flight buffers stay
volatile and TLS spool data is plaintext at rest. Remaining LAN work precedes
GUI; static VXLAN mapping and separate later EVPN/BGP remain required.

## Latest LAN increment: Syslog TLS peer lifecycle validated — 2026-11-05

At implementation/validation commit
`9831449340f3f57571f8cf12cb946f22e12f9ed8`, opt-in
`--syslog-tls-preflight` / `verify_peer_on_start:true` on both declared peers
adds bounded offline mutual trust/time/role/exact-DNS-SAN checks before resource
allocation. Default live-failure labs remain available; distinct reciprocal
issuing CAs are supported. HTTPS shares the memory-BIO exchange helper.
The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42041335915/job/127292631585)
passed in 10.022 seconds. Pre-allocation role/time/trust/name refusal, stale
pins, actual guest logger and independent mutual-TLS storage, served collector
leaf fingerprints, both leaf/key replacements, CA replacement with old-trust/
old-client rejection, distinct issuers, cold restore, rollback, key isolation,
immutable base assets and host invariants passed. Original Syslog TLS, HTTPS
lifecycle, persistent HTTPS and general CI also passed on that commit; 43
unrelated jobs were intentionally skipped by manual suite selection.

Local tests passed 944 cases in 31.685 seconds with 147 environment-dependent
skips; compilation/diff checks passed. No failed native run preceded this
checkpoint. See SYSLOG_TLS_LIFECYCLE.md and the final LAN_NEXT_STEPS section
for scope and evidence. This is explicit offline replacement with downtime;
volatile logs/queues are not restored, and durable retry, automatic renewal,
live reload and revocation remain separate. Remaining LAN work precedes GUI;
static VXLAN VTEP/VNI/VLAN mapping and later separate EVPN/BGP remain required.

## Latest LAN increment: offline HTTPS identity lifecycle validated — 2026-11-05

At implementation/validation commit
`a0cac5c5a20cbe68647b0891a0ee7b077522ab8b`, HTTPS image build/startup adds
bounded memory-BIO validation of supplied local identity trust, current
host-clock validity and server purpose. No sockets, host trust roots or CA
fetching; name/IP verification remains the real client's task. Existing key
checks, pins and recreation policy remain intact. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42039875899/job/127287578185)
passed in 5.581 seconds. Expired/future/client-only/untrusted pre-allocation
refusal, live served-leaf DER fingerprints, leaf/key replacement under the
same CA, stale-pin refusal, CA replacement with old-trust rejection, cold
restore, explicit rollback, key isolation, immutable base identities and host
invariants passed. Original HTTPS and general CI also passed on that commit;
44 other jobs were intentionally skipped by manual suite selection.

Local tests passed 941 cases in 29.014 seconds with 146 environment-dependent
skips; compilation/diff checks passed. No failed native run preceded this
checkpoint. See HTTPS_IDENTITY_LIFECYCLE.md and the final LAN_NEXT_STEPS
section for usage/evidence/limits. This is explicit offline replacement with
downtime, not automatic renewal, revocation, live reload or Syslog lifecycle.
Remaining LAN work precedes GUI; static VXLAN VTEP/VNI/VLAN mapping and later
separate EVPN/BGP remain required roadmap work.

## Latest LAN increment: separate IPv6 DNS/TFTP validated — 2026-11-05

At implementation/validation commit
`4a8cb132a9640d92ef6e99d3a16d119b75bb07ce`,
`example --ipv6-dns-tftp` combines one managed IPv6 DNS server and one separate
read-only TFTP server across static ROAS VLANs and tagged transit. Clients use
only the declared managed resolver; TFTP retains explicit IP literals and adds
no automatic name resolution. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42037833110/job/127280504290)
passed in 32.381 seconds. Concurrent DNS/file observations, actual tagged
request/reply captures, separate listeners, AAAA/A-NODATA/NXDOMAIN, binary/hash
checks, independent service/route/VLAN failures with the other service healthy,
recovery, config drift refusal, cold restore and host invariants passed.
Standalone tagged DNS, tagged TFTP and general CI jobs also passed on that
commit; 42 unrelated jobs were intentionally skipped by suite selection.

Local confirmation passed 938 tests in 28.277 seconds with 145 environment-
dependent skips. The first local run had one timeout in the existing RADIUS
retry socket test; the unchanged seven-test retry module then passed in
1.514 seconds before that full confirming run. Compilation/diff checks passed.
No failed native run preceded this checkpoint. See IPV6_DNS_TFTP.md and the
final LAN_NEXT_STEPS section for exact bounds and selected regression results.
Remaining LAN work precedes GUI; static VXLAN VTEP/VNI/VLAN mapping and
separate later EVPN/BGP remain required roadmap work.

## Latest LAN increment: IPv6 TFTP over static dot1Q validated — 2026-11-05

At implementation/validation commit
`c8ad4031512625b9b6471f11aa202e028816a725`, the new
`example --ipv6-tftp-subinterfaces` supports one separate IPv6-only read-only
TFTP endpoint across static ROAS VLANs 10/20 and tagged transit 100.
The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42035723814/job/127273252102)
passed in 33.705 seconds. Actual tagged request/reply traffic, binary/hash
checks, clients on both routed VLANs, independent fault controls, recovery,
drift-save refusal, cold restore and host invariants passed. Physical IPv6
TFTP, IPv4 TFTP, static IPv6 subinterface and general CI jobs all passed on
that commit. Local tests passed 935 cases in 28.127 seconds with 144
environment-dependent skips. Compilation/diff checks passed; no failed native
run preceded this checkpoint.

See IPV6_TFTP_SUBINTERFACES.md and the final LAN_NEXT_STEPS section for exact
scope. Dynamic IPv6, SVIs, mixed/dual-stack, other services/security, writes,
authenticated/encrypted transfers and generic path MTU remain outside this
increment. Continue LAN before GUI; static VXLAN VTEP/VNI/VLAN mapping and
separate later EVPN/BGP remain required roadmap work.

## Latest LAN increment: managed IPv6 NTP relay validated — 2026-11-05

Commit `6db2e15853b357ab224012a47500cf17d1ea4888` adds
`example --ipv6-ntp-relay`: one managed stratum-10 local reference and one
clockless IPv6 relay serving stratum 11 with explicit client ACLs. Upstream
identity/ACL/graph bounds are validated, and acquisition binds the declared
relay address. Both daemons remain `-6 -x` without CAP_SYS_TIME. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42032733623/job/127262984424)
passed in 35.755 seconds. Standalone IPv6 NTP, IPv4 relay/client, IPv6 probe and
general CI jobs also passed on that commit. Local tests passed 932 cases with
143 environment-dependent skips. Wire/selected-source/ACL/capability evidence,
fresh-relay source-loss/no-local-fallback, recovery, drift, cold restore and
host invariants passed.

See IPV6_NTP_RELAY.md and the final LAN_NEXT_STEPS section for precise scope
and the retained first failed status-expectation fixture. Live relay holdover
is not bounded here; no immediate source-loss revocation or externally accurate
time is claimed. The user requested a visual explanation of this increment;
provide a service-flow diagram that distinguishes source, relay and client,
and explicitly notes no system clock adjustment. Continue LAN before GUI,
retaining static VXLAN and separate EVPN/BGP in the roadmap.

## Latest LAN increment: IPv6 local NTP reference validated — 2026-11-05

Commit `cdcd58c4213c5c7d495a017e8f2305d8b7cb54b8` adds explicit
`ntp_server.family:ipv6` and `example --ipv6-ntp` with a separate statically
bound chronyd local reference, /128 clients, `-6 -x`, no CAP_SYS_TIME and a
private read-only control path. IPv4 defaults/upstream/relay remain unchanged.
The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42030027136/job/127253825568)
passed in 16.291 seconds. IPv4 NTP relay/client, IPv6 probe and TFTP native
regressions plus general CI passed on that commit. Local tests passed 929 cases
with 142 environment-dependent skips. Real allowed/denied SNTP, exact UDP6/
PID/argv/live-capability evidence, independent routing-outage control, service
recovery, drift refusal, cold restore and host invariants passed.

See IPV6_NTP.md and the final LAN_NEXT_STEPS section for exact setup/evidence.
This is an isolated local reference, not accurate external time, NTS, an IPv6
upstream hierarchy, clock adjustment or broader dynamic/security combinations.
Continue remaining LAN before GUI, with static VXLAN and separate EVPN/BGP
still required on the roadmap. Older pending notes are historical.

## Latest LAN increment: IPv6 TFTP validated — 2026-11-05

Commit `cc2361876e6869e4e6674c721f027f3ba05b7891` adds explicit IPv6 TFTP
client/server family selection and `example --ipv6-tftp` over static physical
IPv6-only routing. IPv4 defaults remain unchanged. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42028445357/job/127248456722)
passed in 26.111 seconds; IPv4 TFTP/blksize, static IPv6 subinterface and general
CI jobs also passed on that commit. Local tests passed 925 cases with 141
environment-dependent skips. Native binary/64-KiB reads, negotiation, hash/error
checks, service/routing outage controls, drift refusal, cold restore and host
invariants passed. Local IPv6 socket coverage tests wrong TIDs and repeated
final ACKs.

See IPV6_TFTP.md and the final LAN_NEXT_STEPS section for exact scope and usage.
This is bounded unauthenticated read-only TFTP with no DNS/family fallback,
not generic file services, writes, encrypted/authenticated transfers or broader
service/security/dynamic combinations. Continue remaining LAN before GUI;
static VXLAN and later separate EVPN/BGP remain required. Older pending notes
are historical, not current blockers.

## Latest LAN increment: AAAA-only DNS zones validated

Commit `9306d24d57f90949947a76aa9cd9c81e5ae92c47` accepts an explicit empty
DNS A map when valid AAAA data exists. Empty zones, missing A maps and existing
invalid data remain refused; listener families and other composition limits
are unchanged. `example --ipv6-dns-aaaa` provides the IPv6-only tagged-routing
reference without manufactured IPv4 answers. See DNS_AAAA_ONLY.md.

Extended [dual-stack native DNS](https://github.com/sou1915/Network-LABS/actions/runs/41903234244/job/126831053927)
passed in 43.186 seconds; [IPv6-only subinterface DNS](https://github.com/sou1915/Network-LABS/actions/runs/41903234244/job/126831053243)
passed in 23.898 seconds. General CI passed on the same commit. Real AAAA and
A/NODATA across transports, NXDOMAIN, managed probe family separation, retained
empty A maps and cold restore passed, alongside the original scenarios. Local
tests passed 920 cases with 140 environment-dependent skips. Exact evidence is
in the final LAN_NEXT_STEPS section. No CNAME/DNSSEC/DNS64/recursion/dynamic
widening is claimed. Continue remaining LAN before GUI, retaining static VXLAN
and separate EVPN/BGP in the roadmap. Older pending sections are historical.

## Latest LAN increment: optional IPv6 local-input policy validated

Commit `bb4d071538ca6e9a43d8b81b38a2aa41921a41b1` adds
`example --ipv6-input-firewall` with separate opt-in `firewall_ipv6.input`.
Omission preserves forward-only behavior; loopback and bounded static NDP are
mandatory exceptions, and output is unfiltered. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41902272895/job/126827572558)
passed in 33.861 seconds. Existing forward-firewall and DNS/firewall native
jobs plus general CI also passed on that commit. Local tests passed 917 cases
with 140 environment-dependent skips. Local listener allow/deny, fresh NDP,
stateful versus stateless local replies with preserved forwarding, legacy
omission, drift refusal, cold restore and host invariants passed.

See IPV6_INPUT_FIREWALL.md and the final LAN_NEXT_STEPS section for exact
scope, the retained first failed fixture run and remaining work. This is a
static physical firewall profile, not generic host/output/dual-stack/dynamic/
subinterface/SVI security coverage. Continue LAN before GUI; static VXLAN and
separate EVPN/BGP remain required. Earlier pending sections are historical.

## Latest LAN increment: IPv6 DNS/firewall coexistence validated

Commit `9df4670e82f600005136741a58e0705f92a0691a` adds
`example --ipv6-dns-firewall`, an explicit static physical IPv6-only DNS service
behind the existing stateful forwarding firewall. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41893486552/job/126796720048)
passed in 21.408 seconds. Existing IPv6 firewall, DNS/subinterface and general
CI jobs all passed on that commit. Local tests passed 914 cases with 139
environment-dependent skips. Wire/counter/conntrack evidence, a proven blocked
HTTP listener, stateless DNS-return negative controls, outage isolation, drift,
cold restore and host nftables/network invariants passed.

See IPV6_DNS_FIREWALL.md and the final LAN_NEXT_STEPS section for usage, exact
scope and remaining work. This does not implement local-input filtering or
broader dynamic/dual-stack/subinterface security combinations. Continue LAN
before GUI and retain static VXLAN and later separate EVPN/BGP in the roadmap.
Older pending notes below are historical; preceding bounded profiles remain
validated within their documented scope.

## Latest LAN increment: IPv6-only DNS over subinterfaces validated

Commit `bb17f52207a33fc73887db4342775761214c747f` adds
`example --ipv6-dns-subinterfaces`: an explicit IPv6-only DNS endpoint across
static ROAS VLANs and tagged transit, with no mixed dual-stack, AAA or dynamic/
security widening. The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41890023350/job/126784651019)
passed in 17.131 seconds; existing dual-stack DNS, static IPv6 subinterface and
general CI jobs all passed on that commit. Local tests passed 910 cases with
138 environment-dependent skips. See the final LAN_NEXT_STEPS section and
IPV6_DNS_SUBINTERFACES.md for exact proof, failed fixture run, setup and limits.

This completes one IPv6 subinterface service composition. Continue remaining
LAN AAA/IPv6/switching/services before GUI; static VXLAN and separate EVPN/BGP
remain required on the roadmap. Wired finite reauthentication proof below
remains valid. Older pending sections are historical, not current blockers.

## Latest boundary result: maximum budget and renewed-lease crash validated

At test-only commit `d5fdba582c5c45e8972c8daee4d57758256a4beb`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41878259282/job/126743630911)
passed in **128.898 seconds**; general CI also passed on that commit. Four
real authentications, exactly eight RADIUS requests with fresh authenticators
and State, final-lease traffic, finite completion, and SIGKILL during the second
renewed lease with no subsequent admission/worker passed. Runtime code remains
the validated implementation below; this increment adds native boundary proof.

Earlier API reads returned queued snapshots. Final job timestamps/logs show
completion at 17:34 UTC, so those later queued observations were stale and must
not be interpreted as the actual queue duration. The pending sections below
are historical. See the final LAN_NEXT_STEPS section for exact evidence/limits.
Continue remaining LAN work before GUI, retaining static VXLAN and separate
EVPN/BGP in the roadmap.

## Latest result: finite reauthentication validated

At `b350281e625da65745725c726de57047cf88a02d`, the
[dedicated wired native job](https://github.com/sou1915/Network-LABS/actions/runs/41873926458/job/126728123068)
passed in **97.788 seconds**, and the general `tests` job passed on the same
commit. Local tests passed 906 cases with 137 environment-dependent skips.
The queued/pending sections below are historical and superseded by this result.
See the final LAN_NEXT_STEPS section for failed runs, atomic gate replacement,
bounded positive delivery checks and the exact scope. This is optional finite
closed-port reauthentication (0..3 extra exchanges), not a persistent service.
Continue remaining LAN work before GUI; static VXLAN and separate EVPN/BGP
remain tracked. No merge or full-LAN completion is claimed.

Repository: `sou1915/Network-LABS`.
Handoff branch: `handoff/codex-dot1x-2026-11-04`.
Last validated feature baseline: `feature/hybrid-appliance-runtime`, commit
`2f9fc98b9eb4247e6c6302eff6c33e2f08044887`.

## Goal and agreed order

Build a lightweight Linux desktop network lab simulator with Packet Tracer-like
usability and flexible native appliances, realistic observations/CLI, declarative
save/restore and later device GUIs. The user's laptop is an 8 GB Dell Latitude
5490; overall engine target is at most about 2 GB. Do not invent completion
percentages or claim all LAN/vendor behavior is implemented.

Complete bounded LAN AAA, IPv6, switching and service/security compositions,
then integrate the native engine into GUI. WAN follows later. VXLAN is required
and tracked: explicit static VTEP/VNI/VLAN mapping first; EVPN/BGP is separate.
Read `docs/LAN_NEXT_STEPS.md` for the sequence and previous native evidence.

## Validated baseline

The parent branch contains the prior IPv6/switching/service increments, local
AAA action/role policy, RADIUS SSH and Telnet bounded shells/accounting, durable
Stop outbox, explicit PID/boot/namespace/cgroup-pinned orphan reconciliation,
and native SIGKILL evidence for CLI/SSH/Telnet supervisors.

The latest completed EAP increment is a bounded two-request EAP-MD5/RADIUS
observation and opt-in FreeRADIUS backend with private hash-pinned password
assets. The successful implementation repair is
`34ddbaf9a06d6dc1f1d3dedd2d0b3f774dcef321`; native job:
https://github.com/sou1915/Network-LABS/actions/runs/41444614658/job/125274523414
It passed in 6.658 seconds. General CI/RADIUS also passed. The repair matters:
Cleartext-Password is a string; octet-style unquoted `0x` text was incorrect.
Managed EAP assets are printable ASCII, owned private 0600 files. Quoted literals
must disable expansion and preserve quotes/backslashes. Read
`docs/RADIUS_EAP_MD5.md` before modifying credential or protocol handling.

## Continuation result — 2026-11-04

The finite wired increment is now validated at
`4fafe9a02d69bc07fa8595a55bd6152ede252d05`. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41860209419/job/126679612230)
passed in 43.829 seconds; general CI also passed on that commit. Local tests
passed 901 cases with 137 environment-dependent skips. See the final wired
validation section in `LAN_NEXT_STEPS.md` for exact scope, failure history and
remaining LAN work. Save/stop/authentication now refresh state under the lock;
teardown confirms worker death after SIGKILL, and finalization handles a
concurrent separate-CLI stop without recreating runtime state.

The WIP and immediate-task sections below describe the original handoff
checkpoint and are retained as history. Their pending native result is
superseded by the evidence above. The bounded finite profile is complete;
broader LAN work still precedes GUI, with static VXLAN and later EVPN/BGP
separately tracked.

## Next LAN increment: finite reauthentication — native validation pending

Implementation `a6e20f9fdf164a0c832acb6d4998418ca23936b3` adds optional
`dot1x.reauthentications:0..3`. It closes the port before each new complete
EAP/RADIUS exchange, clears old transaction/State, pins the original accepted
identity and never reuses earlier success after outage/rejection. The omitted
policy keeps the validated single-lease behavior. This is finite foreground
reauthentication with closed intervals, not a persistent service.

Local checks passed 905 tests in 26.837 seconds with 137 environment-dependent
skips; compilation and diff checks passed. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41864390885/job/126694713007)
and its general CI job were still queued without runner allocation at the last
check. Do not treat this new extension as native validated or merge it on the
strength of the older single-lease proof. The added native scenario covers two
real supplicant cycles, fresh RADIUS transactions/State, second-lease traffic,
backend loss between leases and cold restore/recovery.

The active replacement is targeted dispatch run `41864390885` at CI commit
`952d15442c731170efa5ffcb4ca5c055b5a0230a`. Both selected jobs (native wired and
general tests) are queued without assigned runners; 35 unrelated jobs are
intentionally skipped for this manual run. Push/PR scope is unchanged. Use
`gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=dot1x`
for a later targeted rerun. See LAN_NEXT_STEPS.md for scheduling evidence.

GitHub Status now reports an official Actions/Pages incident (investigating,
2026-11-04 16:05 UTC): https://stspg.io/pjgptg3cfc6n . Actions was observed
`degraded_performance`; selected checks have no failure annotations. Keep the
targeted run pending rather than dispatching duplicate retries during the
incident. Local native execution lacks sudo/effective capabilities.

Next action: follow that job, fix any failure without weakening authentication
or gate checks, then record its exact successful commit/job/duration in the
final LAN_NEXT_STEPS section. Continue LAN before GUI and retain the static
VXLAN and separate EVPN/BGP roadmap. Earlier known-failed and redundant
documentation-only workflow runs were asked to cancel to release runner
capacity; the original successful runtime validation run was retained.

## Work in progress on this handoff branch

This is an unvalidated native feature checkpoint, not a completed 802.1X claim.
The existing changes implement a first finite single-port wired admission
experiment using actual EAPOL pass-through to the managed EAP-MD5 backend and a
Linux nftables gate. Native interoperability has not yet been run/reviewed for
this checkpoint. Do not merge it as validated until that test passes.

Key files:

- `network_labs/appliances/dot1x.py`: narrow three-node/one-peer topology,
  default-closed bridge gate, dynamic admission fingerprint checks, finite
  authenticator controller and owned worker teardown.
- `network_labs/appliances/dot1x_worker.py`: raw EAPOL/UDP RADIUS state machine,
  namespace/interface/generation checks, original identity allowlist, verified
  challenge/State/Success, kernel timeout admission and Logoff/expiry handling.
- `tests/test_dot1x.py`: scope, gate bounds, EAPOL envelope and ownership tests.
- `tests/test_native_dot1x_integration.py`: real wired `wpa_supplicant`, EAPOL and
  RADIUS captures, blocked/admitted/expired bidirectional data, wrong credentials,
  Logoff, worker SIGKILL expiry, backend outage, cold restore and drift refusal.
- `docs/DOT1X_WIRED.md`: intended usage, finite scope and limits.
- `.github/workflows/tests.yml`: new `dot1x-wired-interop` job.

Other edits wire the policy into validation, NAS-SVI RADIUS client binding,
gate installation while physical interfaces are DOWN, lifecycle/inspect/save,
`example --radius --radius-eap-md5 --dot1x`, and `dot1x-auth LAB NAS`.

The finite admission lease is 1..30 seconds (default 5), enforced by a kernel
set timeout. SIGKILL is not instant revocation: remaining admission lasts no
longer than that lease. There is no automatic persistent reauthentication,
managed supplicant lifecycle, TLS, wireless mode, dynamic VLAN, multi-client
port, MACsec or accounting in this first wired profile. The independent native
supplicant is a host process restricted to the peer's network namespace; its
password is in a private file, not argv.

## Immediate next task

1. Review the WIP diff against the validated baseline; read the files above.
2. Run local unit tests and syntax checks. The handoff preparation run passed
   896 cases in 27.333 seconds with 138 environment-dependent skips. Recheck
   after further code edits; this local result is not native gate proof.
3. Run/follow the dedicated GitHub Actions `dot1x-wired-interop` job. The local
   workspace does not provide the privileges needed to establish native proof.
   Do not count skipped tests as successful native interoperability.
4. Fix failures and complete the real wire/data-path/lifecycle scenario before
   adding broader features. Inspect actual nftables JSON expiry formats and
   wired supplicant behavior rather than weakening authentication/gate checks.
5. Review teardown especially carefully: `dot1x.stop()` should confirm death
   after its final SIGKILL before deleting namespaces, including when stop runs
   in a different CLI process. Retain identity checks and reject unowned groups.
6. Check malformed/replayed EAPOL, queued Logoff vs backend Success, worker
   crash, runtime generation changes and gate drift. Never touch a recreated
   namespace or interpret missing resources as authenticated/closed evidence.
7. Once the native test passes, record its exact commit/job/duration and limits
   in LAN_NEXT_STEPS.md, then continue the agreed LAN-before-GUI sequence.

Typical local checks:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q network_labs tests
git diff --check
```

Dedicated privileged test (only on a suitable isolated Linux runner):

```bash
sudo env NETWORK_LABS_NATIVE_TESTS=1 python3 -m unittest discover -s tests \
  -p test_native_dot1x_integration.py -v
```

Its workflow installs crun, iproute2, busybox-static, util-linux, nftables,
tcpdump, freeradius and wpasupplicant. Existing secrets/password assets are not
part of this handoff; tests create their own private disposable fixtures.

## Communication and working preferences

The user communicates mostly in Darija and repeatedly authorizes continuing
work in this repo. Give concise progress/evidence, not speculative percentages.
Do not ask repeatedly for already-authorized reversible repo work. Preserve
explicit boundaries, failed-run evidence and native validation limits. Root
native tests must remain isolated to owned lab namespaces/resources. Do not
remove existing tests or weaken checks just to obtain a green result.
