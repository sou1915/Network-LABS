import copy
import unittest
from network_labs.appliances.service_findings import findings


class ServiceFindingsTests(unittest.TestCase):
    def report(self, *stages):
        return {'endpoint': {'status': 'ready'}, 'stages': list(stages)}

    def test_faults_keep_actual_evidence_and_do_not_invent_root_causes(self):
        cases = [
            ({'stage': 'dns', 'status': 'failed', 'rcode': 3}, 'DNS_NXDOMAIN'),
            ({'stage': 'dns', 'status': 'failed', 'rcode': 0, 'addresses': []}, 'DNS_NO_DIRECT_A'),
            ({'stage': 'dns', 'status': 'failed', 'rcode': 2}, 'DNS_ERROR_RESPONSE'),
            ({'stage': 'dns', 'status': 'failed', 'error': 'TimeoutError'}, 'DNS_NO_ANSWER'),
            ({'stage': 'tcp', 'status': 'failed', 'error': 'ConnectionRefusedError'}, 'TCP_REFUSED'),
            ({'stage': 'tcp', 'status': 'failed', 'error': 'TimeoutError'}, 'TCP_NOT_CONNECTED'),
            ({'stage': 'http', 'status': 'failed', 'http_status': 404}, 'HTTP_STATUS_RECEIVED'),
            ({'stage': 'http', 'status': 'failed', 'connected': True}, 'HTTP_NO_STATUS'),
        ]
        for stage, code in cases:
            with self.subTest(code=code):
                report = self.report(stage); before = copy.deepcopy(report)
                row = findings(report)[0]
                self.assertEqual(row['code'], code); self.assertEqual(row['evidence'], stage)
                self.assertEqual(report, before); self.assertTrue(row['next_step'])
        refusal = findings(self.report(cases[4][0]))[0]
        self.assertIn('ne prouve pas', refusal['next_step'])

    def test_missing_evidence_cannot_become_dns_or_http_success(self):
        for kind in ('dns', 'tcp', 'http', 'target'):
            stage = dict(stage=kind, status='unknown', error='bad observation')
            row = findings(self.report(stage))[0]
            self.assertEqual(row['status'], 'unknown'); self.assertIn('aucun succès', row['message'])
        report = self.report(); report['endpoint'] = dict(status='blocked', reasons=['NO_USABLE_IPV4'])
        self.assertEqual(findings(report)[0]['code'], 'SOURCE_NOT_READY')

    def test_success_scopes_and_http_error_do_not_erase_previous_success(self):
        report = self.report(dict(stage='dns', status='passed', addresses=['192.0.2.10']),
                             dict(stage='tcp', status='passed'), dict(stage='http', status='failed', http_status=405))
        rows = findings(report)
        self.assertEqual([r['status'] for r in rows], ['passed', 'passed', 'failed'])
        self.assertIn('GET fonctionne', rows[-1]['next_step'])
        self.assertIn('405', rows[-1]['message'])
        report['stages'][-1].update(status='passed', http_status=200)
        self.assertIn('pas été téléchargé', findings(report)[-1]['next_step'])
