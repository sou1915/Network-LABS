# Persistent plain TCP syslog forwarding

Optional `management.syslog_transport:"tcp"` replaces the BusyBox UDP sender
with a node-local rsyslog daemon. Omitted transport retains UDP. The bounded
TCP profile requires a single-interface numbered OCI host and a distinct
managed TCP collector whose declared allowlist admits that host. A sender
cannot also be a collector in this increment. Existing management edits
continue to require lab recreation.

```bash
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --rsyslog /usr/sbin/rsyslogd --rsyslog-tcp --rsyslog-forward --output /path/to/rootfs
python3 -m network_labs.appliances example --syslog-tcp --syslog-tcp-forward \
  --rootfs /path/to/rootfs > syslog-forward.json
sudo python3 -m network_labs.appliances start syslog-forward.json
sudo python3 -m network_labs.appliances exec syslog-tcp-lan PC2 -- /bin/busybox logger -p local0.notice -t lab 'TCP forwarding event'
sudo python3 -m network_labs.appliances show syslog-tcp-lan PC1 --text 'show logging'
```

The daemon accepts local Unix syslog input at the guest's `/dev/log`, writes
local `/run/messages`, and forwards through omfwd to the declared collector
on TCP/514 using octet-counted framing and rsyslog's SyslogProtocol23 template.
It uses plain ptcp, without UDP fallback or TLS. The rootfs builder's new
`--rsyslog-forward` flag adds matching imuxsock, lmnet, lmnetstrms, lmnsd_ptcp
and lmtcpclt modules with resolved ELF dependencies. Existing UDP-only builds
are unaffected. Startup checks assets before creating the lab and validates
rsyslog's actual generated configuration before launching the sender.

Both main and forwarding queues are fixed arrays configured for 256 messages
and one worker. Queue enqueue timeout is zero; a full queue can discard
messages. The action retries indefinitely while the node remains running,
starting with a one-second resume interval capped at five seconds. Local
logging precedes the asynchronous forwarding action, so a suspended remote
action need not block local output until queues/resources are exhausted.
The global message size is 1 KiB. These settings bound configured message
counts; they are not a hard total memory cap or an unlimited-outage guarantee.
Local logs use the same 64 KiB rotation threshold and one backup as the
collector, with normal message/batch overshoot.

Queue files/disk assistance are not configured, and queue save-on-shutdown
is disabled. Logs, in-flight messages and queues are volatile. Saving writes
only declared policy; cold restore reconstructs configuration and fresh
daemons, not pending delivery or old logs. `inspect` includes selected
`syslog_transport` and managed-file conformity, not queue depth, daemon
liveness, suspension status or delivery. Editing generated forwarding config
is drift and prevents save. A stopped collector's conforming config alone
does not establish a functioning service.

Plain TCP has no collector application acknowledgement. Writes accepted
by the socket can be lost around disconnects, and reconnect/retry does not
establish exactly-once or guaranteed durable delivery. The native retry
check therefore waits for a fresh rsyslog suspension before submitting its
queue-recovery marker, then verifies actual storage after collector restart.
It does not claim every message submitted during an outage is delivered.
TLS, authenticated sender identity, durable retry, RELP, router/multi-interface
senders and generic device-event generation remain separate work.

`syslog-tcp-forward-interop` exercises real BusyBox logger inside the guest,
local Unix input, automatic TCP packets and collector storage, a stopped
collector and fresh suspension, local logging while down, queued-marker
recovery after restart, config drift refusal, declarative save during an
outage, cold restore without queued/log snapshots, and host cleanup. Native
CI evidence is pending.

References: [rsyslog omfwd](https://docs.rsyslog.com/doc/configuration/modules/omfwd.html),
[imuxsock](https://docs.rsyslog.com/doc/configuration/modules/imuxsock.html)
and [queue parameters](https://docs.rsyslog.com/doc/rainerscript/queue_parameters.html).
