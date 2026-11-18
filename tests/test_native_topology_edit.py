import json
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
        self.assertEqual(edit.remove_node(single,'SW1')['nodes'],[])  # an empty project is a blank canvas

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


class MicroVMDraftTests(unittest.TestCase):
    """Adding Firecracker nodes to a draft, and the GUI state read from a micro-VM status report."""

    def lab(self):
        from network_labs.appliances.microvm import example
        return example('/kernel', '/disk')

    def test_each_role_and_dhcp_host_validate(self):
        spec = self.lab()
        spec = edit.add_microvm_node(spec, name='R9', role='router', kernel='/kernel', disk='/disk', ports=2,
                                     addresses='10.9.0.1/24, 10.9.1.1/24')
        spec = edit.add_microvm_node(spec, name='FW9', role='firewall', kernel='/kernel', disk='/disk', ports=2,
                                     addresses='10.8.0.1/24,10.8.1.1/24')
        spec = edit.add_microvm_node(spec, name='SW9', role='switch', kernel='/kernel', disk='/disk', ports=3, addresses='ignored')
        spec = edit.add_microvm_node(spec, name='PC9', role='host', kernel='/kernel', disk='/disk', addresses='dhcp')
        nodes = {n['name']: n for n in spec['nodes']}
        self.assertEqual(nodes['R9']['interfaces'], {'eth0': '10.9.0.1/24', 'eth1': '10.9.1.1/24'})
        self.assertEqual(nodes['FW9']['firewall']['default'], 'drop')
        self.assertEqual(nodes['SW9']['interfaces'], {'eth0': '', 'eth1': '', 'eth2': ''})
        self.assertEqual((nodes['PC9']['interfaces'], nodes['PC9']['dhcp_clients']), ({'eth0': ''}, ['eth0']))
        self.assertTrue(all(n['runtime'] == 'firecracker' for n in spec['nodes']))

    def test_bad_drafts_are_refused_and_input_is_unchanged(self):
        spec = self.lab()
        before = json.dumps(spec, sort_keys=True)
        bad = [dict(role='router', ports=2, addresses='10.9.0.1/24'), dict(role='router', ports=5, addresses=''),
               dict(role='router', ports=2, addresses='dhcp'), dict(role='host', ports=2, addresses='dhcp'),
               dict(role='server', ports=1, addresses='10.9.0.1/24'), dict(role='router', ports=1, addresses='')]
        for case in bad:
            with self.subTest(case=case), self.assertRaises(ValueError):
                edit.add_microvm_node(spec, name='X1', kernel='/kernel', disk='/disk', **case)
        self.assertEqual(json.dumps(spec, sort_keys=True), before)

    def test_status_maps_micro_vms_by_their_vmm_and_containers_by_their_state(self):
        from network_labs.appliances.ui_bridge import observed_states
        status = {'nodes': [
                            {'name': 'VM1', 'runtime': 'firecracker', 'vmm_alive': True, 'vmm_memory_bytes': 64 << 20},
                            {'name': 'VM2', 'runtime': 'firecracker', 'vmm_alive': False},
                            {'name': 'PC1', 'runtime': 'oci', 'state': {'status': 'running'}, 'memory_current_bytes': 1},
                            {'name': 'PC2', 'runtime': 'oci', 'state': None}]}
        self.assertEqual(observed_states(status), {
            'VM1': {'status': 'running', 'memory': 64 << 20}, 'VM2': {'status': 'stopped', 'memory': None},
            'PC1': {'status': 'running', 'memory': 1}, 'PC2': {'status': 'invité non vérifié', 'memory': None}})
