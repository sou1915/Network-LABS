"""Real DHCP between guests: a router guest leases an address to a host guest, which then reaches a static host through it."""
import ipaddress
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
from network_labs.appliances.guest_startup import leases, observe, query, save_observed
from network_labs.appliances.microvm import dhcp_example
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, process_identity

POOL = [ipaddress.IPv4Address('192.0.2.100') + i for i in range(21)]


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class DhcpGuestTests(unittest.TestCase):
    def test_lease_route_reachability_save_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'dhcp'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nldh-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = dhcp_example(kernel, root / 'base.ext4')
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name']); records = []; results = {'probes': [], 'leases': []}
                with manager.locked():
                    try:
                        manager.start(spec); records.extend(manager.state['vms'])
                        sockets = {n['name']: manager.directory / n['name'] / 'guest.vsock' for n in spec['nodes']}

                        def probe(name, destination, expected, attempts=1):
                            for _ in range(attempts):
                                result = request(sockets[name], 'ping', destination=destination)
                                if (result['exit_code'] == 0) == expected: break
                            results['probes'].append({'source': name, 'destination': destination, 'expected': expected, **result})
                            self.assertEqual(result['exit_code'] == 0, expected, result)

                        def leased():
                            """Wait for VM2's lease, then return its address as the guest kernel holds it."""
                            for name in ('VM2', 'VM3'):
                                deadline = time.monotonic() + 40
                                while True:
                                    try: query(sockets[name], 'ready'); break
                                    except (ValueError, OSError):
                                        if time.monotonic() >= deadline: raise
                                        time.sleep(.1)
                            deadline = time.monotonic() + 30
                            while True:
                                text = query(sockets['VM2'], 'addresses')
                                found = [ipaddress.IPv4Interface(w) for line in text.splitlines() for w in line.split()[1:2] if line.split()[:1] == ['inet'] and not w.startswith('127.')]
                                if found: break
                                if time.monotonic() >= deadline: self.fail('VM2 got no DHCP lease: ' + text)
                                time.sleep(.5)
                            self.assertEqual(len(found), 1, text); self.assertIn(found[0].ip, POOL); self.assertEqual(found[0].network.prefixlen, 24)
                            self.assertIn('default via 192.0.2.1 dev eth0', query(sockets['VM2'], 'routes'))
                            table = leases(sockets['R1'], 'eth0'); results['leases'].append(table)
                            self.assertEqual([row['address'] for row in table], [str(found[0].ip)], table)
                            return str(found[0].ip)

                        address = leased(); results['address'] = address
                        # The leased host reaches its gateway and, through R1's forwarding, the static host behind it.
                        probe('VM2', '192.0.2.1', True, attempts=3)
                        probe('VM2', '198.51.100.20', True, attempts=3); probe('VM3', address, True, attempts=3)
                        # Nothing dynamic is saved: VM2 keeps no address or route of its own in the startup file.
                        results['saved'] = save_observed(manager)
                        restored = load_startup(manager.name)
                        self.assertEqual(restored['nodes'][1]['guest_network'], {'addresses': [], 'routes': []})
                        self.assertEqual(restored['nodes'][1]['interfaces'], {'eth0': ''})
                        for name in sockets: shutil.copyfile(manager.directory / name / 'console.log', evidence / (name + '-before-restart.log'))
                        manager.stop()
                        for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                        manager = Manager(spec['name']); manager.start(restored); records.extend(manager.state['vms'])
                        results['restored_address'] = leased()
                        results['restored_profiles'] = {n['name']: observe(sockets[n['name']], n) for n in restored['nodes']}
                        probe('VM2', '198.51.100.20', True, attempts=3)
                        results['cold_restore_passed'] = True
                        (evidence / 'result.json').write_text(json.dumps(results, indent=2))
                    finally:
                        for name in ('R1', 'VM2', 'VM3'):
                            console = manager.directory / name / 'console.log'
                            if console.exists(): shutil.copyfile(console, evidence / (name + '.log'))
                        manager.state = None
                        if manager.directory.exists(): manager.stop()
                for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                self.assertFalse(manager.directory.exists())
