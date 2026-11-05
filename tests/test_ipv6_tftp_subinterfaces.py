"""Explicit IPv6 TFTP over static tagged routing with retained exclusions."""
import copy
import io
import json
import tempfile
from pathlib import Path
import unittest
from contextlib import redirect_stdout
from network_labs.appliances.examples import ipv6_tftp_subinterfaces_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main


class IPv6TFTPSubinterfaceTests(unittest.TestCase):
    def test_cli_reference_and_binary_import(self):
        spec=ipv6_tftp_subinterfaces_lab('/rootfs');self.assertEqual(validate(spec),spec)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-tftp-subinterfaces','--rootfs','/rootfs']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)
        with tempfile.TemporaryDirectory() as folder:
            asset=Path(folder)/'binary';asset.write_bytes(b'\x00\xff')
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['example','--ipv6-tftp-subinterfaces','--rootfs','/rootfs','--tftp-file','test.bin='+str(asset)]),0)
            self.assertEqual(json.loads(output.getvalue())['nodes'][3]['tftp_server']['files'],{'test.bin':{'base64':'AP8='}})

    def test_other_compositions_and_partial_numbering_remain_refused(self):
        original=ipv6_tftp_subinterfaces_lab('/rootfs')
        for fault in ('mixed','child-ipv4','missing-child','missing-physical','numbered-parent','svi','slaac','dns','aaa','second-server'):
            spec=copy.deepcopy(original)
            if fault=='mixed':spec['nodes'][0]['interfaces']['eth0']='192.0.2.10/24'
            if fault=='child-ipv4':spec['nodes'][5]['subinterfaces']['eth0.10']['address']='192.0.2.1/24'
            if fault=='missing-child':del spec['nodes'][5]['ipv6']['eth0.10']
            if fault=='missing-physical':del spec['nodes'][6]['ipv6']['eth1']
            if fault=='numbered-parent':spec['nodes'][5]['ipv6']['eth0']='2001:db8:200::1/64'
            if fault=='svi':spec['nodes'][4]['svis']={'vlan10':{'address':''}}
            if fault=='slaac':spec['nodes'][0]['slaac']=['eth0']
            if fault=='dns':spec['nodes'][0]['resolvers']=['2001:db8:30::10']
            if fault=='aaa':spec['nodes'][0]['radius_access']={'server':'192.0.2.20','users':{'learner':['identity']}}
            if fault=='second-server':spec['nodes'][0]['tftp_server']=copy.deepcopy(spec['nodes'][3]['tftp_server'])
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)
