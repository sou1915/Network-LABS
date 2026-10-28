# RADIUS-authenticated local CLI login

`radius-login` opens a BusyBox shell inside the selected OCI host after both
local authorization and a verified RADIUS Access-Accept. It is a local native
CLI entry point. It does not install SSH/Telnet authentication or change the
existing administrative `exec` path.

The source node's `radius_access` policy must explicitly grant `shell` to the
RADIUS username and declare the same server address supplied to the command:

```json
"radius_access": {
  "server": "192.0.2.20",
  "session_seconds": 300,
  "users": {"learner": ["identity", "shell"]}
}
```

`shell` permits arbitrary commands under the session's non-root Linux identity.
The diagnostic allowlist does not filter commands entered inside that shell.
Without `shell`, even an authenticated diagnostic user cannot log in.
`radius-exec` continues to accept only its three fixed diagnostic actions.

For the managed reference lab, explicitly add `--radius-shell` to
`example --radius` with the existing username and private credential-file
options. Without this flag the example does not grant a shell. Recreate the
lab from the updated manifest; its policy persists through save/restore.

For an already running, appropriately configured `radius-lan`:

```bash
sudo python3 -m network_labs.appliances radius-login radius-lan PC1 192.0.2.20 \
  --username learner --password-file ./radius-password.txt \
  --secret-file ./radius-secret.txt
```

Credential files follow the private regular-file rules in
[RADIUS authentication](NATIVE_RADIUS.md). A denied local policy, rejected
password, Challenge, timeout or invalid reply never reaches the shell launcher.
There is no fallback account. Every new invocation authenticates again.

The CLI selects a terminal only when stdin and stdout are TTYs. `--no-tty`
accepts shell input from stdin without terminal allocation. Interactive sessions
end with `exit` or Ctrl-D. Shell input/output use the caller's terminal directly;
they are not included in a JSON report or stored by the login implementation.
The shell's nonzero exit returns a nonzero CLI status.

The OCI process runs as UID/GID 65532, without supplementary groups or Linux
capabilities, with `noNewPrivileges` and a minimal environment. It has no
RADIUS password or shared secret in its argv, environment or private temporary
process file. All allowed users currently share this Linux UID; they do not
have separate home directories or filesystem isolation from each other.

The node policy's `session_seconds` caps foreground session lifetime at
1..3600 seconds, default 300. `radius-login --seconds N` can shorten this
limit, but cannot extend it. Authentication's separate `--timeout` remains
1..5 seconds. Expiry returns CLI status 124; interruption returns 130 when
session cleanup completes. This is a total lifetime, not an inactivity timer.

Each session uses a generated cgroup-v2 child of its existing node cgroup.
The host verifies the subtree's kill interface before launch; the non-root
shell checks its own cgroup membership before reading user commands. There is
no uncontrolled fallback if the runtime ignores `--cgroup`. On normal exit,
expiry or handled Ctrl-C/SIGTERM interruption, the host kills only that session subtree, waits up to
two seconds for it to become empty and removes it, including background jobs.
A failed cleanup is `unknown` / `SESSION_CLEANUP_UNCONFIRMED`, not a successful
logout. Guest processes cannot write this root-owned cgroup hierarchy.

This profile requires writable cgroup v2, `cgroup.kill` and crun's `exec
--cgroup` support; unavailable session control prevents launching a shell.
The lifetime is enforced by the live CLI supervisor. A host CLI crash or
uncatchable SIGKILL cannot run cleanup; stopping the lab remains necessary in
that case. No automatic stale-session recovery is implemented. Signal handling
requires the main Python thread. This profile does not implement remote
revocation, an idle timer or RADIUS accounting.
As with existing administrative `exec`, the lab lock stays held throughout
the foreground session; close it before other native management commands.

The implementation follows the [kernel cgroup-v2 kill interface](https://docs.kernel.org/admin-guide/cgroup-v2.html)
and [crun sub-cgroup execution option](https://github.com/containers/crun/blob/main/crun.1.md).

The native FreeRADIUS test checks successful non-terminal and PTY sessions,
actual UID/capabilities/no-new-privileges, saved shell permission and denied
password behavior, plus background-job cleanup after logout, expiry and host interruption. The new session cases require successful native CI; local
unit tests alone do not establish OCI or terminal interoperability.
