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
        with patch('network_labs.appliances.guest_startup.query', side_effect=[ADDRESSES, ROUTES, '0\n']):
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
        with patch('network_labs.appliances.guest_startup.query',side_effect=[text,routes,'0\n']):
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
        with patch('network_labs.appliances.guest_startup.query',side_effect=[text,routes,'0\n']):
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

    def test_router_guest_must_forward_and_host_guest_must_not(self):
        from network_labs.appliances.microvm import router_example
        from network_labs.appliances.guest_startup import check_forwarding, forwarding
        spec=router_example('/kernel','/disk');router,host=spec['nodes'][0],spec['nodes'][1]
        self.assertEqual((router['role'],host['gateway'],spec['nodes'][2]['gateway']),('router','192.0.2.1','198.51.100.1'))
        unsupported=ValueError('Guest forwarding failed: unsupported operation')
        for node,answer,accepted in [(router,'1\n',True),(router,'0\n',False),(router,unsupported,False),(host,'0\n',True),(host,'1\n',False),(host,unsupported,True)]:
            with self.subTest(role=node['role'],answer=answer),patch('network_labs.appliances.guest_startup.query',side_effect=[answer]):
                if accepted:check_forwarding('/socket',node)
                else:
                    with self.assertRaises(ValueError):check_forwarding('/socket',node)
        with patch('network_labs.appliances.guest_startup.query',side_effect=ValueError('Guest forwarding failed: forwarding state unavailable')),self.assertRaises(ValueError):
            forwarding('/socket')
        # Forwarding is switched on last, after every address and route it depends on.
        with patch('network_labs.appliances.guest_startup.query') as query,patch('network_labs.appliances.guest_startup.observe',return_value={'addresses':[],'routes':[]}):
            apply('/socket',router)
        self.assertEqual((query.call_args_list[-1].args[1],query.call_args_list[-1].kwargs),('forward',{'state':'on'}))
        with patch('network_labs.appliances.guest_startup.query') as query,patch('network_labs.appliances.guest_startup.observe',return_value={'addresses':[],'routes':[]}):
            apply('/socket',self.node())
        self.assertNotIn('forward',[c.args[1] for c in query.call_args_list])

    def test_router_role_needs_two_ports_and_stays_a_micro_vm_role(self):
        from network_labs.appliances.microvm import router_example
        spec=router_example('/kernel','/disk');spec['nodes'][0]['interfaces']={'eth0':'192.0.2.1/24'}
        with self.assertRaisesRegex(ValueError,'two ports'):validate(spec)
        for role in ('switch','firewall'):
            spec=router_example('/kernel','/disk');spec['nodes'][0]['role']=role
            with self.subTest(role=role),self.assertRaises(ValueError):validate(spec)

    def test_router_chain_declares_one_transit_route_per_router_on_the_right_port(self):
        from network_labs.appliances.microvm import router_chain_example
        from network_labs.appliances.guest_startup import route_port
        spec=router_chain_example('/kernel','/disk');first,second=spec['nodes'][:2]
        self.assertEqual([n['name'] for n in spec['nodes']],['R1','R2','VM2','VM3'])
        self.assertEqual(route_port(first,first['guest_network'],'203.0.113.2'),'eth1')
        self.assertEqual(route_port(second,second['guest_network'],'203.0.113.1'),'eth0')
        # R1 reaches its next hop through its second port, so replay must name that port; forwarding still comes last.
        with patch('network_labs.appliances.guest_startup.query') as query,patch('network_labs.appliances.guest_startup.observe',return_value=first['guest_network']):
            apply('/socket',first)
        calls=[(c.args[1],c.kwargs) for c in query.call_args_list]
        self.assertIn(('route-add',{'network':'198.51.100.0/24','gateway':'203.0.113.2','interface':'eth1'}),calls)
        self.assertEqual(calls[-1],('forward',{'state':'on'}))

    def switch(self):
        from network_labs.appliances.microvm import switch_example
        return switch_example('/kernel', '/disk')['nodes'][0]

    BRIDGED = ('1: lo: <LOOPBACK,UP,LOWER_UP>\n    inet 127.0.0.1/8 scope host lo\n'
               '2: eth0: <BROADCAST,UP,LOWER_UP>\n3: eth1: <BROADCAST,UP,LOWER_UP>\n4: eth2: <BROADCAST,UP,LOWER_UP>\n'
               '5: br0: <BROADCAST,UP,LOWER_UP>\n')

    def test_switch_guest_bridges_every_declared_port_and_nothing_else(self):
        from network_labs.appliances.guest_startup import check_switch
        node = self.switch()
        with patch('network_labs.appliances.guest_startup.query') as query:
            query.side_effect = lambda socket, operation, **kw: {'bridge-ports': 'eth2\neth0\neth1\n', 'addresses': self.BRIDGED, 'forwarding': '0\n'}.get(operation, '')
            apply('/socket', node)
        calls = [(c.args[1], c.kwargs.get('interface')) for c in query.call_args_list]
        self.assertEqual(calls[:7], [('ready', None), ('link', 'eth0'), ('bridge-add', 'eth0'), ('link', 'eth1'), ('bridge-add', 'eth1'), ('link', 'eth2'), ('bridge-add', 'eth2')])
        self.assertNotIn('address-add', [c[0] for c in calls]); self.assertNotIn('forward', [c[0] for c in calls])
        bad = {'missing port': ('eth0\neth1\n', self.BRIDGED, '0\n'),
               'address on bridge': ('eth0\neth1\neth2\n', self.BRIDGED + '    inet 192.0.2.99/24 scope global br0\n', '0\n'),
               'port down': ('eth0\neth1\neth2\n', self.BRIDGED.replace('4: eth2: <BROADCAST,UP,LOWER_UP>', '4: eth2: <BROADCAST>'), '0\n'),
               'routing': ('eth0\neth1\neth2\n', self.BRIDGED, '1\n'),
               'extra port': ('eth0\neth1\neth2\n', self.BRIDGED + '6: eth3: <BROADCAST,UP>\n', '0\n')}
        for label, (ports, text, forwarding) in bad.items():
            replies = {'bridge-ports': ports, 'addresses': text, 'forwarding': forwarding}
            with self.subTest(label), patch('network_labs.appliances.guest_startup.query', side_effect=lambda s, o, **k: replies[o]), self.assertRaises(ValueError):
                check_switch('/socket', node)

    def test_switch_save_rebuilds_from_declared_ports_and_keeps_no_guest_network(self):
        from types import SimpleNamespace
        from pathlib import Path
        from network_labs.appliances.microvm import switch_example
        from network_labs.appliances.guest_startup import save_observed
        spec = switch_example('/kernel', '/disk')
        manager = SimpleNamespace(name='microvm-switch', directory=Path('/private'), state=None, read=lambda: {'phase': 'running', 'spec': copy.deepcopy(spec)})
        empty = {'addresses': [], 'routes': []}
        with patch('network_labs.appliances.guest_startup.check_switch') as check, patch('network_labs.appliances.guest_startup.observe', return_value=empty), \
             patch('network_labs.appliances.persistence.save_startup') as save:
            save_observed(manager)
        self.assertEqual(check.call_count, 2)
        saved = save.call_args.args[1]
        self.assertNotIn('guest_network', saved['nodes'][0])
        self.assertEqual([n['guest_network'] for n in saved['nodes'][1:]], [empty] * 3)

    def test_plain_switch_role_is_unnumbered_and_boots_without_ip(self):
        from network_labs.appliances.microvm import switch_example
        from network_labs.appliances.runtime import firecracker_config
        from pathlib import Path
        spec = switch_example('/kernel', '/disk')
        self.assertNotIn('ip=', firecracker_config(spec['nodes'][0], Path('/k'), Path('/d'))['boot-source']['boot_args'])
        changes = {'numbered port': lambda n: n['interfaces'].update(eth0='192.0.2.1/24'),
                   'one port': lambda n: n.update(interfaces={'eth0': ''}, switchports={}),
                   'gateway': lambda n: n.update(gateway='192.0.2.1'),
                   'guest network': lambda n: n.update(guest_network={'addresses': [], 'routes': []}),
                   'firewall': lambda n: n.update(firewall={'default': 'drop', 'stateful': True, 'rules': [], 'nat': []})}
        for label, change in changes.items():
            bad = copy.deepcopy(spec); change(bad['nodes'][0])
            with self.subTest(label), self.assertRaises(ValueError): validate(bad)

    def dhcp_lab(self):
        from network_labs.appliances.microvm import dhcp_example
        return dhcp_example('/kernel', '/disk')

    LEASED = ('1: lo: <LOOPBACK,UP,LOWER_UP>\n    inet 127.0.0.1/8 scope host lo\n'
              '2: eth0: <BROADCAST,UP,LOWER_UP>\n    inet 192.0.2.100/24 scope global eth0\n')

    def test_dhcp_rules_on_guests(self):
        spec = self.dhcp_lab(); router, client = spec['nodes'][0], spec['nodes'][1]
        self.assertEqual((client['interfaces'], client['dhcp_clients'], router['dhcp_server']['router']), ({'eth0': ''}, ['eth0'], '192.0.2.1'))
        changes = {'client on a router': lambda nodes: nodes[0].update(dhcp_clients=['eth0'], interfaces={'eth0': '', 'eth1': '198.51.100.1/24'}),
                   'client with a static gateway': lambda nodes: nodes[1].update(gateway='192.0.2.1'),
                   'unnumbered port without DHCP': lambda nodes: nodes[1].update(dhcp_clients=[]),
                   'remote pool': lambda nodes: nodes[0]['dhcp_server'].update(network='10.9.0.0/24', start='10.9.0.10', end='10.9.0.20', router=''),
                   'reservation': lambda nodes: nodes[0]['dhcp_server'].update(reservations=[{'mac': '02:00:00:00:00:01', 'address': '192.0.2.110'}]),
                   'extra address on a DHCP port': lambda nodes: nodes[1].update(guest_network={'addresses': ['198.18.0.1/32'], 'routes': []})}
        for label, change in changes.items():
            bad = copy.deepcopy(spec); change(bad['nodes'])
            with self.subTest(label), self.assertRaises(ValueError): validate(bad)

    def test_dhcp_wire_format_and_rejections(self):
        from network_labs.appliances.guest_control import _dhcp_command, request
        from network_labs.appliances.guest_startup import dhcp_pool
        router = self.dhcp_lab()['nodes'][0]
        self.assertEqual(_dhcp_command('dhcp-serve', 'eth0', dhcp_pool(router)), 'DHCP_SERVE eth0 192.0.2.100 192.0.2.120 255.255.255.0 192.0.2.1 600 -')
        self.assertEqual(_dhcp_command('dhcp-serve', 'eth0', dict(dhcp_pool(router), dns=['192.0.2.53', '198.51.100.53'], router='')).split()[-3:], ['-', '600', '192.0.2.53,198.51.100.53'])
        self.assertEqual((_dhcp_command('dhcp-client', 'eth1', None), _dhcp_command('dhcp-leases', 'eth0', None)), ('DHCP_CLIENT eth1', 'DHCP_LEASES eth0'))
        pool = dhcp_pool(router)
        for interface, server in (('eth9', pool), ('eth0', dict(pool, end='192.0.3.200')), ('eth0', dict(pool, lease_seconds=5)),
                                  ('eth0', dict(pool, dns=['1.1.1.1'] * 4)), ('eth0', dict(pool, extra='x')), ('eth0', None)):
            with self.subTest(interface=interface, server=server), self.assertRaises(ValueError): _dhcp_command('dhcp-serve', interface, server)
        with self.assertRaises(ValueError): _dhcp_command('dhcp-client', 'eth0', pool)
        with self.assertRaises(ValueError): request('/missing', 'dhcp-client', interface='eth0', cidr='192.0.2.1/24')

    def test_leased_address_and_default_route_are_never_saved(self):
        client = self.dhcp_lab()['nodes'][1]
        routes = '192.0.2.0/24 dev eth0 scope link src 192.0.2.100\ndefault via 192.0.2.1 dev eth0\n'
        with patch('network_labs.appliances.guest_startup.query', side_effect=[self.LEASED, routes, '0\n']):
            self.assertEqual(observe('/socket', client), {'addresses': [], 'routes': []})
        # Before a lease arrives the port is up and holds nothing: still savable.
        with patch('network_labs.appliances.guest_startup.query', side_effect=['2: eth0: <BROADCAST,UP>\n', '', '0\n']):
            self.assertEqual(observe('/socket', client), {'addresses': [], 'routes': []})
        with patch('network_labs.appliances.guest_startup.query', return_value='2: eth0: <BROADCAST>\n'), self.assertRaises(ValueError):
            observe('/socket', client)

    def test_startup_starts_the_server_and_the_client_without_waiting_for_a_lease(self):
        from network_labs.appliances import guest_startup
        router, client = self.dhcp_lab()['nodes'][:2]
        calls = []
        def fake(socket, operation, **kw):
            calls.append((operation, kw.get('interface'))); return {'forwarding': '1\n', 'dhcp-leases': 'Mac Address       IP Address      Host Name           Expires in\n'}.get(operation, '')
        with patch.object(guest_startup, 'query', side_effect=fake), patch.object(guest_startup, 'observe', return_value={'addresses': [], 'routes': []}):
            apply('/socket', router)
        names = [c[0] for c in calls]
        self.assertLess(names.index('forward'), names.index('dhcp-serve')); self.assertEqual(calls[names.index('dhcp-serve')][1], 'eth0')
        self.assertIn('dhcp-leases', names)
        calls.clear()
        with patch.object(guest_startup, 'query', side_effect=fake), patch.object(guest_startup, 'observe', return_value={'addresses': [], 'routes': []}):
            apply('/socket', client)
        self.assertEqual(calls, [('ready', None), ('link', 'eth0'), ('dhcp-client', 'eth0')])

    def test_lease_listing_is_parsed_and_a_stopped_server_fails(self):
        from network_labs.appliances import guest_startup
        listing = ('Mac Address       IP Address      Host Name           Expires in\n'
                   '52:54:00:12:34:56 192.0.2.100     vm2                 00:09:58\n'
                   '52:54:00:ab:cd:ef 192.0.2.101                         00:09:40\n'
                   '52:54:00:00:00:01 192.0.2.102                         1 days 02:00:00\n')
        with patch.object(guest_startup, 'query', return_value=listing):
            self.assertEqual(guest_startup.leases('/socket', 'eth0'), [{'mac': '52:54:00:12:34:56', 'address': '192.0.2.100', 'hostname': 'vm2'},
                                                                       {'mac': '52:54:00:ab:cd:ef', 'address': '192.0.2.101', 'hostname': ''},
                                                                       {'mac': '52:54:00:00:00:01', 'address': '192.0.2.102', 'hostname': ''}])
        with patch.object(guest_startup, 'query', side_effect=ValueError('Guest dhcp-leases failed: dhcp server not running')), self.assertRaisesRegex(ValueError, 'not running'):
            guest_startup.leases('/socket', 'eth0')

    def test_container_dhcp_starters_leave_micro_vms_to_guest_startup(self):
        from types import SimpleNamespace
        from network_labs.appliances.dhcp import start_clients, start_servers
        manager = SimpleNamespace(state={'spec': self.dhcp_lab()}, crun=lambda *a, **k: self.fail('crun called for a micro-VM: ' + repr(a)),
                                  directory=None)
        start_servers(manager); start_clients(manager)


class SwitchVlanTests(unittest.TestCase):
    """Access and trunk ports on a switch guest: lab-file rules, wire format, startup order and readback."""

    def lab(self):
        from network_labs.appliances.microvm import switch_vlan_example
        return switch_vlan_example('/kernel', '/disk')

    LISTING = ('br0 1 pvid untagged\n'
               'eth0 10 pvid untagged\neth1 10 pvid untagged\neth2 20 pvid untagged\n'
               'eth3 1 pvid untagged\neth3 10\neth3 20\n')

    def test_lab_rules(self):
        spec = self.lab()
        changes = {
            'trunk with an undeclared VLAN': lambda nodes: nodes[0]['switchports']['eth3'].update(allowed=[10, 30]),
            'trunk native VLAN undeclared': lambda nodes: nodes[0]['switchports']['eth3'].update(native_vlan=99),
            'access VLAN undeclared': lambda nodes: nodes[0]['switchports']['eth0'].update(vlan=30),
            'too many VLANs': lambda nodes: nodes[0].update(vlans=list(range(1, 40))),
            'numbered switch port': lambda nodes: nodes[0]['interfaces'].update(eth0='192.0.2.1/24'),
        }
        for label, change in changes.items():
            bad = copy.deepcopy(spec)
            change(bad['nodes'])
            with self.subTest(label), self.assertRaises(ValueError):
                validate(bad)
        whole = copy.deepcopy(spec)
        whole['nodes'][0]['switchports']['eth3']['allowed'] = 'all'
        from network_labs.appliances.guest_startup import vlan_plan
        self.assertIn(('eth3', 10, 'tagged'), vlan_plan(validate(whole)['nodes'][0]))

    def test_wire_format_and_rejections(self):
        from network_labs.appliances.guest_control import _bridge_vlan_command, request
        self.assertEqual(_bridge_vlan_command('bridge-vlan-add', 'eth3', 10, 'tagged'), 'BRIDGE_VLAN_ADD eth3 10 tagged')
        self.assertEqual(_bridge_vlan_command('bridge-vlan-add', 'eth0', 20, 'pvid'), 'BRIDGE_VLAN_ADD eth0 20 pvid')
        self.assertEqual(_bridge_vlan_command('bridge-vlan-delete', 'eth0', 1, None), 'BRIDGE_VLAN_DEL eth0 1')
        self.assertEqual(_bridge_vlan_command('bridge-vlans', None, None, None), 'BRIDGE_VLANS')
        bad = [('bridge-vlan-add', 'eth9', 10, 'pvid'), ('bridge-vlan-add', 'eth0', 0, 'pvid'), ('bridge-vlan-add', 'eth0', 4095, 'pvid'),
               ('bridge-vlan-add', 'eth0', '10', 'pvid'), ('bridge-vlan-add', 'eth0', 10, 'untagged'),
               ('bridge-vlan-delete', 'eth0', 10, 'pvid'),
               ('bridge-vlans', 'eth0', None, None), ('bridge-vlan-filtering', None, 1, None)]
        for operation, interface, vlan, state in bad:
            with self.subTest(operation=operation, interface=interface, vlan=vlan, state=state), self.assertRaises(ValueError):
                _bridge_vlan_command(operation, interface, vlan, state)
        with self.assertRaises(ValueError):
            request('/missing', 'ping', destination='192.0.2.1', vlan=10)

    def test_startup_enables_filtering_drops_default_vlan_and_adds_untagged_last(self):
        from network_labs.appliances import guest_startup
        switch = self.lab()['nodes'][0]
        calls = []
        replies = {'bridge-ports': 'eth0\neth1\neth2\neth3\n', 'bridge-vlans': self.LISTING, 'forwarding': '0\n',
                   'addresses': ''.join(f'{i + 2}: eth{i}: <BROADCAST,UP>\n' for i in range(4)) + '6: br0: <BROADCAST,UP>\n'}

        def fake(socket, operation, **kw):
            calls.append((operation, kw.get('interface'), kw.get('vlan'), kw.get('state')))
            return replies.get(operation, '')
        with patch.object(guest_startup, 'query', side_effect=fake):
            apply('/socket', switch)
        names = [c[0] for c in calls]
        self.assertLess(names.index('bridge-add'), names.index('bridge-vlan-filtering'))
        self.assertEqual([c[1:3] for c in calls if c[0] == 'bridge-vlan-delete'], [(f'eth{i}', 1) for i in range(4)])
        adds = [c[1:] for c in calls if c[0] == 'bridge-vlan-add']
        self.assertEqual(sorted(adds), sorted(guest_startup.vlan_plan(switch)))
        first_pvid = next(i for i, add in enumerate(adds) if add[2] == 'pvid')
        self.assertTrue(all(add[2] == 'pvid' for add in adds[first_pvid:]))

    def test_plain_switch_never_touches_vlans_and_a_kernel_without_filtering_is_named(self):
        from network_labs.appliances import guest_startup
        from network_labs.appliances.microvm import switch_example
        plain = switch_example('/kernel', '/disk')['nodes'][0]
        replies = {'bridge-ports': 'eth0\neth1\neth2\n', 'forwarding': '0\n',
                   'addresses': ''.join(f'{i + 2}: eth{i}: <BROADCAST,UP>\n' for i in range(3)) + '5: br0: <BROADCAST,UP>\n'}
        with patch.object(guest_startup, 'query', side_effect=lambda socket, operation, **kw: replies.get(operation, '')) as query:
            apply('/socket', plain)
        self.assertFalse([c for c in query.call_args_list if c.args[1].startswith('bridge-vlan')])

        def no_filtering(socket, operation, **kw):
            if operation == 'bridge-vlan-filtering':
                raise ValueError('Guest bridge-vlan-filtering failed: no bridge vlan filtering in this guest kernel')
            return ''
        with patch.object(guest_startup, 'query', side_effect=no_filtering), self.assertRaisesRegex(ValueError, 'tools/guest_kernel'):
            apply('/socket', self.lab()['nodes'][0])

    def test_readback_compares_port_membership_exactly(self):
        from network_labs.appliances import guest_startup
        switch = self.lab()['nodes'][0]
        with patch.object(guest_startup, 'query', return_value=self.LISTING):
            self.assertEqual(guest_startup.observed_vlans('/socket', switch), guest_startup.vlan_plan(switch))
        for wrong in (self.LISTING.replace('eth3 20\n', ''), self.LISTING + 'eth0 20\n', self.LISTING.replace('eth2 20', 'eth2 10')):
            with patch.object(guest_startup, 'query', return_value=wrong):
                self.assertNotEqual(guest_startup.observed_vlans('/socket', switch), guest_startup.vlan_plan(switch))
        with patch.object(guest_startup, 'query', return_value=self.LISTING + 'eth1 30 pvid\n'):
            with self.assertRaisesRegex(ValueError, 'Unmanaged'):
                guest_startup.observed_vlans('/socket', switch)
