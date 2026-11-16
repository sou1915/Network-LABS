"""Route commands must describe an applicable, unambiguous Linux route."""
import copy
import unittest

from network_labs.appliances.examples import static_routing_lab, svi_lab
from network_labs.appliances.ios import compile_config
from network_labs.appliances.spec import validate


class StaticRouteTests(unittest.TestCase):
    def configure(self, spec, text, name='SW1'):
        return compile_config(spec, name, 'conf t\n' + text + '\nend')

    def test_forward_and_return_routes_resolve_real_svi_and_physical_aliases(self):
        spec = static_routing_lab('/rootfs')
        configured = self.configure(spec, 'ip route 203.0.113.0 255.255.255.0 198.18.0.2')
        self.assertEqual(configured['nodes'][1]['routes'], [
            {'destination': '203.0.113.0/24', 'gateway': '198.18.0.2', 'interface': 'vlan20'}])
        configured = self.configure(configured, 'ip route 192.0.2.0 255.255.255.0 gi0/0 198.18.0.1', 'R1')
        self.assertEqual(configured['nodes'][2]['routes'][0]['interface'], 'eth0')
        self.assertFalse(spec['nodes'][1]['routes'])

    def test_default_host_and_explicit_svi_routes_have_distinct_persistent_models(self):
        spec = static_routing_lab('/rootfs')
        result = self.configure(spec, 'ip route 0.0.0.0 0.0.0.0 198.18.0.2\nip route 203.0.113.10 255.255.255.255 Vlan 20 198.18.0.3')
        self.assertEqual(result['nodes'][1]['gateway'], '198.18.0.2')
        self.assertEqual(result['nodes'][1]['routes'][0]['destination'], '203.0.113.10/32')
        result = self.configure(result, 'no ip route 0.0.0.0 0.0.0.0 198.18.0.2\nno ip route 203.0.113.10 255.255.255.255 198.18.0.3')
        self.assertEqual(result['nodes'][1]['gateway'], '')
        self.assertEqual(result['nodes'][1]['routes'], [])

    def test_duplicate_add_and_nonmatching_removal_do_not_erase_other_routes(self):
        spec = static_routing_lab('/rootfs')
        route = 'ip route 203.0.113.0 255.255.255.0 198.18.0.2'
        configured = self.configure(spec, route + '\n' + route)
        unchanged = self.configure(configured, 'no ip route 203.0.113.0 255.255.255.0 198.18.0.3')
        self.assertEqual(unchanged, configured)
        with self.assertRaisesRegex(ValueError, 'remove the existing'):
            self.configure(configured, 'ip route 203.0.113.0 255.255.255.0 198.18.0.3')
        replaced = self.configure(configured, 'no ' + route + '\nip route 203.0.113.0 255.255.255.0 198.18.0.3')
        self.assertEqual(replaced['nodes'][1]['routes'][0]['gateway'], '198.18.0.3')

    def test_bad_masks_host_bits_unusable_or_recursive_next_hops_and_extensions_fail_atomically(self):
        invalid = [
            'ip route 203.0.113.10 255.255.255.0 198.18.0.2',
            'ip route 203.0.113.0 0.0.0.255 198.18.0.2',
            'ip route 203.0.113.0 255.0.255.0 198.18.0.2',
            'ip route 203.0.113.0 24 198.18.0.2',
            'ip route 203.0.113.0 255.255.255.0 203.0.113.2',
            'ip route 203.0.113.0 255.255.255.0 198.18.0.0',
            'ip route 203.0.113.0 255.255.255.0 198.18.0.7',
            'ip route 203.0.113.0 255.255.255.0 198.18.0.1',
            'ip route 203.0.113.0 255.255.255.0 192.0.2.1',
            'ip route 203.0.113.0 255.255.255.0 224.0.0.1',
            'ip route 203.0.113.0 255.255.255.0 vlan10 198.18.0.2',
            'ip route 203.0.113.0 255.255.255.0 eth1 198.18.0.2',
            'ip route 203.0.113.0 255.255.255.0 198.18.0.2 5',
            'ip route 203.0.113.0 255.255.255.0 Null0',
            'ip route 0.0.0.0 0.0.0.0 vlan20 198.18.0.2',
            'ip route 192.0.2.0 255.255.255.0 198.18.0.2',
        ]
        for command in invalid:
            spec = static_routing_lab('/rootfs'); before = copy.deepcopy(spec)
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.configure(spec, 'interface vlan10\nshutdown\nexit\n' + command)
            self.assertEqual(spec, before)

    def test_overlapping_on_link_interfaces_require_explicit_selection(self):
        spec = static_routing_lab('/rootfs')
        router = spec['nodes'][2]
        router['interfaces']['eth2'] = '198.18.0.4/29'
        spec = validate(spec)
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            self.configure(spec, 'ip route 192.0.2.0 255.255.255.0 198.18.0.1', 'R1')
        result = self.configure(spec, 'ip route 192.0.2.0 255.255.255.0 gi0/0 198.18.0.1', 'R1')
        self.assertEqual(result['nodes'][2]['routes'][0]['interface'], 'eth0')

    def test_next_hop_resolution_can_use_a_configured_dot1q_subinterface(self):
        spec = static_routing_lab('/rootfs'); router = spec['nodes'][2]
        router['interfaces']['eth0'] = ''
        router['subinterfaces'] = {'eth0.20': {'parent': 'eth0', 'vlan': 20, 'address': '198.18.0.2/29'}}
        spec = validate(spec)
        result = self.configure(spec, 'ip route 192.0.2.0 255.255.255.0 gi0/0.20 198.18.0.1', 'R1')
        self.assertEqual(result['nodes'][2]['routes'][0]['interface'], 'eth0.20')

    def test_default_replacement_is_explicit_and_wrong_hop_removal_is_harmless(self):
        spec = self.configure(static_routing_lab('/rootfs'), 'ip route 0.0.0.0 0.0.0.0 198.18.0.2')
        unchanged = self.configure(spec, 'no ip route 0.0.0.0 0.0.0.0 198.18.0.3')
        self.assertEqual(unchanged, spec)
        with self.assertRaisesRegex(ValueError, 'Remove the existing default'):
            self.configure(spec, 'ip route 0.0.0.0 0.0.0.0 198.18.0.3')

    def test_wrong_context_and_unnumbered_l2_switch_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Line 3'):
            compile_config(static_routing_lab('/rootfs'), 'R1', 'conf t\ninterface gi0/0\nip route 192.0.2.0 255.255.255.0 198.18.0.1')
        with self.assertRaises(ValueError):
            self.configure(svi_lab('/rootfs'), 'ip route 203.0.113.0 255.255.255.0 198.18.0.2', 'SW2')
