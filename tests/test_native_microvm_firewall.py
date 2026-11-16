"""Real firewall guest: inside may ping out, outside may not start inward, drift is refused, policy survives restart."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
from network_labs.appliances import guest_firewall
from network_labs.appliances.guest_image import build
from network_labs.appliances.guest_control import request
from network_labs.appliances.guest_startup import save_observed, observe, query
from network_labs.appliances.microvm import firewall_example
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, process_identity


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class FirewallGuestTests(unittest.TestCase):
    def test_stateful_policy_direction_drift_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'firewall'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlfw-') as temporary:
            root = Path(temporary)
            report = build(shutil.which('busybox'), root / 'base.ext4', with_agent=True, with_firewall=True)
            self.assertTrue(report['guest_firewall_installed'])
            spec = firewall_example(kernel, root / 'base.ext4')
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name']); records = []; results = {'probes': []}
                with manager.locked():
                    try:
                        manager.start(spec); records.extend(manager.state['vms'])
                        sockets = {n['name']: manager.directory / n['name'] / 'guest.vsock' for n in spec['nodes']}
                        firewall = spec['nodes'][0]

                        def probe(name, destination, expected, attempts=1):
                            for _ in range(attempts):
                                result = request(sockets[name], 'ping', destination=destination)
                                if (result['exit_code'] == 0) == expected: break
                            results['probes'].append({'source': name, 'destination': destination, 'expected': expected, **result})
                            self.assertEqual(result['exit_code'] == 0, expected, result)

                        def wait_ready():
                            for name in ('VM2', 'VM3'):
                                deadline = time.monotonic() + 40
                                while True:
                                    try: query(sockets[name], 'ready'); break
                                    except (ValueError, OSError):
                                        if time.monotonic() >= deadline: raise
                                        time.sleep(.1)

                        wait_ready()
                        results['listing'] = query(sockets['FW1'], 'firewall-list')
                        self.assertEqual(guest_firewall.observe(sockets['FW1']), guest_firewall.expected(firewall['firewall']))
                        self.assertEqual(query(sockets['FW1'], 'forwarding').strip(), '1')
                        # Both sides reach the firewall itself; only the inside may open a flow through it.
                        probe('VM2', '192.0.2.1', True, attempts=3); probe('VM3', '198.51.100.1', True, attempts=3)
                        probe('VM2', '198.51.100.20', True, attempts=3)
                        probe('VM3', '192.0.2.20', False)
                        # The inside ping just made is tracked in the guest kernel and shown by sessions.
                        manager.state = None; results['sessions'] = manager.sessions('FW1')
                        self.assertIn('src=192.0.2.20 dst=198.51.100.20', results['sessions']['output'], results['sessions'])
                        # Replies to the inside flow passed only because of connection tracking: without it they are dropped.
                        stateless = dict(firewall, firewall=dict(firewall['firewall'], stateful=False))
                        guest_firewall.apply(sockets['FW1'], stateless)
                        probe('VM2', '198.51.100.20', False)
                        with self.assertRaisesRegex(ValueError, 'differ'): save_observed(manager)
                        # An open policy passes both directions and is likewise refused by save as drift.
                        opened = dict(firewall, firewall={'default': 'accept', 'stateful': True, 'rules': [], 'nat': []})
                        guest_firewall.apply(sockets['FW1'], opened)
                        probe('VM3', '192.0.2.20', True, attempts=3)
                        with self.assertRaisesRegex(ValueError, 'differ'): save_observed(manager)
                        guest_firewall.apply(sockets['FW1'], firewall)
                        probe('VM2', '198.51.100.20', True, attempts=3); probe('VM3', '192.0.2.20', False)
                        # A live policy change through the manager: recorded in lab state, so save sees no drift.
                        inward = copy.deepcopy(firewall['firewall'])
                        inward['rules'].append({'name': 'outside-ping-in', 'in': 'eth1', 'out': 'eth0', 'protocol': 'icmp', 'action': 'accept'})
                        manager.state = None; results['live_change'] = manager.configure_firewall('FW1', inward)
                        self.assertEqual(guest_firewall.observe(sockets['FW1']), guest_firewall.expected(inward))
                        probe('VM3', '192.0.2.20', True, attempts=3)
                        results['saved_after_live_change'] = save_observed(manager)  # Raises on any difference from the recorded policy.
                        manager.state = None; manager.configure_firewall('FW1', firewall['firewall'])
                        probe('VM3', '192.0.2.20', False); probe('VM2', '198.51.100.20', True, attempts=3)
                        results['saved'] = save_observed(manager)
                        restored = load_startup(manager.name)
                        self.assertEqual(restored['nodes'][0]['firewall'], firewall['firewall'])
                        for name in sockets: shutil.copyfile(manager.directory / name / 'console.log', evidence / (name + '-before-restart.log'))
                        manager.stop()
                        for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                        manager = Manager(spec['name']); manager.start(restored); records.extend(manager.state['vms'])
                        wait_ready()
                        results['restored_profiles'] = {n['name']: observe(sockets[n['name']], n) for n in restored['nodes']}
                        probe('VM2', '198.51.100.20', True, attempts=3); probe('VM3', '192.0.2.20', False)
                        results['cold_restore_passed'] = True
                        (evidence / 'result.json').write_text(json.dumps(results, indent=2))
                    finally:
                        for name in ('FW1', 'VM2', 'VM3'):
                            console = manager.directory / name / 'console.log'
                            if console.exists(): shutil.copyfile(console, evidence / (name + '.log'))
                        if manager.directory.exists(): manager.stop()
                for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                self.assertFalse(manager.directory.exists())
                (evidence / 'cleanup.txt').write_text('All owned VMMs and private lab resources removed.\n')
