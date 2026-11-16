"""Graphical edits use native validation and never mutate their input."""
import copy
import unittest
from network_labs.appliances.spec import example
from network_labs.appliances import topology_edit as edit


class TopologyEditTests(unittest.TestCase):
    def setUp(self):self.spec=example('/tmp/rootfs')

    def test_insert_switch_and_host_then_rewire_and_remove(self):
        original=copy.deepcopy(self.spec)
        draft=edit.disconnect(self.spec,('SW1','eth1'),('PC2','eth0'))
        draft=edit.add_node(draft,name='SW2',role='switch',rootfs='/tmp/rootfs',ports=4)
        draft=edit.add_node(draft,name='PC3',role='host',rootfs='/tmp/rootfs',address='192.0.2.30/24')
        for a,b in [(('SW1','eth1'),('SW2','eth0')),(('SW2','eth1'),('PC2','eth0')),(('SW2','eth2'),('PC3','eth0'))]:draft=edit.connect(draft,a,b)
        self.assertEqual(len(draft['nodes']),5);self.assertEqual(len(draft['links']),4)
        self.assertEqual(edit.free_ports(draft,'SW2'),['eth3'])
        draft=edit.remove_node(draft,'PC3')
        self.assertEqual(edit.free_ports(draft,'SW2'),['eth2','eth3'])
        self.assertEqual(self.spec,original)

    def test_invalid_edits_leave_input_unchanged(self):
        original=copy.deepcopy(self.spec)
        for operation in [
            lambda:edit.connect(self.spec,('PC1','eth0'),('PC2','eth0')),
            lambda:edit.connect(self.spec,('SW1','eth9'),('PC2','eth0')),
            lambda:edit.disconnect(self.spec,('PC1','eth0'),('PC2','eth0')),
            lambda:edit.add_node(self.spec,name='PC1',role='host',rootfs='/tmp/rootfs'),
            lambda:edit.add_node(self.spec,name='PC3',role='switch',rootfs='/tmp/rootfs',address='192.0.2.30/24'),
            lambda:edit.add_node(self.spec,name='PC3',role='host',rootfs='/tmp/rootfs',address='invalid'),
            lambda:edit.add_node(self.spec,name='FW1',role='firewall',rootfs='/tmp/rootfs'),
            lambda:edit.add_node(self.spec,name='PC3',role='host',rootfs='/tmp/rootfs',ports=0),
        ]:
            with self.subTest(operation=operation),self.assertRaises(ValueError):operation()
            self.assertEqual(self.spec,original)
        single=edit.remove_node(edit.remove_node(self.spec,'PC1'),'PC2')
        with self.assertRaises(ValueError):edit.remove_node(single,'SW1')

    def test_extend_full_switch_without_mutating_original_or_renaming_ports(self):
        self.assertEqual(edit.next_port(self.spec,'SW1'),'eth2')
        draft=edit.add_port(self.spec,'SW1','eth2')
        self.assertEqual(edit.free_ports(draft,'SW1'),['eth2'])
        self.assertEqual(draft['nodes'][1]['switchports']['eth2'],{'mode':'access','vlan':1})
        self.assertNotIn('eth2',self.spec['nodes'][1]['interfaces'])
        with self.assertRaises(ValueError):edit.add_port(self.spec,'SW1','eth0')

    def test_configure_identity_address_gateway_and_admin_atomically(self):
        original=copy.deepcopy(self.spec)
        draft=edit.configure_node(self.spec,'PC2',new_name='CLIENT2',port='eth0',address='192.0.2.22/24',gateway='192.0.2.10',enabled=False)
        node=draft['nodes'][2]
        self.assertEqual(node['name'],'CLIENT2');self.assertEqual(node['interfaces']['eth0'],'192.0.2.22/24')
        self.assertEqual(node['gateway'],'192.0.2.10');self.assertEqual(node['shutdown'],['eth0'])
        self.assertIn([['SW1','eth1'],['CLIENT2','eth0']],draft['links'])
        self.assertEqual(self.spec,original)
        restored=edit.configure_node(draft,'CLIENT2',new_name='CLIENT2',port='eth0',address='192.0.2.22/24',gateway='',enabled=True)
        self.assertNotIn('gateway',restored['nodes'][2]);self.assertEqual(restored['nodes'][2]['shutdown'],[])

    def test_rejected_configuration_never_applies_partial_name_or_links(self):
        original=copy.deepcopy(self.spec)
        defaults=dict(new_name='CLIENT2',port='eth0',address='192.0.2.22/24',gateway='',enabled=True)
        for fault in ({'address':'invalid'},{'gateway':'198.51.100.1'},{'new_name':'PC1'},{'port':'eth9'},{'enabled':1}):
            with self.subTest(fault=fault),self.assertRaises(ValueError):edit.configure_node(self.spec,'PC2',**{**defaults,**fault})
            self.assertEqual(self.spec,original)
        with self.assertRaises(ValueError):edit.configure_node(self.spec,'SW1',**defaults)
        scripted=copy.deepcopy(self.spec);scripted['nodes'][0]['startup']=[['/bin/echo','ref=PC2']]
        before=copy.deepcopy(scripted)
        with self.assertRaises(ValueError):edit.configure_node(scripted,'PC2',**defaults)
        self.assertEqual(scripted,before)
