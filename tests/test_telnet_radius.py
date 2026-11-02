"""Telnet RADIUS policy, isolated bridge generations and trusted login assets."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch
from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.management import commands, managed_files, start_service
from network_labs.appliances.runtime import Manager, RuntimeFailure
from network_labs.appliances.spec import validate
from network_labs.appliances.ssh_radius_worker import BridgeManager
from network_labs.appliances.telnet_radius import dispatch, rootfs_assets, service_process, LOGIN
from test_native_management import KEY, HASH

SECRET = 'telnet-radius-unit-shared-secret'


class TelnetRadiusTests(unittest.TestCase):
    def spec(self):
        return radius_lab('/rootfs', SECRET, 'a' * 64, role_policy=True, telnet=True)

    def manager(self):
        manager = Manager('telnet-test'); manager.state = {'phase': 'running', 'spec': self.spec()}
        return manager

    def test_standalone_policy_is_explicit_and_has_no_local_account_or_shell(self):
        spec = self.spec(); node = spec['nodes'][0]; config = node['management']
        self.assertEqual(spec, validate(spec)); self.assertEqual(config['telnet_password_hash'], '')
        self.assertEqual(config['ssh_keys'], [])
        self.assertEqual(commands(node), {'telnet': ['/bin/busybox', 'telnetd', '-F', '-K', '-b', '192.0.2.10', '-p', '23', '-l', LOGIN]})
        self.assertEqual(set(managed_files(node)), {'management.json'})
        self.assertNotIn(SECRET, json.dumps(managed_files(node)))
        for fault in ({'telnet_radius': 1}, {'telnet_actions': ['shell']}, {'telnet_actions': 'identity'},
                      {'telnet_actions': ['identity', 'identity']}, {'telnet_password_hash': HASH},
                      {'ssh_keys': [KEY]}, {'syslog_remote': '192.0.2.20'}, {'telnet_actions': [True]}):
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                candidate = copy.deepcopy(spec); candidate['nodes'][0]['management'].update(fault); validate(candidate)
        candidate = copy.deepcopy(spec); candidate['nodes'][0]['radius_access']['roles']['session'] = ['shell']
        candidate['nodes'][0]['radius_access']['user_roles']['learner'].append('session')
        with self.assertRaises(ValueError): validate(candidate)
        for config in ({'interface': 'eth0', 'telnet_actions': ['identity']}, {'interface': 'eth0', 'telnet_radius': True}):
            with self.assertRaises(ValueError):
                candidate = copy.deepcopy(spec); candidate['nodes'][0]['management'] = config; validate(candidate)
        with self.assertRaises(ValueError): radius_lab('/rootfs', SECRET, 'a' * 64, telnet=True, ssh_key=KEY)

    def test_device_and_user_denials_do_not_authenticate_or_execute(self):
        manager = self.manager(); config = manager.state['spec']['nodes'][0]['management']
        config['telnet_actions'] = ['identity']
        with patch('network_labs.appliances.telnet_radius.execute') as execute:
            for action in ('hostname', 'shell', 'shell-tty', 'identity; touch /tmp/bypass'):
                self.assertIsNone(dispatch(manager, 'PC1', action, 'learner', 'password'))
            execute.assert_not_called()
        manager.state['spec']['nodes'][0]['radius_access']['user_roles']['learner'] = ['auditor']
        with patch('network_labs.appliances.radius_exec.probe') as probe:
            self.assertIsNone(dispatch(manager, 'PC1', 'identity', 'learner', 'password')); probe.assert_not_called()
        config['telnet_radius'] = False
        with patch('network_labs.appliances.telnet_radius.execute') as execute:
            self.assertIsNone(dispatch(manager, 'PC1', 'identity', 'learner', 'password')); execute.assert_not_called()

    def test_only_verified_accept_and_successful_fixed_execution_returns_output(self):
        manager = self.manager()
        accepted = {'status': 'passed', 'executed': True, 'returncode': 0, 'stdout': 'uid=65532\n',
                    'authentication': {'status': 'passed', 'authentication': {'decision': 'accepted', 'response_code': 2, 'response_verified': True}}}
        with patch('network_labs.appliances.telnet_radius.execute', return_value=accepted) as execute:
            self.assertEqual(dispatch(manager, 'PC1', 'identity', 'learner', 'password'), 'uid=65532\n')
            self.assertEqual(execute.call_args.kwargs['secret'], SECRET)
        for edit in (lambda r: r.update(returncode=1), lambda r: r.update(executed=False),
                     lambda r: r['authentication']['authentication'].update(response_verified=False), lambda r: r.update(stdout='x' * 4097)):
            result = copy.deepcopy(accepted); edit(result)
            with patch('network_labs.appliances.telnet_radius.execute', return_value=result):
                self.assertIsNone(dispatch(manager, 'PC1', 'identity', 'learner', 'password'))

    def test_telnet_generation_never_borrows_an_ssh_worker_token(self):
        config = {'name': 'test', 'node': 'PC1', 'token': 'telnet-token', 'transport': 'telnet'}
        manager = BridgeManager(config)
        state = {'phase': 'running', 'ssh_radius_workers': {'PC1': {'token': 'telnet-token'}},
                 'telnet_radius_workers': {'PC1': {'token': 'stale'}}}
        with patch.object(Manager, 'read', return_value=state):
            with self.assertRaises(RuntimeFailure): manager.current()
            state['telnet_radius_workers']['PC1']['token'] = 'telnet-token'
            self.assertIs(manager.current(), state)
            state['phase'] = 'stopping'
            with self.assertRaises(RuntimeFailure): manager.current()

    def test_daemon_uses_an_explicit_no_new_privileges_pty_process(self):
        config = service_process(['telnetd'])
        self.assertTrue(config['noNewPrivileges']); self.assertIn('CAP_SETPCAP', config['capabilities']['bounding'])
        self.assertEqual(config['capabilities']['inheritable'], []); self.assertEqual(config['capabilities']['ambient'], [])
        self.assertNotIn('CAP_NET_ADMIN', config['capabilities']['effective'])
        with tempfile.TemporaryDirectory() as d:
            manager = self.manager(); manager.directory = Path(d)
            def execute(*args, **kwargs):
                process = json.loads(Path(args[3]).read_text())
                self.assertTrue(process['noNewPrivileges']); self.assertEqual(process['args'][-1], LOGIN)
            with patch.object(manager, 'crun', side_effect=execute): start_service(manager, manager.state['spec']['nodes'][0], 'telnet')
            self.assertFalse(list(Path(d).glob('telnet-process-*')))

    def test_cli_reference_requires_telnet_opt_in_and_rejects_shell_combinations(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, value in (('password', 'private-telnet-password'), ('secret', SECRET)):
                path = root / name; path.write_text(value); path.chmod(0o600)
            args = ['example', '--rootfs', '/rootfs', '--radius', '--radius-telnet', '--radius-roles', '--radius-user', 'learner',
                    '--radius-password-file', str(root / 'password'), '--radius-secret-file', str(root / 'secret')]
            with redirect_stdout(io.StringIO()) as output: self.assertEqual(main(args), 0)
            node = json.loads(output.getvalue())['nodes'][0]; self.assertTrue(node['management']['telnet_radius'])
            self.assertNotIn('private-telnet-password', output.getvalue())
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()): self.assertEqual(main(args + ['--radius-shell']), 1)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['example', '--rootfs', '/rootfs', '--radius-telnet']), 1)

    @unittest.skipUnless(shutil.which('cc'), 'C compiler required')
    def test_compiled_login_has_separate_identity_and_trusted_offline_copy_plan(self):
        with tempfile.TemporaryDirectory() as d:
            binary = Path(d) / 'telnet-login'
            subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', Path(__file__).parents[1] / 'network_labs/appliances/telnet_radius_login.c', '-o', binary], check=True, capture_output=True)
            self.assertEqual(subprocess.run([binary, '--version'], capture_output=True, text=True).stdout, 'Network LABS Telnet RADIUS login 1\n')
            self.assertIn((binary.resolve(), Path(LOGIN)), rootfs_assets(binary))
            # This environment has no privilege to switch UID. Fail closed before prompting.
            if os.geteuid() == 0 and 'CapEff:\t0000000000000000' in Path('/proc/self/status').read_text():
                denied = subprocess.run([binary, '-f', 'root'], input='identity\nroot\npassword\n', capture_output=True, text=True)
                self.assertEqual(denied.returncode, 125); self.assertEqual(denied.stdout, ''); self.assertEqual(denied.stderr, '')
