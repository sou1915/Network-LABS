# RADIUS-gated Telnet diagnostics

An explicit standalone `management.telnet_radius:true` runs BusyBox telnetd on
the NAS's declared IPv4 address, TCP/23. Each connection selects one fixed
diagnostic, supplies a RADIUS username/password, receives its output only after
a verified Access-Accept and successful non-root execution, then closes. The default profile has no shell or local-password fallback. An explicitly
enabled bounded shell is described below.

Telnet carries credentials and output in clear text on the isolated lab
network. Disabling terminal echo does not encrypt the connection. This profile
is for protocol labs; the existing RADIUS SSH profile provides an encrypted
transport separately.

## Build and start

Compile the trusted helper from the checkout, then package it with its ELF
libraries and matching FreeRADIUS assets. The include of `ssh_radius_relay.c`
shares bounded I/O and framing; no SSH server or SSH key is needed.

```bash
cc -O2 -Wall -Wextra -Werror network_labs/appliances/telnet_radius_login.c \
  -o /absolute/telnet-login
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --output /absolute/rootfs-telnet --telnet-login /absolute/telnet-login \
  --freeradius /usr/sbin/freeradius --freeradius-modules /usr/lib/freeradius \
  --freeradius-dictionaries /usr/share/freeradius
umask 077
python3 -m network_labs.appliances example --radius --radius-telnet --radius-roles \
  --rootfs /absolute/rootfs-telnet --radius-user learner \
  --radius-password-file /absolute/password \
  --radius-secret-file /absolute/shared-secret > telnet-radius.json
sudo python3 -m network_labs.appliances start telnet-radius.json
```

Use the installed matching module directory; some hosts use
`/usr/lib/x86_64-linux-gnu/freeradius`. Credential files follow the existing
private-file rules. The shared secret remains in the private host/managed
server configuration; it is not packaged into the Telnet login helper.

From a lab peer with a route to the NAS, connect using `telnet 192.0.2.10`.
Choose exactly `identity`, `hostname` or `security-context` at the action
prompt, then enter the RADIUS credentials. The username and password are not
echoed. Unknown action text is rejected without invoking a shell or parser.
A successful connection handles exactly one diagnostic, with at most 4096
output bytes; a new action requires a new connection and fresh authentication.

## Explicit authorization

The reference adds the following management policy to the existing RADIUS NAS:

```json
"management": {
  "interface": "eth0",
  "telnet_radius": true,
  "telnet_actions": ["identity", "hostname", "security-context"]
}
```

The NAS also needs `radius_access` and a uniquely matched, separate managed
RADIUS backend/client. Both `management.telnet_actions` and the user's local
[direct or role grants](RADIUS_ROLES.md) must allow the action. An empty node
list denies all actions. The backend may know a username that has no local
assignment; that user remains denied before any authentication request.

The first profile requires a single-interface OCI host and excludes SSH,
local Telnet password hashes, syslog forwarding, implicit shell/accounting grants,
IPv6. Combined service/security compositions are not validated by this increment.
Omission preserves existing local
password Telnet and SSH behavior. No change is made to ordinary admin exec or
raw `radius-auth` diagnostics.

## Privileges, bridge and lifecycle

BusyBox telnetd uses a declared no-new-privileges process with only binding,
PTY and UID/GID/capability-drop permissions. Its fixed compiled login helper
removes every bounding capability, clears supplementary groups, switches to
UID/GID 65532, clears all remaining capability sets and checks those properties
before reading action or credentials. If it cannot drop privilege, it exits
before prompting. Neither login metadata, environment USER nor `-f` arguments
authenticate a user. No `/bin/login` or local password account is used.

The helper connects only to protected NAS loopback TCP/814. A separate owned
host worker holds the backend secret and runs the existing RADIUS diagnostic
executor. Its PID/start time and generation token are tracked separately from
SSH's TCP/813 worker. Unprivileged guest processes cannot bind the low bridge
port, even after the host worker stops. Each runtime call refuses stale or
transitional generations. The worker processes requests sequentially and logs
only bounded outcome codes, never credentials or raw requests.

The action prompt has a 15-second deadline. Credential input and result delivery
share another 15-second helper budget. The host has its existing two-second
request-framing deadline, two-second RADIUS exchange and five-second fixed
execution bound. Unknown, rejected, malformed, unavailable or unverified results
do not produce diagnostic output; there is no automatic retry or local fallback.

`inspect LAB NAS` reports the management configuration and
`telnet_radius_worker_available` separately. File conformity does not establish
listener liveness or successful authentication. Lab stop terminates the owned
worker group before tearing down containers; save preserves only declarative
roles/management/backend policy. Saved recreation starts a fresh worker/token.
There is no live policy editor, RADIUS reply-role assignment, TLS wrapper,
vendor enable/configuration mode or per-command shell filtering.

The dedicated native test runs actual BusyBox Telnet plus FreeRADIUS. It inspects
the real helper before credential input, verifies UID/GID 65532 and empty
capability sets, exercises permitted diagnostics and distinct user/node ceilings,
proves local denials send no RADIUS packets with a capture positive control,
checks backend/worker outage without fallback, low-port impersonation refusal,
configuration drift, saved recreation and host isolation. Results are recorded
with the successful dedicated job and local test counts in LAN_NEXT_STEPS.md.


## Explicit bounded Telnet shell

Rebuild the compiled helper from this checkout and generate the example with
`--radius --radius-telnet --radius-telnet-shell`. Optional `--radius-roles`
assigns the explicit `session` role as well as diagnostic roles. To require
accounting, add `--radius-accounting`; optional `--radius-accounting-outbox
--radius-accounting-journal` uses the existing durable Stop queue and pre-Start
journal. Accounting options without a shell grant are refused. SSH, local
password fallback and dual-stack Telnet remain excluded.

Both `management.telnet_actions` and the user's resolved access grants must
include `shell`. The guest helper's separate `--shell-version` capability check
refuses old diagnostic-only binaries before the Telnet service starts. The
helper still drops all privileges before reading action or credentials. The
legacy diagnostic profile remains the default and can use its existing image.

Choose `shell` at the Telnet action prompt. After verified authentication and,
when enabled, a verified accounting Start receipt, the host opens an actual PTY
shell in the same owned session-cgroup supervisor used by CLI/SSH. The process
retains UID/GID 65532, no capabilities and no new privileges. Shell commands are
not individually filtered by roles; this is explicit unprivileged shell access.
The Telnet credential/reply phase stays bounded to 15 seconds. Once a verified
shell grant arrives, the guest relay has a 3615-second transport ceiling; the
host independently enforces `radius_access.session_seconds` (1..3600 seconds,
default 300). EOF, disconnect, expiry and ordinary exit all enter session cleanup.

The supervisor kills the owned subtree, including background tasks, confirms
empty population and only then records/sends Stop. If Start cannot be verified,
no shell is launched. Possible unconfirmed accounting sends remain conservative;
with an enabled outbox, failed Stop receipt keeps a durable intent for explicit
flush. The journal's empty checkpoint and Stop handoff use the existing private
store lock. Telnet worker SIGKILL recovery is not claimed by this normal-lifecycle
scenario and remains a separately tracked native crash case.

Unlike SSH, the Telnet protocol carries no remote process exit-status channel.
The helper consumes the host's framed final status internally and closes the
connection; shell output cannot forge that status. The shared supervisor sends
its final status only after cleanup/accounting. A client disconnect cannot
itself prove cleanup; inspect session groups and backend/queue evidence.

The dedicated native shell job checks actual Telnet PTY, privilege limits,
background cleanup after exit, expiry and disconnect, denied credentials/roles,
real accounting-response loss with no shell launch, retained Stop flush,
journal handoff and saved recreation. Its results are recorded in LAN_NEXT_STEPS.md.
