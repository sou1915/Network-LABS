"""Role grants preserve default denial, transport ceilings and durable policy pins."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch

from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import radius_lab, dual_stack_radius_lab
from network_labs.appliances.radius_access import allowed_actions, authorize, authorization
from network_labs.appliances.radius_exec import execute
from network_labs.appliances.radius_login import login
from network_labs.appliances import radius_outbox as outbox
from network_labs.appliances.runtime import Manager
from network_labs.appliances.spec import validate
from network_labs.appliances.ssh_radius import dispatch
from test_native_management import KEY

SECRET = 'roles-private-accounting-secret'


class RadiusRolesTests(unittest.TestCase):
    def spec(self):
        return radius_lab('/rootfs', SECRET, 'a' * 64, role_policy=True)

    def manager(self, spec=None):
        manager = Manager('role-test'); manager.state = {'phase': 'running', 'spec': spec or self.spec()}
        return manager

    def test_role_union_is_explicit_and_canonical_without_materialized_direct_grants(self):
        spec = self.spec(); policy = spec['nodes'][0]['radius_access']
        self.assertNotIn('users', policy)
        self.assertEqual(allowed_actions(policy, 'learner'), ['hostname', 'identity', 'security-context'])
        self.assertEqual(authorization(policy, 'learner')['roles'], ['auditor', 'observer'])
        self.assertEqual(allowed_actions(policy, 'unknown'), [])
        self.assertNotIn('shell', allowed_actions(policy, 'learner'))
        self.assertEqual(spec, validate(spec))
        policy['user_roles']['viewer'] = ['observer']
        policy['user_roles']['learner'] = ['auditor']
        normalized = validate(spec); manager = self.manager(normalized)
        self.assertIsNone(authorize(manager, 'PC1', '192.0.2.20', 'learner', 'security-context'))
        self.assertEqual(authorize(manager, 'PC1', '192.0.2.20', 'learner', 'identity'), 'ACTION_NOT_ALLOWED')
        self.assertEqual(authorize(manager, 'PC1', '192.0.2.20', 'viewer', 'security-context'), 'ACTION_NOT_ALLOWED')
        self.assertEqual(authorize(manager, 'PC1', '192.0.2.99', 'viewer', 'identity'), 'SERVER_NOT_ALLOWED')

    def test_ambiguous_unknown_recursive_duplicate_and_unbounded_roles_are_rejected(self):
        faults = [
            {'users': {'learner': ['shell']}}, {'roles': {}}, {'roles': {'bad role': ['identity']}},
            {'roles': {'x' * 33: ['identity']}}, {'roles': {'observer': ['observer']}},
            {'roles': {'observer': ['identity', 'identity']}}, {'roles': {'observer': []}},
            {'roles': {'r' + str(i): ['identity'] for i in range(17)}},
            {'user_roles': {}}, {'user_roles': {'bad user': ['observer']}},
            {'user_roles': {'learner': ['missing']}}, {'user_roles': {'learner': []}},
            {'user_roles': {'learner': ['observer', 'observer']}}, {'user_roles': {'learner': 'observer'}},
            {'user_roles': {'learner': [True]}}, {'user_roles': {'u' + str(i): ['observer'] for i in range(17)}},
            {'roles': None}, {'user_roles': None}, {'roles': {'observer': [None]}},
        ]
        for fault in faults:
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                spec = self.spec(); spec['nodes'][0]['radius_access'].update(fault); validate(spec)
        for key in ('roles', 'user_roles'):
            spec = self.spec(); del spec['nodes'][0]['radius_access'][key]
            with self.assertRaises(ValueError): validate(spec)
        # Defensive resolution never treats malformed stored state as extra grants.
        for policy in ({'roles': {'a': ['shell']}, 'user_roles': {'x': ['a', 'missing']}},
                       {'roles': {'a': ['shell']}, 'user_roles': {'x': ['a']}, 'users': {'x': ['shell']}},
                       {'roles': {}, 'user_roles': {'x': [None]}}, {'users': {'x': 'shell'}}):
            self.assertEqual(allowed_actions(policy, 'x'), [])

    def test_local_denials_precede_authentication_session_creation_and_execution(self):
        manager = self.manager(); policy = manager.state['spec']['nodes'][0]['radius_access']
        policy['user_roles']['learner'] = ['observer']
        with patch('network_labs.appliances.radius_exec.probe') as probe, \
                patch('network_labs.appliances.radius_login.probe') as shell_probe, \
                patch('network_labs.appliances.radius_login.SessionGroup') as groups, \
                patch.object(manager, 'crun') as crun:
            denied = execute(manager, 'PC1', '192.0.2.20', action='security-context', username='learner', password='password', secret=SECRET)
            self.assertEqual(denied['error'], 'ACTION_NOT_ALLOWED'); self.assertIsNone(denied['authentication'])
            shell = login(manager, 'PC1', '192.0.2.20', username='learner', password='password', secret=SECRET)
            self.assertEqual(shell['error'], 'ACTION_NOT_ALLOWED')
            probe.assert_not_called(); shell_probe.assert_not_called(); groups.assert_not_called(); crun.assert_not_called()

    def test_valid_role_still_requires_verified_radius_accept(self):
        manager = self.manager()
        for response in ({'status': 'failed'}, {'status': 'passed', 'authentication': {'response_verified': False, 'response_code': 2, 'decision': 'accepted'}}):
            with patch('network_labs.appliances.radius_exec.probe', return_value=response), patch.object(manager, 'crun') as crun:
                result = execute(manager, 'PC1', '192.0.2.20', action='identity', username='learner', password='password', secret=SECRET)
                self.assertFalse(result['executed']); crun.assert_not_called()
                self.assertEqual(result['authorization']['roles'], ['auditor', 'observer'])

    def test_ssh_node_allowlist_remains_an_independent_ceiling(self):
        spec = radius_lab('/rootfs', SECRET, 'a' * 64, role_policy=True, ssh_key=KEY, ssh_actions=['hostname'])
        manager = self.manager(spec)
        with patch('network_labs.appliances.radius_exec.execute') as executor:
            self.assertIsNone(dispatch(manager, 'PC1', 'identity', 'learner', 'password')); executor.assert_not_called()
        spec['nodes'][0]['radius_access']['user_roles']['learner'] = ['auditor']
        with patch('network_labs.appliances.radius_exec.probe') as probe:
            self.assertIsNone(dispatch(manager, 'PC1', 'hostname', 'learner', 'password')); probe.assert_not_called()

    def test_role_edits_invalidate_stop_binding_and_removing_shell_blocks_delivery(self):
        spec = radius_lab('/rootfs', SECRET, 'a' * 64, role_policy=True, allow_shell=True, accounting=True, accounting_outbox=True)
        with tempfile.TemporaryDirectory() as d, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(d) / 'saved'):
            manager = self.manager(spec)
            record = outbox.enqueue(manager, 'PC1', '192.0.2.20', 'learner', SECRET, 'aaa-' + 'a' * 32, 1, 9, 1, cleanup_complete=True)
            policy = manager.state['spec']['nodes'][0]['radius_access']; original = copy.deepcopy(policy)
            for edit in ('definition', 'assignment'):
                policy.clear(); policy.update(copy.deepcopy(original))
                if edit == 'definition': policy['roles']['session'].append('hostname')
                else: policy['user_roles']['learner'].remove('session')
                with patch('network_labs.appliances.radius_accounting.send') as send:
                    result = outbox.flush(manager); self.assertEqual(result['attempted'], 0); send.assert_not_called()
                self.assertEqual(outbox.pending(manager)['pending'], 1)
            policy.clear(); policy.update(original)
            self.assertEqual(outbox.binding(manager, 'PC1', 'learner')[2], record['policy_sha256'])

    def test_roles_do_not_bypass_the_existing_dual_stack_shell_exclusion(self):
        spec = dual_stack_radius_lab('/rootfs', SECRET, 'a' * 64, ssh_key=KEY)
        access = spec['nodes'][0]['radius_access']; access.pop('users')
        access.update(roles={'hidden': ['shell']}, user_roles={'learner': ['hidden']})
        with self.assertRaises(ValueError): validate(spec)

    def test_cli_role_example_is_opt_in_and_never_implicitly_grants_shell(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, value in (('password', 'private-role-password'), ('secret', SECRET)):
                p = root / name; p.write_text(value); p.chmod(0o600)
            args = ['example', '--radius', '--radius-roles', '--rootfs', '/rootfs', '--radius-user', 'learner',
                    '--radius-password-file', str(root / 'password'), '--radius-secret-file', str(root / 'secret')]
            with redirect_stdout(io.StringIO()) as output: self.assertEqual(main(args), 0)
            policy = json.loads(output.getvalue())['nodes'][0]['radius_access']
            self.assertNotIn('shell', allowed_actions(policy, 'learner')); self.assertNotIn('users', policy)
            with redirect_stdout(io.StringIO()) as output: self.assertEqual(main(args + ['--radius-shell']), 0)
            self.assertIn('shell', allowed_actions(json.loads(output.getvalue())['nodes'][0]['radius_access'], 'learner'))
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['example', '--rootfs', '/rootfs', '--radius-roles']), 1)
        self.assertIn('users', radius_lab('/rootfs', SECRET, 'a' * 64)['nodes'][0]['radius_access'])
