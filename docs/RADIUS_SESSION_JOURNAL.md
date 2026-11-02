# Explicit local accounting session reconciliation

An optional private journal commits a session intent before the local CLI
supervisor sends accounting Start. It supports explicit recovery after that
supervisor process dies. It never replays Start, opens a replacement shell,
or assumes a vanished runtime/cgroup proves cleanup.

```bash
umask 077
python3 -m network_labs.appliances example --radius --radius-shell --radius-accounting \
  --radius-accounting-outbox --radius-accounting-journal \
  --rootfs /absolute/rootfs-radius --radius-user learner \
  --radius-password-file /absolute/password --radius-secret-file /absolute/shared-secret > journal.json
sudo python3 -m network_labs.appliances start journal.json
```

The new `radius_access.accounting_journal:true` requires the managed accounting
Stop outbox and all its existing policy constraints. It currently covers local
`radius-login`, not the persistent RADIUS SSH supervisor. SSH journal/crash
coverage, Telnet, dynamic/dual-stack shell compositions and whole-host crash
reconciliation remain separate work. Default non-journal profiles are unchanged.
Drain/review previously pinned Stop records before changing accounting policy;
enabling this option changes that policy's binding.

The normal sequence is: verified Access-Accept, capacity and backend/source
checks, owned session cgroup creation, fsynced intent, verified accounting Start,
then shell launch. During cleanup the supervisor kills its own subtree, observes
`populated 0`, commits an `empty` checkpoint, removes the cgroup, and hands the
closed event to the Stop outbox. The journal is then removed; the outbox handles
receipt and optional explicit retransmission. A known unsent Start needs no Stop
and retires its empty journal entry. Write failures prevent normal accounting
progress rather than manufacturing cleanup or receipt evidence.

Read intent metadata without waiting on a live supervisor's lifecycle lock:

```bash
sudo python3 -m network_labs.appliances radius-accounting-sessions radius-lan --json
```

Select one session ID for explicit reconciliation:

```bash
sudo python3 -m network_labs.appliances radius-accounting-reconcile radius-lan aaa_SESSION_ID --json
```

The actual ID is `aaa-` plus 32 hexadecimal characters as shown in the inventory.
The example placeholder must be replaced with that exact ID. This command
refuses a supervisor with the original PID/start time in the same boot. That
read-only refusal occurs before waiting for the lab lock; all mutation checks
are repeated while holding it.

For an unclosed `intent`, reconciliation requires the original boot, namespace
device/inode, container PID/start time and owned session cgroup device/inode.
If tasks remain, the default command does nothing. Only an explicit flag permits
killing that one verified orphan group:

```bash
sudo python3 -m network_labs.appliances radius-accounting-reconcile radius-lan aaa_SESSION_ID --terminate --json
```

It waits at most two seconds for empty population, commits the cleanup checkpoint
before removal, and queues a compensating Stop. A missing, substituted or
unverifiable intent cgroup remains unknown. Recreated runtimes cannot retroactively
prove that an unclosed intent ended. A previously committed `empty` checkpoint
is historical cleanup evidence and can hand off under matching policy after
recreation; current kernel resources are not touched when runtime identity differs.

Reconciliation sends no RADIUS packet. Use the existing explicit Stop flush:

```bash
sudo python3 -m network_labs.appliances radius-accounting-flush radius-lan --limit 1 --json
```

Recovered Stops keep the session ID and user, use NAS-Error cause 9 and zero
session time because actual shell execution/duration may be unknown. They do
not claim normal completion or measured usage. Duplicate backend Stops remain
possible; this is not exactly-once accounting or a billing record guarantee.

The journal lives in `/var/lib/network-labs/LAB/accounting-sessions/`, outside
runtime state and startup.json. Its bounded 0600 records and 0700 directories
use the Stop outbox's owner/type checks and fsync discipline. At most 32 records
of at most 4096 bytes are allowed per lab, independently of the Stop queue.
Records include process/kernel identities and a policy pin, never password or
shared-secret bytes. Full/invalid journals refuse new journaled sessions. Partial
writes, unsafe entries and ambiguous states are retained for manual review.

An intent means Start may have been sent; it does not prove a server receipt or
that a shell ever launched. There is no automatic sweep, background replay,
Start receipt ledger, exact launch journal or power-loss fault injection. A host
crash before a cleanup checkpoint still requires manual reconciliation. A crash
between durable checkpoint and Stop handoff is handled conservatively; the
committed empty proof remains available for a later explicit attempt. Runtime
stop/recreate leaves journal evidence in place rather than deleting it.

The dedicated native job starts an actual sleeping unprivileged session with
FreeRADIUS, reads its intent while the owner holds the lab lock, refuses a live
owner, SIGKILLs that owner only, refuses an occupied orphan without the flag,
then verifies explicit termination, empty cgroup removal, local Stop handoff,
no packet before explicit flush and the compensating Stop packet. It also
leaves an unclosed intent through recreation and refuses stale-runtime cleanup,
then verifies a healthy new journaled session and host invariants. Results are
recorded in LAN_NEXT_STEPS.md.
