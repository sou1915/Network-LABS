"""Structured LLDP advertisements remain distinct from topology and reachability."""
import copy
import unittest

from network_labs.appliances.lldp_neighbors import normalize_neighbors
from network_labs.appliances.diagnostics import explain_node
from network_labs.appliances.examples import ospf_dhcp_lldp_lab


def record(local='eth1', name='SW2', port='eth0', subtype='ifname'):
    # JSON0 contract checked against upstream lldpd test_json0_output.
    return {'name': local, 'via': 'LLDP', 'age': '0 day, 00:00:02',
            'chassis': [{'id': [{'type': 'local', 'value': 'advertised-chassis'}],
                         'name': [{'value': name}]}],
            'port': [{'id': [{'type': subtype, 'value': port}], 'ttl': [{'value': '6'}]}]}


def payload(*entries):
    return {'lldp': [{'interface': list(entries)}]}


class LLDPNeighborTests(unittest.TestCase):
    def test_actual_identifiers_ttl_and_duplicate_local_ports_are_preserved(self):
        raw = payload(record(), record(name='unmanaged-peer', port='00:11:22:33:44:55', subtype='mac'))
        original = copy.deepcopy(raw); result = normalize_neighbors(raw)
        self.assertEqual(result['status'], 'observed')
        self.assertEqual([n['local_port'] for n in result['neighbors']], ['eth1', 'eth1'])
        self.assertEqual(result['neighbors'][1]['port_id'], {'type': 'mac', 'value': '00:11:22:33:44:55'})
        self.assertEqual(result['neighbors'][0]['ttl_seconds'], 6)
        self.assertEqual(result['neighbors'][0]['age'], '0 day, 00:00:02')
        self.assertEqual(raw, original)

    def test_empty_table_is_distinct_from_unavailable_or_malformed(self):
        for raw in ({'lldp': [{}]}, payload()):
            result = normalize_neighbors(raw)
            self.assertEqual((result['status'], result['neighbors']), ('observed', []))
        for raw in (None, {}, [], {'lldp': []}, {'lldp': {}}, {'lldp': [{'unexpected': []}]},
                    {'lldp': [{'interface': {}}]}, payload(None), payload({'name': 'eth1'}),
                    payload(record(), None)):
            with self.subTest(raw=raw):
                result = normalize_neighbors(raw)
                self.assertNotEqual(result['status'], 'observed')
                if raw == payload(record(), None):
                    self.assertEqual((result['status'], len(result['neighbors']), result['unparsed_entries']), ('partial', 1, 1))
                else:
                    self.assertIsNone(result['neighbors'])

    def test_missing_name_uses_only_advertised_chassis_and_never_topology(self):
        entry = record(); del entry['chassis'][0]['name']
        summary = normalize_neighbors(payload(entry))
        self.assertEqual(summary['status'], 'observed')
        self.assertIsNone(summary['neighbors'][0]['system_name'])
        node = ospf_dhcp_lldp_lab('/rootfs')['nodes'][1]
        actual = {'links': [], 'addresses': [], 'routes': [], 'forwarding': True,
                  'lldp': {'neighbors': payload(entry)}}
        message = next(f['message'] for f in explain_node(node, actual) if f['code'] == 'LLDP_NEIGHBOR')
        self.assertIn('advertised-chassis', message)
        self.assertNotIn('SW2', message)

    def test_optional_bad_fields_do_not_erase_other_actual_identifiers(self):
        for value in (None, True, '-1', '65536', '6 seconds', '9' * 100):
            entry = record(); entry['port'][0]['ttl'] = [{'value': value}]
            result = normalize_neighbors(payload(entry))
            self.assertEqual(result['status'], 'partial')
            self.assertIsNone(result['neighbors'][0]['ttl_seconds'])
            self.assertEqual(result['neighbors'][0]['port_id']['value'], 'eth0')
        for field in ('id',):
            entry = record(); entry['chassis'][0][field] = [{'type': 'local', 'value': 'one'}, {'type': 'local', 'value': 'two'}]
            self.assertEqual(normalize_neighbors(payload(entry))['status'], 'unknown')
        entry = record(); entry['via'] = 'CDP'
        self.assertEqual(normalize_neighbors(payload(entry))['status'], 'unknown')

    def test_human_findings_escape_announced_text_and_do_not_certify_delivery(self):
        node = ospf_dhcp_lldp_lab('/rootfs')['nodes'][1]
        actual = {'links': [], 'addresses': [], 'routes': [], 'forwarding': True,
                  'lldp': {'neighbors': payload(record(name='peer\n\x1b[2J\u202e'))}}
        findings = explain_node(node, actual)
        finding = next(f for f in findings if f['code'] == 'LLDP_NEIGHBOR')
        self.assertNotIn('\n', finding['message']); self.assertNotIn('\x1b', finding['message'])
        self.assertNotIn('\u202e', finding['message']); self.assertIn('\\u202e', finding['message'])
        self.assertEqual(finding['evidence']['system_name'], 'peer\n\x1b[2J\u202e')
        self.assertIn('pas un temps restant', finding['message'])
        actual['lldp']['neighbors'] = payload()
        self.assertIn('LLDP_NEIGHBORS_EMPTY', {f['code'] for f in explain_node(node, actual)})
        actual['lldp']['neighbors'] = None
        codes = {f['code'] for f in explain_node(node, actual)}
        self.assertIn('LLDP_NEIGHBORS_UNPARSED', codes); self.assertNotIn('LLDP_NEIGHBORS_EMPTY', codes)
