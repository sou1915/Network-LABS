"""Sixteen ports on a real switch guest: a Catalyst 2960 micro-VM boots with eth0..eth15 (Firecracker gives it sixteen
network devices beside its disk and vsock, in port order), PC1 on Fa0/1 reaches PC2 on Fa0/16 through the guest
bridge, and « show interfaces status » lists all sixteen ports, the two cabled ones connected."""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console
from network_labs.appliances.guest_image import build
from network_labs.appliances.guest_startup import query
from network_labs.appliances.runtime import Manager

from tests.test_guest_ports import switch_lab
from tests.test_native_microvm_missions import wait_ready


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class SixteenPortGuestTests(unittest.TestCase):
    def test_a_sixteen_port_switch_boots_and_its_last_port_carries_traffic(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'ports'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlports-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = switch_lab()
            for node in spec['nodes']:
                node.update(kernel=str(kernel), disk=str(root / 'base.ext4'))
            seen = {}
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), \
                    patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name'])
                try:
                    with manager.locked():
                        manager.start(spec)
                        wait_ready(manager, spec)
                    seen['guest interfaces'] = query(manager.directory / 'SW1' / 'guest.vsock', 'addresses')
                    seen['bridge ports'] = query(manager.directory / 'SW1' / 'guest.vsock', 'bridge-ports')
                    pc1 = guest_console.Console(spec['name'], 'PC1')
                    for _ in range(5):
                        seen['PC1 -> PC2'] = pc1.line('ping 192.168.1.20')
                        if '4 packets received' in seen['PC1 -> PC2']:
                            break
                        time.sleep(2)
                    switch = guest_console.Console(spec['name'], 'SW1')
                    switch.line('en')
                    seen['show interfaces status'] = switch.line('show interfaces status')
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            (evidence / 'result.json').write_text(json.dumps(seen, indent=2, ensure_ascii=False))
            for label, text in seen.items():
                print(f'\n{label}:\n{text}', flush=True)
            names = re.findall(r'^\d+: (eth\d+)', seen['guest interfaces'], re.M)
            self.assertEqual(names, [f'eth{i}' for i in range(16)])  # all sixteen, in port order
            self.assertEqual(sorted(seen['bridge ports'].split()), sorted(f'eth{i}' for i in range(16)))
            self.assertIn('4 packets received', seen['PC1 -> PC2'])
            status = seen['show interfaces status']
            self.assertRegex(status, r'Fa0/1 .* connected')
            self.assertRegex(status, r'Fa0/16 .* connected')
            self.assertRegex(status, r'Fa0/8 .* notconnect')
