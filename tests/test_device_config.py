import unittest
from network_labs.engine import demo
from network_labs.cli import Session
from network_labs.device_config import apply_device_commands,fingerprint

class DeviceConfigTests(unittest.TestCase):
    def test_atomic_batch_and_live_references(self):
        lab=demo(); node=lab.nodes['SW1']; port=node.ports['gi0/1']; session=Session(lab,'SW1')
        apply_device_commands(lab,'SW1',['hostname ACCESS','interface gi0/1','description GUI managed','shutdown','end'])
        self.assertIs(lab.nodes['SW1'],node);self.assertIs(node.ports['gi0/1'],port)
        self.assertEqual(session.n.hostname,'ACCESS');self.assertTrue(port.shutdown)
        before=lab.dumps()
        with self.assertRaises(ValueError):
            apply_device_commands(lab,'SW1',['interface gi0/1','no shutdown','switchport access vlan 5000'])
        self.assertEqual(before,lab.dumps());self.assertTrue(port.shutdown)
    def test_clear_endpoint_fields_and_subinterface_delete(self):
        lab=demo()
        apply_device_commands(lab,'PC1',['no ip address','no ip gateway','no ip dns'])
        self.assertEqual(lab.nodes['PC1'].address,'')
        with self.assertRaises(ValueError):
            apply_device_commands(lab,'R1',['no interface extra gi0/0.10'])
        self.assertIn('10',lab.nodes['R1'].interfaces)
        apply_device_commands(lab,'R1',['no interface gi0/0.10'])
        self.assertNotIn('10',lab.nodes['R1'].interfaces)
        self.assertNotIn('gi0/0.10',lab.nodes['R1'].ports)
    def test_vtp_reset_and_description_clear(self):
        lab=demo()
        apply_device_commands(lab,'SW1',['vtp domain CAMPUS','vtp password Secret','no vtp domain','no vtp password','interface gi0/1','description example','no description'])
        n=lab.nodes['SW1']
        self.assertEqual((n.vtp_domain,n.vtp_password,n.ports['gi0/1'].description),('','',''))
    def test_position_not_configuration_conflict(self):
        node=demo().nodes['PC1']; before=fingerprint(node);node.x+=10
        self.assertEqual(before,fingerprint(node))
