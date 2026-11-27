"""EIGRP typed in three real router guests' terminals (FRR's eigrpd in each, typed live): PC1 reaches PC3 across them
with no static route; R1 shows the route as D with IOS's metric and its neighbour R2."""
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

from tests.test_eigrp import TYPED
from tests.test_native_microvm_missions import wait_ready
from tests.test_rip import chain


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class EigrpGuestTests(unittest.TestCase):
    def test_eigrp_typed_in_the_router_terminals_carries_pc1_to_pc3(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'eigrp'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nleigrp-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', size_mib=128, with_agent=True, with_routing=True)
            spec = chain()
            for node in spec['nodes']:
                node['kernel'], node['disk'] = str(kernel), str(root / 'base.ext4')
            transcript, pings, seen = [], {}, {}
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), \
                    patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name'])
                try:
                    with manager.locked():
                        manager.start(spec)
                        wait_ready(manager, spec)
                    pc1 = guest_console.Console(spec['name'], 'PC1')
                    pings['before'] = pc1.line('ping 192.168.3.10')
                    for name, lines in TYPED.items():
                        console = guest_console.Console(spec['name'], name)
                        for line in lines:
                            prompt = console.prompt()
                            reply = console.line(line)
                            transcript.append(prompt + line + ('\n' + reply if reply else ''))
                    r1 = guest_console.Console(spec['name'], 'R1')
                    r1.line('en')
                    deadline = time.monotonic() + 60
                    while True:  # hellos every 5 s: two routers away in a few seconds
                        seen['table'] = r1.line('show ip route')
                        if 'D        192.168.3.0/24' in seen['table'] or time.monotonic() >= deadline:
                            break
                        time.sleep(2)
                    pings['after'] = pc1.line('ping 192.168.3.10')
                    seen['neighbors'] = r1.line('show ip eigrp neighbors')
                    seen['protocols'] = r1.line('show ip protocols')
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            result = {'transcript': transcript, 'pings': pings, **seen}
            (evidence / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
            print('\n' + '\n'.join(transcript), flush=True)
            for label, text in {**seen, **{'PC1 ping ' + k: v for k, v in pings.items()}}.items():
                print(f'\n{label}:\n{text}', flush=True)
            self.assertIn('0 packets received', pings['before'])
            # Learned by FRR's eigrpd in the guests; IOS's metric on GigabitEthernet (FRR's tenth).
            self.assertIn('D        192.168.3.0/24 [90/3328] via 10.0.12.2, GigabitEthernet0/0/1', seen['table'])
            self.assertIn('D        10.0.23.0/30 [90/3072] via 10.0.12.2, GigabitEthernet0/0/1', seen['table'])
            self.assertRegex(seen['neighbors'], r'\n0   10\.0\.12\.2\s+Gi0/0/1\s')
            self.assertIn('Routing Protocol is "eigrp 10"', seen['protocols'])
            self.assertIn('4 packets received', pings['after'])
