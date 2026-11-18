"""The OpenConfig leaf catalogue: generated from the pinned OpenConfig models, read by path."""
import unittest

from network_labs.appliances import openconfig

NEIGHBOR = '/network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor'


class OpenConfigCatalogueTest(unittest.TestCase):
    def test_types_ranges_choices_and_defaults_come_from_the_models(self):
        self.assertEqual(openconfig.catalogue()['commit'], 'fa27bd6ac13d14a167719bbf4eac48b1f298e43f')
        self.assertEqual(openconfig.base(NEIGHBOR + '/timers/config/hold-time'), 'uint16')
        self.assertEqual(openconfig.default(NEIGHBOR + '/timers/config/hold-time'), '90')
        self.assertEqual(openconfig.integer_range(NEIGHBOR + '/config/peer-as'), (0, 4294967295))
        path = NEIGHBOR + '/afi-safis/afi-safi/ipv4-unicast/prefix-limit/config/warning-threshold-pct'
        self.assertEqual(openconfig.integer_range(path), (0, 100))
        self.assertEqual(openconfig.choices(NEIGHBOR + '/config/remove-private-as'),
                         ['PRIVATE_AS_REMOVE_ALL', 'PRIVATE_AS_REPLACE_ALL'])
        self.assertIn('ACCEPT_ROUTE', openconfig.choices(NEIGHBOR + '/afi-safis/afi-safi/apply-policy/config/default-import-policy'))
        self.assertTrue(openconfig.short_help(NEIGHBOR + '/config/peer-as'))
        with self.assertRaises(KeyError):
            openconfig.leaf('/not/a/leaf')


if __name__ == '__main__':
    unittest.main()
