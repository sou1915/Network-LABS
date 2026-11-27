"""Model mode: the workbench on Windows or macOS (no fcntl, termios, pty, resource, grp, pwd, os.sysconf, Unix or vsock
sockets), or on a Linux without KVM for a micro-VM lab. The lab is drawn, configured from its CLIs, and answers show,
ping, traceroute and the simulation from the network model; only ▶ Démarrer says it needs Linux with KVM."""
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

from network_labs.appliances.platform_support import blocker

ROOT = Path(__file__).resolve().parents[1]

# Run in a fresh interpreter: the standard library is loaded first (on Linux it uses os.sysconf itself), then the
# Linux-only modules disappear before the first Network LABS import, as on Windows.
WINDOWS = textwrap.dedent('''
    import os, socket, sys
    import asyncio, unittest.mock, subprocess, json, ssl, hashlib, selectors, concurrent.futures, http.client  # noqa
    for name in ('fcntl', 'termios', 'pty', 'resource', 'grp', 'pwd', 'tty'):
        sys.modules[name] = None
    del os.sysconf
    for attribute in ('AF_VSOCK', 'AF_UNIX'):
        if hasattr(socket, attribute):
            delattr(socket, attribute)
    sys.path[:0] = [sys.argv[1]]
    from network_labs.appliances import guest_console, packet_sim, runtime, spanning_tree, spec, vendor_config  # noqa
    from network_labs.appliances.draft_lab import DraftLab
    from tests.test_layer3_switch import ROUTING, VLANS, lab
    box = {'spec': lab()}
    draft = DraftLab(lambda: box['spec'], lambda s: box.update(spec=spec.validate(s)))
    switch = guest_console.Console('l3', 'SW1', lambda _: draft)
    for line in VLANS + ROUTING:
        switch.line(line)
    pc = guest_console.Console('l3', 'PC1', lambda _: draft)
    print('PING', '4 packets received' in pc.line('ping 192.168.20.10'))
    print('SIM', packet_sim.simulate(box['spec'], 'PC1', '192.168.20.10')['ok'])
    try:
        import tkinter  # noqa: the GUI too, where this Python has Tk
    except ImportError:
        print('GUI skipped')
    else:
        from network_labs.appliances import ui, ui_cli, ui_simulation  # noqa
        print('GUI imported')
''')


class ModelModeTest(unittest.TestCase):
    def test_the_lab_works_without_linux_only_modules(self):
        done = subprocess.run([sys.executable, '-c', WINDOWS, str(ROOT)], capture_output=True, text=True, timeout=120, cwd=ROOT)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertIn('PING True', done.stdout)
        self.assertIn('SIM True', done.stdout)

    def test_who_can_start_what(self):
        micro = {'nodes': [{'runtime': 'firecracker'}]}
        containers = {'nodes': [{'runtime': 'oci'}]}
        self.assertIn('Linux', blocker(micro, platform='win32'))
        self.assertIn('Linux', blocker(containers, platform='darwin'))
        self.assertIn('KVM', blocker(micro, platform='linux', kvm=False))
        self.assertIsNone(blocker(containers, platform='linux', kvm=False))  # containers need no KVM
        self.assertIsNone(blocker(micro, platform='linux', kvm=True))
        self.assertIsNone(blocker(None, platform='linux', kvm=False))  # status, stop… on Linux


@unittest.skipUnless(__import__('os').environ.get('DISPLAY'), 'GUI requires X display')
class ModelModeWindowTest(unittest.TestCase):
    def test_start_explains_model_mode_and_the_status_line_says_it(self):
        import tkinter as tk
        from unittest.mock import patch
        from network_labs.__main__ import App
        from tests.test_layer3_switch import lab
        root = tk.Tk()
        try:
            window = App(root).open_native_lab()
            with patch('network_labs.appliances.platform_support.sys.platform', 'win32'), \
                    patch('network_labs.appliances.ui.messagebox.showinfo') as shown, \
                    patch('network_labs.appliances.ui.launch_terminal') as terminal:
                window.load_spec(lab())
                self.assertIn('Mode modèle', window.runtime_hint.get())
                self.assertFalse(window.launch('start'))
                terminal.assert_not_called()  # no sudo terminal: nothing could run here
                title, text = shown.call_args.args
                self.assertEqual(title, 'Mode modèle')
                self.assertIn('tournent sous Linux', text)
                self.assertIn('✉ Simulation', text)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
