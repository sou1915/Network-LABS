# RADIUS PAP authentication observation

`radius-auth` sends one real IPv4 UDP/1812 Access-Request from a running
single-interface OCI host. The RADIUS server must already exist, be reachable,
and recognize the node's **observed source IPv4** as a NAS/client with the same
shared secret. This command supplies an AAA diagnostic building block; it
does not install a server, create users, change node login policy or enforce
switch admission.

The request contains User-Name, User-Password, NAS-IP-Address and a mandatory
Message-Authenticator. It uses fresh random request authenticators/identifiers.
The client verifies the response identifier, source IP/port, packet/attribute
lengths, Response Authenticator and exactly one valid Message-Authenticator.
Missing or invalid authenticators are discarded, with no legacy fallback.
Configure the server to require Message-Authenticator in requests and include
it in all responses, including rejects. See [RFC 2865](https://www.rfc-editor.org/rfc/rfc2865.html),
[RFC 2869 section 5.14](https://www.rfc-editor.org/rfc/rfc2869.html#section-5.14)
and [FreeRADIUS guidance](https://www.freeradius.org/vul_notifications/2024/07/09/blastradius.html).

PAP password hiding uses the historical RADIUS MD5 construction; this is not
TLS or modern transport encryption. Use this profile only with disposable lab
credentials on an isolated trusted network. A shared secret authenticates a
peer that knows that secret; it is not a public-key server identity.

## Run against an existing server

The command takes the actual running lab name, source node, literal remote
IPv4 server address and `--username`. Required `--password-file` and
`--secret-file` arguments name private regular files (mode 600, no symlinks).
Each contains one UTF-8 credential; one final LF is removed. Passwords are
1..128 encoded bytes without NUL/newlines. Shared secrets are 16..128 printable
ASCII characters without spaces. Usernames are 1..64 characters from
`A-Z a-z 0-9 _ . @ -`. No passwords or secrets are accepted as CLI values.
`--timeout` sets an overall 1..5-second deadline (default 3); `--json` emits
structured evidence. For example, **only if** `micro-lan` is already running
and its PC2 server is configured for PC1:

```bash
sudo python3 -m network_labs.appliances radius-auth micro-lan PC1 192.0.2.20 \
  --username learner --password-file ./radius-password.txt \
  --secret-file ./radius-secret.txt --json
```

Create these files privately using an editor and disposable credentials;
`chmod 600 radius-password.txt radius-secret.txt` sets their required mode.
The command above does not create or configure a PC2 server.

The client runs host Python in the managed source network namespace, bound to
its observed IPv4. Credentials travel over the child's stdin pipe, never argv,
saved lab state or the returned report. They remain in process memory during
the command. No credentials, raw packet bytes, Reply-Message or State attribute
values are included in reports. `capture`/external packet capture can still
record the PAP wire exchange; RADIUS is not transport encryption.

## Interpret results

| Result | Meaning |
|---|---|
| `passed`, `accepted` | Both authenticators verified on Access-Accept. The command grants no access and applies no returned policy. |
| `failed`, `rejected` | Both authenticators verified on Access-Reject. This does not prove the password alone was wrong. |
| `blocked`, `challenge` | Both authenticators verified on Access-Challenge. No challenge reply or session is attempted. |
| `unknown` | No verified decision: timeout, 64-datagram limit, transport problem or unavailable worker evidence. |

Malformed, wrong-peer or unverifiable responses increment `discarded_responses`
and cannot extend the deadline. There is exactly one request and no retries,
fallback server, DNS, IPv6, accounting, authorization enforcement, EAP/802.1X,
CHAP, TACACS+, RadSec or challenge continuation. A timeout does not establish
whether the cause is routing, firewall, credentials or server configuration.
Exit status is zero only for a verified Access-Accept.

Tests exercise real localhost UDP with an independent test responder,
PAP's published RFC 2865 section 7.1 vector, multi-block/UTF-8 passwords,
authenticated Accept/Reject/Challenge, invalid MAC/length/identifier/duplicate
attributes, missing Message-Authenticator, silence and credential handling.
An opt-in native test exercises Accept/Reject across actual veth/bridge nodes
using a deterministic Python responder. It is separate from the real server
interoperability test and is skipped without the privileged native environment.

## Independent FreeRADIUS interoperability

`test_radius_freeradius.py` runs an actual FreeRADIUS 3 daemon on an ephemeral
localhost UDP port, with private temporary configuration and the installed PAP
module/dictionaries. It validates authenticated Accept for ordinary, UTF-8 and
128-byte passwords, authenticated Reject for a wrong password and unknown user,
and the server's silent discard of requests with missing/incorrect
Message-Authenticator. It then terminates its process group and checks the
listener port can be bound again. This test passed locally with the Ubuntu
FreeRADIUS **3.2.5** executable and libraries extracted from distribution
packages; no system server was installed or started for that run.

The dedicated `radius-interop` CI job installs the independent server on a
disposable Ubuntu 24.04 runner and explicitly runs:

```bash
env NETWORK_LABS_RADIUS_INTEROP=1 python3 -m unittest discover -s tests -p test_radius_freeradius.py -v
```

Without that opt-in, ordinary test discovery skips the real daemon test.
With opt-in, a missing binary/module/dictionary is a failure, not a silent skip.
The fixture creates no system service or `/etc/freeradius` configuration. It
uses the same executable bytes from a temporary path to avoid attaching the
host service's pathname profile to its private configuration, without changing
host security policy. No debug `-X` mode is used; password logging is disabled.
For offline package extraction, `NETWORK_LABS_FREERADIUS_ROOT` may name the
trusted extracted root; its libraries are selected only for the test child.

This localhost test proves the bounded PAP client's interoperability with that
server/version. It does not establish native namespace/OCI daemon lifecycle,
other versions/backends, challenge continuation or actual access enforcement.
The managed server profile below adds native lifecycle; its container test is
separate from this localhost interoperability check. Actual login/802.1X
enforcement remains subsequent AAA work.

## Experimental managed server

`example --radius` creates `radius-lan`: PC1 (`192.0.2.10`), SW1 and a real
FreeRADIUS 3 PAP server in PC2 (`192.0.2.20`). The daemon runs **inside PC2's OCI
container**, using the container's cgroup and namespaces. It binds only the
declared IPv4/UDP1812, recognizes only declared NAS/client addresses and always
requires request Message-Authenticator. Accept and Reject replies include a
Message-Authenticator. There is no host daemon or automatic fallback service.

Build a **new** rootfs with trusted matching FreeRADIUS executable, PAP module
directory and complete dictionary directory. The builder copies their ELF
dependencies offline; it does not install a package or start a host service.
For the supported OpenSSL 3 layout it also copies `ossl-modules/legacy.so`
beside the resolved libcrypto and that provider's dependencies. FreeRADIUS
loads this provider during startup even for PAP; `ldd` alone does not list it.
An unavailable matching provider fails the build before creating the rootfs.
Rebuild rootfs images made before this provider-copy fix; updating Python code
does not add missing files to existing images.
Only `rlm_pap.so` is enabled. Dictionaries are bounded to 1024 regular files and
16 MiB; dictionary symlinks are rejected. The initial supported layout is the
Debian/Ubuntu FreeRADIUS 3 layout used by the native CI job.

First prepare `radius-password.txt` and `radius-secret.txt` as private mode-600
files using disposable lab credentials. For this server profile, the shared
secret must be 16..128 ASCII letters/digits or `_ . ~ -`; this excludes config
interpolation/quoting characters. The password has the client limits above.
With the prerequisites already installed and the destination rootfs absent:

```bash
umask 077
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --freeradius /usr/sbin/freeradius --freeradius-modules /usr/lib/freeradius \
  --freeradius-dictionaries /usr/share/freeradius --output "$HOME/network-labs-radius-rootfs"
python3 -m network_labs.appliances example --radius --rootfs "$HOME/network-labs-radius-rootfs" \
  --radius-user learner --radius-password-file ./radius-password.txt \
  --radius-secret-file ./radius-secret.txt > radius-lan.json
sudo python3 -m network_labs.appliances start radius-lan.json
sudo python3 -m network_labs.appliances radius-auth radius-lan PC1 192.0.2.20 \
  --username learner --password-file ./radius-password.txt --secret-file ./radius-secret.txt --json
sudo python3 -m network_labs.appliances inspect radius-lan PC2
```

The example hashes the user's password with SHA-256 before writing the manifest;
the clear password is absent from the generated manifest and daemon config.
These fast unsalted hashes are for disposable labs, not a production password
database. Shared secrets must remain available to FreeRADIUS in clear form:
the manifest, recorded/startup state and generated config contain them. The
loader rejects group/other manifest permissions, and the container config directory/file
are mode 700/600. Protect any explicit `example`/`export` output; those commands
intentionally emit a reusable credential-bearing manifest. Normal CLI results
redact server secrets/password digests. Inspection returns client addresses,
user count and configuration/permission conformity, never credential values.

The `radius_server` field accepts one numbered UP single-interface OCI host,
1..8 distinct static IPv4 clients belonging to other managed OCI hosts, and
1..16 users. Each client contains `address` and `secret`; each user entry contains
only a lowercase 64-character `password_sha256`. Separate nodes are required
for other services. IPv6, arbitrary startup, alias/subinterface combinations
and live server policy edits are rejected in this initial profile.

Start validates the generated policy without echoing parser output, starts
FreeRADIUS in foreground single-process mode under the container and waits up
to five seconds for its readiness message. Authentication/password logging and
debug `-X` are disabled; the daemon log is private. A readiness message does not
guarantee future liveness. `inspect` and save-time drift checks compare the
config digest and root-owned 600/700 file/directory permissions; they do not
establish authentication or daemon health. Use `radius-auth` for real packets.

`save`, stop and `restore` preserve declared policy/credentials using the normal
private startup manifest, not live sessions or a filesystem snapshot. Stop
destroys the OCI daemon with the node. Recreate the lab for policy changes.
The fast `radius-interop` CI job includes a privileged test of the actual copied
daemon/PAP dictionaries inside OCI nodes: Accept, Reject, undeclared client,
wrong secret, private inspection and saved restart. This native test is skipped
in development environments without the required namespace/container support;
its result must be checked separately from the passing localhost daemon test.
Both checks passed for the provider-copy fix in commit `8e33f51`: see the
[dedicated RADIUS CI job](https://github.com/sou1915/Network-LABS/actions/runs/40709234559/job/122889633874).
That result covers this bounded RADIUS scenario, not the entire native suite;
managed STP/LACP restore-path reconciliation and its separate validation are
described in [Native LAN core](NATIVE_LAN_CORE.md#configuration-live-partielle).

This is still PAP authentication observation only: no SSH/Telnet login adapter,
port admission, EAP/802.1X, accounting, challenge continuation, authorization
enforcement, TACACS+ or RadSec is provided.


## Passive daemon and listener evidence

`inspect` now reports three independent observations for a managed server:
configuration conformity, `process` (PID file plus exact expected `/proc/PID/cmdline`)
and `udp_socket` (IPv4 UDP/1812 table in the node network namespace).
A process can be `observed`, `mismatch` or `unknown`. Missing or invalid PID
files and unavailable command lines are unknown, not proof of a stopped daemon.
Unexpected argv and exception contents are not echoed into the report.

The socket is `observed` only for an unconnected UDP binding to the declared
IPv4/1812. `absent` requires a successfully decoded table without that exact
binding; a failed read is `unknown`. Wildcard bindings remain visible as
separate evidence. The table does not attribute a binding to FreeRADIUS.
All readings are sequential; PID reuse and intervening changes remain possible.
Neither process nor socket evidence proves a working authentication exchange.

A daemon can stop while its configuration still verifies. Save drift checks
continue to check configuration; they do not treat these passive readings as
a server readiness guarantee. `radius-exec` must still receive a verified
Accept on every invocation, with no local fallback. The native test now covers
wrong shared secret and actual daemon termination, asserting no diagnostic
process is invoked in either case. These additional cases await native CI.
