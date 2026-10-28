# Bounded session accounting

Accounting is optional and applies to `radius-login` sessions, not the existing
administrative `exec`, SSH/Telnet services or fixed `radius-exec` diagnostics.
Enable `"accounting": true` in both the source's `radius_access` policy and
the managed server's `radius_server` declaration. The same server address and
NAS shared secret are used for authentication and accounting.

The reference generator supports an explicit combined profile:

```bash
umask 077
python3 -m network_labs.appliances example --radius --radius-shell --radius-accounting \
  --rootfs /var/lib/network-labs/rootfs-radius \
  --radius-user learner --radius-password-file ./radius-password.txt \
  --radius-secret-file ./radius-secret.txt > radius-accounting.json
sudo python3 -m network_labs.appliances start radius-accounting.json
```

Use a freshly built [FreeRADIUS rootfs](NATIVE_RADIUS.md) containing the trusted
`rlm_exec.so` module. The builder copies this module and dependencies when
present in the supplied module directory, together with trusted host util-linux
`flock` and its ELF dependencies (Ubuntu BusyBox lacks that applet). Auth-only roots can omit it, but
accounting startup refuses a root without it. Existing roots may need rebuilding.
Private credential-file rules and [login policy](RADIUS_LOGIN.md) remain required.

The client sends one IPv4 UDP/1813 Accounting-Request per event and validates
the Accounting-Response identifier, source endpoint, packet lengths, TLVs and
shared-secret Response Authenticator. It uses the accounting Request
Authenticator defined in [RFC 2866](https://www.rfc-editor.org/rfc/rfc2866.html),
separate from Access-Request's mandatory Message-Authenticator policy.
No password is included in an accounting packet. This is the historical
MD5-based UDP accounting protocol, not TLS/RadSec.

After successful authentication, an acknowledged Start is required before
launching the shell. Start and Stop carry the same generated session ID,
username and observed NAS IPv4. Stop includes monotonic elapsed session
seconds and a termination cause: normal success 1, lifetime expiry 5, host
interruption 6, and failed startup/session 9. Packet/octet usage is not measured.

Start reserves the accounting context before execution. If its receipt is
uncertain, no shell starts; after cleanup the client attempts a compensating
Stop with zero session time and cause 9 when a request may have been sent.
A Start record alone is therefore not proof that a shell opened. A cleanup
that cannot be confirmed withholds Stop to avoid claiming that service ended.
If Stop is unacknowledged after a launched session, the invocation reports
`ACCOUNTING_STOP_UNCONFIRMED`; completed commands are not rolled back.

Each event has a 1..5-second deadline and at most 64 received datagrams.
There are no retries, failover, interim updates, durable resend queue or crash
reconciliation. Lost receipts can leave uncertain or unmatched records.
Host crashes and uncatchable termination retain the login supervisor's existing
limitations. This profile is not a billing or durable audit guarantee.

The managed server listens on UDP/1813 only when accounting is enabled and uses
a fixed BusyBox writer through the synchronous `exec` module only for accounting
packets. Its lock serializes appends; write errors and incomplete readback fail
the request, and a partial append is truncated before releasing the lock.
Records contain only six pipe-separated fields: event, session ID, username,
NAS IPv4, elapsed seconds and numeric termination cause (Start uses 0). No
password or arbitrary request attributes are logged. Records are root-owned
mode 600 under a mode 700 directory. The generated writer is mode 700 and
its hash/permissions are checked with the server configuration. Normal `inspect` output reports
the accounting listener, not private record contents. An administrator can
read the current lab's records explicitly:

```bash
sudo python3 -m network_labs.appliances exec radius-lan PC2 -- \
  /bin/busybox cat /run/network-labs-radius-accounting/sessions
```

Records live on the node's bounded `/run` tmpfs and disappear on stop/recreate.
No log rotation or durable central storage is implemented. The additional
native scenario fills that filesystem and requires an unrecorded Start to
receive no acknowledgement and grant no shell. Native CI must validate this
alongside real Start/Stop matching, termination causes and private file modes.
