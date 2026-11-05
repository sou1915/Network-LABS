# Bounded EAP-MD5 over RADIUS diagnostic

`radius-eap-md5` observes an actual two-request EAP-MD5 exchange with a remote
IPv4 RADIUS backend from a managed NAS network namespace. It verifies the
RADIUS Response Authenticator and Message-Authenticator before using any EAP
challenge or State, then requires the matching final EAP Success or Failure.
It never opens a shell, changes a port, installs authorization or sends EAPOL.
This diagnostic is an EAP protocol foundation. The separately implemented
[finite wired 802.1X profile](DOT1X_WIRED.md) builds a controlled port on that
foundation; the diagnostic command itself still installs no admission.

The sequence is EAP Response/Identity inside Access-Request, verified
Access-Challenge carrying a 16-byte MD5 challenge and one nonempty opaque State,
then EAP Response/MD5 with exactly that State inside a fresh Access-Request.
Only a matching EAP Success inside verified Access-Accept passes. Early accepts,
other methods, malformed lengths, duplicate/missing State, a second challenge
or mismatched final identifiers remain unknown. Verified rejects fail. Invalid
or replayed RADIUS replies are discarded, with at most 64 invalid packets total.
Both requests share one 1..5-second deadline; neither is retransmitted and no
PAP/TLS/alternate-server fallback occurs.

EAP-Message fragments are joined only when consecutive and within the 1024-byte
EAP budget. The existing 4096-byte RADIUS bounds remain. State, raw attributes,
passwords and shared secrets are omitted from reports. Credentials enter the
isolated worker on stdin, never argv. The NAS source address is observed and
bound explicitly; a local/loopback backend target is refused.

## Explicit backend and private asset

PAP-only images and configurations retain their defaults. An EAP-MD5 backend
must explicitly enable `radius_server.eap_md5:true`, package matching modules,
and supply a private `password_file` for every declared user. The existing
`password_sha256` pins its printable ASCII password bytes (an optional final LF is
removed). The method needs the original password; a SHA-256 digest alone cannot
replace it. The file must be a regular nonsymlink file, mode 0600, owned by the
runtime user (root for native lifecycle), with one hard link and at most 128
password bytes. The first managed profile accepts printable ASCII passwords only.

The asset remains on the host. Startup checks its ownership, bounds and digest
before allocating a lab. Only the separate server's private 0700 configuration
directory receives its Cleartext-Password as a safely escaped, single-quoted literal in
a 0600 file. Single quotes prevent attribute expansion.
The generic rootfs, other nodes, manifest, startup.json and CLI reports do not
receive password bytes. The server configuration contains the method's original password; its privacy
is provided by ownership and permissions.
Keep the trusted offline file for cold recreation. Missing or changed assets
refuse startup/save; changing the file does not reload an already running daemon.

Build trusted matching modules with the existing FreeRADIUS assets:

```bash
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --output /absolute/rootfs-eap --freeradius /usr/sbin/freeradius \
  --freeradius-modules /usr/lib/freeradius \
  --freeradius-dictionaries /usr/share/freeradius --freeradius-eap-md5
```

Some installations use `/usr/lib/x86_64-linux-gnu/freeradius`. The explicit build
adds matching `rlm_eap.so` and `rlm_eap_md5.so` with resolved ELF dependencies.
No password asset is copied into the rootfs. The backend's EAP state is volatile,
limited to 32 sessions and a five-second state lifetime. PAP remains usable on
that backend; existing PAP access gates do not switch methods implicitly.

Prepare a persistent root-owned password file privately, then generate the
standalone reference as root so the CLI can read it:

```bash
umask 077
sudo python3 -m network_labs.appliances example --radius --radius-eap-md5 \
  --rootfs /absolute/rootfs-eap --radius-user learner \
  --radius-password-file /absolute/root-owned-password \
  --radius-secret-file /absolute/shared-secret > eap.json
sudo python3 -m network_labs.appliances start eap.json
sudo python3 -m network_labs.appliances radius-eap-md5 radius-lan PC1 192.0.2.20 \
  --username learner --password-file /absolute/root-owned-password \
  --secret-file /absolute/shared-secret --timeout 3 --json
```

The reference excludes SSH/Telnet/shell/accounting and combined dual-stack
example options. The diagnostic can target an explicit remote backend satisfying
this bounded protocol; a passed observation is not a grant of device/network
access. EAP-TLS, PEAP/TTLS, wireless keys, supplicant/authenticator lifecycles,
EAPOL forwarding and controlled-port enforcement are not implemented here.
EAP-MD5 itself supplies neither mutual EAP authentication, confidentiality nor
key derivation; the RADIUS hop's authenticators do not create a TLS tunnel.

The dedicated native scenario uses real FreeRADIUS, checks Identity/Challenge/
MD5/Success packets and exact State/proof bytes, rejects wrong passwords/users,
refuses wrong shared secrets, retains PAP compatibility, tests asset drift,
backend outage/recovery and declarative cold restart, and checks host isolation.
The successful dedicated native job and local results are recorded in
LAN_NEXT_STEPS.md. The native password includes quotes, a backslash and
expansion-like text to verify literal handling; raw EAP packets still contain
only the method proof, not the password.

Protocol references: [RFC 3579](https://www.rfc-editor.org/rfc/rfc3579.html),
[RFC 3748 section 5.4](https://www.rfc-editor.org/rfc/rfc3748.html#section-5.4),
and the [FreeRADIUS EAP-MD5 module](https://networkradius.com/doc/current/raddb/mods-available/eap/md5.html).


A separately explicit [finite wired controlled-port profile](DOT1X_WIRED.md)
now builds on this backend using real EAPOL pass-through and a kernel timeout
gate. The raw `radius-eap-md5` diagnostic itself still changes no access policy.
