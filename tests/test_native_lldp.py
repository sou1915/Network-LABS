"""LLDP is received protocol evidence; declared links must never become neighbors."""
import copy
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.examples import lldp_lab
from network_labs.appliances.lldp import observe, config, global_fingerprint, port_status, read_cli, rootfs_assets
from network_labs.appliances.runtime import oci_config
from network_labs.appliances.spec import validate


class LLDPTests(unittest.TestCase):
    def test_strict_physical_access_scope_and_bounded_timers(self):
        for policy in ({}, {'ports': []}, {'ports': ['eth0', 'eth0']}, {'ports': ['br0']},
                       {'ports': ['eth0'], 'tx_interval': True}, {'ports': ['eth0'], 'tx_hold': 1},
                       {'ports': ['eth0'], 'tx_interval': 61}, {'ports': ['eth0'], 'cdp': True}):
            spec = lldp_lab('/rootfs'); spec['nodes'][0]['lldp'] = policy
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                validate(spec)
        spec = lldp_lab('/rootfs'); spec['nodes'][2]['switchports']['eth1'] = {'mode': 'trunk', 'native_vlan': 10, 'allowed': [10]}
        with self.assertRaisesRegex(ValueError, 'access'):
            validate(spec)
        spec = lldp_lab('/rootfs'); spec['nodes'][0]['startup'] = [['/bin/true']]
        with self.assertRaisesRegex(ValueError, 'startup'):
            validate(spec)

    def test_chroot_capability_only_applies_to_explicit_lldp_node(self):
        spec = lldp_lab('/rootfs'); node = spec['nodes'][0]
        self.assertIn('CAP_SYS_CHROOT', oci_config(spec, node, 0, '/bundle/rootfs')['process']['capabilities']['effective'])
        node['lldp'] = None
        self.assertNotIn('CAP_SYS_CHROOT', oci_config(spec, node, 0, '/bundle/rootfs')['process']['capabilities']['effective'])

    def test_neighbors_unavailable_stays_unknown_even_with_a_declared_topology(self):
        node = lldp_lab('/rootfs')['nodes'][0]
        manager = Mock(); manager.state = {'spec': lldp_lab('/rootfs')}
        manager.crun.return_value = subprocess.CompletedProcess([], 0, config(node), '')
        with patch('network_labs.appliances.lldp.read_cli', return_value=None):
            actual = observe(manager, node)
        self.assertIsNone(actual['neighbors'])
        self.assertFalse(actual['policy_verified'])
        self.assertTrue(actual['configuration_verified'])

    def test_current_global_configuration_and_port_status_detect_runtime_cli_drift(self):
        node = lldp_lab('/rootfs')['nodes'][0]
        manager = Mock(); expected = {'configuration': [{'config': [{'tx-delay': '2'}]}]}
        manager.state = {'lldp_baselines': {'PC1': {'global': global_fingerprint(expected), 'port_status': {'eth0': 'RX and TX'}}}}
        manager.crun.return_value = subprocess.CompletedProcess([], 0, config(node), '')
        for glob, statuses, verified in ((expected, {'lldp.eth0.status': 'RX and TX'}, True),
                                        ({'configuration': 'changed'}, {'lldp.eth0.status': 'RX and TX'}, False),
                                        (expected, {'lldp.eth0.status': 'disabled'}, False),
                                        (expected, None, False)):
            with self.subTest(glob=glob, statuses=statuses), patch('network_labs.appliances.lldp.read_cli', side_effect=[glob, statuses, {'lldp': []}]):
                self.assertEqual(observe(manager, node)['policy_verified'], verified)
        self.assertEqual(port_status({'lldp.eth0.status': 'RX only', 'lldp.eth0.port.descr': 'host'}), {'eth0': 'RX only'})

    def test_bounded_cli_reads_reject_malformed_oversized_empty_and_timeout(self):
        manager = Mock()
        for value in ('', 'not json', '[]', '{}', 'x' * 1048577):
            manager.crun.return_value = subprocess.CompletedProcess([], 0, value, '')
            self.assertIsNone(read_cli(manager, 'PC1', 'neighbors details'))
        manager.crun.side_effect = subprocess.TimeoutExpired('crun', 5)
        self.assertIsNone(read_cli(manager, 'PC1', 'configuration'))
        with self.assertRaises(ValueError):
            read_cli(manager, 'PC1', 'configuration; dangerous')

    def test_rootfs_builder_refuses_unknown_privilege_separation_profile(self):
        for profile in ('not a daemon', 'Privilege separation user: root\nPrivilege separation group: root\nPrivilege separation chroot: /\n'):
            with patch('network_labs.appliances.lldp.subprocess.run', return_value=subprocess.CompletedProcess([], 0, profile, '')):
                with self.assertRaisesRegex(ValueError, 'profile'):
                    rootfs_assets('/trusted/lldpd', '/trusted/lldpcli')

    def test_ios_service_node_edits_are_rejected_without_partial_mutation(self):
        from network_labs.appliances.ios import compile_config
        spec = lldp_lab('/rootfs'); spec['nodes'][2]['dialect'] = 'ios-basic'
        original = copy.deepcopy(spec)
        with self.assertRaisesRegex(ValueError, 'LLDP'):
            compile_config(spec, 'SW1', 'conf t\ninterface eth0\nshutdown\nend')
        self.assertEqual(spec, original)
