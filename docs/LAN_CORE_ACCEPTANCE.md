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

## Acceptance result — core gate closed

**LAN core is accepted for native GUI integration: 7/7 essential checks passed**
at `16bce142fe312dc654ee404d726971cf825f2935` in
[run 42262198799](https://github.com/sou1915/Network-LABS/actions/runs/42262198799).
The [aggregate gate](https://github.com/sou1915/Network-LABS/actions/runs/42262198799/job/128047268789)
reported `LAN_CORE_READY: all seven essential checks passed`.

| Essential check | Passing evidence |
| --- | --- |
| Core packet/service integration | [Six native scenarios, 166.885 s](https://github.com/sou1915/Network-LABS/actions/runs/42262198799/job/128044774347) |
| Switching | [Trunk 24.700 s; common STP/LACP 163.781 s](https://github.com/sou1915/Network-LABS/actions/runs/42262198799/job/128044776177) |
| Restricted SSH | [Passed](https://github.com/sou1915/Network-LABS/actions/runs/42262198799/job/128044776472) |
| RADIUS/SSH shell/accounting | [Passed](https://github.com/sou1915/Network-LABS/actions/runs/42262198799/job/128044776362) |
| Wired admission/managed peer | [Managed peer/recovery 55.518 s; authenticator 198.144 s](https://github.com/sou1915/Network-LABS/actions/runs/42262198799/job/128044776250) |
| 20-node headless reference | [Kernel peak cases 29.007 s; enterprise HTTP/NAT/restore 19.455 s](https://github.com/sou1915/Network-LABS/actions/runs/42262198799/job/128044774774) |
| General regression | [1024 cases in 48.339 s, 115 environment/opt-in skips; executable guest smoke passed](https://github.com/sou1915/Network-LABS/actions/runs/42262198799/job/128044776615) |

All ten selected jobs passed, including the summary and two retained historical
retry jobs. The other 52 profiles were intentionally skipped, not rerun or
counted as fresh native evidence. No failed native attempt preceded this
consolidated acceptance. Workflow YAML/dependencies/scenario names, local
all-success versus skipped-required gate behavior and documentation links were
checked. Runtime behavior and test assertions were unchanged.

The first LAN release boundary is now closed. Next work is native GUI
integration; deferred extensions above must not be added back as prerequisites
without an explicit scope change. The old broad-catalogue estimate (about 80%)
and whole-product estimate (45–50%) remain historical planning estimates, not a
percentage for this gate. This closure does not claim the entire LAN catalogue,
enterprise NAC, all combinations or whole-product/laptop RAM certification.

## GUI follow-up — 2026-11-06

The same seven essential checks passed again at GUI implementation
`cad63774a58a9d51aa3b73bc28d90b932fb7fc86` in
[run 42267670327](https://github.com/sou1915/Network-LABS/actions/runs/42267670327).
All ten selected jobs passed; 52 were skipped. General CI additionally verified
the [first actual GUI/native flow](NATIVE_GUI_FLOW.md) with an unprivileged Tk
client, sudo backend and real OCI traffic. The LAN scope remains frozen;
GUI essentials are the active phase.
