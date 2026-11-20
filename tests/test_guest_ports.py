"""Sixteen ports per micro-VM (eth0..eth15), as a switch lab needs: the guest agent parses two-digit port names in every
request (its configuration renderers prove it without a guest), the host side checks them, and a 2960 placed from the
library gets 16 ports; eth16 and beyond stay refused."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from network_labs.appliances import topology_edit
from network_labs.appliances.guest_control import _bridge_vlan_command, guest_interface, ospf_fields, rip_fields
from network_labs.appliances.native_models import MICROVM_PORTS, default_ports
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project


def switch_lab(ports=16):
    spec = blank_project('ports')
    spec = topology_edit.add_microvm_node(spec, name='SW1', role='switch', kernel='/k', disk='/d', ports=ports, model='cisco-2960')
    for index, port in ((1, 'eth0'), (2, f'eth{ports - 1}')):
        spec = topology_edit.add_microvm_node(spec, name=f'PC{index}', role='host', kernel='/k', disk='/d', ports=1,
                                              addresses=f'192.168.1.{index * 10}/24')
        spec = topology_edit.connect(spec, (f'PC{index}', 'eth0'), ('SW1', port))
    return validate(spec)


class PortLimitTest(unittest.TestCase):
    def test_sixteen_ports_and_no_more(self):
        self.assertEqual(MICROVM_PORTS, 16)
        spec = switch_lab()
        self.assertEqual(list(spec['nodes'][0]['interfaces']), [f'eth{i}' for i in range(16)])
        with self.assertRaises(ValueError):
            topology_edit.add_microvm_node(blank_project('x'), name='SW1', role='switch', kernel='/k', disk='/d', ports=17)
        self.assertEqual(default_ports('cisco-2960', 'firecracker'), 16)  # a 2960 from the library: Fa0/1 .. Fa0/16
        self.assertEqual(default_ports('cisco-2960', 'oci'), 24)  # containers keep their own limit

    def test_firecracker_numbers_the_devices_in_port_order(self):
        from pathlib import Path as P
        from network_labs.appliances.runtime import firecracker_config
        devices = firecracker_config(switch_lab()['nodes'][0], P('/k'), P('/d'))['network-interfaces']
        # The guest names its network devices in this order: eth10 must be the eleventh, not the third.
        self.assertEqual([d['iface_id'] for d in devices], [f'eth{i}' for i in range(16)])
        self.assertEqual([d['host_dev_name'] for d in devices], [f'tap{i}' for i in range(16)])
        self.assertTrue(devices[15]['guest_mac'].endswith(':0f'))

    def test_the_last_port_carries_traffic_in_the_model(self):
        from network_labs.appliances.network_model import Model
        self.assertEqual(Model(switch_lab()).ping('PC1', '192.168.1.20')[0], True)

    def test_two_digit_port_names_on_the_host_side(self):
        self.assertTrue(all(guest_interface(n) for n in ('eth10', 'eth15', 'eth15.4094', 'eth12.10')))
        self.assertFalse(any(guest_interface(n) for n in ('eth16', 'eth010', 'eth1a', 'eth15.0')))
        self.assertEqual(_bridge_vlan_command('bridge-vlan-add', 'eth15', 10, 'pvid'), 'BRIDGE_VLAN_ADD eth15 10 pvid')
        with self.assertRaises(ValueError):
            _bridge_vlan_command('bridge-vlan-add', 'eth16', 10, 'pvid')


class AgentPortTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.folder.name) / 'agent'
        subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', '-o', str(cls.binary), 'network_labs/appliances/guest/agent.c'], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def invoke(self, line):
        out = subprocess.run([str(self.binary), '--stdio'], input=(line + '\n').encode(), capture_output=True, timeout=7).stdout
        header, _, body = out.partition(b'\n')
        return int(header.split()[1]), body.decode()

    def test_rip_and_ospf_render_every_port_up_to_eth15(self):
        ports = [{'port': f'eth{i}', 'passive': i % 2 == 1} for i in range(16)]
        code, config = self.invoke('NL1 RIP_RENDER ' + rip_fields({'router_id': '10.0.0.1', 'version': 2, 'interfaces': ports}))
        self.assertEqual(code, 0, config)
        self.assertIn('interface "eth15"', config)
        ospf = [{'port': f'eth{i}', 'cost': 10, 'passive': False, 'type': 'broadcast', 'priority': 1} for i in range(16)]
        code, config = self.invoke('NL1 OSPF_RENDER ' + ospf_fields({'router_id': '10.0.0.1', 'hello': 1, 'dead': 4, 'interfaces': ospf}))
        self.assertEqual(code, 0, config)
        self.assertIn('interface "eth15"', config)
        for bad in ('10.0.0.1 2 eth16:a', '10.0.0.1 2 eth010:a', '10.0.0.1 2 eth15:a,eth15:p'):
            with self.subTest(fields=bad):
                self.assertEqual(self.invoke('NL1 RIP_RENDER ' + bad)[0], 2)

    def test_eigrp_passive_ports_up_to_eth15(self):
        passive = ','.join(f'eth{i}' for i in range(16))
        code, config = self.invoke(f'NL1 EIGRP_RENDER 100 10.0.0.1 10.0.0.0/8 {passive}')
        self.assertEqual(code, 0, config)
        self.assertIn('passive-interface eth15', config)
        self.assertEqual(self.invoke('NL1 EIGRP_RENDER 100 10.0.0.1 10.0.0.0/8 eth16')[0], 2)


if __name__ == '__main__':
    unittest.main()
