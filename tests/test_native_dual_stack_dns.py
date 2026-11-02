"""Explicit static dual-stack DNS policy and unchanged IPv4-only defaults."""
import copy
import io
import json
import unittest
from pathlib import Path
from contextlib import redirect_stdout,redirect_stderr
from unittest.mock import Mock,patch
from network_labs.appliances.examples import dual_stack_dns_lab,dns_lab,slaac_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.dns import server_config,start_servers
from network_labs.appliances.__main__ import main
from network_labs.appliances.service_adapters import adapters


class DualStackDNSTests(unittest.TestCase):
    def test_reference_and_cli_preserve_static_routes_and_explicit_listener(self):
        spec=dual_stack_dns_lab('/rootfs');self.assertEqual(validate(spec),spec)
        server=spec['nodes'][3];text=server_config(server)
        self.assertIn('listen-address=198.51.100.20\n',text)
        self.assertIn('listen-address=2001:db8:20::20\n',text)
        self.assertIn('host-record=server.lab.test,198.51.100.20,2001:db8:20::20,60\n',text)
        self.assertIn('no-resolv\n',text);self.assertNotIn('server=',text)
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['example','--dual-stack-dns','--rootfs','/rootfs']),0)
        self.assertEqual(json.loads(out.getvalue()),spec)
        with redirect_stderr(io.StringIO()),redirect_stdout(io.StringIO()):
            self.assertEqual(main(['example','--dual-stack-dns','--dual-stack','--rootfs','/rootfs']),1)

    def test_ipv4_dns_default_config_and_dad_wait_remain_explicit(self):
        spec=dns_lab('/rootfs');server=spec['nodes'][2];text=server_config(server)
        self.assertNotIn('listen_ipv6',server['dns_server']);self.assertNotIn('records_ipv6',server['dns_server'])
        self.assertNotIn('listen-address=2001:',text)
        manager=Mock();manager.directory=Path('/tmp');manager.state={'spec':spec}
        with patch('network_labs.appliances.ipv6.wait_addresses') as wait:start_servers(manager);wait.assert_not_called()
        spec=dual_stack_dns_lab('/rootfs');manager.state={'spec':spec}
        with patch('network_labs.appliances.ipv6.wait_addresses') as wait:
            start_servers(manager);wait.assert_called_once_with(manager,3,spec['nodes'][3])

    def test_aaaa_normalization_unique_names_addresses_and_zone(self):
        spec=dual_stack_dns_lab('/rootfs');spec['nodes'][3]['dns_server']['records_ipv6']={'V6.LAB.TEST.':'2001:0db8:20::AB'}
        node=validate(spec)['nodes'][3]
        self.assertEqual(node['dns_server']['records_ipv6'],{'v6.lab.test':'2001:db8:20::ab'})
        self.assertIn('host-record=v6.lab.test,2001:db8:20::ab,60\n',server_config(node))
        for value in ({'bad.test':'2001:db8::1'},{'x.lab.test':'fe80::1'},{'x.lab.test':'::1'},
                      {'x.lab.test':'::'},{'x.lab.test':'::ffff:192.0.2.10'},{'x.lab.test':'ff02::1'},
                      {'x.lab.test':'2001:db8::1%eth0'},{'x.lab.test':True},[],
                      {'X.lab.test.':'2001:db8::1','x.lab.test':'2001:db8::2'},
                      {'x.lab.test':'2001:db8::1','y.lab.test':'2001:db8::1'}):
            candidate=dual_stack_dns_lab('/rootfs');candidate['nodes'][3]['dns_server']['records_ipv6']=value
            with self.subTest(value=value),self.assertRaises(ValueError):validate(candidate)

    def test_listener_requires_boolean_and_numbered_single_host(self):
        for value in ('yes',1,None):
            spec=dual_stack_dns_lab('/rootfs');spec['nodes'][3]['dns_server']['listen_ipv6']=value
            with self.subTest(value=value),self.assertRaises(ValueError):validate(spec)
        spec=dns_lab('/rootfs');spec['nodes'][2]['dns_server']['listen_ipv6']=True
        with self.assertRaises(ValueError):validate(spec)
        spec=dual_stack_dns_lab('/rootfs');spec['nodes'][1]['dns_server']=spec['nodes'][3].pop('dns_server')
        with self.assertRaises(ValueError):validate(spec)

    def test_dynamic_and_partially_numbered_compositions_stay_rejected(self):
        for change in ('slaac','ipv4','ipv6','ospfv3'):
            spec=dual_stack_dns_lab('/rootfs')
            if change=='slaac':spec['nodes'][0]['slaac']=['eth0']
            elif change=='ipv4':spec['nodes'][0]['interfaces']['eth0']=''
            elif change=='ipv6':spec['nodes'][0]['ipv6']={};spec['nodes'][0]['ipv6_routes']=[]
            else:spec['nodes'][1]['ospfv3']={'router_id':'1.1.1.1','interfaces':{'eth0':{'area':'0.0.0.0'}}}
            with self.subTest(change=change),self.assertRaises(ValueError):validate(spec)

    def test_dns_edits_still_require_recreation(self):
        old=dual_stack_dns_lab('/rootfs')['nodes'][3];new=copy.deepcopy(old)
        new['dns_server']['records_ipv6']['server.lab.test']='2001:db8:20::99'
        with self.assertRaises(ValueError):adapters(new,old)
