"""A running Cisco switch guest changed only from its terminal: « switchport access vlan 10 » separates PC1 from PC2 and
PC3 on the real bridge, and « shutdown » on a port takes its link down, then « no shutdown » brings it back, live;
« interface vlan 1 » then gives the switch its management address, which PC1 (VLAN 1) reaches and PC2 (VLAN 10) does not."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console, topology_edit
from network_labs.appliances.guest_image import build
from network_labs.appliances.guest_startup import query
from network_labs.appliances.runtime import Manager
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project

from tests.test_native_microvm_missions import wait_ready

VLAN = ['en', 'conf t', 'vlan 10', 'name STAFF', 'int range fa0/2 - 3', 'sw mo acc', 'sw acc vl 10', 'end', 'sh vlan br']
SHUT = ['conf t', 'int fa0/3', 'shut', 'end', 'sh int status']
NO_SHUT = ['conf t', 'int fa0/3', 'no shut', 'end']
SVI = ['conf t', 'int vlan 1', 'ip address 10.0.0.250 255.255.255.0', 'no shut', 'end', 'ping 10.0.0.1', 'sh ip int br']


def lab(kernel, disk):
    """SW1 (Catalyst 2960, no VLAN set: all ports in VLAN 1) with PC1..PC3 on one subnet."""
    spec = blank_project('switch-live')
    spec = topology_edit.add_microvm_node(spec, name='SW1', role='switch', kernel=kernel, disk=disk, ports=3, model='cisco-2960')
    for index in range(3):
        name = f'PC{index + 1}'
        spec = topology_edit.add_microvm_node(spec, name=name, role='host', kernel=kernel, disk=disk, ports=1,
                                              addresses=f'10.0.0.{index + 1}/24')
        spec = topology_edit.connect(spec, (name, 'eth0'), ('SW1', f'eth{index}'))
    return validate(spec)


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1' and os.environ.get('NETWORK_LABS_GUEST_VLAN') == '1',
                     'Opt-in real KVM test on a guest kernel with 802.1Q and bridge VLAN filtering')
class SwitchLiveGuestTests(unittest.TestCase):
    def test_vlans_and_shutdown_typed_on_a_running_switch(self):
        self.assertEqual(os.geteuid(), 0)
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'switch-live'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlswl-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = lab(str(kernel), str(root / 'base.ext4'))
            transcript, pings, vlans, tables = [], {}, None, {}
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), \
                    patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name'])
                try:
                    with manager.locked():
                        manager.start(spec)
                        wait_ready(manager, spec)
                    switch = guest_console.Console(spec['name'], 'SW1')
                    hosts = {name: guest_console.Console(spec['name'], name) for name in ('PC1', 'PC2')}

                    def typed(lines):
                        for line in lines:
                            prompt = switch.prompt()
                            reply = switch.line(line)
                            transcript.append(prompt + line + ('\n' + reply if reply else ''))

                    def ping(label, source, destination, reach):
                        for _ in range(3):  # a first ping after a change can lose its ARP exchange
                            pings[label] = hosts[source].line('ping ' + destination)
                            if ('4 packets received' in pings[label]) == reach:
                                break
                            time.sleep(1)

                    ping('PC1 -> PC2, all in VLAN 1', 'PC1', '10.0.0.2', True)
                    typed(VLAN)
                    ping('PC1 -> PC2, PC2 in VLAN 10', 'PC1', '10.0.0.2', False)
                    ping('PC2 -> PC3, both in VLAN 10', 'PC2', '10.0.0.3', True)
                    vlans = query(manager.directory / 'SW1' / 'guest.vsock', 'bridge-vlans')
                    typed(SHUT)
                    ping('PC2 -> PC3, Fa0/3 shut', 'PC2', '10.0.0.3', False)
                    typed(NO_SHUT)
                    ping('PC2 -> PC3, Fa0/3 no shut', 'PC2', '10.0.0.3', True)
                    typed(SVI)  # the switch's management address on its bridge, in VLAN 1 (filtering is on)
                    ping('PC1 -> SW1 Vlan1', 'PC1', '10.0.0.250', True)
                    ping('PC2 (VLAN 10) -> SW1 Vlan1', 'PC2', '10.0.0.250', False)
                    tables = {'SW1 mac': switch.line('sh mac address-table'), 'PC1 arp': hosts['PC1'].line('arp -a')}
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            text = '\n'.join(transcript)
            (evidence / 'result.json').write_text(json.dumps({'transcript': text, 'pings': pings, 'bridge_vlans': vlans, 'tables': tables},
                                                             indent=2, ensure_ascii=False))
            print('\n' + text, flush=True)
            for label, reply in pings.items():
                print(f'\n{label}:\n{reply}', flush=True)
            self.assertIn('4 packets received', pings['PC1 -> PC2, all in VLAN 1'])
            self.assertIn('0 packets received', pings['PC1 -> PC2, PC2 in VLAN 10'])  # the real bridge now separates them
            self.assertIn('4 packets received', pings['PC2 -> PC3, both in VLAN 10'])
            self.assertIn('0 packets received', pings['PC2 -> PC3, Fa0/3 shut'])
            self.assertIn('4 packets received', pings['PC2 -> PC3, Fa0/3 no shut'])
            self.assertRegex(transcript[len(VLAN) - 1], r'10\s+STAFF\s+active\s+Fa0/2, Fa0/3')
            self.assertRegex(transcript[-len(NO_SHUT) - len(SVI) - 1], r'Fa0/3\s+disabled')
            self.assertIn('4 packets received', pings['PC1 -> SW1 Vlan1'])
            self.assertIn('0 packets received', pings['PC2 (VLAN 10) -> SW1 Vlan1'])
            self.assertIn('!!!!!', transcript[-2])  # SW1 pings PC1 from its SVI
            self.assertRegex(transcript[-1], r'Vlan1\s+10\.0\.0\.250\s+YES manual up\s+up')
            for label, text in tables.items():
                print(f'\n{label}:\n{text}', flush=True)
            # Learned by the real bridge from the pings: PC1 on Fa0/1 in VLAN 1, PC2/PC3 on Fa0/2-3 in VLAN 10.
            self.assertRegex(tables['SW1 mac'], r'\n\s+1\s+[0-9a-f.]{14}\s+DYNAMIC\s+Fa0/1\n')
            self.assertRegex(tables['SW1 mac'], r'\n\s+10\s+[0-9a-f.]{14}\s+DYNAMIC\s+Fa0/[23]\n')
            self.assertRegex(tables['PC1 arp'], r'10\.0\.0\.250\s+([0-9A-F]{2}-){5}[0-9A-F]{2}\s+dynamic')
