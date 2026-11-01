"""Combined services retain separate identities, explicit routes and bounded policy."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout,redirect_stderr
from network_labs.appliances.examples import dual_stack_services_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main
from test_native_dual_stack_radius import SECRET,DIGEST
from test_native_management import KEY


class DualStackServicesTests(unittest.TestCase):
    def example(self):return dual_stack_services_lab('/rootfs',SECRET,DIGEST,ssh_key=KEY)

    def test_canonical_routes_separate_services_and_explicit_resolver(self):
        spec=self.example();self.assertEqual(validate(spec),spec);self.assertEqual(len(spec['nodes']),5)
        nas,r1,r2,radius,dns=spec['nodes']
        self.assertEqual(nas['resolvers'],['203.0.113.53']);self.assertEqual(nas['radius_access']['server'],'198.51.100.20')
        self.assertEqual(r1['routes'][-1],{'destination':'203.0.113.0/24','gateway':'198.18.0.2','interface':'eth1'})
        self.assertEqual(r1['ipv6_routes'][-1],{'destination':'2001:db8:30::/64','gateway':'2001:db8:100::2','interface':'eth1'})
        self.assertEqual(r2['ipv6']['eth2'],'2001:db8:30::1/64')
        self.assertIsNone(radius['dns_server']);self.assertIsNone(dns['radius_server']);self.assertIsNone(dns['management'])
        self.assertEqual(dns['dns_server']['records_ipv6'],{'nas.lab.test':'2001:db8:10::10'})

    def test_colocated_dns_server_on_nas_or_radius_is_rejected(self):
        for index in (0,3):
            spec=self.example();policy=copy.deepcopy(spec['nodes'][4]['dns_server']);policy['listen_ipv6']=True
            spec['nodes'][index]['dns_server']=policy
            with self.subTest(index=index),self.assertRaises(ValueError):validate(spec)

    def test_unvalidated_shell_and_dynamic_compositions_stay_rejected(self):
        for edit in ('shell','slaac','missing-ipv6'):
            spec=self.example()
            if edit=='shell':spec['nodes'][0]['radius_access']['users']['learner'].append('shell')
            elif edit=='slaac':spec['nodes'][4]['slaac']=['eth0']
            else:spec['nodes'][4]['ipv6']={}
            with self.subTest(edit=edit),self.assertRaises(ValueError):validate(spec)

    def test_cli_requires_existing_radius_ssh_dual_stack_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,value in (('secret',SECRET),('password','example-test-password'),('key.pub',KEY)):
                path=root/name;path.write_text(value);path.chmod(0o600)
            args=['example','--rootfs','/rootfs','--radius','--radius-ssh','--radius-dual-stack','--radius-dns','--radius-user','learner',
                  '--radius-secret-file',str(root/'secret'),'--radius-password-file',str(root/'password'),'--ssh-authorized-key',str(root/'key.pub')]
            with redirect_stdout(io.StringIO()) as out:self.assertEqual(main(args),0)
            self.assertEqual(json.loads(out.getvalue())['name'],'dual-stack-services-lan')
            self.assertNotIn('example-test-password',out.getvalue())
            args.remove('--radius-dual-stack')
            with redirect_stderr(io.StringIO()),redirect_stdout(io.StringIO()):self.assertEqual(main(args),1)
        with redirect_stderr(io.StringIO()),redirect_stdout(io.StringIO()):
            self.assertEqual(main(['example','--rootfs','/rootfs','--radius-dns']),1)
