"""Explicit IPv6-only DNS transport over static tagged routing."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from network_labs.appliances.examples import ipv6_dns_subinterfaces_lab, dual_stack_dns_lab
from network_labs.appliances.dns import server_config
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main


class IPv6DNSSubinterfaceTests(unittest.TestCase):
    def test_explicit_listener_and_cli_preserve_static_tagged_routing(self):
        spec=ipv6_dns_subinterfaces_lab('/rootfs');self.assertEqual(validate(spec),spec)
        text=server_config(spec['nodes'][3])
        self.assertEqual([s for s in text.splitlines() if s.startswith('listen-address=')],['listen-address=2001:db8:30::10'])
        self.assertIn('host-record=server.lab.test,192.0.2.10,2001:db8:30::10,60',text)
        self.assertIn('no-resolv',text)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-dns-subinterfaces','--rootfs','/rootfs']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)

    def test_listener_is_opt_in_and_mixed_or_dynamic_profiles_stay_refused(self):
        original=ipv6_dns_subinterfaces_lab('/rootfs')
        for fault in ('listener','mixed','slaac','svi','router-service','radius-access'):
            spec=copy.deepcopy(original)
            if fault=='listener':spec['nodes'][3]['dns_server']['listen_ipv6']=False
            if fault=='mixed':spec['nodes'][0]['interfaces']['eth0']='192.0.2.10/24'
            if fault=='slaac':spec['nodes'][0]['slaac']=['eth0']
            if fault=='svi':spec['nodes'][4]['svis']={'vlan10':{'address':''}}
            if fault=='router-service':spec['nodes'][5]['dns_server']=spec['nodes'][3].pop('dns_server')
            if fault=='radius-access':spec['nodes'][0]['radius_access']={'server':'192.0.2.20','users':{'learner':['identity']}}
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)

    def test_partially_numbered_dual_stack_dns_remains_refused(self):
        spec=dual_stack_dns_lab('/rootfs');spec['nodes'][0]['interfaces']['eth0']=''
        with self.assertRaises(ValueError):validate(spec)
