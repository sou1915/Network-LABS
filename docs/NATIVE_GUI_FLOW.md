# Native GUI lifecycle and observations

The native workbench now has a topology view and a real backend result path.
Open it from the desktop's existing native-lab entry. It remains distinct
from the educational canvas and Wasm backend; opening this window does not
change their selected execution engine.

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
It retains a screenshot and JSON evidence. Native validation is pending.
