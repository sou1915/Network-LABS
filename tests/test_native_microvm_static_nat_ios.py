"""IOS static NAT and a NAT pool on a real router guest, typed in R1's terminal: PC9 reaches PC1 by its public address
203.0.113.10 (R1 holds it on its outside port and translates), PC1 leaves as 203.0.113.10; once the static entry is
removed the address goes with it, and a pool (without overload) translates PC1 to one of its addresses."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console
from network_labs.appliances.guest_image import build
from network_labs.appliances.runtime import Manager

from tests.test_ios_nat import MARKS, POOL, STATIC, lab
from tests.test_native_microvm_missions import wait_ready


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class IosStaticNatGuestTests(unittest.TestCase):
    def test_static_nat_and_a_pool_typed_in_the_router_terminal_translate_for_real(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'ios-static-nat'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlsnat-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True, with_firewall=True)
            spec = lab(str(kernel), str(root / 'base.ext4'))
            transcript, pings = [], {}
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), \
                    patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name'])
                try:
                    with manager.locked():
                        manager.start(spec)
                        wait_ready(manager, spec)
                    r1 = guest_console.Console(spec['name'], 'R1')
                    pc1, pc9 = guest_console.Console(spec['name'], 'PC1'), guest_console.Console(spec['name'], 'PC9')

                    def typed(lines):
                        for line in lines:
                            prompt = r1.prompt()
                            reply = r1.line(line)
                            transcript.append(prompt + line + ('\n' + reply if reply else ''))

                    def ping(label, console, destination, reach):
                        for _ in range(3):  # the first echo after a change can lose its ARP exchange
                            pings[label] = console.line('ping ' + destination)
                            if ('4 packets received' in pings[label]) == reach:
                                break
                            time.sleep(1)

                    typed(['en'])
                    ping('PC9 -> 203.0.113.10, no NAT', pc9, '203.0.113.10', False)
                    typed(MARKS + STATIC)
                    ping('PC9 -> 203.0.113.10, static NAT', pc9, '203.0.113.10', True)
                    ping('PC1 -> PC9, static NAT', pc1, '198.51.100.10', True)
                    typed(['sh ip nat translations'])
                    typed(POOL)
                    ping('PC9 -> 203.0.113.10, static removed', pc9, '203.0.113.10', False)
                    ping('PC1 -> PC9, pool', pc1, '198.51.100.10', True)
                    typed(['sh ip nat translations', 'sh ip nat statistics'])
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            text = '\n'.join(transcript)
            (evidence / 'result.json').write_text(json.dumps({'transcript': text, 'pings': pings}, indent=2, ensure_ascii=False))
            print('\n' + text, flush=True)
            for label, reply in pings.items():
                print(f'\n{label}:\n{reply}', flush=True)
            self.assertIn('0 packets received', pings['PC9 -> 203.0.113.10, no NAT'])
            self.assertIn('4 packets received', pings['PC9 -> 203.0.113.10, static NAT'])  # R1 answers ARP and translates
            self.assertIn('4 packets received', pings['PC1 -> PC9, static NAT'])  # R2 has no route to 192.168.1.0/24
            self.assertIn('0 packets received', pings['PC9 -> 203.0.113.10, static removed'])
            self.assertIn('4 packets received', pings['PC1 -> PC9, pool'])
            static_table = next(t for t in transcript if t.startswith('R1#sh ip nat translations'))
            self.assertRegex(static_table, r'---  203\.0\.113\.10\s+192\.168\.1\.10')
            self.assertRegex(static_table, r'icmp 203\.0\.113\.10\S*\s+192\.168\.1\.10')  # read from the guest kernel
            self.assertRegex(transcript[-2], r'icmp 203\.0\.113\.2[01]\S*\s+192\.168\.1\.10')  # an address of the pool
