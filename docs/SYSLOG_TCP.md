# Plain TCP syslog collector

The optional `syslog_server.transport:"tcp"` enables a persistent node-local
rsyslog `imptcp` listener on its declared IPv4 address and TCP/514. Omitted
transport keeps the existing UDP profile. The ruleset still admits only the
explicit managed source-IP allowlist, uses the existing volatile 64 KiB
rotation threshold with one backup, and does not read host/kernel logs.
TCP creates no UDP listener. Collector edits require lab recreation.

Build matching offline assets and generate the three-node reference:

```bash
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --rsyslog /usr/sbin/rsyslogd --rsyslog-tcp --output /path/to/rootfs
python3 -m network_labs.appliances example --syslog-tcp --rootfs /path/to/rootfs > syslog-tcp.json
sudo python3 -m network_labs.appliances start syslog-tcp.json
sudo python3 -m network_labs.appliances syslog-send syslog-tcp-lan PC2 PC1 --message 'Interface restored' --json
sudo python3 -m network_labs.appliances show syslog-tcp-lan PC1 --text 'show logging'
```

`--rsyslog-tcp` requires `--rsyslog` and packages the matching `imptcp.so`
and resolved ELF dependencies in addition to the UDP modules. Old UDP-only
rootfs builds continue to work for UDP; TCP startup explicitly requests a
rebuild when its module is absent. The collector validates its actual rsyslog
configuration before launching. Its module uses one helper thread and a
16-session limit; the existing main queue holds 256 messages. Global message
size is 1 KiB and imptcp maxFrameSize is 1024. These are rsyslog parser/queue
settings, not a claim of strict malformed-frame rejection or a total memory
cap. Both octet-counted and legacy LF framing are enabled by the receiver.

`syslog-send` is a finite diagnostic between two distinct managed,
single-interface OCI hosts. It binds the observed source IPv4 in the owned
network namespace and submits one RFC5424-shaped message using RFC6587
length-prefixed framing. The user message is 1..512 printable ASCII characters.
A fresh nonce identifies each call. Host Python performs the socket operation;
no guest Python package, persistent sender daemon or guest trust change is
introduced. Collector receipt is separately checked through an exact source
address/message match in a bounded 8 KiB tail window for up to three seconds.

A failed TCP submission reports `failed`. A completed submission without the
exact log observation reports `unknown`, including an allowlist rejection or
an observation-window miss; it does not infer a cause. Only actual matching
storage reports `passed`. There is no application acknowledgement or claim
of exactly-once/durable delivery. The nonce, frames and runtime logs do not
enter saved policy. Save verifies managed configuration; it does not imply
service liveness. After cold restore the transport/allowlist return and logs
start empty. The existing BusyBox management forwarder remains UDP.

This increment provides plain TCP reception and a finite diagnostic, without
TLS, sender authentication, persistent TCP forwarding, durable retries, RELP,
IPv6 collectors or a general RFC5424 validation claim. IP filtering is an
allowlist, not identity authentication.

The dedicated `syslog-tcp-interop` scenario checks split/coalesced octet-counted
frames, LF framing, allowed storage versus a transmitted-but-rejected sender,
packet evidence, rotation, external config drift refusal, collector outage
and restart, cold save/restore and host namespace/link/IPv4-route invariants.
At implementation commit `d07b96fcf4ce77b0a52f11edcf5f3de833430905`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41175172265/job/124461114710)
passed all these checks in 7.922 seconds. The local suite completed 772 tests
with 119 environment-dependent skips. The general CI tests also passed;
broader suites were still running at this checkpoint. This records actual plain-TCP receipt
and collector storage, not persistent forwarding, TLS or durable delivery.

References: [rsyslog imptcp](https://docs.rsyslog.com/doc/configuration/modules/imptcp.html)
and [RFC6587 framing](https://www.rfc-editor.org/rfc/rfc6587).
