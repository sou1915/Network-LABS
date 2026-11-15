import copy
import unittest
from unittest.mock import patch
from network_labs.appliances.microvm import example
from network_labs.appliances.spec import validate
from network_labs.appliances.guest_startup import observe, apply

ADDRESSES = '1: lo: <LOOPBACK,UP>\n    inet 127.0.0.1/8 scope host lo\n2: eth0: <BROADCAST,UP>\n    inet 192.0.2.10/24 scope global eth0\n    inet 198.51.100.1/32 scope global eth0\n'
ROUTES = '192.0.2.0/24 dev eth0 scope link src 192.0.2.10\n203.0.113.0/24 via 192.0.2.20 dev eth0\n'
PROFILE = {'addresses': ['198.51.100.1/32'], 'routes': [{'network':'203.0.113.0/24','gateway':'192.0.2.20'}]}

class GuestStartupTests(unittest.TestCase):
    def node(self): return example('/kernel','/disk')['nodes'][0]

    def test_schema_rejects_unrepresentable_profiles(self):
        for profile in (None, {}, {'addresses':[], 'routes':[], 'shell':'id'}, {'addresses':['192.0.2.10/24'], 'routes':[]}, {'addresses':[], 'routes':[{'network':'203.0.113.1/24','gateway':'192.0.2.20'}]}, {'addresses':[], 'routes':[{'network':'203.0.113.0/24','gateway':'10.0.0.1'}]}):
            spec=example('/kernel','/disk');spec['nodes'][0]['guest_network']=profile
            with self.subTest(profile=profile), self.assertRaises((ValueError, TypeError)): validate(spec)

    def test_observation_captures_only_supported_ipv4(self):
        with patch('network_labs.appliances.guest_startup.query', side_effect=[ADDRESSES, ROUTES]):
            self.assertEqual(observe('/socket',self.node()),PROFILE)
        for text in (ADDRESSES.replace('BROADCAST,UP','BROADCAST'), ADDRESSES.replace('192.0.2.10/24','192.0.2.12/24'), ADDRESSES+'3: eth1: <UP>\n'):
            with patch('network_labs.appliances.guest_startup.query', return_value=text), self.assertRaises(ValueError): observe('/socket',self.node())
        with patch('network_labs.appliances.guest_startup.query',side_effect=[ADDRESSES, ROUTES+'blackhole 10.0.0.0/8\n']), self.assertRaises(ValueError): observe('/socket',self.node())

    def test_custom_connected_route_attributes_are_not_silently_dropped(self):
        with patch('network_labs.appliances.guest_startup.query', side_effect=[ADDRESSES, '192.0.2.0/24 dev eth0 scope link src 192.0.2.10 metric 100\n']), self.assertRaises(ValueError):
            observe('/socket', self.node())

    def test_replay_order_and_failed_mutation_never_retried(self):
        node=self.node();node['guest_network']=copy.deepcopy(PROFILE)
        with patch('network_labs.appliances.guest_startup.query') as query, patch('network_labs.appliances.guest_startup.observe',return_value=PROFILE):
            apply('/socket',node)
            self.assertEqual([c.args[1] for c in query.call_args_list],['ready','address-add','route-add'])
        with patch('network_labs.appliances.guest_startup.query',side_effect=['ready',ValueError('mutation failed')]) as query, self.assertRaises(ValueError): apply('/socket',node)
        self.assertEqual(query.call_count,2)

    def test_save_failure_never_overwrites_startup(self):
        from types import SimpleNamespace
        from pathlib import Path
        from network_labs.appliances.guest_startup import save_observed
        manager=SimpleNamespace(name='microvm-pair',directory=Path('/private'),state=None,read=lambda:{'phase':'running','spec':example('/kernel','/disk')})
        with patch('network_labs.appliances.guest_startup.observe',side_effect=ValueError('agent unavailable')), patch('network_labs.appliances.persistence.save_startup') as save, self.assertRaises(ValueError): save_observed(manager)
        save.assert_not_called()

    def test_changed_capture_and_failed_readback_are_rejected(self):
        from types import SimpleNamespace
        from pathlib import Path
        from network_labs.appliances.guest_startup import save_observed
        manager=SimpleNamespace(name='microvm-pair',directory=Path('/private'),state=None,read=lambda:{'phase':'running','spec':example('/kernel','/disk')})
        empty={'addresses':[], 'routes':[]}
        with patch('network_labs.appliances.guest_startup.observe',side_effect=[empty,empty,PROFILE]), patch('network_labs.appliances.persistence.save_startup') as save, self.assertRaises(ValueError): save_observed(manager)
        save.assert_not_called()
        node=self.node();node['guest_network']=PROFILE
        with patch('network_labs.appliances.guest_startup.query'), patch('network_labs.appliances.guest_startup.observe',return_value=empty), self.assertRaises(ValueError): apply('/socket',node)

    def test_declared_extra_port_is_verified_and_replayed(self):
        node=self.node();node['interfaces']['eth1']='198.51.100.10/24'
        text=ADDRESSES.replace('    inet 198.51.100.1/32 scope global eth0\n','')+'3: eth1: <BROADCAST,UP>\n    inet 198.51.100.10/24 scope global eth1\n'
        routes='192.0.2.0/24 dev eth0 scope link src 192.0.2.10\n198.51.100.0/24 dev eth1 scope link src 198.51.100.10\n'
        with patch('network_labs.appliances.guest_startup.query',side_effect=[text,routes]):
            self.assertEqual(observe('/socket',node),{'addresses':[],'routes':[]})
        with patch('network_labs.appliances.guest_startup.query') as query, patch('network_labs.appliances.guest_startup.observe',return_value={'addresses':[],'routes':[]}):
            apply('/socket',node)
            self.assertEqual(query.call_args_list[1].kwargs,{'interface':'eth1','cidr':'198.51.100.10/24'})
            self.assertEqual(query.call_args_list[2].kwargs,{'interface':'eth1','state':'up'})

    def test_extra_addresses_and_routes_on_second_port_are_captured_and_replayed(self):
        node=self.node();node['interfaces']['eth1']='198.51.100.10/24'
        text=ADDRESSES.replace('    inet 198.51.100.1/32 scope global eth0\n','')+'3: eth1: <BROADCAST,UP>\n    inet 198.51.100.10/24 scope global eth1\n    inet 198.51.100.11/24 scope global secondary eth1\n'
        routes='192.0.2.0/24 dev eth0 scope link src 192.0.2.10\n198.51.100.0/24 dev eth1 scope link src 198.51.100.10\n203.0.113.0/24 via 198.51.100.20 dev eth1\n'
        profile={'addresses':[],'routes':[{'network':'203.0.113.0/24','gateway':'198.51.100.20'}],'port_addresses':{'eth1':['198.51.100.11/24']}}
        with patch('network_labs.appliances.guest_startup.query',side_effect=[text,routes]):
            self.assertEqual(observe('/socket',node),profile)
        # A next hop on eth1's subnet reported through eth0 cannot be replayed faithfully.
        with patch('network_labs.appliances.guest_startup.query',side_effect=[text,routes.replace('dev eth1\n','dev eth0\n')]), self.assertRaises(ValueError):
            observe('/socket',node)
        node['guest_network']=copy.deepcopy(profile)
        with patch('network_labs.appliances.guest_startup.query') as query, patch('network_labs.appliances.guest_startup.observe',return_value=profile):
            apply('/socket',node)
        self.assertEqual([(c.args[1],c.kwargs) for c in query.call_args_list[3:]],[
            ('address-add',{'interface':'eth1','cidr':'198.51.100.11/24'}),
            ('route-add',{'network':'203.0.113.0/24','gateway':'198.51.100.20','interface':'eth1'})])

    def test_addresses_on_different_ports_cannot_share_a_subnet(self):
        from network_labs.appliances.microvm import multinic_example
        for profile in ({'addresses':['198.51.100.99/24'],'routes':[]}, {'addresses':[],'routes':[],'port_addresses':{'eth1':['192.0.2.99/24']}},
                        {'addresses':[],'routes':[],'port_addresses':{'eth2':['203.0.113.1/24']}}, {'addresses':[],'routes':[],'port_addresses':{'eth0':['192.0.2.99/24']}}):
            spec=multinic_example('/kernel','/disk');spec['nodes'][0]['guest_network']=profile
            with self.subTest(profile=profile), self.assertRaises(ValueError): validate(spec)
        spec=multinic_example('/kernel','/disk');spec['nodes'][0]['guest_network']={'addresses':['192.0.2.11/24'],'routes':[],'port_addresses':{'eth1':[]}}
        self.assertEqual(validate(spec)['nodes'][0]['guest_network'],{'addresses':['192.0.2.11/24'],'routes':[]})

    def test_dead_vmm_aborts_startup_without_waiting_for_the_agent(self):
        with patch('network_labs.appliances.guest_startup.query',side_effect=OSError('no socket')) as query, self.assertRaisesRegex(ValueError,'VMM exited'):
            apply('/socket',self.node(),alive=lambda:query.call_count<2)
        self.assertEqual(query.call_count,2)
