# Native GUI lifecycle and observations

The native workbench now has a topology view and a real backend result path.
Open it from the desktop's existing native-lab entry. It uses the agreed
main-window layout while keeping native state separate from the educational
canvas and Wasm backend. Returning restores their existing project and engine.

## First usable flow

1. Prepare a native BusyBox rootfs using the existing appliance guide, then
   choose **Nouveau LAN** (name/rootfs) or open an existing native manifest.
2. Review the generated nodes/links. JSON configuration remains available;
   **Valider / plan** validates it offline and redraws the declared topology.
3. **Démarrer** saves a private project and sends a private per-operation
   manifest snapshot to the real backend. Confirm sudo in the external terminal.
4. **Actualiser l’état** shows actual OCI process states and per-node cgroup
   RAM. Select a node and **Inspecter** for kernel links/addresses/routes.
5. Select an OCI host and destination and choose **Tester liaison** for a
   bounded, bidirectional native IPv4 ICMP verification. Failed/blocked tests
   remain failures; a running process is not proof of network delivery.
6. **Arrêter** updates the view only after backend teardown is confirmed.

The graph is the selected manifest before observation and the backend's
public running topology after a response. Edges are declared links, not
simulated packet delivery. Green indicates an observed running OCI process;
unknown/unobserved and Firecracker guest readiness are not marked running.
Observations are snapshots requested by the user, not continuous monitoring.
Status/stop/inspect use the displayed lab even if the JSON editor is invalid.

## Privilege and result handling

The desktop stays unprivileged. An unprivileged terminal wrapper authenticates
with `sudo -v` using the terminal's real input/error streams, then invokes a
fixed typed backend with `sudo -n`. Only start/status/stop/inspect and bounded
verify operations are accepted. No shell command string is constructed.
The backend uses the existing native Manager/locks and returns a public
topology and redacted observations; rootfs/private credential policies remain
in the existing engine.

Only the unprivileged wrapper writes GUI results. Each request/result has a
unique context and lives in a private user directory with mode-0600 JSON.
Manifest saves use private atomic replacement. Stale/mismatched/public result
files and malformed backend replies do not produce a success state. The GUI
does not collect passwords, elevate itself or write result paths as root.

Opening a different project changes the displayed lab without stopping other
labs. Closing the window does not stop a running lab or cancel privileged
operations. If the terminal closes without a result, a five-minute UI wait
limit reports uncertainty and permits a fresh status request; it never kills
the privileged operation or assumes teardown. Explicit Stop remains required.

## Scope and validation

This is the first native GUI vertical slice: automatic topology view, basic
LAN creation, JSON configuration, lifecycle, runtime observations and a real
connectivity check. Canvas node/link editing, full per-device configuration
forms, embedded consoles/capture workflows, broader project management and
desktop/hardware acceptance remain later GUI work. LAN core remains closed;
advanced LAN extensions must not become new prerequisites.

Unit/Tk tests cover private transport, sudo ordering, typed argv, canceled
authentication, bad/stale results and honest visual states. The dedicated
native GUI test runs Tk as the normal hosted-runner user, uses the actual
sudo/backend and OCI packets, verifies private result ownership and confirms
stop/host cleanup. Only external-terminal presentation is replaced for CI's
passwordless sudo; interactive password-prompt UX still needs a real desktop.
It retains a screenshot and JSON evidence.

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


## Captured GUI evidence

![Running native GUI with verified traffic](images/native-gui-running.png)

This is the actual Xvfb capture after real native verification.
The public [operation report](images/native-gui-result.json) records the UI UID,
result-file owners, native probe and stop outcome. The
[provenance record](images/native-gui-provenance.json) binds both files to
artifact 13545820693, source commit and run/job, with the verified original ZIP
SHA-256 and individual file hashes. The desktop/native job passed on the same commit.

## Previous desktop layout (rejected as the design reference)

The native LAN now uses the existing [workspace design](workspace_design.png):
light theme, equipment list on the left, topology in the centre and inspector
on the right. Device cards reuse the desktop's own icons and shared colours.
Opening native LAN replaces the visible workspace inside the main window;
**Retour au projet pédagogique** restores the previous project and its save
shortcut without changing its backend. Switching views does not stop a lab.
Native process state and connectivity results still come from the real backend.
The inspector keeps the result of a connectivity check visible beside the graph.

This corrects the previous separate technical-window presentation. The left
list selects existing native devices; graphical creation/cabling and full
per-device forms remain pending. JSON, dependencies and detailed observations
are available as central tabs. This is alignment with the agreed layout, not
completion of all GUI editing workflows.


At source `a82b0571194f81759e29bf6e50d8e5b65dfd8664`, the
[desktop/native job](https://github.com/sou1915/Network-LABS/actions/runs/42276785462/job/128095032017)
passed 1033 regression cases in 47.945 seconds (116 environment/opt-in skips).
The real native GUI test passed in 4.466 seconds using the actual main App and
embedded native workspace, including return to the preserved model project.
It verified three running OCI devices, kernel inspection, bidirectional ICMP,
six private user-owned responses, direct root-state denial and confirmed
teardown without callback errors or host-network leaks. The screenshot and
report above now show this embedded layout rather than the earlier window.
Local full regression passed 1033 cases in 30.311 seconds (166 skips, including
Tk because the local environment has no display); desktop execution was
verified in CI. Interactive password-prompt and hardware acceptance remain open.

The same source also passed all ten selected jobs in
[run 42276785462](https://github.com/sou1915/Network-LABS/actions/runs/42276785462),
including the [7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42276785462/job/128097531781).
The dedicated wired 802.1X job passed managed-peer recovery (55.167 s) and
independent-supplicant admission/revocation (219.122 s); 52 other profiles were
intentionally skipped. The superseded run 42276666855 was canceled after the
explicit desktop-entry correction, not used as final validation evidence.


## User-supplied target design

![Authoritative GUI reference](images/agreed-gui-reference.jpg)

This is the user's target mockup, not an implementation screenshot. It
supersedes workspace_design.png and enterprise_lan.png as the visual target.
The current native workbench has verified backend functionality but does not
implement this design yet. See CODEX_HANDOFF.md for the required layout and
capability boundaries.

## Reference shell implementation

The first increment toward the supplied mockup adds a compact dark title bar,
a central topology/technical notebook, a resizable bottom dock for real native
results, and a neighbouring operation-event table. The project equipment list
supports case-insensitive search by name, role or runtime. Redrawing or loading
a project preserves the search without leaving hidden stale equipment entries.

Events record received backend operation outcomes, including failures; they
are not packet capture events. The dark results dock displays real inspection
and probe JSON, not an interactive vendor CLI. Device thumbnails, VLAN/DMZ
visual groups, graphical editing, embedded device forms/interactive consoles
and packet-event integration remain pending. The supplied mockup is still the
target, and this increment is not visual completion or a firmware replica.


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


All ten selected jobs on final shell source passed in
[run 42293363242](https://github.com/sou1915/Network-LABS/actions/runs/42293363242),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42293363242/job/128154680651).
The other 52 profiles were intentionally skipped. The initial shell also
passed all ten selected jobs in run 42293016742. No native runtime behavior or
protocol assertions were changed for this GUI increment.

## Graphical topology editing

**Ajouter** creates a generic OCI Linux host, switch or router with an explicit
rootfs, name, 1–16 initial ports and optional IPv4/CIDR on eth0. Use empty
physical addresses for switches. Advanced existing configurations and
Firecracker remain editable through JSON, not cloned as generic devices.

**Câbler** selects two devices on the canvas, then offers their free ports.
If an OCI device has no free port, the dialog explicitly labels a new port;
confirmation creates that interface and cable together in the draft. There
is no silent modification to a running node. Native manifest validation
rejects occupied/invalid ports, self-links and unguarded switch loops. A
refused cable never leaves a newly created interface behind. Canceling the
port dialog changes nothing. Right-click a cable to remove it from the draft.
**Supprimer** removes the selected device and its attached cables. Deleting
the last node, or breaking advanced references, is refused by native validation.

**Sélection** restores selection/dragging. Dragging repositions a card; links
follow on release. Coordinates currently last only for this workbench session,
while saved native JSON retains the actual devices, interfaces and cables.
There is no persisted layout/undo history yet.

All edits run against an isolated copy and commit only after full native
validation. Editing is blocked during pending native operations. If JSON or
backend observation differs from the drawing, use **Configuration JSON →
Valider / plan** before editing. Edits clear runtime colours and label the
view as a draft: save, explicitly stop the running lab if needed and start to
apply. An observed status can redisplay the actual running topology without
overwriting the JSON draft. There is no live topology reconfiguration.

The native GUI scenario now inserts a second switch and a third host,
rewires the draft to five devices/four links, saves it through the GUI, then
starts the real OCI fabric and verifies PC1 ↔ PC3. Form/click/drag tests cover
adding, cable-port selection and extension, loop rejection without partial
edits, pending-operation guards and JSON/view mismatch. The packet scenario
uses the same GUI commit path; it does not automate physical mouse gestures.
Device photos, VLAN visual groups, per-device configuration forms,
interactive consoles and packet-event views remain separate pending work.


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


All ten selected jobs on graphical-editor source c6e3a28 passed in
[run 42302077273](https://github.com/sou1915/Network-LABS/actions/runs/42302077273),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42302077273/job/128184138620).
The other 52 profiles were intentionally skipped. No native runtime or safety
assertion was weakened to support graphical editing.

## Basic device configuration

The right device pane now has **État / test** and **Configuration** tabs.
Choose an OCI device, then edit its name, one physical port's IPv4/CIDR,
node-wide IPv4 gateway and enabled state. Apply commits a validated draft;
save and stop/start are still required to change the running network. This
is a generic native project form, not a vendor firmware GUI. It edits one
selected port per application; selecting another port reloads that port's
saved values. **Recharger le formulaire** discards unapplied form fields.

Switch physical addresses and gateway are read-only here (SVI configuration
remains JSON). DHCP-managed port addresses are read-only; DHCP is not switched
to static implicitly. Firecracker remains read-only in this basic form. Other
configuration is retained and checked by the existing native validator.

A basic rename updates cable endpoints and retains the session position.
Exact structured references, startup scripts or custom commands make renaming
conservative: use explicit JSON editing for such projects rather than guessing
how to rewrite advanced references. Invalid addressing, duplicate names,
unknown ports or unsupported combinations commit no part of the change.

The form snapshots the whole canonical draft when loaded. If another action
changes any project configuration, the old form refuses Apply and asks for
reload; this also catches changes invisible in the public topology such as
memory settings. Pending native operations refuse Apply. Form drafts do not
replace observed kernel state and do not imply successful network traffic.

The real native GUI scenario now uses this form to rename PC3 to CLIENT3,
change its address to 192.0.2.33/24 and set gateway 192.0.2.20 before save/start.
It then inspects the actual default route and verifies PC1 ↔ CLIENT3 using the
new IPv4 address. The screenshot selects the new Configuration tab.


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


All ten selected jobs on device-form source 13b6dcf passed in
[run 42303521155](https://github.com/sou1915/Network-LABS/actions/runs/42303521155),
including wired 802.1X and the
[7/7 LAN aggregate](https://github.com/sou1915/Network-LABS/actions/runs/42303521155/job/128189114015).
The other 52 profiles were intentionally skipped. No runtime behavior,
protocol assertion or privilege boundary was weakened for this GUI increment.
