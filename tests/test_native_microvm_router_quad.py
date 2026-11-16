"""Real four-port router guest: every port eth0..eth3 carries its own segment, fails alone and survives restore."""
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
from network_labs.appliances.microvm import quad_router_example
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, process_identity

NETS = ['192.0.2', '198.51.100', '203.0.113', '100.64.0']


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class QuadRouterGuestTests(unittest.TestCase):
    def test_four_ports_route_fail_independently_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'router-quad'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlrq-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = quad_router_example(kernel, root / 'base.ext4')
            endpoints = [f'VM{i + 1}' for i in range(4)]
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

                        def wait_ready():
                            for name in endpoints:
                                deadline = time.monotonic() + 40
                                while True:
                                    try: query(sockets[name], 'ready'); break
                                    except (ValueError, OSError):
                                        if time.monotonic() >= deadline: raise
                                        time.sleep(.1)

                        def full_mesh(attempts):
                            for i, source in enumerate(endpoints):
                                for j, net in enumerate(NETS):
                                    if i != j: probe(source, f'{net}.10', True, attempts=attempts)

                        wait_ready()
                        self.assertEqual(query(sockets['R1'], 'forwarding').strip(), '1')
                        addresses = query(sockets['R1'], 'addresses'); results['router_addresses'] = addresses
                        for i, net in enumerate(NETS): self.assertRegex(addresses, rf'eth{i}[\s\S]*inet {net}\.1/24')
                        # Each pair of segments, both directions: twelve routed paths across the four ports.
                        full_mesh(attempts=3)
                        # Each port fails alone: only paths through it break.
                        for k, net in enumerate(NETS):
                            query(sockets['R1'], 'link', interface=f'eth{k}', state='down')
                            other = (k + 1) % 4; third = (k + 2) % 4
                            probe(endpoints[other], f'{net}.10', False)
                            probe(endpoints[other], f'{NETS[third]}.10', True, attempts=3)
                            query(sockets['R1'], 'link', interface=f'eth{k}', state='up')
                            probe(endpoints[other], f'{net}.10', True, attempts=5)
                        results['saved'] = save_observed(manager)
                        restored = load_startup(manager.name)
                        self.assertEqual(sorted(restored['nodes'][0]['interfaces']), ['eth0', 'eth1', 'eth2', 'eth3'])
                        for name in sockets: shutil.copyfile(manager.directory / name / 'console.log', evidence / (name + '-before-restart.log'))
                        manager.stop()
                        for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                        manager = Manager(spec['name']); manager.start(restored); records.extend(manager.state['vms'])
                        wait_ready()
                        results['restored_profiles'] = {n['name']: observe(sockets[n['name']], n) for n in restored['nodes']}
                        full_mesh(attempts=3)
                        results['cold_restore_passed'] = True
                        (evidence / 'result.json').write_text(json.dumps(results, indent=2))
                    finally:
                        for name in ('R1', *endpoints):
                            console = manager.directory / name / 'console.log'
                            if console.exists(): shutil.copyfile(console, evidence / (name + '.log'))
                        manager.state = None
                        if manager.directory.exists(): manager.stop()
                for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                self.assertFalse(manager.directory.exists())
