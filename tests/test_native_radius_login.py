import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from network_labs.appliances.radius_login import login
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.__main__ import main


ACCEPT = {'status': 'passed', 'authentication': {'decision': 'accepted', 'response_verified': True, 'response_code': 2}}


class RadiusLoginTests(unittest.TestCase):
    def manager(self, folder):
        manager = Mock(); manager.directory = Path(folder)
        spec = radius_lab('/rootfs', 'private-shared-secret', 'a' * 64, allow_shell=True)
        manager.read.return_value = {'phase': 'running', 'spec': spec}
        return manager

    def login(self, manager, **options):
        return login(manager, 'PC1', '192.0.2.20', username='learner', password='private-password',
                     secret='private-shared-secret', **options)

    def test_shell_is_explicit_opt_in_and_does_not_expand_radius_exec(self):
        default = radius_lab('/rootfs', 'private-shared-secret', 'a' * 64)
        self.assertNotIn('shell', default['nodes'][0]['radius_access']['users']['learner'])
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(folder); manager.read.return_value['spec'] = default
            with patch('network_labs.appliances.radius_login.probe') as auth, \
                 patch('network_labs.appliances.radius_login.subprocess.call') as launch:
                result = self.login(manager)
            self.assertEqual(result['error'], 'ACTION_NOT_ALLOWED')
            auth.assert_not_called(); launch.assert_not_called()
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['example', '--rootfs', '/rootfs', '--radius-shell']), 1)
        with tempfile.TemporaryDirectory() as folder:
            password = Path(folder) / 'password'; password.write_text('disposable-password'); password.chmod(0o600)
            secret = Path(folder) / 'secret'; secret.write_text('private-shared-secret'); secret.chmod(0o600)
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['example', '--rootfs', '/rootfs', '--radius', '--radius-shell',
                                       '--radius-user', 'learner', '--radius-password-file', str(password),
                                       '--radius-secret-file', str(secret)]), 0)
            policy = json.loads(output.getvalue())['nodes'][0]['radius_access']
            self.assertIn('shell', policy['users']['learner'])

    def test_reject_timeout_challenge_and_unverified_accept_never_open_session(self):
        reports = [{'status': 'unknown', 'authentication': None},
                   {'status': 'failed', 'authentication': {'response_verified': True, 'response_code': 3, 'decision': 'rejected'}},
                   {'status': 'blocked', 'authentication': {'response_verified': True, 'response_code': 11, 'decision': 'challenge'}},
                   {'status': 'passed', 'authentication': {'response_verified': False, 'response_code': 2, 'decision': 'accepted'}}]
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(folder)
            for report in reports:
                with self.subTest(report=report), patch('network_labs.appliances.radius_login.probe', return_value=report), \
                     patch('network_labs.appliances.radius_login.subprocess.call') as launch:
                    result = self.login(manager)
                    self.assertFalse(result['session_attempted']); launch.assert_not_called()

    def test_session_uses_private_process_file_and_same_nonroot_restrictions_with_or_without_tty(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(folder)
            for terminal in (False, True):
                def launch(args):
                    self.assertEqual(args[:4], ['crun', '--root', str(Path(folder) / 'crun'), 'exec'])
                    process_file = Path(args[5])
                    self.assertEqual(process_file.stat().st_mode & 0o777, 0o600)
                    process = json.loads(process_file.read_text())
                    self.assertEqual(process['terminal'], terminal)
                    self.assertEqual(process['args'], ['/bin/busybox', 'sh', *(['-i'] if terminal else [])])
                    self.assertEqual(process['user'], {'uid': 65532, 'gid': 65532, 'additionalGids': []})
                    self.assertTrue(process['noNewPrivileges'])
                    self.assertTrue(all(value == [] for value in process['capabilities'].values()))
                    self.assertNotIn('private-', process_file.read_text())
                    return 0
                with patch('network_labs.appliances.radius_login.probe', return_value=ACCEPT), \
                     patch('network_labs.appliances.radius_login.subprocess.call', side_effect=launch):
                    self.assertEqual(self.login(manager, terminal=terminal)['status'], 'passed')
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_session_failure_and_interrupt_remove_process_file_and_never_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(folder)
            for error, status in ((OSError('private-error'), 'unknown'), (KeyboardInterrupt(), 'interrupted')):
                with patch('network_labs.appliances.radius_login.probe', return_value=ACCEPT), \
                     patch('network_labs.appliances.radius_login.subprocess.call', side_effect=error) as launch:
                    result = self.login(manager)
                self.assertEqual(result['status'], status); self.assertNotIn('private-error', str(result))
                launch.assert_called_once(); self.assertEqual(list(Path(folder).iterdir()), [])
