"""Static dual-stack routing keeps protocol policy and existing scope explicit."""
import copy
import unittest
from network_labs.appliances.examples import dual_stack_lab, ipv6_routed_lab, slaac_lab, dhcpv6_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.service_adapters import adapters


class DualStackTests(unittest.TestCase):
    def test_example_has_both_complete_forward_and_return_paths(self):
        spec = dual_stack_lab('/rootfs'); self.assertEqual(validate(copy.deepcopy(spec)), spec)
        self.assertEqual([n['forwarding'] for n in spec['nodes']], [False, True, True, False])
        self.assertEqual([n['ipv6_forwarding'] for n in spec['nodes']], [False, True, True, False])
        self.assertEqual(spec['nodes'][0]['gateway'], '192.0.2.1')
        self.assertEqual(spec['nodes'][3]['gateway'], '198.51.100.1')
        self.assertEqual(spec['nodes'][1]['routes'][0]['gateway'], '198.18.0.2')
        self.assertEqual(spec['nodes'][1]['ipv6_routes'][0]['gateway'], '2001:db8:100::2')
        self.assertTrue(all(n['ipv6'] and all(n['interfaces'].values()) for n in spec['nodes']))

    def test_family_forwarding_policies_are_independent(self):
        for ipv4 in (False, True):
            for ipv6 in (False, True):
                spec = dual_stack_lab('/rootfs'); spec['nodes'][1].update(forwarding=ipv4, ipv6_forwarding=ipv6)
                self.assertEqual(validate(spec)['nodes'][1]['forwarding'], ipv4)
                self.assertEqual(spec['nodes'][1]['ipv6_forwarding'], ipv6)
        spec = ipv6_routed_lab('/rootfs'); self.assertTrue(all(not n['forwarding'] for n in spec['nodes']))
        self.assertEqual(validate(spec), spec)

    def test_unnumbered_ipv4_forwarding_and_unvalidated_compositions_rejected(self):
        spec = ipv6_routed_lab('/rootfs'); spec['nodes'][1]['forwarding'] = True
        with self.assertRaises(ValueError): validate(spec)
        for factory in (slaac_lab, dhcpv6_lab):
            spec = factory('/rootfs')
            spec['nodes'][0].update(interfaces={'eth0': '192.0.2.10/24'}, gateway='192.0.2.1')
            with self.assertRaises(ValueError): validate(spec)
        spec = dual_stack_lab('/rootfs'); spec['nodes'][1]['startup'] = [['/bin/echo', 'untracked']]
        with self.assertRaises(ValueError): validate(spec)
        for field in ('gateway', 'routes'):
            spec = dual_stack_lab('/rootfs')
            if field == 'gateway': spec['nodes'][0]['gateway'] = '203.0.113.1'
            else: spec['nodes'][1]['routes'][0]['gateway'] = '203.0.113.1'
            with self.assertRaises(ValueError): validate(spec)

    def test_dual_stack_live_mutations_still_require_recreation(self):
        old = dual_stack_lab('/rootfs')['nodes'][1]
        for field in ('forwarding', 'ipv6_forwarding'):
            changed = copy.deepcopy(old); changed[field] = False
            with self.assertRaises(ValueError): adapters(changed, old)
