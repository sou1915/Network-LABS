# Finite wired 802.1X / EAP-MD5 admission

The explicit `dot1x` profile adds a real EAPOL authenticator and a Linux nftables
controlled-port gate. Exactly one directly connected peer with a declared MAC,
one two-port Linux bridge NAS, and one separate managed EAP-MD5 RADIUS server
share VLAN 1 and a connected IPv4 subnet. The NAS uses one numbered SVI as its
RADIUS client. There is no VLAN assignment, wireless mode or implicit CLI role
grant. The supplied identity allowlist is specifically for opening this port.

The gate is installed while interfaces are DOWN, before bridge membership or
forwarding is enabled. Before admission, both ingress and egress ordinary data
on the controlled port are dropped; EAPOL remains available. The uncontrolled
NAS/backend uplink remains usable. Peer data additionally requires the declared
source MAC. Authentication does not rely on a preconfigured neighbor entry or
a synthetic topology path.

## A deliberately finite session

`dot1x-auth LAB NAS` starts one owned host authenticator in the NAS namespace,
without retaining the lab lock during the exchange or authorization window.
The root worker has a pinned namespace/interface and runtime generation token;
lab teardown terminates its owned process group and confirms death after any
final SIGKILL before deleting containers. Unconfirmed death retains the worker
record and refuses namespace teardown. Save, stop and authentication reload
current runtime state under the lab lock, preserving other CLI workers.
Requests and backend secrets enter the worker on stdin, not argv or logs.
Only constant outcome/stage codes and gate metadata are reported.

The worker sends Request/Identity to the pinned peer and relays its responses to
the managed backend. Both RADIUS authenticators, opaque State, method and EAP
identifiers must verify through the MD5/Success sequence before admission. The
NAS never needs the peer's password. Disallowed identities, malformed EAPOL,
unverified backend responses, backend outage and unsupported methods do not
open the port. Each exchange has one 1..5-second deadline and at most two RADIUS requests.
The entire command has a shared 64-discard budget and performs no method/server
fallback or packet retransmission.

Successful authentication installs a kernel admission element with an explicit
1..30-second timeout (`dot1x.seconds`, default 5). The worker sends EAP Success,
monitors Logoff and then closes the gate before returning a final result.
Logoff closes early. A new Start during an authorized window ends this finite
session; it does not create an unlimited reauthentication loop. Normal expiry
removes admission automatically. Even SIGKILL cannot extend the kernel lease:
data may remain admitted for the remaining lease, at most the configured
seconds, and then is blocked without worker cleanup. Immediate SIGKILL
revocation is not claimed. By default a new explicit command is required for
a new window. Optional finite reauthentication is described below.

The live worker also subscribes to Linux link events for the pinned controlled
interface before sampling its administrative/carrier flags. Observed admin
DOWN or carrier loss ends the entire command with `status:blocked`,
`reason:LINK_LOST` and confirmed `port_closed:true` when cleanup succeeds.
An earlier admission remains historical (`authenticated:true`); unused
reauthentication cycles are discarded. A queued down/up pair still revokes
the old admission even if current flags have recovered. Link return requires
a new explicit command and complete EAP exchange. Checks run before backend
Success can grant admission and around the event wait (at most 100 ms per
wait, plus scheduling/processing/cleanup); zero-latency revocation is not
claimed. Interface deletion/replacement still requires the existing generation
and closure checks; unconfirmed closure reports unknown. Malformed, truncated,
overrun or excessive link events fail closed
with an unknown outcome. If the worker is killed or cannot confirm gate
closure, the existing finite kernel lease remains the independent bound.

A passed result means a verified admission occurred and final closure was
confirmed; it does not certify application traffic or a zero-loss interval.
`inspect` exposes gate conformity and actual kernel admission separately.
Privileged rule deletion/edit invalidates the managed guarantee and is refused
by save/new authentication rather than silently adopted or repaired.

## Optional finite reauthentication

Set `nodes[1].dot1x.reauthentications` to an integer from 0 to 3 before starting
the reference manifest. Omission or 0 preserves one admission. A value of 1
requests two complete authentications, 3 requests four; the command always ends
after its finite budget. The existing `dot1x.seconds` bounds each individual
kernel lease and `--timeout` bounds each authentication exchange. The controller
wait budget covers all requested exchanges and leases, plus cleanup overhead.

At the end of each lease the worker confirms gate closure **before** sending a
new Request/Identity. It clears the old RADIUS request, State and per-exchange
identity, and requires a fresh verified MD5/Success sequence to reopen. Each verified grant atomically replaces the verified gate with the same
closed-default policy plus exactly one size-one timeout admission. This avoids
relying on reclamation of an earlier timeout-set element. Policy drift refuses
before replacement. The same peer MAC and first authenticated username remain pinned; a different allowed
username is refused too. There is an intentional closed interval during each
exchange, so uninterrupted application sessions are not promised. No grace
lease or last-success fallback is installed when the backend is unavailable.
Logoff, peer Start during admission, drift or worker death ends the command;
there is no automatic worker restart or unbounded daemon. Logoff or peer Start
can end the command early; the completion count reports how many exchanges
actually admitted the peer.

Reports include `completed_authentications` and the total `radius_requests`.
`authenticated` records whether any verified admission happened earlier; it
alone is not a successful final outcome. A later authentication timeout reports
`status:unknown`, `reason:AUTH_TIMEOUT` and confirmed `port_closed:true` when
cleanup succeeds, even if the first exchange succeeded. Verified rejection
reports failed; identity changes report blocked. `inspect` includes the declared
reauthentication budget separately from the actual kernel admission.
Save/restore preserves the budget only, never a worker, completed cycle or lease.

## Optional backend session duration

An EAP-MD5 server user may declare `session_timeout` (integer 1..4294967295)
under `radius_server.users.USER`. The managed backend emits the standard
RADIUS `Session-Timeout` reply attribute. After verifying Access-Accept and
EAP Success, the wired worker installs a kernel lease of
`min(dot1x.seconds, Session-Timeout)`. The configured policy fingerprint and
default timeout stay unchanged; only the admission element is shortened.
The result reports `authorization_seconds` and `server_session_timeout`.
For example, add `"session_timeout": 3` alongside the existing digest and
private password path for the backend's `learner` user.

By default this backend attribute terminates the finite command after that
one admission, discarding unused local reauthentication cycles. A server
limit at or below the NAS limit reports `SERVER_SESSION_TIMEOUT`; an earlier
NAS limit reports `LEASE_EXPIRED`. Both require confirmed gate closure for a
passed result. A new explicit authentication is needed for another grant.
Without the attribute, the existing bounded reauthentication behavior stays
unchanged. Zero, duplicate or malformed duration attributes are refused before
admission. These checks apply to authenticated Accepts, not unverified replies
or Challenges.

An EAP-enabled backend user may also declare `"termination_action": 1`
(RADIUS-Request), requiring `session_timeout`. Verified Termination-Action 1
allows a fresh exchange when the effective lease expires, only within the
NAS's existing `dot1x.reauthentications` budget (0..3). The old gate closes
first; each new grant requires a complete verified EAP exchange with fresh
State and the pinned identity. NAS duration/budget bounds always apply.
Budget zero still permits only one grant; exhaustion ends closed, even when
the server asks again. There is no grace lease, automatic restart or fallback
to an earlier success when RADIUS is unavailable. The final result reports
`server_termination_action` (0 by default). Explicit 0 retains termination;
action 1 without Session-Timeout, values other than 0/1, and malformed or
duplicate action attributes are refused before admission. The managed server
configuration accepts an explicit action only alongside the duration. The
native evidence for bounded server-requested renewal is recorded below.

This setting is EAP-only; PAP user configuration rejects it. The standalone
EAP diagnostic still reports authentication rather than opening any port or
enforcing a session. Save/restore retains the declared integer, never a lease.
The dedicated native duration evidence is recorded below.

Gate observation interprets libnftables JSON `timeout`/`expires` in seconds;
an omitted element timeout inherits the actual set default. These JSON values
have whole-second precision. Fractional changes made by a privileged external
writer are not certified by this observation. The managed admission command
uses explicit integer-second kernel timeouts. See the
[JSON schema](https://manpages.debian.org/bookworm/libnftables1/libnftables-json.5.en.html)
and [RADIUS Session-Timeout](https://www.rfc-editor.org/rfc/rfc2865#section-5.27).

## Server-requested renewal validation — 2026-11-06

Implementation `9329910fd9fd4b61a4c6ad8ab4e6f01d0aa9e9aa` adds
verified Termination-Action=RADIUS-Request (1) to the finite wired EAP-MD5
profile. EAP-enabled backend users may declare `termination_action` 0/1
alongside required `session_timeout`. Action 1 permits fresh authentication
after the effective lease expires, within the existing local 0..3 renewal
budget only. Each old gate closes before a fresh EAP exchange; request/State
and per-exchange policy reset, with identity pinned. Action 0/default keeps
one admission when Session-Timeout is present. Missing duration with action 1,
unsupported values and malformed/duplicate policy attributes refuse admission.
The result also reports `server_termination_action`; there is no grace lease,
implicit worker restart or fallback to a previous success.

The [dedicated wired native job](https://github.com/sou1915/Network-LABS/actions/runs/42243831204/job/127980741652)
passed the full extended scenario in 196.309 seconds. Real wpa_supplicant and
FreeRADIUS produced two MD5/Success cycles and exactly four Access-Requests
with four distinct request authenticators and two fresh State values. Both
Accepts carried Session-Timeout 3 and Termination-Action 1 under a 30-second
NAS ceiling and local budget 1. Second-lease bidirectional data worked; budget
exhaustion completed closed after two admissions. Backend loss after the first
grant returned unknown/AUTH_TIMEOUT with one admission, three requests,
historical authenticated=true and confirmed closure. Saved recreation started
closed, retained both policy fields/budget and completed two healthy admissions
with four requests. Previous duration/SIGKILL/carrier/denial/reauthentication/
drift/teardown controls and host namespace/link/IPv4/IPv6 route/rule invariants
passed. Both selected jobs passed; 58 others were intentionally skipped.
Local full tests passed 1006 cases in 30.862 seconds with 162 environment
skips; compile/diff/link checks passed. Unit coverage includes budgets 0/1/3,
fresh State/closed transitions, backend outage/rejection and identity changes.
No failed native run preceded this increment.

## Backend duration validation — 2026-11-06

Implementation `d71a8ba7c2e95fbfaa3040aab6c96db9b0aae185` and
correction `78b44e1acbac047a2aa5fe7cb1e6246e781b814f` add verified
RADIUS Session-Timeout enforcement to finite wired admission. EAP-enabled
backend users may declare a positive uint32 `session_timeout`; the managed
server emits the standard attribute. Only after authenticated Access-Accept
and EAP Success does the NAS grant `min(local seconds, server timeout)`.
Presence of the attribute ends the finite command after that admission,
discarding unused renewals. Results report effective/server seconds and
SERVER_SESSION_TIMEOUT or the earlier local LEASE_EXPIRED. Missing attributes
preserve existing finite reauthentication. Zero/duplicate/malformed durations
and unsupported or ambiguous Termination-Action are refused before admission.
PAP-only server user configuration rejects the new field.

The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42240831488/job/127970370968)
passed the extended real supplicant/FreeRADIUS scenario in 160.962 seconds at
`78b44e1`. Captured Access-Accept carried timeout 3; the kernel element used
3 seconds under a 30-second NAS bound, before and after cold restore. Each
command completed only one admission/two requests despite unused renewals.
SIGKILL still expired the shortened kernel lease. A 20-second backend limit
could not extend a 2-second NAS limit. A foreign 10-second element under that
2-second policy invalidated observation and refused save/new authentication.
Existing denial/reauthentication/carrier/expiry/Logoff/drift/teardown controls
and host namespace/link/IPv4/IPv6 route/rule invariants passed. Both selected
jobs passed; 58 others were intentionally skipped. Local full tests passed
1003 cases in 30.905 seconds with 162 environment skips; compile/diff/link
checks passed.

Initial run 42239853939 at `d71a8ba` failed the new native assertion expecting
3000 where nft JSON returned 3. Review of libnftables documentation/source
confirmed whole-second timeout/expiration output. Correction `78b44e1` fixes
both the test and pre-existing runtime inspection's milliseconds assumption,
checks strict integer bounds, and uses the actual set default when an element
omits its timeout. The new real oversized-element refusal verifies the runtime
repair. JSON whole-second precision does not certify fractional edits by an
external privileged writer; managed leases use explicit integer seconds.

## Reference setup

Build the matching EAP-MD5 FreeRADIUS rootfs and prepare the root-owned private
password asset as described in [RADIUS_EAP_MD5.md](RADIUS_EAP_MD5.md). Then:

```bash
umask 077
sudo python3 -m network_labs.appliances example --radius --radius-eap-md5 --dot1x \
  --rootfs /absolute/rootfs-eap --radius-user learner \
  --radius-password-file /absolute/root-owned-password \
  --radius-secret-file /absolute/shared-secret > dot1x.json
sudo python3 -m network_labs.appliances start dot1x.json
python3 -m network_labs.appliances plan dot1x.json
```

`plan` shows the PC1 namespace. Run an independent host `wpa_supplicant` in that
namespace, with a private root-owned configuration (mode 0600):

```text
ap_scan=0
network={
  key_mgmt=IEEE8021X
  eap=MD5
  identity="learner"
  password="YOUR_LAB_PASSWORD"
  eapol_flags=0
}
```

```bash
sudo ip netns exec PC1_NAMESPACE wpa_supplicant -D wired -i eth0 \
  -c /absolute/private-supplicant.conf
```

This supplicant is an independently managed peer, not a guest-image daemon or
an engine-persisted credential. Stop it before lab teardown. In another terminal:

```bash
sudo python3 -m network_labs.appliances dot1x-auth dot1x-lan SW1 --json
```

While its authorization window is active, another terminal can execute a PC1
ping to PC2 through the existing node exec command. Before the command and after
its finite lease, data is blocked. To allow more time for manual observation,
set `nodes[1].dot1x.seconds` to at most 30 in the manifest before starting; NAS
policy/topology edits require recreation. Save/restart retains only the declared
policy and starts closed, never from a saved authorization or worker token.

## Current limits and validation

This is a finite untagged wired EAP-MD5 command with optional bounded
reauthentication, not a persistent managed supplicant/authenticator service.
Unbounded reauthentication, multi-client ports, trunks/LAGs, other security
compositions, dynamic VLANs, MACsec,
EAP-TLS/PEAP/TTLS and accounting remain separate work. EAP-MD5 does not supply
mutual EAP authentication, confidentiality or link keys. The backend's
explicit private asset requirements remain in force.

The dedicated native test uses unmodified wired wpa_supplicant and actual
FreeRADIUS. It checks a working uncontrolled uplink while peer data is blocked,
EAPOL Identity/MD5/Success and RADIUS State captures, bidirectional data during
admission, expiry, wrong credentials/identity, Logoff, SIGKILL kernel expiry,
backend outage, saved recreation starting closed, separate-CLI teardown during
active admission, gate-drift refusal and host isolation. The finite-reauthentication
extension also captures two actual EAPOL/RADIUS cycles, fresh State/request
authenticators, second-lease bidirectional traffic, backend loss between cycles
and recovery after saved recreation. The boundary scenario also requires four
complete authentications at the maximum configured budget, exactly eight
captured RADIUS requests with fresh authenticators/State, and no further grant
after SIGKILL during the second lease. Local tests additionally
cover bounded reauthentication, fresh State, identity pinning, replayed
identities, queued Logoff before backend Success, runtime and
namespace/interface generation refusal, and unconfirmed SIGKILL cleanup. Exact
validation evidence and limits are recorded in LAN_NEXT_STEPS.md.

The carrier extension adds sustained peer-down and rapid down/up fixtures
with a 30-second lease and unused renewals: both must end before lease expiry,
remain closed after link return and preserve the uncontrolled backend path.
Saved recreation must start closed and recover only through a new explicit
exchange with actual RADIUS packets and bidirectional data.

Implementation `73a3c56497d95b58dafd8998c598d8151fb0a0f7` adds
controlled-link revocation to the existing finite wired EAP-MD5 profile.
The live worker subscribes to pinned-namespace Linux link events before
sampling flags, checks administrative/carrier state around its bounded wait
and before granting backend Success, and remembers queued down/up loss.
Observed link loss terminates the command with `blocked/LINK_LOST`, closes
the verified gate and discards unused reauthentication cycles. Historical
`authenticated:true` does not mean the peer remains admitted. Link return
requires a new explicit authentication. Truncated/overrun/excessive events
fail closed with an unknown result; runtime/interface generation and gate
closure checks still apply. Scheduling/cleanup latency and the independent
kernel lease after worker death remain explicit limits.

The [dedicated wired native job](https://github.com/sou1915/Network-LABS/actions/runs/42232715325/job/127942385678)
passed the full extended scenario in 128.714 seconds. Real supplicant/RADIUS
admission with a 30-second lease and unused renewals was revoked after both
sustained peer-down and rapid down/up, before lease expiry. Both returned
LINK_LOST with one completed admission/two RADIUS requests and confirmed
closure; neither resumed authorization on link return. The uncontrolled
NAS/backend path survived. Saved recreation started closed; a new explicit
exchange captured two Access-Requests and Challenge/Accept and restored
bidirectional traffic, then Logoff closed the gate. Existing expiry, denial,
reauthentication, worker-kill, teardown, drift and host-isolation checks passed.
Both selected jobs passed, including general CI; 58 others were intentionally
skipped. Local tests passed 998 cases in 30.643 seconds with 162 environment
skips; compilation, diff and documentation-link checks passed. No failed
native run preceded this result.

References: [wpa_supplicant](https://w1.fi/wpa_supplicant/),
[nftables timeout elements](https://wiki.nftables.org/wiki-nftables/index.php/Element_timeouts),
[RFC 3579](https://www.rfc-editor.org/rfc/rfc3579.html) and
[RFC 3748](https://www.rfc-editor.org/rfc/rfc3748.html).
