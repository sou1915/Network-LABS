"""Management configuration validates actual auth material and scoped listeners."""
import base64
import copy
import json
from pathlib import Path
import struct
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

    def test_incompatible_busybox_options_fail_before_any_service_is_launched(self):
        from network_labs.appliances.runtime import RuntimeFailure
        manager = Mock(); manager.state = {'spec': management_lab('/rootfs', KEY, HASH)}
        manager.crun.return_value.stdout = 'telnetd\nlogin\nsyslogd\nlogger\n'
        manager.crun.return_value.stderr = ''
        with self.assertRaises(RuntimeFailure): start_servers(manager)
        self.assertFalse(any('--detach' in c.args for c in manager.crun.call_args_list))
