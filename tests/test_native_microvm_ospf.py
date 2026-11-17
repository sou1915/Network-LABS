"""Real OSPF between three router guests (BIRD in each guest): the mission fails, then the IOS fix converges and VM2 reaches VM3."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances import missions, vendor_config, vendor_show
from network_labs.appliances.guest_image import build
from network_labs.appliances.guest_startup import save_observed
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager

from tests.test_native_microvm_missions import wait_ready

MISSION = 'ospf-multi-constructeurs'
SOLUTION = 'router ospf 1\n network 192.0.2.0 0.0.0.255 area 0\n network 203.0.113.0 0.0.0.3 area 0\n passive-interface gi0/0/0'


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class OspfGuestTests(unittest.TestCase):
    def test_three_vendor_ospf_mission_on_real_guests(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'ospf'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlospf-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True, with_routing=True)
            broken = missions.mission(MISSION)['build'](kernel, root / 'base.ext4')
            fixed = vendor_config.apply(broken, 'R1', SOLUTION)
            results, shows = {}, {}
            state_root = patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state')
            with state_root, patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                for label, spec in (('broken', broken), ('fixed', fixed)):
                    manager = Manager(spec['name'])
                    with manager.locked():
                        try:
                            manager.start(spec)
                            wait_ready(manager, spec)
                            deadline = time.monotonic() + (8 if label == 'broken' else 40)
                            while True:  # OSPF converges a few seconds after the routers boot (hello 1 s, dead 4 s)
                                real = {i: (ok, d) for i, ok, d in missions.run_real(manager, MISSION)['results']}
                                if all(ok for ok, _ in real.values()) or time.monotonic() >= deadline:
                                    break
                                time.sleep(1)
                            results[label] = missions.grade(spec, MISSION, real)
                            if label == 'fixed':
                                for name, command in (('R1', 'show ip ospf neighbor'), ('R1', 'show ip route'),
                                                      ('R2', 'show ospf neighbor'), ('R2', 'show route'),
                                                      ('R3', 'display ospf peer brief'), ('R3', 'display ip routing-table')):
                                    node = next(n for n in spec['nodes'] if n['name'] == name)
                                    manager.state = None
                                    shows[f'{name}> {command}'] = vendor_show.show(node, manager.observe_node(name), command)
                                manager.state = None
                                save_observed(manager)
                                restored = load_startup(spec['name'])
                                # OSPF's routes are learned again on every boot: none is saved as a static route.
                                saved = [n.get('guest_network', {}).get('routes', []) for n in restored['nodes'][:3]]
                                self.assertEqual(saved, [[], [], []])
                                self.assertEqual(restored['nodes'][0]['ospf'], spec['nodes'][0]['ospf'])
                        finally:
                            if manager.directory.exists():
                                manager.stop()
            (evidence / 'result.json').write_text(json.dumps({'grades': results, 'shows': shows}, indent=2))
            for title, text in shows.items():
                print(f'\n{title}\n{text}', flush=True)
            print('\nOSPF mission grades:', json.dumps({k: (v['passed'], v['total']) for k, v in results.items()}), flush=True)
            self.assertFalse(any(r['status'] == 'ok' for r in results['broken']['results'] if r['kind'] == 'réel'), results['broken'])
            self.assertTrue(results['fixed']['solved'], results['fixed'])
            self.assertIn('FULL', shows['R1> show ip ospf neighbor'])
            self.assertIn('O        198.51.100.0/24', shows['R1> show ip route'])
