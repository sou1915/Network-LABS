"""Scoped v2c policy, namespace telemetry view and secret/config boundaries."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from network_labs.appliances.examples import snmp_lab, dual_stack_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.snmp import config_text, prepare_files, observe, drift, command, rootfs_assets
from network_labs.appliances.service_adapters import adapters


class SNMPTests(unittest.TestCase):
    def test_reference_normalization_and_bounded_community_tokens(self):
        spec = snmp_lab('/rootfs')
        self.assertEqual(validate(copy.deepcopy(spec)), spec)
        self.assertEqual(len(spec['nodes']), 4)
        self.assertFalse(spec['nodes'][2]['forwarding'])
        for community in ('short', 'public\nRW', 'a' * 65, 'with space', '#comment', 3, 'é' * 8):
            bad = copy.deepcopy(spec); bad['nodes'][2]['snmp_agent']['community'] = community
            with self.subTest(community=community), self.assertRaises(ValueError): validate(bad)

    def test_managers_must_be_explicit_unambiguous_remote_managed_addresses(self):
        for managers in ([], ['*'], ['127.0.0.1'], ['224.0.0.1'], ['192.0.2.20'], ['192.0.2.99'], [3], ['192.0.2.10'] * 17):
            spec = snmp_lab('/rootfs'); spec['nodes'][2]['snmp_agent']['managers'] = managers
            with self.subTest(managers=managers), self.assertRaises(ValueError): validate(spec)
        spec = snmp_lab('/rootfs'); spec['nodes'][3]['interfaces']['eth0'] = '192.0.2.10/24'; spec['nodes'][3]['gateway'] = None
        with self.assertRaises(ValueError): validate(spec)
        spec = snmp_lab('/rootfs'); spec['nodes'][2]['snmp_agent']['managers'] *= 2
        self.assertEqual(validate(spec)['nodes'][2]['snmp_agent']['managers'], ['192.0.2.10'])

    def test_invalid_interfaces_startup_ipv6_and_live_edits_are_refused(self):
        for changes in ({'interface': 'eth9'}, {'interface': None}, {'version': '3'}):
            spec = snmp_lab('/rootfs'); spec['nodes'][2]['snmp_agent'].update(changes)
            with self.assertRaises(ValueError): validate(spec)
        for field, value in [('shutdown', ['eth0']), ('startup', [['/bin/echo', 'unmanaged']])]:
            spec = snmp_lab('/rootfs'); spec['nodes'][2][field] = value
            with self.assertRaises(ValueError): validate(spec)
        spec = dual_stack_lab('/rootfs'); spec['nodes'][1]['snmp_agent'] = {'interface': 'eth0', 'community': 'network-labs-ro', 'managers': ['192.0.2.10']}
        with self.assertRaises(ValueError): validate(spec)
        old = snmp_lab('/rootfs')['nodes'][2]; new = copy.deepcopy(old); new['snmp_agent']['community'] = 'changed-token'
        with self.assertRaises(ValueError): adapters(new, old)

    def test_vacm_is_v2c_only_read_only_and_excludes_host_resource_objects(self):
        node = snmp_lab('/rootfs')['nodes'][2]; text = config_text(node)
        self.assertIn('agentAddress udp:192.0.2.20:161', text)
        self.assertIn('com2sec NetworkLabsSecurity 192.0.2.10 network-labs-ro', text)
        self.assertIn('group NetworkLabsGroup v2c NetworkLabsSecurity', text)
        self.assertIn('access NetworkLabsGroup "" v2c noauth exact NetworkLabsView none none', text)
        self.assertNotIn(' v1 ', text); self.assertNotIn('rwcommunity', text)
        self.assertIn('[snmp] persistentDir /run/snmp', text)
        for excluded in ('.1.3.6.1.2.1.25', '.1.3.6.1.4.1', 'extend ', 'exec ', 'pass ', 'master agentx'):
            self.assertNotIn(excluded, text)
        args = command(); self.assertIn('-C', args); self.assertEqual(args[0], '/usr/lib/network-labs/snmpd')
        self.assertNotIn('hr_system', args[-1]); self.assertNotIn('disk', args[-1])

    def test_sensitive_config_permissions_and_audit_without_community_disclosure(self):
        node = snmp_lab('/rootfs')['nodes'][2]
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder); (bundle / 'files').mkdir(); prepare_files(bundle, node)
            path = bundle / 'files/snmpd.conf'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_text(), config_text(node))
        with patch('network_labs.appliances.snmp.observe_config', return_value={'configuration_verified': True}):
            report = observe(Mock(), node); self.assertEqual(drift(Mock(), node), [])
            self.assertNotIn('network-labs-ro', json.dumps(report))
            self.assertIn('not daemon liveness', report['note'])
        with patch('network_labs.appliances.snmp.observe_config', return_value={'configuration_verified': False}):
            self.assertTrue(drift(Mock(), node))

    def test_rootfs_uses_trusted_elf_dependency_plan_and_actual_identity_probe(self):
        with patch('network_labs.appliances.dns_rootfs.assets', return_value=[]) as assets:
            rootfs_assets('/trusted/snmpd')
            options = assets.call_args.kwargs
            self.assertEqual(options['destination'], '/usr/lib/network-labs/snmpd')
            self.assertTrue(options['version_check'](Mock(returncode=0, stdout='', stderr='NET-SNMP version: 5.9.4')))
            self.assertFalse(options['version_check'](Mock(returncode=0, stdout='not snmp', stderr='')))


class SNMPv3Tests(unittest.TestCase):
    def setUp(self):
        from network_labs.appliances.snmp import usm_credentials
        from network_labs.appliances.examples import snmpv3_lab
        self.user = usm_credentials('monitor', 'native-auth-password', 'native-privacy-password')
        self.spec = snmpv3_lab('/rootfs', self.user)
        self.node = self.spec['nodes'][2]

    def test_master_key_derivation_is_bounded_and_input_secrets_are_not_declarations(self):
        from network_labs.appliances.snmp import master_key
        self.assertEqual(len(master_key('native-auth-password')), 64)
        self.assertNotEqual(self.user['auth_master_key'], self.user['privacy_master_key'])
        for invalid in ('short', 'x' * 129, 'é' * 8, 'password\nline', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): master_key(invalid)
        self.assertNotIn('native-auth-password', json.dumps(self.spec))
        self.assertNotIn('native-privacy-password', json.dumps(self.spec))

    def test_usm_validation_rejects_plaintext_bad_keys_unknown_algorithms_and_mode_mixing(self):
        for update in ({'username': 'bad user'}, {'username': 'x' * 33}, {'auth_master_key': 'plaintext'},
                       {'privacy_master_key': 'a' * 63}, {'algorithm': 'MD5'}):
            spec = copy.deepcopy(self.spec); spec['nodes'][2]['snmp_agent']['usm'].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)
        spec = copy.deepcopy(self.spec); spec['nodes'][2]['snmp_agent']['community'] = 'network-labs-ro'
        with self.assertRaises(ValueError): validate(spec)
        spec = copy.deepcopy(self.spec); spec['nodes'][2]['snmp_agent']['usm'] = None
        with self.assertRaises(ValueError): validate(spec)
        self.assertEqual(validate(copy.deepcopy(self.spec)), self.spec)

    def test_v3_requires_privacy_has_source_filter_and_no_community_fallback(self):
        text = config_text(self.node)
        self.assertIn('sourceFilterType acceptlist', text)
        self.assertIn('sourceFilterAddress 192.0.2.10', text)
        self.assertIn('createUser monitor SHA-256 -m 0x', text)
        self.assertIn(' AES -m 0x', text)
        self.assertIn('access NetworkLabsGroup "" usm priv exact NetworkLabsView none none', text)
        self.assertNotIn(' v2c ', text); self.assertNotIn('com2sec ', text)

    def test_runtime_engine_identity_is_required_not_stored_in_saved_policy(self):
        from network_labs.appliances.snmp import start_server
        with self.assertRaises(ValueError): command(self.node)
        with self.assertRaises(ValueError): command(self.node, 'not-an-engine-token')
        manager = Mock(); manager.directory = Path('/tmp/snmp-test')
        start_server(manager, self.node); start_server(manager, self.node)
        launches = [c for c in manager.crun.call_args_list if '--detach' in c.args]
        identities = [next(arg for arg in c.args if arg.startswith('--engineID=')) for c in launches]
        self.assertNotEqual(*identities)
        self.assertIn(',usmConf', command(self.node, 'a' * 24)[-2])
        self.assertNotIn('engineID', config_text(self.node))
        self.assertNotIn('engine_id', json.dumps(self.spec))

    def test_inspection_does_not_disclose_usm_keys_and_client_config_keeps_algorithms(self):
        from network_labs.appliances.snmp import client_config
        with patch('network_labs.appliances.snmp.observe_config', return_value={'configuration_verified': True}):
            report = observe(Mock(), self.node)
        self.assertEqual(report['version'], '3'); self.assertEqual(report['security']['level'], 'authPriv')
        for key in (self.user['auth_master_key'], self.user['privacy_master_key']): self.assertNotIn(key, json.dumps(report))
        text = client_config(self.user)
        self.assertIn('defAuthType SHA-256', text); self.assertIn('defPrivType AES', text)
        self.assertIn('defSecurityLevel authPriv', text)
        self.assertNotIn('native-auth-password', text)
        self.assertIn('defAuthMasterKey 0x' + self.user['auth_master_key'], text)

    def test_v2c_rendered_policy_remains_compatible(self):
        node = snmp_lab('/rootfs')['nodes'][2]; text = config_text(node)
        self.assertLess(text.index('com2sec '), text.index('group '))
        self.assertLess(text.index('group '), text.index('view '))
        self.assertLess(text.index('view '), text.index('access '))
        self.assertNotIn('usm', text); self.assertNotIn('usmConf', command()[-1])
