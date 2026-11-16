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
out closed. Explicit dead-peer recovery is described below; cold recreation
also remains available. Wrong credentials remain a RADIUS denial, not a daemon
startup success being mistaken for admission.

Teardown closes/stops the NAS worker first, then signals only the matching
owned peer process group. PID reuse does not authorize signalling. Unconfirmed
death or a foreign process group retains the record and refuses namespace
teardown; another CLI can complete normal cleanup. No daemonization flag is
used and no manual peer process is adopted.

This host service is outside node OCI cgroup memory accounting. No total
application/GUI/host-service RAM acceptance is claimed by this increment.

## Explicit recovery without lab recreation

```bash
sudo python3 -m network_labs.appliances dot1x-peer-recover LAB PC1 --json
```

This command replaces only a dead, recorded managed peer. It requires a
stable running lab, no NAS authenticator worker, and a verified closed gate.
It refuses a live peer, changed credentials/handoff, namespace/interface/MAC
drift, changed control-directory ownership/inode/mode, foreign entries or a
replaced/live control socket. Original directory/socket identities are recorded
at startup; legacy active runtimes lacking these records must be recreated.
An absent old socket/directory after clean peer exit is permitted, without
adopting any existing object. No existing live peer or unrelated process is
signalled by recovery.

After all checks, the engine records `phase:recovering-peer`, removes only the
verified stale socket/directory, reaps an owned completed child if applicable
and launches one fresh peer through the same sealed private handoff. It
confirms the gate is still closed before returning to `running`. Node
namespaces, containers, backend and declared policy are retained. The result
requires a new explicit `dot1x-auth`; recovery never grants admission.

Failure after recovery begins retains the incomplete phase and any recorded
resources. Existing auth/save guards refuse this phase. Use normal explicit
stop/restore to clean it up; another recover command does not adopt partial
state. There is no background restart loop or automatic recovery policy.
Inspection/start/stop also reap known completed children left by another CLI's
teardown or recovery, without signalling live/reused processes.

The extended native scenario tests active/live refusal, credential and foreign
socket preservation, in-place CLI recovery, fresh RADIUS exchanges/data and
unchanged backend/namespaces. The native recovery evidence is recorded below.

## In-place recovery validation — 2026-11-06

Implementation `af6723cac8613278bfc921b191db58b8ac2bcd20` adds
`dot1x-peer-recover LAB PC1 --json` for explicit in-place recovery of a dead
recorded supplicant. It requires a stable running lab, no authenticator worker
and a verified closed NAS gate. Original namespace/interface/MAC, credential/
handoff and control directory/socket ownership identities must match. Live
peers, active auth, drift, foreign entries/replaced sockets and responsive
sockets without a matching owner are refused before replacement. Legacy
active state without the new startup ownership metadata requires recreation.
Only verified stale control objects are removed; namespaces, backend and
policy remain. Startup uses the same sealed private handoff and ends with
confirmed closure and authentication_required=true. Fresh explicit auth is
still required. A failed restart retains recovering-peer phase and any
recorded resources; auth/save refuse it until explicit stop/restore. Known dead
children are reaped without waiting for or signalling a live reused PID.

The [dedicated wired native job](https://github.com/sou1915/Network-LABS/actions/runs/42257561787/job/128028719091)
passed the extended managed-peer/recovery scenario in 56.219 seconds and
repeated the full independent-supplicant authenticator scenario in 193.355
seconds. Recovery refused a live peer, active auth, changed credentials and
a foreign regular file replacing the old socket, preserving records/files.
A separate CLI then replaced only the dead peer: its namespace identity,
all lab namespace names and the actual backend PID remained unchanged. The
gate stayed closed until a new finite authentication produced four fresh
RADIUS requests and bidirectional data; save retained the original manifest.
Existing peer death, wrong-password, cold restore, teardown and host namespace/
link/IPv4/IPv6 route/rule invariants passed. Both selected jobs passed; 58 others
were intentionally skipped. Local full tests passed 1024 cases in 30.440
seconds with 163 environment skips; the 17 focused peer cases, compile/diff/
link checks passed. Unit coverage includes failed-restart auth/save refusal,
missing clean-exit control paths and live reused-PID cache isolation. No failed
native run preceded this increment.

## Validation

The dedicated native scenario runs real FreeRADIUS and the managed unmodified
wired supplicant. It covers repeated finite commands without manual peer
launch, actual EAPOL/RADIUS cycles/data, private handoff, active save, peer death
and save refusal, asset drift before allocation, cold restore, separate-CLI
teardown during admission and independently pinned wrong credentials.
Unit tests additionally verify schema boundaries,
sealed memfd/argv/state handling, stale PID/foreign-group refusal and retained
state after unconfirmed death.

Implementation `f4ebb509df3d901ec3265b1665287a852d1783ab` adds an
optional `dot1x_supplicant` policy to the existing wired PC1 peer. A trusted
foreground host wpa_supplicant runs in that peer's namespace across finite
NAS commands. The schema pins identity/interface and a private password-file
hash; preflight rejects invalid assets before allocation. Configuration is
passed through a sealed mode-0600 memfd, with no secret in argv, runtime peer
files or startup JSON. Inspection checks owned process, namespace/interface,
control readiness and original handoff/asset pins; save refuses dead or
unverifiable peers. Normal CLI hash redaction is added by `22a0844`.
Teardown stops the NAS first, then signals the owned peer group and confirms
peer process death before namespace removal. PID reuse/foreign groups do not authorize signalling.
Cold restore preserves policy only and starts a new peer with the gate closed.
The authenticator remains explicit/finite; there is no automatic peer restart
or persistent NAS authentication service.

At final validation commit `ff4b08a7d96d62ce81dfe027ef1383b57b58a704`,
the [dedicated wired job](https://github.com/sou1915/Network-LABS/actions/runs/42253373302/job/128014020814)
passed the new managed-peer scenario in 45.443 seconds and the existing full
authenticator scenario in 193.528 seconds. The new reference verified two real
EAPOL Success/four RADIUS requests, data in both directions, active save,
a second CLI auth reusing the same peer, peer SIGKILL followed by closed
authentication timeout/save refusal, changed-asset refusal before allocation,
cold restore, separate-CLI teardown during admission and actual wrong-password
rejection while the peer stayed running. Host namespace/link/IPv4/IPv6
route/rule invariants passed. Both selected jobs passed; 58 others were
intentionally skipped. Local full tests passed 1015 cases in 30.441 seconds
with 163 environment skips; compile/diff/link checks passed.

Initial run 42252777315 at `f4ebb50` passed both jobs (managed peer 44.769
seconds, old authenticator 219.613 seconds). Run 42253118016 at `22a0844`
passed general CI but failed the first admitted ping in the new fixture.
Fixture-only correction `ff4b08a` uses the existing reference's bounded data/
ARP readiness pattern: real traffic must succeed within two seconds and a
verified admitted lease, otherwise it fails. Duration, packet, credential and
cleanup assertions were retained; no admission/runtime policy was relaxed.
