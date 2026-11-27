"""A static route through a port on real router guests, typed live: R1 sends everything out of g0/0/1 with no next hop
(« ip route 0.0.0.0 0.0.0.0 g0/0/1 »); PC1 reaches PC9 only once R2 answers R1's ARP by proxy (« ip proxy-arp », IOS's
default, typed back after « no ip proxy-arp »), and R1's ARP table then holds PC9's address with R2's MAC."""
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
from network_labs.appliances.runtime import Manager

from tests.test_ios_nat import lab
from tests.test_ios_routes import R1, R2_BACK
from tests.test_native_microvm_missions import wait_ready


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class PortRouteGuestTests(unittest.TestCase):
    def test_a_route_through_a_port_works_through_the_neighbours_proxy_arp(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'port-route'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlportroute-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = lab(str(kernel), str(root / 'base.ext4'))
            transcript, seen = [], {}
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), \
                    patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name'])
                try:
                    with manager.locked():
                        manager.start(spec)
                        wait_ready(manager, spec)
                    consoles = {name: guest_console.Console(spec['name'], name) for name in ('R1', 'R2', 'PC1')}

                    def typed(name, lines):
                        for line in lines:
                            prompt = consoles[name].prompt()
                            reply = consoles[name].line(line)
                            transcript.append(prompt + line + ('\n' + reply if reply else ''))

                    def ping(label, reach):
                        for _ in range(3):  # the first echo after a change can lose its ARP exchange
                            seen[label] = consoles['PC1'].line('ping 198.51.100.10')
                            if ('4 packets received' in seen[label]) == reach:
                                break
                            time.sleep(2)

                    typed('R1', R1)
                    typed('R2', R2_BACK)
                    ping('PC1 -> PC9, R2 without proxy ARP', False)
                    typed('R2', ['conf t', 'int g0/0/0', 'ip proxy-arp', 'end'])
                    ping('PC1 -> PC9, R2 with proxy ARP', True)
                    typed('R1', ['sh ip route', 'sh arp'])
                    typed('R2', ['sh arp'])
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            text = '\n'.join(transcript)
            (evidence / 'result.json').write_text(json.dumps({'transcript': text, **seen}, indent=2, ensure_ascii=False))
            print('\n' + text, flush=True)
            for label, reply in seen.items():
                print(f'\n{label}:\n{reply}', flush=True)
            self.assertIn('0 packets received', seen['PC1 -> PC9, R2 without proxy ARP'])
            self.assertIn('4 packets received', seen['PC1 -> PC9, R2 with proxy ARP'])
            self.assertIn('S*       0.0.0.0/0 is directly connected, GigabitEthernet0/0/1', transcript[-3])
            # R1 resolved PC9's address on g0/0/1 to R2's own MAC: proxy ARP answered by the real guest.
            r2_mac = re.search(r'Internet  203\.0\.113\.2\s+-   (\S+)', transcript[-1])[1]
            self.assertRegex(transcript[-2], rf'Internet  198\.51\.100\.10\s+0   {re.escape(r2_mac)}  ARPA   GigabitEthernet0/0/1')
