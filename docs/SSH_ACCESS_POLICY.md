# Restricted SSH actions

An optional `management.ssh_actions` list confines every configured SSH key on
that node to fixed diagnostic commands. Authentication still uses Dropbear
public-key authentication. This is server-side command authorization, not
RADIUS password authentication, a per-user role hierarchy or shell accounting.
The local `radius-login` supervisor remains a separate path.

```json
"management": {
  "interface": "eth0",
  "ssh_keys": ["ssh-ed25519 REPLACE_WITH_YOUR_PUBLIC_KEY"],
  "ssh_actions": ["identity", "hostname", "security-context"]
}
```

Clients request the exact action name, for example:

```bash
ssh -i ./identity lab@192.0.2.20 identity
ssh -i ./identity lab@192.0.2.20 hostname
ssh -i ./identity lab@192.0.2.20 security-context
```

`identity` runs BusyBox id; `hostname` runs BusyBox hostname; `security-context`
reads `/proc/self/status`. No user-supplied command is evaluated or added to
argv. Extra arguments, shell syntax, interactive shell requests, SCP commands
and SFTP subsystem requests are denied with exit 126. PTY allocation, TCP
forwarding and agent forwarding are disabled for these keys. The existing
non-root UID/GID 65532 and inherited OCI no-new-privileges policy still apply.
All keys share this node's action list and Linux identity.

An empty list denies every command. Omitting the field, or using null, retains
the existing unrestricted non-root SSH shell profile. Restricted actions
require SSH keys and cannot coexist with a Telnet shell on the same node.
They do not restrict administrator host-side `exec` or the separate local
RADIUS executor; those retain their own authorization model.

The generator supports repeatable action options:

```bash
python3 -m network_labs.appliances example --management \
  --rootfs /var/lib/network-labs/rootfs-management \
  --ssh-authorized-key ./identity.pub --ssh-action identity --ssh-action hostname \
  > management-observer.json
```

The generated authorized_keys file forces a root-owned dispatcher under the
read-only `/lab` mount. The `/home`, `/home/lab` and `/home/lab/.ssh` directories
are root-owned mode 755 in the restricted profile so another uid-65532 process
cannot replace an ancestor of authorized_keys. Inspection/save checks the
managed files and these permissions; it does not prove daemon liveness or
an authentication decision. Edit the manifest and recreate the lab to change
the policy. Declarative save/restore preserves it; host keys remain ephemeral.

The dedicated SSH CI scenario uses real Dropbear/OpenSSH connections to test
allowed diagnostics, wrong-key denial, shell/SCP/SFTP/injection denials, PTY
and forwarding refusal, unprivileged ancestor replacement, permission/script
drift, saved restart and deny-all policy. Unit tests cover validation, exact
command dispatch and unavailable permission observations.

RADIUS-backed SSH login still needs a credential-safe authentication bridge
and remote session supervision/accounting. A forced command alone does not
provide that integration.
