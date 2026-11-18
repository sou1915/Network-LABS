"""Packet Tracer style on real guests: unconfigured devices added as the workbench adds them, started, then configured
only from their terminals (IOS abbreviations on the router, ip addr / ip route on the PCs), live; the PCs then ping."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console, topology_edit
from network_labs.appliances.guest_image import build
from network_labs.appliances.runtime import Manager
from network_labs.appliances.ui_quick import blank_project

from tests.test_native_microvm_missions import wait_ready

TYPED = {'R1': ['en', 'sh ip int br', 'conf t', 'int g0/0/0', 'ip add 192.168.1.1 255.255.255.0', 'no shut', 'exit',
                'int g0/0/1', 'ip add 192.168.2.1 255.255.255.0', 'no shut', 'end', 'sh ip int br'],
         'PC1': ['ip addr add 192.168.1.10/24 dev eth0', 'ip route add default via 192.168.1.1', 'ip addr'],
         'PC2': ['ip addr add 192.168.2.10/24 dev eth0', 'ip route add default via 192.168.2.1', 'ping 192.168.1.10']}


def quick_lab(kernel, disk):
    """What three library clicks and two cables give in the workbench: no address anywhere."""
    spec = blank_project('quick-lab')
    spec = topology_edit.add_microvm_node(spec, name='R1', role='router', kernel=kernel, disk=disk, ports=2, model='cisco-isr4331')
    for name in ('PC1', 'PC2'):
        spec = topology_edit.add_microvm_node(spec, name=name, role='host', kernel=kernel, disk=disk, ports=1)
    spec = topology_edit.connect(spec, ('PC1', 'eth0'), ('R1', 'eth0'))
    return topology_edit.connect(spec, ('PC2', 'eth0'), ('R1', 'eth1'))


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class QuickLabGuestTests(unittest.TestCase):
    def test_unconfigured_devices_are_configured_live_from_their_terminals(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'quick'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlquick-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', size_mib=128, with_agent=True)
            spec = quick_lab(str(kernel), str(root / 'base.ext4'))
            transcript = []
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), \
                    patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name'])
                try:
                    with manager.locked():
                        manager.start(spec)
                        wait_ready(manager, spec)
                    for name, lines in TYPED.items():
                        console = guest_console.Console(spec['name'], name)
                        for line in lines:
                            reply = console.line(line)
                            transcript.append(console.prompt() + line + ('\n' + reply if reply else ''))
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            text = '\n'.join(transcript)
            (evidence / 'transcript.txt').write_text(text)
            print('\n' + text, flush=True)
            self.assertIn('192.168.1.1', transcript[-len(TYPED['PC2']) - len(TYPED['PC1']) - 1])  # R1's last sh ip int br
            self.assertIn('4 packets received', transcript[-1])  # PC2 reaches PC1 through R1, all configured live
