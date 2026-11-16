# Offline HTTPS identity validation and replacement

The HTTPS rootfs builder and startup preflight validate the supplied local
leaf/chain using only its declared CA bundle. A short TLS exchange occurs
entirely between memory BIOs: there are no sockets, host trust roots, network
requests or copied CA signing keys. OpenSSL performs chain/time/server-purpose
validation through Python's SSL client. Existing key matching, public pins,
private-key permissions and size bounds remain enforced. Invalid assets are
refused before the lab allocates namespaces or containers.

Expired, not-yet-valid, untrusted and client-only certificates fail even if the
manifest explicitly pins their bytes. The host's current clock is authoritative
for this local check. It does not validate the manifest IP/DNS identity, perform
revocation checks, fetch intermediates or establish that a running daemon uses
these files. Clients continue to choose an explicit CA and verify the live
peer's name/IP. Existing inspection remains an asset/configuration observation;
it does not continuously reevaluate expiry or replace client handshakes.

To replace a leaf and key under the same CA:

1. Obtain a new server certificate/chain and matching unencrypted mode-0600
   private key, keeping the required IP/DNS SANs. Retain the old image if an
   explicit rollback is needed. No signing key is supplied to Network-LABS.
2. Build a **new** rootfs directory with `rootfs --nginx`, using the new
   `--https-certificate-file` and `--https-private-key-file` and the same
   `--https-ca-file`. See [HTTPS_SERVER.md](HTTPS_SERVER.md) for the full command.
3. Generate a new `example --https` manifest referencing that image and the
   existing client image. This creates the new public file pins. For the same
   lab name, stop the old lab before starting the replacement manifest.
4. Probe the replacement with the explicit CA, then save the new declaration.
   Cold restore requires that new image and matching offline assets.

For a CA change, build another image with the replacement CA and its issued
leaf/key, generate fresh pins, recreate the lab, and supply the new CA explicitly
to clients. An old-only trust bundle rejects the new identity even when the
server is healthy. Repointing an old manifest at new assets without updating
pins fails preflight. Changing policy on a running node requires recreation.
Replacement creates downtime; no in-place or automatic renewal is provided.

Rollback is another explicit stop/start with the old manifest and retained
conforming image, plus the corresponding client CA. Saved policy contains
public hashes and image references, never private-key PEM or TLS sessions.
The engine does not mutate retained base images or automatically select them.

The dedicated native test requires rejected expired/future/client-only/untrusted
images before resource allocation, a real original HTTPS peer, a new leaf/key
under the same CA, stale-pin refusal, a new CA with old-client-trust rejection,
live peer DER fingerprints matching each selected certificate, actual verified
TLS/HTTP, cold restore, explicit rollback, key isolation, unchanged base-image
identity hashes and host network invariants. The original persistent HTTPS and
general CI jobs are selected regressions. Exact evidence is recorded in
LAN_NEXT_STEPS.md; local skips are not native proof.

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 \
  -f suite=https-identity-lifecycle
```

Syslog TLS keeps its existing separate behavior; this increment does not add
Syslog certificate rotation, durable retry, ACME, revocation, live reload,
application authentication or a GUI. Remaining LAN work precedes GUI. Static
VXLAN VTEP/VNI/VLAN mapping and later separate EVPN/BGP remain on the roadmap.
