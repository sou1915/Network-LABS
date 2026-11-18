"""Real eBGP between three router guests in three ASes (FRR in each guest): the mission fails, the IOS fix reaches the
running R1 live, the session comes up and VM2 reaches VM3 across the three ASes."""
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
from network_labs.appliances.runtime import Manager

from tests.test_native_microvm_missions import wait_ready

MISSION = 'bgp-trois-operateurs'
FIX = 'router bgp 65001\n neighbor 203.0.113.2 remote-as 65002\n network 192.0.2.0 mask 255.255.255.0'


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class BgpGuestTests(unittest.TestCase):
    def test_three_as_bgp_mission_fixed_live_on_real_guests(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'bgp'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlbgp-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', size_mib=128, with_agent=True, with_routing=True)
            broken = missions.mission(MISSION)['build'](kernel, root / 'base.ext4')
            fixed = vendor_config.apply(broken, 'R1', FIX)
            grades, shows = {}, {}
            state_root = patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state')
            with state_root, patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(broken['name'])
                with manager.locked():
                    try:
                        manager.start(broken)
                        wait_ready(manager, broken)
                        for label, spec in (('broken', broken), ('live', fixed)):
                            if label == 'live':
                                manager.state = None
                                manager.configure_routing('R1', next(n for n in fixed['nodes'] if n['name'] == 'R1'))
                            deadline = time.monotonic() + (10 if label == 'broken' else 60)
                            while True:  # BGP: session, then updates (timers 3/9, connect retry 5 s)
                                found = {i: (ok, d) for i, ok, d in missions.run_real(manager, MISSION)['results']}
                                if all(ok for ok, _ in found.values()) or time.monotonic() >= deadline:
                                    break
                                time.sleep(2)
                            grades[label] = missions.grade(spec, MISSION, found)
                        for name, command in (('R1', 'show ip bgp summary'), ('R1', 'show ip bgp'), ('R1', 'show ip route'),
                                              ('R2', 'show bgp summary'), ('R2', 'show route'),
                                              ('R3', 'display bgp peer'), ('R3', 'display bgp routing-table')):
                            node = next(n for n in fixed['nodes'] if n['name'] == name)
                            manager.state = None
                            shows[f'{name}> {command}'] = vendor_show.show(node, manager.observe_node(name), command)
                    finally:
                        if manager.directory.exists():
                            manager.stop()
            (evidence / 'result.json').write_text(json.dumps({'grades': grades, 'shows': shows}, indent=2, ensure_ascii=False))
            for title, text in shows.items():
                print(f'\n{title}\n{text}', flush=True)
            print('\nBGP mission grades:', json.dumps({k: (v['passed'], v['total']) for k, v in grades.items()}), flush=True)
            self.assertFalse(any(r['status'] == 'ok' for r in grades['broken']['results'] if r['kind'] == 'réel'), grades['broken'])
            self.assertTrue(grades['live']['solved'], grades['live'])
            self.assertIn('Established', shows['R3> display bgp peer'])
            self.assertIn('B        198.51.100.0/24', shows['R1> show ip route'])
