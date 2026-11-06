# Managed wired EAP-MD5 peer

The optional `dot1x_supplicant` field starts an engine-owned, foreground host
`wpa_supplicant -D wired` in the declared peer's network namespace. It stays
alive across finite `dot1x-auth` commands and stops during lab teardown.
Without the field the independent/manual peer workflow is unchanged.

The scope is the existing three-node, one-peer, VLAN 1 wired reference in
[DOT1X_WIRED.md](DOT1X_WIRED.md). The authenticator remains an explicit finite
command with its existing duration/renewal limits. Starting a peer service
does not open the controlled port or automatically start/restart a NAS worker.
Persistent NAS authentication, automatic peer recovery, stronger EAP/TLS,
multi-client/dynamic VLAN/accounting remain separate work.

## Configuration

Generate the existing `--radius --radius-eap-md5 --dot1x` manifest. Add this
field to the existing PC1 node before starting it (replace the digest with
the SHA-256 of the actual password bytes, excluding an optional final newline):

```json
"dot1x_supplicant": {
  "interface": "eth0",
  "username": "learner",
  "password_file": "/absolute/root-owned-peer-password",
  "password_sha256": "<64 lowercase hexadecimal characters>"
}
```

The identity must be allowed by the NAS. The peer asset is independently
pinned; a different password from the backend produces real authentication
rejection. Credentials use the existing EAP asset rules: a single-link,
regular, owned file mode 0600, no symlink, 1..128 printable ASCII password
bytes, with one optional final newline. Native start requires root ownership.
Offline parsing/planning does not read assets. Host `wpa_supplicant` and Linux
memfd support are required; there is no guest-image or alternate-method fallback.
Policy changes require recreation.

The engine reads the credential privately, builds a hex-encoded EAP password
configuration in a mode-0600 memfd and seals it against writes/growth/shrink.
Only the inherited `/proc/self/fd/N` reference appears in process argv.
The configuration is not written to runtime disk, startup JSON or command
logs. Daemon stdout/stderr are discarded. Plaintext credentials still exist
in trusted process memory; this is not protection against a privileged host
administrator. The backend's separate private configuration is unaffected.

The root-private lab directory contains the peer's Unix control socket.
Inspection checks PID/starttime, namespace/interface identity, control PING,
the declared asset pin and the original configuration handoff digest. It does
not attest arbitrary privileged modifications to daemon memory/control state
or certify packet delivery. `running` and `configuration_verified` are
separate from NAS admission. Use real traffic and `dot1x-auth` for that proof.

## Lifecycle and recovery

Start the manifest normally, inspect PC1, then run the existing explicit
`dot1x-auth LAB SW1 --json`. Repeated commands reuse the same peer process.
Admission still starts closed and each NAS exchange must verify EAP/RADIUS.

Save refuses a dead/unverifiable declared peer or changed private asset.
Save/restore preserves policy and asset paths/pins only, never a process,
control socket, authorization or worker generation. Cold restore starts a new
owned peer and a closed gate; explicit authentication is required again.

There is no automatic restart after peer death. A current admitted lease may
last until its existing finite kernel bound; immediate revocation on process
SIGKILL is not claimed. Subsequent reauthentication without the peer times
out closed. Recreate from a previously saved manifest after fixing the asset
or service failure. Wrong credentials remain a RADIUS denial, not a daemon
startup success being mistaken for admission.

Teardown closes/stops the NAS worker first, then signals only the matching
owned peer process group. PID reuse does not authorize signalling. Unconfirmed
death or a foreign process group retains the record and refuses namespace
teardown; another CLI can complete normal cleanup. No daemonization flag is
used and no manual peer process is adopted.

## Validation

The dedicated native scenario runs real FreeRADIUS and the managed unmodified
wired supplicant. It covers repeated finite commands without manual peer
launch, actual EAPOL/RADIUS cycles/data, private handoff, active save, peer death
and save refusal, asset drift before allocation, cold restore, separate-CLI
teardown during admission and independently pinned wrong credentials.
Native results are pending. Unit tests additionally verify schema boundaries,
sealed memfd/argv/state handling, stale PID/foreign-group refusal and retained
state after unconfirmed death.
