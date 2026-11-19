"""Static routes through a port (« ip route 0.0.0.0 0.0.0.0 g0/0/1 ») and proxy ARP (on by default, « no ip proxy-arp »):
kept as IOS lines, shown as IOS shows them, followed by the network model as IOS and the guests forward."""
import unittest

from network_labs.appliances import guest_console, ios_routes
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.network_model import Model
from network_labs.appliances.spec import validate

from tests.test_ios_nat import lab

R1 = ['en', 'conf t', 'ip route 0.0.0.0 0.0.0.0 g0/0/1', 'end']
R2_BACK = ['en', 'conf t', 'ip route 192.168.1.0 255.255.255.0 203.0.113.1', 'int g0/0/0', 'no ip proxy-arp', 'end']


class PortRouteTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': lab()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def type(self, name, lines):
        console = guest_console.Console('ios-static-nat', name, lambda _: self.lab)
        return [console.line(line) for line in lines]

    def node(self, name):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == name)

    def reach(self):
        return Model(self.box['spec']).ping('PC1', '198.51.100.10')

    def test_a_route_through_a_port_needs_the_neighbours_proxy_arp(self):
        table = self.type('R1', R1 + ['sh ip route'])[-1]
        self.assertIn('Gateway of last resort is 0.0.0.0 to network 0.0.0.0', table)
        self.assertIn('S*       0.0.0.0/0 is directly connected, GigabitEthernet0/0/1', table)
        self.assertEqual(ios_routes.port_routes(self.node('R1'))[0][1], 'eth1')
        self.type('R2', R2_BACK)
        self.assertEqual(ios_routes.proxy_arp(self.node('R2')), {'eth0': False, 'eth1': True})
        ok, why = self.reach()
        self.assertFalse(ok)
        self.assertIn('ne répond pas sur ce segment', why)  # R2 does not answer R1's ARP for 198.51.100.10
        self.type('R2', ['en', 'conf t', 'int g0/0/0', 'ip proxy-arp', 'end'])
        ok, why = self.reach()
        self.assertTrue(ok, why)
        self.assertIn('ip route 0.0.0.0 0.0.0.0 GigabitEthernet0/0/1', self.type('R1', ['en', 'sh run'])[-1])
        self.type('R1', ['en', 'conf t', 'no ip route 0.0.0.0 0.0.0.0 g0/0/1', 'end'])
        self.assertEqual(ios_routes.port_routes(self.node('R1')), [])
        self.assertFalse(self.reach()[0])

    def test_a_next_hop_after_the_port_is_an_ordinary_route(self):
        self.type('R1', ['en', 'conf t', 'ip route 0.0.0.0 0.0.0.0 g0/0/1 203.0.113.2', 'end'])
        self.assertEqual((ios_routes.port_routes(self.node('R1')), self.node('R1').get('gateway') or
                          self.node('R1')['guest_network']['routes'][0]['gateway']), ([], '203.0.113.2'))

    def test_a_host_with_a_too_wide_mask_reaches_through_proxy_arp_as_on_ios(self):
        self.type('R1', ['en', 'conf t', 'ip route 0.0.0.0 0.0.0.0 203.0.113.2', 'end'])
        self.type('R2', ['en', 'conf t', 'ip route 192.168.1.0 255.255.255.0 203.0.113.1', 'end'])
        pc1 = self.node('PC1')
        pc1['interfaces']['eth0'], pc1['gateway'] = '192.168.1.10/16', None  # 198.51.100.10 is still off-link: needs a gateway
        self.box['spec'] = validate(self.box['spec'])
        self.assertFalse(self.reach()[0])
        pc1 = self.node('PC1')
        pc1['interfaces']['eth0'] = '192.168.1.10/1'  # now « on-link » for PC1: R1 answers its ARP by proxy
        self.box['spec'] = validate(self.box['spec'])
        ok, why = self.reach()
        self.assertTrue(ok, why)


if __name__ == '__main__':
    unittest.main()
