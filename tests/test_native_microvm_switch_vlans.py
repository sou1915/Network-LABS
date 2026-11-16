"""Real VLAN switch guests: access ports separate one subnet into two VLANs, and a trunk carries both to a second switch."""
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
from network_labs.appliances.guest_startup import check_switch, observed_vlans, query, save_observed, vlan_plan
from network_labs.appliances.microvm import switch_vlan_example
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, process_identity


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1' and os.environ.get('NETWORK_LABS_GUEST_VLAN') == '1',
                     'Opt-in real KVM test on a guest kernel with 802.1Q and bridge VLAN filtering')
class SwitchVlanGuestTests(unittest.TestCase):
    def test_access_isolation_trunk_port_loss_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'switch-vlans'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlvl-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = switch_vlan_example(kernel, root / 'base.ext4')
            hosts = ['VM1', 'VM2', 'VM3', 'VM4']
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

                        def wait_ready():
                            for name in hosts:
                                deadline = time.monotonic() + 40
                                while True:
                                    try:
                                        query(sockets[name], 'ready')
                                        break
                                    except (ValueError, OSError):
                                        if time.monotonic() >= deadline:
                                            raise
                                        time.sleep(.1)

                        def connectivity():
                            # Same subnet everywhere: only the VLAN decides who hears whom.
                            probe('VM1', '192.0.2.12', True, attempts=3)   # VLAN 10, same switch
                            probe('VM1', '192.0.2.14', True, attempts=3)   # VLAN 10, across the trunk
                            probe('VM1', '192.0.2.13', False)              # VLAN 20
                            probe('VM4', '192.0.2.13', False)              # VLAN 10 on SW2 to VLAN 20 on SW1

                        wait_ready()
                        for switch in spec['nodes'][:2]:
                            results[switch['name'] + '_vlans'] = query(sockets[switch['name']], 'bridge-vlans')
                            self.assertEqual(observed_vlans(sockets[switch['name']], switch), vlan_plan(switch))
                        connectivity()
                        # Moving VM3's port into VLAN 10 joins it to VM1; moving it back separates it again.
                        query(sockets['SW1'], 'bridge-vlan-add', interface='eth2', vlan=10, state='pvid')
                        query(sockets['SW1'], 'bridge-vlan-delete', interface='eth2', vlan=20)
                        probe('VM1', '192.0.2.13', True, attempts=5)
                        with self.assertRaisesRegex(ValueError, 'VLAN membership differs'):
                            check_switch(sockets['SW1'], spec['nodes'][0])
                        query(sockets['SW1'], 'bridge-vlan-add', interface='eth2', vlan=20, state='pvid')
                        query(sockets['SW1'], 'bridge-vlan-delete', interface='eth2', vlan=10)
                        probe('VM1', '192.0.2.13', False)
                        # Losing the trunk breaks only the path to SW2.
                        query(sockets['SW1'], 'link', interface='eth3', state='down')
                        probe('VM1', '192.0.2.14', False)
                        probe('VM1', '192.0.2.12', True)
                        query(sockets['SW1'], 'link', interface='eth3', state='up')
                        probe('VM1', '192.0.2.14', True, attempts=5)
                        results['saved'] = save_observed(manager)
                        restored = load_startup(manager.name)
                        self.assertEqual(restored['nodes'][0]['switchports'], spec['nodes'][0]['switchports'])
                        manager.stop()
                        for record in records:
                            self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                        manager = Manager(spec['name'])
                        manager.start(restored)
                        records.extend(manager.state['vms'])
                        wait_ready()
                        connectivity()
                        results['cold_restore_passed'] = True
                        (evidence / 'result.json').write_text(json.dumps(results, indent=2))
                    finally:
                        for name in ('SW1', 'SW2', *hosts):
                            console = manager.directory / name / 'console.log'
                            if console.exists():
                                shutil.copyfile(console, evidence / (name + '.log'))
                        manager.state = None
                        if manager.directory.exists():
                            manager.stop()
                for record in records:
                    self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                self.assertFalse(manager.directory.exists())
