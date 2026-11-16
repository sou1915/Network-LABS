"""The reference-shaped campus remains a validated native configuration."""
import unittest
from network_labs.appliances.campus import campus_example
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_bridge import public_topology
from network_labs.appliances.workspace_art import access_vlans,firewall_hosts,link_caption
from network_labs.appliances.topology_edit import add_node


class CampusTemplateTests(unittest.TestCase):
    def test_real_roles_routes_trunks_and_closed_firewall(self):
        spec=campus_example('/tmp/rootfs');self.assertEqual(validate(spec),spec)
        self.assertEqual(len(spec['nodes']),10);self.assertEqual(len(spec['links']),9)
        nodes={n['name']:n for n in spec['nodes']}
        self.assertEqual(nodes['FW1']['firewall']['default'],'drop');self.assertFalse(nodes['FW1']['firewall']['rules'])
        self.assertTrue(nodes['R1']['forwarding']);self.assertEqual(len(nodes['R1']['subinterfaces']),3)
        graph=public_topology(spec)
        self.assertEqual(access_vlans(graph,spec),{'PC1':10,'PC2':10,'PC3':20,'PC4':20,'PC5':30})
        self.assertEqual(firewall_hosts(graph),{'SRV1':'FW1'})
        self.assertEqual(link_caption(['R1','eth1'],['SW1','eth0'],nodes),'Trunk · 802.1Q')
        self.assertEqual(link_caption(['R1','eth0'],['FW1','eth0'],nodes),'10.0.0.0/30')

    def test_firewall_palette_requires_explicit_policy(self):
        spec=campus_example('/tmp/rootfs')
        with self.assertRaises(ValueError):add_node(spec,name='FW2',role='firewall',rootfs='/tmp/rootfs')
        draft=add_node(spec,name='FW2',role='firewall',rootfs='/tmp/rootfs',firewall={'default':'drop','stateful':True,'rules':[]})
        self.assertEqual(draft['nodes'][-1]['firewall']['default'],'drop')
