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
Managed server lifecycle and actual login/802.1X enforcement remain subsequent
AAA work.
