"""RSTP requires an actual OVS backend; configuration is separate from runtime state."""
import copy
import subprocess
import unittest
from unittest.mock import Mock

from network_labs.appliances.examples import rstp_lab
from network_labs.appliances.ovs import table, fingerprint, tree, transaction
from network_labs.appliances.spec import validate


class OVSTests(unittest.TestCase):
    def test_rstp_requires_explicit_ovs_and_preserves_input(self):
        spec = rstp_lab('/rootfs'); original = copy.deepcopy(spec)
        self.assertEqual(validate(spec), spec)
        self.assertEqual(spec, original)
        spec['nodes'][3]['switch_backend'] = 'linux'
        with self.assertRaisesRegex(ValueError, 'RSTP'):
            validate(spec)

    def test_unsupported_controller_combinations_fail_before_resources(self):
        for changes in ({'startup': [['/bin/true']]}, {'dialect': 'ios-basic'}, {'shutdown': ['eth1']},
                        {'memory_mib': 32}, {'lldp': {'ports': ['eth0']}}, {'switch_backend': 'unknown'}):
            spec = rstp_lab('/rootfs'); spec['nodes'][3].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate(spec)
        for settings in ({'hello_time': 3}, {'mode': 'stp'}, {'ports': {'eth1': {'bpdu_guard': True}}}):
            spec = rstp_lab('/rootfs'); spec['nodes'][3]['spanning_tree'].update(settings)
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                validate(spec)

    def test_mixed_trees_and_trunks_are_not_silently_supported(self):
        spec = rstp_lab('/rootfs'); spec['nodes'][3]['switch_backend'] = 'linux'; spec['nodes'][3]['spanning_tree']['mode'] = 'stp'
        with self.assertRaisesRegex(ValueError, 'same STP mode'):
            validate(spec)
        spec = rstp_lab('/rootfs'); spec['nodes'][3]['switchports']['eth0'] = {'mode': 'trunk', 'native_vlan': 10, 'allowed': [10]}
        with self.assertRaisesRegex(ValueError, 'access'):
            validate(spec)

    def test_rstp_and_access_memberships_enter_the_same_atomic_database_transaction(self):
        args = transaction(rstp_lab('/rootfs')['nodes'][3])
        self.assertIn('rstp_enable=true', args)
        self.assertIn('stp_enable=false', args)
        self.assertIn('other_config:rstp-force-protocol-version=2', args)
        self.assertEqual(args.count('tag=10'), 3)
        self.assertNotIn('stp_state', args)
        self.assertNotIn('controller', args)

    def test_policy_fingerprint_ignores_protocol_counters_but_requires_live_controller(self):
        actual = {'controller_available': True,
                  'bridges': [{'name': 'br0', 'rstp_enable': True, 'rstp_status': {'rstp_root_id': 'first'}}],
                  'ports': [{'name': 'eth0', 'tag': 10, 'rstp_status': {'rstp_port_state': 'Forwarding'}, 'rstp_statistics': {'rstp_rx_count': 1}}]}
        before = fingerprint(actual)
        actual['bridges'][0]['rstp_status']['rstp_root_id'] = 'second'
        actual['ports'][0]['rstp_statistics']['rstp_rx_count'] = 100
        self.assertEqual(fingerprint(actual), before)
        actual['ports'][0]['tag'] = 20
        self.assertNotEqual(fingerprint(actual), before)
        actual['controller_available'] = False
        self.assertIsNone(fingerprint(actual))

    def test_ovsdb_parser_refuses_unavailable_malformed_and_oversized_data(self):
        manager = Mock()
        for output in ('', 'not json', '{}', 'x' * 1048577, '{"headings":["wrong"],"data":[]}'):
            manager.crun.return_value = subprocess.CompletedProcess([], 0, output, '')
            self.assertIsNone(table(manager, 'SW1', 'Bridge', 'name'))
        manager.crun.return_value = subprocess.CompletedProcess([], 0, '{"headings":["name","rstp_status"],"data":[["br0",["map",[["rstp_root_id","real"]]]]]}', '')
        self.assertEqual(table(manager, 'SW1', 'Bridge', 'name,rstp_status'), [{'name': 'br0', 'rstp_status': {'rstp_root_id': 'real'}}])

    def test_routing_tree_report_cannot_invent_a_root_or_live_controller(self):
        actual = {'controller_available': False, 'bridges': [{'name': 'br0', 'rstp_enable': True,
                   'rstp_status': {'rstp_root_id': 'a', 'rstp_bridge_id': 'a'}}], 'ports': []}
        report = tree(actual)
        self.assertEqual(report['protocol'], 'unavailable')
        self.assertFalse(report['is_root'])
        self.assertEqual(report['ports'], {})
