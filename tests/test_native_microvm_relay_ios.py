"""IOS DHCP relay on real router guests: R2 serves 192.168.10.0/24, a LAN two hops away (its pool typed before the lab
starts, as in Packet Tracer); PC1's DHCP client gets nothing until « ip helper-address 10.0.12.2 » is typed on R1's LAN
port, live; then PC1 takes an address from R2 through R1's relay and reaches R2."""
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
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.guest_image import build
from network_labs.appliances.runtime import Manager
from network_labs.appliances.spec import validate

from tests.test_ios_relay import HELPER, POOL, lab
from tests.test_native_microvm_missions import wait_ready


def configured(kernel, disk):
    """The lab with R2's relayed pool and its route back, typed in R2's terminal before ▶ Démarrer."""
    box = {'spec': lab(kernel, disk)}
    draft = DraftLab(lambda: box['spec'], lambda spec: box.update(spec=validate(spec)))
    console = guest_console.Console('ios-relay', 'R2', lambda _: draft)
    for line in POOL:
        console.line(line)
    return box['spec']


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class IosRelayGuestTests(unittest.TestCase):
    def test_helper_address_typed_live_relays_the_remote_client_to_its_server(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'ios-relay'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlrelay-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = configured(str(kernel), str(root / 'base.ext4'))
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

                    time.sleep(6)  # several discover rounds of PC1's client: nothing relays them yet
                    seen['before'] = consoles['PC1'].line('ip addr')
                    typed('R1', HELPER)
                    deadline = time.monotonic() + 45
                    while True:
                        seen['after'] = consoles['PC1'].line('ip addr')
                        if 'inet 192.168.10.' in seen['after'] or time.monotonic() >= deadline:
                            break
                        time.sleep(1)
                    seen['ping'] = consoles['PC1'].line('ping 10.0.12.2')
                    typed('R2', ['en', 'sh ip dhcp binding'])
                    typed('R1', ['sh run | include helper'])
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            text = '\n'.join(transcript)
            (evidence / 'result.json').write_text(json.dumps({'transcript': text, **seen}, indent=2, ensure_ascii=False))
            print('\n' + text, flush=True)
            for label, reply in seen.items():
                print(f'\nPC1 ({label}):\n{reply}', flush=True)
            self.assertNotIn('inet 192.168.10.', seen['before'])
            leased = re.search(r'inet 192\.168\.10\.(\d+)/24', seen['after'])
            self.assertTrue(leased and 10 <= int(leased[1]) <= 254, seen['after'])  # any pool address past the excluded .1-.9
            self.assertIn('4 packets received', seen['ping'])  # through the lease's default router, R1
            self.assertRegex(transcript[-2], r'\n192\.168\.10\.\d+\s+01[0-9a-f]{2}\.[0-9a-f]{4}\.')  # read in R2's lease file
            self.assertIn('ip helper-address 10.0.12.2', transcript[-1])
