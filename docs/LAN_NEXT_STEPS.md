# LAN work order

Agreed order: complete the bounded AAA, IPv6 and switching profiles, polish
the other LAN services, then integrate the native engine into the GUI.
WAN work remains later. Each feature needs packet/service evidence and
failure/recovery coverage appropriate to its scope.

1. AAA: RADIUS-gated execution, then declared per-node access policy and
   login integration, role enforcement, accounting and 802.1X/EAP. TACACS+
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

This is an explicit operator-invoked authentication gate, not a persistent
device access policy: the operator selects the server and credentials for
each invocation. A verified Accept permits the selected fixed action;
returned RADIUS authorization attributes are not applied. All accepted
identities map to the same non-root UID. Existing admin exec, SSH and Telnet
paths are unchanged. No accounting packets, session or role model exist yet.
The lab lock remains held throughout authentication and execution.

Unit tests cover denied/unverified decisions, unknown actions and process
privileges. The managed FreeRADIUS native test also checks real execution,
UID, effective capabilities, no-new-privileges and denied-password behavior;
that opt-in test requires successful CI before claiming native validation.

Process configuration follows the
[OCI specification](https://github.com/opencontainers/runtime-spec/blob/main/config.md)
and [crun process option](https://github.com/containers/crun/blob/main/crun.1.md).
