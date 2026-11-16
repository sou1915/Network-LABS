"""VLAN group metadata must come from explicit access-port configuration."""
import unittest
from network_labs.appliances.spec import example
from network_labs.appliances.ui_bridge import public_topology
from network_labs.appliances.workspace_art import access_vlans,networks


class DeclaredVlanTests(unittest.TestCase):
    def test_only_explicit_access_membership_is_grouped(self):
        spec=example('/tmp/rootfs');graph=public_topology(spec)
        self.assertEqual(access_vlans(graph,spec),{'PC1':1,'PC2':1})
        spec['nodes'][1]['switchports']['eth1']={'mode':'trunk','native_vlan':1,'allowed':'all'}
        self.assertEqual(access_vlans(graph,spec),{'PC1':1})
        spec['nodes'][1]['switchports']={}
        self.assertEqual(access_vlans(graph,spec),{})

    def test_multihomed_host_with_different_vlans_is_not_falsely_grouped(self):
        spec=example('/tmp/rootfs');spec['nodes'][0]['interfaces']['eth1']=''
        spec['nodes'][1]['interfaces']['eth2']='';spec['nodes'][1]['switchports']['eth2']={'mode':'access','vlan':20}
        spec['links'].append([['PC1','eth1'],['SW1','eth2']])
        self.assertNotIn('PC1',access_vlans(public_topology(spec),spec))

    def test_group_subnet_does_not_include_an_unconnected_interface(self):
        spec=example('/tmp/rootfs');spec['nodes'][0]['interfaces']['eth1']='198.51.100.10/24'
        self.assertEqual(networks(public_topology(spec),['PC1'],spec,1),'192.0.2.0/24')
