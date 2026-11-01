"""Bounded IPv6 SSH listeners with IPv4 RADIUS diagnostic authorization."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr,redirect_stdout
from unittest.mock import Mock,patch
from network_labs.appliances.examples import dual_stack_radius_lab,radius_lab,dual_stack_dns_lab
from network_labs.appliances.management import commands,start_service
from network_labs.appliances.spec import validate
from network_labs.appliances.service_adapters import adapters
from network_labs.appliances.__main__ import main
from test_native_management import KEY

SECRET='dual-stack-radius-test-secret'
DIGEST=hashlib.sha256(b'example-test-password').hexdigest()


class DualStackRadiusTests(unittest.TestCase):
    def test_explicit_listener_policy_and_canonical_example(self):
        spec=dual_stack_radius_lab('/rootfs',SECRET,DIGEST,ssh_key=KEY)
        self.assertEqual(validate(spec),spec)
        client=spec['nodes'][0];args=commands(client)['ssh']
        self.assertIn('192.0.2.10:22',args);self.assertIn('[2001:db8:10::10]:22',args)
        self.assertEqual(args.count('-p'),2)
        self.assertEqual(client['radius_access']['server'],'198.51.100.20')
        self.assertEqual(spec['nodes'][3]['radius_server']['clients'][0]['address'],'192.0.2.10')
        for flag in ('-s','-w','-j','-k'):self.assertIn(flag,args)
        old=radius_lab('/rootfs',SECRET,DIGEST,ssh_key=KEY)['nodes'][0]
        self.assertNotIn('ssh_ipv6',old['management']);self.assertEqual(commands(old)['ssh'].count('-p'),1)

    def test_ipv6_requires_boolean_numbered_host_and_managed_radius(self):
        for value in ('yes',1,None):
            spec=dual_stack_radius_lab('/rootfs',SECRET,DIGEST,ssh_key=KEY);spec['nodes'][0]['management']['ssh_ipv6']=value
            with self.subTest(value=value),self.assertRaises(ValueError):validate(spec)
        spec=radius_lab('/rootfs',SECRET,DIGEST,ssh_key=KEY);spec['nodes'][0]['management']['ssh_ipv6']=True
        with self.assertRaises(ValueError):validate(spec)
        for edit in ('no-radius','shell','accounting','syslog','no-ipv6-listener','dynamic','partial-ipv4'):
            spec=dual_stack_radius_lab('/rootfs',SECRET,DIGEST,ssh_key=KEY);client=spec['nodes'][0]
            if edit=='no-radius':client['management']['ssh_radius']=False
            elif edit=='shell':client['radius_access']['users']['learner'].append('shell');client['management']['ssh_actions'].append('shell')
            elif edit=='accounting':client['radius_access']['accounting']=True
            elif edit=='syslog':client['management']['syslog_remote']='198.51.100.20'
            elif edit=='no-ipv6-listener':client['management']['ssh_ipv6']=False
            elif edit=='dynamic':client['slaac']=['eth0']
            else:spec['nodes'][1]['interfaces']['eth0']=''
            with self.subTest(edit=edit),self.assertRaises(ValueError):validate(spec)

    def test_dns_and_aaa_profile_combination_remains_rejected(self):
        spec=dual_stack_radius_lab('/rootfs',SECRET,DIGEST,ssh_key=KEY)
        spec['nodes'][0]['resolvers']=['198.51.100.20']
        with self.assertRaises(ValueError):validate(spec)

    def test_dad_wait_precedes_ssh_launch_and_changes_require_recreation(self):
        spec=dual_stack_radius_lab('/rootfs',SECRET,DIGEST,ssh_key=KEY);client=spec['nodes'][0]
        with tempfile.TemporaryDirectory() as folder:
            manager=Mock();manager.directory=Path(folder);manager.state={'spec':spec}
            with patch('network_labs.appliances.ipv6.wait_addresses') as wait:
                manager.crun.side_effect=lambda *a,**k:self.assertTrue(wait.called)
                start_service(manager,client,'ssh');wait.assert_called_once_with(manager,0,client)
        new=copy.deepcopy(client);new['management']['ssh_ipv6']=False
        with self.assertRaises(ValueError):adapters(new,client)

    def test_cli_uses_private_credential_files_and_rejects_other_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,value in (('secret',SECRET),('password','example-test-password'),('key.pub',KEY)):
                path=root/name;path.write_text(value);path.chmod(0o600)
            args=['example','--rootfs','/rootfs','--radius','--radius-ssh','--radius-dual-stack','--radius-user','learner',
                  '--radius-secret-file',str(root/'secret'),'--radius-password-file',str(root/'password'),'--ssh-authorized-key',str(root/'key.pub')]
            with redirect_stdout(io.StringIO()) as out:self.assertEqual(main(args),0)
            spec=json.loads(out.getvalue());self.assertEqual(spec['name'],'dual-stack-radius-lan')
            self.assertNotIn('example-test-password',out.getvalue());self.assertTrue(spec['nodes'][0]['management']['ssh_ipv6'])
            for extra in (['--radius-shell'],['--radius-accounting'],['--dual-stack']):
                with redirect_stderr(io.StringIO()),redirect_stdout(io.StringIO()):self.assertEqual(main(args+extra),1)
        with redirect_stderr(io.StringIO()),redirect_stdout(io.StringIO()):
            self.assertEqual(main(['example','--rootfs','/rootfs','--radius-dual-stack']),1)
