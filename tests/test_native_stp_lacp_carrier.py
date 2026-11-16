"""Reusable common-tree topology with distinct kernel carrier thresholds."""
import unittest
from network_labs.appliances.examples import stp_lacp_lab
from network_labs.appliances.lacp import validate_links
from network_labs.appliances.spec import validate


class STPLACPCarrierTopologyTests(unittest.TestCase):
    def test_two_vlans_one_logical_bundle_and_a_more_expensive_spare(self):
        for threshold in (1, 2):
            spec = stp_lacp_lab('/rootfs', threshold); self.assertEqual(validate(spec), spec)
            self.assertEqual(validate_links(spec).count(('SW1', 'SW2')), 2)
            for node in spec['nodes'][4:]:
                self.assertEqual(node['shutdown'], [])
                self.assertEqual(node['port_channels']['bond1']['min_links'], threshold)
                self.assertEqual(node['switchports']['bond1']['allowed'], [10, 20])
                self.assertEqual(node['switchports']['eth4']['allowed'], [10, 20])
                self.assertGreater(node['spanning_tree']['ports']['eth4']['cost'], node['spanning_tree']['ports']['bond1']['cost'])
                self.assertFalse({'eth2', 'eth3'} & set(node['spanning_tree']['ports']))
            self.assertLess(spec['nodes'][4]['spanning_tree']['priority'], spec['nodes'][5]['spanning_tree']['priority'])
        for threshold in (0, 3, True, '2'):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError): stp_lacp_lab('/rootfs', threshold)
