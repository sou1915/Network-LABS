"""VLAN wire-format comparison and observed, cumulative interface counters."""
import copy
import unittest

from network_labs.appliances.diagnostics import explain, port_counters
from network_labs.appliances.examples import lacp_lab
from network_labs.appliances.vlan_audit import compare_links
from test_native_diagnostics import fake_manager


def observed(entries):
    return {'links': [
        {'ifname': 'br0', 'ifindex': 2, 'linkinfo': {'info_data': {'vlan_filtering': 1, 'vlan_protocol': '802.1Q'}}},
        {'ifname': 'bond1', 'ifindex': 10, 'master': 'br0', 'flags': ['UP', 'LOWER_UP']}],
        'vlans': [{'ifname': 'bond1', 'vlans': entries}], 'addresses': [], 'routes': [], 'forwarding': False}


def snapshots(a=None, b=None):
    normal = [{'vlan': 10}, {'vlan': 20}]
    return {'SW1': observed(normal if a is None else a), 'SW2': observed(normal if b is None else b)}


class VLANAuditTests(unittest.TestCase):
    def test_lacp_collapses_to_one_link_and_uses_observation_not_manifest(self):
        spec = lacp_lab('/rootfs'); actual = snapshots(a=[{'vlan': 10}]); before = copy.deepcopy(actual)
        result, = compare_links(spec, actual)
        self.assertEqual(len(result['declared_physical_links']), 2)
        self.assertEqual(result['endpoints'], [{'node': 'SW1', 'port': 'bond1'}, {'node': 'SW2', 'port': 'bond1'}])
        self.assertEqual(result['status'], 'attention')
        finding, = result['findings']
        self.assertEqual(finding['code'], 'VLAN_TAGGED_NOT_ADMITTED')
        self.assertEqual(finding['evidence']['vlans'], [20])
        self.assertEqual(finding['evidence']['direction'], 'SW2/bond1 → SW1/bond1')
        self.assertEqual(actual, before)
        self.assertEqual(spec['nodes'][4]['switchports']['bond1']['allowed'], [10, 20])

    def test_different_access_vids_reclassify_untagged_without_false_no_common_failure(self):
        actual = snapshots(a=[{'vlan': 10, 'flags': ['PVID', 'Egress Untagged']}],
                           b=[{'vlan': 20, 'flags': ['PVID', 'Egress Untagged']}])
        result, = compare_links(lacp_lab('/rootfs'), actual)
        self.assertEqual({f['code'] for f in result['findings']}, {'VLAN_UNTAGGED_RECLASSIFIED'})
        self.assertEqual(len(result['findings']), 2)
        self.assertEqual(result['findings'][0]['evidence']['target_pvid'], 20)
        self.assertIn('voulue', result['findings'][0]['message'])

    def test_untagged_return_without_pvid_is_detected_despite_same_vid(self):
        actual = snapshots(a=[{'vlan': 10}], b=[{'vlan': 10, 'flags': ['PVID', 'Egress Untagged']}])
        result, = compare_links(lacp_lab('/rootfs'), actual)
        self.assertEqual([f['code'] for f in result['findings']], ['VLAN_UNTAGGED_NO_PVID'])
        self.assertEqual(result['findings'][0]['evidence']['source_vlans'], [10])

    def test_ranges_are_expanded_and_stp_blocking_does_not_invalidate_membership_comparison(self):
        actual = snapshots(a=[{'vlan': 10, 'vlanEnd': 12}], b=[{'vlan': 10}, {'vlan': 11}, {'vlan': 12}])
        actual['SW1']['spanning_tree'] = {'ports': {'bond1': {'state': 'blocking'}}}
        result, = compare_links(lacp_lab('/rootfs'), actual)
        self.assertEqual(result['status'], 'compatible')
        self.assertEqual(result['evidence']['a']['vlans'], [10, 11, 12])
        self.assertEqual(result['evidence']['a']['stp']['state'], 'blocking')
        self.assertIn('livraison restent à vérifier', result['findings'][0]['message'])

    def test_missing_disabled_or_nonstandard_observations_stay_unknown(self):
        cases = []
        actual = snapshots(); del actual['SW2']; cases.append(actual)
        actual = snapshots(); actual['SW1']['vlans'] = []; cases.append(actual)
        actual = snapshots(); actual['SW1']['links'][0]['linkinfo']['info_data']['vlan_filtering'] = 0; cases.append(actual)
        actual = snapshots(); actual['SW1']['links'][0]['linkinfo']['info_data']['vlan_protocol'] = '802.1ad'; cases.append(actual)
        actual = snapshots(); actual['SW1']['links'][1]['master'] = 'other'; cases.append(actual)
        actual = snapshots(a=[{'vlan': 10, 'vlanEnd': 4095}]); cases.append(actual)
        actual = snapshots(a=[{'vlan': 10, 'vlanEnd': 11, 'flags': ['PVID']}]); cases.append(actual)
        actual = snapshots(a=[{'vlan': 10}, {'vlan': 10, 'flags': ['Egress Untagged']}]); cases.append(actual)
        for actual in cases:
            with self.subTest(actual=actual):
                result, = compare_links(lacp_lab('/rootfs'), actual)
                self.assertEqual(result['status'], 'unknown')
                self.assertEqual(result['findings'][0]['code'], 'VLAN_LINK_UNKNOWN')
        result, = compare_links(lacp_lab('/rootfs'), snapshots(a=[]))
        self.assertEqual(result['status'], 'attention')
        self.assertIn('VLAN_NO_MEMBERSHIP', {f['code'] for f in result['findings']})

    def test_full_lab_compares_links_and_node_selection_does_not_read_peers(self):
        manager = fake_manager(lacp_lab('/rootfs')); actual = snapshots()
        manager.inspect.side_effect = lambda name: actual.get(name, {'links': [], 'addresses': [], 'routes': [], 'forwarding': False})
        selected = explain(manager, 'SW1')
        manager.inspect.assert_called_once_with('SW1')
        self.assertIsNone(selected['link_checks_complete'])
        self.assertEqual(selected['link_checks'], [])
        all_nodes = explain(manager)
        self.assertEqual(len(all_nodes['link_checks']), 1)
        self.assertTrue(all_nodes['link_checks_complete'])
        self.assertEqual(all_nodes['packet_delivery'], 'not_tested')

    def test_64bit_counters_remain_cumulative_and_nonzero_drops_have_no_invented_cause(self):
        node = lacp_lab('/rootfs')['nodes'][4]
        stats = {d: {'packets': 2**40, 'bytes': 2**48, 'errors': 0, 'dropped': 0} for d in ('rx', 'tx')}
        stats['rx']['dropped'] = 3
        findings = port_counters(node, {'bond1': {'ifindex': 10, 'stats64': stats, 'stats': {}}})
        data = next(f['evidence'] for f in findings if f['code'] == 'PORT_COUNTERS')
        self.assertEqual(data['counters']['rx_packets'], 2**40)
        self.assertEqual(data['width_bits'], 64); self.assertTrue(data['cumulative'])
        warning = next(f for f in findings if f['code'] == 'PORT_ERRORS_OR_DROPS')
        self.assertEqual(warning['evidence']['counters']['rx_dropped'], 3)
        self.assertIn('ni la cause ni un flux précis', warning['message'])

    def test_partial_32bit_or_missing_counters_are_not_zero_filled(self):
        node = lacp_lab('/rootfs')['nodes'][4]
        findings = port_counters(node, {'eth0': {'stats': {'rx': {'packets': 0}, 'tx': None}}})
        data = next(f['evidence'] for f in findings if f['code'] == 'PORT_COUNTERS')
        self.assertEqual(data['width_bits'], 32)
        self.assertEqual(data['counters']['rx_packets'], 0)
        self.assertIsNone(data['counters']['rx_dropped']); self.assertIsNone(data['counters']['tx_packets'])
        self.assertIn('PORT_COUNTERS_PARTIAL', {f['code'] for f in findings})
        self.assertIn('PORT_COUNTERS_UNAVAILABLE', {f['code'] for f in findings})
        self.assertNotIn('PORT_ERRORS_OR_DROPS', {f['code'] for f in findings})
