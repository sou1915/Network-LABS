"""Costed parallel transits remain bounded to two physical OSPFv3 routers."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import ipv6_dns_ospfv3_failover_lab,ipv6_dns_ospfv3_lab
from network_labs.appliances.spec import validate


class IPv6DNSOSPFv3FailoverTests(unittest.TestCase):
    def test_reference_cli_and_retained_single_transit_policy(self):
        spec=ipv6_dns_ospfv3_failover_lab('/rootfs');self.assertEqual(validate(spec),spec)
        self.assertTrue(all(not n['ipv6_routes'] for n in spec['nodes'][1:3]))
        for node in spec['nodes'][1:3]:self.assertEqual(node['ospfv3']['interfaces']['eth2']['cost'],100)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-dns-ospfv3-failover','--rootfs','/rootfs']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)
        one=ipv6_dns_ospfv3_lab('/rootfs');one['nodes'][2]['ospfv3']['interfaces']['eth0']['cost']=15
        self.assertEqual(validate(one),one)  # Existing single-link asymmetric costs remain valid.

    def test_parallel_pair_requires_explicit_preference_and_paired_costs(self):
        original=ipv6_dns_ospfv3_failover_lab('/rootfs')
        for fault in ('equal','asymmetric','half-active','missing-link','third-transit'):
            spec=copy.deepcopy(original)
            if fault=='equal':
                for node in spec['nodes'][1:3]:node['ospfv3']['interfaces']['eth2']['cost']=10
            if fault=='asymmetric':spec['nodes'][2]['ospfv3']['interfaces']['eth2']['cost']=200
            if fault=='half-active':spec['nodes'][2]['ospfv3']['interfaces']['eth2']['passive']=True
            if fault=='missing-link':spec['links'].pop()
            if fault=='third-transit':
                for index in (1,2):
                    node=spec['nodes'][index];node['interfaces']['eth3']='';node['ipv6']['eth3']=f'2001:db8:300::{index}/64'
                    node['ospfv3']['interfaces']['eth3']={'passive':False,'cost':200}
                spec['links'].append([['R1','eth3'],['R2','eth3']])
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)
