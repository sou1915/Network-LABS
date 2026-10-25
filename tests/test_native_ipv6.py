"""Static IPv6 L2 declarations, namespace-only configuration and conservative audit."""
import copy
import json
import subprocess
import unittest
from unittest.mock import Mock
from network_labs.appliances.examples import ipv6_vlan_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.ipv6 import configure, drift
from network_labs.appliances.service_adapters import adapters


class IPv6Tests(unittest.TestCase):
    def test_six_node_vlan_profile_is_canonical_and_backward_compatible(self):
        spec = ipv6_vlan_lab('/rootfs')
        self.assertEqual(len(spec['nodes']), 6)
        self.assertEqual(spec['nodes'][0]['ipv6'], {'eth0': '2001:db8:10::10/64'})
        self.assertEqual(validate(spec), spec)
        self.assertEqual(spec['nodes'][4]['switchports']['eth2']['allowed'], [10, 20])

    def test_invalid_addresses_and_unvalidated_service_compositions_rejected(self):
        for address in ('192.0.2.1/24', 'fe80::1/64', '::1/64', 'ff02::1/64', '2001:db8::1/48', '2001:db8::/64', '2001:db8::1', True):
            spec = ipv6_vlan_lab('/rootfs'); spec['nodes'][0]['ipv6']['eth0'] = address
            with self.subTest(address=address), self.assertRaises(ValueError): validate(spec)
        spec = ipv6_vlan_lab('/rootfs'); spec['nodes'][1]['ipv6'] = copy.deepcopy(spec['nodes'][0]['ipv6'])
        with self.assertRaises(ValueError): validate(spec)
        spec = ipv6_vlan_lab('/rootfs'); spec['nodes'][0]['startup'] = [['/bin/echo', 'untracked']]
        with self.assertRaises(ValueError): validate(spec)
        spec = ipv6_vlan_lab('/rootfs'); spec['nodes'][4]['ipv6'] = {'eth0': '2001:db8::1/64'}
        with self.assertRaises(ValueError): validate(spec)

    def test_configuration_targets_owned_namespace_with_dad_and_no_ra(self):
        manager = Mock(); node = ipv6_vlan_lab('/rootfs')['nodes'][0]
        configure(manager, 0, node)
        manager.ns.assert_any_call(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/accept_dad=1')
        manager.ns.assert_any_call(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/accept_ra=0')
        manager.ns.assert_any_call(0, 'ip', '-6', 'addr', 'add', '2001:db8:10::10/64', 'dev', 'eth0')

    def test_address_and_dad_drift_are_not_persisted_as_healthy(self):
        manager = Mock(); node = ipv6_vlan_lab('/rootfs')['nodes'][0]
        rows = [{'ifname': 'eth0', 'addr_info': [{'family': 'inet6', 'scope': 'global', 'local': '2001:db8:10::10', 'prefixlen': 64}]}]
        def ns(index, *args, **kwargs):
            if args[:2] == ('ip', '-j'):
                value = json.dumps(rows)
            else:
                value = '1' if args[-1].endswith('accept_dad') else '0'
            return subprocess.CompletedProcess([], 0, value, '')
        manager.ns.side_effect = ns
        self.assertEqual(drift(manager, 0, node), [])
        rows[0]['addr_info'][0]['tentative'] = True
        self.assertTrue(any('DAD' in e for e in drift(manager, 0, node)))
        rows[0]['addr_info'] = []
        self.assertTrue(any('addresses differ' in e for e in drift(manager, 0, node)))

    def test_live_host_mutations_refused_before_any_runtime_apply(self):
        old = ipv6_vlan_lab('/rootfs')['nodes'][0]; new = copy.deepcopy(old)
        new['shutdown'] = ['eth0']
        with self.assertRaises(ValueError): adapters(new, old)
