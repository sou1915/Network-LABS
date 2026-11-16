"""Real switch guest: three endpoint guests share one segment only through its in-guest bridge."""
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
from network_labs.appliances.guest_startup import check_switch, save_observed, query
from network_labs.appliances.microvm import switch_example
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, process_identity


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class SwitchGuestTests(unittest.TestCase):
    def test_bridging_port_loss_no_addressing_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'switch'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlsw-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = switch_example(kernel, root / 'base.ext4')
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
                            for name in ('VM1', 'VM2', 'VM3'):
                                deadline = time.monotonic() + 40
                                while True:
                                    try: query(sockets[name], 'ready'); break
                                    except (ValueError, OSError):
                                        if time.monotonic() >= deadline: raise
                                        time.sleep(.1)

                        wait_ready()
                        # Startup already verified the bridge; read it again here as recorded evidence.
                        check_switch(sockets['SW1'], spec['nodes'][0])
                        results['bridge_ports'] = query(sockets['SW1'], 'bridge-ports')
                        results['switch_addresses'] = query(sockets['SW1'], 'addresses')
                        self.assertEqual(query(sockets['SW1'], 'forwarding').strip(), '0')
                        probe('VM1', '192.0.2.12', True, attempts=3); probe('VM1', '192.0.2.13', True, attempts=3)
                        probe('VM2', '192.0.2.13', True, attempts=3)
                        # The host fabric joins each guest port to one VMM tap only: frames between endpoints cross the guest.
                        query(sockets['SW1'], 'link', interface='eth2', state='down')
                        probe('VM1', '192.0.2.13', False); probe('VM1', '192.0.2.12', True)
                        query(sockets['SW1'], 'link', interface='eth2', state='up')
                        probe('VM1', '192.0.2.13', True, attempts=5)
                        results['saved'] = save_observed(manager)
                        restored = load_startup(manager.name)
                        self.assertNotIn('guest_network', restored['nodes'][0])
                        for name in sockets: shutil.copyfile(manager.directory / name / 'console.log', evidence / (name + '-before-restart.log'))
                        manager.stop()
                        for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                        manager = Manager(spec['name']); manager.start(restored); records.extend(manager.state['vms'])
                        wait_ready()
                        check_switch(sockets['SW1'], restored['nodes'][0])
                        probe('VM1', '192.0.2.13', True, attempts=3); probe('VM3', '192.0.2.12', True, attempts=3)
                        results['cold_restore_passed'] = True
                        (evidence / 'result.json').write_text(json.dumps(results, indent=2))
                    finally:
                        for name in ('SW1', 'VM1', 'VM2', 'VM3'):
                            console = manager.directory / name / 'console.log'
                            if console.exists(): shutil.copyfile(console, evidence / (name + '.log'))
                        manager.state = None
                        if manager.directory.exists(): manager.stop()
                for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                self.assertFalse(manager.directory.exists())
