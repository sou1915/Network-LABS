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
            if args[:5] == ('ip', '-j', '-6', 'route', 'show'):
                value = json.dumps([{'dst': '2001:db8:10::/64', 'dev': 'eth0', 'protocol': 'kernel'}])
            elif args[:2] == ('ip', '-j'):
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

    def test_routed_example_has_explicit_return_paths_and_separate_forwarding(self):
        from network_labs.appliances.examples import ipv6_routed_lab
        from unittest.mock import patch
        spec = ipv6_routed_lab('/rootfs'); self.assertEqual(validate(spec), spec)
        self.assertEqual([n['ipv6_forwarding'] for n in spec['nodes']], [False, True, True, False])
        self.assertTrue(all(not n['forwarding'] for n in spec['nodes']))
        manager = Mock(); manager.state = {'spec': spec}; router = spec['nodes'][1]
        configure(manager, 1, router)
        self.assertFalse(any(call.args[1:4] == ('ip', '-6', 'route') for call in manager.ns.call_args_list))
        from network_labs.appliances.ipv6 import install_routes
        with patch('network_labs.appliances.ipv6.wait_addresses') as ready:
            install_routes(manager)
        ready.assert_any_call(manager, 1, router)
        self.assertEqual(ready.call_count, 4)
        manager.ns.assert_any_call(1, 'ip', '-6', 'route', 'add', '2001:db8:20::/64', 'via', '2001:db8:100::2', 'dev', 'eth1', 'proto', 'static')
        manager.ns.assert_any_call(1, 'sysctl', '-w', 'net/ipv6/conf/eth0/forwarding=1')

    def test_route_validation_rejects_offlink_self_ambiguous_and_unsupported_values(self):
        from network_labs.appliances.examples import ipv6_routed_lab
        for changes in ({'gateway': '2001:db8:99::1'}, {'gateway': '2001:db8:100::1'},
                        {'gateway': 'fe80::1'}, {'destination': '2001:db8:20::1/64'}, {'interface': 'eth99'},
                        {'destination': 'ff00::/8'}, {'destination': '::/128'}, {'destination': 'fe80::/64'}, {'destination': '2001:db8:100::/64'}):
            spec = ipv6_routed_lab('/rootfs'); spec['nodes'][1]['ipv6_routes'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): validate(spec)
        spec = ipv6_routed_lab('/rootfs'); spec['nodes'][0]['ipv6_forwarding'] = True
        with self.assertRaises(ValueError): validate(spec)
        spec = ipv6_routed_lab('/rootfs'); spec['nodes'][1]['ipv6_routes'] *= 2
        with self.assertRaises(ValueError): validate(spec)

    def test_route_and_forwarding_drift_are_detected(self):
        from network_labs.appliances.examples import ipv6_routed_lab
        node = ipv6_routed_lab('/rootfs')['nodes'][0]
        manager = Mock(); rows = [{'ifname': 'eth0', 'addr_info': [{'family': 'inet6', 'scope': 'global', 'local': '2001:db8:10::10', 'prefixlen': 64}]}]
        routes = [{'dst': '2001:db8:10::/64', 'dev': 'eth0', 'protocol': 'kernel'},
                  {'dst': 'default', 'gateway': '2001:db8:10::1', 'dev': 'eth0', 'protocol': 'static'}]
        def ns(index, *args, **kwargs):
            if args[:5] == ('ip', '-j', '-6', 'route', 'show'): value = json.dumps(routes)
            elif args[0] == 'ip': value = json.dumps(rows)
            else: value = '1' if args[-1].endswith('accept_dad') else '0'
            return subprocess.CompletedProcess([], 0, value, '')
        manager.ns.side_effect = ns
        self.assertEqual(drift(manager, 0, node), [])
        routes.pop()
        self.assertTrue(any('routes differ' in e for e in drift(manager, 0, node)))
        original = manager.ns.side_effect
        manager.ns.side_effect = lambda i, *a, **k: subprocess.CompletedProcess([], 0, '1', '') if a[-1] == 'net/ipv6/conf/all/forwarding' else original(i, *a, **k)
        self.assertTrue(any('global forwarding differs' in e for e in drift(manager, 0, node)))

    def test_dad_failure_blocks_static_route_installation(self):
        from network_labs.appliances.ipv6 import wait_addresses
        from network_labs.appliances.runtime import RuntimeFailure
        manager = Mock(); node = ipv6_vlan_lab('/rootfs')['nodes'][0]
        manager.ns.return_value = subprocess.CompletedProcess([], 0, json.dumps([{'ifname': 'eth0', 'addr_info': [{'local': '2001:db8:10::10', 'dadfailed': True}]}]), '')
        with self.assertRaises(RuntimeFailure): wait_addresses(manager, 0, node)
