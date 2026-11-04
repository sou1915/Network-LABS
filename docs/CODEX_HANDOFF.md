# Network-LABS: Codex handoff — 2026-11-04

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
