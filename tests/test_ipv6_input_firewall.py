"""Opt-in local input semantics and unchanged forward-only defaults."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from network_labs.appliances.examples import ipv6_input_firewall_lab, ipv6_dns_firewall_lab
from network_labs.appliances.firewall_ipv6 import render
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main


class IPv6InputFirewallTests(unittest.TestCase):
    def test_opt_in_input_preserves_forward_chain_and_requires_ndp_and_loopback(self):
        base=ipv6_dns_firewall_lab('/rootfs')['nodes'][1]
        spec=ipv6_input_firewall_lab('/rootfs');node=spec['nodes'][1]
        self.assertEqual(validate(spec),spec)
        text=render(node['firewall_ipv6'],ports=node['interfaces'])
        old=render(base['firewall_ipv6'])
        self.assertNotIn('hook input',old)
        self.assertEqual(text.split('chain input')[0],old.rsplit('}',1)[0])
        self.assertIn('hook input priority filter; policy drop;',text)
        self.assertIn('iifname "lo" counter accept',text)
        self.assertIn('ip6 nexthdr ipv6-icmp ip6 hoplimit 255 icmpv6 type { 135, 136 }',text)
        self.assertNotIn('hook output',text)
        with self.assertRaises(ValueError):render(node['firewall_ipv6'])
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-input-firewall','--rootfs','/rootfs']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)

    def test_nested_input_policy_rejects_output_matches_invalid_types_and_nesting(self):
        original=ipv6_input_firewall_lab('/rootfs')
        for fault in ('out','stateful','nested','default','port','ndp','none'):
            spec=copy.deepcopy(original);policy=spec['nodes'][1]['firewall_ipv6']['input']
            if fault=='out':policy['rules'][0]['out']='eth1'
            if fault=='stateful':policy['stateful']=1
            if fault=='nested':policy['input']={}
            if fault=='default':policy['default']='open'
            if fault=='port':policy['rules'][0]['dport']=False
            if fault=='ndp':policy['rules'][1]['icmp_type']='nd-router-advert'
            if fault=='none':spec['nodes'][1]['firewall_ipv6']['input']=None
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)
