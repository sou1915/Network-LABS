"""RIP typed in three real router guests' terminals (BIRD in each): PC1 reaches PC3 across them with no static route;
then tracert on PC1 and traceroute on R1 show the routers hop by hop, from real probes."""
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

from tests.test_native_microvm_missions import wait_ready
from tests.test_rip import TYPED, chain


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class RipGuestTests(unittest.TestCase):
    def test_rip_typed_in_the_router_terminals_carries_pc1_to_pc3(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'rip'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlrip-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True, with_routing=True)
            spec = chain()
            for node in spec['nodes']:
                node['kernel'], node['disk'] = str(kernel), str(root / 'base.ext4')
            transcript, pings, table, traces = [], {}, '', {}
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
                    deadline = time.monotonic() + 60
                    r1 = guest_console.Console(spec['name'], 'R1')
                    r1.line('en')
                    while True:  # RIP updates every 5 s in the lab: two hops to learn
                        table = r1.line('show ip route')
                        if 'R        192.168.3.0/24' in table or time.monotonic() >= deadline:
                            break
                        time.sleep(2)
                    pings['after'] = pc1.line('ping 192.168.3.10')
                    transcript.append('R1#show ip protocols\n' + r1.line('show ip protocols'))
                    traces['PC1 tracert'] = pc1.line('tracert 192.168.3.10')
                    traces['R1 traceroute'] = r1.line('traceroute 192.168.3.10')
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            result = {'transcript': transcript, 'table': table, 'pings': pings, 'traces': traces}
            (evidence / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
            print('\n' + '\n'.join(transcript) + '\n\nR1#show ip route\n' + table, flush=True)
            for label, reply in pings.items():
                print(f'\nPC1 ping 192.168.3.10 ({label}):\n{reply}', flush=True)
            self.assertIn('0 packets received', pings['before'])
            self.assertIn('R        192.168.3.0/24 [120/2] via 10.0.12.2, GigabitEthernet0/0/1', table)
            self.assertIn('4 packets received', pings['after'])
            for label, reply in traces.items():
                print(f'\n{label} 192.168.3.10:\n{reply}', flush=True)
            # Real probes, hop by hop: each router answers from the port the probe came in by, PC3 last.
            self.assertRegex(traces['PC1 tracert'], r'  1 .* ms  192\.168\.1\.1\n  2 .* ms  10\.0\.12\.2\n  3 .* ms  10\.0\.23\.2\n'
                                                    r'  4 .* ms  192\.168\.3\.10\n\nTrace complete\.')
            self.assertRegex(traces['R1 traceroute'], r'  1 10\.0\.12\.2 \d+ msec.*\n  2 10\.0\.23\.2 .*\n  3 192\.168\.3\.10 \d+ msec')
