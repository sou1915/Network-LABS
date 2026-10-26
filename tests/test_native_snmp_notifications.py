"""Notification declaration, log-only authorization and service ownership."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from network_labs.appliances.examples import snmp_notifications_lab, snmpv3_lab
from network_labs.appliances.snmp import usm_credentials, config_text as agent_config
from network_labs.appliances.snmp_notifications import config_text, prepare_files, drift, observe, command, client_config
from network_labs.appliances.spec import validate
from network_labs.appliances.service_adapters import adapters


class NotificationTests(unittest.TestCase):
    def test_reference_modes_matching_receiver_and_bound_source(self):
        for mode in ('trap', 'inform'):
            spec = snmp_notifications_lab('/rootfs', mode)
            self.assertEqual(validate(copy.deepcopy(spec)), spec)
            self.assertEqual(len(spec['nodes']), 5)
            text = agent_config(spec['nodes'][2]); self.assertIn('[snmp] clientaddr 192.0.2.20', text)
            self.assertIn('udp:192.0.2.10:162', text)
            self.assertEqual('-Ci ' in text, mode == 'inform')
            self.assertIn('defCommunity network-labs-notify', client_config(spec['nodes'][2]))

    def test_bad_receiver_addresses_credentials_mode_and_unmatched_policy_are_refused(self):
        for changes in ({'receiver': '127.0.0.1'}, {'receiver': '192.0.2.20'}, {'receiver': '192.0.2.99'},
                        {'community': 'bad\ninjection'}, {'community': 'mismatched'}, {'mode': 'other'}, {'unknown': True}):
            spec = snmp_notifications_lab('/rootfs'); spec['nodes'][2]['snmp_agent']['notifications'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): validate(spec)
        spec = snmp_notifications_lab('/rootfs'); spec['nodes'][0]['snmp_receiver']['sources'] = ['192.0.2.30']
        with self.assertRaises(ValueError): validate(spec)
        spec = snmpv3_lab('/rootfs', usm_credentials('monitor', 'auth-passphrase', 'privacy-passphrase'))
        spec['nodes'][2]['snmp_agent']['notifications'] = {'receiver': '192.0.2.10', 'community': 'notification-token', 'mode': 'trap'}
        with self.assertRaises(ValueError): validate(spec)

    def test_receiver_requires_static_up_managed_peers_and_exclusive_syslog_ownership(self):
        for changes in ({'interface': 'eth9'}, {'sources': []}, {'sources': ['192.0.2.99']},
                        {'sources': ['192.0.2.10']}, {'sources': [3]}, {'sources': ['192.0.2.20'] * 17}):
            spec = snmp_notifications_lab('/rootfs'); spec['nodes'][0]['snmp_receiver'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): validate(spec)
        for changes in ({'shutdown': ['eth0']}, {'startup': [['/bin/echo', 'unmanaged']]},
                        {'management': {'interface': 'eth0', 'syslog_remote': '192.0.2.20'}}):
            spec = snmp_notifications_lab('/rootfs'); spec['nodes'][0].update(changes)
            with self.assertRaises(ValueError): validate(spec)
        old = snmp_notifications_lab('/rootfs')['nodes'][0]; new = copy.deepcopy(old); new['snmp_receiver']['community'] = 'changed-token'
        with self.assertRaises(ValueError): adapters(new, old)

    def test_receiver_authorizes_logging_only_and_disables_agentx(self):
        node = snmp_notifications_lab('/rootfs')['nodes'][0]; text = config_text(node)
        self.assertIn('authCommunity log network-labs-notify 192.0.2.20', text)
        self.assertIn('sourceFilterType acceptlist', text); self.assertIn('snmpTrapdAddr udp:192.0.2.10:162', text)
        for forbidden in ('disableAuthorization', 'traphandle', 'execute', 'forward ', 'authUser'):
            self.assertNotIn(forbidden, text)
        self.assertIn('-X', command()); self.assertIn('-Ls6', command())

    def test_sensitive_files_and_file_conformity_do_not_claim_packet_delivery(self):
        node = snmp_notifications_lab('/rootfs')['nodes'][0]
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder); (bundle / 'files').mkdir(); prepare_files(bundle, node)
            for path in (bundle / 'files').iterdir(): self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with patch('network_labs.appliances.snmp_notifications.observe_config', return_value={'configuration_verified': True}):
            report = observe(Mock(), node); self.assertEqual(drift(Mock(), node), [])
            self.assertNotIn('network-labs-notify', json.dumps(report))
            self.assertIn('acknowledgement and accepted logging are separate', report['note'])
        with patch('network_labs.appliances.snmp_notifications.observe_config', return_value={'configuration_verified': False}):
            self.assertTrue(drift(Mock(), node))

    def test_missing_rotating_syslog_support_fails_before_daemon_launch(self):
        from network_labs.appliances.snmp_notifications import start_receivers
        from network_labs.appliances.runtime import RuntimeFailure
        manager = Mock(); manager.state = {'spec': snmp_notifications_lab('/rootfs')}
        manager.crun.return_value.stdout = ''; manager.crun.return_value.stderr = ''
        with self.assertRaises(RuntimeFailure): start_receivers(manager)
        self.assertFalse(any('--detach' in c.args for c in manager.crun.call_args_list))
