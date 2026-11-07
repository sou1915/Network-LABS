# Network-LABS: Codex handoff — 2026-11-04

## Authoritative GUI reference supplied by user

The user explicitly rejected both workspace_design.png and enterprise_lan.png
as the agreed GUI. The actual reference is now retained at
[agreed-gui-reference.jpg](images/agreed-gui-reference.jpg). This overrides
all earlier statements calling the recent embedded workbench the agreed UI.
It is a working backend prototype, not visual acceptance.

Implement the reference's application shell: top menus/action toolbar and
Topologie/Équipements/Scénarios/Captures navigation; searchable equipment
library with device thumbnails/categories on the left; large topology with
port/subnet annotations and coloured VLAN/DMZ groups; selected-device GUI/CLI
panel on the right; docked device console tabs below; adjacent traffic events,
packet details/logs and observed path. Preserve real native operations and
honest capability boundaries. The pictured device brands, firmware screens,
wireless and live traffic are design examples, not proof of implemented native
support. Do not mark them functional or manufacture traffic events. Prioritise
the shell and essential native workflows, then graphical editing and supported
configuration. Keep providing real implementation screenshots. LAN core stays
accepted; VXLAN remains tracked after LAN/GUI.

## Current rounded-panel and native web checkpoint

User explicitly requires rounded edges throughout the GUI and better web
virtualisation/management. Source `d0e6df1e507e568aec406d4755b76e13a35fdc90` expands rounded surfaces to
the header, tabs, library/topology/device panels, diagnostics/events/interface
tables, management sections and scrollbar thumbs. Preserve the supplied
reference palette. **Gestion web** now opens an actual native-management page
in the browser, sharing the validated project draft with Tk. The previous
pedagogical portal was not wired to native OCI projects.

Web name/IP/gateway/admin edits synchronize with the GUI. Routes/firewall
policy are read-only declared configuration. Changes remain offline drafts:
save/stop/start to apply them in Linux. No guest HTTP service or vendor firmware
is claimed. The native adapter reuses authenticated loopback HTTP and Tk-thread
dispatch, protects stale edits/pending operations, and returns only selected
public configuration fields. No sudo/backend command is exposed through HTTP.

Local full regression with actual Chromium acceptance passed 1054 cases
(55.851 s, 141 skips); an additional switch/DHCP readonly test passed separately.
Browser-driven edits, invalid-write recovery, same-tab switching and actual Tk
synchronization passed. The actual local browser screenshot and provenance are
retained as native-web-management.png / native-web-provenance.json. No native
lab was started for that local browser capture. The dedicated GitHub native
scenario now applies CLIENT3's actual address through HTTP before real probes.
See NATIVE_GUI_FLOW.md. LAN core stays frozen; VXLAN remains later.

## Previous GUI typography and interaction checkpoint

Latest user feedback rejects the old typeface and sharp edges and explicitly
requests an interactive interface. Source
`217be17f7416eefc0330f70e8e103ae9bb07f0c1` bundles the original SIL-OFL Inter
font, privately registered through Fontconfig on Linux without installing
fonts or spawning helpers. Rounded antialiased buttons/fields, library cards,
selection outlines and management panel retain the supplied reference palette.

Actual wheel zoom, explicit zoom/reset controls, middle-button or Shift-drag
pan, connected-wire hover highlighting and double-click device configuration
are implemented. Session node dragging works under zoom. View-only gestures
preserve the manifest and never invoke sudo. Existing validated offline
configuration/cabling and real native lifecycle/probes remain. The diagnostic
pane is read-only: genuine native interactive consoles/capture and richer
supported forms are still pending. LAN core remains frozen 7/7; static VXLAN
stays on the later roadmap.

Local Xvfb/system-Tk regression passed 1049 cases (41.476 s, 141 environment
skips); fourteen focused native workbench checks passed, including actual
wheel/pan/hover/double-click events and scaled drag coordinates. The dedicated
GitHub native scenario additionally asserts Inter and saves normal/135% views.

The [desktop/native job](https://github.com/sou1915/Network-LABS/actions/runs/42316748403/job/128231116270)
passed 1049 general cases (47.387 s, 116 skips) plus the real campus scenario
(10.402 s). Current screenshot/report/provenance bind to source 217be17 and
artifact 13550324801; the new zoomed screenshot is also retained. The report
confirms Inter Variable, zoom, routed success, firewall-path failure, seven
UID-1001 result files, root-state refusal, confirmed stop and no callback errors.
Host cleanup invariants passed. See NATIVE_GUI_FLOW.md for remaining scope.

All ten selected jobs in run 42316748403 passed; 52 other profiles were
intentionally skipped. Wired 802.1X job 128231115458 passed and LAN aggregate
128233042144 confirms 7/7. No new LAN prerequisite was added.

## Previous GUI polish checkpoint

Source `f27f49fdd7021200840fcacb5f99636a229eda96` improves the reference-style
campus: collision-aware port labels, larger host captions, synchronized page
underline and selected toolbar modes, search hint, balanced lower panes and
pinned interface Apply/Reload actions. Runtime hint is explicitly a snapshot
and does not infer green/running from a declared topology. Diagnostic title
shows the real probe pair; output remains read-only with separate full JSON.
The user continues asking for visual improvement; preserve the supplied
reference palette/proportions and keep providing actual screenshots.

The [desktop/native job](https://github.com/sou1915/Network-LABS/actions/runs/42313340373/job/128219882981)
passed 1047 cases (50.288 s, 116 skips) plus real campus/form/visible-actions
validation (10.129 s). Routing success, configured firewall-path failure,
seven UID-1001 results, direct root-state refusal, stop/callback/host-network
invariants passed. Screenshot/report/provenance now bind to artifact
13549022791 at f27f49f. Full local regression with temporary Xvfb passed 1047
cases (40.188 s, 141 skips), alongside focused actual Tk checks. No runtime/
protocol or privilege code changed. See NATIVE_GUI_FLOW.md for exact scope.
Next broader work remains genuine native interactive consoles/capture and
supported richer GUI. LAN core remains accepted; static VXLAN stays tracked.

## Reference-colour campus checkpoint

The user rejected the previous look again, requesting the same design and
colours as images/agreed-gui-reference.jpg. Source
`9fcbd4a720cf49bfc3279caa1b6c429689aa05b2` now uses the 1280×720 layout:
full-height left catalogue; topology/diagnostics to its right; compact top
navigation; a red/dark management pane with interface table/details; blue/red
monitor themes and blue/green/amber VLAN areas. Default native project is now
the real Campus-entreprise template (10 nodes, 9 links), with routed VLANs
10/20/30, two switches, R1, default-drop FW1 and a server endpoint. There is
no fake Wi-Fi, vendor firmware, LACP or DNS/Web readiness. Client/server themes
are presentation of Linux hosts. Small-LAN creation remains available.

The [desktop/native job](https://github.com/sou1915/Network-LABS/actions/runs/42311053032/job/128212313234)
passed 1047 cases (49.576 s, 116 skips) plus the real campus (9.887 s), on its
first native run. The form changed CLIENT3's name/address/default gateway;
actual inter-VLAN PC1 ↔ CLIENT3 passed through R1, and PC1 ↔ SRV1 was blocked
by FW1's default-drop policy. Seven result files remained UID 1001; root-state
read refusal, stop, callback and host-network invariants passed. Current
screenshot/proof/provenance: artifact 13548780601 at source 9fcbd4a. Full local
regression under temporary Xvfb passed 1047 cases (38.163 s, 141 skips), plus
focused actual Tk tests. Polling timer cleanup was corrected after local
preview. See NATIVE_GUI_FLOW.md for exact behaviour and remaining scope.

Keep the provided design as the reference. Next work: genuine interactive
native consoles/capture and richer supported management forms, without routing
native operations through the model backend. LAN core stays accepted; static
VXLAN remains tracked after LAN/GUI. Older look checkpoints below are history.

## Current GUI visual correction

Source `22e2206112e36d2a513e674a3c7cf76370314097` addresses the user's
explicit complaint that the GUI still did not resemble the supplied image.
Compact menus/toolbar, original rack/monitor artwork, categorized clickable
palette, dotted white canvas, role/VLAN placement, coloured declared access
zones, physical port captions and orthogonal cable lanes replace large cards.
The dark read-only diagnostic pane renders actual ping output; raw JSON has
its own tab. Do not call it an interactive console or claim vendor firmware.
VLAN groups come only from explicit unambiguous access membership, and subnet
captions exclude unconnected interfaces. The actual native scenario now has
VLAN 10 / VLAN 20 and an 802.1Q trunk, with failed PC1 ↔ PC2 and successful
PC1 ↔ CLIENT3 probes; the latter's gateway is .10 in VLAN 10. Seven result files
remain user-owned. First visual capture exposed overlapping cable lanes and
selection/labels; the final source corrects these without runtime changes.
Next priorities remain interactive native consoles/capture and supported
richer device GUI, while respecting the supplied visual reference. LAN core
stays frozen; VXLAN remains tracked. See NATIVE_GUI_FLOW.md for exact limits.


The final [desktop/native job](https://github.com/sou1915/Network-LABS/actions/runs/42307186227/job/128199382142)
passed 1045 cases (48.487 s, 116 skips) plus the real two-VLAN UI scenario
(9.269 s). It observed same-VLAN success and cross-VLAN failure, retained
actual ping output and seven private user-owned result files, confirmed stop
and left no callback/host-network leaks. Screenshot/report/provenance now
refer to artifact 13547310471 at source 22e2206. Local general regression on
the initial visual revision passed 1045 cases (31.263 s, 170 skips). Both
visual revisions passed desktop/native tests; the final screenshot corrects
the initial visual overlaps. Read the supplied reference as the continuing
target, not a claim of completed vendor UI or interactive console support.

## Basic native device forms

Source `13b6dcf2342afa79bcc042869997cd8a6f0aff29` adds a right-hand
Configuration tab beside État / test: OCI name, selected physical port IPv4,
node-wide gateway and port enabled state. Whole-draft snapshot checking
prevents stale forms from overwriting concurrent edits. All changes are atomic
validated drafts, applied to the runtime only after save/stop/start. Basic
renames update cable endpoints and session positions; structured references,
scripts/custom commands conservatively require explicit JSON rename. Switch
physical IP/gateway, DHCP-controlled addresses and Firecracker are read-only
in this basic form. See NATIVE_GUI_FLOW.md for full boundaries. Next work is
the remaining actual reference layout: images/VLAN visual groups, richer
supported device forms, interactive native consoles and packet views. Keep
LAN core frozen and VXLAN tracked. Never route native actions to model CLI.



At source `13b6dcf2342afa79bcc042869997cd8a6f0aff29`, the
[desktop/native job](https://github.com/sou1915/Network-LABS/actions/runs/42303521155/job/128187034367)
passed 1042 regression cases in 47.928 s (116 environment/opt-in skips) and the
separate real device-form scenario in 4.505 s. The form renamed PC3 to CLIENT3,
updated its IPv4 to 192.0.2.33/24 and gateway to 192.0.2.20 before native
save/start. Kernel inspection asserted the actual default route via .20;
bidirectional PC1 ↔ CLIENT3 probes used the new .33 address and passed.
All five OCI nodes and four links were stopped without callback or host-network
leaks. GUI/result ownership remained UID 1001 and root-state access was denied.
The current screenshot/report/provenance correspond to artifact 13545820693,
with original ZIP and per-file SHA-256 verification. Local regression passed
1042 cases in 30.466 s (170 environment skips, including display-dependent
cases); Tk and real native execution were verified in CI. No failed native
run preceded this increment.

## Graphical topology editor

Latest source `c6e3a282dddc7990582fd0b3797aa7b3a626076f` adds generic OCI
host/switch/router creation, mouse cable selection with explicit free/new
ports, cable/device removal and dragging. All configuration changes are
atomic validated drafts; no live Manager/kernel changes occur. A full OCI
port list can be extended in the cable dialog. Native occupied-port, loop,
reference and final-node checks remain strict. JSON validation is available
in its tab. Drag coordinates are session-only; native JSON persists topology.
See NATIVE_GUI_FLOW.md for operation and exact limits. Do not confuse the
results dock with an interactive console. Photos/VLAN groups/device forms/
interactive consoles/capture remain pending. Keep supplied reference and VXLAN
roadmap. The expanded native GUI scenario builds five nodes/four links and
verifies PC1 ↔ PC3 after a real save/start, without changing privilege handling.



At final editor source `c6e3a282dddc7990582fd0b3797aa7b3a626076f`, the
[desktop/native job](https://github.com/sou1915/Network-LABS/actions/runs/42302077273/job/128182107166)
passed 1039 cases in 49.335 s (116 environment/opt-in skips), followed by the
real edited-topology scenario in 4.771 s. Five OCI devices/four links started
from the saved GUI draft; PC1 ↔ PC3 passed through the two-switch fabric.
The GUI and all six result files remained UID 1001, direct root-state access
was denied, stop completed, and no callback or host-network leaks remained.
The current screenshot/report/provenance bind to artifact 13544318464 with
verified ZIP and file SHA-256 hashes. Local regression passed 1039 cases in
30.460 s (169 environment skips, including display-dependent tests).

The earlier editor source dc9a439 passed its desktop/native scenario too.
Run 42301952887 was canceled when a new GUI fixture mistakenly expected an
unguarded switch loop to succeed. The fixture was corrected to assert refusal
and unchanged draft, then exercise safe new-port cabling to a host; the native
loop check and runtime behavior were not weakened. Final validation uses
run 42302077273, not the canceled run.

## GUI reference shell increment

Source `d18df0909839b28a223cdd8835fbacce0d1f970d` begins implementing the
actual supplied mockup: compact dark header, searchable project equipment,
upper topology/device area and resizable lower results/operation-event docks.
The event table only records actual backend outcomes; the dark results area
is JSON inspection/probe output, not an interactive console or packet stream.
Next priorities remain graphical topology editing and supported device forms,
plus the reference's device images and VLAN groups. Do not claim visual parity.
Keep native backend/privilege boundaries and real screenshots.



Final shell source `d18df0909839b28a223cdd8835fbacce0d1f970d` passed the
[desktop/native job](https://github.com/sou1915/Network-LABS/actions/runs/42293363242/job/128152218260):
1034 regression cases in 45.238 s (116 environment/opt-in skips), plus the
real embedded GUI / sudo / OCI scenario in 4.079 s. The latter verifies the
connectivity button remains visible above the dock at 1240×800, four actual
operation events after verification, real bidirectional ICMP, private results,
confirmed stop, preserved model project and no callback/host-network leaks.
The screenshot/report/provenance now correspond to artifact 13540452917.
The earlier shell passed its desktop/native test too; its screenshot exposed
clipped controls, which the final source corrects. Local general regression
passed 1034 cases in 30.402 s (167 environment skips, including display tests).

## Superseded layout interpretation — user rejected this reference

The user requires the existing agreed desktop layout, referenced by
[workspace_design.png](workspace_design.png), rather than a separate technical
native window. Native LAN now occupies the main desktop with the same theme,
device icons and left equipment / centre topology / right inspector layout.
Back restores the pedagogical workspace without changing its model backend;
native sudo/IPC behavior remains unchanged. Validate the actual embedded App
flow, capture its real native screenshot, and keep supplying screenshots after
GUI additions. Graphical node/link creation and full device forms remain open.
LAN core stays frozen; VXLAN remains later in the roadmap.

Source `a82b0571194f81759e29bf6e50d8e5b65dfd8664` passed the
[desktop/native job](https://github.com/sou1915/Network-LABS/actions/runs/42276785462/job/128095032017):
1033 regression cases (47.945 s, 116 skips), plus real embedded App / sudo / OCI
lifecycle and bidirectional ICMP (4.466 s), including return to the model
workspace. Screenshot/report/provenance now refer to artifact 13533009570.
Local full regression passed 1033 cases (30.311 s, 166 environment skips).

The same source also passed all ten selected jobs in
[run 42276785462](https://github.com/sou1915/Network-LABS/actions/runs/42276785462),
including the [7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42276785462/job/128097531781).
The dedicated wired 802.1X job passed managed-peer recovery (55.167 s) and
independent-supplicant admission/revocation (219.122 s); 52 other profiles were
intentionally skipped. The superseded run 42276666855 was canceled after the
explicit desktop-entry correction, not used as final validation evidence.


## Current priority: native GUI essentials — first flow verified — 2026-11-06

LAN core remains accepted (7/7); advanced LAN extensions stay deferred. The
user prioritises practical essentials and larger useful increments over LAN
micro-refinements. **Continue GUI work, not advanced LAN implementation.**

The [native workbench](../network_labs/appliances/ui.py) now renders a native
topology, creates a basic LAN or opens JSON, saves private configuration and
performs start/status/inspect/bounded bidirectional verify/stop with actual
backend results. [ui_bridge.py](../network_labs/appliances/ui_bridge.py) keeps
the GUI/terminal wrapper unprivileged and runs only typed operations via sudo.
The root backend never writes the GUI result path. Results are private and
context-bound; invalid/failed replies do not imply running or stopped state.
The educational canvas/Wasm engine remain separate and unchanged.

At implementation `cad63774a58a9d51aa3b73bc28d90b932fb7fc86`, the
[desktop/native job](https://github.com/sou1915/Network-LABS/actions/runs/42267670327/job/128063724857)
passed general regression (1033 cases, 47.405 seconds, 116 environment/opt-in
skips) and the separate real GUI/native scenario (4.207 seconds). Tk ran as
UID 1001; all six result files were written by UID 1001, and direct root-state
access was refused. The actual sudo backend created three OCI nodes/two links,
returned runtime status/kernel inspection, verified bidirectional native ICMP,
confirmed stop and handled a subsequent failed status without false success.
No callback errors or namespace/link/IPv4/IPv6 route/rule leaks remained.
Only terminal presentation was substituted for passwordless CI; kernel,
Manager, sudo and traffic were real. Interactive password-prompt UX remains
manual desktop acceptance.

All ten selected jobs in run 42267670327 passed, including `lan-core-ready`;
52 other profiles were intentionally skipped. Local full tests passed 1033
cases in 30.030 seconds with 166 environment skips. Compilation, workflow
structure, diff and documentation-link checks passed. No failed native run
preceded this GUI increment. LAN protocol behavior was unchanged.

See [NATIVE_GUI_FLOW.md](NATIVE_GUI_FLOW.md) for the captured screenshot,
operation JSON, exact privilege/observation limits and usage. Next useful GUI
increment: native node/link editing and basic per-node configuration instead
of requiring JSON for topology changes. Embedded consoles/capture and broader
forms follow. Do not reopen the frozen [LAN core gate](LAN_CORE_ACCEPTANCE.md)
for deferred features. Existing main desktop/vendor forms are not yet full
native configuration integration. Static VXLAN stays after LAN/GUI, with
EVPN/BGP/WAN separate. Historical percentage estimates below are not a GUI
completion counter.

## Wired 802.1X guarded in-place peer recovery — 2026-11-06

Implementation `af6723cac8613278bfc921b191db58b8ac2bcd20` adds
`dot1x-peer-recover LAB PC1 --json` for explicit in-place recovery of a dead
recorded supplicant. It requires a stable running lab, no authenticator worker
and a verified closed NAS gate. Original namespace/interface/MAC, credential/
handoff and control directory/socket ownership identities must match. Live
peers, active auth, drift, foreign entries/replaced sockets and responsive
sockets without a matching owner are refused before replacement. Legacy
active state without the new startup ownership metadata requires recreation.
Only verified stale control objects are removed; namespaces, backend and
policy remain. Startup uses the same sealed private handoff and ends with
confirmed closure and authentication_required=true. Fresh explicit auth is
still required. A failed restart retains recovering-peer phase and any
recorded resources; auth/save refuse it until explicit stop/restore. Known dead
children are reaped without waiting for or signalling a live reused PID.

The [dedicated wired native job](https://github.com/sou1915/Network-LABS/actions/runs/42257561787/job/128028719091)
passed the extended managed-peer/recovery scenario in 56.219 seconds and
repeated the full independent-supplicant authenticator scenario in 193.355
seconds. Recovery refused a live peer, active auth, changed credentials and
a foreign regular file replacing the old socket, preserving records/files.
A separate CLI then replaced only the dead peer: its namespace identity,
all lab namespace names and the actual backend PID remained unchanged. The
gate stayed closed until a new finite authentication produced four fresh
RADIUS requests and bidirectional data; save retained the original manifest.
Existing peer death, wrong-password, cold restore, teardown and host namespace/
link/IPv4/IPv6 route/rule invariants passed. Both selected jobs passed; 58 others
were intentionally skipped. Local full tests passed 1024 cases in 30.440
seconds with 163 environment skips; the 17 focused peer cases, compile/diff/
link checks passed. Unit coverage includes failed-restart auth/save refusal,
missing clean-exit control paths and live reused-PID cache isolation. No failed
native run preceded this increment.

See [DOT1X_MANAGED_PEER.md](DOT1X_MANAGED_PEER.md). Recovery remains explicit;
automatic peer recovery/persistent NAS supervision, stronger EAP/TLS,
multi-client/dynamic VLAN/accounting and wider switching remain open. LAN
precedes native GUI; static VXLAN and separate EVPN/BGP/WAN remain tracked.
Planning estimates stay LAN about 80%, whole product about 45–50%.

## Wired 802.1X engine-owned supplicant peer — 2026-11-06

Implementation `f4ebb509df3d901ec3265b1665287a852d1783ab` adds an
optional `dot1x_supplicant` policy to the existing wired PC1 peer. A trusted
foreground host wpa_supplicant runs in that peer's namespace across finite
NAS commands. The schema pins identity/interface and a private password-file
hash; preflight rejects invalid assets before allocation. Configuration is
passed through a sealed mode-0600 memfd, with no secret in argv, runtime peer
files or startup JSON. Inspection checks owned process, namespace/interface,
control readiness and original handoff/asset pins; save refuses dead or
unverifiable peers. Normal CLI hash redaction is added by `22a0844`.
Teardown stops the NAS first, then signals the owned peer group and confirms
peer process death before namespace removal. PID reuse/foreign groups do not authorize signalling.
Cold restore preserves policy only and starts a new peer with the gate closed.
The authenticator remains explicit/finite; there is no automatic peer restart
or persistent NAS authentication service.

At final validation commit `ff4b08a7d96d62ce81dfe027ef1383b57b58a704`,
the [dedicated wired job](https://github.com/sou1915/Network-LABS/actions/runs/42253373302/job/128014020814)
passed the new managed-peer scenario in 45.443 seconds and the existing full
authenticator scenario in 193.528 seconds. The new reference verified two real
EAPOL Success/four RADIUS requests, data in both directions, active save,
a second CLI auth reusing the same peer, peer SIGKILL followed by closed
authentication timeout/save refusal, changed-asset refusal before allocation,
cold restore, separate-CLI teardown during admission and actual wrong-password
rejection while the peer stayed running. Host namespace/link/IPv4/IPv6
route/rule invariants passed. Both selected jobs passed; 58 others were
intentionally skipped. Local full tests passed 1015 cases in 30.441 seconds
with 163 environment skips; compile/diff/link checks passed.

Initial run 42252777315 at `f4ebb50` passed both jobs (managed peer 44.769
seconds, old authenticator 219.613 seconds). Run 42253118016 at `22a0844`
passed general CI but failed the first admitted ping in the new fixture.
Fixture-only correction `ff4b08a` uses the existing reference's bounded data/
ARP readiness pattern: real traffic must succeed within two seconds and a
verified admitted lease, otherwise it fails. Duration, packet, credential and
cleanup assertions were retained; no admission/runtime policy was relaxed.

See [DOT1X_MANAGED_PEER.md](DOT1X_MANAGED_PEER.md). Persistent NAS supervision,
automatic peer recovery, stronger EAP/TLS, multi-client/dynamic VLAN/accounting
and wider switching remain open. LAN precedes native GUI; static VXLAN and
separate EVPN/BGP/WAN remain tracked. Planning estimates stay LAN about 80%,
whole product about 45–50%.

## Wired 802.1X bounded server-requested reauthentication — 2026-11-06

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

See [DOT1X_WIRED.md](DOT1X_WIRED.md). Persistent authenticator/supplicant
service, stronger EAP/TLS, multi-client/dynamic VLAN/accounting and wider
switching remain open. LAN precedes native GUI; static VXLAN and separate
EVPN/BGP/WAN stay tracked. Planning estimates remain LAN about 80%, whole
product about 45–50%.

## Wired 802.1X verified backend session duration — 2026-11-06

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

See [DOT1X_WIRED.md](DOT1X_WIRED.md). Persistent authenticator/supplicant
service, stronger EAP/TLS, multi-client/dynamic VLAN/accounting and wider
switching remain open. LAN precedes native GUI; static VXLAN and separate
EVPN/BGP/WAN remain tracked. Planning estimates stay LAN about 80%, whole
product about 45–50%.

## Wired 802.1X controlled-link revocation — 2026-11-06

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

See [DOT1X_WIRED.md](DOT1X_WIRED.md). Persistent authenticators/supplicants,
stronger EAP/TLS, multi-client/dynamic VLAN/accounting and wider switching
remain open. LAN precedes native GUI; static VXLAN and separate EVPN/BGP/WAN
remain tracked. Planning estimates stay LAN about 80%, whole product 45–50%.

## Pinned shell accounting ACK loss — 2026-11-06

Corrected test commit `3a5b15a85e3a8ee051f1103ee2c4d69c8ab66b6b`
adds native packet-loss validation without runtime or protocol scope changes.
Lost Start ACK prevented payload execution (SSH 126) and durably queued a
zero-duration compensating Stop/cause 9. Lost Stop ACK after an admitted
shell returned uncertainty (125), retained Stop/cause 1 and recovered only
through explicit flush. Captures/session IDs, actual backend duplicate Stops,
empty journal/session groups, exact host trust through cold restore and
host namespace/link/IPv4/IPv6 route/rule/nftables invariants passed. Duplicate
delivery is expected; this does not claim exactly-once accounting.

The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42209558186/job/127864535740)
passed ACK-loss in 20.104 seconds, orphan-journal in 9.479 seconds and pinned
lifecycle in 7.596 seconds. All six selected jobs passed; 54 intentionally
skipped. Local tests passed 991 cases in 30.594 seconds with 162 environment
skips. Initial run 42209349058 at `504371a` passed the loss/recovery checks
but failed final saved-spec equality because the expanded fixture lacked
default canonicalization. The corrected fixture uses the standard validator
before startup and retains the exact equality assertion; no runtime behavior
or acceptance assertion was relaxed.

See [SSH_SHELL_HOST_IDENTITY.md](SSH_SHELL_HOST_IDENTITY.md). Remaining LAN
precedes native GUI; static VXLAN and separate EVPN/BGP/WAN remain tracked.
Planning estimates stay LAN about 80%, whole product about 45–50%.

## Latest LAN validation: pinned shell PTY and accounting lifecycle — 2026-11-06

Test commit `91997a938d33eb54b48428dca9db981abd455caa` extends the
existing pinned IPv4 journaled shell validation without changing protocol
behavior or manifest scope. The native PTY/shell reference now also runs
with declared host identity and mandatory outbox/journal enabled. Wrong
credentials/actions created no payload; command exit 7 propagated. Real PTY,
no-new-privileges, empty capabilities and no password echo passed. Background
payloads were removed after normal exit, expiry and client disconnect; healthy
completion left no journal/outbox records. The backend recorded four Start
and four Stop entries with matching session IDs and causes 1/5/6/9. Cold
restore reused the exact pre-provisioned known_hosts without keyscan. Host
namespace/link/IPv4/IPv6 route/rule/forwarding/unprivileged-port invariants passed.

The [expanded native job](https://github.com/sou1915/Network-LABS/actions/runs/42203206143/job/127843341125)
passed the new lifecycle scenario in 7.773 seconds and repeated the orphan
journal scenario in 9.935 seconds. All six selected jobs in run 42203206143
passed; 54 other jobs were intentionally skipped. Local full tests under
umask 022 passed 990 cases in 30.036 seconds with 161 environment skips;
compilation/diff/link checks passed. No native failure preceded this validation.
See [SSH_SHELL_HOST_IDENTITY.md](SSH_SHELL_HOST_IDENTITY.md). Native GUI remains
after remaining LAN work; static VXLAN and separate EVPN/BGP/WAN stay tracked.
Planning estimates stay LAN about 80%, whole product about 45–50%.

## Latest LAN increment: pinned IPv4 journaled SSH shell — 2026-11-06

Implementation `9146031a8cddcb11a5987fa1d3a5ff02162f3fc9` permits the
explicit SSH host identity with an IPv4 RADIUS shell only when accounting,
durable Stop outbox and session journal are all selected. Generator flags
are `--radius --radius-ssh --radius-ssh-shell --radius-accounting
--radius-accounting-outbox --radius-accounting-journal --ssh-host-key-file`.
Client-key/RADIUS/action/Start gates remain unchanged. Diagnostics cannot
silently acquire shell grants; partial accounting, IPv6 pinned shells,
Telnet/syslog and NAS managed-server co-location remain refused. The suite
reuses `ssh-radius-host-key`; selector choices stay at 25.
See [SSH_SHELL_HOST_IDENTITY.md](SSH_SHELL_HOST_IDENTITY.md).

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42173268692/job/127745802977)
passed in 10.636 seconds. The real SSH journal reference ran with pinned,
pre-provisioned strict known_hosts and no keyscan. Wrong host trust created
no additional session intent. Live-owner cleanup refusal, supervisor SIGKILL
with orphan payload, nonempty-session refusal, explicit termination, durable
Stop handoff without network delivery, one explicit Stop transmission with
backend records, stale-runtime cleanup refusal and healthy acknowledged
completion passed. Cold restore kept the exact trust file and used a fresh
bridge token. Host namespace/link/IPv4/IPv6 route/rule invariants passed.
Native grants are direct-user; not every role/topology combination is claimed.

All six selected jobs passed in run 42173268692: pinned shell, old SSH
journal, pinned diagnostics, standalone pinned SSH, RADIUS/SSH and general CI.
The other 54 jobs were intentionally skipped. Local full tests under
umask 022 passed 989 cases in 31.490 seconds with 160 environment skips;
compilation/diff checks passed. No native failure preceded this result.
Continue LAN before native GUI; static VXLAN and separate EVPN/BGP/WAN
remain tracked. Estimates stay LAN about 80%, whole product about 45–50%.

## Latest LAN acceptance measurement: kernel memory peak — 2026-11-05

Implementation `1ad4241d651fa3ebf6e70d3b10017aa028100712` adds benchmark
report version 2 with optional kernel cgroup-v2 `memory.peak`, parent history
provenance, a fresh-parent current-run verdict and parent OOM events. Missing
support is null, corrupt/inaccessible counters fail, populated parents refuse
before allocation, and empty parents retain explicit prior-history scope.
No counters are reset. The post-load snapshot covers charged startup/load
memory, not all host work or total application RAM. Existing phase sampling
and historical v1 reports remain separate. See [BENCHMARK_KERNEL_PEAK.md](BENCHMARK_KERNEL_PEAK.md).

The [native job](https://github.com/sou1915/Network-LABS/actions/runs/42129277749/job/127601472273)
passed the real presampling transient and 20-node scenarios in 29.601 seconds,
then the existing enterprise HTTP/NAT/return-route/save-restore regression in
21.131 seconds. The 20-node fresh-parent kernel peak was 9,588,736 bytes
(9.145 MiB), with 10s idle and 10s ICMP from 12 clients, 100 requests each;
all 1,200 requests returned, all nodes stayed running and no OOM kill was
observed. The 12 MiB presampling allocation produced a 14.965 MiB kernel
peak while idle sampling saw only 2.098 MiB. Host invariants and stopped-node
cleanup passed. These remain headless cgroup references, not a whole-app,
GUI/heavy-service or laptop 2 GiB certification.

Both selected jobs (native benchmark and general CI) passed in run
42129277749; 57 other jobs were intentionally skipped. Exact artifact JSON
and source/digest provenance are committed under docs/benchmarks; ZIP SHA-256
matched GitHub metadata. Local full tests under umask 022 passed 985 cases in
30.977 seconds with 159 environment skips; compilation/diff/link checks passed.
No native failure preceded this checkpoint. Remaining LAN precedes native
GUI; static VXLAN and separate EVPN/BGP/WAN remain tracked. Planning estimates
stay LAN about 80%, whole product about 45–50%.

Workflow maintenance: the manual selector now has 25 choices. Reuse/group
selectors or adjust the input schema before adding another choice; preserve
the default all scope and unconditional push/PR selection of every job.

## Latest LAN increment: pinned dual-stack SSH with IPv4 RADIUS — 2026-11-05

Implementation `8c776020e21b88d57a6cb3d7e4c2730216f36949` permits the
explicit host identity in `--radius --radius-ssh --radius-dual-stack`
diagnostics. One Dropbear daemon uses the same key for both literal IPv4/IPv6
listeners. Pre-provisioned strict known_hosts keeps both entries unchanged
through cold restore. RADIUS stays IPv4 and still gates each diagnostic;
host trust does not bypass client-key authentication or RADIUS action policy.
Standalone IPv6 pinned SSH, shell/accounting, DNS coexistence, dynamic
addressing/routing and other NAS service co-location remain refused.
See [DUAL_STACK_SSH_HOST_IDENTITY.md](DUAL_STACK_SSH_HOST_IDENTITY.md).

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42126484317/job/127591903712)
passed in 37.598 seconds. Both SSH families verified the declared identity,
rejected wrong host trust/client keys and enforced RADIUS credential/action
denials. Real IPv4/IPv6 SSH and IPv4 RADIUS packets were captured without
plaintext credentials on TCP/22. IPv4 forwarding loss denied diagnostics on
still-reachable IPv6 SSH; IPv6 forwarding loss broke IPv6 SSH while IPv4
diagnostics continued. Backend loss/recovery, drift refusal, unchanged trust
after cold restore, a fresh bridge token and host invariants passed.

All four selected jobs in run 42126484317 passed: new scenario, pinned IPv4
RADIUS SSH, old unpinned dual-stack RADIUS and general CI. The other 54 jobs
were intentionally skipped. Local full tests under umask 022 passed 980 cases
in 30.981 seconds with 157 environment skips; compilation/diff/link checks
passed. No native failure preceded this checkpoint. Continue remaining LAN
before native GUI. Static VXLAN and separate EVPN/BGP/WAN remain tracked;
planning estimates stay LAN about 80%, whole product about 45–50%.

## Latest LAN increment: pinned SSH identity with RADIUS diagnostics — 2026-11-05

Implementation `19c853f6c504d6f137d756aa64624aeb5c717aaf` permits
`management.ssh_host_key` with explicit IPv4 `ssh_radius` diagnostics and
adds `--ssh-host-key-file` to the corresponding generator. Fixed diagnostics
remain behind client-key authentication and fresh RADIUS user/action checks.
Standalone pinned identity remains supported. Shell grants (including grants
not selected through SSH), accounting, Telnet, syslog, IPv6 and other server
co-location on the NAS remain refused. This is not RADIUS authentication
inside the SSH handshake. See [SSH_RADIUS_HOST_IDENTITY.md](SSH_RADIUS_HOST_IDENTITY.md).

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42091389971/job/127470040092)
passed in 5.793 seconds. It reuses the real SSH/FreeRADIUS reference with
pinned host identity enabled, pre-provisioned strict known_hosts and no
keyscan. Wrong host trust/client key, wrong/unknown RADIUS credentials,
per-user action denial, malformed credentials, shell/SCP/SFTP/injection,
backend outage, dead bridge and bridge impersonation controls passed.
Host-key unreadability and conformity passed; cold restore preserved the
exact trust file, used a fresh bridge token and restored authorized actions.
Host namespace/link/IPv4/IPv6 route/rule invariants passed. Native grants are
direct-user; reusable-role validation has local evidence, not every native
role/AAA combination. All three native jobs passed in that first attempt;
general CI failed a new CLI fixture because its credential files inherited
mode 0644 under umask 022 and the CLI correctly rejected them.

Fixture-only repair `72ae65a79fb4c8eb8576997344c80201d000e2f1` creates
those files mode 0600 from creation; protocol/runtime checks and assertions
are unchanged. [Replay 42125394285](https://github.com/sou1915/Network-LABS/actions/runs/42125394285)
passed all four selected jobs: pinned RADIUS SSH, standalone pinned SSH,
existing RADIUS/SSH and general CI; 53 other jobs intentionally skipped.
The new native scenario passed again in 6.174 seconds (job 127588151990).
Local full tests under explicit umask 022 passed 976 cases in 30.301 seconds
with 156 environment skips; compilation/diff/link checks passed. No native
scenario failed; retain the first general-CI fixture failure in the history.

Continue remaining LAN before native GUI. Static VXLAN and separate
EVPN/BGP/WAN remain tracked. Planning estimates remain LAN about 80%, whole
product about 45–50%; this bounded combination does not close the LAN gate.

## Latest LAN increment: explicit SSH host identity — 2026-11-05

Implementation `1ac714da5e0e6dceef004e4fda98d3d9a9777340` adds optional
`management.ssh_host_key` with absolute offline file reference and canonical
public ed25519 identity. The standalone restricted IPv4 SSH generator accepts
`--ssh-host-key-file`; it omits the usual syslog sender in this profile.
Host `dropbearkey` validates a mode-0600 bounded snapshot before allocation;
only the selected node receives the private snapshot in fresh `/run`, root
owned mode 0600. Dropbear uses explicit `-r`, with no `-R` fallback. Raw key
bytes never enter declarations/startup JSON, command arguments or persistent
command logs. Runtime conformity checks file type/mode/owner/hash. Source
assets must still conform at cold restore; they are referenced, not backed up.
RADIUS, Telnet, syslog, IPv6 and other server co-location remain refused for
this opt-in profile; existing ephemeral defaults remain unchanged.

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42089486906/job/127463481874)
passed in 2.703 seconds. Pre-provisioned strict known_hosts worked on the
first connection and unchanged after cold restore, without keyscan. Real SSH
verified restricted actions, uid-65532 key unreadability, no copies on other
nodes, runtime content/mode/symlink drift refusal and pre-allocation rejection
of missing/malformed/mismatched/symlink/mode-invalid assets. Explicit identity
replacement rejected old trust, worked after an explicit trust update and
cold-restored again. Host namespace/link/IPv4/IPv6 route/rule invariants passed.
Existing SSH access, RADIUS/SSH and general CI jobs also passed: all four
selected jobs succeeded; 52 other jobs were intentionally skipped.
Local tests passed 972 cases in 30.003 seconds with 155 environment skips;
compilation/diff checks passed. No native failure preceded this result.
See [SSH_HOST_IDENTITY.md](SSH_HOST_IDENTITY.md). Continue remaining LAN before
full native GUI; static VXLAN and separate EVPN/BGP/WAN remain tracked.
Planning estimates stay LAN about 80%, whole product about 45–50%.

## Latest LAN increment: separate IPv6 DNS and named HTTPS — 2026-11-05

Implementation `05953899d1187f73a177e8e632704d5ab0cb6f90` adds
`example --ipv6-dns-https --https-client-rootfs PATH`. Five static IPv6-only
nodes put DNS PC3 and HTTPS PC2 on distinct R2-facing networks behind two
routers. PC1 uses only the managed DNS resolver; AAAA resolves
`secure.lab.test` and TLS verifies the original DNS name against the supplied
CA. DNS/HTTPS co-location, external/service-node resolvers, combined firewall,
dynamic, dual-stack and logical-interface compositions remain refused.
Existing HTTPS/firewall and standalone DNS profiles remain separate.

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42087775672/job/127457432669)
passed in 15.027 seconds. UDP/TCP DNS plus named HTTPS, real DNS/TLS wire,
GET body, wrong CA/name and unknown-name controls passed. DNS outage broke
named HTTPS while literal verified TLS/the same HTTPS process stayed live;
HTTPS outage preserved DNS answers and its process. Explicit recovery,
resolver/DNS/HTTPS config drift refusal, exact declarative cold restore and
host invariants passed. Baseline IPv6 HTTPS, tagged IPv6 DNS, dual-stack DNS
and general CI also passed: five selected jobs succeeded; 50 other jobs were
intentionally skipped, not new proof. Local tests passed 968 cases in 30.478
seconds with 154 environment skips; compilation/diff checks passed. No
failed native run preceded this result. See [IPV6_DNS_HTTPS.md](IPV6_DNS_HTTPS.md).

Continue remaining LAN before full native GUI integration. Static VXLAN and
separate EVPN/BGP/WAN remain tracked; planning estimates stay LAN about 80%,
whole product about 45–50%, not measured coverage or an ETA.

## Latest LAN validation: same-port HTTPS source isolation — 2026-11-05

Test commit `72b0732f90be9a93dd9075f42071486dae4b0e1a` strengthens the
existing IPv6 HTTPS/firewall scenario without changing protocol behavior,
manifest scope or the example. A temporary alternate source `2001:db8:10::99`
uses the same interface, destination and TCP/443 as the authorized client.
Completed DAD, source-bound gateway reachability and the expected route prove
it can transmit. Its HTTPS connect times out, with actual ingress SYNs,
absent egress, and increasing default-drop counters. Authorized and direct
verified TLS remain successful, and the server PID stays unchanged. The
extra address is observed as drift and refuses save; it is removed before
successful save. The control passes again after cold restore. This is source
address filtering, not authenticated client identity or anti-spoofing.

The [expanded native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42086361238/job/127452432140)
passed in 35.461 seconds. All five selected jobs in run 42086361238 passed,
including baseline IPv6 HTTPS, standalone IPv6 firewall, DNS/firewall and
general CI. Other 49 jobs were intentionally skipped. Four focused local
policy/CLI tests, compilation/diff/link checks passed. No native failure
preceded this validation. See [IPV6_HTTPS_FIREWALL.md](IPV6_HTTPS_FIREWALL.md).
Planning estimates stay LAN about 80%, whole product about 45–50%.
Remaining LAN work still precedes full native GUI; static VXLAN and separate
EVPN/BGP/WAN remain tracked.

## Latest LAN increment: IPv6 HTTPS forwarding firewall — validated 2026-11-05

Implementation `8ce6321df0e06cee37bc5413478d7e20253288c3` adds
`example --ipv6-https-firewall --https-client-rootfs PATH`: PC1, a separate
default-deny FW1, and the existing managed IPv6 HTTPS PC2. Explicit rules
allow client-to-server TCP/443 and echo requests, with stateful returns.
HTTPS composition now permits one managed forwarding-only IPv6 firewall;
local-input, other service/security, dynamic, dual-stack and VLAN/SVI/logical
interface compositions remain refused. See [IPV6_HTTPS_FIREWALL.md](IPV6_HTTPS_FIREWALL.md).

The [dedicated native scenario](https://github.com/sou1915/Network-LABS/actions/runs/42079365366/job/127428042126)
passed in 22.128 seconds. Trusted TLS/GET, wrong CA rejection, positive
allow/state/default-drop counters, IPv6 conntrack and real two-interface
captures passed. A live TCP/8080 control was reachable on the server but
blocked across the firewall: ingress packets appeared without egress packets.
Routing/service outages had independent direct-TLS/echo controls; save
refused forwarding/ruleset drift. Exact declarations cold-restored with
working HTTPS. A stateless variant kept outbound TCP/443 and explicit echo
return but blocked remote TLS while direct TLS/echo worked; restoring the
stateful profile recovered service. Host invariants, including nftables,
passed. This is port-based forwarding, not TLS inspection or a production
PMTU/error-policy guarantee.

All five selected jobs in run 42079365366 passed: new scenario, baseline
IPv6 HTTPS, standalone IPv6 firewall, DNS/firewall and general CI. The other
49 jobs were intentionally skipped. Local tests passed 965 cases in 32.219
seconds with 153 environment-dependent skips; compilation/diff/link checks
passed. No native failure preceded this checkpoint. Planning estimates remain
approximately LAN 80% and whole product 45–50%. Continue LAN before full
native GUI integration; static VXLAN and separate EVPN/BGP/WAN stay tracked.

## Latest LAN increment: static IPv6 HTTPS — validated 2026-11-05

Implementation `81ba8ba63e1b844142e670f75a27a55645ba4895` adds
`example --ipv6-https --https-client-rootfs PATH`, one managed NGINX server
behind two static physical IPv6 routers. Explicit server `family: ipv6`
selects its numbered IPv6 eth0 address and `ipv6only=on`; existing IPv4
defaults remain unchanged. Other services/security, dual-stack, dynamic
addressing/routing, SVI/subinterfaces and multiple-server combinations remain
refused. See [IPV6_HTTPS.md](IPV6_HTTPS.md) for commands and boundaries.

Native run 42073646773/job 127407962710 passed in 13.213 seconds. It verified
real trusted TLS/GET/HEAD, wrong CA/name refusal, HTTP 404/405, IPv6-only
listener/wire, independent routing and service outages with local controls,
unchanged server PID through routing loss, drift refusal, explicit restart,
declarative cold restore and host invariants. Existing IPv4 HTTPS server and
identity-lifecycle jobs and general CI also passed. All four selected jobs
succeeded; 49 other jobs were intentionally skipped, not newly validated.

Local tests passed 962 cases in 30.469 seconds with 152 environment-dependent
skips after allowing the suite's existing loopback sockets. Compilation/diff
checks passed; no native failure preceded this checkpoint. LAN remains before
native GUI integration. Planning estimates remain approximately LAN 80% and
whole product 45–50%; one bounded profile does not justify a measured increase.
Static VXLAN, then separate EVPN/BGP and later WAN remain roadmap work.

## Current LAN readiness audit — completed 2026-11-05

The user requested continued work followed by a concrete progress percentage,
working-feature inventory and remaining work. Full suite run 42056055804 is
pinned to `f3146a0912fb77f59cd12bd3f20c87dc929d5f14`. It completed with
50 successful jobs and two setup-cancelled jobs. The comprehensive native
suite passed 51 test cases in 1600.113 seconds. The dedicated wired 802.1X
scenario passed in 112.327 seconds. Both cancellations were Ubuntu Azure mirror index-download
stalls before tests, not protocol assertions. Strict LACP completed positive
STRICT_VERIFIED on kernel 7.0.0-1017-azure/iproute2 7.1.0 in 701.725 seconds.

Repair `c145a9e0962178ab7ede0093f32b08d086d329aa` adds a CI-only bounded APT
helper using the official HTTPS Ubuntu archive for the two affected jobs,
a `lan-readiness-retry` selector and a correction to stale OVS RSTP scope text.
Targeted run 42059320195 retried those two native jobs plus general CI. Do not
claim one 52/52 green attempt: final evidence must distinguish the full baseline
and repaired retries. Protocol assertions were not changed.

The repaired replay completed successfully: all three selected jobs passed,
49 intentionally skipped. Tagged IPv6 TFTP passed its native scenario in
33.669 seconds; reverse STP/LACP control loss passed in 165.158 seconds.
Across the baseline and repaired replay, all 52 workflow job profiles now
have passing evidence; this is not one fully green original attempt.

PROJECT_STATUS.md records user-requested planning estimates: LAN about 80%
(75–85 range), overall about 45–50%, with explicit checklist/weight assumptions.
These are not measured test coverage, engineering effort or an ETA. The coverage
table and outdated guide cross-references have been refreshed. Local full tests
passed 959 cases in 31.021 seconds with 151 skips; read-only runtime-plan tests
passed 13 cases with one environment skip after the wording-only correction.
Keep LAN before GUI, with static VXLAN and separate EVPN/BGP/WAN still tracked.

## Latest LAN increment: costed OSPFv3 DNS failover validated — 2026-11-05

At implementation/validation commit
`8c2978f05f324662665e5e9a3dfa06c6f31555d3`,
`example --ipv6-dns-ospfv3-failover` adds two directly paired physical transits
between the same routers, with symmetric per-link and distinct path costs.
Single-link behavior remains available. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42055074653/job/127341141821)
passed in 51.123 seconds. Both Full adjacencies, preferred FIB selection,
carrier-up bidirectional primary blackhole with backup DNS/wire selection,
failback, total withdrawal with local live-DNS controls, backup-only recovery,
unchanged live daemon PIDs/declarations, drift refusal and fresh cold restore
with primary DNS/wire and baseline qdiscs passed. Single-transit DNS/OSPFv3,
standalone physical/SVI OSPFv3 and general CI also passed on that commit; 48
other jobs were intentionally skipped by manual selection.

Local tests passed 959 cases in 30.380 seconds with 151 environment-dependent
skips; compilation/diff checks passed. No failed native run preceded this
checkpoint. See IPV6_DNS_OSPFV3_FAILOVER.md and the final LAN_NEXT_STEPS
section for scope. External tc faults remain outside managed/save audit;
there is no zero-loss/fixed-time SLA, ECMP, larger graph or arbitrary physical/
one-way failure claim. Remaining LAN work precedes GUI; static VXLAN mapping
and later separate EVPN/BGP remain required roadmap work.

## Latest LAN increment: IPv6 DNS over OSPFv3 validated — 2026-11-05

At implementation/validation commit
`d320b987b0a75e84a2899a480e0dc7996e69398a`,
`example --ipv6-dns-ospfv3` adds one managed IPv6 DNS host behind exactly two
physical OSPFv3 routers, without router static routes. Active ports pair
directly; IDs differ, timers match, every numbered port participates and LAN
ports are passive. Clients use only the managed resolver. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42052137810/job/127330744403)
passed in 40.685 seconds. Full adjacencies, bidirectional BIRD kernel routes,
actual OSPFv3/DNS packets, AAAA/A-NODATA/NXDOMAIN, managed probes, independent
DNS-service versus learned-route loss, local live-DNS controls, reconvergence,
drift refusal, declarative cold restore and host invariants passed. Standalone
physical/SVI OSPFv3, tagged IPv6 DNS, dual-stack DNS and general CI also passed
on that commit; 46 other jobs were intentionally skipped by manual selection.

Local tests passed 956 cases in 31.056 seconds with 150 environment-dependent
skips; compilation/diff checks passed. No failed native run preceded this
checkpoint. See IPV6_DNS_OSPFV3.md and the final LAN_NEXT_STEPS section for
exact scope. Mixed/AAA, SVI/subinterface, firewall, other services and dynamic
addressing remain excluded. Remaining LAN work precedes GUI; static VXLAN
mapping and later separate EVPN/BGP remain required roadmap work.

## Latest LAN increment: guarded Syslog sender recovery validated — 2026-11-05

At implementation/validation commit
`c68850c3070aae41473771348d9fd91ec8fa265a`,
`syslog-forward-recover LAB NODE` explicitly starts a confirmed dead opted-in
disk-queue sender in its retained running node. It refreshes state under the
lab lock, requires config/TLS/spool conformity, reapplies optional offline peer
checks, uses bounded in-container process censuses and PID/inode comparisons,
and refuses live or ambiguous state. No signals, manual queue rewrite or
local-log replay. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42048879065/job/127319255687)
passed in 21.454 seconds. Both TCP and TLS verified live/missing-PID process
refusal, unrelated live PID refusal, malformed/symlink preservation, drift
refusal before cleanup, stale/absent PID recovery through separate CLI calls,
duplicate refusal, matching new PID/argv, same retained container, real queued
replay and TCP/TLS packets, continued delivery and cold-restore non-retention.
Original disk-queue, default TCP/TLS and general CI also passed on that commit;
45 other jobs were intentionally skipped by manual suite selection.

Local tests passed 952 cases in 30.346 seconds with 149 environment-dependent
skips; compilation/diff checks passed. No failed native run preceded this
checkpoint. See SYSLOG_FORWARD_RECOVERY.md and the final LAN_NEXT_STEPS
section for exact scope. Started is process evidence, not collector delivery.
No supervisor or cross-lab-stop queue retention is added. Remaining LAN work
precedes GUI; static VXLAN mapping and later separate EVPN/BGP remain required.

## Latest LAN increment: node-overlay Syslog disk queue validated — 2026-11-05

At implementation/validation commit
`5068997708973ea70b752982918ba92e127115ae`, optional
`--syslog-disk-queue` / `management.syslog_disk_queue:true` adds a private pure
disk action queue for TCP/TLS on the owned node overlay. Defaults remain
volatile; imported base-image spools are refused. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42045057015/job/127305646601)
passed in 21.711 seconds. Both transports verified real guest delivery,
fresh suspension, three on-disk markers, actual root-owned 0700 directory/
0600 files, exact PID/argv, sender SIGKILL/death, replay inside the same surviving
container without marker resubmission/local-log replay, actual TCP/TLS packets,
continued delivery, drift refusal and cold-restore non-retention. Default TCP
forwarding, default Syslog TLS and general CI also passed on that commit; 45
other jobs were intentionally skipped by manual selection.

Local tests passed 949 cases in 30.025 seconds with 148 environment-dependent
skips; compilation/diff checks passed. First native run 42044564699 / job
127303904974 failed because queue.fileCreateMode is unsupported in rsyslog
8.2312.0. The repair uses supported private umask 0077 and adds actual queue
file-mode checks; failed evidence is retained and recovery assertions remain.
See SYSLOG_DISK_QUEUE.md and the final LAN_NEXT_STEPS section for exact scope.
Only sender-process recovery is validated: lab stop/recreation removes the
spool, and host power-loss durability, broader durable retry/RELP, supervisors
and exactly-once delivery remain separate. Main/input/in-flight buffers stay
volatile and TLS spool data is plaintext at rest. Remaining LAN work precedes
GUI; static VXLAN mapping and separate later EVPN/BGP remain required.

## Latest LAN increment: Syslog TLS peer lifecycle validated — 2026-11-05

At implementation/validation commit
`9831449340f3f57571f8cf12cb946f22e12f9ed8`, opt-in
`--syslog-tls-preflight` / `verify_peer_on_start:true` on both declared peers
adds bounded offline mutual trust/time/role/exact-DNS-SAN checks before resource
allocation. Default live-failure labs remain available; distinct reciprocal
issuing CAs are supported. HTTPS shares the memory-BIO exchange helper.
The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42041335915/job/127292631585)
passed in 10.022 seconds. Pre-allocation role/time/trust/name refusal, stale
pins, actual guest logger and independent mutual-TLS storage, served collector
leaf fingerprints, both leaf/key replacements, CA replacement with old-trust/
old-client rejection, distinct issuers, cold restore, rollback, key isolation,
immutable base assets and host invariants passed. Original Syslog TLS, HTTPS
lifecycle, persistent HTTPS and general CI also passed on that commit; 43
unrelated jobs were intentionally skipped by manual suite selection.

Local tests passed 944 cases in 31.685 seconds with 147 environment-dependent
skips; compilation/diff checks passed. No failed native run preceded this
checkpoint. See SYSLOG_TLS_LIFECYCLE.md and the final LAN_NEXT_STEPS section
for scope and evidence. This is explicit offline replacement with downtime;
volatile logs/queues are not restored, and durable retry, automatic renewal,
live reload and revocation remain separate. Remaining LAN work precedes GUI;
static VXLAN VTEP/VNI/VLAN mapping and later separate EVPN/BGP remain required.

## Latest LAN increment: offline HTTPS identity lifecycle validated — 2026-11-05

At implementation/validation commit
`a0cac5c5a20cbe68647b0891a0ee7b077522ab8b`, HTTPS image build/startup adds
bounded memory-BIO validation of supplied local identity trust, current
host-clock validity and server purpose. No sockets, host trust roots or CA
fetching; name/IP verification remains the real client's task. Existing key
checks, pins and recreation policy remain intact. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42039875899/job/127287578185)
passed in 5.581 seconds. Expired/future/client-only/untrusted pre-allocation
refusal, live served-leaf DER fingerprints, leaf/key replacement under the
same CA, stale-pin refusal, CA replacement with old-trust rejection, cold
restore, explicit rollback, key isolation, immutable base identities and host
invariants passed. Original HTTPS and general CI also passed on that commit;
44 other jobs were intentionally skipped by manual suite selection.

Local tests passed 941 cases in 29.014 seconds with 146 environment-dependent
skips; compilation/diff checks passed. No failed native run preceded this
checkpoint. See HTTPS_IDENTITY_LIFECYCLE.md and the final LAN_NEXT_STEPS
section for usage/evidence/limits. This is explicit offline replacement with
downtime, not automatic renewal, revocation, live reload or Syslog lifecycle.
Remaining LAN work precedes GUI; static VXLAN VTEP/VNI/VLAN mapping and later
separate EVPN/BGP remain required roadmap work.

## Latest LAN increment: separate IPv6 DNS/TFTP validated — 2026-11-05

At implementation/validation commit
`4a8cb132a9640d92ef6e99d3a16d119b75bb07ce`,
`example --ipv6-dns-tftp` combines one managed IPv6 DNS server and one separate
read-only TFTP server across static ROAS VLANs and tagged transit. Clients use
only the declared managed resolver; TFTP retains explicit IP literals and adds
no automatic name resolution. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42037833110/job/127280504290)
passed in 32.381 seconds. Concurrent DNS/file observations, actual tagged
request/reply captures, separate listeners, AAAA/A-NODATA/NXDOMAIN, binary/hash
checks, independent service/route/VLAN failures with the other service healthy,
recovery, config drift refusal, cold restore and host invariants passed.
Standalone tagged DNS, tagged TFTP and general CI jobs also passed on that
commit; 42 unrelated jobs were intentionally skipped by suite selection.

Local confirmation passed 938 tests in 28.277 seconds with 145 environment-
dependent skips. The first local run had one timeout in the existing RADIUS
retry socket test; the unchanged seven-test retry module then passed in
1.514 seconds before that full confirming run. Compilation/diff checks passed.
No failed native run preceded this checkpoint. See IPV6_DNS_TFTP.md and the
final LAN_NEXT_STEPS section for exact bounds and selected regression results.
Remaining LAN work precedes GUI; static VXLAN VTEP/VNI/VLAN mapping and
separate later EVPN/BGP remain required roadmap work.

## Latest LAN increment: IPv6 TFTP over static dot1Q validated — 2026-11-05

At implementation/validation commit
`c8ad4031512625b9b6471f11aa202e028816a725`, the new
`example --ipv6-tftp-subinterfaces` supports one separate IPv6-only read-only
TFTP endpoint across static ROAS VLANs 10/20 and tagged transit 100.
The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42035723814/job/127273252102)
passed in 33.705 seconds. Actual tagged request/reply traffic, binary/hash
checks, clients on both routed VLANs, independent fault controls, recovery,
drift-save refusal, cold restore and host invariants passed. Physical IPv6
TFTP, IPv4 TFTP, static IPv6 subinterface and general CI jobs all passed on
that commit. Local tests passed 935 cases in 28.127 seconds with 144
environment-dependent skips. Compilation/diff checks passed; no failed native
run preceded this checkpoint.

See IPV6_TFTP_SUBINTERFACES.md and the final LAN_NEXT_STEPS section for exact
scope. Dynamic IPv6, SVIs, mixed/dual-stack, other services/security, writes,
authenticated/encrypted transfers and generic path MTU remain outside this
increment. Continue LAN before GUI; static VXLAN VTEP/VNI/VLAN mapping and
separate later EVPN/BGP remain required roadmap work.

## Latest LAN increment: managed IPv6 NTP relay validated — 2026-11-05

Commit `6db2e15853b357ab224012a47500cf17d1ea4888` adds
`example --ipv6-ntp-relay`: one managed stratum-10 local reference and one
clockless IPv6 relay serving stratum 11 with explicit client ACLs. Upstream
identity/ACL/graph bounds are validated, and acquisition binds the declared
relay address. Both daemons remain `-6 -x` without CAP_SYS_TIME. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42032733623/job/127262984424)
passed in 35.755 seconds. Standalone IPv6 NTP, IPv4 relay/client, IPv6 probe and
general CI jobs also passed on that commit. Local tests passed 932 cases with
143 environment-dependent skips. Wire/selected-source/ACL/capability evidence,
fresh-relay source-loss/no-local-fallback, recovery, drift, cold restore and
host invariants passed.

See IPV6_NTP_RELAY.md and the final LAN_NEXT_STEPS section for precise scope
and the retained first failed status-expectation fixture. Live relay holdover
is not bounded here; no immediate source-loss revocation or externally accurate
time is claimed. The user requested a visual explanation of this increment;
provide a service-flow diagram that distinguishes source, relay and client,
and explicitly notes no system clock adjustment. Continue LAN before GUI,
retaining static VXLAN and separate EVPN/BGP in the roadmap.

## Latest LAN increment: IPv6 local NTP reference validated — 2026-11-05

Commit `cdcd58c4213c5c7d495a017e8f2305d8b7cb54b8` adds explicit
`ntp_server.family:ipv6` and `example --ipv6-ntp` with a separate statically
bound chronyd local reference, /128 clients, `-6 -x`, no CAP_SYS_TIME and a
private read-only control path. IPv4 defaults/upstream/relay remain unchanged.
The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42030027136/job/127253825568)
passed in 16.291 seconds. IPv4 NTP relay/client, IPv6 probe and TFTP native
regressions plus general CI passed on that commit. Local tests passed 929 cases
with 142 environment-dependent skips. Real allowed/denied SNTP, exact UDP6/
PID/argv/live-capability evidence, independent routing-outage control, service
recovery, drift refusal, cold restore and host invariants passed.

See IPV6_NTP.md and the final LAN_NEXT_STEPS section for exact setup/evidence.
This is an isolated local reference, not accurate external time, NTS, an IPv6
upstream hierarchy, clock adjustment or broader dynamic/security combinations.
Continue remaining LAN before GUI, with static VXLAN and separate EVPN/BGP
still required on the roadmap. Older pending notes are historical.

## Latest LAN increment: IPv6 TFTP validated — 2026-11-05

Commit `cc2361876e6869e4e6674c721f027f3ba05b7891` adds explicit IPv6 TFTP
client/server family selection and `example --ipv6-tftp` over static physical
IPv6-only routing. IPv4 defaults remain unchanged. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/42028445357/job/127248456722)
passed in 26.111 seconds; IPv4 TFTP/blksize, static IPv6 subinterface and general
CI jobs also passed on that commit. Local tests passed 925 cases with 141
environment-dependent skips. Native binary/64-KiB reads, negotiation, hash/error
checks, service/routing outage controls, drift refusal, cold restore and host
invariants passed. Local IPv6 socket coverage tests wrong TIDs and repeated
final ACKs.

See IPV6_TFTP.md and the final LAN_NEXT_STEPS section for exact scope and usage.
This is bounded unauthenticated read-only TFTP with no DNS/family fallback,
not generic file services, writes, encrypted/authenticated transfers or broader
service/security/dynamic combinations. Continue remaining LAN before GUI;
static VXLAN and later separate EVPN/BGP remain required. Older pending notes
are historical, not current blockers.

## Latest LAN increment: AAAA-only DNS zones validated

Commit `9306d24d57f90949947a76aa9cd9c81e5ae92c47` accepts an explicit empty
DNS A map when valid AAAA data exists. Empty zones, missing A maps and existing
invalid data remain refused; listener families and other composition limits
are unchanged. `example --ipv6-dns-aaaa` provides the IPv6-only tagged-routing
reference without manufactured IPv4 answers. See DNS_AAAA_ONLY.md.

Extended [dual-stack native DNS](https://github.com/sou1915/Network-LABS/actions/runs/41903234244/job/126831053927)
passed in 43.186 seconds; [IPv6-only subinterface DNS](https://github.com/sou1915/Network-LABS/actions/runs/41903234244/job/126831053243)
passed in 23.898 seconds. General CI passed on the same commit. Real AAAA and
A/NODATA across transports, NXDOMAIN, managed probe family separation, retained
empty A maps and cold restore passed, alongside the original scenarios. Local
tests passed 920 cases with 140 environment-dependent skips. Exact evidence is
in the final LAN_NEXT_STEPS section. No CNAME/DNSSEC/DNS64/recursion/dynamic
widening is claimed. Continue remaining LAN before GUI, retaining static VXLAN
and separate EVPN/BGP in the roadmap. Older pending sections are historical.

## Latest LAN increment: optional IPv6 local-input policy validated

Commit `bb4d071538ca6e9a43d8b81b38a2aa41921a41b1` adds
`example --ipv6-input-firewall` with separate opt-in `firewall_ipv6.input`.
Omission preserves forward-only behavior; loopback and bounded static NDP are
mandatory exceptions, and output is unfiltered. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41902272895/job/126827572558)
passed in 33.861 seconds. Existing forward-firewall and DNS/firewall native
jobs plus general CI also passed on that commit. Local tests passed 917 cases
with 140 environment-dependent skips. Local listener allow/deny, fresh NDP,
stateful versus stateless local replies with preserved forwarding, legacy
omission, drift refusal, cold restore and host invariants passed.

See IPV6_INPUT_FIREWALL.md and the final LAN_NEXT_STEPS section for exact
scope, the retained first failed fixture run and remaining work. This is a
static physical firewall profile, not generic host/output/dual-stack/dynamic/
subinterface/SVI security coverage. Continue LAN before GUI; static VXLAN and
separate EVPN/BGP remain required. Earlier pending sections are historical.

## Latest LAN increment: IPv6 DNS/firewall coexistence validated

Commit `9df4670e82f600005136741a58e0705f92a0691a` adds
`example --ipv6-dns-firewall`, an explicit static physical IPv6-only DNS service
behind the existing stateful forwarding firewall. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41893486552/job/126796720048)
passed in 21.408 seconds. Existing IPv6 firewall, DNS/subinterface and general
CI jobs all passed on that commit. Local tests passed 914 cases with 139
environment-dependent skips. Wire/counter/conntrack evidence, a proven blocked
HTTP listener, stateless DNS-return negative controls, outage isolation, drift,
cold restore and host nftables/network invariants passed.

See IPV6_DNS_FIREWALL.md and the final LAN_NEXT_STEPS section for usage, exact
scope and remaining work. This does not implement local-input filtering or
broader dynamic/dual-stack/subinterface security combinations. Continue LAN
before GUI and retain static VXLAN and later separate EVPN/BGP in the roadmap.
Older pending notes below are historical; preceding bounded profiles remain
validated within their documented scope.

## Latest LAN increment: IPv6-only DNS over subinterfaces validated

Commit `bb17f52207a33fc73887db4342775761214c747f` adds
`example --ipv6-dns-subinterfaces`: an explicit IPv6-only DNS endpoint across
static ROAS VLANs and tagged transit, with no mixed dual-stack, AAA or dynamic/
security widening. The [dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41890023350/job/126784651019)
passed in 17.131 seconds; existing dual-stack DNS, static IPv6 subinterface and
general CI jobs all passed on that commit. Local tests passed 910 cases with
138 environment-dependent skips. See the final LAN_NEXT_STEPS section and
IPV6_DNS_SUBINTERFACES.md for exact proof, failed fixture run, setup and limits.

This completes one IPv6 subinterface service composition. Continue remaining
LAN AAA/IPv6/switching/services before GUI; static VXLAN and separate EVPN/BGP
remain required on the roadmap. Wired finite reauthentication proof below
remains valid. Older pending sections are historical, not current blockers.

## Latest boundary result: maximum budget and renewed-lease crash validated

At test-only commit `d5fdba582c5c45e8972c8daee4d57758256a4beb`, the
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41878259282/job/126743630911)
passed in **128.898 seconds**; general CI also passed on that commit. Four
real authentications, exactly eight RADIUS requests with fresh authenticators
and State, final-lease traffic, finite completion, and SIGKILL during the second
renewed lease with no subsequent admission/worker passed. Runtime code remains
the validated implementation below; this increment adds native boundary proof.

Earlier API reads returned queued snapshots. Final job timestamps/logs show
completion at 17:34 UTC, so those later queued observations were stale and must
not be interpreted as the actual queue duration. The pending sections below
are historical. See the final LAN_NEXT_STEPS section for exact evidence/limits.
Continue remaining LAN work before GUI, retaining static VXLAN and separate
EVPN/BGP in the roadmap.

## Latest result: finite reauthentication validated

At `b350281e625da65745725c726de57047cf88a02d`, the
[dedicated wired native job](https://github.com/sou1915/Network-LABS/actions/runs/41873926458/job/126728123068)
passed in **97.788 seconds**, and the general `tests` job passed on the same
commit. Local tests passed 906 cases with 137 environment-dependent skips.
The queued/pending sections below are historical and superseded by this result.
See the final LAN_NEXT_STEPS section for failed runs, atomic gate replacement,
bounded positive delivery checks and the exact scope. This is optional finite
closed-port reauthentication (0..3 extra exchanges), not a persistent service.
Continue remaining LAN work before GUI; static VXLAN and separate EVPN/BGP
remain tracked. No merge or full-LAN completion is claimed.

Repository: `sou1915/Network-LABS`.
Handoff branch: `handoff/codex-dot1x-2026-11-04`.
Last validated feature baseline: `feature/hybrid-appliance-runtime`, commit
`2f9fc98b9eb4247e6c6302eff6c33e2f08044887`.

## Goal and agreed order

Build a lightweight Linux desktop network lab simulator with Packet Tracer-like
usability and flexible native appliances, realistic observations/CLI, declarative
save/restore and later device GUIs. The user's laptop is an 8 GB Dell Latitude
5490; overall engine target is at most about 2 GB. Do not invent completion
percentages or claim all LAN/vendor behavior is implemented.

Complete bounded LAN AAA, IPv6, switching and service/security compositions,
then integrate the native engine into GUI. WAN follows later. VXLAN is required
and tracked: explicit static VTEP/VNI/VLAN mapping first; EVPN/BGP is separate.
Read `docs/LAN_NEXT_STEPS.md` for the sequence and previous native evidence.

## Validated baseline

The parent branch contains the prior IPv6/switching/service increments, local
AAA action/role policy, RADIUS SSH and Telnet bounded shells/accounting, durable
Stop outbox, explicit PID/boot/namespace/cgroup-pinned orphan reconciliation,
and native SIGKILL evidence for CLI/SSH/Telnet supervisors.

The latest completed EAP increment is a bounded two-request EAP-MD5/RADIUS
observation and opt-in FreeRADIUS backend with private hash-pinned password
assets. The successful implementation repair is
`34ddbaf9a06d6dc1f1d3dedd2d0b3f774dcef321`; native job:
https://github.com/sou1915/Network-LABS/actions/runs/41444614658/job/125274523414
It passed in 6.658 seconds. General CI/RADIUS also passed. The repair matters:
Cleartext-Password is a string; octet-style unquoted `0x` text was incorrect.
Managed EAP assets are printable ASCII, owned private 0600 files. Quoted literals
must disable expansion and preserve quotes/backslashes. Read
`docs/RADIUS_EAP_MD5.md` before modifying credential or protocol handling.

## Continuation result — 2026-11-04

The finite wired increment is now validated at
`4fafe9a02d69bc07fa8595a55bd6152ede252d05`. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41860209419/job/126679612230)
passed in 43.829 seconds; general CI also passed on that commit. Local tests
passed 901 cases with 137 environment-dependent skips. See the final wired
validation section in `LAN_NEXT_STEPS.md` for exact scope, failure history and
remaining LAN work. Save/stop/authentication now refresh state under the lock;
teardown confirms worker death after SIGKILL, and finalization handles a
concurrent separate-CLI stop without recreating runtime state.

The WIP and immediate-task sections below describe the original handoff
checkpoint and are retained as history. Their pending native result is
superseded by the evidence above. The bounded finite profile is complete;
broader LAN work still precedes GUI, with static VXLAN and later EVPN/BGP
separately tracked.

## Next LAN increment: finite reauthentication — native validation pending

Implementation `a6e20f9fdf164a0c832acb6d4998418ca23936b3` adds optional
`dot1x.reauthentications:0..3`. It closes the port before each new complete
EAP/RADIUS exchange, clears old transaction/State, pins the original accepted
identity and never reuses earlier success after outage/rejection. The omitted
policy keeps the validated single-lease behavior. This is finite foreground
reauthentication with closed intervals, not a persistent service.

Local checks passed 905 tests in 26.837 seconds with 137 environment-dependent
skips; compilation and diff checks passed. The
[dedicated native job](https://github.com/sou1915/Network-LABS/actions/runs/41864390885/job/126694713007)
and its general CI job were still queued without runner allocation at the last
check. Do not treat this new extension as native validated or merge it on the
strength of the older single-lease proof. The added native scenario covers two
real supplicant cycles, fresh RADIUS transactions/State, second-lease traffic,
backend loss between leases and cold restore/recovery.

The active replacement is targeted dispatch run `41864390885` at CI commit
`952d15442c731170efa5ffcb4ca5c055b5a0230a`. Both selected jobs (native wired and
general tests) are queued without assigned runners; 35 unrelated jobs are
intentionally skipped for this manual run. Push/PR scope is unchanged. Use
`gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=dot1x`
for a later targeted rerun. See LAN_NEXT_STEPS.md for scheduling evidence.

GitHub Status now reports an official Actions/Pages incident (investigating,
2026-11-04 16:05 UTC): https://stspg.io/pjgptg3cfc6n . Actions was observed
`degraded_performance`; selected checks have no failure annotations. Keep the
targeted run pending rather than dispatching duplicate retries during the
incident. Local native execution lacks sudo/effective capabilities.

Next action: follow that job, fix any failure without weakening authentication
or gate checks, then record its exact successful commit/job/duration in the
final LAN_NEXT_STEPS section. Continue LAN before GUI and retain the static
VXLAN and separate EVPN/BGP roadmap. Earlier known-failed and redundant
documentation-only workflow runs were asked to cancel to release runner
capacity; the original successful runtime validation run was retained.

## Work in progress on this handoff branch

This is an unvalidated native feature checkpoint, not a completed 802.1X claim.
The existing changes implement a first finite single-port wired admission
experiment using actual EAPOL pass-through to the managed EAP-MD5 backend and a
Linux nftables gate. Native interoperability has not yet been run/reviewed for
this checkpoint. Do not merge it as validated until that test passes.

Key files:

- `network_labs/appliances/dot1x.py`: narrow three-node/one-peer topology,
  default-closed bridge gate, dynamic admission fingerprint checks, finite
  authenticator controller and owned worker teardown.
- `network_labs/appliances/dot1x_worker.py`: raw EAPOL/UDP RADIUS state machine,
  namespace/interface/generation checks, original identity allowlist, verified
  challenge/State/Success, kernel timeout admission and Logoff/expiry handling.
- `tests/test_dot1x.py`: scope, gate bounds, EAPOL envelope and ownership tests.
- `tests/test_native_dot1x_integration.py`: real wired `wpa_supplicant`, EAPOL and
  RADIUS captures, blocked/admitted/expired bidirectional data, wrong credentials,
  Logoff, worker SIGKILL expiry, backend outage, cold restore and drift refusal.
- `docs/DOT1X_WIRED.md`: intended usage, finite scope and limits.
- `.github/workflows/tests.yml`: new `dot1x-wired-interop` job.

Other edits wire the policy into validation, NAS-SVI RADIUS client binding,
gate installation while physical interfaces are DOWN, lifecycle/inspect/save,
`example --radius --radius-eap-md5 --dot1x`, and `dot1x-auth LAB NAS`.

The finite admission lease is 1..30 seconds (default 5), enforced by a kernel
set timeout. SIGKILL is not instant revocation: remaining admission lasts no
longer than that lease. There is no automatic persistent reauthentication,
managed supplicant lifecycle, TLS, wireless mode, dynamic VLAN, multi-client
port, MACsec or accounting in this first wired profile. The independent native
supplicant is a host process restricted to the peer's network namespace; its
password is in a private file, not argv.

## Immediate next task

1. Review the WIP diff against the validated baseline; read the files above.
2. Run local unit tests and syntax checks. The handoff preparation run passed
   896 cases in 27.333 seconds with 138 environment-dependent skips. Recheck
   after further code edits; this local result is not native gate proof.
3. Run/follow the dedicated GitHub Actions `dot1x-wired-interop` job. The local
   workspace does not provide the privileges needed to establish native proof.
   Do not count skipped tests as successful native interoperability.
4. Fix failures and complete the real wire/data-path/lifecycle scenario before
   adding broader features. Inspect actual nftables JSON expiry formats and
   wired supplicant behavior rather than weakening authentication/gate checks.
5. Review teardown especially carefully: `dot1x.stop()` should confirm death
   after its final SIGKILL before deleting namespaces, including when stop runs
   in a different CLI process. Retain identity checks and reject unowned groups.
6. Check malformed/replayed EAPOL, queued Logoff vs backend Success, worker
   crash, runtime generation changes and gate drift. Never touch a recreated
   namespace or interpret missing resources as authenticated/closed evidence.
7. Once the native test passes, record its exact commit/job/duration and limits
   in LAN_NEXT_STEPS.md, then continue the agreed LAN-before-GUI sequence.

Typical local checks:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q network_labs tests
git diff --check
```

Dedicated privileged test (only on a suitable isolated Linux runner):

```bash
sudo env NETWORK_LABS_NATIVE_TESTS=1 python3 -m unittest discover -s tests \
  -p test_native_dot1x_integration.py -v
```

Its workflow installs crun, iproute2, busybox-static, util-linux, nftables,
tcpdump, freeradius and wpasupplicant. Existing secrets/password assets are not
part of this handoff; tests create their own private disposable fixtures.

## Communication and working preferences

The user communicates mostly in Darija and repeatedly authorizes continuing
work in this repo. Give concise progress/evidence, not speculative percentages.
Do not ask repeatedly for already-authorized reversible repo work. Preserve
explicit boundaries, failed-run evidence and native validation limits. Root
native tests must remain isolated to owned lab namespaces/resources. Do not
remove existing tests or weaken checks just to obtain a green result.


All ten selected jobs on final shell source passed in
[run 42293363242](https://github.com/sou1915/Network-LABS/actions/runs/42293363242),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42293363242/job/128154680651).
The other 52 profiles were intentionally skipped. The initial shell also
passed all ten selected jobs in run 42293016742. No native runtime behavior or
protocol assertions were changed for this GUI increment.


All ten selected jobs on graphical-editor source c6e3a28 passed in
[run 42302077273](https://github.com/sou1915/Network-LABS/actions/runs/42302077273),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42302077273/job/128184138620).
The other 52 profiles were intentionally skipped. No native runtime or safety
assertion was weakened to support graphical editing.


All ten selected jobs on device-form source 13b6dcf passed in
[run 42303521155](https://github.com/sou1915/Network-LABS/actions/runs/42303521155),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42303521155/job/128189114015).
The other 52 profiles were intentionally skipped. No runtime behavior,
protocol assertion or privilege boundary was weakened for this GUI increment.


All ten selected jobs on final visual source 22e2206 passed in
[run 42307186227](https://github.com/sou1915/Network-LABS/actions/runs/42307186227),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42307186227/job/128201233579).
The other 52 profiles were intentionally skipped. The visual redesign changed
presentation and the GUI test fixture; native runtime/protocol behavior and
privilege boundaries remain unchanged.


All ten selected jobs on reference-campus source 9fcbd4a passed in
[run 42311053032](https://github.com/sou1915/Network-LABS/actions/runs/42311053032),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42311053032/job/128214033629).
The other 52 profiles were intentionally skipped. The GUI/campus template and
fixture changed; native runtime/protocol assertions and privilege boundaries
were not weakened.


All ten selected jobs on polish source f27f49f passed in
[run 42313340373](https://github.com/sou1915/Network-LABS/actions/runs/42313340373),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42313340373/job/128221582556).
The other 52 profiles were intentionally skipped. No native runtime/protocol
or privilege assertion was changed to support the visual/usability polish.
