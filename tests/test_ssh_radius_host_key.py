"""Pinned server identity composed with diagnostic-only RADIUS authorization."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.spec import validate
from test_native_management import KEY as PUBLIC


class SSHRadiusHostKeyTests(unittest.TestCase):
    def profile(self,**options):
        with patch('network_labs.appliances.ssh_host_key.read_identity',return_value=(b'fixture',PUBLIC)):
            return radius_lab('/rootfs','example-radius-secret','a'*64,ssh_key=PUBLIC,ssh_host_key_file='/offline/key',**options)

    def test_direct_and_role_diagnostics_preserve_explicit_identity(self):
        for role_policy in (False,True):
            spec=self.profile(role_policy=role_policy)
            self.assertEqual(validate(copy.deepcopy(spec)),spec)
            config=spec['nodes'][0]['management']
            self.assertTrue(config['ssh_radius']);self.assertEqual(config['ssh_host_key']['public_key'],PUBLIC)
            self.assertFalse(spec['nodes'][0]['radius_access']['accounting'])

    def test_shell_accounting_unselected_aaa_and_malformed_grants_remain_refused(self):
        for fault in ('shell','role-shell','accounting','unselected','malformed'):
            spec=self.profile(role_policy=fault=='role-shell');node=spec['nodes'][0]
            if fault=='shell':node['radius_access']['users']['learner'].append('shell')
            if fault=='role-shell':node['radius_access']['roles']['observer'].append('shell')
            if fault=='accounting':node['radius_access']['accounting']=True
            if fault=='unselected':node['management']['ssh_radius']=False
            if fault=='malformed':node['radius_access']['users']=None
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)
        for option in ({'allow_shell':True},{'ssh_shell':True},{'accounting':True}):
            with self.subTest(option=option),self.assertRaises(ValueError):self.profile(**option)

    def test_cli_emits_pinned_diagnostic_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'client.pub').write_text(PUBLIC)
            (root/'password').write_text('test-password');(root/'secret').write_text('example-radius-secret')
            with patch('network_labs.appliances.ssh_host_key.read_identity',return_value=(b'fixture',PUBLIC)),redirect_stdout(io.StringIO()) as output:
                code=main(['example','--rootfs','/rootfs','--radius','--radius-ssh','--radius-user','learner',
                    '--radius-password-file',str(root/'password'),'--radius-secret-file',str(root/'secret'),
                    '--ssh-authorized-key',str(root/'client.pub'),'--ssh-action','identity','--ssh-host-key-file','/offline/key'])
            self.assertEqual(code,0)
            config=json.loads(output.getvalue())['nodes'][0]['management']
            self.assertEqual(config['ssh_host_key']['file'],'/offline/key');self.assertTrue(config['ssh_radius'])
