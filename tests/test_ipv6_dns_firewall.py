"""Bounded DNS/IPv6 forwarding security composition and retained exclusions."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from network_labs.appliances.examples import ipv6_dns_firewall_lab, ipv6_dns_subinterfaces_lab
from network_labs.appliances.firewall_ipv6 import render
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main


class IPv6DNSFirewallTests(unittest.TestCase):
    def test_explicit_reference_and_cli(self):
        spec=ipv6_dns_firewall_lab('/rootfs');self.assertEqual(validate(spec),spec)
        policy=spec['nodes'][1]['firewall_ipv6'];self.assertEqual(policy['default'],'drop');self.assertTrue(policy['stateful'])
        rules=policy['rules'][1:]
        self.assertEqual([(r['protocol'],r['dport']) for r in rules],[('udp',53),('tcp',53)])
        self.assertTrue(all(r['source']=='2001:db8:10::10/128' and r['destination']=='2001:db8:20::20/128' for r in rules))
        self.assertIn('ct state established,related counter accept',render(policy))
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-dns-firewall','--rootfs','/rootfs']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)

    def test_mixed_dynamic_and_aaa_compositions_remain_refused(self):
        for fault in ('mixed','slaac','aaa'):
            spec=ipv6_dns_firewall_lab('/rootfs')
            if fault=='mixed':spec['nodes'][0]['interfaces']['eth0']='192.0.2.10/24'
            if fault=='slaac':spec['nodes'][0]['slaac']=['eth0']
            if fault=='aaa':spec['nodes'][0]['radius_access']={'server':'192.0.2.20','users':{'learner':['identity']}}
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)

    def test_firewall_still_refuses_subinterface_compositions(self):
        spec=ipv6_dns_subinterfaces_lab('/rootfs')
        spec['nodes'][5]['role']='firewall'
        spec['nodes'][5]['firewall_ipv6']=copy.deepcopy(ipv6_dns_firewall_lab('/rootfs')['nodes'][1]['firewall_ipv6'])
        with self.assertRaises(ValueError):validate(spec)
