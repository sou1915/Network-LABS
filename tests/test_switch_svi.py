"""A switch's management interface typed as in Packet Tracer: « interface vlan 1 », « ip address », « no shutdown »,
« ip default-gateway »: the address sits on the switch guest's bridge, shut until « no shutdown », reachable from the PCs."""
import copy
import unittest
from unittest import mock

from network_labs.appliances import guest_console, guest_startup
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.network_model import Model, static_routes
from network_labs.appliances.spec import validate
from network_labs.appliances.svi import management

from tests.test_native_microvm_switch_live import lab

MANAGEMENT = ['en', 'conf t', 'int vlan 1', 'ip address 10.0.0.250 255.255.255.0', 'exit', 'ip default-gateway 10.0.0.1', 'end']


class SwitchSviTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': lab('/k', '/d')}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))
        self.sw = guest_console.Console('switch-live', 'SW1', lambda _: self.lab)

    def type(self, lines):
        return [self.sw.line(line) for line in lines]

    def node(self):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == 'SW1')

    def test_the_svi_is_shut_until_no_shutdown_then_answers(self):
        self.type(MANAGEMENT)
        self.assertIsNone(management(self.node()))  # a new interface vlan is shut, as on a Catalyst
        self.assertRegex(self.sw.line('sh ip int br'), r'Vlan1\s+10\.0\.0\.250\s+YES manual administratively down down')
        self.assertFalse(Model(self.box['spec']).ping('PC1', '10.0.0.250')[0])
        replies = self.type(['conf t', 'int vlan 1', 'no shut', 'end'])
        self.assertIn('%LINK-5-CHANGED: Interface Vlan1, changed state to up', replies[2])
        self.assertEqual(management(self.node()), {'name': 'vlan1', 'vlan': 1, 'address': '10.0.0.250/24', 'gateway': '10.0.0.1'})
        self.assertEqual([(str(n), str(g)) for n, g in static_routes(self.node())], [('0.0.0.0/0', '10.0.0.1')])
        ok, why = Model(self.box['spec']).ping('PC1', '10.0.0.250')
        self.assertTrue(ok, why)
        self.assertIn('!!!!!', self.sw.line('ping 10.0.0.2'))  # the switch pings a PC from its SVI
        running = self.sw.line('sh run')
        self.assertIn('interface Vlan1\n ip address 10.0.0.250 255.255.255.0\n!', running)
        self.assertIn('ip default-gateway 10.0.0.1', running)

    def test_one_management_svi_and_its_removal(self):
        self.type(MANAGEMENT)
        reply = self.type(['conf t', 'int vlan 2'])[-1]
        self.assertIn('Une seule interface vlan de gestion', reply)
        self.type(['end', 'conf t', 'no int vlan 1', 'end'])
        self.assertEqual((self.node()['svis'], self.node()['shutdown']), ({}, []))

    def test_a_running_switch_takes_the_svi_on_its_bridge(self):
        self.type(MANAGEMENT + ['conf t', 'int vlan 1', 'no shut', 'end'])
        up = copy.deepcopy(self.node())
        down = copy.deepcopy(up)
        down['svis'], down['shutdown'] = {}, []
        calls = []
        with mock.patch.object(guest_startup, 'query', lambda socket, operation, **fields: calls.append((operation, fields)) or ''), \
                mock.patch.object(guest_startup, 'check_switch', lambda socket, node: None):
            guest_startup.change_switch('/unused', down, up)
            self.assertEqual(calls, [('address-add', {'interface': 'br0', 'cidr': '10.0.0.250/24'}),
                                     ('route-add', {'network': '0.0.0.0/0', 'gateway': '10.0.0.1', 'interface': 'br0'})])
            calls.clear()
            guest_startup.change_switch('/unused', up, down)
            self.assertEqual([c[0] for c in calls], ['route-delete', 'address-delete'])
            calls.clear()
            tagged = copy.deepcopy(up)  # VLAN filtering on, SVI in VLAN 10: the bridge itself moves to VLAN 10
            tagged['vlans'], tagged['switchports'] = [1, 10], {'eth0': {'mode': 'access', 'vlan': 10}}
            tagged['svis'] = {'vlan10': {'vlan': 10, 'address': '10.0.0.250/24'}}
            guest_startup.change_switch('/unused', down, tagged)
            self.assertEqual([(c[0], c[1].get('interface'), c[1].get('vlan')) for c in calls if c[1].get('interface') == 'br0'][:2],
                             [('bridge-vlan-add', 'br0', 10), ('bridge-vlan-delete', 'br0', 1)])


if __name__ == '__main__':
    unittest.main()
