"""Explicit managed DNS over the bounded physical OSPFv3 pair."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import ipv6_dns_ospfv3_lab,ospfv3_svi_lab
from network_labs.appliances.spec import validate


class IPv6DNSOSPFv3Tests(unittest.TestCase):
    def test_reference_and_cli_have_no_router_static_fallback(self):
        spec=ipv6_dns_ospfv3_lab('/rootfs');self.assertEqual(validate(spec),spec)
        self.assertTrue(all(n['ipv6_routes']==[] for n in spec['nodes'][1:3]))
        self.assertEqual(spec['nodes'][0]['resolvers'],['2001:db8:20::20'])
        self.assertEqual(spec['nodes'][3]['dns_server']['records'],{})
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-dns-ospfv3','--rootfs','/rootfs']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)

    def test_incomplete_adjacency_and_other_compositions_remain_refused(self):
        original=ipv6_dns_ospfv3_lab('/rootfs')
        for fault in ('no-dns','second-dns','one-router','router-id','timers','missing-lan','two-active','wrong-active','resolver','mixed','slaac','aaa'):
            spec=copy.deepcopy(original)
            if fault=='no-dns':spec['nodes'][3]['dns_server']=None
            if fault=='second-dns':spec['nodes'][0]['dns_server']=copy.deepcopy(spec['nodes'][3]['dns_server'])
            if fault=='one-router':spec['nodes'][2]['ospfv3']=None
            if fault=='router-id':spec['nodes'][2]['ospfv3']['router_id']='1.1.1.1'
            if fault=='timers':spec['nodes'][2]['ospfv3']['dead']=5
            if fault=='missing-lan':del spec['nodes'][1]['ospfv3']['interfaces']['eth0']
            if fault=='two-active':spec['nodes'][1]['ospfv3']['interfaces']['eth0']['passive']=False
            if fault=='wrong-active':
                spec['nodes'][1]['ospfv3']['interfaces']['eth0']['passive']=False
                spec['nodes'][1]['ospfv3']['interfaces']['eth1']['passive']=True
            if fault=='resolver':spec['nodes'][0]['resolvers']=['2001:db8:20::99']
            if fault=='mixed':spec['nodes'][0]['interfaces']['eth0']='192.0.2.10/24'
            if fault=='slaac':spec['nodes'][0]['slaac']=['eth0']
            if fault=='aaa':spec['nodes'][0]['radius_access']={'server':'192.0.2.20','users':{'learner':['identity']}}
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)

    def test_dns_on_ospfv3_svis_stays_separate(self):
        spec=ospfv3_svi_lab('/rootfs');spec['nodes'][0]['resolvers']=['2001:db8:20::20']
        spec['nodes'][3]['dns_server']=ipv6_dns_ospfv3_lab('/rootfs')['nodes'][3]['dns_server']
        with self.assertRaises(ValueError):validate(spec)
