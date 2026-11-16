import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.radius_exec import execute


class RadiusExecTests(unittest.TestCase):
    def manager(self):
        manager = Mock()
        manager.read.return_value = {'phase': 'running', 'spec': {'nodes': [{'name': 'PC1',
            'radius_access': {'server': '192.0.2.20', 'users': {'learner': ['identity']}}}]}}
        return manager

    def call(self, manager, **options):
        return execute(manager, 'PC1', '192.0.2.20', action='identity', username='learner',
                       password='private-password', secret='private-shared-secret', **options)

    def test_only_verified_accept_can_reach_executor(self):
        for status, code, verified in [('failed', 3, True), ('blocked', 11, True),
                                       ('unknown', None, False), ('passed', 2, False)]:
            manager = self.manager()
            with patch('network_labs.appliances.radius_exec.probe', return_value={
                    'status': status, 'authentication': {'response_code': code,
                    'response_verified': verified, 'decision': 'accepted'}}):
                self.assertFalse(self.call(manager)['executed'])
            manager.crun.assert_not_called()

    def test_accepted_execution_is_private_nonroot_and_capability_free(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(); manager.directory = Path(folder)
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

    def test_local_policy_denials_never_contact_radius_or_execute(self):
        for fault, expected in [('missing', 'NO_ACCESS_POLICY'), ('server', 'SERVER_NOT_ALLOWED'),
                                ('user', 'ACTION_NOT_ALLOWED'), ('action', 'ACTION_NOT_ALLOWED')]:
            with self.subTest(fault=fault):
                manager = self.manager(); node = manager.read.return_value['spec']['nodes'][0]
                if fault == 'missing': node.pop('radius_access')
                elif fault == 'server': node['radius_access']['server'] = '192.0.2.30'
                elif fault == 'user': node['radius_access']['users'] = {'other': ['identity']}
                else: node['radius_access']['users']['learner'] = ['hostname']
                with patch('network_labs.appliances.radius_exec.probe') as auth:
                    result = self.call(manager)
                self.assertEqual(result['error'], expected); self.assertFalse(result['executed'])
                auth.assert_not_called(); manager.crun.assert_not_called()

    def test_policy_schema_rejects_ambiguous_servers_users_and_actions(self):
        import copy
        from network_labs.appliances.spec import example, validate
        base = {'server': '192.0.2.20', 'users': {'learner': ['identity']}}
        for change in ({'server': 'localhost'}, {'server': '::1'}, {'server': '127.0.0.1'},
                       {'server': '192.0.2.10'}, {'server': 3221226004}, {'users': {}},
                       {'users': {'bad user': ['identity']}}, {'users': {'learner': ['root-shell']}},
                       {'users': {'learner': ['identity', 'identity']}}, {'secret': 'unexpected'},
                       {'session_seconds': True}, {'session_seconds': 0}, {'session_seconds': 3601}):
            spec = example('/rootfs'); spec['nodes'][0]['radius_access'] = {**copy.deepcopy(base), **change}
            with self.subTest(change=change), self.assertRaises(ValueError): validate(spec)
        spec = example('/rootfs'); spec['nodes'][0]['radius_access'] = base
        normalized = validate(spec)
        self.assertEqual(normalized, validate(normalized))
