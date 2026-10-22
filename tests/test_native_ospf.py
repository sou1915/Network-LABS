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
        manager.crun.side_effect = [subprocess.CompletedProcess([], 0, config(node), '')] + [subprocess.CompletedProcess([], 1, '', 'no socket')] * 3
        result = observe(manager, node)
        self.assertTrue(result['configuration_verified'])
        self.assertIsNone(result['neighbors'])
        self.assertIsNone(result['routes'])
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
