"""OSPF policy boundaries and conservative observation of real daemon state."""
import copy
import subprocess
import unittest
from unittest.mock import Mock, patch
from network_labs.appliances.examples import ospf_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.ospf import config, observe, dynamic_route, read_cli, enabled_interfaces
from network_labs.appliances.ios import compile_config


class OSPFTests(unittest.TestCase):
    def test_config_has_explicit_area_ports_passive_and_no_redistribution(self):
        node = ospf_lab('/rootfs')['nodes'][2]
        text = config(node)
        self.assertIn('protocol ospf v2 ospf4', text)
        self.assertIn('area 0.0.0.0', text)
        self.assertIn('interface "eth2" { type ptp; cost 10; stub yes;', text)
        self.assertIn('export where source = RTS_OSPF', text)
        self.assertIn('export none', text)
        self.assertNotIn('persist;', text)
        self.assertNotIn('interface "*"', text)

    def test_invalid_policies_rejected(self):
        changes = [dict(router_id=123), dict(router_id='224.0.0.1'), dict(router_id='1.1.1.1; include "evil";'),
                   dict(area=1), dict(hello=0), dict(dead=1), dict(hello=5, dead=4), dict(interfaces={}),
                   dict(interfaces={'eth9': {}}), dict(interfaces={'eth0': {'cost': True}}),
                   dict(interfaces={'eth0': {'passive': 'yes'}}), dict(interfaces={'eth0': {'passive': True}})]
        for change in changes:
            spec = ospf_lab('/rootfs'); spec['nodes'][2]['ospf'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(spec)
        for change in (dict(forwarding=False), dict(shutdown=['eth0']), dict(startup=[['/bin/true']])):
            spec = ospf_lab('/rootfs'); spec['nodes'][2].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(spec)
        spec = ospf_lab('/rootfs'); spec['nodes'][3]['ospf']['router_id'] = '1.1.1.1'
        with self.assertRaisesRegex(ValueError, 'unique'):
            validate(spec)

    def test_unknown_control_state_is_not_empty_neighbors_or_converged(self):
        node = ospf_lab('/rootfs')['nodes'][2]
        manager = Mock()
        manager.crun.side_effect = [subprocess.CompletedProcess([], 0, config(node), '')] + [subprocess.CompletedProcess([], 1, '', 'no socket')] * 4
        result = observe(manager, node)
        self.assertTrue(result['configuration_verified'])
        self.assertIsNone(result['neighbors'])
        self.assertIsNone(result['routes'])
        self.assertIsNone(result['interfaces'])
        self.assertNotIn('converged', result)
        for text in ('8001 syntax error\n', 'x' * 65537):
            manager.crun.side_effect = None
            manager.crun.return_value = subprocess.CompletedProcess([], 0, text, '')
            self.assertIsNone(read_cli(manager, 'R1', 'show status'))

    def test_dynamic_route_exemption_is_scoped_to_ospf_nodes_and_protocol(self):
        node = ospf_lab('/rootfs')['nodes'][2]
        self.assertTrue(dynamic_route(node, {'protocol': 'bird'}))
        self.assertTrue(dynamic_route(node, {'protocol': 192}))
        self.assertFalse(dynamic_route(node, {'protocol': 'static'}))
        self.assertFalse(dynamic_route({}, {'protocol': 'bird'}))

    def test_live_edit_is_refused_before_journal(self):
        from network_labs.appliances.runtime import Manager
        spec = ospf_lab('/rootfs'); manager = Mock()
        manager.read.return_value = {'spec': spec, 'phase': 'running'}
        candidate = copy.deepcopy(spec); candidate['nodes'][2]['interfaces']['eth2'] = '192.0.2.2/24'
        with self.assertRaisesRegex(ValueError, 'service adapter'):
            Manager._configure_network(manager, 'R1', candidate, 'test')
        manager.save.assert_not_called()

    def test_cli_cost_passive_context_and_process_selection(self):
        spec = ospf_lab('/rootfs'); before = copy.deepcopy(spec)
        result = compile_config(spec, 'R1', 'conf t\nrouter ospf 1\npassive-interface eth0\ninterface eth1\nip ospf cost 50\nend')
        self.assertTrue(result['nodes'][2]['ospf']['interfaces']['eth0']['passive'])
        self.assertEqual(result['nodes'][2]['ospf']['interfaces']['eth1']['cost'], 50)
        self.assertEqual(spec, before)
        for command in ('router ospf 2', 'router ospf 1\nrouter-id 4.4.4.4',
                        'interface eth0\nip ospf cost 0', 'interface eth0\nip ospf cost 65536',
                        'router ospf 1\npassive-interface default', 'passive-interface eth0',
                        'interface eth0\nip address 10.0.12.3 255.255.255.252'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                compile_config(spec, 'R1', 'conf t\n' + command + '\nend')

    def test_network_selectors_preserve_overlap_removal_and_interface_options(self):
        spec = ospf_lab('/rootfs')
        def commands(spec, text):
            return compile_config(spec, 'R1', 'conf t\nrouter ospf 1\n' + text + '\nend')
        # Both selectors enable eth0. Removing one must not disable the other.
        a = commands(spec, 'network 10.0.12.1 0.0.0.0 area 0')
        b = commands(a, 'no network 10.0.12.0 0.0.0.3 area 0.0.0.0')
        self.assertIn('eth0', enabled_interfaces(b['nodes'][2]))
        c = commands(b, 'no network 10.0.12.1 0.0.0.0 area 0')
        self.assertNotIn('eth0', enabled_interfaces(c['nodes'][2]))
        self.assertNotIn('interface "eth0"', config(c['nodes'][2]))
        self.assertEqual(c['nodes'][2]['ospf']['interfaces']['eth0'], spec['nodes'][2]['ospf']['interfaces']['eth0'])
        self.assertEqual(commands(c, 'no network 10.0.12.1 0.0.0.0 area 0'), c)
        d = commands(c, 'network 10.0.12.0 0.0.0.3 area 0')
        self.assertEqual(d, spec)

    def test_selectors_reject_invalid_unknown_and_empty_transit(self):
        spec = ospf_lab('/rootfs')
        for command in ('network 10.0.12.0 0.0.1.1 area 0', 'network 203.0.113.0 0.0.0.255 area 0',
                        'network 10.0.12.0 0.0.0.3 area 1',
                        'no network 10.0.12.0 0.0.0.3 area 0\nno network 10.0.13.0 0.0.0.3 area 0'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                compile_config(spec, 'R1', 'conf t\nrouter ospf 1\n' + command + '\nend')
        for networks in ([], ['10.0.12.1/30'], ['203.0.113.0/24'], [123], '10.0.12.0/30'):
            candidate = copy.deepcopy(spec); candidate['nodes'][2]['ospf']['networks'] = networks
            with self.subTest(networks=networks), self.assertRaises(ValueError):
                validate(candidate)

    def test_drift_and_unavailable_or_pending_control_refused_before_journal(self):
        from network_labs.appliances.runtime import Manager, RuntimeFailure
        spec = ospf_lab('/rootfs'); manager = Mock()
        manager.read.return_value = {'spec': spec, 'phase': 'running'}
        candidate = compile_config(spec, 'R1', 'conf t\ninterface eth0\nip ospf cost 100\nend')
        for verified, reply in ((False, '0003 OK\n'), (True, None), (True, '0004-Reconfiguration in progress\n0000 OK\n'),
                                (True, '0003-Running\n0022-Configuration unconfirmed\n0000 OK\n')):
            with self.subTest(verified=verified, reply=reply), \
                 patch('network_labs.appliances.ospf.observe_config', return_value={'configuration_verified': verified}), \
                 patch('network_labs.appliances.ospf._cli', return_value=reply), self.assertRaises(RuntimeFailure):
                Manager._configure_network(manager, 'R1', candidate, 'test')
            manager.save.assert_not_called()

    def test_idempotent_ospf_edit_does_not_reload_or_increment_revision(self):
        from network_labs.appliances.runtime import Manager
        spec = ospf_lab('/rootfs'); manager = Mock()
        manager.read.return_value = {'spec': spec, 'phase': 'running', 'revision': 4}
        with patch('network_labs.appliances.ospf.preflight_change'), patch('network_labs.appliances.ospf.apply_change') as apply:
            result = Manager._configure_network(manager, 'R1', copy.deepcopy(spec), 'test')
        self.assertTrue(result['unchanged']); self.assertEqual(result['revision'], 4)
        manager.save.assert_not_called(); apply.assert_not_called()

    def test_create_delete_process_requires_complete_explicit_policy(self):
        from network_labs.appliances.examples import ospf_cli_lab
        spec = ospf_cli_lab('/rootfs'); before = copy.deepcopy(spec)
        text = 'conf t\nrouter ospf 42\nrouter-id 1.1.1.1\nnetwork 10.0.12.0 0.0.0.3 area 0\nend'
        result = compile_config(spec, 'R1', text)
        self.assertEqual(spec, before)
        self.assertEqual(result['nodes'][2]['ospf']['process_id'], 42)
        self.assertEqual(set(enabled_interfaces(result['nodes'][2])), {'eth0'})
        removed = compile_config(result, 'R1', 'conf t\nno router ospf 42\nend')
        self.assertEqual(removed, spec)
        for value in ('conf t\nrouter ospf 42\nend', 'conf t\nrouter ospf 0\nrouter-id 1.1.1.1\nnetwork 10.0.12.0 0.0.0.3 area 0\nend',
                      text.replace('1.1.1.1', '2.2.2.2').replace('42', '65536')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                compile_config(spec, 'R1', value)
        for value in ('conf t\nno router ospf 1\nend', 'conf t\nrouter ospf 1\nend'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                compile_config(result, 'R1', value)
        with self.assertRaisesRegex(ValueError, 'service adapter'):
            compile_config(spec, 'R1', text.replace('end', 'interface eth2\nip address 192.0.2.2 255.255.255.0\nend'))

    def test_creation_rejects_existing_process_or_control_artifacts_before_journal(self):
        from network_labs.appliances.runtime import Manager, RuntimeFailure
        from network_labs.appliances.examples import ospf_cli_lab
        spec = ospf_cli_lab('/rootfs')
        candidate = compile_config(spec, 'R1', 'conf t\nrouter ospf 1\nrouter-id 1.1.1.1\nnetwork 10.0.12.0 0.0.0.3 area 0\nend')
        for pids, exitcode in ((['1'], 1), (['77'], 1), ([], 0)):
            manager = Mock(); manager.read.return_value = {'spec': spec, 'phase': 'running'}
            manager.crun.return_value = subprocess.CompletedProcess([], exitcode, '', '')
            with self.subTest(pids=pids, exitcode=exitcode), \
                 patch('network_labs.appliances.ospf.processes', return_value=pids), self.assertRaises(RuntimeFailure):
                Manager._configure_network(manager, 'R1', candidate, 'test')
            manager.save.assert_not_called()

    def test_missing_binaries_rejected_before_creation_journal(self):
        from network_labs.appliances.runtime import Manager, RuntimeFailure
        from network_labs.appliances.examples import ospf_cli_lab
        spec = ospf_cli_lab('/rootfs')
        candidate = compile_config(spec, 'R1', 'conf t\nrouter ospf 1\nrouter-id 1.1.1.1\nnetwork 10.0.12.0 0.0.0.3 area 0\nend')
        manager = Mock(); manager.read.return_value = {'spec': spec, 'phase': 'running'}
        manager.crun.side_effect = [subprocess.CompletedProcess([], 1, '', '')] * 2 + [RuntimeFailure('binary unavailable')]
        with patch('network_labs.appliances.ospf.processes', return_value=[]), self.assertRaisesRegex(RuntimeFailure, 'binary unavailable'):
            Manager._configure_network(manager, 'R1', candidate, 'test')
        manager.save.assert_not_called()

    def test_removal_requires_exactly_one_managed_non_init_process(self):
        from network_labs.appliances.runtime import Manager, RuntimeFailure
        spec = ospf_lab('/rootfs'); candidate = compile_config(spec, 'R1', 'conf t\nno router ospf 1\nend')
        for owned, all_pids in ((['1'], ['1']), ([], []), (['8'], ['8', '9'])):
            manager = Mock(); manager.read.return_value = {'spec': spec, 'phase': 'running'}
            with self.subTest(owned=owned, all_pids=all_pids), \
                 patch('network_labs.appliances.ospf.observe_config', return_value={'configuration_verified': True}), \
                 patch('network_labs.appliances.ospf._cli', return_value='0003-Running\n0000 OK\n'), \
                 patch('network_labs.appliances.ospf.processes', side_effect=[owned, all_pids]), self.assertRaises(RuntimeFailure):
                Manager._configure_network(manager, 'R1', candidate, 'test')
            manager.save.assert_not_called()

    def test_broadcast_policy_has_real_election_parameters_and_interface_observation(self):
        from network_labs.appliances.examples import ospf_broadcast_lab
        spec = ospf_broadcast_lab('/rootfs'); node = spec['nodes'][6]
        self.assertIn('type broadcast; cost 10; stub no; hello 1; dead 4; priority 0; wait 4;', config(node))
        self.assertIn('type ptp; cost 10; stub yes;', config(node))
        self.assertEqual(spec['nodes'][2]['multicast']['snooping'], False)
        for options in ({'network_type': 'nbma'}, {'network_type': True}, {'priority': -1}, {'priority': 256}, {'priority': True}):
            candidate = copy.deepcopy(spec); candidate['nodes'][6]['ospf']['interfaces']['eth0'].update(options)
            with self.subTest(options=options), self.assertRaises(ValueError):
                validate(candidate)
        node = ospf_lab('/rootfs'); node['nodes'][2]['ospf']['interfaces']['eth0']['priority'] = 2
        with self.assertRaisesRegex(ValueError, 'requires broadcast'):
            validate(node)

    def test_broadcast_cli_network_and_priority_are_explicit_and_bounded(self):
        spec = ospf_lab('/rootfs')
        candidate = compile_config(spec, 'R1', 'conf t\ninterface eth0\nip ospf network broadcast\nip ospf priority 0\nend')
        self.assertIn('priority 0;', config(candidate['nodes'][2]))
        restored = compile_config(candidate, 'R1', 'conf t\ninterface eth0\nno ip ospf priority\nip ospf network point-to-point\nend')
        self.assertEqual(restored, spec)
        for commands in ('ip ospf priority 0', 'ip ospf priority 256', 'ip ospf network non-broadcast',
                         'ip ospf network broadcast\nip ospf priority 256'):
            with self.subTest(commands=commands), self.assertRaises(ValueError):
                compile_config(spec, 'R1', 'conf t\ninterface eth0\n' + commands + '\nend')

    def test_per_interface_timers_inherit_without_mutating_other_interfaces(self):
        from network_labs.appliances.ospf import interface_timers
        spec = ospf_lab('/rootfs'); before = copy.deepcopy(spec)
        result = compile_config(spec, 'R1', 'conf t\ninterface eth0\nip ospf hello-interval 2\nip ospf dead-interval 8\nend')
        node = result['nodes'][2]
        self.assertEqual(interface_timers(node, node['ospf']['interfaces']['eth0']), (2, 8))
        self.assertEqual(interface_timers(node, node['ospf']['interfaces']['eth1']), (1, 4))
        self.assertEqual(spec, before)
        self.assertIn('interface "eth0" { type ptp; cost 10; stub no; hello 2; dead 8;', config(node))
        # Inheritance stays inheritance: changing a manifest-wide default takes
        # effect on ports without overrides, not on explicitly configured ports.
        result['nodes'][2]['ospf'].update(hello=3, dead=12)
        node = validate(result)['nodes'][2]
        self.assertEqual(interface_timers(node, node['ospf']['interfaces']['eth0']), (2, 8))
        self.assertEqual(interface_timers(node, node['ospf']['interfaces']['eth1']), (3, 12))
        result = compile_config(spec, 'R1', 'conf t\ninterface eth0\nip ospf network broadcast\nip ospf hello-interval 2\nip ospf dead-interval 8\nend')
        self.assertIn('hello 2; dead 8; priority 1; wait 8;', config(result['nodes'][2]))

    def test_interface_timer_validation_is_atomic_and_bounded(self):
        spec = ospf_lab('/rootfs'); before = copy.deepcopy(spec)
        for commands in ('ip ospf hello-interval 0', 'ip ospf hello-interval 61',
                         'ip ospf dead-interval 1', 'ip ospf dead-interval 241',
                         'ip ospf hello-interval 4', 'ip ospf hello-interval 8\nip ospf dead-interval 8',
                         'ip ospf dead-interval minimal hello-multiplier 5', 'no ip ospf hello-interval'):
            with self.subTest(commands=commands), self.assertRaises(ValueError):
                compile_config(spec, 'R1', 'conf t\ninterface eth0\n' + commands + '\nend')
            self.assertEqual(spec, before)
        for options in ({'hello': True}, {'dead': True}, {'hello': '2'}, {'dead': None}):
            candidate = copy.deepcopy(spec); candidate['nodes'][2]['ospf']['interfaces']['eth0'].update(options)
            with self.subTest(options=options), self.assertRaises(ValueError):
                validate(candidate)
        # The whole block is validated once; temporary command order can differ.
        result = compile_config(spec, 'R1', 'conf t\ninterface eth0\nip ospf hello-interval 10\nip ospf dead-interval 40\nend')
        self.assertEqual(result['nodes'][2]['ospf']['interfaces']['eth0']['dead'], 40)
