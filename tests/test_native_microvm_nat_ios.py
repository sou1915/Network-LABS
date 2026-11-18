"""IOS PAT on a real router guest: typed in R1's terminal, PC1's private LAN reaches R2, which has no route back to it,
only once « ip nat inside / outside » and « ip nat inside source list 1 interface … overload » are in place."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console, topology_edit
from network_labs.appliances.guest_image import build
from network_labs.appliances.runtime import Manager
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project

from tests.test_native_microvm_missions import wait_ready

BEFORE = ['en', 'conf t', 'ip route 0.0.0.0 0.0.0.0 203.0.113.2', 'access-list 1 permit 192.168.1.0 0.0.0.255',
          'ip nat inside source list 1 interface g0/0/1 overload', 'end']
MARKS = ['conf t', 'int g0/0/0', 'ip nat inside', 'int g0/0/1', 'ip nat outside', 'end', 'sh ip nat statistics']


def lab(kernel, disk):
    """PC1 192.168.1.10 — R1 (Cisco) — R2 203.0.113.2, which knows only its own networks."""
    spec = blank_project('ios-nat')
    spec = topology_edit.add_microvm_node(spec, name='R1', role='router', kernel=kernel, disk=disk, ports=2, model='cisco-isr4331',
                                          addresses='192.168.1.1/24,203.0.113.1/30')
    spec = topology_edit.add_microvm_node(spec, name='R2', role='router', kernel=kernel, disk=disk, ports=2, model='cisco-isr4331',
                                          addresses='203.0.113.2/30,198.51.100.1/24')
    spec = topology_edit.add_microvm_node(spec, name='PC1', role='host', kernel=kernel, disk=disk, ports=1, addresses='192.168.1.10/24')
    next(n for n in spec['nodes'] if n['name'] == 'PC1')['gateway'] = '192.168.1.1'
    spec = topology_edit.connect(spec, ('PC1', 'eth0'), ('R1', 'eth0'))
    return validate(topology_edit.connect(spec, ('R1', 'eth1'), ('R2', 'eth0')))


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class IosNatGuestTests(unittest.TestCase):
    def test_pat_typed_in_the_router_terminal_translates_for_real(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'ios-nat'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlnat-') as temporary:
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
                    r1, pc1 = guest_console.Console(spec['name'], 'R1'), guest_console.Console(spec['name'], 'PC1')

                    def typed(console, lines):
                        for line in lines:
                            prompt = console.prompt()
                            reply = console.line(line)
                            transcript.append(prompt + line + ('\n' + reply if reply else ''))
                    typed(r1, BEFORE)
                    pings['without inside/outside'] = pc1.line('ping 198.51.100.1')
                    typed(r1, MARKS)
                    time.sleep(1)
                    pings['with PAT'] = pc1.line('ping 198.51.100.1')
                    typed(r1, ['sh ip nat translations', 'sh run | include nat'])
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            text = '\n'.join(transcript)
            (evidence / 'result.json').write_text(json.dumps({'transcript': text, 'pings': pings}, indent=2, ensure_ascii=False))
            print('\n' + text, flush=True)
            for label, reply in pings.items():
                print(f'\nPC1 ping 198.51.100.1 ({label}):\n{reply}', flush=True)
            self.assertIn('0 packets received', pings['without inside/outside'])  # R2 cannot answer 192.168.1.10
            self.assertIn('4 packets received', pings['with PAT'])  # it answers 203.0.113.1, R1 translates back
            self.assertIn('icmp', transcript[-2])  # the translation, read from the guest kernel
