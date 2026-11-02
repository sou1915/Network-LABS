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


class USMInformTests(unittest.TestCase):
    def spec(self):
        from network_labs.appliances.examples import snmpv3_informs_lab
        return snmpv3_informs_lab('/rootfs', usm_credentials('notify', 'auth-passphrase', 'privacy-passphrase'))

    def test_usm_reference_uses_receiver_authoritative_informs_without_community_fallback(self):
        spec = self.spec(); self.assertEqual(validate(copy.deepcopy(spec)), spec)
        receiver = spec['nodes'][0]; agent = spec['nodes'][2]
        text = config_text(receiver)
        self.assertIn('createUser notify SHA-256 -m 0x', text)
        self.assertIn('authUser log notify priv', text)
        self.assertNotIn('authCommunity', text); self.assertNotIn('createUser -e', text)
        text = agent_config(agent)
        self.assertIn('trapsess -v3 -Ci -u notify -l authPriv -a SHA-256 -x AES', text)
        self.assertNotIn('trapsess -v2c', text)
        self.assertIn('defAuthMasterKey', client_config(agent))
        self.assertIn('clientaddr 192.0.2.20', client_config(agent))

    def test_mixed_security_traps_bad_keys_and_unmatched_receiver_are_refused(self):
        for target, changes in ((0, {'community': 'fallback-token'}),
                                (2, {'community': 'fallback-token'}),
                                (2, {'mode': 'trap'})):
            spec = self.spec()
            config = spec['nodes'][0]['snmp_receiver'] if target == 0 else spec['nodes'][2]['snmp_agent']['notifications']
            config.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): validate(spec)
        spec = self.spec(); spec['nodes'][0]['snmp_receiver']['usm']['auth_master_key'] = '0' * 64
        with self.assertRaises(ValueError): validate(spec)
        spec = self.spec(); spec['nodes'][0]['snmp_receiver']['usm']['privacy_master_key'] = 'bad'
        with self.assertRaises(ValueError): validate(spec)
        spec = self.spec(); del spec['nodes'][2]['snmp_agent']['usm']
        spec['nodes'][2]['snmp_agent']['community'] = 'polling-token'
        with self.assertRaises(ValueError): validate(spec)

    def test_secret_redaction_mode_0600_and_fresh_receiver_engine_required(self):
        from network_labs.appliances.snmp import observe as agent_observe
        spec = self.spec(); receiver, agent = spec['nodes'][0], spec['nodes'][2]
        with self.assertRaises(ValueError): command(receiver)
        self.assertIn('--engineID=' + 'a' * 24, command(receiver, 'a' * 24))
        self.assertNotIn('--engineID=', ' '.join(command()))
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder); (bundle / 'files').mkdir(); prepare_files(bundle, receiver)
            self.assertEqual((bundle / 'files/snmp-receiver.conf').stat().st_mode & 0o777, 0o600)
        with patch('network_labs.appliances.snmp_notifications.observe_config', return_value={'configuration_verified': True}), \
             patch('network_labs.appliances.snmp.observe_config', return_value={'configuration_verified': True}):
            reports = json.dumps([observe(Mock(), receiver), agent_observe(Mock(), agent)])
            for key in receiver['snmp_receiver']['usm'].values():
                if key != 'notify': self.assertNotIn(key, reports)
            self.assertEqual(observe(Mock(), receiver)['versions'], ['3'])
        old = copy.deepcopy(receiver); receiver['snmp_receiver']['usm']['username'] = 'changed'
        with self.assertRaises(ValueError): adapters(receiver, old)

    def test_cli_requires_complete_credentials_and_exclusive_reference_flags(self):
        import contextlib
        import io
        from network_labs.appliances.__main__ import main
        from network_labs.appliances.runtime import plan
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder); auth = folder / 'auth'; privacy = folder / 'privacy'
            auth.write_text('auth-passphrase'); privacy.write_text('privacy-passphrase')
            args = ['example', '--rootfs', '/rootfs', '--snmpv3-informs', '--snmp-user', 'notify',
                    '--snmp-auth-passphrase-file', str(auth), '--snmp-privacy-passphrase-file', str(privacy)]
            output = io.StringIO()
            with contextlib.redirect_stdout(output): self.assertEqual(main(args), 0)
            spec = json.loads(output.getvalue()); self.assertEqual(spec['name'], 'snmpv3-informs')
            self.assertEqual(len(plan(spec)['nodes']), 5)
            for invalid in (args + ['--snmpv3'], args + ['--snmp-notification-mode', 'trap'],
                            ['example', '--rootfs', '/rootfs', '--snmpv3-informs']):
                with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(main(invalid), 1)
