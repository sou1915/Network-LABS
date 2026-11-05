# Project checkpoint and planning estimate — 2026-11-05

This assessment answers the user's request for what works, what remains and
an approximate percentage. It does not declare the LAN or project complete.
The agreed order remains bounded LAN work, native GUI integration, then the
tracked overlay/WAN stages. No existing roadmap item is moved past that order
by this report.

Current work is on `handoff/codex-dot1x-2026-11-04`; this checkpoint does not
claim it has been merged into the older prototype branch. Use the native
guides on this branch for the recent engine features.

## Validation checkpoint

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
  journal/reconciliation, finite wired EAP-MD5 admission/reauthentication.
- Existing educational desktop/web interfaces and the limited Wasm LAN
  backend. They remain distinct from the native engine's full integration.

## What remains

LAN work still includes native MSTP/PVST and broader switching/kernel fault
coverage; stronger/persistent 802.1X/EAP, multi-client/dynamic VLAN/accounting,
TACACS+/protected AAA; more dynamic/IPv6/security/service combinations; broader
file/DNS service features; Syslog queue retention across lab recreation and
broader durable delivery; and compatibility/resource acceptance. The detailed
coverage table distinguishes implemented subsets from these remaining options.

After the LAN gate, the native engine still needs complete desktop topology,
configuration, observations/capture and privilege-flow integration. Existing
educational forms are not already that integration. Manufacturer-inspired
pages/partial CLI dialects are not full vendor firmware.

Static VXLAN with explicit VTEP/VNI/VLAN mapping remains planned. EVPN/BGP is
separate. WAN/VPN is later. Optional Firecracker adapter detection/liveness
does not make full guest OSs or vendor appliances automatically available.

The 20-node [headless CI benchmark](benchmarks/enterprise-20-ci.json) is a short
idle/ICMP reference. It does not prove total application RAM, GUI/services
under load, all lab sizes, or the 2 GiB target on the user's 8-GB laptop.
That acceptance measurement remains open.

The next work should close explicitly selected LAN gaps and acceptance checks,
keeping new combinations scoped and independently proven before native GUI
integration. This inventory is a checkpoint, not permission to count planned
features as working.
