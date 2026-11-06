# Explicit SSH host identity across cold restore

The optional `management.ssh_host_key` declaration references an offline
Dropbear ed25519 private key and its exact OpenSSH public identity. Cold
restore reads that same conforming asset, so clients can reuse a known_hosts
entry provisioned before the first connection. The default remains an
ephemeral Dropbear host key; enabling this option does not change client
public-key authentication or restricted command authorization.

```bash
dropbearkey -t ed25519 -f /path/to/server-host.key
chmod 600 /path/to/server-host.key
python3 -m network_labs.appliances example --management \
  --rootfs /path/to/dropbear-rootfs \
  --ssh-authorized-key /path/to/client.pub --ssh-action identity \
  --ssh-host-key-file /path/to/server-host.key > pinned-ssh.json
sudo python3 -m network_labs.appliances start pinned-ssh.json
```

Build the rootfs with the existing `rootfs --dropbear` option. Install the
trusted `dropbearkey` host tool for generation, manifest generation and every
startup/preflight. On Ubuntu it comes from `dropbear-bin`. The client key and
server host key are distinct identities. The generator's pinned reference
enables standalone restricted IPv4 SSH and omits its usual syslog sender.

The manifest stores only `ssh_host_key.file` (absolute path) and
`ssh_host_key.public_key` (canonical public ed25519 key), never private bytes.
Provision known_hosts from that public identity through a trusted channel:

```text
192.0.2.20 ssh-ed25519 REPLACE_WITH_DECLARED_PUBLIC_KEY_BASE64
```

Use `StrictHostKeyChecking=yes` and that known_hosts file in the SSH client.
No keyscan or automatic trust acceptance is required by this profile.

The source must be a regular non-symlink mode-0600 file, 1..4096 bytes.
The host takes a bounded file-descriptor snapshot and derives its public
identity using `dropbearkey -y` on a temporary mode-0600 copy in a private
directory. Missing/malformed/mismatched assets fail before lab allocation.
The checked snapshot is copied only into the selected node's fresh `/run`
tmpfs, at `/run/network-labs-ssh-host.key`, with root ownership and mode 0600.
No private bytes enter command arguments, managed config/startup JSON or
persistent command logs. Dropbear uses explicit `-r`, with no `-R` fallback.
The authenticated uid-65532 client cannot read that private file.

Inspection/save check the runtime file's type, owner, mode and digest against
the checked startup snapshot. Content, mode or symlink drift refuses save.
Conformity is not a live host-key handshake; clients must verify the actual
SSH exchange. Runtime state holds a digest, not the private bytes. The source
asset must still be available and conforming at cold restore; save stores a
reference and does not back it up or freeze later external file edits.

Changing identity requires explicit manifest replacement and lab recreation.
An old known_hosts entry must reject the replacement. Updating client trust
is a separate explicit action. No automatic key rotation, key recovery,
encrypted/hardware keys, SSH host certificates or SSH CA service is added.
This bounded option requires restricted IPv4 SSH without Telnet, syslog or
other managed server co-location. A separate [pinned RADIUS diagnostic
profile](SSH_RADIUS_HOST_IDENTITY.md) also exists, including a separately
bounded [dual-stack diagnostic reference](DUAL_STACK_SSH_HOST_IDENTITY.md).
A separately bounded [IPv4 journaled shell](SSH_SHELL_HOST_IDENTITY.md)
requires accounting, Stop outbox and session journal. Wider AAA/IPv6
combinations remain separate work. Existing ephemeral SSH/RADIUS
defaults are unchanged.

## Validation

The dedicated native scenario uses real Dropbear/OpenSSH and pre-provisioned
known_hosts, reuses the exact trust file after cold restore, checks command
authorization and uid-65532 key unreadability, rejects runtime content/mode/
symlink drift, and rejects missing/malformed/mismatched/symlink/mode-invalid
offline assets before allocation. Explicit new identity must fail old trust,
succeed after an explicit trust update, and survive another cold restore.
Host namespaces/links/IPv4/IPv6 routes/rules are checked.

At implementation commit `1ac714da5e0e6dceef004e4fda98d3d9a9777340`, the
[dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42089486906/job/127463481874)
passed in 2.703 seconds. Existing SSH access and RADIUS/SSH regressions also
passed, together with general CI. All four selected jobs succeeded; the other
52 jobs were intentionally skipped. Local tests passed
972 cases in 30.003 seconds with 155 environment-dependent skips; compilation
and diff checks passed. No failed native run preceded this result.

The selector runs these native scenarios and general CI:
`gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ssh-host-key`.
