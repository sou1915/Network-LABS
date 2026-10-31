"""Routed LAN services compose existing daemons without loosening their scope."""
import contextlib
import io
import json
import unittest

from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import lan_services_lab
from network_labs.appliances.dhcp_multi import server_config as pools_config
from network_labs.appliances.dns import server_config as dns_config


class LANServicesTests(unittest.TestCase):
    def test_dhcp_resolvers_are_real_separate_dns_node_with_return_routes(self):
        spec = lan_services_lab('/rootfs'); nodes = {n['name']: n for n in spec['nodes']}
        self.assertEqual(len(nodes), 8)
        self.assertEqual(nodes['DNS1']['interfaces'], {'eth0': '198.18.0.4/29'})
        self.assertEqual({r['destination']: r['gateway'] for r in nodes['DNS1']['routes']},
                         {'192.0.2.0/24': '198.18.0.1', '198.51.100.0/24': '198.18.0.1', '203.0.113.0/24': '198.18.0.2'})
        text = pools_config(nodes['DHCP1'])
        for index in (0, 1):
            self.assertIn(f'dhcp-option=tag:pool{index},option:dns-server,198.18.0.4\n', text)
        for client in ('PC1', 'PC3'):
            self.assertEqual(nodes[client]['dhcp_clients'], ['eth0'])
            self.assertFalse(nodes[client]['resolvers'])
        for line in ('no-resolv', 'no-hosts', 'cache-size=0', 'host-record=web.lab.test,203.0.113.10,60'):
            self.assertIn(line + '\n', dns_config(nodes['DNS1']))
        self.assertIsNone(nodes['DNS1']['dhcp_pools'])
        self.assertIsNone(nodes['DHCP1']['dns_server'])
        self.assertEqual(nodes['SW2']['switchports']['eth3'], {'mode': 'access', 'vlan': 20})
        self.assertIn([['SW2', 'eth3'], ['DNS1', 'eth0']], spec['links'])

    def test_http_startup_recipe_and_discovery_keep_declared_scope(self):
        nodes = {n['name']: n for n in lan_services_lab('/rootfs')['nodes']}
        self.assertEqual(nodes['PC2']['interfaces']['eth0'], '203.0.113.10/24')
        self.assertIn('/bin/busybox httpd -p 80', nodes['PC2']['startup'][0][-1])
        self.assertEqual({n for n in nodes if nodes[n]['lldp'] is not None}, {'SW1', 'SW2', 'R1'})
        self.assertEqual(nodes['SW2']['lldp']['ports'], ['eth0', 'eth1'])
        self.assertTrue(nodes['SW1']['ospf']['interfaces']['vlan10']['passive'])
        self.assertTrue(nodes['SW1']['ospf']['interfaces']['vlan30']['passive'])
        self.assertIsNone(nodes['DNS1']['ospf'])

    def test_cli_reference_is_explicit_and_exclusive(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(['example', '--lan-services', '--rootfs', '/rootfs']), 0)
        self.assertEqual(json.loads(out.getvalue())['name'], 'lan-services')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['example', '--lan-services', '--ospf-dhcp-lldp', '--rootfs', '/rootfs']), 1)
