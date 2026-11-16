# Explicit recovery of a dead Syslog disk-queue sender

For a running lab whose TCP/TLS sender opted into `syslog_disk_queue:true`:

```bash
sudo python3 -m network_labs.appliances syslog-forward-recover syslog-tcp-lan PC2
```

This starts a confirmed dead sender inside its retained OCI node. The command
prints JSON with `status:"started"`, the observed PID, previous stale PID if
present, and the scope of that evidence. It does not stop a running sender or
restart the node. Confirm actual collector storage separately.

The lab must be running without pending configuration. The selected node must
be an existing disk-queue sender and its managed config, TLS identity assets
and spool directory must conform. Existing optional Syslog peer preflight is
reapplied with pinned offline identities. The command runs under the existing
lab lock and refreshes state after acquiring it.

Inside the owned container, a bounded census checks at most 128 process
entries. A live PID-file owner or live rsyslog executable refuses recovery,
including when the PID file is missing. Invalid/non-regular/symlink PID files,
unavailable process evidence and changed PID/inode observations also refuse.
The census runs again before cleanup. Only a regular, unchanged stale PID
file whose process is absent or dead/zombie can be removed. No signals are
sent to any process. The fixed sender start function then tests its config
and launches the declared daemon. A bounded wait requires matching live PID/
argv observations before reporting `started`.

The command does not deserialize, copy, clear or resubmit spool records, and
does not replay or remove local log output. The existing rsyslog queue performs
recovery. A duplicate recovery request refuses while the new sender is live.
The lab lock serializes cooperating CLI requests; this is not protection
against a malicious root process racing changes inside the node. If startup
is requested but readiness cannot be verified, the command reports failure;
inspect the node before another attempt, since a daemon may have started.

This provides an explicit operator action after a daemon crash, with no
automatic supervisor or delivery acknowledgement. The same container/spool
must remain present; stopping/recreating the lab still removes its owned
spool. Main/input/in-flight buffers remain volatile. Queue capacity, plaintext
at-rest data and TCP/TLS duplicate/loss boundaries remain those in
[SYSLOG_DISK_QUEUE.md](SYSLOG_DISK_QUEUE.md).

The dedicated native test reuses the existing TCP/TLS SIGKILL-and-replay
scenario with recovery through separate CLI processes. It requires precise
live-PID/missing-file process-census refusal, unrelated live PID refusal,
malformed/symlink PID preservation, drift refusal before stale-file cleanup,
stale-PID and absent-PID recovery, duplicate refusal, same retained container,
exact new PID/argv, real spool replay without marker resubmission, actual TCP/
TLS packets, continued delivery and cold-restore non-retention. The original
disk-queue scenario and default TCP/TLS forwarding remain separate selected
regressions, alongside general CI. Exact evidence is in LAN_NEXT_STEPS.md.

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=syslog-recover
```

Remaining LAN work precedes GUI. Static VXLAN with explicit VTEP/VNI/VLAN
mapping remains required; EVPN/BGP remains separate later work.
