# Private Stop-only accounting outbox

An optional host-side outbox retains a closed session's accounting Stop until
an authenticated Accounting-Response confirms receipt. It survives lab stop,
a fresh CLI process and recreation from the saved matching configuration. It
never queues a Start or opens a session during replay.

Enable `radius_access.accounting_outbox:true` with accounting enabled and a
separate managed accounting server admitting the declared NAS. The reference:

```bash
umask 077
python3 -m network_labs.appliances example --radius --radius-shell --radius-accounting \
  --radius-accounting-retries 1 --radius-accounting-outbox \
  --rootfs /absolute/rootfs-radius --radius-user learner \
  --radius-password-file /absolute/password --radius-secret-file /absolute/shared-secret > radius-outbox.json
sudo python3 -m network_labs.appliances start radius-outbox.json
```

Existing RADIUS credential-file, rootfs and private manifest requirements apply.
The bounded IPv4 local/RADIUS SSH shell accounting scope is unchanged; current
static dual-stack diagnostic profiles still exclude shell/accounting. Omission
preserves the existing nonpersistent accounting behavior.

After a verified Access-Accept, the supervisor verifies the managed backend,
static NAS binding and queue capacity before allowing a new accounted session.
Start still needs a live verified receipt before any shell launch. After the
session group confirms cleanup, a Stop intent is written and fsynced before its
first send. Successful receipt removes and fsyncs the local entry. Unconfirmed
receipt leaves the entry pending and retains the existing unknown session result.
Unconfirmed cleanup withholds both Stop transmission and Stop enqueue.
A compensating Stop after uncertain Start follows the same rule, without opening
a shell. Its termination cause is 9 and session time is zero.

Inspect the queue even when the lab is stopped:

```bash
sudo python3 -m network_labs.appliances radius-accounting-pending radius-lan --json
```

After restoring the same saved lab, explicitly replay a bounded batch:

```bash
sudo python3 -m network_labs.appliances restore radius-lan
sudo python3 -m network_labs.appliances radius-accounting-flush radius-lan --limit 4 --timeout 3 --json
```

The flush limit is 1..8 entries, default 4; each entry retains its 1..5-second
exchange timeout and declared finite retries. Larger remaining batches need
another explicit invocation. A nonempty queue, blocked policy or unconfirmed
receipt remains visible and returns an incomplete result. Startup does not
silently flush, authenticate a user or reopen a session. Replay sends Stop only.

Each event is pinned to its lab, source node/static NAS configuration, backend
address/node, username and access policy, incorporating a digest of the current
NAS secret. No secret/password bytes are stored in the outbox. Replay obtains
the secret from the running managed configuration and refuses changed bindings
before sending. The accounting wrapper also refuses an observed NAS address
that differs from its declaration. Policy changes or secret rotation leave the
event available for review; nothing is silently discarded or redirected.

The default location is `/var/lib/network-labs/LAB/accounting-outbox/`, outside
the ephemeral runtime directory and outside startup.json. Directories are private
0700 and records are regular 0600 files owned by the lifecycle user (root in
normal use). Each record is at most 4096 bytes; at most 32 committed events are
allowed per lab. New accounted sessions are refused when this bound is reached
or existing queue data is invalid. A closed session whose persistence write
fails still attempts live Stop, but does not claim a durable pending event.
JSON API accounting results report whether enqueue/clear was confirmed.

Writes use an fsynced private temporary file, a non-overwriting link, removal of
the temporary link and directory fsync; relevant parent directories are synced
after creation. Receipt-driven deletion also syncs the directory. Invalid JSON,
unsafe file types/permissions, symlinks, excess entries or abandoned temporary
files stop automatic processing and are retained for administrator review.
No automatic repair or discard command is provided. Saving/exporting startup
configuration does not include the queue or session events.

Replay preserves session ID, username, recorded duration and termination cause.
Acct-Delay-Time starts with elapsed wall-clock seconds since the Stop intent;
backward clock changes clamp it to zero, and overlarge ages block delivery.
Finite retransmissions add monotonic elapsed time during that exchange, using
the existing identifier/authenticator rules. This is approximate event timing,
not a clock synchronization or billing guarantee.

This increment does not journal running sessions, Start intents, or the gap
before cleanup/Stop commit. A host/supervisor crash in those earlier phases can
still leave unmatched backend records requiring reconciliation. No power-loss
fault injection or background replay daemon is included. A crash after backend
receipt but before local deletion may cause duplicate Stop records on replay;
there is no exactly-once backend storage guarantee. Deleting startup/runtime
state does not authorize deleting pending records.

The dedicated native test loses live Stop receipts with actual FreeRADIUS,
confirms cleanup and private persistent storage, stops the lab, lists pending
metadata without a running lab, recreates with a rotated secret and blocks
replay, restores the original policy, retains an event after failed delivery,
then confirms an explicit Stop-only replay with aged Acct-Delay-Time and no
new shell launch. A healthy subsequent session clears its intent normally.
Packet evidence, fresh processes, saved policy and host cleanup are checked;
results are recorded in LAN_NEXT_STEPS.md.
