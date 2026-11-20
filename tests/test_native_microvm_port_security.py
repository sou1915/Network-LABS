"""Port security on a real switch guest, typed live: Fa0/1 sticky learns PC1; Fa0/2's secure address is not PC2's, so
PC2's first frames err-disable it (violation shutdown: its link goes down in the guest) and PC2 reaches nobody; Fa0/3 in
restrict keeps PC3 out while the port stays up. With PC2's own address and « shutdown » then « no shutdown », Fa0/2
comes back and PC2 reaches PC1."""
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

from tests.test_native_microvm_missions import wait_ready
from tests.test_port_security_guest import RESTRICT, STICKY, WRONG_MAC, cisco, lab


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class PortSecurityGuestTests(unittest.TestCase):
    def test_violation_err_disables_restrict_keeps_out_and_shut_no_shut_recovers(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'port-security'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlps-') as temporary:
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
                    consoles = {name: guest_console.Console(spec['name'], name) for name in ('SW1', 'PC1', 'PC2', 'PC3')}

                    def typed(lines):
                        for line in lines:
                            prompt = consoles['SW1'].prompt()
                            reply = consoles['SW1'].line(line)
                            transcript.append(prompt + line + ('\n' + reply if reply else ''))
                        return transcript[-1]

                    def ping(label, source, destination, reach):
                        for _ in range(4):
                            seen[label] = consoles[source].line('ping ' + destination)
                            if ('4 packets received' in seen[label]) == reach:
                                break
                            time.sleep(2)

                    typed(STICKY + WRONG_MAC[1:] + RESTRICT[1:])  # already in privileged EXEC after the first block
                    ping('PC1 -> PC2 (Fa0/2 violation)', 'PC1', '192.168.1.20', False)
                    ping('PC1 -> PC3 (Fa0/3 restrict)', 'PC1', '192.168.1.30', False)
                    typed(['sh int status', 'sh port-security', 'sh port-security int fa0/2', 'sh port-security address'])
                    typed(['conf t', 'int fa0/2', 'no switchport port-security mac-address 0200.0000.0001',
                           f'switchport port-security mac-address {cisco("PC2")}', 'shutdown', 'no shutdown', 'end'])
                    ping('PC2 -> PC1 (recovered)', 'PC2', '192.168.1.10', True)
                    typed(['sh int status'])
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            text = '\n'.join(transcript)
            (evidence / 'result.json').write_text(json.dumps({'transcript': text, **seen}, indent=2, ensure_ascii=False))
            print('\n' + text, flush=True)
            for label, reply in seen.items():
                print(f'\n{label}:\n{reply}', flush=True)
            self.assertIn('0 packets received', seen['PC1 -> PC2 (Fa0/2 violation)'])
            self.assertIn('0 packets received', seen['PC1 -> PC3 (Fa0/3 restrict)'])
            status = next(t for t in transcript if t.startswith('SW1#sh int status'))
            self.assertRegex(status, r'Fa0/2 +err-disabled')
            self.assertRegex(status, r'Fa0/3 +connected')
            self.assertIn('Port Status                : Secure-shutdown', next(t for t in transcript if 'sh port-security int fa0/2' in t))
            self.assertRegex(next(t for t in transcript if t.startswith('SW1#sh port-security address')),
                             rf'{re.escape(cisco("PC1"))} +SecureSticky +Fa0/1')
            self.assertRegex(next(t for t in transcript if t.startswith('SW1#sh port-security\n')), r'Fa0/3 +1 +1 +[1-9]\d* +Restrict')
            self.assertIn('4 packets received', seen['PC2 -> PC1 (recovered)'])
            self.assertRegex(transcript[-1], r'Fa0/2 +connected')
