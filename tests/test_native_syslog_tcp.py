"""Plain TCP collector contracts and explicit submission/delivery distinction."""
import copy
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from network_labs.appliances.examples import syslog_tcp_lab, syslog_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.syslog_server import files, rootfs_assets
from network_labs.appliances.syslog_send import send, frame


class SyslogTCPTests(unittest.TestCase):
    def test_tcp_only_configuration_and_explicit_module_assets(self):
        spec = syslog_tcp_lab('/rootfs'); self.assertEqual(validate(copy.deepcopy(spec)), spec)
        text = files(spec['nodes'][0])['syslog-server.conf']
        self.assertIn('module(load="imptcp" threads="1" maxSessions="16")', text)
        self.assertIn('address="192.0.2.10" port="514"', text)
        self.assertIn('supportOctetCountedFraming="on" maxFrameSize="1024"', text)
        self.assertNotIn('imudp', text); self.assertNotIn('imuxsock', text)
        for value in ('tls', 'TCP', None, 1):
            candidate = copy.deepcopy(spec); candidate['nodes'][0]['syslog_server']['transport'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): validate(candidate)
        with patch('network_labs.appliances.dns_rootfs.assets', return_value=[]), patch('network_labs.appliances.dns_rootfs.shared_library_assets', return_value=[]) as modules:
            rootfs_assets('/trusted/rsyslogd', '/trusted/modules', tcp=True)
            self.assertEqual([c.args[0].name for c in modules.call_args_list], ['imudp.so', 'lmnet.so', 'imptcp.so'])

    def manager(self, transmitted=True, stored=False):
        spec = syslog_tcp_lab('/rootfs'); raw = '<133>1 - network-labs PC2 - - - NLAB-' + 'a' * 32 + ' hello'
        return SimpleNamespace(name=spec['name'], read=lambda: {'spec': spec, 'phase': 'running'},
            ns=lambda *a, **kw: subprocess.CompletedProcess(a, 0, json.dumps({'transmitted': transmitted}), ''),
            crun=lambda *a, **kw: subprocess.CompletedProcess(a, 0, ('192.0.2.20 ' + raw + '\n') if stored else '192.0.2.99 ' + raw + '\n', ''))

    def test_submission_is_not_delivery_and_log_must_match_actual_source_and_nonce(self):
        def endpoint(manager, index, node): return {'status': 'ready', 'address': '192.0.2.10' if index == 0 else '192.0.2.20'}
        with patch('network_labs.appliances.syslog_send._endpoint', side_effect=endpoint), patch('network_labs.appliances.syslog_send.secrets.token_hex', return_value='a'*32):
            self.assertEqual(send(self.manager(stored=True), 'PC2', 'PC1', 'hello')['status'], 'passed')
            self.assertEqual(send(self.manager(transmitted=False), 'PC2', 'PC1', 'hello')['status'], 'failed')
            with patch('network_labs.appliances.syslog_send.time.monotonic', side_effect=[0, 1, 4]), patch('network_labs.appliances.syslog_send.time.sleep'):
                result = send(self.manager(), 'PC2', 'PC1', 'hello')
            self.assertEqual(result['status'], 'unknown'); self.assertTrue(result['transmitted']); self.assertFalse(result['collector_observed'])

    def test_message_validation_refuses_log_injection_before_network_access(self):
        manager = self.manager()
        for message in ('', 'line\nbreak', '\r', '\t', 'é', 'x'*513):
            with self.subTest(message=message), self.assertRaises(ValueError): send(manager, 'PC2', 'PC1', message)
        self.assertEqual(frame('<133>message'), '12 <133>message')
