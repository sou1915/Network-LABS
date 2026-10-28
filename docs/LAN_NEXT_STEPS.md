# LAN work order

Agreed order: complete the bounded AAA, IPv6 and switching profiles, polish
the other LAN services, then integrate the native engine into the GUI.
WAN work remains later. Each feature needs packet/service evidence and
failure/recovery coverage appropriate to its scope.

1. AAA: RADIUS-gated execution and declared per-node action policy, then
   login integration, richer role enforcement, accounting and 802.1X/EAP. TACACS+
   and protected transports require their own implementations and validation.
2. IPv6: IPv6 SVIs/subinterfaces, OSPFv3, DHCPv6 relay/PD, firewall and RA Guard;
   validate coexistence with the existing IPv4 services.
3. Switching: physical/carrier failure coverage, remaining kernel validation,
   broader topology/security interactions and separately scoped MSTP/PVST.
4. Services: persistent HTTPS, Syslog TCP/TLS, broader DNS and file services;
   improve diagnostics, lifecycle, save/restore and documentation.
5. GUI: connect the native lifecycle, configuration and observations to the UI
   after the above profiles are ready.

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

Only single-interface OCI hosts are supported, with 1..16 users and the three
fixed actions. The RADIUS example declares its learner's permissions on PC1.
Existing manifests must add this field and recreate the lab to use
`radius-exec`; `radius-auth` remains an independent diagnostic without it.
The policy has no credentials and survives declarative save/restore. Updating
it requires editing the manifest and recreating the lab; no live policy editor
is implemented.

A locally allowed action still requires a verified Access-Accept. Returned
RADIUS authorization attributes are not applied. All accepted identities map
to the same non-root UID; the user/action allowlist is local authorization,
not a hierarchy of device roles. Existing admin exec, SSH and Telnet paths
are unchanged and are not protected by this policy. No accounting packets
or persistent session exist yet. The lab lock remains held throughout
authorization, authentication and execution.

Unit tests cover denied/unverified decisions, unknown actions and process
privileges. The managed FreeRADIUS native test also checks real execution,
UID, effective capabilities, no-new-privileges and denied-password behavior;
that opt-in test requires successful CI before claiming native validation.

Process configuration follows the
[OCI specification](https://github.com/opencontainers/runtime-spec/blob/main/config.md)
and [crun process option](https://github.com/containers/crun/blob/main/crun.1.md).
