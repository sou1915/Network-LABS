"""Real firewall guest with address translation: the inside leaves masqueraded, VM2 is published, NAT changes live and survives restore."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from network_labs.appliances import guest_firewall
from network_labs.appliances.capture import capture
from network_labs.appliances.guest_image import build
from network_labs.appliances.guest_control import request
from network_labs.appliances.guest_startup import save_observed, query
from network_labs.appliances.microvm import firewall_nat_example
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, process_identity


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class FirewallNatGuestTests(unittest.TestCase):
    def test_masquerade_publish_live_change_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'firewall-nat'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlnat-') as temporary, ThreadPoolExecutor(max_workers=1) as pool:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True, with_firewall=True)
            spec = firewall_nat_example(kernel, root / 'base.ext4')
            policy = spec['nodes'][0]['firewall']
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name']); records = []; results = {'probes': [], 'captures': {}}
                with manager.locked():
                    manager.start(spec); records.extend(manager.state['vms'])
                sockets = {n['name']: manager.directory / n['name'] / 'guest.vsock' for n in spec['nodes']}
                try:
                    def probe(name, destination, expected, attempts=1):
                        for _ in range(attempts):
                            result = request(sockets[name], 'ping', destination=destination)
                            if (result['exit_code'] == 0) == expected: break
                        results['probes'].append({'source': name, 'destination': destination, 'expected': expected, **result})
                        self.assertEqual(result['exit_code'] == 0, expected, result)

                    def seen(label, node, port, expression, source, destination):
                        """Ping once while recording on the host side of one guest port: the frame shows the translated addresses."""
                        probe(source, destination, True, attempts=3)  # Neighbours resolved first: the capture then sees the request itself.
                        ready = threading.Event(); path = root / (label + '.pcap')
                        future = pool.submit(capture, Manager(spec['name']), node, port, path, seconds=8, packets=1, expression=expression, ready=ready.set)
                        self.assertTrue(ready.wait(8), 'Capture did not become ready')
                        probe(source, destination, True)
                        report = future.result(timeout=15); results['captures'][label] = report
                        shutil.copyfile(path, evidence / (label + '.pcap'))
                        return report['captured_packets']

                    for name in ('VM2', 'VM3'):
                        deadline = time.monotonic() + 40
                        while True:
                            try: query(sockets[name], 'ready'); break
                            except (ValueError, OSError):
                                if time.monotonic() >= deadline: raise
                                time.sleep(.1)
                    results['nat_listing'] = query(sockets['FW1'], 'firewall-nat-list')
                    self.assertEqual(guest_firewall.observe_nat(sockets['FW1']), guest_firewall.expected_nat(policy))
                    # Masquerade: VM3 receives VM2's ping from the firewall's outside address, never from 192.0.2.20.
                    self.assertEqual(seen('masqueraded', 'VM3', 'eth0', 'icmp[icmptype] = icmp-echo and src host 198.51.100.1', 'VM2', '198.51.100.20'), 1)
                    # Destination NAT: VM3 pings the firewall's outside address and VM2 answers it, from VM3's own address.
                    self.assertEqual(seen('published', 'VM2', 'eth0', 'icmp[icmptype] = icmp-echo and src host 198.51.100.20', 'VM3', '198.51.100.1'), 1)
                    # Live change without masquerade: VM3 now sees VM2's real address.
                    plain = copy.deepcopy(policy); plain['nat'] = [entry for entry in plain['nat'] if entry['type'] == 'dnat']
                    with manager.locked():
                        manager.state = None; results['live_change'] = manager.configure_firewall('FW1', plain)
                    self.assertEqual(guest_firewall.observe_nat(sockets['FW1']), guest_firewall.expected_nat(plain))
                    self.assertEqual(seen('unmasqueraded', 'VM3', 'eth0', 'icmp[icmptype] = icmp-echo and src host 192.0.2.20', 'VM2', '198.51.100.20'), 1)
                    with manager.locked():
                        manager.state = None; manager.configure_firewall('FW1', policy)
                        results['saved'] = save_observed(manager)
                        restored = load_startup(manager.name)
                        self.assertEqual(restored['nodes'][0]['firewall']['nat'], policy['nat'])
                        manager.stop()
                    for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                    with manager.locked():
                        manager = Manager(spec['name']); manager.start(restored); records.extend(manager.state['vms'])
                    for name in ('VM2', 'VM3'):
                        deadline = time.monotonic() + 40
                        while True:
                            try: query(sockets[name], 'ready'); break
                            except (ValueError, OSError):
                                if time.monotonic() >= deadline: raise
                                time.sleep(.1)
                    self.assertEqual(guest_firewall.observe_nat(sockets['FW1']), guest_firewall.expected_nat(policy))
                    self.assertEqual(seen('restored-masqueraded', 'VM3', 'eth0', 'icmp[icmptype] = icmp-echo and src host 198.51.100.1', 'VM2', '198.51.100.20'), 1)
                    results['cold_restore_passed'] = True
                    (evidence / 'result.json').write_text(json.dumps(results, indent=2))
                finally:
                    for name in ('FW1', 'VM2', 'VM3'):
                        console = manager.directory / name / 'console.log'
                        if console.exists(): shutil.copyfile(console, evidence / (name + '.log'))
                    with manager.locked():
                        manager.state = None
                        if manager.directory.exists(): manager.stop()
                for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                self.assertFalse(manager.directory.exists())
