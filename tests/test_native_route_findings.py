"""Human routing findings must distinguish observations from flow verdicts."""
import copy
import unittest

from network_labs.appliances.route_lookup import lookup, render
from network_labs.appliances.route_findings import findings, ipv4_labels
from network_labs.appliances.diagnostics import explain_node
from test_native_route_lookup import manager_for


class RouteFindingTests(unittest.TestCase):
    def report(self):
        return lookup(manager_for(), 'SW1', '203.0.113.10', source='192.0.2.10', ingress='vlan10')

    def codes(self, report):
        return {row['code']: row for row in findings(report)}

    def test_visible_numeric_settings_include_zero_and_unknown_without_generic_only_text(self):
        report = self.report(); settings = report['ipv4_settings']
        settings['interfaces']['vlan10'].update(effective_rp_filter=0, forwarding=0)
        settings['interfaces']['vlan20'].update(effective_rp_filter=None, forwarding=None)
        rpf, forwarding = ipv4_labels(settings)
        self.assertIn('vlan10=off(0)', rpf); self.assertIn('vlan20=?(?)', rpf)
        self.assertIn('vlan10=off', forwarding); self.assertIn('vlan20=?', forwarding)
        node = manager_for().read()['spec']['nodes'][1]
        actual = {'links': [], 'routes': [], 'addresses': [], 'forwarding': True, 'ipv4_settings': settings}
        messages = {row['code']: row for row in explain_node(node, actual)}
        self.assertIn('all=2', messages['IPV4_SOURCE_VALIDATION']['message'])
        self.assertIn('vlan10=off(0)', messages['IPV4_SOURCE_VALIDATION']['message'])
        self.assertIn('vlan20=?', messages['IPV4_INGRESS_FORWARDING']['message'])
        self.assertEqual(messages['IPV4_INGRESS_FORWARDING']['severity'], 'unknown')

    def test_empty_pending_failed_and_stale_neighbors_are_distinct_and_never_a_ping_verdict(self):
        report = self.report(); original = copy.deepcopy(report)
        for states, code, severity in (([], 'NEIGHBOR_NOT_CACHED', 'info'), (['INCOMPLETE'], 'NEIGHBOR_PENDING', 'info'),
                (['FAILED'], 'NEIGHBOR_FAILED', 'warning'), (['STALE'], 'NEIGHBOR_CACHED', 'info'),
                (['DELAY'], 'NEIGHBOR_CACHED', 'info'), (['PROBE'], 'NEIGHBOR_CACHED', 'info'),
                (['NOARP'], 'NEIGHBOR_CACHED', 'info'), (['PERMANENT'], 'NEIGHBOR_CACHED', 'info'),
                (['REACHABLE'], 'NEIGHBOR_CACHED', 'info'), (['unexpected'], 'NEIGHBOR_STATE_UNKNOWN', 'unknown')):
            report['neighbors']['records'] = [] if not states else [{'dst': '198.18.0.2', 'dev': 'vlan20', 'state': states}]
            before = copy.deepcopy(report); codes = self.codes(report)
            with self.subTest(states=states):
                self.assertEqual(codes[code]['severity'], severity)
                self.assertEqual(report, before)
                self.assertEqual(report['packet_delivery'], 'not_tested')
        self.assertEqual(self.codes(original)['NEIGHBOR_FAILED']['evidence']['record']['state'], ['FAILED'])
        # iproute2 omits dev when the caller supplied an explicit dev filter.
        del original['neighbors']['records'][0]['dev']
        observed = self.codes(original)['NEIGHBOR_FAILED']['evidence']
        self.assertNotIn('dev', observed['record'])
        self.assertEqual(observed['query']['device'], 'vlan20')
        original['neighbors']['query']['target'] = '198.18.0.3'
        self.assertIn('NEIGHBOR_CONTEXT_UNKNOWN', self.codes(original))

    def test_actual_link_flags_and_ingress_forwarding_use_context_and_keep_rpf_uncertain(self):
        report = self.report()
        report['egress_link']['flags'] = []
        next(row for row in report['links']['records'] if row['ifname'] == 'vlan10')['flags'] = ['UP']
        report['ipv4_settings']['interfaces']['vlan10']['forwarding'] = 0
        codes = self.codes(report)
        self.assertIn('EGRESS_ADMIN_DOWN', codes); self.assertIn('INGRESS_NO_LOWER_UP', codes)
        self.assertIn('INGRESS_FORWARDING_DISABLED', codes)
        self.assertIn('Aucun rejet de ce flux', codes['INGRESS_RP_FILTER']['message'])
        report['selected']['type'] = 'local'
        self.assertNotIn('INGRESS_FORWARDING_DISABLED', self.codes(report))
        report['selected']['type'] = None
        report['ipv4_settings']['interfaces']['vlan10']['forwarding'] = None
        self.assertIn('INGRESS_FORWARDING_UNKNOWN', self.codes(report))

    def test_missing_or_uncorrelated_neighbor_data_never_becomes_a_peer_failure(self):
        report = self.report()
        report['neighbors']['records'] = None
        codes = self.codes(report)
        self.assertIn('NEIGHBOR_UNAVAILABLE', codes); self.assertNotIn('NEIGHBOR_FAILED', codes)
        report['neighbors']['records'] = [{'dst': '198.18.0.3', 'dev': 'vlan20', 'state': ['FAILED']}]
        codes = self.codes(report)
        self.assertIn('NEIGHBOR_CONTEXT_UNKNOWN', codes); self.assertNotIn('NEIGHBOR_FAILED', codes)
        report['neighbors'] = None
        self.assertIn('NEIGHBOR_NOT_QUERIED', self.codes(report))

    def test_command_failure_keeps_raw_error_and_does_not_invent_a_missing_route_cause(self):
        report = self.report()
        report['selected'] = None; report['neighbors'] = None
        report['lookup'] = {'status': 'command_failed', 'records': None, 'returncode': 2, 'error': 'Invalid argument'}
        report['findings'] = findings(report)
        codes = self.codes(report)
        self.assertEqual(codes['ROUTE_LOOKUP_UNAVAILABLE']['evidence']['error'], 'Invalid argument')
        self.assertEqual(codes['ROUTE_LOOKUP_UNAVAILABLE']['severity'], 'unknown')
        self.assertIn('ROUTE_CONTEXT_PARTIAL', codes)
        self.assertIn('Invalid argument', render(report))
        self.assertNotIn('NEIGHBOR_FAILED', codes)
