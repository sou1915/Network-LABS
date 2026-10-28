# RADIUS-gated SSH diagnostics

This opt-in profile combines SSH public-key authentication with a fresh RADIUS
credential check for each fixed diagnostic. It supports `identity`, `hostname`
and `security-context`. It does not replace SSH's authentication handshake with
PAM/password authentication, enable interactive remote shells, integrate Telnet
or send shell-session accounting for these diagnostics.

Build the existing BusyBox rootfs with both trusted `--dropbear` and FreeRADIUS
assets; see [RADIUS setup](NATIVE_RADIUS.md) and the management rootfs options.
No guest Python, PAM module, compiler or extra guest executable is required.
The generator requires the explicit combined profile and private RADIUS files:

```bash
umask 077
python3 -m network_labs.appliances example --radius --radius-ssh \
  --rootfs /var/lib/network-labs/rootfs-radius-ssh \
  --ssh-authorized-key ./identity.pub \
  --radius-user learner --radius-password-file ./radius-password.txt \
  --radius-secret-file ./radius-secret.txt > radius-ssh.json
sudo python3 -m network_labs.appliances start radius-ssh.json
```

Use repeatable `--ssh-action` options to narrow the node-wide SSH allowlist.
The manifest sets `management.ssh_radius: true` together with explicit
`ssh_actions`, SSH keys and `radius_access`. A single-interface OCI host and
one managed RADIUS server containing its matching NAS client are required.
External RADIUS server secrets are not accepted by this bridge profile.

An SSH client on the lab network supplies two newline-terminated stdin lines:
RADIUS username, then password. Keep this local input file private (mode 600).
For example, a file with `learner` on its first line and the RADIUS password
on its second can be used as follows:

```bash
ssh -T -i ./identity lab@192.0.2.10 identity < ./ssh-radius-credentials.txt
```

The SSH client must run in a namespace connected to the internal lab fabric;
TCP/22 is not published on the host. Credentials are not command arguments or
environment variables. Usernames are bounded to 64 ASCII login characters;
passwords to 128 UTF-8 bytes without NUL/CR/LF. The client reads bounded fields
and has a 15-second overall deadline. Missing, invalid or rejected credentials,
unavailable RADIUS, unavailable supervisor or an unverified response deny the
request. Unknown commands, shell syntax, SCP/SFTP and PTY requests retain the
[restricted SSH policy](SSH_ACCESS_POLICY.md).

After the key check, the forced command forwards one bounded request to a
host Python supervisor in that node's network namespace. The supervisor keeps
the NAS shared secret outside the guest, checks both the SSH action list and
that RADIUS user's `radius_access` actions, verifies an Access-Accept using the
existing integrity-checked PAP client, then executes only the fixed diagnostic
with UID/GID 65532, empty capabilities and no-new-privileges. No arbitrary
client command is evaluated, and no shell is launched on approval. All accepted
RADIUS identities still share the same Linux UID; this is not per-user OS
isolation or a complete role hierarchy.

The internal bridge binds TCP/813 only on the node's loopback. Before binding,
it verifies the exact network namespace and sets that namespace's
`net.ipv4.ip_unprivileged_port_start` to 1024. This keeps an unprivileged guest
process from impersonating a stopped supervisor and collecting passwords.
It does not change the host namespace's port policy. Local guest callers still
need valid RADIUS credentials and authorization for any diagnostic; the bridge
itself is not an independent SSH key authentication service.

Requests have bounded framing and a two-second input deadline; the RADIUS
exchange uses two seconds with no retry. The bridge handles one request at a
time with a small listen backlog. Credentials are not cached, persisted or
logged; this does not promise cryptographic erasure of process memory. The
RADIUS wire transport remains the existing historical UDP/MD5 profile, not
RadSec. SSH encrypts the remote credential input; the internal loopback hop
assumes trusted lab administrators.

Each runtime call checks the current lab phase and supervisor generation.
Requests do not hold the lifecycle lock, allowing an SSH client inside an
existing node console to work; concurrent configuration/teardown may deny a
request. Stop terminates the owned supervisor process group before deleting
containers. Save/restore preserves declarative policy and starts a fresh
supervisor generation, not active sessions or cached authentication.
`inspect` reports worker process availability separately from file conformity;
neither is an authentication verdict.

The native CI scenario uses actual OpenSSH, Dropbear and FreeRADIUS packets:
correct/wrong credentials, per-user command denial, UTF-8/128-byte passwords,
wrong SSH key, command/subsystem denial, server/supervisor outages, low-port
impersonation refusal, saved restart and process cleanup. Interactive SSH
RADIUS login, richer roles and remote session supervision/accounting remain
later work.
