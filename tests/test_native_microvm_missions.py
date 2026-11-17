"""Real guests grade a mission: the broken route lab fails its pings, the IOS fix makes them pass."""
import copy
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


def wait_ready(manager, spec):
    """Every guest agent answers before the mission's pings."""
    for node in spec['nodes']:
        socket, deadline = manager.directory / node['name'] / 'guest.vsock', time.monotonic() + 40
        while True:
            try:
                query(socket, 'ready')
                break
            except (ValueError, OSError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.1)
    return True


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
                            wait_ready(manager, spec)
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

    def test_firewall_health_probes_hold_on_the_working_lab_and_catch_a_fault(self):
        """The panne lab's probes are what the working lab really does; an inbound DENY fault fails the publication probe."""
        from network_labs.appliances import faults
        self.assertEqual(os.geteuid(), 0)
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        with tempfile.TemporaryDirectory(prefix='nlpf-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            working = faults.LABS['pare-feu']['build'](kernel, root / 'base.ext4')
            broken = copy.deepcopy(working)
            faults.FAULTS['pare-feu']['inbound-deny'][0][0](broken)
            grades = {}
            state_root = patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state')
            with state_root, patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                for label, spec in (('working', working), ('broken', broken)):
                    manager = Manager(spec['name'])
                    with manager.locked():
                        try:
                            manager.start(spec)
                            wait_ready(manager, spec)
                            for _ in range(3):
                                found = {i: (ok, d) for i, ok, d in missions.run_real(manager, 'panne-pare-feu')['results']}
                                if label == 'broken' or all(ok for ok, _ in found.values()):
                                    break
                            grades[label] = [ok for _, (ok, _) in sorted(found.items())]
                        finally:
                            manager.stop()
            print('\nPanne pare-feu probes:', json.dumps(grades), flush=True)
            self.assertEqual(grades['working'], [True, True])
            self.assertEqual(grades['broken'], [True, False])

    def test_dhcp_mission_solved_on_real_guests(self):
        """The DHCP mission fixed with IOS commands: VM2 takes a lease from R1 and reaches VM3."""
        self.assertEqual(os.geteuid(), 0)
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        with tempfile.TemporaryDirectory(prefix='nlmd-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            lab = missions.mission('serveur-dhcp')['build'](kernel, root / 'base.ext4')
            fixed = vendor_config.apply(lab, 'R1', 'ip dhcp excluded-address 192.0.2.1 192.0.2.99\nip dhcp pool LAN\n'
                                                   ' network 192.0.2.0 255.255.255.0\n default-router 192.0.2.1\n lease 0 0 10')
            state_root = patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state')
            with state_root, patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(fixed['name'])
                with manager.locked():
                    try:
                        manager.start(fixed)
                        wait_ready(manager, fixed)
                        for _ in range(10):  # the lease and its default route arrive a few seconds after boot
                            found = {i: (ok, d) for i, ok, d in missions.run_real(manager, 'serveur-dhcp')['results']}
                            if all(ok for ok, _ in found.values()):
                                break
                            time.sleep(2)
                        grade = missions.grade(fixed, 'serveur-dhcp', found)
                    finally:
                        manager.stop()
            print('\nDHCP mission grade:', grade['passed'], '/', grade['total'], flush=True)
            self.assertTrue(grade['solved'], grade)

