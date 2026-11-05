# Pinned SSH server identity with RADIUS diagnostics

The bounded IPv4 [SSH/RADIUS diagnostic profile](SSH_RADIUS.md) now accepts
the [explicit offline SSH host identity](SSH_HOST_IDENTITY.md) declaration.
These remain separate checks: the client verifies the server's public host
key, Dropbear authenticates the client's SSH key, then the requested fixed
diagnostic needs an authorized user/action and a verified RADIUS Accept.
This does not add RADIUS password authentication inside the SSH handshake.

```bash
python3 -m network_labs.appliances example --radius --radius-ssh \
  --rootfs /path/to/radius-dropbear-rootfs \
  --radius-user learner --radius-password-file /path/to/password \
  --radius-secret-file /path/to/shared-secret \
  --ssh-authorized-key /path/to/client.pub --ssh-action identity \
  --ssh-host-key-file /path/to/server-host.key > pinned-radius-ssh.json
sudo python3 -m network_labs.appliances start pinned-radius-ssh.json
```

Build the existing RADIUS/Dropbear image and provision the offline ed25519
host key as described in the linked guides. The host still needs
`dropbearkey` for manifest generation/preflight. This profile's NAS/SSH server
is PC1 at `192.0.2.10`; the separate RADIUS backend is PC2 at `192.0.2.20`.
Provision a known_hosts entry for `192.0.2.10` from the declared public key.
Use strict host checking and the existing diagnostic stdin credential protocol;
do not replace it with password arguments or automatic trust acceptance.

The source remains an offline mode-0600 asset. Only its path and public key
enter declarations; only the NAS gets its private snapshot in fresh `/run`.
The existing runtime mode/owner/type/hash checks and pre-allocation offline
asset checks apply. Cold restore requires the same conforming source and
starts a fresh bridge while preserving the declared server identity. It does
not restore live SSH sessions or credential state. Key/action/RADIUS failures
must deny diagnostics; host-key trust never bypasses RADIUS authorization.

This reference covers fixed IPv4 diagnostics. A separate
[dual-stack pinned reference](DUAL_STACK_SSH_HOST_IDENTITY.md) adds both SSH
families with the same IPv4 RADIUS backend. Direct-user and reusable-role
declarations are allowed, but shell grants (including grants not requested
through SSH), accounting, Telnet, syslog and other managed-server
co-location on the NAS remain refused. Wider shell/accounting/IPv6
compositions retain their separate scope. The native IPv4 increment
uses direct-user grants; it does not claim every role/AAA combination.
Protected RADIUS transport, automatic identity lifecycle and SSH host
certificates remain separate work.

## Validation

The new native scenario reuses the real FreeRADIUS/SSH reference suite with
the pinned identity enabled. It checks pre-provisioned strict known_hosts
without keyscan, deliberately wrong server trust, client-key rejection,
wrong/unknown RADIUS credentials, per-user action denial, malformed/incomplete
credential input, fixed actions/privileges, shell/SCP/SFTP/injection denial,
backend outage, dead bridge denial and protected bridge impersonation refusal.
Cold restore must preserve the exact trust file, create a fresh bridge token
and restore authorized diagnostics. Host namespace/link/IPv4/IPv6 route/rule
invariants and private host-key unreadability are checked.

At implementation commit `19c853f6c504d6f137d756aa64624aeb5c717aaf`,
the [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42091389971/job/127470040092)
passed in 5.793 seconds. All three selected native jobs passed, but general
CI failed the new CLI fixture: its password/secret files inherited mode 0644
under the runner's umask 022, and the CLI correctly refused them. Repair
`72ae65a79fb4c8eb8576997344c80201d000e2f1` creates those test files with
mode 0600 from creation, independent of umask. Protocol behavior, runtime
permission checks and assertions were not relaxed.

The [repaired replay](https://github.com/sou1915/Network-LABS/actions/runs/42125394285)
passed all four selected jobs at that repair commit; 53 other jobs were
intentionally skipped. The expanded native scenario passed again in
6.174 seconds ([job 127588151990](https://github.com/sou1915/Network-LABS/actions/runs/42125394285/job/127588151990)).
Standalone pinned SSH, existing RADIUS/SSH and general CI also passed.
Local tests under explicit umask 022 passed 976 cases in 30.301 seconds with
156 environment-dependent skips; compilation/diff/link checks passed.
No native scenario failed; the first general-CI fixture failure remains
part of the validation history.

Run with:
`gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ssh-radius-host-key`.
The selector also runs standalone pinned SSH, existing RADIUS/SSH and general
CI regressions; intentionally skipped jobs are not new proof.
