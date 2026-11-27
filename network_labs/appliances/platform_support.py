"""What this computer can run.

Labs run on Linux: micro-VMs need KVM as well, containers do not. Elsewhere (Windows, macOS) or for a micro-VM lab on a
Linux without KVM, the workbench runs in model mode, as Packet Tracer does: devices are drawn, cabled and configured
from their CLI windows, and show, ping, traceroute and the simulation mode answer from the network model. Only
starting real guests needs the Linux side.
"""
import os
import sys

MODEL_MODE = ('Cet ordinateur ne peut pas démarrer ce lab : {why}.\n\nIl reste utilisable en mode modèle, comme Packet '
              'Tracer : double-clic sur un équipement pour sa CLI (configuration, show, ping, traceroute) et ✉ Simulation, '
              'calculés par le modèle du réseau. Sur un ordinateur Linux avec KVM, ▶ Démarrer lance les vraies micro-VM.')


def blocker(spec=None, platform=None, kvm=None):
    """None when this computer can run lab actions (SPEC's lab, to start one); otherwise the reason, in French."""
    platform = sys.platform if platform is None else platform
    if not platform.startswith('linux'):
        return 'les micro-VM et les conteneurs du lab tournent sous Linux'
    has_kvm = os.path.exists('/dev/kvm') if kvm is None else kvm
    if spec is not None and not has_kvm and any(n.get('runtime') == 'firecracker' for n in spec.get('nodes', [])):
        return 'les micro-VM demandent KVM (/dev/kvm est absent)'
    return None


def model_mode(spec=None):
    """True when this computer can only run SPEC's lab in model mode."""
    return blocker(spec) is not None
