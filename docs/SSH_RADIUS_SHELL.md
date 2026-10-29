# Bounded RADIUS shell over SSH

An explicit shell permission extends the [RADIUS SSH diagnostics](SSH_RADIUS.md)
profile. The SSH key authenticates the transport account `lab`; a fresh RADIUS
username/password and the user's local `shell` permission are then required.
The default diagnostic profile still denies shell and PTY requests.

Generate a combined profile with an existing Dropbear/FreeRADIUS rootfs:

```bash
umask 077
python3 -m network_labs.appliances example --radius --radius-ssh --radius-ssh-shell \
  --radius-accounting --rootfs /var/lib/network-labs/rootfs-radius-ssh \
  --ssh-authorized-key ./identity.pub --radius-user learner \
  --radius-password-file ./radius-password.txt --radius-secret-file ./radius-secret.txt \
  > radius-ssh-shell.json
sudo python3 -m network_labs.appliances start radius-ssh-shell.json
```

The generator adds `shell` to both `management.ssh_actions` and the learner's
`radius_access.users` permissions. Manually authored policies require both;
RADIUS alone cannot override a missing local permission. Changing this profile
requires lab recreation. Save/restore preserves the declarative permission.

From a client connected to the lab network:

```bash
ssh -tt -i ./identity lab@192.0.2.10
```

Wait for the RADIUS username and password prompts before entering credentials.
The guest relay disables echo before prompting. Do not pre-pipe credentials
into a PTY: input sent before a prompt can be echoed by the terminal before
the relay takes control. Interactive commands use a real host-supervised
PTY, initially 80 columns by 24 rows. Ctrl-C/Ctrl-D reach that terminal;
window-size propagation is not implemented.

For non-PTY scripting, request the literal `shell` action and send the two
credential lines followed by command lines over SSH stdin. Passwords do not
appear in command arguments or environment variables. Arbitrary commands in
SSH's original exec request, SCP/SFTP and forwarding remain denied; arbitrary
Linux shell commands are available only inside the successfully authorized
shell. An omitted exec request selects shell only in this explicit profile.

The existing `radius-login` supervisor checks a verified Access-Accept, creates
a private cgroup-v2 session subtree and launches UID/GID 65532 with empty
capabilities and no-new-privileges. The shell checks its actual cgroup before
reading commands. All descendants are killed and the subtree removed on main
shell exit, lifetime expiry or terminal-transport disconnection. The policy's
`radius_access.session_seconds` bounds the lifetime (default 300, maximum 3600).
The SSH daemon has explicit no-new-privileges and the additional CHOWN, FOWNER
and KILL capabilities needed to manage its unprivileged PTY relay; the shell
itself has none.

Optional accounting reuses the existing Start receipt gate, compensating Stop
rules, and Stop only after confirmed cleanup. Final SSH status is emitted after
cleanup and any required Stop receipt: normal shell exit preserves its code;
expiry is 124, unconfirmed execution/cleanup/accounting is 125, denial 126,
and an interrupted session 130. A lost transport cannot confirm a final status.
Neither completed commands nor filesystem changes are rolled back.

Shell output uses bounded base64 data records, separate from final status, so
a user's output cannot forge a successful completion. The relay buffers are
bounded and total shell output is limited to 1 MiB; exceeding it ends the
session with an unsuccessful status and cleanup. Private FIFO transports carry
credentials and input as streams, not persistent file contents, and are removed
on normal completion/handled termination. Uncatchable process death retains
usual cleanup limitations. One bridge handles one request/session at a time;
concurrent requests may time out while a shell is active.

This remains a trusted educational lab with a shared UID, not per-user OS
isolation, PAM/password authentication in SSH's handshake, crash recovery,
durable accounting or Telnet AAA. Native CI exercises actual non-PTY/PTY
shells, privilege/cgroup evidence, normal/background cleanup, expiry,
disconnection, accounting causes and saved restart.
