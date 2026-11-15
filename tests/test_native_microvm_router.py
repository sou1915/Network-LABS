"""Real router guest: two endpoint guests reach each other only through its forwarding."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
from network_labs.appliances.guest_image import build
from network_labs.appliances.guest_control import request
from network_labs.appliances.guest_startup import save_observed, observe, query
from network_labs.appliances.microvm import router_example
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, process_identity


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class RouterGuestTests(unittest.TestCase):
    def test_forwarding_between_segments_loss_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'router'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlrt-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = router_example(kernel, root / 'base.ext4')
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name']); records = []; results = {'probes': []}
                with manager.locked():
                    try:
                        manager.start(spec); records.extend(manager.state['vms'])
                        sockets = {n['name']: manager.directory / n['name'] / 'guest.vsock' for n in spec['nodes']}

                        def probe(name, destination, expected, attempts=1):
                            # The first packet across a fresh path can be spent on ARP; retries are only allowed where stated.
                            for _ in range(attempts):
                                result = request(sockets[name], 'ping', destination=destination)
                                if (result['exit_code'] == 0) == expected: break
                            results['probes'].append({'source': name, 'destination': destination, 'expected': expected, **result})
                            self.assertEqual(result['exit_code'] == 0, expected, result)
                            return result

                        def wait_ready():
                            for name in ('VM2', 'VM3'):
                                deadline = time.monotonic() + 40
                                while True:
                                    try: query(sockets[name], 'ready'); break
                                    except (ValueError, OSError):
                                        if time.monotonic() >= deadline: raise
                                        time.sleep(.1)

                        wait_ready()
                        self.assertEqual(query(sockets['R1'], 'forwarding').strip(), '1')
                        self.assertEqual(query(sockets['VM2'], 'forwarding').strip(), '0')
                        results['router_routes'] = query(sockets['R1'], 'routes')
                        results['endpoint_routes'] = query(sockets['VM2'], 'routes')
                        self.assertIn('default via 192.0.2.1', results['endpoint_routes'])
                        # Each endpoint first reaches its own gateway, then the far segment through the router.
                        probe('VM2', '192.0.2.1', True, attempts=3); probe('VM3', '198.51.100.1', True, attempts=3)
                        forward = probe('VM2', '198.51.100.20', True, attempts=3); probe('VM3', '192.0.2.20', True, attempts=3)
                        direct = probe('VM2', '192.0.2.1', True)
                        # One routed hop costs exactly one TTL relative to the directly connected gateway.
                        ttl = lambda result: int(result['output'].split('ttl=')[1].split()[0])
                        self.assertEqual(ttl(forward), ttl(direct) - 1, (forward, direct)); results['ttl'] = {'direct': ttl(direct), 'routed': ttl(forward)}
                        # Negative control: the same lab without forwarding does not pass traffic, gateways stay reachable.
                        query(sockets['R1'], 'forward', state='off')
                        probe('VM2', '198.51.100.20', False); probe('VM3', '192.0.2.20', False)
                        probe('VM2', '192.0.2.1', True); probe('VM3', '198.51.100.1', True)
                        with self.assertRaisesRegex(ValueError, 'not forwarding'): save_observed(manager)
                        query(sockets['R1'], 'forward', state='on')
                        probe('VM2', '198.51.100.20', True, attempts=3)
                        # Losing the far-side port breaks only the routed path.
                        query(sockets['R1'], 'link', interface='eth1', state='down')
                        probe('VM2', '198.51.100.20', False); probe('VM2', '192.0.2.1', True)
                        query(sockets['R1'], 'link', interface='eth1', state='up')
                        probe('VM2', '198.51.100.20', True, attempts=5)
                        results['saved'] = save_observed(manager)
                        restored = load_startup(manager.name)
                        self.assertEqual(restored['nodes'][0]['role'], 'router')
                        for name in sockets: shutil.copyfile(manager.directory / name / 'console.log', evidence / (name + '-before-restart.log'))
                        manager.stop()
                        for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                        manager = Manager(spec['name']); manager.start(restored); records.extend(manager.state['vms'])
                        wait_ready()
                        results['restored_profiles'] = {n['name']: observe(sockets[n['name']], n) for n in restored['nodes']}
                        self.assertEqual(query(sockets['R1'], 'forwarding').strip(), '1')
                        probe('VM2', '198.51.100.20', True, attempts=3); probe('VM3', '192.0.2.20', True, attempts=3)
                        results['cold_restore_passed'] = True
                        (evidence / 'result.json').write_text(json.dumps(results, indent=2))
                    finally:
                        for name in ('R1', 'VM2', 'VM3'):
                            console = manager.directory / name / 'console.log'
                            if console.exists(): shutil.copyfile(console, evidence / (name + '.log'))
                        if manager.directory.exists(): manager.stop()
                for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                self.assertFalse(manager.directory.exists())
                (evidence / 'cleanup.txt').write_text('All owned VMMs and private lab resources removed.\n')
