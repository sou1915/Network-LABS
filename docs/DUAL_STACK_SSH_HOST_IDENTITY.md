# Pinned dual-stack SSH identity with an IPv4 RADIUS backend

The [routed dual-stack RADIUS diagnostic reference](DUAL_STACK_RADIUS.md)
now accepts the [explicit offline SSH host identity](SSH_HOST_IDENTITY.md).
One Dropbear process uses the same pinned ed25519 host key on
`192.0.2.10:22` and `[2001:db8:10::10]:22`. The client still needs a valid
SSH key, and each diagnostic still requires an authorized action and a
verified IPv4 RADIUS Accept from the separate backend at `198.51.100.20`.
RADIUS itself is not transported over IPv6 by this profile.

```bash
umask 077
python3 -m network_labs.appliances example --radius --radius-ssh \
  --radius-dual-stack --rootfs /path/to/radius-dropbear-rootfs \
  --radius-user learner --radius-password-file /path/to/password \
  --radius-secret-file /path/to/shared-secret \
  --ssh-authorized-key /path/to/client.pub --ssh-action identity \
  --ssh-host-key-file /path/to/server-host.key > pinned-dual-stack-ssh.json
sudo python3 -m network_labs.appliances start pinned-dual-stack-ssh.json
```

The host needs `dropbearkey`; the offline source remains a regular
non-symlink mode-0600 ed25519 private asset. Public identity/path references
are saved, not raw private bytes. Only the selected NAS receives its checked
private snapshot. Runtime conformity and offline restore prerequisites retain
their [existing scope](SSH_HOST_IDENTITY.md).

Provision strict known_hosts entries for both literal addresses from the
same declared public identity, using a trusted channel. The two entries
must remain unchanged across cold restore; no keyscan, family fallback or
automatic trust update is required. Follow the existing encrypted diagnostic
stdin credential protocol from [SSH_RADIUS.md](SSH_RADIUS.md). Trusting the
host key does not bypass client authentication or RADIUS authorization.

This is static routed dual-stack SSH diagnostics with an IPv4 AAA backend.
Pinned standalone IPv6 SSH, shell grants, accounting, Telnet, syslog, dynamic
addressing/routing, DNS coexistence and other managed-server co-location
remain refused. Existing unpinned DNS/AAA coexistence is a separate reference.
Protected RADIUS transport, SSH host certificates, automatic key lifecycle
and every role/topology combination remain separate work.

## Validation

The native scenario reuses the existing routed dual-stack RADIUS suite with
pinned host trust. It verifies both SSH families against pre-provisioned
known_hosts, wrong host trust/client keys, RADIUS credential/action denials,
actual IPv4/IPv6 SSH and IPv4 RADIUS packets, and no plaintext credentials on
TCP/22. IPv4 forwarding loss must deny diagnostics over still-reachable IPv6
SSH because its RADIUS backend becomes unreachable. IPv6 forwarding loss
must break IPv6 SSH while verified IPv4 diagnostics continue. Backend loss,
explicit recovery, drift refusal and cold restore with unchanged trust and
a fresh bridge token are checked, along with host namespace/link/route/rule/
forwarding/unprivileged-port invariants.

At implementation commit `8c776020e21b88d57a6cb3d7e4c2730216f36949`,
the [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42126484317/job/127591903712)
passed in 37.598 seconds. All four selected jobs passed: this scenario,
pinned IPv4 RADIUS SSH, the unpinned dual-stack RADIUS reference and general
CI. The other 54 jobs were intentionally skipped, not new native evidence.
Local full tests under umask 022 passed 980 cases in 30.981 seconds with
157 environment-dependent skips; compilation/diff/link checks passed.
No failed native run preceded this checkpoint.

Run with:
`gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=dual-stack-ssh-host-key`.
The selector also runs pinned IPv4 RADIUS SSH, the unpinned dual-stack RADIUS
reference and general CI; skipped jobs are not new proof.
