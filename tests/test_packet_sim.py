"""Simulation mode: each frame of a ping, cable by cable, as Packet Tracer shows it — ARP first (a broadcast flooding
the VLAN, the reply unicast), then the ICMP request and reply, along the routed path the model computes and, between
routers, across the switches of the VLAN (tags on trunks, the tree spanning tree leaves), with headers and TTLs."""
import os
import unittest

from network_labs.appliances.microvm import router_on_a_stick_example
from network_labs.appliances.packet_sim import simulate
from network_labs.appliances.runtime import guest_mac

from tests.test_guest_stp import lab as loop_lab
from tests.test_layer3_switch import ROUTING, VLANS, lab as l3_lab


def crossings(result, kind=None):
    return [(e['from'], e['from_port'], e['to'], e['to_port'], e.get('tag')) for e in result['events'] if kind in (None, e['kind'])]


def typed(spec, node, lines):
    from network_labs.appliances import guest_console
    from network_labs.appliances.draft_lab import DraftLab
    from network_labs.appliances.spec import validate
    box = {'spec': spec}
    draft = DraftLab(lambda: box['spec'], lambda s: box.update(spec=validate(s)))
    console = guest_console.Console(spec['name'], node, lambda _: draft)
    for line in lines:
        console.line(line)
    return box['spec']


def cisco(mac):
    digits = mac.replace(':', '')
    return '.'.join(digits[i:i + 4] for i in range(0, 12, 4))


class PacketSimTest(unittest.TestCase):
    def test_router_on_a_stick_tags_each_vlan_on_the_trunk(self):
        result = simulate(router_on_a_stick_example('/k', '/d'), 'VM1', '198.51.100.10')
        self.assertTrue(result['ok'])
        self.assertEqual(crossings(result, 'ICMP'), [
            ('VM1', 'eth0', 'SW1', 'eth0', None), ('SW1', 'eth2', 'R1', 'eth0', 10),  # request: VLAN 10 up the trunk
            ('R1', 'eth0', 'SW1', 'eth2', 20), ('SW1', 'eth1', 'VM2', 'eth0', None),  # routed into VLAN 20
            ('VM2', 'eth0', 'SW1', 'eth1', None), ('SW1', 'eth2', 'R1', 'eth0', 20),  # reply
            ('R1', 'eth0', 'SW1', 'eth2', 10), ('SW1', 'eth0', 'VM1', 'eth0', None)])
        request = next(e for e in result['events'] if e['kind'] == 'ICMP' and e['from'] == 'R1')
        self.assertEqual(request['layers']['Couche 3'], 'IPv4 : 192.0.2.10 → 198.51.100.10, TTL 63')  # one router passed
        self.assertIn('802.1Q VLAN 20', request['layers']['Couche 2'])
        self.assertIn(f'{cisco(guest_mac("R1", "eth0"))} → {cisco(guest_mac("VM2", "eth0"))}', request['layers']['Couche 2'])
        self.assertEqual(request['layers']['Couche 4'], 'ICMP Echo Request (type 8)')

    def test_arp_comes_once_per_next_hop_and_both_ends_learn(self):
        result = simulate(router_on_a_stick_example('/k', '/d'), 'VM1', '198.51.100.10')
        arp = [e for e in result['events'] if e['kind'] == 'ARP']
        self.assertEqual([e['what'] for e in arp if e['what'] == 'réponse ARP' and e['to'] in ('VM1', 'R1')],
                         ['réponse ARP', 'réponse ARP'])  # VM1 asks for R1, R1 for VM2; the replies need none
        first = arp[0]
        self.assertIn('ffff.ffff.ffff', first['layers']['Couche 2'])
        self.assertEqual(first['layers']['ARP'], 'Requête : Qui a 192.0.2.1 ? Répondre à 192.0.2.10')
        steps = [e['step'] for e in result['events']]
        self.assertEqual(steps, sorted(steps))
        self.assertLess(max(e['step'] for e in arp if e['to'] == 'VM1'),
                        min(e['step'] for e in result['events'] if e['kind'] == 'ICMP'))  # ARP before the first echo
        self.assertEqual(len(simulate(router_on_a_stick_example('/k', '/d'), 'VM1', '198.51.100.10', arp=False)['events']), 8)

    def test_the_broadcast_floods_the_vlan_and_stops_at_the_blocked_port(self):
        result = simulate(loop_lab(), 'PC1', '192.168.1.20')
        self.assertTrue(result['ok'])
        flood = [e for e in result['events'] if e['what'] == 'requête ARP (diffusion)']
        together = [e for e in flood if e['step'] == flood[-1]['step']]
        self.assertGreater(len(together), 1)  # frames that leave a switch at once move together
        refused = [e for e in flood if 'bloqué par le spanning tree' in e['arrival']]
        self.assertEqual([(e['to'], e['to_port']) for e in refused], [('SW1', 'eth1')])  # SW1's Fa0/2 blocks (Altn)
        self.assertNotIn(('SW1', 'eth1'), [(c[0], c[1]) for c in crossings(result, 'ICMP')])  # unicast follows the tree
        self.assertNotIn(('SW2', 'eth1', 'SW1', 'eth1', None), crossings(result, 'ICMP'))

    def test_a_layer_3_switch_routes_inside_itself(self):
        spec = typed(typed(l3_lab(), 'SW1', VLANS), 'SW1', ROUTING)
        result = simulate(spec, 'PC1', '192.168.20.10')
        self.assertTrue(result['ok'])
        self.assertEqual(crossings(result, 'ICMP')[:2], [('PC1', 'eth0', 'SW1', 'eth0', None), ('SW1', 'eth1', 'PC2', 'eth0', None)])
        hop = next(e for e in result['events'] if e['kind'] == 'ICMP' and e['to'] == 'SW1')
        self.assertIn('sortie par Vlan20, TTL 63', hop['arrival'])

    def test_a_ping_with_no_route_ends_with_the_drop_and_its_reason(self):
        result = simulate(router_on_a_stick_example('/k', '/d'), 'VM1', '203.0.113.9')
        self.assertFalse(result['ok'])
        last = result['events'][-1]
        self.assertEqual((last['kind'], last['to']), ('DROP', 'R1'))
        self.assertEqual(last['drop'], 'R1 n’a aucune route vers 203.0.113.9')


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class SimulationWindowTest(unittest.TestCase):
    def test_stepping_moves_envelopes_along_the_cables(self):
        import tkinter as tk
        from network_labs.__main__ import App
        root = tk.Tk()
        try:
            window = App(root).open_native_lab()
            window.load_spec(router_on_a_stick_example('/k', '/d'))
            root.update()
            sim = window.open_simulation('VM1', '198.51.100.10')
            root.update()
            self.assertEqual(len(sim.list.get_children()), len(sim.events))
            sim.step_forward()
            sim.draw_envelopes(sim.current(), 1.0)
            envelope = window.canvas.find_withtag('sim-envelope')
            self.assertTrue(envelope)
            box = window.canvas.bbox('sim-envelope')
            link = next(i for i, (a, b) in enumerate(window.graph['links']) if {a[0], b[0]} == {'SW1', 'VM1'})
            coords = window.canvas.coords(window.link_shapes[link])
            self.assertTrue(any(abs((box[0] + box[2]) / 2 - x) < 2 and abs((box[1] + box[3]) / 2 - y) < 2
                                for x, y in zip(coords[::2], coords[1::2])))  # at the cable's end, by SW1
            sim.step_back()
            self.assertFalse(window.canvas.find_withtag('sim-envelope'))
            while sim.position < len(sim.steps):
                sim.step_forward()
            sim.finish()
            self.assertIn('Ping réussi', sim.status.get())
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
