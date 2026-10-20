"""Bundle safety, configuration and real-state parsing contracts."""
import copy
import unittest
from unittest.mock import patch

from network_labs.appliances.examples import lacp_lab
from network_labs.appliances.ios import compile_config
from network_labs.appliances.lacp import parse_members
from network_labs.appliances.runtime import Manager
from network_labs.appliances.spec import validate


class LACPTests(unittest.TestCase):
    def test_two_physical_links_are_one_logical_edge(self):
        spec = lacp_lab('/rootfs')
        self.assertEqual(len(spec['nodes']), 6)
        self.assertEqual(len(spec['links']), 6)
        self.assertEqual(validate(spec), spec)
        self.assertNotIn('eth2', spec['nodes'][4]['switchports'])
        self.assertIn('bond1', spec['nodes'][4]['switchports'])

    def test_unsafe_or_unpaired_bundles_rejected(self):
        edits = [lambda s: s['nodes'][4]['port_channels']['bond1'].update(members=['eth2', 'eth2']),
                 lambda s: s['nodes'][4]['port_channels']['bond1'].update(mode='on'),
                 lambda s: s['nodes'][4]['port_channels']['bond1'].update(mode='passive'),
                 lambda s: s['nodes'][4]['port_channels']['bond1'].update(min_links=3),
                 lambda s: s['links'].pop(),
                 lambda s: s['nodes'][4]['switchports'].update(eth2={'mode': 'access', 'vlan': 10}),
                 lambda s: s['nodes'][5]['port_channels'].clear()]
        for edit in edits:
            spec = lacp_lab('/rootfs'); edit(spec)
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                validate(spec)
        # Extra unaggregated parallel links still form a forbidden L2 cycle.
        spec = lacp_lab('/rootfs')
        for n in spec['nodes'][4:]:
            n['interfaces']['eth4'] = ''
        spec['links'].append([['SW1', 'eth4'], ['SW2', 'eth4']])
        with self.assertRaisesRegex(ValueError, 'loop'):
            validate(spec)

    def test_partial_cli_logical_port_policy_and_existing_member_mode(self):
        spec = lacp_lab('/rootfs'); before = copy.deepcopy(spec)
        changed = compile_config(spec, 'SW1', 'conf t\ninterface port-channel1\nswitchport trunk allowed vlan 10\nport-channel min-links 2\nshutdown\nend')
        self.assertEqual(changed['nodes'][4]['switchports']['bond1']['allowed'], [10])
        self.assertEqual(changed['nodes'][4]['port_channels']['bond1']['min_links'], 2)
        self.assertIn('bond1', changed['nodes'][4]['shutdown'])
        active = compile_config(spec, 'SW2', 'conf t\ninterface fa0/3\nchannel-group 1 mode active\nend')
        self.assertEqual(active['nodes'][5]['port_channels']['bond1']['mode'], 'active')
        self.assertEqual(spec, before)
        with self.assertRaisesRegex(ValueError, 'logical port-channel'):
            compile_config(spec, 'SW1', 'conf t\ninterface fa0/3\nswitchport mode trunk\nend')
        with self.assertRaisesRegex(ValueError, 'passive/passive'):
            compile_config(spec, 'SW1', 'conf t\ninterface fa0/3\nchannel-group 1 mode passive\nend')

    def test_parser_requires_actor_and_partner_collecting_distributing(self):
        text = '''Ethernet Channel Bonding Driver: v6
Slave Interface: eth2
MII Status: up
details actor lacp pdu:
    port state: 63
details partner lacp pdu:
    port state: 62
Slave Interface: eth3
MII Status: up
details actor lacp pdu:
    port state: 7
details partner lacp pdu:
    port state: 5
'''
        result = parse_members(text)
        self.assertTrue(result[0]['collecting_distributing'])
        self.assertFalse(result[1]['collecting_distributing'])
        self.assertFalse(parse_members('Slave Interface: eth2\nMII Status: up\n')[0]['collecting_distributing'])

    def test_invalid_configuration_never_applied(self):
        manager = Manager('lacp-lan'); manager.state = {'spec': lacp_lab('/rootfs'), 'phase': 'running'}
        with patch.object(manager, 'save'), patch('network_labs.appliances.lan.configure') as apply:
            with self.assertRaises(ValueError):
                manager.configure_ios('SW1', 'conf t\ninterface po1\nport-channel min-links 3\nend')
            apply.assert_not_called()
