"""Bundle safety, configuration and real-state parsing contracts."""
import copy
import unittest
from unittest.mock import patch

from network_labs.appliances.examples import lacp_lab
from network_labs.appliances.ios import compile_config
from network_labs.appliances.lacp import configure, drift, observe, parse_members
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
Active Aggregator Info:
    Aggregator ID: 1
Slave Interface: eth2
MII Status: up
Aggregator ID: 1
details actor lacp pdu:
    port state: 63
details partner lacp pdu:
    port state: 62
Slave Interface: eth3
MII Status: up
Aggregator ID: 1
details actor lacp pdu:
    port state: 7
details partner lacp pdu:
    port state: 5
'''
        result = parse_members(text)
        self.assertTrue(result[0]['collecting_distributing'])
        self.assertFalse(result[1]['collecting_distributing'])
        # Linux can retain synchronized port-state bits after carrier loss.
        down = text.replace('MII Status: up', 'MII Status: down', 1)
        self.assertFalse(parse_members(down)[0]['collecting_distributing'])
        inactive = text.replace('Aggregator ID: 1', 'Aggregator ID: 2', 1)
        self.assertFalse(parse_members(inactive)[0]['collecting_distributing'])
        self.assertFalse(parse_members('Slave Interface: eth2\nMII Status: up\n')[0]['collecting_distributing'])

    def test_parameter_update_takes_only_affected_bond_down_before_netlink(self):
        import json
        import subprocess
        from types import SimpleNamespace
        node = lacp_lab('/rootfs')['nodes'][5]
        old = copy.deepcopy(node); node['port_channels']['bond1']['mode'] = 'active'
        calls = []
        links = [{'ifname': 'bond1', 'ifindex': 5}, {'ifname': 'eth2', 'master': 'bond1'}, {'ifname': 'eth3', 'master': 'bond1'}]
        def ns(index, *args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, json.dumps(links) if '-j' in args else '', '')
        configure(SimpleNamespace(ns=ns), 0, node, old)
        down = calls.index(('ip', 'link', 'set', 'dev', 'bond1', 'down'))
        apply = next(i for i, call in enumerate(calls) if 'lacp_active' in call)
        self.assertLess(down, apply)
        self.assertFalse(any(call[-1:] == ('down',) and 'bond1' not in call for call in calls))

    def test_drift_uses_actual_iproute_ad_option_keys(self):
        node = lacp_lab('/rootfs')['nodes'][4]
        links = [{'ifname': p, 'ifindex': i + 1, 'master': 'bond1' if p in ('eth2', 'eth3') else 'br0'} for i, p in enumerate(node['interfaces'])]
        links += [{'ifname': 'br0', 'ifindex': 20}, {'ifname': 'bond1', 'ifindex': 21, 'master': 'br0',
                   'linkinfo': {'info_kind': 'bond', 'info_data': {'mode': '802.3ad', 'miimon': 100, 'min_links': 1,
                               'ad_lacp_active': 'on', 'ad_lacp_rate': 'fast', 'xmit_hash_policy': 'layer2+3'}}}]
        self.assertEqual(drift(node, {'links': links}), [])
        links[-1]['linkinfo']['info_data']['miimon'] = 200
        self.assertIn('bonding configuration differs', drift(node, {'links': links})[0])

    def test_ready_requires_current_kernel_active_slave_not_stale_port_bits(self):
        import subprocess
        from types import SimpleNamespace
        node = lacp_lab('/rootfs')['nodes'][4]
        proc = ('Active Aggregator Info:\n    Aggregator ID: 1\nSlave Interface: eth2\n'
                'MII Status: up\nAggregator ID: 1\ndetails actor lacp pdu:\n    port state: 63\n'
                'details partner lacp pdu:\n    port state: 63\n')
        links = [{'ifname': 'bond1', 'flags': ['UP', 'LOWER_UP']},
                 {'ifname': 'eth2', 'flags': ['UP', 'LOWER_UP'], 'linkinfo': {'info_slave_data': {
                     'state': 'BACKUP', 'mii_status': 'UP', 'ad_aggregator_id': 1}}}]
        manager = SimpleNamespace(ns=lambda *args: subprocess.CompletedProcess(args, 0, proc, ''))
        actual = observe(manager, 0, node, links)['bond1']
        self.assertFalse(actual['ready'])
        self.assertTrue(actual['carrier_without_ready_lacp'])
        links[1]['linkinfo']['info_slave_data']['state'] = 'ACTIVE'
        actual = observe(manager, 0, node, links)['bond1']
        self.assertTrue(actual['ready'])
        self.assertFalse(actual['carrier_without_ready_lacp'])
        # Both peers can default after LACP expiry while physical carrier is up.
        proc = proc.replace('port state: 63', 'port state: 0')
        actual = observe(manager, 0, node, links)['bond1']
        self.assertFalse(actual['ready'])
        self.assertTrue(actual['carrier_without_ready_lacp'])
        links[0]['flags'] = ['UP']
        self.assertFalse(observe(manager, 0, node, links)['bond1']['carrier_without_ready_lacp'])

    def test_invalid_configuration_never_applied(self):
        manager = Manager('lacp-lan'); manager.state = {'spec': lacp_lab('/rootfs'), 'phase': 'running'}
        with patch.object(manager, 'save'), patch('network_labs.appliances.lan.configure') as apply:
            with self.assertRaises(ValueError):
                manager.configure_ios('SW1', 'conf t\ninterface po1\nport-channel min-links 3\nend')
            apply.assert_not_called()
