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
artifact 13533009570, source commit and run/job, with the verified original ZIP
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
