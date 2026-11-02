# Local roles for RADIUS-gated CLI and SSH

A node's `radius_access` can use reusable named roles instead of direct
user/action lists. Authorization stays on the host supervisor and precedes any
RADIUS request. The selected user must still receive a verified Access-Accept
for every allowed action or shell. A backend account alone grants no local
access. RADIUS reply attributes do not select roles or change grants.

```json
"radius_access": {
  "server": "192.0.2.20",
  "roles": {
    "observer": ["identity", "hostname"],
    "auditor": ["security-context"],
    "session": ["shell"]
  },
  "user_roles": {
    "reader": ["observer"],
    "reviewer": ["observer", "auditor"],
    "session-user": ["session"]
  },
  "session_seconds": 60
}
```

This excerpt belongs on the NAS OCI host. Declare the authenticating accounts
separately under the managed server's `radius_server.users`, with their password
digests. Backend authentication and the NAS role assignment are independent.
Unknown users, unknown roles and disallowed actions deny by default.

The actions for a user are the union of exactly its assigned roles. Roles do not
inherit from other roles, and their names carry no special authority. Each role
contains only the existing `identity`, `hostname`, `security-context` or `shell`
actions. There are at most 16 roles and 16 users per node, with 1..16 distinct
role names per user. Role names are 1..32 ASCII letters/digits/underscore/hyphen,
starting with a letter; existing ASCII username rules remain unchanged.

Choose either the existing `users: {name: [actions]}` form or both `roles` and
`user_roles`. Mixing the forms, empty grants, duplicate entries, missing role
definitions and unknown fields/actions are rejected before lab creation. Save
preserves normalized role definitions and assignments, without expanding them
into duplicate direct grants. Existing direct-list manifests retain their
behavior and remain the default.

Generate an opt-in standalone reference profile:

```bash
umask 077
python3 -m network_labs.appliances example --radius --radius-roles \
  --rootfs /absolute/rootfs-radius --radius-user learner \
  --radius-password-file /absolute/password \
  --radius-secret-file /absolute/shared-secret > roles.json
sudo python3 -m network_labs.appliances start roles.json
sudo python3 -m network_labs.appliances radius-exec radius-lan PC1 192.0.2.20 \
  --username learner --password-file /absolute/password \
  --secret-file /absolute/shared-secret --action identity --json
```

The reference assigns `observer` and `auditor` to the declared learner. It grants
no shell unless `--radius-shell` or `--radius-ssh-shell` was explicitly selected.
The latter also requires `--radius-ssh --ssh-authorized-key /absolute/key.pub`
and an image containing Dropbear and the compiled relay. The `--radius-roles`
example flag covers the standalone RADIUS profile; combined/dual-stack example
generation keeps its existing form. The existing dual-stack shell/accounting
exclusion also checks effective role grants and cannot be bypassed by moving
`shell` into a role. Broader role/service compositions require separate evidence.

`radius-exec` and `radius-login` JSON results include `authorization` metadata:
`mode`, assigned `roles` and resolved `actions` for a locally permitted attempt.
This reports local grants, not successful authentication or execution. SSH keeps
its existing output protocol. Its node-wide `management.ssh_actions` is an
additional ceiling: both that list and the user's resolved actions must admit
the requested operation. A role cannot expand the node's SSH action list.

All diagnostics and shells retain UID/GID 65532, empty capabilities and
`noNewPrivileges`. Roles do not create Linux users, grant root, configure network
devices or provide vendor privilege levels. An explicitly granted `shell`
allows commands available to that unprivileged process; the role model does
not filter individual commands inside the shell. Ordinary administrative exec,
SSH/Telnet paths and raw `radius-auth` diagnostics retain their separate scope.

Roles work with enabled accounting, Stop outbox and CLI/SSH journaling. The full
normalized access policy remains part of the durable policy pin: changing a
role definition or assignment blocks replay of old Stop records. Review/drain
those records before changing policy. Apply declarative role changes by lab
recreation; no live role editor, central role distribution or revocation of an
already running shell is implemented. Existing session deadlines remain global
per node.

The dedicated native test uses real FreeRADIUS and key-authenticated SSH with
separate reader, auditor, combined and shell identities. It verifies role unions,
local and SSH ceilings, a valid backend-only account denied locally, zero
RADIUS packets for local-policy denials with a successful capture positive
control, wrong passwords, non-root shell accounting/journal handoff, backend
outage/recovery, saved role retention, reduced grants after recreation and host
cleanup. The successful dedicated native job and local test results are recorded
in LAN_NEXT_STEPS.md.


An explicit standalone [RADIUS Telnet diagnostic profile](TELNET_RADIUS.md)
now applies the same local role/direct grants and a separate node action
ceiling before authentication. It admits one fixed diagnostic per connection;
an explicit bounded Telnet shell extends it with optional accounting and
identity-pinned worker-death recovery.
