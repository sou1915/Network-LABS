"""Observed facts must not turn into claims about events or packet success."""
import copy
from contextlib import nullcontext
import io
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.__main__ import main
from network_labs.appliances.diagnostics import explain, explain_node, render
from network_labs.appliances.examples import campus, firewall_lab, lacp_lab, stp_lab
from network_labs.appliances.runtime import RuntimeFailure


def snapshot(node):
    return {'links': [{'ifname': p, 'flags': ['UP', 'LOWER_UP']} for p in node['interfaces']],
            'addresses': [], 'routes': [], 'forwarding': node['forwarding']}


def fake_manager(spec):
    state = {'phase': 'running', 'revision': 3, 'spec': spec}
    def crun(*args, **kwargs):
        assert args[0] == 'state' and kwargs == {'check': False}, 'Diagnostic attempted a write or exec'
        return subprocess.CompletedProcess(args, 0, '{"status":"running"}', '')
    byname = {n['name']: n for n in spec['nodes']}
    return SimpleNamespace(name=spec['name'], read=lambda: state, crun=Mock(side_effect=crun),
                           inspect=Mock(side_effect=lambda name: snapshot(byname[name])))


class NativeDiagnosticTests(unittest.TestCase):
    def test_blocking_is_explained_as_observed_state_not_failed_connectivity(self):
        node = next(n for n in stp_lab('/rootfs')['nodes'] if n['name'] == 'SW3')
        actual = snapshot(node)
        actual['spanning_tree'] = {'protocol': 'stp', 'bridge_id': '3000.001122334455',
                                  'root_id': '1000.aabbccddeeff', 'is_root': False, 'root_port': 'eth2',
                                  'root_path_cost': 100, 'ports': {'eth2': {'state': 'forwarding'}, 'eth3': {'state': 'blocking'}}}
        original = copy.deepcopy(actual)
        findings = explain_node(node, actual)
        self.assertEqual(actual, original)
        self.assertEqual({f['code'] for f in findings}, {'STP_ROOT_PATH', 'STP_BLOCKING', 'STP_FORWARDING'})
        blocked = next(f for f in findings if f['code'] == 'STP_BLOCKING')
        self.assertEqual(blocked['severity'], 'info')
        self.assertEqual(blocked['evidence']['state'], 'blocking')

    def test_guard_disabled_with_carrier_is_correlated_not_a_fabricated_event(self):
        node = next(n for n in stp_lab('/rootfs')['nodes'] if n['name'] == 'SW3')
        actual = snapshot(node)
        actual['spanning_tree'] = {'protocol': 'stp', 'bridge_id': '3000.001122334455',
                                  'root_id': '3000.001122334455', 'is_root': True, 'root_port': None,
                                  'root_path_cost': 0, 'ports': {
                                      'eth2': {'state': 'disabled', 'bpdu_guard': True},
                                      'eth3': {'state': 'listening', 'root_guard': True}}}
        findings = explain_node(node, actual)
        self.assertIn('STP_DISABLED_WITH_BPDU_GUARD', {f['code'] for f in findings})
        self.assertIn('STP_ROOT_GUARD_LISTENING', {f['code'] for f in findings})
        actual['links'][2]['flags'] = []
        findings = explain_node(node, actual)
        self.assertNotIn('STP_DISABLED_WITH_BPDU_GUARD', {f['code'] for f in findings})
        self.assertIn('LINK_ADMIN_DOWN', {f['code'] for f in findings})

    def test_lacp_degradation_comes_from_negotiation_not_configured_member_count(self):
        node = lacp_lab('/rootfs')['nodes'][4]
        actual = snapshot(node)
        actual['links'].append({'ifname': 'bond1', 'flags': ['UP', 'LOWER_UP']})
        actual['port_channels'] = {'bond1': {'ready': True, 'negotiated_members': ['eth3'], 'members': []}}
        self.assertIn('LACP_DEGRADED', {f['code'] for f in explain_node(node, actual)})
        actual['port_channels']['bond1']['ready'] = False
        self.assertIn('LACP_NOT_READY', {f['code'] for f in explain_node(node, actual)})
        actual['port_channels']['bond1'].update(ready=True, negotiated_members=['eth2', 'eth3'])
        self.assertIn('LACP_READY', {f['code'] for f in explain_node(node, actual)})

    def test_actual_vlan_ranges_and_dhcp_addresses_do_not_claim_lease_origin(self):
        node = campus('/rootfs')['nodes'][0]
        actual = snapshot(node)
        findings = explain_node(node, actual)
        self.assertIn('DHCP_ADDRESS_MISSING', {f['code'] for f in findings})
        actual['addresses'] = [{'ifname': 'eth0', 'addr_info': [
            {'family': 'inet', 'scope': 'global', 'local': '10.10.10.101', 'prefixlen': 24}]}]
        address = next(f for f in explain_node(node, actual) if f['code'] == 'DHCP_ADDRESS_PRESENT')
        self.assertIn('ne sont pas vérifiés', address['message'])
        switch = campus('/rootfs')['nodes'][4]
        actual = snapshot(switch)
        actual['vlans'] = [{'ifname': 'eth2', 'vlans': [{'vlan': 10, 'vlanEnd': 20, 'flags': ['PVID', 'Egress Untagged']}]}]
        found = next(f for f in explain_node(switch, actual) if f['code'] == 'VLAN_MEMBERSHIP')
        self.assertIn('10-20 PVID untagged', found['message'])

    def test_firewall_reports_actual_policy_and_cumulative_counters(self):
        node = next(n for n in firewall_lab('/rootfs')['nodes'] if n['name'] == 'FW1')
        actual = snapshot(node)
        actual['firewall'] = {'nftables': [
            {'chain': {'family': 'ip', 'table': 'network_labs', 'name': 'forward', 'hook': 'forward', 'policy': 'drop'}},
            {'rule': {'family': 'ip', 'table': 'network_labs', 'chain': 'forward', 'comment': 'rule:http',
                      'expr': [{'counter': {'packets': 12, 'bytes': 600}}, {'accept': None}]}},
            {'rule': {'family': 'ip', 'table': 'unrelated', 'chain': 'other', 'expr': [{'counter': {'packets': 99}}]}}]}
        found = next(f for f in explain_node(node, actual) if f['code'] == 'FIREWALL_SNAPSHOT')
        self.assertEqual(found['evidence']['chains'][0]['policy'], 'drop')
        self.assertEqual(len(found['evidence']['counters']), 1)
        self.assertEqual(found['evidence']['counters'][0]['packets'], 12)
        self.assertIn('cumulatifs', found['message'])

    def test_unavailable_node_does_not_hide_other_nodes_or_mutate_state(self):
        manager = fake_manager(stp_lab('/rootfs')); state = copy.deepcopy(manager.read())
        manager.inspect.side_effect = lambda name: (_ for _ in ()).throw(RuntimeFailure('namespace unavailable')) if name == 'PC1' else snapshot(manager.read()['spec']['nodes'][1])
        report = explain(manager)
        self.assertFalse(report['observation_complete'])
        self.assertFalse(report['nodes'][0]['observations_available'])
        self.assertTrue(report['nodes'][1]['observations_available'])
        self.assertEqual(report['nodes'][0]['findings'][0]['code'], 'OBSERVATION_FAILED')
        self.assertEqual(report['packet_delivery'], 'not_tested')
        self.assertEqual(manager.read(), state)
        self.assertIn('aucun paquet', render(report))

    def test_stopped_vm_unknown_and_dead_containers_are_not_ready(self):
        manager = fake_manager(stp_lab('/rootfs'))
        with self.assertRaises(ValueError):
            explain(manager, 'MISSING')
        manager.crun.assert_not_called()
        manager.read()['phase'] = 'failed'
        self.assertFalse(explain(manager)['observation_complete'])
        manager.inspect.assert_not_called(); manager.crun.assert_not_called()
        manager.read()['phase'] = 'running'
        manager.read()['spec']['nodes'][0]['runtime'] = 'firecracker'
        self.assertFalse(explain(manager, 'PC1')['observation_complete'])
        manager.read()['spec']['nodes'][0]['runtime'] = 'oci'
        manager.crun.side_effect = None
        for code, stdout in ((0, '{"status":"stopped"}'), (1, ''), (0, 'invalid json')):
            manager.crun.return_value = subprocess.CompletedProcess([], code, stdout, 'unavailable')
            self.assertFalse(explain(manager, 'PC1')['observation_complete'])
        manager.inspect.assert_not_called()

    def test_cli_text_and_json_use_the_same_passive_report(self):
        manager = fake_manager(stp_lab('/rootfs'))
        manager.locked = lambda: nullcontext(manager)
        with patch('network_labs.appliances.__main__.Manager', return_value=manager), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['explain', manager.name, 'PC1', '--json']), 0)
            report = json.loads(output.getvalue())
            self.assertTrue(report['passive']); self.assertEqual(len(report['nodes']), 1)
            self.assertNotIn('packet_test_passed', report)
            output.seek(0); output.truncate()
            self.assertEqual(main(['explain', manager.name, 'PC1']), 0)
            self.assertIn('PC1 (host, oci)', output.getvalue())
