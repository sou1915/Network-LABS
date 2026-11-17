"""Real guests grade a mission: the broken route lab fails its pings, the IOS fix makes them pass."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances import missions, vendor_config
from network_labs.appliances.guest_image import build
from network_labs.appliances.guest_startup import query
from network_labs.appliances.runtime import Manager


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class MissionGuestTests(unittest.TestCase):
    def test_route_mission_fails_then_passes_on_real_guests(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'mission'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlms-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            broken = missions.mission('route-manquante')['build'](kernel, root / 'base.ext4')
            fixed = vendor_config.apply(broken, 'R1', 'ip route 198.51.100.0 255.255.255.0 203.0.113.2')
            results = {}
            state_root = patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state')
            with state_root, patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                for label, spec in (('broken', broken), ('fixed', fixed)):
                    manager = Manager(spec['name'])
                    with manager.locked():
                        try:
                            manager.start(spec)
                            for node in spec['nodes']:  # every guest agent answers before the mission's pings
                                socket, deadline = manager.directory / node['name'] / 'guest.vsock', time.monotonic() + 40
                                while True:
                                    try:
                                        query(socket, 'ready')
                                        break
                                    except (ValueError, OSError):
                                        if time.monotonic() >= deadline:
                                            raise
                                        time.sleep(.1)
                            real = {}
                            for _ in range(3):  # guests finish booting while the first probes run
                                found = missions.run_real(manager, 'route-manquante')['results']
                                real = {index: (ok, detail) for index, ok, detail in found}
                                if label == 'broken' or all(ok for ok, _ in real.values()):
                                    break
                            results[label] = missions.grade(spec, 'route-manquante', real)
                        finally:
                            manager.stop()
            (evidence / 'result.json').write_text(json.dumps(results, indent=2))
            print('\nMission grades:', json.dumps({k: (v['passed'], v['total']) for k, v in results.items()}), flush=True)
            self.assertFalse(any(r['status'] == 'ok' for r in results['broken']['results'] if r['kind'] == 'réel'), results['broken'])
            self.assertTrue(results['fixed']['solved'], results['fixed'])
