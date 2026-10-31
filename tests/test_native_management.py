"""Management configuration validates actual auth material and scoped listeners."""
import base64
import copy
import json
from pathlib import Path
import struct
import os
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from network_labs.appliances.examples import management_lab, dual_stack_lab
from network_labs.appliances.management import public_key, commands, prepare_files, drift, start_servers
from network_labs.appliances.spec import validate
from network_labs.appliances.service_adapters import adapters
from network_labs.appliances.runtime import oci_config

KEY = 'ssh-ed25519 ' + base64.b64encode(struct.pack('!I', 11) + b'ssh-ed25519' + struct.pack('!I', 32) + bytes(range(32))).decode()
HASH = '$6$NetworkLABS$' + 'a' * 86


class ManagementTests(unittest.TestCase):
    def test_example_and_raw_manifest_validate_without_startup_default(self):
        spec = management_lab('/rootfs', KEY, HASH)
        self.assertEqual(spec['nodes'][2]['name'], 'R1')
        self.assertEqual(validate(copy.deepcopy(spec)), spec)
        del spec['nodes'][2]['startup']
        self.assertEqual(validate(spec)['nodes'][2]['management']['ssh_keys'], [KEY])
        self.assertFalse(spec['nodes'][2]['forwarding'])

    def test_public_key_options_private_data_bad_lengths_and_bad_passwords_rejected(self):
        self.assertEqual(public_key(KEY + ' test-comment'), KEY)
        for key in ('-----BEGIN OPENSSH PRIVATE KEY-----', 'command="id" ' + KEY, KEY + '\n' + KEY,
                    'ssh-ed25519 !!', 'ssh-rsa AAAA', 'ssh-ed25519 ' + base64.b64encode(b'bad').decode()):
            with self.assertRaises(ValueError): public_key(key)
        for password in ('plaintext', '$1$salt$md5', HASH + '\n', '$6$rounds=9999999$NetworkLABS$' + 'a' * 86):
            spec = management_lab('/rootfs', KEY)
            spec['nodes'][2]['management']['telnet_password_hash'] = password
            with self.assertRaises(ValueError): validate(spec)

    def test_missing_down_unnumbered_remote_self_or_unknown_fields_are_rejected(self):
        for changes in ({'interface': 'eth9'}, {'ssh_keys': [KEY] * 17}, {'syslog_remote': '192.0.2.20'},
                        {'syslog_remote': '203.0.113.100'}, {'syslog_remote': '224.0.0.1'}, {'unknown': True}):
            spec = management_lab('/rootfs', KEY); spec['nodes'][2]['management'].update(changes)
            with self.assertRaises(ValueError): validate(spec)
        spec = management_lab('/rootfs', KEY); spec['nodes'][2]['shutdown'] = ['eth0']
        with self.assertRaises(ValueError): validate(spec)
        spec = dual_stack_lab('/rootfs'); spec['nodes'][0]['management'] = {'interface': 'eth0', 'ssh_keys': [KEY]}
        with self.assertRaises(ValueError): validate(spec)
        old = management_lab('/rootfs', KEY)['nodes'][2]; new = copy.deepcopy(old); new['management']['ssh_keys'] = []
        with self.assertRaises(ValueError): adapters(new, old)

    def test_real_daemon_arguments_bind_node_address_disable_ssh_password_and_bound_syslog(self):
        node = management_lab('/rootfs', KEY, HASH)['nodes'][2]; args = commands(node)
        self.assertEqual(args['ssh'][0], '/usr/sbin/dropbear')
        self.assertIn('192.0.2.20:22', args['ssh'])
        for flag in ('-s', '-w', '-j', '-k'): self.assertIn(flag, args['ssh'])
        self.assertIn('/bin/login', args['telnet']); self.assertIn('192.0.2.20', args['telnet'])
        self.assertIn('192.0.2.10:514', args['syslog']); self.assertIn('64', args['syslog'])
        config = oci_config({'name': 'test'}, node, 2, Path('/run/test/R1/rootfs'))
        mounts = {m['destination']: m for m in config['mounts']}
        for path in ('/etc/passwd', '/home/lab/.ssh/authorized_keys'):
            self.assertIn('ro', mounts[path]['options'])

    def test_managed_files_preserve_existing_accounts_and_audit_active_auth_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            rootfs = Path(folder) / 'rootfs'; (rootfs / 'etc').mkdir(parents=True)
            (rootfs / 'etc/group').write_text('root:x:0:\n')
            (rootfs / 'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n_lldpd:x:65534:65534::/run:/bin/sh\n')
            node = management_lab(rootfs, KEY, HASH)['nodes'][2]
            bundle = Path(folder) / 'bundle'; (bundle / 'files').mkdir(parents=True)
            prepare_files(bundle, node)
            passwd = (bundle / 'files/management-passwd').read_text()
            self.assertIn('_lldpd:', passwd); self.assertIn('lab:' + HASH + ':65532:65532:', passwd)
            self.assertEqual((bundle / 'files/authorized_keys').read_text(), KEY + '\n')
            self.assertEqual(json.loads((bundle / 'files/management.json').read_text())['commands'], commands(node))
            with patch('network_labs.appliances.management.observe_config', return_value={'configuration_verified': True}) as read:
                self.assertEqual(drift(Mock(), node), [])
                self.assertTrue(any(c.args[2] == '/etc/passwd' for c in read.call_args_list))
                self.assertTrue(any(c.args[2] == '/home/lab/.ssh/authorized_keys' for c in read.call_args_list))
            with patch('network_labs.appliances.management.observe_config', return_value={'configuration_verified': False}):
                self.assertTrue(drift(Mock(), node))

    def test_restricted_ssh_policy_validation_and_generated_forced_command(self):
        from network_labs.appliances.management import managed_files
        from network_labs.appliances.ssh_access import dispatcher, KEY_OPTIONS
        for actions in ('identity', ['shell'], ['identity', 'identity'], [True], {'identity': True}):
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                management_lab('/rootfs', KEY, ssh_actions=actions)
        with self.assertRaises(ValueError): management_lab('/rootfs', KEY, HASH, ssh_actions=['identity'])
        with self.assertRaises(ValueError): management_lab('/rootfs', ssh_actions=['identity'])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'etc').mkdir()
            (root / 'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n')
            (root / 'etc/group').write_text('root:x:0:\n')
            node = management_lab(root, KEY, ssh_actions=['identity'])['nodes'][2]
            files = managed_files(node)
            self.assertEqual(files['authorized_keys'], KEY_OPTIONS + ' ' + KEY + '\n')
            self.assertEqual(files['ssh-dispatch.sh'], dispatcher(['identity']))
            node['management']['ssh_actions'] = []
            self.assertIn('exit 126', managed_files(node)['ssh-dispatch.sh'])

    def test_dispatcher_treats_client_requests_as_exact_action_names(self):
        from network_labs.appliances.ssh_access import dispatcher
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); marker = root / 'bypass'; script = root / 'dispatch.sh'
            script.write_text(dispatcher(['identity']).replace('/bin/busybox id', "printf 'ID-OK\\n'"))
            for command in ('', '/bin/sh', 'hostname', 'sftp', 'scp -t /tmp/file', 'identity --help',
                            'identity; touch ' + str(marker), 'identity\ntouch ' + str(marker),
                            '$(touch ' + str(marker) + ')'):
                result = subprocess.run(['sh', str(script)], env={**os.environ, 'SSH_ORIGINAL_COMMAND': command},
                                        capture_output=True, text=True, timeout=2)
                self.assertEqual(result.returncode, 126, result)
                self.assertEqual(result.stdout, '')
                self.assertFalse(marker.exists())
            allowed = subprocess.run(['sh', str(script)], env={**os.environ, 'SSH_ORIGINAL_COMMAND': 'identity'},
                                     capture_output=True, text=True, timeout=2)
            self.assertEqual(allowed.returncode, 0, allowed)
            self.assertEqual(allowed.stdout, 'ID-OK\n')

    def test_restricted_ssh_permission_drift_is_not_reported_as_verified(self):
        from network_labs.appliances.management import observe
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'etc').mkdir()
            (root / 'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n')
            (root / 'etc/group').write_text('root:x:0:\n')
            node = management_lab(root, KEY, ssh_actions=['identity'])['nodes'][2]
            manager = Mock()
            with patch('network_labs.appliances.management.observe_config', return_value={'configuration_verified': True}):
                manager.crun.return_value = subprocess.CompletedProcess([], 0, '755:0:0\n755:0:0\n755:0:0\n644:0:0\n', '')
                self.assertTrue(observe(manager, node)['configuration_verified'])
                manager.crun.return_value = subprocess.CompletedProcess([], 0, '755:0:0\n777:0:0\n755:0:0\n644:0:0\n', '')
                self.assertFalse(observe(manager, node)['configuration_verified'])
                manager.crun.side_effect = subprocess.TimeoutExpired('stat', 3)
                self.assertFalse(observe(manager, node)['configuration_verified'])

    def test_restricted_daemon_exec_uses_explicit_privilege_config(self):
        from network_labs.appliances.management import start_service
        node = management_lab('/rootfs', KEY, ssh_actions=['identity'])['nodes'][2]
        manager = Mock()
        with tempfile.TemporaryDirectory() as folder:
            manager.directory = Path(folder)
            def launch(*args, **kwargs):
                self.assertEqual(args[:3], ('exec', '--detach', '--process'))
                path = Path(args[3]); self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                process = json.loads(path.read_text())
                self.assertTrue(process['noNewPrivileges'])
                self.assertEqual(process['user'], {'uid': 0, 'gid': 0, 'additionalGids': []})
                self.assertEqual(process['args'], commands(node)['ssh'])
                for name in ('bounding', 'effective', 'permitted'):
                    self.assertEqual(set(process['capabilities'][name]), {'CAP_SETUID', 'CAP_SETGID', 'CAP_NET_BIND_SERVICE'})
                self.assertEqual(process['capabilities']['inheritable'], [])
                self.assertEqual(process['capabilities']['ambient'], [])
            manager.crun.side_effect = launch
            start_service(manager, node, 'ssh')
            self.assertFalse(list(manager.directory.glob('ssh-process-*')))

    def test_incompatible_busybox_options_fail_before_any_service_is_launched(self):
        from network_labs.appliances.runtime import RuntimeFailure
        manager = Mock(); manager.state = {'spec': management_lab('/rootfs', KEY, HASH)}
        manager.crun.return_value.stdout = 'telnetd\nlogin\nsyslogd\nlogger\n'
        manager.crun.return_value.stderr = ''
        with self.assertRaises(RuntimeFailure): start_servers(manager)
        self.assertFalse(any('--detach' in c.args for c in manager.crun.call_args_list))
