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
DOWN, carrier loss or deletion ends the entire command with `status:blocked`,
`reason:LINK_LOST` and confirmed `port_closed:true` when cleanup succeeds.
An earlier admission remains historical (`authenticated:true`); unused
reauthentication cycles are discarded. A queued down/up pair still revokes
the old admission even if current flags have recovered. Link return requires
a new explicit command and complete EAP exchange. Checks run before backend
Success can grant admission and around the event wait (at most 100 ms per
wait, plus scheduling/processing/cleanup); zero-latency revocation is not
claimed. Malformed, truncated, overrun or excessive link events fail closed
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
exchange with actual RADIUS packets and bidirectional data. Native validation
of this extension is pending.

References: [wpa_supplicant](https://w1.fi/wpa_supplicant/),
[nftables timeout elements](https://wiki.nftables.org/wiki-nftables/index.php/Element_timeouts),
[RFC 3579](https://www.rfc-editor.org/rfc/rfc3579.html) and
[RFC 3748](https://www.rfc-editor.org/rfc/rfc3748.html).
