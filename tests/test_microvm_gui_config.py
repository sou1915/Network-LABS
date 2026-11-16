"""Configuring micro-VM nodes from the GUI: draft forms, guest management sections, and the live firewall action."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from network_labs.appliances import topology_edit, ui_bridge
from network_labs.appliances.management_options import configure_section, sections
from network_labs.appliances.microvm import firewall_example, router_on_a_stick_example, switch_vlan_example


class GuestDraftFormTests(unittest.TestCase):
    def test_port_address_gateway_and_name_change_on_a_micro_vm_draft(self):
        spec = firewall_example('/kernel', '/disk')
        draft = topology_edit.configure_node(spec, 'VM2', new_name='VM2', port='eth0', address='192.0.2.21/24',
                                             gateway='192.0.2.1', enabled=True)
        host = next(n for n in draft['nodes'] if n['name'] == 'VM2')
        self.assertEqual((host['interfaces']['eth0'], host['gateway']), ('192.0.2.21/24', '192.0.2.1'))
        self.assertEqual(spec['nodes'][1]['interfaces']['eth0'], '192.0.2.20/24')  # The input draft is never edited in place.
        renamed = topology_edit.configure_node(spec, 'VM3', new_name='WEB1', port='eth0', address='198.51.100.20/24',
                                               gateway='198.51.100.1', enabled=True)
        self.assertIn(['FW1', 'eth1'], [e for link in renamed['links'] for e in link if e[0] == 'FW1'])
        self.assertIn('WEB1', [e[0] for link in renamed['links'] for e in link])
        with self.assertRaisesRegex(ValueError, 'débrancher'):
            topology_edit.configure_node(spec, 'VM2', new_name='VM2', port='eth0', address='192.0.2.20/24',
                                         gateway='192.0.2.1', enabled=False)
        with self.assertRaises(ValueError):
            topology_edit.configure_node(spec, 'VM2', new_name='VM2', port='eth0', address='198.51.100.9/24',
                                         gateway='192.0.2.1', enabled=True)  # Gateway no longer on the port's subnet.


class GuestManagementSectionTests(unittest.TestCase):
    def test_each_guest_role_offers_only_what_the_guest_supports(self):
        lab = router_on_a_stick_example('/kernel', '/disk')
        offered = {n['name']: [s['id'] for s in sections(n)] for n in lab['nodes']}
        self.assertEqual(offered['SW1'], ['vmresources', 'switching'])
        self.assertEqual(offered['R1'], ['vmresources', 'subinterfaces', 'dhcpserver'])
        self.assertEqual(offered['VM1'], ['vmresources', 'dhcpserver'])
        self.assertEqual([s['id'] for s in sections(firewall_example('/kernel', '/disk')['nodes'][0])],
                         ['vmresources', 'firewall', 'subinterfaces', 'dhcpserver'])

    def test_switch_vlans_and_router_subinterfaces_are_edited_through_lab_validation(self):
        spec = switch_vlan_example('/kernel', '/disk')
        ports = dict(spec['nodes'][0]['switchports'])
        ports['eth2'] = {'mode': 'access', 'vlan': 10}
        saved = configure_section(spec, 'SW1', 'switching', {'vlans': [1, 10, 20], 'switchports': ports})
        self.assertEqual(saved['nodes'][0]['switchports']['eth2'], {'mode': 'access', 'vlan': 10})
        bad = dict(ports, eth3={'mode': 'trunk', 'native_vlan': 1, 'allowed': [10, 30]})
        with self.assertRaises(ValueError):
            configure_section(spec, 'SW1', 'switching', {'vlans': [1, 10, 20], 'switchports': bad})
        router_lab = router_on_a_stick_example('/kernel', '/disk')
        subinterfaces = dict(router_lab['nodes'][1]['subinterfaces'])
        subinterfaces['eth0.30'] = {'parent': 'eth0', 'vlan': 30, 'address': '203.0.113.1/24'}
        saved = configure_section(router_lab, 'R1', 'subinterfaces', {'subinterfaces': subinterfaces})
        self.assertIn('eth0.30', saved['nodes'][1]['subinterfaces'])
        with self.assertRaises(ValueError):
            configure_section(router_lab, 'SW1', 'subinterfaces', {'subinterfaces': subinterfaces})


class LiveFirewallBridgeTests(unittest.TestCase):
    def request(self, **change):
        base = {'id': 'a' * 32, 'owner_uid': os.geteuid(), 'action': 'firewall', 'target': '/tmp/snapshot.json',
                'lab': 'microvm-firewall', 'node': 'FW1', 'destination': None}
        return {**base, **change}

    def test_request_needs_a_snapshot_and_a_node(self):
        self.assertEqual(ui_bridge.validate_request(self.request())['action'], 'firewall')
        for fault in ({'target': 'microvm-firewall'}, {'node': None}, {'node': 'bad;name'}, {'destination': 'VM2'}):
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                ui_bridge.validate_request(self.request(**fault))

    def test_backend_applies_the_saved_projects_policy_to_the_running_lab(self):
        spec = firewall_example('/kernel', '/disk')
        spec['nodes'][0]['firewall']['rules'].append({'name': 'outside-ping-in', 'in': 'eth1', 'out': 'eth0', 'protocol': 'icmp',
                                                      'action': 'accept'})
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder) / 'manifest.json'
            snapshot.write_text(json.dumps(spec))
            manager = unittest.mock.MagicMock()
            manager.__enter__.return_value = manager
            manager.locked.return_value = manager
            manager.read.return_value = {'spec': spec}
            manager.configure_firewall.return_value = {'configured': 'FW1', 'revision': 2}
            with patch('network_labs.appliances.runtime.Manager', return_value=manager):
                result = ui_bridge.backend('firewall', str(snapshot), 'FW1')
                manager.configure_firewall.assert_called_once()
                name, policy = manager.configure_firewall.call_args.args
                self.assertEqual((name, policy['rules'][-1]['name']), ('FW1', 'outside-ping-in'))
                self.assertEqual((result['ok'], result['action'], result['data']['revision']), (True, 'firewall', 2))
                with self.assertRaisesRegex(ValueError, 'no firewall policy'):
                    ui_bridge.backend('firewall', str(snapshot), 'VM2')
