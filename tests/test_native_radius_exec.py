import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.radius_exec import execute


class RadiusExecTests(unittest.TestCase):
    def call(self, manager, **options):
        return execute(manager, 'PC1', '192.0.2.20', action='identity', username='learner',
                       password='private-password', secret='private-shared-secret', **options)

    def test_only_verified_accept_can_reach_executor(self):
        for status, code, verified in [('failed', 3, True), ('blocked', 11, True),
                                       ('unknown', None, False), ('passed', 2, False)]:
            manager = Mock()
            with patch('network_labs.appliances.radius_exec.probe', return_value={
                    'status': status, 'authentication': {'response_code': code,
                    'response_verified': verified, 'decision': 'accepted'}}):
                self.assertFalse(self.call(manager)['executed'])
            manager.crun.assert_not_called()

    def test_accepted_execution_is_private_nonroot_and_capability_free(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Mock(); manager.directory = Path(folder)
            def crun(*args, **kwargs):
                self.assertEqual(args[:2], ('exec', '--process'))
                path = Path(args[2]); self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                process = json.loads(path.read_text())
                self.assertEqual(process['user'], {'uid': 65532, 'gid': 65532, 'additionalGids': []})
                self.assertTrue(process['noNewPrivileges'])
                self.assertTrue(all(value == [] for value in process['capabilities'].values()))
                self.assertNotIn('private-', path.read_text())
                self.assertEqual(kwargs['input_text'], '')
                self.assertEqual(kwargs['timeout'], 5)
                return subprocess.CompletedProcess([], 0, 'uid=65532 gid=65532\n', '')
            manager.crun.side_effect = crun
            with patch('network_labs.appliances.radius_exec.probe', return_value={
                    'status': 'passed', 'authentication': {'response_code': 2,
                    'response_verified': True, 'decision': 'accepted'}}):
                result = self.call(manager)
            self.assertEqual(result['status'], 'passed'); self.assertTrue(result['executed'])
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_unknown_action_never_authenticates(self):
        with patch('network_labs.appliances.radius_exec.probe') as auth:
            with self.assertRaises(ValueError):
                execute(Mock(), 'PC1', '192.0.2.20', action='/bin/sh', username='x', password='x', secret='x')
            auth.assert_not_called()
