# Pinned IPv4 RADIUS SSH shell with durable accounting

The existing bounded [RADIUS SSH shell](SSH_RADIUS_SHELL.md) can now use
the [explicit offline server host identity](SSH_HOST_IDENTITY.md), when
accounting, durable Stop outbox and session journal are all enabled. The
client verifies the declared server key and authenticates its SSH key;
the shell still needs a permitted RADIUS user/action and accounting Start
acknowledgement. Host trust does not bypass those gates.

```bash
umask 077
python3 -m network_labs.appliances example --radius --radius-ssh \
  --radius-ssh-shell --radius-accounting --radius-accounting-outbox \
  --radius-accounting-journal --rootfs /path/to/radius-ssh-relay-rootfs \
  --radius-user learner --radius-password-file /path/to/password \
  --radius-secret-file /path/to/shared-secret \
  --ssh-authorized-key /path/to/client.pub --ssh-action identity \
  --ssh-host-key-file /path/to/server-host.key > pinned-ssh-shell.json
sudo python3 -m network_labs.appliances start pinned-ssh-shell.json
```

Build the existing FreeRADIUS/Dropbear image with the trusted compiled SSH
relay required by the shell guide. Host `dropbearkey`, a mode-0600 offline
ed25519 source, public identity declaration and runtime private-file checks
retain their existing scope. Pre-provision strict known_hosts for NAS PC1
at `192.0.2.10`. Use the existing encrypted stdin credential/relay protocol.
The generator appends explicit `shell` to its SSH action list and permits
bounded shell access through the declared RADIUS access policy.

All three accounting flags are mandatory for this pinned shell increment.
Diagnostics-only pinned profiles retain their existing restrictions, and
an unselected shell grant cannot silently widen them. Pinned shells over
IPv6, partial accounting lifecycles, Telnet, syslog and managed-server
co-location on the NAS remain refused. Larger/coexisting topologies and
every reusable-role combination have not been established by this native
reference. Existing unpinned shell/accounting profiles remain unchanged.

The [session journal](RADIUS_SESSION_JOURNAL.md) and
[Stop outbox](RADIUS_OUTBOX.md) keep their original guarantees: worker death
can leave live payloads requiring explicit orphan reconciliation, queued Stop
does not itself acknowledge backend delivery, and a changed runtime identity
refuses stale cleanup. Cold restore preserves declarations and host trust,
not live SSH sessions or process state. No automatic supervisor restart,
exactly-once accounting or automatic client trust update is added.

## Validation

The dedicated native scenario reuses the real SSH journal suite with pinned
host trust. It verifies a real authenticated shell, wrong-host trust refusal
without a new session intent, supervisor SIGKILL with live orphan payload,
live-owner/nonempty-session cleanup refusal, explicit termination, durable
Stop handoff without implicit network delivery, exactly one bounded explicit
Stop transmission and actual backend records. Cold restore must keep the same
pre-provisioned known_hosts, use a fresh bridge token, reject stale-runtime
reconciliation and complete a healthy shell with Stop acknowledgement.
Host namespace/link/IPv4/IPv6 route/rule invariants are checked.

Additional native lifecycle coverage is now pending: the real PTY/shell suite
with pinned identity and full outbox/journal enabled. It exercises denied
credentials/actions without payload creation, a chosen command exit status,
PTY/no-new-privileges/empty capabilities, no password echo, background-process
cleanup, expiry, client disconnect, matching Start/Stop session IDs and all
four expected termination causes. Healthy completion must leave both journal
and outbox empty; restored shells must reuse the exact pre-provisioned trust
file. Host namespace/link/route/rule/forwarding/unprivileged-port invariants
are checked. This adds validation, not protocol behavior or manifest scope.

At implementation commit `9146031a8cddcb11a5987fa1d3a5ff02162f3fc9`,
the [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42173268692/job/127745802977)
passed in 10.636 seconds. All six selected jobs passed: pinned shell, old SSH
journal, pinned diagnostics, standalone pinned SSH, RADIUS/SSH and general CI.
The other 54 jobs were intentionally skipped, not new native evidence.
Local full tests under umask 022 passed 989 cases in 31.490 seconds with
160 environment-dependent skips; compilation/diff checks passed. No failed
native run preceded this result.

The existing manual selector is reused without adding a 26th choice:
`gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ssh-radius-host-key`.
It selects the new pinned journaled shell, the existing unpinned SSH journal,
pinned diagnostics, standalone pinned SSH, RADIUS/SSH and general CI.
