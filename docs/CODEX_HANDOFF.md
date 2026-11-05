# Network-LABS: Codex handoff — 2026-11-04

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
