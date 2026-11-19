"""Inter-VLAN routing on a real Layer 3 switch guest (Catalyst 9200L), typed live: PC1 in VLAN 10 and PC2 in VLAN 20 do
not reach each other until « ip routing » (each « interface vlan N » is the guest bridge's br0.N, and the guest forwards);
then the trace goes through 192.168.10.1, the switch's routing table lists both VLANs, and « no ip routing » cuts it."""
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

from tests.test_layer3_switch import ROUTING, VLANS, lab
from tests.test_native_microvm_missions import wait_ready


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1' and os.environ.get('NETWORK_LABS_GUEST_VLAN') == '1',
                     'Opt-in real KVM test on a guest kernel with 802.1Q and bridge VLAN filtering')
class Layer3SwitchGuestTests(unittest.TestCase):
    def test_ip_routing_typed_live_routes_between_the_vlans(self):
        self.assertEqual(os.geteuid(), 0)
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'layer3-switch'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nll3-') as temporary:
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
                    consoles = {name: guest_console.Console(spec['name'], name) for name in ('SW1', 'PC1')}

                    def typed(lines):
                        for line in lines:
                            prompt = consoles['SW1'].prompt()
                            reply = consoles['SW1'].line(line)
                            transcript.append(prompt + line + ('\n' + reply if reply else ''))
                        return transcript[-1]

                    def ping(label, reach):
                        for _ in range(3):  # the first echo after a change can lose its ARP exchange
                            seen[label] = consoles['PC1'].line('ping 192.168.20.10')
                            if ('4 packets received' in seen[label]) == reach:
                                break
                            time.sleep(2)

                    typed(VLANS)
                    ping('PC1 -> PC2, Layer 2 only', False)
                    typed(ROUTING[1:])  # already in privileged EXEC
                    ping('PC1 -> PC2, ip routing', True)
                    seen['trace'] = consoles['PC1'].line('tracert 192.168.20.10')
                    typed(['sh ip route', 'sh ip int br'])
                    typed(['conf t', 'no ip routing', 'end'])
                    ping('PC1 -> PC2, no ip routing', False)
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            text = '\n'.join(transcript)
            (evidence / 'result.json').write_text(json.dumps({'transcript': text, **seen}, indent=2, ensure_ascii=False))
            print('\n' + text, flush=True)
            for label, reply in seen.items():
                print(f'\n{label}:\n{reply}', flush=True)
            self.assertIn('0 packets received', seen['PC1 -> PC2, Layer 2 only'])
            self.assertIn('4 packets received', seen['PC1 -> PC2, ip routing'])
            self.assertIn('0 packets received', seen['PC1 -> PC2, no ip routing'])
            self.assertRegex(seen['trace'], r'1 .* 192\.168\.10\.1\n.*2 .* 192\.168\.20\.10')
            table = next(t for t in transcript if t.startswith('SW1#sh ip route'))
            self.assertIn('C        192.168.10.0/24 is directly connected, Vlan10', table)
            self.assertIn('C        192.168.20.0/24 is directly connected, Vlan20', table)
            self.assertRegex(next(t for t in transcript if t.startswith('SW1#sh ip int br')), r'Vlan10 +192\.168\.10\.1 +YES manual up +up')
