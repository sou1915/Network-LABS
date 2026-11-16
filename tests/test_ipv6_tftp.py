"""Explicit static IPv6 TFTP profile, canonical family and retained exclusions."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from network_labs.appliances.examples import ipv6_tftp_lab, tftp_lab
from network_labs.appliances.tftp_server import config_text
from network_labs.appliances.tftp import read
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main


class IPv6TFTPTests(unittest.TestCase):
    def test_opt_in_server_and_cli_preserve_ipv4_defaults(self):
        spec=ipv6_tftp_lab('/rootfs');self.assertEqual(validate(spec),spec)
        self.assertEqual(spec['nodes'][3]['tftp_server']['family'],'ipv6')
        self.assertIn('listen-address=2001:db8:20::20',config_text(spec['nodes'][3]))
        ipv4=tftp_lab('/rootfs')['nodes'][2]
        self.assertNotIn('family',ipv4['tftp_server']);self.assertNotIn('listen-address=',config_text(ipv4))
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-tftp','--rootfs','/rootfs']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)

    def test_remote_family_rejections_precede_lab_access(self):
        for address,family in (('::1','ipv6'),('fe80::1','ipv6'),('ff02::1','ipv6'),('::','ipv6'),('::ffff:192.0.2.20','ipv6'),('2001:db8::1%eth0','ipv6'),('192.0.2.20','ipv6'),('2001:db8::20','ipv4'),('2001:db8::20','auto')):
            with self.subTest(address=address,family=family),self.assertRaises(ValueError):read(None,'PC1',address,'sample.bin',family=family)

    def test_mixed_and_other_service_profiles_remain_refused(self):
        original=ipv6_tftp_lab('/rootfs')
        for fault in ('family','mixed','dns','slaac','aaa'):
            spec=copy.deepcopy(original)
            if fault=='family':spec['nodes'][3]['tftp_server']['family']='ipv4'
            if fault=='mixed':spec['nodes'][0]['interfaces']['eth0']='192.0.2.10/24'
            if fault=='dns':spec['nodes'][0]['resolvers']=['2001:db8:20::20']
            if fault=='slaac':spec['nodes'][0]['slaac']=['eth0']
            if fault=='aaa':spec['nodes'][0]['radius_access']={'server':'192.0.2.20','users':{'learner':['identity']}}
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)
