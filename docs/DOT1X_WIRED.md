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
open the port. The exchange has one 1..5-second deadline, at most two RADIUS
requests and a 64-discard budget; it performs no fallback or automatic retry.

Successful authentication installs a kernel admission element with an explicit
1..30-second timeout (`dot1x.seconds`, default 5). The worker sends EAP Success,
monitors Logoff and then closes the gate before returning a final result.
Logoff closes early. A new Start during an authorized window ends this finite
session; it does not create an unlimited reauthentication loop. Normal expiry
removes admission automatically. Even SIGKILL cannot extend the kernel lease:
data may remain admitted for the remaining lease, at most the configured
seconds, and then is blocked without worker cleanup. Immediate SIGKILL
revocation is not claimed. A new explicit command is required for a new window.

A passed result means a verified admission occurred and final closure was
confirmed; it does not certify application traffic or a zero-loss interval.
`inspect` exposes gate conformity and actual kernel admission separately.
Privileged rule deletion/edit invalidates the managed guarantee and is refused
by save/new authentication rather than silently adopted or repaired.

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

This is one finite untagged wired EAP-MD5 session, not a persistent managed
supplicant/authenticator service. Automatic reauthentication, multi-client
ports, trunks/LAGs, other security compositions, dynamic VLANs, MACsec,
EAP-TLS/PEAP/TTLS and accounting remain separate work. EAP-MD5 does not supply
mutual EAP authentication, confidentiality or link keys. The backend's
explicit private asset requirements remain in force.

The dedicated native test uses unmodified wired wpa_supplicant and actual
FreeRADIUS. It checks a working uncontrolled uplink while peer data is blocked,
EAPOL Identity/MD5/Success and RADIUS State captures, bidirectional data during
admission, expiry, wrong credentials/identity, Logoff, SIGKILL kernel expiry,
backend outage, saved recreation starting closed, separate-CLI teardown during
active admission, gate-drift refusal and host isolation. Local tests additionally
cover replayed identities, queued Logoff before backend Success, runtime and
namespace/interface generation refusal, and unconfirmed SIGKILL cleanup. Exact
validation evidence and limits are recorded in LAN_NEXT_STEPS.md.

References: [wpa_supplicant](https://w1.fi/wpa_supplicant/),
[nftables timeout elements](https://wiki.nftables.org/wiki-nftables/index.php/Element_timeouts),
[RFC 3579](https://www.rfc-editor.org/rfc/rfc3579.html) and
[RFC 3748](https://www.rfc-editor.org/rfc/rfc3748.html).
