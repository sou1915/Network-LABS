"""Separate DNS/HTTPS identity and bounded static IPv6 composition."""
import copy
import io
import json
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch
from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import ipv6_dns_https_lab,ipv6_https_firewall_lab
from network_labs.appliances.spec import validate


class IPv6DNSHTTPSTests(unittest.TestCase):
    def profile(self):
        with patch('network_labs.appliances.https_server.read_asset',return_value=b'public fixture'):
            return ipv6_dns_https_lab('/server','/client')

    def test_separate_service_nodes_managed_resolver_and_cli(self):
        spec=self.profile();self.assertEqual(validate(copy.deepcopy(spec)),spec)
        self.assertEqual(len(spec['nodes']),5)
        self.assertEqual(spec['nodes'][0]['resolvers'],['2001:db8:30::30'])
        self.assertEqual(spec['nodes'][3]['rootfs'],'/server')
        self.assertIsNone(spec['nodes'][3]['dns_server'])
        self.assertEqual(spec['nodes'][4]['rootfs'],'/client')
        self.assertIsNone(spec['nodes'][4]['https_server'])
        self.assertEqual(spec['nodes'][4]['dns_server']['records'],{})
        with patch('network_labs.appliances.https_server.read_asset',return_value=b'public fixture'),redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-dns-https','--rootfs','/server','--https-client-rootfs','/client']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)

    def test_external_resolver_colocation_firewall_and_dynamic_remain_refused(self):
        for fault in ('external','no-resolver','https-resolver','dns-resolver','colocation','listen4','second-dns','dynamic','firewall'):
            spec=self.profile();client=spec['nodes'][0];server=spec['nodes'][3];dns=spec['nodes'][4]
            if fault=='external':client['resolvers']=['2001:db8:99::99']
            if fault=='no-resolver':client['resolvers']=[]
            if fault=='https-resolver':server['resolvers']=client['resolvers'][:]
            if fault=='dns-resolver':dns['resolvers']=client['resolvers'][:]
            if fault=='colocation':server['dns_server']=dns['dns_server'];dns['dns_server']=None
            if fault=='listen4':dns['dns_server']['listen_ipv6']=False
            if fault=='second-dns':client['dns_server']=copy.deepcopy(dns['dns_server'])
            if fault=='dynamic':spec['nodes'][1]['router_advertisements']=['eth0']
            if fault=='firewall':
                with patch('network_labs.appliances.https_server.read_asset',return_value=b'public fixture'):
                    spec=ipv6_https_firewall_lab('/server','/client')
                spec['nodes'][0]['resolvers']=['2001:db8:30::30']
                spec['nodes'][1]['interfaces']['eth2']='';spec['nodes'][1]['ipv6']['eth2']='2001:db8:30::1/64'
                spec['nodes'].append(copy.deepcopy(dns));spec['links'].append([['FW1','eth2'],['PC3','eth0']])
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)
