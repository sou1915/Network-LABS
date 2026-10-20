"""Classic kernel STP, safe cycle validation and declaration/state separation."""
import copy
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from network_labs.appliances.examples import lacp_lab, stp_lab
from network_labs.appliances.ios import compile_config
from network_labs.appliances.runtime import Manager, RuntimeFailure
from network_labs.appliances.spanning_tree import bridge_options, configure_ports, drift, observe, TICKS, verify_kernel
from network_labs.appliances.spec import validate


class STPTests(unittest.TestCase):
    def test_triangle_requires_every_switch_and_matching_timers(self):
        spec = stp_lab('/rootfs')
        self.assertEqual(len(spec['nodes']), 9)
        self.assertEqual(len(spec['links']), 9)
        self.assertEqual(validate(spec), spec)
        for edit in (lambda n: n.update(spanning_tree={'mode': 'off'}),
                     lambda n: n['spanning_tree'].update(hello_time=2),
                     lambda n: n['spanning_tree'].update(mode='rstp'),
                     lambda n: n['spanning_tree'].update(priority=4097),
                     lambda n: n['spanning_tree']['ports']['eth2'].update(priority=17),
                     lambda n: n['spanning_tree']['ports']['eth2'].update(cost=0)):
            s = stp_lab('/rootfs'); n = next(n for n in s['nodes'] if n['name'] == 'SW1'); edit(n)
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                validate(s)
        s = stp_lab('/rootfs')
        for n in s['nodes']:
            n['spanning_tree'] = {'mode': 'off'}
        with self.assertRaisesRegex(ValueError, 'loop'):
            validate(s)

    def test_cyclic_lacp_topology_uses_logical_bridge_ports(self):
        s = lacp_lab('/rootfs')
        for n in s['nodes'][4:]:
            n['interfaces']['eth4'] = ''
            n['spanning_tree'] = {'mode': 'stp'}
        s['links'].append([['SW1', 'eth4'], ['SW2', 'eth4']])
        s = validate(s)
        self.assertIn('bond1', s['nodes'][4]['spanning_tree']['ports'])
        self.assertNotIn('eth2', s['nodes'][4]['spanning_tree']['ports'])

    def test_parameter_apply_never_disables_enabled_tree_and_maps_wire_priority(self):
        node = next(n for n in stp_lab('/rootfs')['nodes'] if n['name'] == 'SW1')
        options = bridge_options(node, node, initial=False)
        self.assertEqual(options[options.index('stp_state') + 1], '1')
        self.assertNotIn('forward_delay', options)
        calls = []
        manager = SimpleNamespace(ns=lambda *args: calls.append(args))
        configure_ports(manager, 0, node, node, initial=True, recreated=set())
        self.assertTrue(all(call[-1] == '32' for call in calls))

    def test_unknown_or_userspace_controller_cannot_be_claimed_as_classic_stp(self):
        node = next(n for n in stp_lab('/rootfs')['nodes'] if n['name'] == 'SW1')
        for state in (0, 2):
            manager = SimpleNamespace(ns=lambda *args: subprocess.CompletedProcess(args, 0, json.dumps([{'linkinfo': {'info_data': {'stp_state': state}}}]), ''))
            with self.assertRaises(RuntimeFailure):
                verify_kernel(manager, 0, node)

    def test_snapshot_drift_ignores_elected_root_and_port_state(self):
        node = next(n for n in stp_lab('/rootfs')['nodes'] if n['name'] == 'SW1')
        bridge = {'stp_state': 1, 'vlan_filtering': 1, 'vlan_default_pvid': 0, 'priority': 4096,
                  'hello_time': TICKS, 'max_age': 6*TICKS, 'forward_delay': 4*TICKS,
                  'bridge_id': '1000.aa:bb:cc:dd:ee:ff', 'root_id': '0000.aa:bb:cc:dd:ee:01', 'root_port': 3}
        links = [{'ifname': 'br0', 'linkinfo': {'info_data': bridge}}]
        links += [{'ifname': p, 'flags': ['UP', 'LOWER_UP'], 'linkinfo': {'info_slave_data': {
                    'cost': 100, 'priority': 32, 'state': 'blocking' if p == 'eth3' else 'forwarding', 'no': hex(i+1)}}}
                  for i, p in enumerate(node['switchports'])]
        self.assertEqual(drift(node, links), [])
        actual = observe(node, links)
        self.assertFalse(actual['is_root'])
        self.assertEqual(actual['root_port'], 'eth2')
        self.assertEqual(actual['ports']['eth3']['priority'], 128)
        self.assertTrue(actual['local_state_settled'])
        links[1]['linkinfo']['info_slave_data']['cost'] = 99
        self.assertTrue(any('port parameters differ' in e for e in drift(node, links)))

    def test_per_port_settings_do_not_share_in_memory_templates(self):
        s = stp_lab('/rootfs')
        sw = next(n for n in s['nodes'] if n['name'] == 'SW1')
        shared = {'cost': 100, 'priority': 128}
        sw['spanning_tree']['ports'] = {'eth2': shared, 'eth3': shared}
        s = validate(s)
        result = compile_config(s, 'SW1', 'conf t\ninterface fa0/3\nspanning-tree cost 200\nspanning-tree port-priority 64\nend')
        sw = next(n for n in result['nodes'] if n['name'] == 'SW1')
        self.assertEqual(sw['spanning_tree']['ports']['eth2'], {'cost': 200, 'priority': 64})
        self.assertEqual(sw['spanning_tree']['ports']['eth3'], shared)

    def test_policy_updates_validate_before_apply_and_use_rollback_journal(self):
        manager = Manager('stp-lan'); spec = stp_lab('/rootfs')
        manager.state = {'spec': spec, 'phase': 'running', 'revision': 0}
        with patch.object(manager, 'save'), patch('network_labs.appliances.lan.configure') as apply:
            with self.assertRaises(ValueError):
                manager.configure_spanning_tree('SW3', priority=1)
            apply.assert_not_called()
            apply.side_effect = [RuntimeFailure('apply failed'), None]
            with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                manager.configure_spanning_tree('SW3', priority=0)
            self.assertEqual(manager.state['spec'], spec)
            self.assertEqual(manager.state['phase'], 'running')
            self.assertNotIn('pending_spec', manager.state)
