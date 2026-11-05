"""Separate managed IPv6 DNS/TFTP with explicit static composition bounds."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from network_labs.appliances.examples import ipv6_dns_tftp_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main


class IPv6DNSTFTPTests(unittest.TestCase):
    def test_reference_cli_and_import(self):
        spec=ipv6_dns_tftp_lab('/rootfs');self.assertEqual(validate(spec),spec)
        self.assertEqual(spec['nodes'][3]['dns_server']['records'],{})
        self.assertEqual(spec['nodes'][3]['dns_server']['records_ipv6'],{'files.lab.test':'2001:db8:20::10'})
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-dns-tftp','--rootfs','/rootfs']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)
        with tempfile.TemporaryDirectory() as folder:
            asset=Path(folder)/'binary';asset.write_bytes(b'\x00\xff')
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['example','--ipv6-dns-tftp','--rootfs','/rootfs','--tftp-file','test.bin='+str(asset)]),0)
            self.assertEqual(json.loads(output.getvalue())['nodes'][2]['tftp_server']['files'],{'test.bin':{'base64':'AP8='}})

    def test_unmanaged_or_other_service_compositions_remain_refused(self):
        original=ipv6_dns_tftp_lab('/rootfs')
        for fault in ('no-dns','second-dns','dns-cohost','resolver-on-tftp','unknown-resolver','extra-resolver','listener','mixed','slaac','aaa','second-tftp'):
            spec=copy.deepcopy(original)
            if fault=='no-dns':spec['nodes'][3]['dns_server']=None
            if fault=='second-dns':spec['nodes'][1]['dns_server']=copy.deepcopy(spec['nodes'][3]['dns_server'])
            if fault=='dns-cohost':spec['nodes'][2]['dns_server']=spec['nodes'][3].pop('dns_server')
            if fault=='resolver-on-tftp':spec['nodes'][2]['resolvers']=['2001:db8:30::10']
            if fault=='unknown-resolver':spec['nodes'][0]['resolvers']=['2001:db8:30::99']
            if fault=='extra-resolver':spec['nodes'][0]['resolvers'].append('2001:db8:30::99')
            if fault=='listener':spec['nodes'][3]['dns_server']['listen_ipv6']=False
            if fault=='mixed':spec['nodes'][0]['interfaces']['eth0']='192.0.2.10/24'
            if fault=='slaac':spec['nodes'][0]['slaac']=['eth0']
            if fault=='aaa':spec['nodes'][0]['radius_access']={'server':'192.0.2.20','users':{'learner':['identity']}}
            if fault=='second-tftp':spec['nodes'][1]['tftp_server']=copy.deepcopy(spec['nodes'][2]['tftp_server'])
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)
