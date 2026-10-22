"""OSPF policy boundaries and conservative observation of real daemon state."""
import copy
import subprocess
import unittest
from unittest.mock import Mock
from network_labs.appliances.examples import ospf_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.ospf import config, observe, dynamic_route, read_cli


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
        with self.assertRaisesRegex(ValueError, 'service adapter'):
            Manager._configure_network(manager, 'R1', copy.deepcopy(spec), 'test')
        manager.save.assert_not_called()
