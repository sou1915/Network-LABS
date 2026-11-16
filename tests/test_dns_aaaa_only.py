"""AAAA-only data is explicit and independent from DNS transport family."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from network_labs.appliances.examples import ipv6_dns_aaaa_lab, dual_stack_dns_lab, dns_lab
from network_labs.appliances.dns import server_config
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main


class DNSAAAAOnlyTests(unittest.TestCase):
    def test_explicit_empty_a_map_with_aaaa_and_cli(self):
        spec=ipv6_dns_aaaa_lab('/rootfs');self.assertEqual(validate(spec),spec)
        node=spec['nodes'][3];self.assertEqual(node['dns_server']['records'],{})
        self.assertIn('host-record=server.lab.test,2001:db8:30::10,60\n',server_config(node))
        self.assertNotIn('192.0.2.',server_config(node))
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['example','--ipv6-dns-aaaa','--rootfs','/rootfs']),0)
        self.assertEqual(json.loads(out.getvalue()),spec)

    def test_both_transports_keep_their_listeners_with_aaaa_only_data(self):
        spec=dual_stack_dns_lab('/rootfs');spec['nodes'][3]['dns_server']['records']={}
        node=validate(spec)['nodes'][3];text=server_config(node)
        self.assertIn('listen-address=198.51.100.20\n',text)
        self.assertIn('listen-address=2001:db8:20::20\n',text)
        self.assertIn('host-record=server.lab.test,2001:db8:20::20,60\n',text)

    def test_empty_or_missing_or_invalid_a_maps_and_invalid_aaaa_still_refuse(self):
        original=ipv6_dns_aaaa_lab('/rootfs')
        for fault in ('empty','missing','null','list','mapped','duplicate','zone'):
            spec=copy.deepcopy(original);policy=spec['nodes'][3]['dns_server']
            if fault=='empty':policy['records_ipv6']={}
            if fault=='missing':policy.pop('records')
            if fault=='null':policy['records']=None
            if fault=='list':policy['records']=[]
            if fault=='mapped':policy['records_ipv6']={'server.lab.test':'::ffff:192.0.2.20'}
            if fault=='duplicate':policy['records_ipv6']['other.lab.test']='2001:db8:30::10'
            if fault=='zone':policy['records_ipv6']={'other.test':'2001:db8:30::10'}
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)
        ipv4=dns_lab('/rootfs');ipv4['nodes'][2]['dns_server']['records']={}
        with self.assertRaises(ValueError):validate(ipv4)
