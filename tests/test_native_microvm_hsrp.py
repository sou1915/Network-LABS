"""HSRP on real router guests: R1 and R2 speak HSRP (version 1 on the PC's LAN, version 2 on the server's) from the lines
typed in their CLIs. R1 becomes active on the LAN (priority 110, preempt), R2 on the server side; PC1's gateway is the
virtual address, answered with the virtual MAC 0000.0c07.ac01, and PC1 reaches the server. Shutting R1's LAN port live
hands the LAN group to R2 (PC1 still reaches the server, same gateway MAC); « no shutdown » and R1 takes it back."""
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

from tests.test_hsrp import configured
from tests.test_native_microvm_missions import wait_ready

ACTIVE_R1 = r'Gi0/0/0 +1 +110 P Active +local +192\.168\.1\.3 +192\.168\.1\.1'
ACTIVE_R2 = r'Gi0/0/1 +2 +110 P Active +local +10\.0\.0\.2 +10\.0\.0\.1'
TAKEN_OVER = r'Gi0/0/0 +1 +100   Active +local +unknown +192\.168\.1\.1'
TAKEN_BACK = r'Gi0/0/0 +1 +110 P Active +local'


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1' and os.environ.get('NETWORK_LABS_GUEST_VLAN') == '1',
                     'Opt-in real KVM test on the Network LABS guest kernel (macvlan)')
class HsrpGuestTests(unittest.TestCase):
    def test_election_failover_and_preempt(self):
        self.assertEqual(os.geteuid(), 0)
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'hsrp'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlhs-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = configured(str(kernel), str(root / 'base.ext4'))['spec']
            seen = {}
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), \
                    patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name'])
                try:
                    with manager.locked():
                        manager.start(spec)
                        wait_ready(manager, spec)
                    consoles = {name: guest_console.Console(spec['name'], name) for name in ('R1', 'R2', 'PC1')}
                    for name in ('R1', 'R2'):
                        consoles[name].line('en')

                    def until(label, name, pattern, seconds):
                        deadline = time.monotonic() + seconds
                        while True:
                            seen[label] = consoles[name].line('show standby brief')
                            if re.search(pattern, seen[label]) or time.monotonic() >= deadline:
                                return
                            time.sleep(1)

                    def ping(label):
                        for _ in range(8):
                            seen[label] = consoles['PC1'].line('ping 10.0.0.10')
                            if '4 packets received' in seen[label]:
                                break
                            time.sleep(2)

                    def typed(name, lines):
                        for line in lines:
                            consoles[name].line(line)

                    until('R1 elected', 'R1', ACTIVE_R1, 70)  # listen, speak, standby, active: about 30 s with 3 / 10 s timers
                    until('R2 elected', 'R2', ACTIVE_R2, 30)
                    ping('PC1 -> SRV')
                    seen['PC1 arp'] = consoles['PC1'].line('arp -a')
                    seen['R1 show standby'] = consoles['R1'].line('show standby')
                    typed('R1', ['conf t', 'int g0/0/0', 'shutdown', 'end'])
                    until('R2 took over', 'R2', TAKEN_OVER, 30)
                    ping('PC1 -> SRV, R1 LAN port shut')
                    seen['R2 show standby'] = consoles['R2'].line('show standby')
                    typed('R1', ['conf t', 'int g0/0/0', 'no shutdown', 'end'])
                    until('R1 took back', 'R1', TAKEN_BACK, 40)
                    ping('PC1 -> SRV, R1 back')
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            (evidence / 'result.json').write_text(json.dumps(seen, indent=2, ensure_ascii=False))
            for label, text in seen.items():
                print(f'\n{label}:\n{text}', flush=True)
            self.assertRegex(seen['R1 elected'], ACTIVE_R1)
            self.assertRegex(seen['R2 elected'], ACTIVE_R2)
            self.assertIn('4 packets received', seen['PC1 -> SRV'])
            self.assertIn('00000c07ac01', re.sub(r'[-:.]', '', seen['PC1 arp'].lower()))  # the gateway is the virtual MAC
            self.assertIn('Active virtual MAC address is 0000.0c07.ac01 (MAC In Use)', seen['R1 show standby'])
            self.assertRegex(seen['R2 took over'], TAKEN_OVER)
            self.assertIn('4 packets received', seen['PC1 -> SRV, R1 LAN port shut'])
            self.assertRegex(seen['R1 took back'], TAKEN_BACK)
            self.assertIn('4 packets received', seen['PC1 -> SRV, R1 back'])
