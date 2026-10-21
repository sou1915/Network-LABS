"""Multiple relayed IPv4 pools: strict policy, scoped options and CLI edits."""
import copy
import unittest
from network_labs.appliances.examples import dhcp_multi_lab, dhcp_relay_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.ios import compile_config
from network_labs.appliances.dhcp_multi import server_config
from network_labs.appliances.dhcp_relay import server_config as relay_config, rules


class DHCPMultiTests(unittest.TestCase):
    def test_ranges_and_options_are_scoped_per_network(self):
        spec = dhcp_multi_lab('/rootfs')
        config = server_config(spec['nodes'][3])
        for line in ('port=0', 'dhcp-range=set:pool0,192.0.2.100,192.0.2.110,255.255.255.0,3600s',
                     'dhcp-option=tag:pool0,option:router,192.0.2.1',
                     'dhcp-option=tag:pool1,option:router,198.18.0.1',
                     'dhcp-option=tag:pool0,option:dns-server,192.0.2.53',
                     'dhcp-option=tag:pool1,option:dns-server,198.18.0.53'):
            self.assertIn(line + '\n', config)
        self.assertIn('dhcp-relay=198.18.0.1,198.51.100.10,vlan30', relay_config(spec['nodes'][2]))
        spec['nodes'][3]['dhcp_pools']['pools'][0].update(router='', dns=[])
        config = server_config(validate(spec)['nodes'][3])
        self.assertIn('dhcp-option=tag:pool0,option:router\n', config)
        self.assertIn('dhcp-option=tag:pool0,option:dns-server\n', config)

    def test_bad_or_overlapping_pools_and_ambiguous_reservations_rejected(self):
        changes = [dict(network='192.0.2.0/25'), dict(network='198.51.100.0/24'),
                   dict(network=None), dict(start=123), dict(router=123), dict(dns=[123]),
                   dict(dns=['127.0.0.1']), dict(end='198.18.1.1'), dict(lease_seconds=True),
                   dict(reservations=[{'mac': '02:00:00:00:20:01', 'address': '198.18.0.105'}])]
        for change in changes:
            spec = dhcp_multi_lab('/rootfs'); spec['nodes'][3]['dhcp_pools']['pools'][1].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(spec)
        spec = dhcp_multi_lab('/rootfs')
        spec['nodes'][3]['dhcp_pools']['pools'].append(copy.deepcopy(spec['nodes'][3]['dhcp_pools']['pools'][0]))
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            validate(spec)

    def test_policy_bounds_and_service_conflicts(self):
        for pools in ([], 'bad', [{}] * 17):
            spec = dhcp_multi_lab('/rootfs'); spec['nodes'][3]['dhcp_pools']['pools'] = pools
            with self.subTest(pools=pools), self.assertRaises(ValueError):
                validate(spec)
        spec = dhcp_multi_lab('/rootfs'); spec['nodes'][3]['dhcp_server'] = dhcp_relay_lab('/rootfs')['nodes'][3]['dhcp_server']
        with self.assertRaisesRegex(ValueError, 'share'):
            validate(spec)
        spec = dhcp_multi_lab('/rootfs'); spec['nodes'][3]['shutdown'] = ['eth0']
        with self.assertRaisesRegex(ValueError, 'UP numbered'):
            validate(spec)

    def test_multiple_helpers_remove_only_selected_vlan_and_roundtrip(self):
        spec = dhcp_multi_lab('/rootfs')
        removed = compile_config(spec, 'SW1', 'conf t\ninterface vlan10\nno ip helper-address 198.51.100.10\nend')
        self.assertEqual([r['interface'] for r in rules(removed['nodes'][2])], ['vlan20'])
        added = compile_config(removed, 'SW1', 'conf t\ninterface vlan10\nip helper-address 198.51.100.10\nend')
        self.assertEqual(added, spec)
        self.assertEqual(len(rules(spec['nodes'][2])), 2)

    def test_duplicate_client_or_client_upstream_overlap_rejected(self):
        spec = dhcp_multi_lab('/rootfs')
        spec['nodes'][2]['dhcp_relay'].append(copy.deepcopy(spec['nodes'][2]['dhcp_relay'][0]))
        with self.assertRaisesRegex(ValueError, 'one helper'):
            validate(spec)
        for policy in ([], [{}] * 33):
            spec = dhcp_multi_lab('/rootfs'); spec['nodes'][2]['dhcp_relay'] = policy
            with self.assertRaisesRegex(ValueError, '1..32'):
                validate(spec)

    def test_pool_server_network_edits_refused_before_journal(self):
        from unittest.mock import Mock
        from network_labs.appliances.runtime import Manager
        spec = dhcp_multi_lab('/rootfs'); state = {'spec': spec, 'phase': 'running'}
        manager = Mock(); manager.read.return_value = state
        with self.assertRaisesRegex(ValueError, 'service adapter'):
            Manager._configure_network(manager, 'DHCP1', copy.deepcopy(spec), 'test')
        manager.save.assert_not_called()
