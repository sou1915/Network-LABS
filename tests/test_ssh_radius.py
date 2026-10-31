"""RADIUS SSH bridge boundaries without substituting packet tests."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from contextlib import redirect_stdout, redirect_stderr
import socket
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.examples import radius_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.ssh_radius import dispatch, managed_secret, CLIENT
from network_labs.appliances.ssh_radius_worker import request
from test_native_management import KEY

SECRET = 'ssh-radius-private-fixture-secret'
DIGEST = hashlib.sha256(b'private-fixture-password').hexdigest()


class SSHRadiusTests(unittest.TestCase):
    def test_policy_requires_managed_matching_nas_and_restricted_ssh(self):
        spec = radius_lab('/rootfs', SECRET, DIGEST, ssh_key=KEY)
        source = spec['nodes'][0]
        self.assertEqual(managed_secret(spec, source), ('192.0.2.20', SECRET))
        for edit in (lambda s: s['nodes'][0]['management'].update(ssh_radius=1),
                     lambda s: s['nodes'][0]['management'].update(ssh_actions=None),
                     lambda s: s['nodes'][0].update(radius_access=None),
                     lambda s: s['nodes'][0]['radius_access'].update(server='192.0.2.99'),
                     lambda s: s['nodes'][2]['radius_server'].update(clients=[])):
            candidate = copy.deepcopy(spec); edit(candidate)
            with self.assertRaises(ValueError): validate(candidate)
        self.assertNotIn(SECRET, CLIENT)
        self.assertIn('read -r -n 129 password', CLIENT)

    def test_only_explicit_action_and_verified_accept_can_return_output(self):
        spec = radius_lab('/rootfs', SECRET, DIGEST, ssh_key=KEY)
        manager = Mock(); manager.state = {'phase': 'running', 'spec': spec}; manager.read.return_value = manager.state
        receipt = {'status': 'passed', 'executed': True, 'returncode': 0, 'stdout': 'uid=65532\n',
                   'authentication': {'status': 'passed', 'authentication': {
                       'response_verified': True, 'response_code': 2, 'decision': 'accepted'}}}
        with patch('network_labs.appliances.radius_exec.execute', return_value=receipt) as execute:
            self.assertEqual(dispatch(manager, 'PC1', 'identity', 'learner', 'password'), 'uid=65532\n')
            self.assertEqual(execute.call_args.kwargs['secret'], SECRET)
            for action in ('shell', 'identity; id', 'sftp'):
                execute.reset_mock()
                self.assertIsNone(dispatch(manager, 'PC1', action, 'learner', 'password'))
                execute.assert_not_called()
            for edit in (lambda r: r['authentication']['authentication'].update(response_verified=False),
                         lambda r: r.update(executed=False), lambda r: r.update(returncode=1),
                         lambda r: r.update(stdout='x' * 4097), lambda r: r.update(stdout=None)):
                invalid = copy.deepcopy(receipt); edit(invalid); execute.return_value = invalid
                self.assertIsNone(dispatch(manager, 'PC1', 'identity', 'learner', 'password'))
            spec['nodes'][0]['management']['ssh_actions'] = ['hostname']
            execute.reset_mock()
            self.assertIsNone(dispatch(manager, 'PC1', 'identity', 'learner', 'password'))
            execute.assert_not_called()

    def test_cli_generator_requires_explicit_combined_profile_and_keeps_password_out(self):
        from network_labs.appliances.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); key = root / 'key.pub'; key.write_text(KEY)
            password = root / 'password'; password.write_text('private-cli-password\n'); password.chmod(0o600)
            secret = root / 'secret'; secret.write_text(SECRET + '\n'); secret.chmod(0o600)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(['example', '--rootfs', '/rootfs', '--radius', '--radius-ssh',
                             '--ssh-authorized-key', str(key), '--ssh-action', 'hostname',
                             '--radius-user', 'learner', '--radius-password-file', str(password),
                             '--radius-secret-file', str(secret)])
            self.assertEqual(code, 0)
            spec = json.loads(stdout.getvalue())
            self.assertTrue(spec['nodes'][0]['management']['ssh_radius'])
            self.assertEqual(spec['nodes'][0]['management']['ssh_actions'], ['hostname'])
            self.assertNotIn('private-cli-password', stdout.getvalue())
            with redirect_stderr(io.StringIO()):
                self.assertNotEqual(main(['example', '--rootfs', '/rootfs', '--radius-ssh',
                                          '--ssh-authorized-key', str(key)]), 0)

    def test_generation_and_phase_are_rechecked_before_runtime_calls(self):
        from network_labs.appliances import runtime
        from network_labs.appliances.ssh_radius_worker import BridgeManager
        import subprocess
        spec = radius_lab('/rootfs', SECRET, DIGEST, ssh_key=KEY)
        state = {'phase': 'running', 'spec': spec, 'ssh_radius_workers': {'PC1': {'token': 'current'}}}
        with tempfile.TemporaryDirectory() as folder, patch.object(runtime, 'STATE_ROOT', Path(folder)):
            manager = BridgeManager({'name': spec['name'], 'node': 'PC1', 'token': 'current'})
            manager.directory.mkdir()
            path = manager.directory / 'state.json'; path.write_text(json.dumps(state))
            with patch.object(runtime, 'run', return_value=subprocess.CompletedProcess([], 0, '[]', '')) as run:
                manager.ns(0, 'ip', '-j', 'link'); run.assert_called_once()
                for change in ('generation', 'phase'):
                    candidate = copy.deepcopy(state)
                    if change == 'generation': candidate['ssh_radius_workers']['PC1']['token'] = 'recreated'
                    else: candidate['phase'] = 'stopping'
                    path.write_text(json.dumps(candidate)); run.reset_mock()
                    with self.assertRaises(runtime.RuntimeFailure): manager.crun('exec', 'PC1', '/bin/busybox', 'id')
                    run.assert_not_called()

    def test_wrong_namespace_cannot_change_a_sysctl_or_bind_a_listener(self):
        from network_labs.appliances.ssh_radius_worker import serve
        from types import SimpleNamespace
        with patch('os.geteuid', return_value=0), patch.object(Path, 'stat', return_value=SimpleNamespace(st_ino=7)), \
             patch.object(Path, 'write_text') as write, patch('socket.socket') as listener:
            with self.assertRaises(ValueError): serve({'namespace_inode': 8, 'namespace': '/run/netns/not-ours'})
            write.assert_not_called(); listener.assert_not_called()

    def test_request_framing_rejects_truncation_oversize_bad_utf8_and_version(self):
        # socketpair returns two sockets, each explicitly closed below.
        def frame(payload):
            reader, writer = socket.socketpair()
            try:
                writer.sendall(payload); writer.shutdown(socket.SHUT_WR)
                return request(reader)
            finally:
                reader.close(); writer.close()
        self.assertEqual(frame('NLSSH1\nidentity\nlearner\npässword\n'.encode()), ['identity', 'learner', 'pässword'])
        for payload in (b'NLSSH0\nidentity\nlearner\npassword\n', b'NLSSH1\nidentity\n',
                        b'NLSSH1\n' + b'x' * 33 + b'\nu\np\n',
                        b'NLSSH1\nidentity\n' + b'u' * 65 + b'\np\n',
                        b'NLSSH1\nidentity\nu\n' + b'p' * 129 + b'\n',
                        b'NLSSH1\nidentity\nu\n\xff\n'):
            with self.subTest(length=len(payload)), self.assertRaises(ValueError): frame(payload)
