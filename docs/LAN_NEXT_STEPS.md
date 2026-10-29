# LAN work order

Agreed order: complete the bounded AAA, IPv6 and switching profiles, polish
the other LAN services, then integrate the native engine into the GUI.
WAN work remains later. Each feature needs packet/service evidence and
failure/recovery coverage appropriate to its scope.

1. AAA: RADIUS-gated execution and declared per-node action policy, then
   Interactive SSH/Telnet login integration, richer role enforcement, durable accounting/retry and 802.1X/EAP. TACACS+
   and protected transports require their own implementations and validation.
2. IPv6: IPv6 SVIs/subinterfaces, OSPFv3, DHCPv6 relay/PD, firewall and RA Guard;
   validate coexistence with the existing IPv4 services.
3. Switching: physical/carrier failure coverage, remaining kernel validation,
   broader topology/security interactions and separately scoped MSTP/PVST.
4. Services: persistent HTTPS, Syslog TCP/TLS, broader DNS and file services;
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

Next: IPv6 firewall, RA Guard and supported service coexistence. Dynamic
routing/services over router subinterfaces remain outside the static profile. The broader AAA and switching/service gaps above
remain tracked; these bounded increments do not complete the entire LAN.

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
