# Sender process recovery with a disk-backed Syslog action queue

Optional `management.syslog_disk_queue:true` selects a pure rsyslog disk
action queue for the existing single-interface IPv4 TCP or mutual-TLS sender.
Omission retains the fixed-array volatile queue. UDP refuses the field.
Existing management edits require recreation.

```bash
python3 -m network_labs.appliances example --syslog-tcp --syslog-tcp-forward \
  --syslog-disk-queue --rootfs /absolute/rsyslog-rootfs > syslog-disk.json
```

For TLS, add `--syslog-disk-queue` to the existing `example --syslog-tls`
command with separate provisioned images and peer names. It also works with
the separately opted-in `--syslog-tls-preflight`. Rootfs prerequisites remain
those in [SYSLOG_FORWARD.md](SYSLOG_FORWARD.md) and [SYSLOG_TLS.md](SYSLOG_TLS.md).

The action uses fixed queue prefix `forward` in
`/var/spool/network-labs-syslog` on the owned node overlay, outside `/run`
tmpfs. The directory is root-owned mode 0700; the opted-in sender uses private
umask 0077, with actual queue-file mode 0600 required by native validation.
The queue requests 1 MiB max disk space, 64 KiB segment size,
one worker, batch size one, checkpoint interval one, synchronous queue files,
zero enqueue timeout and save-on-shutdown. These are rsyslog limits with
metadata/record/segment overshoot, not a filesystem quota or an unlimited
outage guarantee. Queue-full/resource failures can discard messages.
Startup refuses base images already containing this spool path, including
symlinks, so new labs cannot silently adopt imported queue records. The spool
is created only in the running node's private overlay.

Only messages that reach the action spool have this process-recovery boundary.
The 256-message main queue, local Unix socket buffering, local `/run/messages`
and in-flight network data remain volatile. `logger` success does not acknowledge
durable enqueue or remote storage. TCP/TLS has no application delivery receipt;
duplicates and loss around in-flight/dequeue/disconnect boundaries remain
possible. This is not exactly-once delivery or RELP.

The same retained node filesystem lets rsyslog recover its own spool after a
sender-daemon restart, including the native-tested SIGKILL case. No helper
deserializes queue records or resubmits local log lines. The native restart
fixture verifies the exact old PID/argv and process death, removes only its
stale PID file and volatile local log, then invokes the existing sender start
function. A separately scoped public
[sender recovery command](SYSLOG_FORWARD_RECOVERY.md) now verifies dead-process
evidence and config/spool conformity before starting that sender. No automatic
daemon supervisor is added. Active PID files and queue data must not be deleted
to force a second daemon to start.

The spool contains plaintext log records even when TLS encrypts the transport.
Protection is directory/file permissions and the lab's host filesystem access;
no at-rest encryption is added. Inspection checks only directory type, ownership
and mode alongside managed config/assets. It exposes neither message contents
nor queue depth and does not claim liveness, completed fsync or delivery.
Directory/config drift refuses save. Mutable queue bytes are not fingerprinted
as declarative config.

Save/export contains the selected policy and image references, never queued
messages. Stopping/recreating the lab removes its owned overlay and spool.
Cold restore creates an empty queue and fresh logs. This increment does not
provide cross-lab-stop queue retention, a host power-loss/filesystem durability
proof, corrupt-spool repair or queue migration across certificate changes.

The dedicated native test covers both TCP and TLS: actual guest logger storage,
fresh collector suspension, marker presence in on-disk queue records, exact
sender PID/argv, SIGKILL and observed death, replay inside the same surviving
container without resubmitting markers or preserving local output, collector
recovery, TCP plaintext versus TLS encrypted packet evidence, continued new
delivery, permission/config drift refusal and explicit cold-restore non-retention.
Host network invariants are checked. Default TCP/TLS and general CI are selected
regressions. Exact evidence is recorded in LAN_NEXT_STEPS.md.

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 \
  -f suite=syslog-disk-queue
```

Remaining LAN work precedes GUI. Static VXLAN with explicit VTEP/VNI/VLAN
mapping remains required; EVPN/BGP remains separate later work.
