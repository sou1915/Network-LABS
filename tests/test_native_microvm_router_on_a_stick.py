"""Real inter-VLAN routing: a router guest routes VLAN 10 to VLAN 20 over one trunk with two 802.1Q subinterfaces."""
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
from network_labs.appliances.guest_startup import observe, query, save_observed
from network_labs.appliances.microvm import router_on_a_stick_example
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, process_identity


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1' and os.environ.get('NETWORK_LABS_GUEST_VLAN') == '1',
                     'Opt-in real KVM test on a guest kernel with 802.1Q and bridge VLAN filtering')
class RouterOnAStickGuestTests(unittest.TestCase):
    def test_inter_vlan_routing_trunk_pruning_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'router-on-a-stick'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlrs-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = router_on_a_stick_example(kernel, root / 'base.ext4')
            state = patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state')
            config = patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config')
            with state, config:
                manager = Manager(spec['name'])
                records = []
                results = {'probes': []}
                with manager.locked():
                    try:
                        manager.start(spec)
                        records.extend(manager.state['vms'])
                        sockets = {n['name']: manager.directory / n['name'] / 'guest.vsock' for n in spec['nodes']}

                        def probe(name, destination, expected, attempts=1):
                            for _ in range(attempts):
                                result = request(sockets[name], 'ping', destination=destination)
                                if (result['exit_code'] == 0) == expected:
                                    break
                            results['probes'].append({'source': name, 'destination': destination, 'expected': expected, **result})
                            self.assertEqual(result['exit_code'] == 0, expected, result)
                            return result

                        def wait_ready():
                            for name in ('VM1', 'VM2'):
                                deadline = time.monotonic() + 40
                                while True:
                                    try:
                                        query(sockets[name], 'ready')
                                        break
                                    except (ValueError, OSError):
                                        if time.monotonic() >= deadline:
                                            raise
                                        time.sleep(.1)

                        def ttl(result):
                            return int(result['output'].split('ttl=')[1].split()[0])

                        wait_ready()
                        results['router_addresses'] = query(sockets['R1'], 'addresses')
                        self.assertIn('eth0.10@eth0', results['router_addresses'])
                        self.assertIn('inet 198.51.100.1/24', results['router_addresses'])
                        self.assertEqual(query(sockets['R1'], 'forwarding').strip(), '1')
                        # Each host reaches its own gateway subinterface, then the other VLAN one routed hop away.
                        direct = probe('VM1', '192.0.2.1', True, attempts=3)
                        probe('VM2', '198.51.100.1', True, attempts=3)
                        routed = probe('VM1', '198.51.100.10', True, attempts=3)
                        probe('VM2', '192.0.2.10', True, attempts=3)
                        self.assertEqual(ttl(routed), ttl(direct) - 1, (routed, direct))
                        # Pruning VLAN 20 from the switch trunk cuts only VLAN 20 from the router.
                        query(sockets['SW1'], 'bridge-vlan-delete', interface='eth2', vlan=20)
                        probe('VM1', '198.51.100.10', False)
                        probe('VM1', '192.0.2.1', True)
                        query(sockets['SW1'], 'bridge-vlan-add', interface='eth2', vlan=20, state='tagged')
                        probe('VM1', '198.51.100.10', True, attempts=5)
                        results['saved'] = save_observed(manager)
                        restored = load_startup(manager.name)
                        self.assertEqual(restored['nodes'][1]['subinterfaces'], spec['nodes'][1]['subinterfaces'])
                        manager.stop()
                        for record in records:
                            self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                        manager = Manager(spec['name'])
                        manager.start(restored)
                        records.extend(manager.state['vms'])
                        wait_ready()
                        results['restored_profiles'] = {n['name']: observe(sockets[n['name']], n) for n in restored['nodes'][1:]}
                        probe('VM1', '198.51.100.10', True, attempts=3)
                        results['cold_restore_passed'] = True
                        (evidence / 'result.json').write_text(json.dumps(results, indent=2))
                    finally:
                        for name in ('SW1', 'R1', 'VM1', 'VM2'):
                            console = manager.directory / name / 'console.log'
                            if console.exists():
                                shutil.copyfile(console, evidence / (name + '.log'))
                        manager.state = None
                        if manager.directory.exists():
                            manager.stop()
                for record in records:
                    self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                self.assertFalse(manager.directory.exists())
