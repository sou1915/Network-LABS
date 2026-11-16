# Routed dual-stack SSH diagnostics with IPv4 RADIUS

This bounded profile runs Dropbear on explicitly declared IPv4 and IPv6
TCP/22 addresses, with the same SSH key gate and forced diagnostic policy on
both. A fresh verified RADIUS Access-Accept plus the local user/action allowlist
is required before each diagnostic runs as UID/GID 65532 with empty capabilities
and no-new-privileges. It does not authenticate the SSH handshake with a RADIUS
password: the SSH key authenticates transport access, then the forced command
reads separate RADIUS credentials over that encrypted connection.

The reference is PC1—R1—R2—PC2. PC1 is the managed SSH NAS; PC2 is a separate
FreeRADIUS service. Static IPv4/IPv6 routes and forwarding are independent.
RADIUS PAP remains IPv4 UDP/1812 and requires the existing authenticated
response/message checks. This is IPv6 SSH with an IPv4 AAA backend, not
RADIUS-over-IPv6, RadSec, mutual TLS, or device-wide vendor AAA.

Use a trusted BusyBox rootfs built with the existing Dropbear and FreeRADIUS
binary/module/dictionary options. The key must be OpenSSH ed25519 public data;
secret/password files follow the private-file rules in [NATIVE_RADIUS.md](NATIVE_RADIUS.md).

```bash
umask 077
python3 -m network_labs.appliances example --radius --radius-ssh --radius-dual-stack \
  --rootfs /absolute/rootfs --ssh-authorized-key /absolute/id_ed25519.pub \
  --radius-user learner --radius-password-file /absolute/password \
  --radius-secret-file /absolute/shared-secret > dual-stack-radius.json
sudo python3 -m network_labs.appliances start dual-stack-radius.json
sudo python3 -m network_labs.appliances verify dual-stack-radius-lan PC1 PC2 --family ipv4
sudo python3 -m network_labs.appliances verify dual-stack-radius-lan PC1 PC2 --family ipv6
```

From an explicitly connected lab client that has SSH routing to PC1, verify
its host key and run fixed `identity`, `hostname` or `security-context` commands
against either 192.0.2.10 or 2001:db8:10::10 as SSH user `lab`. Supply the RADIUS
username and password to the forced command. No host-side routable attachment
or external listener is created by this example. The dedicated native test
runs an independent OpenSSH client in the owned PC2 network namespace and uses
strict per-test known_hosts entries after observing the guest host key.

`management.ssh_ipv6:true` explicitly adds `[declared-static-ipv6]:22` to the
existing address-bound Dropbear command; omission retains IPv4-only arguments.
Startup waits for DAD before launching SSH. The option requires an UP numbered
single-interface OCI host, SSH keys, and a declared IPv6 address on eth0.
In IPv6 labs, the currently supported management composition additionally
requires a managed IPv4 RADIUS server, `ssh_radius:true`, a fixed `ssh_actions`
list and the matching `radius_access` policy. Ordinary unrestricted SSH,
Telnet, shell/accounting, syslog, dynamic IPv6, SVIs,
subinterfaces, RA Guard and firewall combinations remain excluded here.
Forwarding and other SSH bypass paths keep their existing restrictions.

Loss of IPv4 routing or the RADIUS daemon denies diagnostic execution even
when IPv6 SSH transport is healthy. Loss of IPv6 routing leaves IPv4 SSH and
IPv4 RADIUS usable. Wrong keys, wrong RADIUS passwords and locally unauthorized
actions never reach the diagnostic executor. No cached-accept fallback is added.
A live SSH session or listener alone does not prove successful AAA.

Managed policy files, private RADIUS config and both address families are
audited before save. Changes require recreation. Cold restore starts fresh
Dropbear and RADIUS processes plus a fresh owned supervisor token. Host keys,
SSH sessions and RADIUS decisions are not persisted. Verify host identity again
after recreation. This profile does not add durable accounting, richer roles,
802.1X/EAP, TACACS+ or protected RADIUS transport.

The native job verifies both SSH families, UID/capabilities, per-user positive
and negative controls, wrong keys/passwords, arbitrary-command denial, encrypted
SSH wire content, actual IPv4 RADIUS traffic, independent routing failures,
backend outage/recovery, policy drift refusal, cold restore, supervisor cleanup
and host network invariants. Results are recorded in LAN_NEXT_STEPS.md.

A later explicit [combined DNS/AAA profile](DUAL_STACK_SERVICES.md) permits
a separate DNS service node plus static NAS resolvers; other exclusions remain.
