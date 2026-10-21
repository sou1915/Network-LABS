"""Conservative multicast policy, drift and bounded actual-probe contracts."""
import copy
import unittest
from unittest.mock import patch

from network_labs.appliances.examples import multicast_lab
from network_labs.appliances.ios import compile_config
from network_labs.appliances.multicast import bridge_options, drift, configure
from network_labs.appliances.multicast_probe import validate_probe
from network_labs.appliances.spec import validate


def links(node):
    from network_labs.appliances.multicast import ROUTER
    options = bridge_options(node['multicast'])
    return [{'ifname': 'br0', 'linkinfo': {'info_data': {k: int(v) for k, v in zip(options[::2], options[1::2])}}}] + [
        {'ifname': p, 'linkinfo': {'info_slave_data': {'multicast_router': ROUTER[s['router']],
                                                    'mcast_flood': s['flood'], 'fast_leave': s['fast_leave']}}}
        for p, s in node['multicast']['ports'].items()]


class MulticastTests(unittest.TestCase):
    def test_policy_rejects_unsupported_scope_querier_without_snooping_and_invalid_flags(self):
        base = multicast_lab('/rootfs')
        for change in (lambda n: n['multicast'].update(snooping=False),
                       lambda n: n['multicast'].update(querier=1),
                       lambda n: n['multicast']['ports']['eth1'].update(flood='off'),
                       lambda n: n['multicast']['ports']['eth1'].update(router=3),
                       lambda n: n['multicast']['ports'].update(eth9={}),
                       lambda n: n['switchports']['eth1'].update(vlan=20),
                       lambda n: n['switchports'].update(eth1={'mode': 'trunk', 'native_vlan': 10, 'allowed': [10]}),
                       lambda n: n.update(startup=[['/bin/true']])):
            spec = copy.deepcopy(base); change(spec['nodes'][0])
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(spec)
        spec = copy.deepcopy(base); spec['nodes'][1]['multicast'] = {}
        with self.assertRaises(ValueError):
            validate(spec)

    def test_cli_validates_whole_block_preserves_original_and_rejects_fake_vendor_features(self):
        spec = multicast_lab('/rootfs'); before = copy.deepcopy(spec)
        result = compile_config(spec, 'SW1', 'conf t\nno ip igmp snooping querier\nno ip igmp snooping\nend')
        self.assertFalse(result['nodes'][0]['multicast']['snooping'])
        for text in ('no ip igmp snooping', 'ip igmp snooping vlan 10', 'ip igmp snooping querier address 192.0.2.1'):
            with self.assertRaises(ValueError):
                compile_config(spec, 'SW1', 'conf t\n' + text + '\nend')
        self.assertEqual(spec, before)

    def test_drift_preserves_unknown_and_ignores_dynamic_mdb_and_timers(self):
        node = multicast_lab('/rootfs')['nodes'][0]; actual = links(node)
        self.assertEqual(drift(node, actual), [])
        actual[0]['linkinfo']['info_data']['mcast_querier_interval'] = 12345
        self.assertEqual(drift(node, actual), [])  # Not declared or managed.
        actual[0]['linkinfo']['info_data'].pop('mcast_querier')
        self.assertTrue(any('mcast_querier' in e for e in drift(node, actual)))
        self.assertTrue(drift(node, []))
        self.assertFalse(drift({'multicast': None}, []))
        actual = links(node); actual[1]['linkinfo']['info_slave_data']['multicast_router'] = 2
        self.assertTrue(any('eth0' in e for e in drift(node, actual)))

    def test_iproute_fast_leave_aliases_preserve_actual_values_and_refuse_conflict(self):
        node = multicast_lab('/rootfs')['nodes'][0]
        node['multicast']['ports']['eth1']['fast_leave'] = True
        actual = links(node)
        for row in actual[1:]:
            info = row['linkinfo']['info_slave_data']
            info['fastleave'] = info.pop('fast_leave')
        self.assertFalse(drift(node, actual))
        actual[2]['linkinfo']['info_slave_data']['fast_leave'] = False
        self.assertTrue(any('eth1' in e for e in drift(node, actual)))

    def test_host_isolation_rejects_virtual_leaks_and_baseline_changes_but_allows_pci_hotplug(self):
        from test_native_integration import unexpected_host_link_changes
        before = {('eth0', 1)}
        hotplug = ('enP44832s1', 10)
        self.assertEqual(unexpected_host_link_changes(before, before | {hotplug}, {'enP44832s1'}),
                         {'removed_or_replaced': set(), 'added_virtual': set()})
        self.assertTrue(unexpected_host_link_changes(before, before | {('nlab0', 2)})['added_virtual'])
        self.assertTrue(unexpected_host_link_changes(before, {('eth0', 2)}, {'eth0'})['removed_or_replaced'])

    def test_unrelated_edits_do_not_reassert_multicast_or_flush_membership(self):
        from unittest.mock import Mock
        node = multicast_lab('/rootfs')['nodes'][0]; manager = Mock()
        configure(manager, 0, node, copy.deepcopy(node), False)
        manager.ns.assert_not_called()
        old = copy.deepcopy(node); node['multicast']['ports']['eth1']['fast_leave'] = True
        configure(manager, 0, node, old, False)
        self.assertFalse(any('flush' in call.args for call in manager.ns.call_args_list))
        self.assertTrue(any('fastleave' in call.args and 'on' in call.args for call in manager.ns.call_args_list))

    def test_probe_bounds_and_multibyte_payload_budget(self):
        self.assertEqual(validate_probe('239.10.10.10', 5000, 1, 100, 'test'), '239.10.10.10')
        for args in [('224.0.0.1', 5000, 1, 1, None), ('232.0.0.1', 5000, 1, 1, None),
                     ('239.1.1.1', 0, 1, 1, None), ('239.1.1.1', 5000, 31, 1, None),
                     ('239.1.1.1', 5000, 1, 101, None), ('239.1.1.1', 5000, 1, 1, ''),
                     ('239.1.1.1', 5000, 1, 1, 'é' * 601)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                validate_probe(*args)

    def test_explain_missing_observations_remain_unknown_and_do_not_certify_delivery(self):
        from network_labs.appliances.diagnostics import explain_node
        node = multicast_lab('/rootfs')['nodes'][0]
        found = explain_node(node, {'links': [], 'addresses': [], 'routes': []})
        finding = next(f for f in found if f['code'] == 'MULTICAST_UNVERIFIED')
        self.assertFalse(finding['evidence']['policy_verified'])
        self.assertTrue(any(f['code'] == 'MULTICAST_MEMBERSHIPS' and f['severity'] == 'unknown' for f in found))
