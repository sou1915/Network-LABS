"""Managed sender-engine trust, rotation ordering and fail-closed boundaries."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from network_labs.appliances.examples import snmpv3_traps_lab
from network_labs.appliances.snmp import usm_credentials, config_text as agent_text
from network_labs.appliances.snmp_notifications import config_text, prepare_files
from network_labs.appliances.snmp_traps import initialize, users_text, wire_engine, sender_token, observe_users, stop_receiver
from network_labs.appliances.spec import validate
from network_labs.appliances.runtime import RuntimeFailure


class USMTrapTests(unittest.TestCase):
    def spec(self):
        return snmpv3_traps_lab('/rootfs', usm_credentials('notify', 'trap-auth-password', 'trap-privacy-password'))

    def manager(self, folder):
        manager = Mock(); manager.directory = Path(folder)
        manager.state = {'spec': self.spec()}; manager.read.side_effect = lambda: manager.state
        receiver = manager.state['spec']['nodes'][0]
        bundle = manager.directory / receiver['name']; (bundle / 'files').mkdir(parents=True)
        prepare_files(bundle, receiver)
        return manager, receiver

    def test_two_sender_reference_has_only_engine_bound_users_and_no_inform_session(self):
        spec = self.spec(); self.assertEqual(validate(copy.deepcopy(spec)), spec)
        self.assertEqual(len(spec['nodes']), 6)
        text = config_text(spec['nodes'][0])
        self.assertIn('includeFile /lab/snmp-trap-users.conf', text); self.assertNotIn('createUser ', text)
        self.assertIn('authUser log notify priv', text); self.assertNotIn('authCommunity', text)
        for index in (2, 5):
            text = agent_text(spec['nodes'][index]); self.assertIn('trapsess -v3 -u notify', text); self.assertNotIn('-Ci', text)

    def test_named_senders_modes_sources_and_credentials_must_match(self):
        for value in ([], ['R1', 'R1'], ['unknown'], ['PC3'], [3], ['R1']):
            spec = self.spec(); spec['nodes'][0]['snmp_receiver']['trap_senders'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): validate(spec)
        spec = self.spec(); del spec['nodes'][0]['snmp_receiver']['trap_senders']
        with self.assertRaises(ValueError): validate(spec)
        spec = self.spec(); spec['nodes'][2]['snmp_agent']['notifications']['mode'] = 'inform'
        with self.assertRaises(ValueError): validate(spec)
        spec = self.spec(); spec['nodes'][5]['snmp_agent']['notifications']['usm']['auth_master_key'] = '0' * 64
        with self.assertRaises(ValueError): validate(spec)
        spec = self.spec(); del spec['nodes'][0]['snmp_receiver']['usm']; spec['nodes'][0]['snmp_receiver']['community'] = 'fallback-token'
        with self.assertRaises(ValueError): validate(spec)

    def test_runtime_allocation_is_private_distinct_and_never_added_to_startup_spec(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, receiver = self.manager(folder); original = copy.deepcopy(manager.state['spec'])
            initialize(manager); bindings = manager.state['snmp_trap_engines']
            self.assertNotEqual(bindings['R1']['token'], bindings['R2']['token'])
            self.assertEqual(manager.state['spec'], original)
            path = manager.directory / 'PC1/files/snmp-trap-users.conf'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_text(), users_text(manager.state, receiver))
            for record in bindings.values():
                self.assertIn('createUser -e 0x' + wire_engine(record['token']), path.read_text())
            with self.assertRaises(RuntimeFailure): initialize(manager)
            del manager.state['snmp_trap_engines']['R1']
            self.assertFalse(observe_users(manager, receiver)['configuration_verified'])
            with self.assertRaises(RuntimeFailure): users_text(manager.state, receiver)

    def test_rotation_retires_old_sender_but_preserves_other_binding_and_rebinds_before_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, receiver = self.manager(folder); initialize(manager)
            manager.ns.return_value.stdout = ''
            node = manager.state['spec']['nodes'][2]
            with patch('network_labs.appliances.snmp_notifications.observe', return_value={'configuration_verified': True}), \
                 patch('network_labs.appliances.snmp_traps.stop_receiver') as stop, \
                 patch('network_labs.appliances.snmp_notifications.start_trapd') as start:
                first = sender_token(manager, node); stop.assert_not_called(); start.assert_not_called()
                other = copy.deepcopy(manager.state['snmp_trap_engines']['R2'])
                second = sender_token(manager, node); self.assertNotEqual(first, second)
                stop.assert_called_once(); start.assert_called_once()
                self.assertEqual(manager.state['snmp_trap_engines']['R2'], other)
                text = (manager.directory / 'PC1/files/snmp-trap-users.conf').read_text()
                self.assertNotIn(wire_engine(first), text); self.assertIn(wire_engine(second), text)
            with patch('network_labs.appliances.snmp_notifications.observe', return_value={'configuration_verified': False}):
                old = copy.deepcopy(manager.state)
                with self.assertRaises(RuntimeFailure): sender_token(manager, node)
                self.assertEqual(manager.state, old)
            manager.ns.return_value.stdout = '192.0.2.20:161'
            with self.assertRaises(RuntimeFailure): sender_token(manager, node)

    def test_rotation_refuses_a_pid_that_is_not_the_owned_receiver(self):
        manager = Mock(); node = self.spec()['nodes'][0]
        manager.crun.side_effect = [Mock(stdout='1\n')]
        with self.assertRaises(RuntimeFailure): stop_receiver(manager, node, 0)
        manager.crun.side_effect = [Mock(stdout='42\n'), Mock(stdout='/bin/sleep\n')]
        with self.assertRaises(RuntimeFailure): stop_receiver(manager, node, 0)
        self.assertFalse(any('/bin/busybox' in c.args and 'kill' in c.args for c in manager.crun.call_args_list))

    def test_cli_requires_credentials_and_refuses_mixed_reference_flags(self):
        from network_labs.appliances.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder); auth = folder / 'auth'; privacy = folder / 'privacy'
            auth.write_text('trap-auth-password'); privacy.write_text('trap-privacy-password')
            args = ['example', '--rootfs', '/rootfs', '--snmpv3-traps', '--snmp-user', 'notify',
                    '--snmp-auth-passphrase-file', str(auth), '--snmp-privacy-passphrase-file', str(privacy)]
            output = io.StringIO()
            with contextlib.redirect_stdout(output): self.assertEqual(main(args), 0)
            self.assertEqual(json.loads(output.getvalue())['name'], 'snmpv3-traps')
            for invalid in (args + ['--snmpv3-informs'], args + ['--snmp-notification-mode', 'trap'],
                            ['example', '--rootfs', '/rootfs', '--snmpv3-traps']):
                with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(main(invalid), 1)

    def test_failed_receiver_rebind_does_not_restore_retired_trust(self):
        with tempfile.TemporaryDirectory() as folder:
            manager, receiver = self.manager(folder); initialize(manager); manager.ns.return_value.stdout = ''
            node = manager.state['spec']['nodes'][2]
            with patch('network_labs.appliances.snmp_notifications.observe', return_value={'configuration_verified': True}), \
                 patch('network_labs.appliances.snmp_traps.stop_receiver'), \
                 patch('network_labs.appliances.snmp_notifications.start_trapd', side_effect=RuntimeFailure('rebind failed')):
                first = sender_token(manager, node)
                with self.assertRaises(RuntimeFailure): sender_token(manager, node)
                second = manager.state['snmp_trap_engines']['R1']['token']; self.assertNotEqual(first, second)
                text = (manager.directory / 'PC1/files/snmp-trap-users.conf').read_text()
                self.assertNotIn(wire_engine(first), text); self.assertIn(wire_engine(second), text)

    def test_distinct_notification_user_is_created_locally_without_polling_permission(self):
        spec = self.spec(); spec['nodes'][2]['snmp_agent']['usm'] = usm_credentials('polling', 'other-polling-auth', 'other-polling-privacy')
        validate(spec); text = agent_text(spec['nodes'][2])
        self.assertIn('createUser notify SHA-256 -m 0x', text)
        self.assertIn('createUser polling SHA-256 -m 0x', text)
        self.assertIn('group NetworkLabsGroup usm polling', text)
        self.assertNotIn('group NetworkLabsGroup usm notify', text)

    def test_same_sender_username_cannot_have_contradictory_polling_and_trap_keys(self):
        spec = self.spec(); spec['nodes'][2]['snmp_agent']['usm']['auth_master_key'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'different polling and trap keys'): validate(spec)
