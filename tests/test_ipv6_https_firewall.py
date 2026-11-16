"""Explicit HTTPS forwarding profile; broader service/security remains refused."""
import copy
import io
import json
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch
from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import ipv6_https_firewall_lab
from network_labs.appliances.firewall_ipv6 import render
from network_labs.appliances.spec import validate


class IPv6HTTPSFirewallTests(unittest.TestCase):
    def profile(self):
        with patch('network_labs.appliances.https_server.read_asset',return_value=b'public fixture'):
            return ipv6_https_firewall_lab('/server','/client')

    def test_explicit_https_allow_stateful_return_and_default_drop_cli(self):
        spec=self.profile();self.assertEqual(validate(copy.deepcopy(spec)),spec)
        policy=spec['nodes'][1]['firewall_ipv6']
        self.assertEqual(policy['default'],'drop');self.assertTrue(policy['stateful'])
        self.assertEqual([r['dport'] for r in policy['rules'] if r['protocol']=='tcp'],[443])
        text=render(policy)
        for token in ('ct state established,related','tcp dport 443','ip6 saddr 2001:db8:10::10/128',
                      'ip6 daddr 2001:db8:20::20/128','counter drop comment "default"'):
            self.assertIn(token,text)
        self.assertNotIn('8080',text);self.assertNotIn('chain input',text)
        self.assertEqual(spec['nodes'][2]['rootfs'],'/server')
        self.assertTrue(all(n['rootfs']=='/client' for n in spec['nodes'][:2]))
        with patch('network_labs.appliances.https_server.read_asset',return_value=b'public fixture'),redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-https-firewall','--rootfs','/server','--https-client-rootfs','/client']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)

    def test_local_input_other_services_dynamic_and_dual_stack_remain_refused(self):
        for fault in ('input','resolvers','dynamic','dual-stack','family','second-server'):
            spec=self.profile();fw=spec['nodes'][1];server=spec['nodes'][2]
            if fault=='input':fw['firewall_ipv6']['input']={'default':'drop','rules':[]}
            if fault=='resolvers':spec['nodes'][0]['resolvers']=['2001:db8:20::20']
            if fault=='dynamic':spec['nodes'][0]['slaac']=['eth0']
            if fault=='dual-stack':spec['nodes'][0]['interfaces']['eth0']='192.0.2.10/24'
            if fault=='family':server['https_server'].pop('family')
            if fault=='second-server':spec['nodes'][0]['https_server']=copy.deepcopy(server['https_server'])
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)
