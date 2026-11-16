"""One pinned identity on both SSH listeners with IPv4 RADIUS decisions."""
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
from network_labs.appliances.examples import dual_stack_radius_lab,dual_stack_services_lab
from network_labs.appliances.management import commands
from network_labs.appliances.spec import validate
from test_native_management import KEY as PUBLIC


class DualStackSSHHostKeyTests(unittest.TestCase):
    def profile(self):
        with patch('network_labs.appliances.ssh_host_key.read_identity',return_value=(b'fixture',PUBLIC)):
            return dual_stack_radius_lab('/rootfs','example-radius-secret','a'*64,ssh_key=PUBLIC,ssh_host_key_file='/offline/key')

    def test_both_listeners_use_one_explicit_identity_and_ipv4_backend(self):
        spec=self.profile();self.assertEqual(validate(copy.deepcopy(spec)),spec)
        node=spec['nodes'][0];argv=commands(node)['ssh']
        self.assertNotIn('-R',argv);self.assertEqual(argv.count('-r'),1);self.assertEqual(argv.count('-p'),2)
        self.assertIn('192.0.2.10:22',argv);self.assertIn('[2001:db8:10::10]:22',argv)
        self.assertEqual(node['radius_access']['server'],'198.51.100.20')
        self.assertEqual(node['management']['ssh_host_key']['public_key'],PUBLIC)

    def test_standalone_ipv6_shell_accounting_and_dns_compositions_remain_refused(self):
        for fault in ('no-radius','no-ipv6-listener','shell','accounting','dns'):
            spec=self.profile();node=spec['nodes'][0]
            if fault=='no-radius':node['management']['ssh_radius']=False
            if fault=='no-ipv6-listener':node['management']['ssh_ipv6']=False
            if fault=='shell':node['radius_access']['users']['learner'].append('shell')
            if fault=='accounting':node['radius_access']['accounting']=True
            if fault=='dns':
                pin=copy.deepcopy(node['management']['ssh_host_key'])
                spec=dual_stack_services_lab('/rootfs','example-radius-secret','a'*64,ssh_key=PUBLIC)
                spec['nodes'][0]['management']['ssh_host_key']=pin
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)

    def test_cli_keeps_explicit_pin_in_dual_stack_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,value in (('password','test-password'),('secret','example-radius-secret'),('client.pub',PUBLIC)):
                fd=os.open(root/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                with os.fdopen(fd,'w') as stream:stream.write(value)
            with patch('network_labs.appliances.ssh_host_key.read_identity',return_value=(b'fixture',PUBLIC)),redirect_stdout(io.StringIO()) as output:
                code=main(['example','--rootfs','/rootfs','--radius','--radius-ssh','--radius-dual-stack',
                    '--radius-user','learner','--radius-secret-file',str(root/'secret'),'--radius-password-file',str(root/'password'),
                    '--ssh-authorized-key',str(root/'client.pub'),'--ssh-action','identity','--ssh-host-key-file','/offline/key'])
            self.assertEqual(code,0)
            config=json.loads(output.getvalue())['nodes'][0]['management']
            self.assertTrue(config['ssh_ipv6']);self.assertEqual(config['ssh_host_key']['file'],'/offline/key')
