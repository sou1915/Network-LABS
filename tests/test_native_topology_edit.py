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
