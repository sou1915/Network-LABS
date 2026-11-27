"""A Layer 3 switch: on a Catalyst 9200L micro-VM, « ip routing » and one « interface vlan N » per VLAN route between the
VLANs (inter-VLAN routing without a router); each SVI is the bridge's VLAN interface br0.N in the guest, which forwards.
A 2960 refuses ip routing and a second SVI, as on IOS. « ip route » on the routing switch goes through the SVI that
reaches its next hop."""
import copy
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console, svi, topology_edit
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project

VLANS = ['en', 'conf t', 'vlan 10', 'name STAFF', 'vlan 20', 'name GUESTS', 'int g1/0/1', 'sw mo acc', 'sw acc vl 10',
         'int g1/0/2', 'sw mo acc', 'sw acc vl 20', 'int vlan 10', 'ip add 192.168.10.1 255.255.255.0', 'no sh',
         'int vlan 20', 'ip add 192.168.20.1 255.255.255.0', 'no sh', 'end']
ROUTING = ['en', 'conf t', 'ip routing', 'end']


def lab(kernel='/k', disk='/d', model='cisco-9200l'):
    """SW1 (three ports) with PC1 on its first port (192.168.10.10, gateway .1) and PC2 on its second (192.168.20.10)."""
    spec = blank_project('l3')
    spec = topology_edit.add_microvm_node(spec, name='SW1', role='switch', kernel=kernel, disk=disk, ports=3, model=model)
    for name, address in (('PC1', '192.168.10.10/24'), ('PC2', '192.168.20.10/24')):
        spec = topology_edit.add_microvm_node(spec, name=name, role='host', kernel=kernel, disk=disk, ports=1, addresses=address)
    spec = topology_edit.connect(spec, ('PC1', 'eth0'), ('SW1', 'eth0'))
    spec = topology_edit.connect(spec, ('PC2', 'eth0'), ('SW1', 'eth1'))
    spec = validate(spec)
    for name, gateway in (('PC1', '192.168.10.1'), ('PC2', '192.168.20.1')):
        next(n for n in spec['nodes'] if n['name'] == name)['gateway'] = gateway
    return validate(spec)


class Layer3SwitchTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': lab()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def type(self, name, lines):
        console = guest_console.Console('l3', name, lambda _: self.lab)
        return [console.line(line) for line in lines]

    def node(self, name='SW1'):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == name)

    def test_ip_routing_routes_between_the_vlans(self):
        self.type('SW1', VLANS)
        self.assertIn('0 packets received', self.type('PC1', ['ping 192.168.20.10'])[0])  # a Layer 2 switch until ip routing
        self.assertEqual(self.type('SW1', ['en', 'sh ip route'])[-1].splitlines()[0], 'Default gateway is not set')
        self.type('SW1', ROUTING)
        self.assertTrue(svi.routing(self.node()))
        self.assertEqual([(s['name'], s['device'], s['address']) for s in svi.routed(self.node())],
                         [('vlan10', 'br0.10', '192.168.10.1/24'), ('vlan20', 'br0.20', '192.168.20.1/24')])
        self.assertIn('4 packets received', self.type('PC1', ['ping 192.168.20.10'])[0])
        trace = self.type('PC1', ['tracert 192.168.20.10'])[0]
        self.assertRegex(trace, r'1 .* 192\.168\.10\.1\n.*2 .* 192\.168\.20\.10')
        table = self.type('SW1', ['en', 'sh ip route'])[-1]
        self.assertIn('C        192.168.10.0/24 is directly connected, Vlan10', table)
        self.assertIn('L        192.168.20.1/32 is directly connected, Vlan20', table)
        self.assertRegex(self.type('SW1', ['en', 'sh ip int br'])[-1], r'Vlan20 +192\.168\.20\.1 +YES manual up +up')
        self.assertIn('\nip routing\n', self.type('SW1', ['en', 'sh run'])[-1])
        self.type('SW1', ['en', 'conf t', 'no ip routing', 'end'])
        self.assertIn('0 packets received', self.type('PC1', ['ping 192.168.20.10'])[0])

    def test_a_static_route_goes_through_the_svi_that_reaches_its_next_hop(self):
        self.type('SW1', VLANS + ROUTING)
        self.type('SW1', ['en', 'conf t', 'ip route 0.0.0.0 0.0.0.0 192.168.20.254', 'ip route 10.9.0.0 255.255.0.0 172.16.0.1', 'end'])
        self.assertEqual([(str(n), str(g), d) for n, g, d, _ in svi.static_routes(self.node())],
                         [('0.0.0.0/0', '192.168.20.254', 'br0.20')])  # the second next hop is on no SVI: kept, unused
        table = self.type('SW1', ['en', 'sh ip route'])[-1]
        self.assertIn('Gateway of last resort is 192.168.20.254 to network 0.0.0.0', table)
        self.assertIn('S*       0.0.0.0/0 [1/0] via 192.168.20.254, Vlan20', table)
        self.assertIn('ip route 10.9.0.0 255.255.0.0 172.16.0.1', self.type('SW1', ['en', 'sh run'])[-1])
        self.type('SW1', ['en', 'conf t', 'no ip route 0.0.0.0 0.0.0.0', 'end'])
        self.assertEqual(svi.static_routes(self.node()), [])

    def test_a_2960_is_a_layer_2_switch(self):
        self.box['spec'] = lab(model='cisco-2960')
        replies = self.type('SW1', ['en', 'conf t', 'ip routing', 'int vlan 1', 'ip add 192.168.1.2 255.255.255.0', 'int vlan 10',
                                    'exit', 'ip route 0.0.0.0 0.0.0.0 192.168.1.1', 'end'])
        self.assertIn('% Invalid input detected', replies[2])  # as a 2960 answers it
        self.assertIn('Une seule interface vlan', replies[5])
        self.assertIn('% Invalid input detected', replies[7])
        self.assertNotIn('ip routing', self.type('SW1', ['en', 'conf t', 'ip ?'])[-1])

    def test_a_routing_switch_ignores_ip_default_gateway(self):
        self.type('SW1', VLANS + ['en', 'conf t', 'ip default-gateway 192.168.10.254', 'end'])
        self.assertEqual(svi.management(self.node())['gateway'], '192.168.10.254')
        self.type('SW1', ROUTING)
        self.assertIsNone(svi.management(self.node()))


class Layer3GuestTest(unittest.TestCase):
    def routed_lab(self, routes=()):
        box = {'spec': lab()}
        draft = DraftLab(lambda: box['spec'], lambda spec: box.update(spec=validate(spec)))
        console = guest_console.Console('l3', 'SW1', lambda _: draft)
        for line in VLANS + ROUTING + ['en', 'conf t', *routes, 'end']:
            console.line(line)
        return next(n for n in box['spec']['nodes'] if n['name'] == 'SW1')

    def test_boot_puts_each_svi_on_its_bridge_vlan_interface_then_forwards(self):
        from network_labs.appliances import guest_startup
        node = self.routed_lab(['ip route 0.0.0.0 0.0.0.0 192.168.20.254'])
        calls = []

        def fake(socket, operation, **kw):
            calls.append((operation, kw.get('interface'), kw.get('vlan'), kw.get('state') or kw.get('cidr') or kw.get('gateway')))
            return {'forwarding': '1\n', 'bridge-ports': 'eth0\neth1\neth2\n'}.get(operation, '')
        with patch.object(guest_startup, 'query', side_effect=fake), patch.object(guest_startup, 'check_switch'):
            guest_startup.apply('/socket', node)
        start = calls.index(('bridge-vlan-add', 'br0', 10, 'tagged'))
        self.assertEqual(calls[start:start + 9], [
            ('bridge-vlan-add', 'br0', 10, 'tagged'), ('vlan-add', 'br0', 10, None), ('link', 'br0.10', None, 'up'),
            ('address-add', 'br0.10', None, '192.168.10.1/24'),
            ('bridge-vlan-add', 'br0', 20, 'tagged'), ('vlan-add', 'br0', 20, None), ('link', 'br0.20', None, 'up'),
            ('address-add', 'br0.20', None, '192.168.20.1/24'),
            ('route-add', 'br0.20', None, '192.168.20.254')])
        self.assertEqual(calls[start + 9], ('forward', None, None, 'on'))
        self.assertNotIn(('address-add', 'br0'), [c[:2] for c in calls])  # no management address on the bridge itself

    def test_the_readback_wants_the_svi_interfaces_their_addresses_routes_and_forwarding(self):
        from network_labs.appliances import guest_startup
        node = self.routed_lab(['ip route 0.0.0.0 0.0.0.0 192.168.20.254'])
        listing = ''.join(f'{i + 2}: eth{i}: <BROADCAST,UP,LOWER_UP>\n' for i in range(3)) + '5: br0: <BROADCAST,UP,LOWER_UP>\n' \
            + '6: br0.10@br0: <BROADCAST,UP,LOWER_UP>\n    inet 192.168.10.1/24 scope global br0.10\n' \
            + '7: br0.20@br0: <BROADCAST,UP,LOWER_UP>\n    inet 192.168.20.1/24 scope global br0.20\n'
        replies = {'bridge-ports': 'eth0\neth1\neth2\n', 'addresses': listing, 'forwarding': '1\n',
                   'routes': 'default via 192.168.20.254 dev br0.20\n', 'bridge-vlans': '', 'bridge-stp-show': 'bridge stp_state 0\n'}
        with patch.object(guest_startup, 'query', side_effect=lambda s, o, **k: replies[o]), \
                patch.object(guest_startup, 'observed_vlans', return_value=guest_startup.vlan_plan(node)):
            guest_startup.check_switch('/socket', node)
            for label, change in (('no forwarding', {'forwarding': '0\n'}), ('no route', {'routes': ''}),
                                  ('missing SVI', {'addresses': listing.split('7: br0.20')[0]})):
                with self.subTest(label), patch.dict(replies, change), self.assertRaises(ValueError):
                    guest_startup.check_switch('/socket', node)

    def test_ip_routing_typed_live_adds_the_svis_then_forwards_and_no_ip_routing_undoes_it(self):
        from network_labs.appliances import guest_startup
        routed = self.routed_lab()
        plain = copy.deepcopy(routed)
        plain['cli_config']['global'] = [line for line in plain['cli_config']['global'] if line != 'ip routing']
        for old, new, first, last in ((plain, routed, ('address-delete', 'br0'), ('forward', None)),
                                      (routed, plain, ('forward', None), ('address-add', 'br0'))):
            calls = []
            with patch.object(guest_startup, 'query', side_effect=lambda s, o, **k: calls.append((o, k.get('interface'))) or ''), \
                    patch.object(guest_startup, 'check_switch'):
                guest_startup.change_switch('/socket', old, new)
            self.assertEqual((calls[0], calls[-1]), (first, last))  # the management address leaves first; forwarding last
            self.assertIn(('vlan-add' if new is routed else 'vlan-delete', 'br0' if new is routed else 'br0.20'), calls)


if __name__ == '__main__':
    unittest.main()
