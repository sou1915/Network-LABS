"""Pinned IPv4 shell requires the complete durable accounting lifecycle."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.spec import validate
from test_native_management import KEY as PUBLIC


class SSHShellHostKeyTests(unittest.TestCase):
    def profile(self,**options):
        with patch('network_labs.appliances.ssh_host_key.read_identity',return_value=(b'fixture',PUBLIC)):
            return radius_lab('/rootfs','example-radius-secret','a'*64,ssh_key=PUBLIC,ssh_shell=True,
                accounting=True,accounting_outbox=True,accounting_journal=True,ssh_host_key_file='/offline/key',**options)

    def test_complete_shell_lifecycle_supports_direct_and_role_grants(self):
        for roles in (False,True):
            spec=self.profile(role_policy=roles);self.assertEqual(validate(copy.deepcopy(spec)),spec)
            node=spec['nodes'][0];self.assertIn('shell',node['management']['ssh_actions'])
            self.assertTrue(all(node['radius_access'][k] for k in ('accounting','accounting_outbox','accounting_journal')))
            self.assertEqual(node['management']['ssh_host_key']['public_key'],PUBLIC)

    def test_partial_lifecycle_and_unselected_shell_never_admit_pinned_shell(self):
        for fault in ('accounting','accounting_outbox','accounting_journal','unselected','ipv6'):
            spec=self.profile();node=spec['nodes'][0]
            if fault in ('accounting','accounting_outbox','accounting_journal'):node['radius_access'][fault]=False
            if fault=='unselected':node['management']['ssh_actions'].remove('shell')
            if fault=='ipv6':node['ipv6']={'eth0':'2001:db8:10::10/64'};node['management']['ssh_ipv6']=True
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)

    def test_cli_requires_explicit_shell_and_full_accounting_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,value in (('password','test-password'),('secret','example-radius-secret'),('client.pub',PUBLIC)):
                fd=os.open(root/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                with os.fdopen(fd,'w') as output:output.write(value)
            args=['example','--rootfs','/rootfs','--radius','--radius-ssh','--radius-ssh-shell','--radius-accounting',
                  '--radius-accounting-outbox','--radius-accounting-journal','--radius-user','learner',
                  '--radius-secret-file',str(root/'secret'),'--radius-password-file',str(root/'password'),
                  '--ssh-authorized-key',str(root/'client.pub'),'--ssh-action','identity','--ssh-host-key-file','/offline/key']
            with patch('network_labs.appliances.ssh_host_key.read_identity',return_value=(b'fixture',PUBLIC)),redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args),0)
            node=json.loads(output.getvalue())['nodes'][0]
            self.assertIn('shell',node['management']['ssh_actions']);self.assertTrue(node['radius_access']['accounting_journal'])
