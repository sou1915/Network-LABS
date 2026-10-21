"""L3 switch policy, partial CLI contexts and truthful kernel SVI evidence."""
import copy
import subprocess
import unittest
from unittest.mock import Mock

from network_labs.appliances.examples import svi_lab, rstp_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.ios import compile_config
from network_labs.appliances.interface_stats import managed_ports
from network_labs.appliances.svi import observe, drift
from network_labs.appliances.runtime import Manager


class SVITests(unittest.TestCase):
    def test_switch_addressing_is_only_on_declared_virtual_vlan_interfaces(self):
        spec = svi_lab('/rootfs')
        self.assertFalse(spec['nodes'][4]['forwarding'])
        self.assertTrue({'vlan10', 'vlan20'} <= managed_ports(spec['nodes'][4]))
        spec['nodes'][4]['interfaces']['eth0'] = '203.0.113.1/24'
        with self.assertRaisesRegex(ValueError, 'physical ports'):
            validate(spec)
        spec = svi_lab('/rootfs'); spec['nodes'][5]['forwarding'] = True
        with self.assertRaisesRegex(ValueError, 'forwarding'):
            validate(spec)

    def test_invalid_unusable_overlapping_and_injectable_svi_policies_are_rejected(self):
        for field in ({'address': '192.0.2.99/24'}, {'address': '127.0.0.1/24'}, {'address': '224.0.0.1/24'},
                      {'address': '0.0.0.0/24'}, {'address': '198.51.100.0/24'}, {'address': '198.51.100.255/24'},
                      {'address': 123}, {'address': '198.51.100.1/24\nanything'}, {'vlan': 10}, {'vlan': True}, {'vrf': 'unknown'}):
            spec = svi_lab('/rootfs'); spec['nodes'][4]['svis']['vlan20'].update(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(spec)
        for svis in ([], {'vlan010': {'vlan': 10}}, {'br0': {'vlan': 10}}, {f'vlan{i}': {'vlan': i} for i in range(1, 34)}):
            spec = svi_lab('/rootfs'); spec['nodes'][4]['svis'] = svis
            with self.subTest(svis=svis), self.assertRaises(ValueError):
                validate(spec)

    def test_svis_do_not_silently_enable_unsupported_backends_or_roles(self):
        for index in (0, 1):
            spec = svi_lab('/rootfs'); spec['nodes'][index]['svis'] = {'vlan10': {'vlan': 10, 'address': ''}}
            with self.assertRaises(ValueError):
                validate(spec)
        spec = rstp_lab('/rootfs'); spec['nodes'][3]['svis'] = {'vlan10': {'vlan': 10, 'address': '192.0.2.1/24'}}
        with self.assertRaisesRegex(ValueError, 'Linux-bridge'):
            validate(spec)

    def test_realistic_svi_command_contexts_create_edit_delete_and_validate_whole_blocks(self):
        spec = svi_lab('/rootfs'); before = copy.deepcopy(spec)
        enabled = compile_config(spec, 'SW1', 'conf t\nip routing\ninterface vlan 20\nshutdown\nend')
        self.assertTrue(enabled['nodes'][4]['forwarding'])
        self.assertIn('vlan20', enabled['nodes'][4]['shutdown'])
        modified = compile_config(enabled, 'SW1', 'conf t\ninterface Vlan20\nno ip address\nno shutdown\nend')
        self.assertEqual(modified['nodes'][4]['svis']['vlan20']['address'], '')
        restored = compile_config(modified, 'SW1', 'conf t\ninterface vlan20\nip address 198.51.100.1 255.255.255.0\nend')
        removed = compile_config(restored, 'SW1', 'conf t\nno interface vlan 20\nend')
        self.assertNotIn('vlan20', removed['nodes'][4]['svis'])
        with self.assertRaisesRegex(ValueError, 'Line'):
            compile_config(spec, 'SW1', 'conf t\ninterface vlan20\nshutdown\nswitchport access vlan 10\nend')
        self.assertEqual(spec, before)

    def test_manifest_static_routes_use_a_numbered_svi_not_an_unnumbered_switchport(self):
        spec = svi_lab('/rootfs'); node = spec['nodes'][4]
        node['routes'] = [{'destination': '203.0.113.0/24', 'gateway': '198.51.100.254', 'interface': 'vlan20'}]
        self.assertEqual(validate(spec)['nodes'][4]['routes'][0]['interface'], 'vlan20')
        node['routes'][0]['interface'] = 'eth0'
        with self.assertRaises(ValueError):
            validate(spec)

    def test_kernel_parent_vlan_and_arp_evidence_remain_independent_of_carrier_guesses(self):
        node = svi_lab('/rootfs')['nodes'][4]
        links = [{'ifname': 'br0', 'ifindex': 7}]
        for vid in (10, 20):
            links.append({'ifname': 'vlan' + str(vid), 'link_index': 7, 'flags': ['UP'], 'operstate': 'DOWN',
                          'linkinfo': {'info_kind': 'vlan', 'info_data': {'id': vid, 'protocol': '802.1Q'}}})
        manager = Mock(); manager.ns.return_value = subprocess.CompletedProcess([], 0, '1\n2\n1\n2\n', '')
        actual = observe(manager, 4, node, links)
        self.assertTrue(actual['vlan20']['encapsulation_verified'])
        self.assertTrue(actual['vlan20']['arp_verified'])
        self.assertEqual(actual['vlan20']['operstate'], 'DOWN')
        self.assertNotIn('ready', actual['vlan20'])
        links[2]['link_index'] = 8
        self.assertFalse(observe(manager, 4, node, links)['vlan20']['encapsulation_verified'])
        manager.ns.return_value = subprocess.CompletedProcess([], 1, '', 'unavailable')
        self.assertFalse(observe(manager, 4, node, links)['vlan20']['arp_verified'])

    def test_save_refuses_self_membership_or_svi_encapsulation_drift(self):
        node = svi_lab('/rootfs')['nodes'][4]
        actual = {'vlans': [{'ifname': 'br0', 'vlans': [{'vlan': 10, 'flags': []}, {'vlan': 20, 'flags': []}]}],
                  'svis': {n: {'encapsulation_verified': True, 'arp_verified': True} for n in node['svis']}}
        self.assertEqual(drift(node, actual), [])
        actual['vlans'][0]['vlans'][1]['flags'] = ['Egress Untagged']
        self.assertTrue(drift(node, actual))
        actual['vlans'][0]['vlans'][1]['flags'] = []
        actual['svis']['vlan20']['arp_verified'] = False
        self.assertTrue(drift(node, actual))

    def test_ovs_network_updates_are_refused_before_journaling_unapplied_configuration(self):
        state = {'spec': rstp_lab('/rootfs'), 'phase': 'running'}
        manager = Mock(); manager.read.return_value = state
        original = copy.deepcopy(state)
        candidate = copy.deepcopy(state['spec']); candidate['nodes'][3]['spanning_tree']['priority'] = 8192
        with self.assertRaisesRegex(ValueError, 'OVS live'):
            Manager._configure_network(manager, 'SW1', candidate, 'should not apply')
        manager.save.assert_not_called()
        self.assertEqual(state, original)
