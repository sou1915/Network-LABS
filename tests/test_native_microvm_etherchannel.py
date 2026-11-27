"""EtherChannel on real switch guests: SW1 (channel-group 1 mode active) and SW2 (mode passive) bundle their two cables
with real LACP between the guest kernels' 802.3ad bonds. « show etherchannel summary » reads Po1(SU) with Fa0/1(P)
Fa0/2(P) on both; spanning tree has one port, Po1, forwarding (nothing blocks); PC1 reaches PC2; shutting Fa0/1 on SW1
live leaves the bundle up on Fa0/2 and PC1 still reaches PC2."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.guest_image import build
from network_labs.appliances.runtime import Manager
from network_labs.appliances.spec import validate

from tests.test_etherchannel import SW1, SW2, lab, ports_of
from tests.test_guest_stp import ports
from tests.test_native_microvm_missions import wait_ready


def configured(kernel, disk):
    """The lab with both switches' lines typed in their CLIs while it is stopped (a bundle is set up at ▶ Démarrer)."""
    box = {'spec': lab(kernel, disk)}
    draft = DraftLab(lambda: box['spec'], lambda spec: box.update(spec=validate(spec)))
    for name, lines in (('SW1', SW1), ('SW2', SW2)):
        console = guest_console.Console('etherchannel', name, lambda _: draft)
        for line in lines:
            console.line(line)
    return box['spec']


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1' and os.environ.get('NETWORK_LABS_GUEST_VLAN') == '1',
                     'Opt-in real KVM test on the Network LABS guest kernel (802.1Q, bonding)')
class EtherChannelGuestTests(unittest.TestCase):
    def test_lacp_bundles_both_cables_and_survives_a_member_shut(self):
        self.assertEqual(os.geteuid(), 0)
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'etherchannel'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlec-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = configured(str(kernel), str(root / 'base.ext4'))
            seen = {}
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), \
                    patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name'])
                try:
                    with manager.locked():
                        manager.start(spec)
                        wait_ready(manager, spec)
                    consoles = {name: guest_console.Console(spec['name'], name) for name in ('SW1', 'SW2', 'PC1')}
                    for name in ('SW1', 'SW2'):
                        consoles[name].line('en')

                    def bundled(label, wanted):
                        deadline = time.monotonic() + 40
                        while True:
                            views = {name: consoles[name].line('show etherchannel summary') for name in ('SW1', 'SW2')}
                            if all(wanted(ports_of(view)) for view in views.values()) or time.monotonic() >= deadline:
                                seen[label] = views
                                return
                            time.sleep(1)

                    def ping(label):
                        for _ in range(10):
                            seen[label] = consoles['PC1'].line('ping 192.168.1.20')
                            if '4 packets received' in seen[label]:
                                break
                            time.sleep(2)

                    bundled('bundled', lambda view: view == {'Po1(SU)': ['Fa0/1(P)', 'Fa0/2(P)']})
                    seen['bonds SW1'] = consoles['SW1'].query('bond-show')
                    ping('PC1 -> PC2')
                    seen['spanning tree SW1'] = consoles['SW1'].line('show spanning-tree')
                    for line in ('conf t', 'int fa0/1', 'shutdown', 'end'):
                        consoles['SW1'].line(line)
                    deadline = time.monotonic() + 30
                    while True:
                        seen['after Fa0/1 shut'] = consoles['SW1'].line('show etherchannel summary')
                        if ports_of(seen['after Fa0/1 shut']) == {'Po1(SU)': ['Fa0/1(D)', 'Fa0/2(P)']} or time.monotonic() >= deadline:
                            break
                        time.sleep(1)
                    ping('PC1 -> PC2, one cable')
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            (evidence / 'result.json').write_text(json.dumps(seen, indent=2, ensure_ascii=False))
            for label, text in seen.items():
                print(f'\n{label}:\n{text}', flush=True)
            for name in ('SW1', 'SW2'):
                self.assertEqual(ports_of(seen['bundled'][name]), {'Po1(SU)': ['Fa0/1(P)', 'Fa0/2(P)']}, name)
            self.assertIn('4 packets received', seen['PC1 -> PC2'])
            tree = ports(seen['spanning tree SW1'])
            self.assertEqual(tree.get('Po1', (None, None))[1], 'FWD')
            self.assertNotIn('BLK', [state for _, state in tree.values()])
            self.assertEqual(ports_of(seen['after Fa0/1 shut']), {'Po1(SU)': ['Fa0/1(D)', 'Fa0/2(P)']})
            self.assertIn('4 packets received', seen['PC1 -> PC2, one cable'])
