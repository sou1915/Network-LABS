# Project checkpoint and planning estimate — 2026-11-06

The current user priority is a bounded first LAN release: finish essentials,
defer advanced extensions, then integrate the native GUI. The frozen
[LAN core acceptance gate](LAN_CORE_ACCEPTANCE.md) now controls that transition.
It is accepted: **7/7 essential checks passed** on one source revision. Native
GUI integration is in progress: the first native lifecycle/observation/traffic
flow and basic graphical topology editing are verified. Work continues
toward the actual user-supplied mockup. The ten-node routed campus, generic
device artwork, VLAN groups, basic native device forms, rounded Inter UI and
interactive topology viewport are implemented. Rounded main panels and an
authenticated browser-based native draft manager now share the Tk settings.
Nine configuration modules now cover filtering/NAT, routing, switch VLAN/SVI,
802.1Q, IPv6, and client/server DHCP/DNS according to the node role.
[Per-node coverage and remaining commercial parity](NODE_MANAGEMENT_ROADMAP.md)
remain explicit; this is not a completed vendor firmware implementation. Richer forms, interactive native
consoles and packet views remain pending.
Older broad-catalogue percentages below
are historical planning estimates, not a completion counter for this gate.
No protocol/security assertion is relaxed by this scope decision.

Current work is on `handoff/codex-dot1x-2026-11-04`; this checkpoint does not
claim it has been merged into the older prototype branch. Use the native
guides on this branch for the recent engine features.

## Workspace polish

The reference-style workspace now has separated readable port captions,
clear active navigation/tool state, a useful search hint, balanced lower
panes, larger host labels and permanently visible interface Apply/Reload
buttons. Runtime counts remain explicit observations, not inferred connectivity.
The actual native campus and button visibility passed CI; the latest image
and source-bound evidence are in NATIVE_GUI_FLOW.md. This is visual/usability
polish; interactive native consoles and capture remain pending.

## Reference-colour campus workspace

The latest visual revision follows the supplied 1280×720 proportions with a
full-height catalogue, compact bars/navigation, brighter device/VLAN colours,
and a red/dark management panel with an actual interface table and form. The
default campus has ten real OCI nodes/nine cables, three routed VLANs, two
switches, a router, default-drop firewall and server endpoint. Native CI
verified inter-VLAN traffic and firewall blocking; the captured screenshot
shows this actual campus. Generic artwork does not add proprietary firmware,
Windows/Wi-Fi or server application support. See NATIVE_GUI_FLOW.md for proof.

## Visual alignment increment

The user's supplied image now drives compact menus/toolbar, an illustrated
categorized palette, role/VLAN placement, coloured declared access zones,
orthogonal cables and readable ping output beside real operation events.
Original generic device illustrations replace large flat cards; they are not
vendor models or firmware replicas. An explicit two-VLAN native fixture checks
both successful same-VLAN and failed cross-VLAN probes. Interactive consoles,
packet capture/views and richer supported device GUI remain pending. See
[NATIVE_GUI_FLOW.md](NATIVE_GUI_FLOW.md) for the actual captured implementation.

## Basic device form increment

A right-hand Configuration tab now edits generic OCI names, physical-port
IPv4, node-wide gateway and admin state through validated offline drafts.
Stale forms refuse Apply; renames with advanced references/scripts require
JSON instead of guessed rewrites. The native GUI scenario uses the form to
rename/address CLIENT3, observes its real default route and probes the new IP.
This is a generic project form; vendor firmware views and advanced forms are
not complete. See NATIVE_GUI_FLOW.md for current evidence and screenshot.

## Graphical topology editor

Generic OCI host/switch/router creation, free/new-port cable dialogs, cable/
device removal and session-only dragging now edit native JSON through atomic
native validation. They do not modify running networks; save and stop/start
apply the draft. The real five-device/four-link GUI scenario passes with
PC1 ↔ PC3 through two switches. Forms and click/drag behavior are covered by
Tk tests. See [GUI flow and current screenshot](NATIVE_GUI_FLOW.md) for proof.
Device photos, VLAN visual groups, supported per-device forms, interactive
consoles and packet-event views remain pending; the target mockup is not yet
fully implemented.

## GUI target and shell

The actual user-supplied target is
[agreed-gui-reference.jpg](images/agreed-gui-reference.jpg), superseding both
older desktop screenshots. The first shell increment adds searchable project
equipment and lower native-result/operation-event docks. The device panel's
controls remain visible at the tested laptop size. The real screenshot is in
[NATIVE_GUI_FLOW.md](NATIVE_GUI_FLOW.md). Device thumbnails, VLAN visual groups,
graphical editing, embedded forms/interactive consoles and packet-event
integration remain pending; visual parity has not been reached.

## Validation checkpoint

The agreed embedded desktop layout passed at
`a82b0571194f81759e29bf6e50d8e5b65dfd8664` in the
[desktop/native job](https://github.com/sou1915/Network-LABS/actions/runs/42276785462/job/128095032017).
Regression passed 1033 cases (47.945 s, 116 skips), and actual embedded Tk /
sudo / OCI start-status-inspect-verify-stop plus restored model workspace
passed in 4.466 s. The [current screenshot and proof](NATIVE_GUI_FLOW.md)
show this layout; full graphical editing/forms remain pending.

The [first native GUI flow](NATIVE_GUI_FLOW.md) passed at
`cad63774a58a9d51aa3b73bc28d90b932fb7fc86` in
[run 42267670327](https://github.com/sou1915/Network-LABS/actions/runs/42267670327).
A real unprivileged Tk session drove sudo/OCI start, status, kernel inspection,
bidirectional traffic and confirmed stop in 4.207 seconds. All six result files
were owned by UID 1001, root state remained directly unreadable, and a failed
status did not become success. A captured screenshot/report are retained.
General CI passed 1033 cases in 47.405 seconds with 116 skips; all ten selected
jobs passed, including the essential LAN gate. Local tests passed 1033 cases
with 166 skips. Full native topology editing/forms/console/capture integration
and real desktop/hardware acceptance remain open; this is one verified GUI
vertical slice, not full GUI completion.

The [LAN core aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42262198799/job/128047268789)
passed at `16bce142fe312dc654ee404d726971cf825f2935`: six core native
packet/service scenarios (166.885 s), switching, restricted SSH, RADIUS/shell/
accounting, finite wired/managed peer, 20-node headless reference and general
regression all passed. General CI ran 1024 cases in 48.339 seconds with 115
skips and passed executable guest smoke. All ten selected jobs passed; 52
other profiles were intentionally skipped. No runtime behavior/assertions
changed. See [LAN_CORE_ACCEPTANCE.md](LAN_CORE_ACCEPTANCE.md) for limits and
deferred extensions. This closes the first core LAN gate and enables GUI work;
it does not declare the broad catalogue or entire product complete.

The latest bounded increment adds [explicit in-place wired peer recovery](DOT1X_MANAGED_PEER.md)
at `af6723cac8613278bfc921b191db58b8ac2bcd20`. The
[native job](https://github.com/sou1915/Network-LABS/actions/runs/42257561787/job/128028719091)
passed the peer/recovery reference in 56.219 seconds and independent peer
regression in 193.355 seconds. It proved refusal/preservation for live, active,
credential-drift and foreign-socket cases, closed in-place replacement with
unchanged namespaces/backend PID, and fresh authentication/data afterward.
Both selected jobs passed; 58 were intentionally skipped. Local tests passed
1024 cases in 30.440 seconds with 163 environment skips. Failed-restart state
and reused-PID cache isolation have focused coverage. No failed native run
preceded this increment. Recovery remains explicit; planning estimates are
unchanged.

The latest bounded increment adds an [engine-owned wired supplicant peer](DOT1X_MANAGED_PEER.md)
at `f4ebb509df3d901ec3265b1665287a852d1783ab`, with normal-CLI pin
redaction `22a0844` and final native fixture correction `ff4b08a`.
The [dedicated job](https://github.com/sou1915/Network-LABS/actions/runs/42253373302/job/128014020814)
passed the managed-peer scenario in 45.443 seconds and old authenticator
regression in 193.528 seconds. Both selected jobs passed; 58 were intentionally
skipped. Local tests passed 1015 cases in 30.441 seconds with 163 environment
skips. An intermediate native first-ping failure was repaired with bounded
verified-lease data readiness; the guide retains the exact attempt history.
The peer is now managed across commands, while NAS authentication remains
explicit/finite. Host-service/total-RAM acceptance remains open; planning
estimates are unchanged.

The latest bounded increment adds [verified RADIUS-requested wired reauthentication](DOT1X_WIRED.md)
at `9329910fd9fd4b61a4c6ad8ab4e6f01d0aa9e9aa`. The
[native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42243831204/job/127980741652)
passed in 196.309 seconds: two actual MD5/Success cycles, four fresh requests,
verified duration/action attributes, closed budget exhaustion, backend-outage
refusal and healthy cold-restore recovery. Both selected jobs passed; 58 were
intentionally skipped. Local tests passed 1006 cases in 30.862 seconds with
162 environment skips. No failed native run preceded this increment. The
profile remains finite single-peer EAP-MD5; planning estimates are unchanged.

The latest bounded increment enforces [verified wired RADIUS Session-Timeout](DOT1X_WIRED.md)
at corrected commit `78b44e1acbac047a2aa5fe7cb1e6246e781b814f`.
The [native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42240831488/job/127970370968)
passed in 160.962 seconds: a backend limit shortened the kernel lease through
cold restore and worker SIGKILL, a longer backend limit could not extend the
NAS limit, and a real oversized element refused save/new authentication.
Both selected jobs passed; 58 were intentionally skipped. Local full tests
passed 1003 cases in 30.905 seconds with 162 environment skips. The first
native attempt failed its JSON milliseconds assumption; the corrected run
also repairs the pre-existing runtime unit/bounds check. See the guide for
whole-second precision and protocol limits. Planning estimates are unchanged.

The latest bounded increment adds [wired controlled-link revocation](DOT1X_WIRED.md)
at `73a3c56497d95b58dafd8998c598d8151fb0a0f7`. The extended
[native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42232715325/job/127942385678)
passed in 128.714 seconds, including sustained carrier loss, queued down/up,
closed link return, explicit authentication recovery after cold restore and
existing wired regression/host-isolation controls. Both selected jobs passed;
58 were intentionally skipped. Local tests passed 998 cases in 30.643 seconds
with 162 environment skips. No failed native run preceded this result. The
profile remains finite single-peer EAP-MD5; planning estimates are unchanged.

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

This strengthens existing validation; planning estimates remain unchanged.
See [SSH_SHELL_HOST_IDENTITY.md](SSH_SHELL_HOST_IDENTITY.md).

The latest validation strengthens [pinned SSH shell lifecycle evidence](SSH_SHELL_HOST_IDENTITY.md)
at `91997a938d33eb54b48428dca9db981abd455caa`. In
[run 42203206143](https://github.com/sou1915/Network-LABS/actions/runs/42203206143),
the new pinned PTY/expiry/disconnect/complete-accounting scenario passed in
7.773 seconds and orphan-journal controls passed again in 9.935 seconds.
All six selected jobs passed; 54 others were intentionally skipped. Local
tests passed 990 cases in 30.036 seconds with 161 environment skips. No
protocol behavior or scope changed; estimates remain unchanged.

The latest bounded increment adds a [pinned IPv4 journaled SSH shell](SSH_SHELL_HOST_IDENTITY.md)
at `9146031a8cddcb11a5987fa1d3a5ff02162f3fc9`, requiring accounting,
durable Stop outbox and session journal. Its native scenario passed in
10.636 seconds in [run 42173268692](https://github.com/sou1915/Network-LABS/actions/runs/42173268692),
including orphan cleanup/Stop delivery and unchanged host trust through cold
restore. All six selected jobs passed; 54 others were intentionally skipped.
Local tests passed
989 cases in 31.490 seconds with 160 environment skips. Wider AAA/LAN
acceptance scope remains open; planning estimates are unchanged.

The latest acceptance increment adds [kernel cgroup memory peaks](BENCHMARK_KERNEL_PEAK.md)
at `1ad4241d651fa3ebf6e70d3b10017aa028100712`. In
[run 42129277749](https://github.com/sou1915/Network-LABS/actions/runs/42129277749),
two new native scenarios passed in 29.601 seconds and the old enterprise
regression passed in 21.131 seconds. A real presampling transient exposed
the sampling blind spot; the fresh 20-node reference delivered all 1,200
requests with a 9.145 MiB kernel cgroup peak and no OOM kill. Both selected
jobs passed (including general CI); 57 others were intentionally skipped.
Exact artifact JSON/digest provenance is retained. Local tests passed 985
cases in 30.977 seconds with 159 environment skips. Total application/GUI/
heavy-service/laptop memory acceptance stays open; estimates are unchanged.

The latest bounded increment adds [pinned dual-stack SSH with IPv4 RADIUS](DUAL_STACK_SSH_HOST_IDENTITY.md)
at `8c776020e21b88d57a6cb3d7e4c2730216f36949`. Its dedicated native
scenario passed in 37.598 seconds in
[run 42126484317](https://github.com/sou1915/Network-LABS/actions/runs/42126484317),
including both-family trust checks, independent route loss and unchanged
known_hosts through cold restore. All four selected jobs passed; 54 other
jobs were intentionally skipped. Local full tests under umask 022 passed
980 cases in 30.981 seconds with 157 environment skips. Wider AAA/LAN
acceptance scope remains open; planning estimates are unchanged.

The latest bounded increment combines [pinned SSH identity and IPv4 RADIUS diagnostics](SSH_RADIUS_HOST_IDENTITY.md)
at `19c853f6c504d6f137d756aa64624aeb5c717aaf`. Its dedicated native
scenario passed in 5.793 seconds in
[run 42091389971](https://github.com/sou1915/Network-LABS/actions/runs/42091389971),
with strict host trust, independent client-key/RADIUS denials, outages and
unchanged trust through cold restore. All three native jobs passed in that
attempt, but general CI failed the new CLI fixture's inherited mode-0644
credentials under umask 022. The CLI correctly enforced its private-file rule.
Fixture-only repair `72ae65a79fb4c8eb8576997344c80201d000e2f1` creates
test credentials mode 0600 from creation, without relaxing checks/assertions.
[Replay 42125394285](https://github.com/sou1915/Network-LABS/actions/runs/42125394285)
passed all four selected jobs (new native scenario: 6.174 seconds); 53 other
jobs were intentionally skipped. Local tests under explicit umask 022 passed
976 cases in 30.301 seconds with 156 environment skips. Wider AAA/LAN
acceptance scope remains open; planning estimates are unchanged.

The latest bounded increment adds [explicit offline SSH host identity](SSH_HOST_IDENTITY.md)
at `1ac714da5e0e6dceef004e4fda98d3d9a9777340`. Its dedicated native
scenario passed in 2.703 seconds in
[run 42089486906](https://github.com/sou1915/Network-LABS/actions/runs/42089486906),
with unchanged strict client trust through cold restore and explicit identity
replacement controls. SSH access, RADIUS/SSH and general CI also passed:
four selected jobs succeeded; 52 other jobs were intentionally skipped.
Local tests passed 972 cases in 30.003 seconds with
155 environment skips. The estimates remain unchanged: wider AAA/lifecycle
and LAN acceptance scope is still open.

The latest bounded increment adds [separate IPv6 DNS and named HTTPS](IPV6_DNS_HTTPS.md)
at `05953899d1187f73a177e8e632704d5ab0cb6f90`. Its dedicated native
scenario passed in 15.027 seconds in
[run 42087775672](https://github.com/sou1915/Network-LABS/actions/runs/42087775672).
All five selected jobs passed, including baseline IPv6 HTTPS, tagged IPv6
DNS, dual-stack DNS and general CI; 50 other jobs were intentionally skipped.
Local tests passed 968 cases in
30.478 seconds with 154 environment skips. This closes one service
composition gap; planning estimates remain unchanged.

The latest validation strengthens the existing HTTPS/firewall profile with
same-interface, same-destination and same-port source denial before and after
cold restore, at `72b0732f90be9a93dd9075f42071486dae4b0e1a`.
The expanded scenario passed in 35.461 seconds in
[run 42086361238](https://github.com/sou1915/Network-LABS/actions/runs/42086361238).
All five selected jobs passed; 49 other jobs were intentionally skipped.
Four focused local policy/CLI tests and compilation/diff/link checks passed.
Protocol behavior and manifest scope are unchanged. This closes a validation
gap and leaves the planning estimates unchanged.

The latest bounded increment adds [IPv6 HTTPS behind a forwarding firewall](IPV6_HTTPS_FIREWALL.md)
at `8ce6321df0e06cee37bc5413478d7e20253288c3`. Its dedicated native
scenario passed in 22.128 seconds in
[run 42079365366](https://github.com/sou1915/Network-LABS/actions/runs/42079365366).
All five selected jobs passed, including baseline IPv6 HTTPS, standalone
IPv6 firewall, DNS/firewall and general CI; 49 other jobs were intentionally
skipped. Local tests passed 965 cases in 32.219 seconds with 153 environment
skips. This closes a bounded service/security combination, not the wider LAN
acceptance gate. Planning estimates remain unchanged.

The preceding increment adds [managed static IPv6 HTTPS](IPV6_HTTPS.md)
at `81ba8ba63e1b844142e670f75a27a55645ba4895`. Its dedicated native
scenario passed in 13.213 seconds in
[run 42073646773](https://github.com/sou1915/Network-LABS/actions/runs/42073646773),
alongside the existing IPv4 HTTPS, identity-lifecycle and general CI jobs.
All four selected jobs passed; 49 other jobs were intentionally skipped.
Local tests passed 962 cases in 30.469
seconds with 152 environment-dependent skips. The estimates below are
unchanged: this closes one bounded service gap rather than a whole phase.

The full workflow audit completed at code/documentation baseline
`f3146a0912fb77f59cd12bd3f20c87dc929d5f14`:
[run 42056055804](https://github.com/sou1915/Network-LABS/actions/runs/42056055804).
It finished with 50 successful jobs and two setup-cancelled jobs, not a
single 52/52 green attempt. The comprehensive native-container job passed
all 51 test cases in 1600.113 seconds. The dedicated wired 802.1X job passed
its native scenario in 112.327 seconds. Two jobs hit Ubuntu mirror
dependency-install timeouts before their native tests ran (jobs 127344638569
and 127344639438). Repair `c145a9e` changes only the two affected setup steps to a
CI-only helper using the official Ubuntu HTTPS archive and bounded APT retries/
timeouts. It adds a targeted `lan-readiness-retry` suite for those jobs and
general CI; no native assertions or protocol behavior are relaxed.
The [repaired replay, run 42059320195](https://github.com/sou1915/Network-LABS/actions/runs/42059320195),
passed all three selected jobs at `c145a9e0962178ab7ede0093f32b08d086d329aa`:
tagged IPv6 TFTP (one native scenario, 33.669 seconds), reverse STP/LACP
control loss (one native scenario, 165.158 seconds), and general CI.
The other 49 jobs were intentionally skipped in this targeted replay.
Together, the baseline audit and repaired replay provide passing evidence for
all 52 workflow job profiles. The original setup cancellations remain part of
the audit history; the replay changes CI setup and runtime scope wording,
not protocol behavior.
The strict-LACP job already completed
the positive STRICT_VERIFIED path on kernel 7.0.0-1017-azure with pinned
iproute2 7.1.0; its native scenario passed in 701.725 seconds.
Local tests passed 959 cases in 31.021 seconds with 151 environment-dependent
skips. Skips are not native proof. The read-only runtime plan tests also passed 13 cases (one environment skip)
after correcting its stale description of optional OVS RSTP; runtime protocol
behavior is unchanged. Exact supported profiles and evidence are in [LAN_PROTOCOL_COVERAGE.md](LAN_PROTOCOL_COVERAGE.md) and
[LAN_NEXT_STEPS.md](LAN_NEXT_STEPS.md).

## Requested percentages: explicit estimates

**Native LAN: about 80%, with a planning range of 75–85%.**
**Whole intended product: about 45–50%.**

These are engineering/planning estimates with assumed scope and weights,
not measured test coverage, protocol completeness, elapsed effort or an ETA.
There is no frozen exhaustive product backlog. The estimates must be revised
if that scope changes. A passing test/job percentage is a separate number.

For transparency, the LAN estimate uses ten equally weighted planning groups.
Ready means the named bounded reference is implemented and has dedicated
native evidence; it does not mean all vendor options work. Partial receives
half credit solely for this planning checklist:

| LAN planning group | Checkpoint state | Credit |
| --- | --- | --- |
| Owned native lifecycle/fabric and declarative persistence | Bounded references ready | 1 |
| Access/trunk/SVI and scoped STP/RSTP/LACP switching | Bounded references ready | 1 |
| Static IPv4/IPv6 and bounded OSPFv2/v3 routing | Bounded references ready | 1 |
| DHCP/RA/SLAAC/relay and bounded PD addressing | Bounded references ready | 1 |
| Core DNS/TFTP/NTP/SNMP service references | Bounded references ready | 1 |
| HTTPS/Syslog TLS identity and sender-process recovery | Bounded references ready | 1 |
| RADIUS access/accounting and finite wired admission | Bounded references ready | 1 |
| Broader service/security/dynamic coexistence matrix | Several references ready; gaps remain | 0.5 |
| Remaining advanced native LAN extensions | MSTP/PVST, stronger/persistent AAA and other backlog still open | 0 |
| Compatibility/resource/product acceptance | Native evidence and short benchmark exist; whole-app acceptance open | 0.5 |

This yields 8/10 planning credits. Group sizes are not equal engineering
effort, so the displayed estimate is approximate rather than a precise 80.00%.

For the whole product, an illustrative phase allocation is LAN 50%, native
GUI integration 25%, VXLAN/EVPN 10%, WAN 10%, release/performance acceptance 5%.
LAN earns roughly 80% of its allocation. The existing native manifest/runtime
panel is a small GUI integration pilot, approximately 20% of that allocation;
the working installable prototype earns approximately 20% of release acceptance.
Overlay/WAN work earns no completion credit here. The resulting roughly 46
planning points are reported as **45–50%**, not a precise measured percentage.
These weights are assumptions for this report, not an earlier delivery contract.

## What is working now

- Real Linux OCI nodes and packets, explicit CLI/lifecycle, managed config,
  save/cold restore, drift refusal, captures and bounded diagnostics.
- VLAN access/trunk, dot1Q/SVIs, common STP/LACP recovery and optional OVS RSTP;
  static IPv4/IPv6, OSPFv2/v3 and the two-link IPv6 DNS failover reference.
- DHCPv4 and selected DHCPv6/RA/relay/PD, real DNS A/AAAA, read-only TFTP,
  clockless NTP reference/relay, SNMP and scoped firewall/security profiles.
- Persistent fixed IPv4/separate static IPv6 HTTPS and Syslog TCP/TLS, explicit certificate/key/CA
  replacement, node-overlay sender queues and guarded dead-sender recovery.
- RADIUS authorization/roles, bounded SSH/Telnet sessions, accounting outbox/
  journal/reconciliation, finite wired EAP-MD5 admission/reauthentication
  with controlled-link revocation, verified backend session-duration caps and
  bounded server-requested reauthentication and an optional owned peer service
  with guarded in-place recovery.
- Native workbench topology, private manifest lifecycle, observed status/inspection
  and real connectivity verification through a sudo backend. Node/link editing
  and broader native forms remain pending.
- Existing educational desktop/web interfaces and the limited Wasm LAN
  backend. They remain distinct from the native engine's full integration.

## Deferred LAN extensions and next product work

The following catalogue extensions remain tracked beyond the frozen first core
release. They do not all block native GUI integration: native MSTP/PVST and broader switching/kernel fault
coverage; stronger EAP and persistent NAS authentication/peer recovery,
multi-client/dynamic VLAN/accounting,
TACACS+/protected AAA; more dynamic/IPv6/security/service combinations; broader
file/DNS service features; Syslog queue retention across lab recreation and
broader durable delivery; and compatibility/resource acceptance. The detailed
coverage table distinguishes implemented subsets from these remaining options.

After the seven-check LAN core gate, the native engine still needs complete desktop topology,
configuration, observations/capture and privilege-flow integration. Existing
educational forms are not already that integration. Manufacturer-inspired
pages/partial CLI dialects are not full vendor firmware.

Static VXLAN with explicit VTEP/VNI/VLAN mapping remains planned. EVPN/BGP is
separate. WAN/VPN is later. Optional Firecracker adapter detection/liveness
does not make full guest OSs or vendor appliances automatically available.

The historical [20-node sampled benchmark](benchmarks/enterprise-20-ci.json)
and newer [kernel-peak checkpoint](BENCHMARK_KERNEL_PEAK.md) are short
headless idle/ICMP references. They do not prove total application RAM, GUI/services
under load, all lab sizes, or the 2 GiB target on the user's 8-GB laptop.
That acceptance measurement remains open.

The next work should close explicitly selected LAN gaps and acceptance checks,
keeping new combinations scoped and independently proven before native GUI
integration. This inventory is a checkpoint, not permission to count planned
features as working.

The same source also passed all ten selected jobs in
[run 42276785462](https://github.com/sou1915/Network-LABS/actions/runs/42276785462),
including the [7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42276785462/job/128097531781).
The dedicated wired 802.1X job passed managed-peer recovery (55.167 s) and
independent-supplicant admission/revocation (219.122 s); 52 other profiles were
intentionally skipped. The superseded run 42276666855 was canceled after the
explicit desktop-entry correction, not used as final validation evidence.


All ten selected jobs on graphical-editor source c6e3a28 passed in
[run 42302077273](https://github.com/sou1915/Network-LABS/actions/runs/42302077273),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42302077273/job/128184138620).
The other 52 profiles were intentionally skipped. No native runtime or safety
assertion was weakened to support graphical editing.


All ten selected jobs on device-form source 13b6dcf passed in
[run 42303521155](https://github.com/sou1915/Network-LABS/actions/runs/42303521155),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42303521155/job/128189114015).
The other 52 profiles were intentionally skipped. No runtime behavior,
protocol assertion or privilege boundary was weakened for this GUI increment.


All ten selected jobs on final visual source 22e2206 passed in
[run 42307186227](https://github.com/sou1915/Network-LABS/actions/runs/42307186227),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42307186227/job/128201233579).
The other 52 profiles were intentionally skipped. The visual redesign changed
presentation and the GUI test fixture; native runtime/protocol behavior and
privilege boundaries remain unchanged.


All ten selected jobs on reference-campus source 9fcbd4a passed in
[run 42311053032](https://github.com/sou1915/Network-LABS/actions/runs/42311053032),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42311053032/job/128214033629).
The other 52 profiles were intentionally skipped. The GUI/campus template and
fixture changed; native runtime/protocol assertions and privilege boundaries
were not weakened.


All ten selected jobs on polish source f27f49f passed in
[run 42313340373](https://github.com/sou1915/Network-LABS/actions/runs/42313340373),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42313340373/job/128221582556).
The other 52 profiles were intentionally skipped. No native runtime/protocol
or privilege assertion was changed to support the visual/usability polish.


Final acceptance for GUI typography/interaction source 217be17: all ten selected
jobs passed in [run 42316748403](https://github.com/sou1915/Network-LABS/actions/runs/42316748403);
52 unrelated profiles were intentionally skipped. This includes dedicated
[wired 802.1X](https://github.com/sou1915/Network-LABS/actions/runs/42316748403/job/128231115458)
and the [7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42316748403/job/128233042144).
LAN core remains accepted; advanced LAN, native interactive consoles/capture
and static VXLAN retain their existing roadmap boundaries.


Final acceptance for native web source d0e6df1: all ten selected jobs passed in
[run 42342996553](https://github.com/sou1915/Network-LABS/actions/runs/42342996553);
52 unrelated profiles were intentionally skipped. Dedicated wired 802.1X
job 128314605913 passed; [LAN aggregate 128315692374](https://github.com/sou1915/Network-LABS/actions/runs/42342996553/job/128315692374)
confirms 7/7. LAN remains closed; VXLAN stays a later roadmap item.
