"""Explicit IPv6 HTTPS policy and refusal of unvalidated compositions."""
import copy
import io
import json
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch
from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import ipv6_https_lab
from network_labs.appliances.https_server import files
from network_labs.appliances.spec import validate


class IPv6HTTPSTests(unittest.TestCase):
    def profile(self):
        with patch('network_labs.appliances.https_server.read_asset',return_value=b'public fixture'):
            return ipv6_https_lab('/server','/client')

    def test_explicit_ipv6_listener_and_cli_keep_distinct_identity_rootfs(self):
        spec=self.profile();self.assertEqual(validate(copy.deepcopy(spec)),spec)
        server=spec['nodes'][3]
        self.assertEqual(server['rootfs'],'/server')
        self.assertTrue(all(n['rootfs']=='/client' for n in spec['nodes'][:3]))
        text=files(server)['https.conf']
        self.assertIn('listen [2001:db8:20::20]:443 ssl ipv6only=on;',text)
        self.assertNotIn('listen 80',text);self.assertNotIn('listen [::]',text)
        with patch('network_labs.appliances.https_server.read_asset',return_value=b'public fixture'),redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-https','--rootfs','/server','--https-client-rootfs','/client']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)

    def test_unvalidated_families_services_and_dynamic_routing_are_refused(self):
        for fault in ('missing-family','auto','dual-stack','dynamic','dns','firewall','ospf','second-server','shutdown'):
            spec=self.profile();server=spec['nodes'][3]
            if fault=='missing-family':server['https_server'].pop('family')
            if fault=='auto':server['https_server']['family']='auto'
            if fault=='dual-stack':spec['nodes'][0]['interfaces']['eth0']='192.0.2.10/24'
            if fault=='dynamic':spec['nodes'][1]['router_advertisements']=['eth0']
            if fault=='dns':spec['nodes'][0]['resolvers']=['2001:db8:20::20']
            if fault=='firewall':spec['nodes'][1]['firewall_ipv6']={'rules':[]}
            if fault=='ospf':spec['nodes'][1]['ospfv3']={'router_id':'1.1.1.1','area':'0.0.0.0','interfaces':['eth0','eth1']}
            if fault=='second-server':spec['nodes'][0]['https_server']=copy.deepcopy(server['https_server'])
            if fault=='shutdown':server['shutdown']=['eth0']
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)
