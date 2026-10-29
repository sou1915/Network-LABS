import io
import json
from pathlib import Path
import tempfile
import subprocess
import signal
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from network_labs.appliances.radius_login import login
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.__main__ import main


ACCEPT = {'status': 'passed', 'authentication': {'decision': 'accepted', 'response_verified': True, 'response_code': 2}}


class FakeGroup:
    name = 'aaa-test'
    closed = False
    def __enter__(self): return self
    def __exit__(self, *_): self.closed = True; return False


class RadiusLoginTests(unittest.TestCase):
    def setUp(self):
        scope = patch('network_labs.appliances.radius_login.SessionGroup', side_effect=lambda *_: FakeGroup())
        self.groups = scope.start(); self.addCleanup(scope.stop)

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
                self.assertEqual(main(['example', '--rootfs', '/rootfs', '--radius', '--radius-shell', '--radius-accounting',
                                       '--radius-user', 'learner', '--radius-password-file', str(password),
                                       '--radius-secret-file', str(secret)]), 0)
            policy = json.loads(output.getvalue())['nodes'][0]['radius_access']
            self.assertIn('shell', policy['users']['learner'])
            self.assertTrue(policy['accounting'])

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
                def launch(args, **options):
                    self.assertEqual(args[:4], ['crun', '--root', str(Path(folder) / 'crun'), 'exec'])
                    process_file = Path(args[5])
                    self.assertEqual(process_file.stat().st_mode & 0o777, 0o600)
                    process = json.loads(process_file.read_text())
                    self.assertEqual(process['terminal'], terminal)
                    tail = ['/bin/busybox', 'sh', *(['-i'] if terminal else [])]
                    self.assertEqual(process['args'][-len(tail):], tail)
                    self.assertIn('/proc/self/cgroup', process['args'][3])
                    self.assertEqual(args[-3:], ['--cgroup', 'aaa-test', 'PC1'])
                    self.assertEqual(options['timeout'], 300)
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
            for error, status in ((OSError('private-error'), 'unknown'), (KeyboardInterrupt(), 'interrupted'),
                                  (subprocess.TimeoutExpired(['crun'], 1), 'expired')):
                with patch('network_labs.appliances.radius_login.probe', return_value=ACCEPT), \
                     patch('network_labs.appliances.radius_login.subprocess.call', side_effect=error) as launch:
                    result = self.login(manager)
                self.assertEqual(result['status'], status); self.assertNotIn('private-error', str(result))
                self.assertTrue(result['cleanup_complete'])
                launch.assert_called_once(); self.assertEqual(list(Path(folder).iterdir()), [])

    def test_session_limit_cannot_be_extended_and_missing_control_never_launches(self):
        from network_labs.appliances.runtime import RuntimeFailure
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(folder)
            with patch('network_labs.appliances.radius_login.probe') as auth:
                for seconds in (0, True, 301, 3601):
                    with self.subTest(seconds=seconds), self.assertRaises(ValueError): self.login(manager, seconds=seconds)
                auth.assert_not_called()
            self.groups.side_effect = RuntimeFailure('session control unavailable')
            with patch('network_labs.appliances.radius_login.probe', return_value=ACCEPT), \
                 patch('network_labs.appliances.radius_login.subprocess.call') as launch:
                result = self.login(manager, seconds=1)
            self.assertEqual(result['status'], 'unknown'); launch.assert_not_called()
            self.assertFalse(result['session_attempted'])

    def test_cleanup_failure_overrides_a_successful_shell_exit(self):
        from network_labs.appliances.runtime import RuntimeFailure
        class FailedCleanup(FakeGroup):
            def __exit__(self, *_): raise RuntimeFailure('cleanup failed')
        self.groups.side_effect = lambda *_: FailedCleanup()
        with tempfile.TemporaryDirectory() as folder:
            with patch('network_labs.appliances.radius_login.probe', return_value=ACCEPT), \
                 patch('network_labs.appliances.radius_login.subprocess.call', return_value=0):
                result = self.login(self.manager(folder))
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['error'], 'SESSION_CLEANUP_UNCONFIRMED')
        self.assertFalse(result['cleanup_complete'])

    def test_sigterm_uses_cleanup_path_and_restores_previous_handler(self):
        previous = signal.getsignal(signal.SIGTERM)
        def launch(*_, **__): signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        with tempfile.TemporaryDirectory() as folder:
            with patch('network_labs.appliances.radius_login.probe', return_value=ACCEPT), \
                 patch('network_labs.appliances.radius_login.subprocess.call', side_effect=launch):
                result = self.login(self.manager(folder))
        self.assertEqual(result['status'], 'interrupted'); self.assertTrue(result['cleanup_complete'])
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_worker_exit_preserves_signal_handler_and_stops_after_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(folder)
            manager.read.return_value['spec']['nodes'][0]['radius_access']['accounting'] = True
            groups = []; events = []
            def group(*_): groups.append(FakeGroup()); return groups[-1]
            self.groups.side_effect = group
            def account(*_, **request):
                events.append(request)
                if request['event'] == 'stop': self.assertTrue(groups[-1].closed)
                return {'status': 'passed', 'requests_sent': 1}
            def worker_exit(*_, **__): raise SystemExit(0)
            with patch('network_labs.appliances.radius_login.probe', return_value=ACCEPT), \
                 patch('network_labs.appliances.radius_login.account', side_effect=account), \
                 patch('network_labs.appliances.radius_login.signal.signal') as replace_handler:
                with self.assertRaises(SystemExit):
                    self.login(manager, launcher=worker_exit, handle_signals=False)
                replace_handler.assert_not_called()
            self.assertTrue(groups[-1].closed)
            self.assertEqual([event['event'] for event in events], ['start', 'stop'])
            self.assertEqual(events[-1]['terminate_cause'], 6)

    def test_accounting_ack_gates_launch_and_stop_follows_confirmed_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(folder)
            manager.read.return_value['spec']['nodes'][0]['radius_access']['accounting'] = True
            groups = []
            def group(*_): groups.append(FakeGroup()); return groups[-1]
            self.groups.side_effect = group
            events = []
            def account(*_, **request):
                events.append(request)
                if request['event'] == 'stop': self.assertTrue(groups[-1].closed)
                return {'status': 'passed', 'requests_sent': 1}
            with patch('network_labs.appliances.radius_login.probe', return_value=ACCEPT), \
                 patch('network_labs.appliances.radius_login.account', side_effect=account), \
                 patch('network_labs.appliances.radius_login.subprocess.call', return_value=0):
                result = self.login(manager)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual([event['event'] for event in events], ['start', 'stop'])
            self.assertEqual(events[0]['session_id'], events[1]['session_id'])
            self.assertEqual(events[1]['terminate_cause'], 1)

    def test_unacknowledged_start_never_launches_and_compensates_possible_record(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(folder)
            manager.read.return_value['spec']['nodes'][0]['radius_access']['accounting'] = True
            for sent, count in ((0, 1), (1, 2), (None, 2)):
                events = []
                def account(*_, **request):
                    events.append(request)
                    return {'status': 'unknown', 'requests_sent': sent} if request['event'] == 'start' else {'status': 'passed'}
                with patch('network_labs.appliances.radius_login.probe', return_value=ACCEPT), \
                     patch('network_labs.appliances.radius_login.account', side_effect=account), \
                     patch('network_labs.appliances.radius_login.subprocess.call') as launch:
                    result = self.login(manager)
                self.assertEqual(result['status'], 'blocked'); self.assertTrue(result['cleanup_complete'])
                launch.assert_not_called(); self.assertEqual(len(events), count)
                if count == 2:
                    self.assertEqual(events[1]['terminate_cause'], 9)
                    self.assertEqual(events[1]['session_seconds'], 0)

    def test_stop_failure_is_unknown_and_unconfirmed_cleanup_withholds_stop(self):
        from network_labs.appliances.runtime import RuntimeFailure
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(folder)
            manager.read.return_value['spec']['nodes'][0]['radius_access']['accounting'] = True
            with patch('network_labs.appliances.radius_login.probe', return_value=ACCEPT), \
                 patch('network_labs.appliances.radius_login.account', side_effect=[{'status': 'passed', 'requests_sent': 1}, {'status': 'unknown'}]), \
                 patch('network_labs.appliances.radius_login.subprocess.call', return_value=0):
                result = self.login(manager)
            self.assertEqual(result['error'], 'ACCOUNTING_STOP_UNCONFIRMED'); self.assertTrue(result['cleanup_complete'])
            class FailedCleanup(FakeGroup):
                def __exit__(self, *_): raise RuntimeFailure('unavailable')
            self.groups.side_effect = lambda *_: FailedCleanup()
            with patch('network_labs.appliances.radius_login.probe', return_value=ACCEPT), \
                 patch('network_labs.appliances.radius_login.account', return_value={'status': 'passed', 'requests_sent': 1}) as account, \
                 patch('network_labs.appliances.radius_login.subprocess.call', return_value=0):
                result = self.login(manager)
            account.assert_called_once()
            self.assertEqual(result['accounting']['stop']['status'], 'withheld')
