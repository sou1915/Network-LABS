# Mutual TLS syslog

The optional TLS profile uses rsyslog's gtls driver in mandatory encrypted
mode on TCP/6514. Sender and collector validate the CA chain and an explicitly
configured peer DNS certificate name with x509/name authentication. Both
present an offline certificate/key. SAN prioritization and extended-key-purpose
checks are enabled; the configured GnuTLS priority permits TLS 1.2 and 1.3.
The IP sender allowlist remains an additional collector rule. Plain UDP/TCP
profiles retain their existing defaults and ports; TLS creates no 514 listener
and has no plaintext fallback.

This first profile is two single-interface OCI hosts, one sender IP and one
collector peer identity. They may use different rootfs images. The sender
keeps the existing bounded volatile queues and retry behavior. Co-located
sender/collector and router/multi-interface TLS collectors are refused.

Provision each image with its own leaf identity and the explicit trust CA:

```bash
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --rsyslog /usr/sbin/rsyslogd --rsyslog-tls \
  --syslog-ca-file /path/to/ca.pem \
  --syslog-certificate-file /path/to/collector.pem \
  --syslog-private-key-file /path/to/collector.key --output /path/to/server-rootfs
# Repeat for the client rootfs with its sender certificate and key.
python3 -m network_labs.appliances example --syslog-tls \
  --rootfs /path/to/server-rootfs --syslog-client-rootfs /path/to/client-rootfs \
  --syslog-server-name collector.lab --syslog-client-name sender.lab > syslog-tls.json
sudo python3 -m network_labs.appliances start syslog-tls.json
sudo python3 -m network_labs.appliances exec syslog-tls-lan PC2 -- /bin/busybox logger -p local0.notice -t lab 'TLS event'
sudo python3 -m network_labs.appliances show syslog-tls-lan PC1 --text 'show logging'
```

Use matching trusted rsyslog and GnuTLS modules, normally installed via
`rsyslog` and `rsyslog-gnutls` on Ubuntu. `--rsyslog-tls` packages imtcp,
lmtcpsrv, lmnsd_gtls and the forwarding dependencies; the three identity asset
arguments are required together with it. CA/certificate inputs must contain
public certificates only. Private keys must be matching, unencrypted PEM,
mode 0600, and at most 64 KiB. No CA signing key is copied or generated.
The builder creates a private identity directory and writes each key with
mode 0600 from creation. Identity assets reside at fixed paths under
`/etc/network-labs/syslog-tls`; the directory is masked in non-TLS OCI nodes
sharing an identity-bearing base image.

Collector policy is `syslog_server.transport:"tls"` with a `tls` object;
sender policy is `management.syslog_transport:"tls"` with `syslog_tls`.
Each object has `peer`, `ca_sha256` and `certificate_sha256`. Names are explicit
lowercase DNS names without wildcard authorization. Pins are SHA-256 of
complete public PEM file bytes for the local CA and local identity certificate,
not a remote-leaf pin or DER certificate thumbprint. The example
reads only public files to generate these pins. The saved manifest contains
public pins and rootfs references, never raw keys or a restored TLS session.

Startup checks public pins, private-key permissions and certificate/key
matching, then the daemon validates the generated config. Expiry, chain and
peer authorization are enforced by the actual TLS handshake. Runtime audit
compares public pins plus a runtime-only private-key digest and mode 0600;
missing/changed assets block save. The key digest stays outside startup policy.
Changing certificates/CA/peer policy requires explicit new pins and lab
recreation. Inspection reports asset/config conformity, not handshake success
or delivery. Saving a conforming policy does not promise an available service.

Cold restore needs the supplied offline identities to remain available and
conform to the saved public pins. Keys are not bundled into exported startup
JSON. Logs, queues, runtime digests and TLS sessions are rebuilt. TLS does not
add application acknowledgements, durable retry, automatic certificate renewal,
CRL/OCSP management, public-CA provisioning, multiple identities or a general
RFC5425 interoperability claim. Exact peer names use rsyslog/GnuTLS certificate
matching semantics; this is not a separate certificate-name implementation.

`syslog-tls-interop` provisions ephemeral CA-signed server/client identities
outside the repository, verifies guest logger storage and a separate Python
TLS client, checks encrypted packet payloads, rejects wrong trust/name and a
same-CA unauthorized client identity, rejects plaintext input, audits asset
changes, exercises collector outage/retry and cold restore, and checks host
cleanup. At implementation commit
`c27e6f0603154433a7c170246c71ebcbdd0fdf9d`, the
[dedicated mutual TLS job](https://github.com/sou1915/Network-LABS/actions/runs/41204838147/job/124547706724)
passed in 13.851 seconds on Ubuntu 24.04. It completed the valid, wrong-name
and wrong-CA recreated profiles, independent verified TLS connections,
same-CA unauthorized-client rejection, plaintext rejection, encrypted-marker
packet checks, non-TLS-node identity masking, CA/key-mode drift refusal,
post-suspension retry, declarative save/cold restore and cleanup.

The local suite passed 781 tests with 121 environment-dependent skips.
General CI, the existing plain TCP collector/forwarder, SSH/RADIUS and several
IPv6 jobs also passed; broader suites were still running at this checkpoint.
This is evidence for the bounded mutual TLS profile and listed controls,
not automatic certificate lifecycle, revocation, durable retry or arbitrary
vendor interoperability.

References: [gtls](https://docs.rsyslog.com/doc/concepts/ns_gtls.html),
[imtcp](https://docs.rsyslog.com/doc/configuration/modules/imtcp.html)
and [omfwd](https://docs.rsyslog.com/doc/configuration/modules/omfwd.html).
