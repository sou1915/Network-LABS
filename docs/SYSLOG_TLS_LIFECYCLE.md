# Syslog TLS peer preflight and explicit identity replacement

`example --syslog-tls --syslog-tls-preflight` adds
`verify_peer_on_start:true` to both the collector's `syslog_server.tls` and
sender's `management.syslog_tls` policies. All other arguments remain those
in [SYSLOG_TLS.md](SYSLOG_TLS.md). Omission retains existing live-handshake
failure labs. The builder still accepts the local identity and its peer trust
bundle without knowing which role it will have.

The opt-in requires exactly one TLS collector and one TLS sender, both opted
in, with matching declared sender IP/collector target. It adds a bounded
memory-BIO mutual TLS exchange at startup, before resource allocation. Only
the supplied peer CA bundles are loaded; no sockets, host roots or external
CA fetching are used. OpenSSL validates chains, current host-clock validity,
serverAuth for the collector and clientAuth for the sender. Both leaves must
contain their authorized exact DNS SAN. This opt-in accepts no wildcard or
legacy CN-only authorization; existing GnuTLS name semantics remain unchanged
when the option is omitted. Half-enabled and miswired pairs are refused.

The sender's CA bundle validates the collector; the collector's CA bundle
validates the sender. Either may differ from the issuer of its local identity.
Two distinct issuing CAs are supported when trust is configured reciprocally.
Private-key matching/permissions and exact public file pins remain enforced.
Even freshly pinned expired, future, wrong-purpose, wrong-trust or wrong-name
pairs fail before namespaces/containers are allocated.

The offline result is an additional local asset check, not a live handshake,
delivery verdict or guarantee that OpenSSL and GnuTLS accept every PKI profile
identically. Real rsyslog/GnuTLS still performs its own mutual validation on
TCP/6514. Runtime inspection remains config/asset conformity; it does not
continuously reevaluate certificate expiry or observe TLS sessions.

To replace identities, build new immutable sender and collector images with
their replacement certificates/keys and explicit peer CA bundles. Generate a
new `example --syslog-tls --syslog-tls-preflight` manifest to create new public
pins, then stop the old lab and start the new declaration with the same lab
name. Keep exact DNS SANs and role-compatible purposes. A same-CA leaf/key
replacement can retain the trust bundles. A CA replacement requires updating
the corresponding peer trust, images and manifest pins. Repointing old policy
at replacement images without new pins is refused.

After verifying actual logger delivery, save the new declaration. Cold restore
requires those retained offline assets; private keys, live sessions, volatile
logs and queues are not exported or restored. Rollback is explicit stop/start
with the old manifest and retained images. Replacement has downtime and may
lose unsent volatile messages. This adds no live reload, automatic renewal,
CRL/OCSP, ACME, durable sender retry or delivery acknowledgement.

The dedicated native scenario requires pre-allocation validity/purpose/trust/
name refusal, stale-pin refusal, actual guest logger storage and independent
mutual-TLS framed messages, served collector leaf DER fingerprints, both leaf/
key replacements under one CA, CA replacement with rejection of old trust and
old client credentials, distinct reciprocal issuing CAs, cold restore and
explicit rollback. It also checks configuration/identity conformity, key
isolation, unchanged retained base identities and host network invariants.
Original Syslog TLS, HTTPS lifecycle/persistent HTTPS and general CI are
selected regressions. Exact results are recorded in LAN_NEXT_STEPS.md.

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 \
  -f suite=syslog-tls-lifecycle
```

Remaining LAN work precedes GUI. Static VXLAN with explicit VTEP/VNI/VLAN
mapping remains required; EVPN/BGP remains separate later work.
