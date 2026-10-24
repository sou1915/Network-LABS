"""LLDP is received protocol evidence; declared links must never become neighbors."""
import copy
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.examples import lldp_lab, ospf_dhcp_lldp_lab
from network_labs.appliances.lldp import observe, config, global_fingerprint, port_status, read_cli, rootfs_assets
from network_labs.appliances.runtime import oci_config
from network_labs.appliances.spec import validate


class LLDPTests(unittest.TestCase):
    def test_strict_physical_scope_and_bounded_timers(self):
        for policy in ({}, {'ports': []}, {'ports': ['eth0', 'eth0']}, {'ports': ['br0']},
                       {'ports': ['eth0'], 'tx_interval': True}, {'ports': ['eth0'], 'tx_hold': 1},
                       {'ports': ['eth0'], 'tx_interval': 61}, {'ports': ['eth0'], 'cdp': True}):
            spec = lldp_lab('/rootfs'); spec['nodes'][0]['lldp'] = policy
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                validate(spec)
        spec = lldp_lab('/rootfs'); spec['nodes'][2]['switchports']['eth1'] = {'mode': 'trunk', 'native_vlan': 10, 'allowed': [10]}
        self.assertEqual(validate(spec)['nodes'][2]['lldp']['ports'], ['eth0', 'eth1'])
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
        self.assertEqual(port_status({'lldp.eth0.status': 'RX only', 'lldp.eth0.port.descr': 'host'}, ['eth0']), {'eth0': 'RX only'})

    def test_dotted_physical_names_remain_exact_and_do_not_select_nested_status_keys(self):
        self.assertEqual(port_status({'lldp.lan.0.status': 'RX and TX',
                                      'lldp.lan.0.port.status': 'unrelated',
                                      'lldp.other.status': 'disabled'}, ['lan.0']),
                         {'lan.0': 'RX and TX'})

    def test_bounded_cli_reads_reject_malformed_oversized_empty_and_timeout(self):
        manager = Mock()
        for value in ('', 'not json', '[]', '{}', 'x' * 1048577):
            manager.crun.return_value = subprocess.CompletedProcess([], 0, value, '')
            self.assertIsNone(read_cli(manager, 'PC1', 'neighbors details'))
        manager.crun.side_effect = subprocess.TimeoutExpired('crun', 5)
        self.assertIsNone(read_cli(manager, 'PC1', 'configuration'))
        with self.assertRaises(ValueError):
            read_cli(manager, 'PC1', 'configuration; dangerous')

    def test_rootfs_uses_verbose_identity_not_bare_numeric_version(self):
        profile = 'lldpd 1.0.17\nPrivilege separation user: _lldpd\nPrivilege separation group: _lldpd\nPrivilege separation chroot: /run/lldpd\n'
        with patch('network_labs.appliances.lldp.subprocess.run', return_value=subprocess.CompletedProcess([], 0, profile, '')), \
             patch('network_labs.appliances.dns_rootfs.assets', return_value=[]) as asset:
            rootfs_assets('/trusted/lldpd', '/trusted/lldpcli')
        self.assertEqual([call.kwargs['version_args'] for call in asset.call_args_list], [('-vv',), ('-vv',)])

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

    def test_composition_selects_only_changed_service_and_preserves_lldp(self):
        from network_labs.appliances.ios import compile_config
        from network_labs.appliances.service_adapters import adapters
        spec = ospf_dhcp_lldp_lab('/rootfs'); original = copy.deepcopy(spec)
        for command, module in (('interface vlan20\nip ospf cost 55', 'ospf'),
                                ('interface vlan10\nno ip helper-address 198.18.0.3', 'dhcp_relay')):
            candidate = compile_config(spec, 'SW1', 'conf t\n' + command + '\nend')
            selected = adapters(candidate['nodes'][1], spec['nodes'][1])
            self.assertEqual([m.__name__.split('.')[-1] for m in selected], [module])
            self.assertEqual(candidate['nodes'][1]['lldp'], spec['nodes'][1]['lldp'])
        self.assertEqual(spec, original)
        # LLDP follows physical ports, while OSPF follows numbered SVIs.
        spec['nodes'][1]['lldp']['ports'] = ['vlan20']
        with self.assertRaisesRegex(ValueError, 'physical'):
            validate(spec)

    def test_lldp_policy_and_network_edits_are_centrally_refused_before_journal(self):
        from network_labs.appliances.runtime import Manager
        for base, index, field, value in (
                (ospf_dhcp_lldp_lab('/rootfs'), 1, 'lldp', {'ports': ['eth1'], 'tx_interval': 7, 'tx_hold': 3}),
                (ospf_dhcp_lldp_lab('/rootfs'), 1, 'shutdown', ['eth1']),
                (lldp_lab('/rootfs'), 2, 'shutdown', ['eth1']),
                (lldp_lab('/rootfs'), 2, 'lldp', None)):
            manager = Mock(); state = {'spec': base, 'phase': 'running'}
            manager.read.return_value = state
            candidate = copy.deepcopy(base); candidate['nodes'][index][field] = value
            with self.subTest(field=field, name=base['name']), patch('network_labs.appliances.lan.configure') as apply:
                with self.assertRaises(ValueError):
                    Manager._configure_network(manager, base['nodes'][index]['name'], candidate, 'test')
                manager.save.assert_not_called(); apply.assert_not_called()
            self.assertEqual(state, {'spec': base, 'phase': 'running'})

    def test_static_lldp_noop_does_not_reapply_network(self):
        from network_labs.appliances.runtime import Manager
        spec = lldp_lab('/rootfs'); manager = Mock()
        manager.read.return_value = {'spec': spec, 'phase': 'running', 'revision': 3}
        with patch('network_labs.appliances.lan.configure') as apply:
            result = Manager._configure_network(manager, 'SW1', copy.deepcopy(spec), 'test')
        self.assertTrue(result['unchanged']); self.assertEqual(result['revision'], 3)
        manager.save.assert_not_called(); apply.assert_not_called()

    def test_composed_cli_example_and_mutually_exclusive_profiles(self):
        import contextlib
        import io
        from network_labs.appliances.__main__ import main
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['example', '--ospf-dhcp-lldp', '--rootfs', '/rootfs']), 0)
        spec = json.loads(output.getvalue())
        self.assertEqual(spec['name'], 'ospf-dhcp-lldp-lan')
        self.assertEqual([n['name'] for n in spec['nodes'] if n.get('lldp')], ['SW1', 'R1', 'SW2'])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['example', '--ospf-dhcp-lldp', '--lldp', '--rootfs', '/rootfs']), 1)
