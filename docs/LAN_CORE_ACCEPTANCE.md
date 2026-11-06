# LAN core acceptance — frozen 2026-11-06

The user explicitly prioritised essentials and faster LAN closure, deferring
optional detail/advanced extensions. This is the first bounded native LAN
release boundary. It replaces the open-ended requirement to implement the
entire LAN catalogue before GUI integration. Existing capabilities and their
limits remain documented; no runtime enforcement or test assertions change.

## Essential gate

The first LAN core is ready for native GUI integration when all seven checks
below pass on the same source revision. Until then it is an acceptance
candidate. Fix demonstrated blockers in these checks; do not add new protocols,
extra compositions or speculative refinements to this gate.

| Required CI check | Essential proof |
| --- | --- |
| `lan-core-acceptance` | Six existing native scenarios: static-route/return-path edits and rollback; inter-VLAN SVI/trunk gateways; routed DNS/HTTP failure/recovery/capture; DHCP-provided DNS over UDP/TCP; integrated multi-VLAN OSPF/DHCP isolation and recovery; independent IPv4/IPv6 forwarding/routes. Cold restore and host isolation remain asserted. |
| `switching-interop` | Real VLAN trunk edits/tags/pruning and common STP/LACP forwarding/restore. |
| `ssh-access` | Existing server-enforced SSH diagnostics, bypass denials and restored policy. |
| `radius-interop` | Real RADIUS allow/deny, managed backend, SSH diagnostics/shells, bounded accounting and cleanup. |
| `dot1x-wired-interop` | Existing finite wired admission, managed peer/recovery, denied access, actual EAPOL/RADIUS, expiry/failure/restore and owned teardown. |
| `benchmark-kernel-peak` | Existing 20-node headless traffic/resource reference, no OOM, actual HTTP/NAT/return paths and restore/cleanup. |
| `tests` | Existing general engine/CLI/desktop/Wasm regression and syntax checks. |

`lan-core-ready` depends on exactly these seven jobs and refuses failure,
cancellation, skipped or missing required results. It produces a visible
GitHub Actions summary. The six core packet scenarios reuse existing tests;
there is no duplicate test implementation or relaxed verification.

The existing manual selector is reused to keep its 25-choice compatibility:

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=lan-readiness-retry
```

It also retains its two historical tagged-TFTP/reverse-STP-LACP retry jobs.
Those are additional regression evidence, not new first-release requirements.
Push/PR and `suite=all` still schedule the whole workflow. Targeted acceptance
is not a claim that all catalogue profiles were rerun. This workflow now has
62 jobs: seven essential checks, the summary, two retained retry checks and
52 other profiles skipped by this targeted selection.

## Deferred extensions

These stay in the roadmap and do not block this first core gate:

- Persistent NAS supervision and automatic peer restart; stronger EAP/TLS,
  multi-client/dynamic VLAN/wired accounting, TACACS+/protected AAA.
- MSTP/PVST, gateway redundancy and larger/one-way/dynamic topology matrices.
- Additional DNS/file features, Syslog retention across recreation and broader
  IPv6/security/service combinations.
- Wider kernels/hardware, full application/GUI/host-service RAM certification,
  production/vendor parity and exhaustive performance/security coverage.

Credential privacy, fail-closed admission, denied traffic, real packet/service
verification, rollback, host isolation and owned cleanup remain essential.
EAP-MD5 is the existing educational bounded profile, not enterprise-grade
mutual authentication. No safety failure is deferred as cosmetic detail.

The resource gate measures a bounded headless reference; it does not certify
whole-product RAM or the user's laptop before GUI integration exists.
After the core gate closes, implement the native GUI lifecycle/configuration/
observations flow. Keep static VXLAN VTEP/VNI/VLAN mapping after LAN/GUI;
EVPN/BGP and WAN/VPN remain separate later stages.

## Candidate status

Native acceptance is pending. The old broad-catalogue estimate (about 80%)
and whole-product estimate (45–50%) are historical planning estimates, not a
percentage for this frozen gate. Report the seven actual check results and
remaining demonstrated blockers instead of inventing a new percentage.
