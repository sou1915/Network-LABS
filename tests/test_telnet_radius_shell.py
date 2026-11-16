"""Explicit Telnet shell grants share the existing cleanup/accounting supervisor."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch
from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.radius_access import allowed_actions
from network_labs.appliances.ssh_radius_shell import serve_shell

SECRET = 'private-telnet-shell-test-secret'


class TelnetShellTests(unittest.TestCase):
    def test_shell_requires_both_explicit_node_and_user_grants(self):
        old = radius_lab('/rootfs', SECRET, 'a'*64, telnet=True, role_policy=True)
        self.assertNotIn('shell', old['nodes'][0]['management']['telnet_actions'])
        self.assertNotIn('shell', allowed_actions(old['nodes'][0]['radius_access'], 'learner'))
        spec = radius_lab('/rootfs', SECRET, 'a'*64, telnet=True, telnet_shell=True, role_policy=True, accounting=True, accounting_outbox=True, accounting_journal=True)
        node = spec['nodes'][0]
        self.assertIn('shell', node['management']['telnet_actions']); self.assertIn('shell', allowed_actions(node['radius_access'], 'learner'))
        manager = Mock(); manager.state = {'phase':'running', 'spec':spec}; manager.read.return_value = manager.state
        node['management']['telnet_actions'].remove('shell')
        with patch('network_labs.appliances.ssh_radius_shell.login') as login:
            connection = Mock(); serve_shell(manager, 'PC1', connection, 'learner', 'password', terminal=True, transport='telnet')
            login.assert_not_called(); connection.sendall.assert_called_once_with(b'DENY\n')
        with self.assertRaises(ValueError): radius_lab('/rootfs', SECRET, 'a'*64, telnet_shell=True)

    def test_telnet_calls_the_shared_supervisor_without_borrowing_ssh_policy(self):
        spec = radius_lab('/rootfs', SECRET, 'a'*64, telnet=True, telnet_shell=True)
        manager = Mock(); manager.state = {'phase':'running','spec':spec}; manager.read.return_value = manager.state
        with patch('network_labs.appliances.ssh_radius_shell.login', return_value={'status':'blocked'}) as login:
            connection = Mock(); serve_shell(manager, 'PC1', connection, 'learner', 'password', terminal=True, transport='telnet')
            self.assertFalse(login.call_args.kwargs['handle_signals']); self.assertTrue(login.call_args.kwargs['terminal'])
            self.assertEqual(login.call_args.kwargs['secret'], SECRET)
        spec['nodes'][0]['radius_access']['users']['learner'].remove('shell')
        with patch('network_labs.appliances.radius_login.probe') as probe:
            connection = Mock(); serve_shell(manager, 'PC1', connection, 'learner', 'password', terminal=True, transport='telnet')
            probe.assert_not_called(); connection.sendall.assert_called_once_with(b'DENY\n')

    def test_cli_enables_shell_and_journal_only_with_explicit_telnet_shell(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, value in (('password','private-password'), ('secret',SECRET)):
                path = root/name; path.write_text(value); path.chmod(0o600)
            args = ['example','--rootfs','/rootfs','--radius','--radius-telnet','--radius-telnet-shell','--radius-roles',
                    '--radius-accounting','--radius-accounting-outbox','--radius-accounting-journal','--radius-user','learner',
                    '--radius-password-file',str(root/'password'),'--radius-secret-file',str(root/'secret')]
            with redirect_stdout(io.StringIO()) as output: self.assertEqual(main(args),0)
            node = json.loads(output.getvalue())['nodes'][0]
            self.assertIn('shell', node['management']['telnet_actions']); self.assertTrue(node['radius_access']['accounting_journal'])
            args.remove('--radius-telnet-shell')
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()): self.assertEqual(main(args),1)
