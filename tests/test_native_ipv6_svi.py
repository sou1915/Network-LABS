"""IPv6 SVI boundaries and static-route/save auditing on virtual VLAN links."""
import copy
import json
import subprocess
import unittest
from unittest.mock import Mock

from network_labs.appliances.examples import ipv6_svi_lab
from network_labs.appliances.ipv6 import configure, drift
from network_labs.appliances.service_adapters import adapters
from network_labs.appliances.spec import validate


class IPv6SVITests(unittest.TestCase):
    def test_example_routes_between_vlans_without_ipv4_or_physical_switch_addresses(self):
        spec = ipv6_svi_lab('/rootfs')
        self.assertEqual(validate(spec), spec)
        core = spec['nodes'][4]
        self.assertEqual(set(core['ipv6']), {'vlan10', 'vlan20'})
        self.assertTrue(core['ipv6_forwarding']); self.assertFalse(core['forwarding'])
        self.assertTrue(all(not p['address'] for p in core['svis'].values()))
        self.assertTrue(all(not a for n in spec['nodes'] for a in n['interfaces'].values()))
        manager = Mock(); configure(manager, 4, core)
        manager.ns.assert_any_call(4, 'ip', '-6', 'addr', 'add', '2001:db8:10::1/64', 'dev', 'vlan10')
        manager.ns.assert_any_call(4, 'sysctl', '-w', 'net/ipv6/conf/vlan20/accept_ra=0')
        manager.ns.assert_any_call(4, 'sysctl', '-w', 'net/ipv6/conf/all/forwarding=1')

    def test_invalid_links_addresses_and_unvalidated_service_compositions_rejected(self):
        for update in ({'ipv6': {'eth0': '2001:db8:10::1/64'}},
                       {'ipv6': {'br0': '2001:db8:10::1/64'}},
                       {'ipv6': {'vlan99': '2001:db8:10::1/64'}},
                       {'ipv6': {'vlan10': '2001:db8:10::1/64', 'vlan20': '2001:db8:10::2/64'}},
                       {'ipv6': {'vlan10': 'fe80::1/64'}}, {'switch_backend': 'ovs'},
                       {'svis': {'vlan010': {'vlan': 10}}}, {'svis': []},
                       {'svis': {'vlan10': {'vlan': 20}}}, {'forwarding': True},
                       {'svis': {'vlan10': {'vlan': 10, 'address': '192.0.2.1/24'}, 'vlan20': {'vlan': 20}}},
                       {'router_advertisements': ['vlan10']},
                       {'ospfv3': {'router_id': '1.1.1.1', 'interfaces': {'eth0': {}}}}):
            spec = ipv6_svi_lab('/rootfs'); spec['nodes'][4].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)

    def test_routes_require_a_numbered_svi_and_live_changes_require_recreation(self):
        spec = ipv6_svi_lab('/rootfs'); core = spec['nodes'][4]
        core['ipv6_routes'] = [{'destination': '2001:db8:99::/64', 'gateway': '2001:db8:20::fe', 'interface': 'vlan20'}]
        self.assertEqual(validate(spec)['nodes'][4]['ipv6_routes'], core['ipv6_routes'])
        for update in ({'interface': 'eth1'}, {'gateway': '2001:db8:10::fe'}, {'gateway': '2001:db8:20::1'}):
            candidate = copy.deepcopy(spec); candidate['nodes'][4]['ipv6_routes'][0].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(candidate)
        old = ipv6_svi_lab('/rootfs')['nodes'][4]
        changed = copy.deepcopy(old); changed['ipv6_forwarding'] = False
        with self.assertRaisesRegex(ValueError, 'recreation'): adapters(changed, old)

    def test_ipv6_audit_rejects_svi_address_forwarding_and_route_drift(self):
        core = ipv6_svi_lab('/rootfs')['nodes'][4]; manager = Mock()
        rows = [{'ifname': p, 'addr_info': [{'family': 'inet6', 'scope': 'global', 'local': v.split('/')[0], 'prefixlen': 64}]}
                for p, v in core['ipv6'].items()]
        routes = [{'dst': '2001:db8:10::/64', 'dev': 'vlan10', 'protocol': 'kernel'},
                  {'dst': '2001:db8:20::/64', 'dev': 'vlan20', 'protocol': 'kernel'}]
        settings = {}
        def ns(index, *args, **kwargs):
            if args[:5] == ('ip', '-j', '-6', 'route', 'show'): value = json.dumps(routes)
            elif args[:2] == ('ip', '-j'): value = json.dumps(rows)
            else: value = settings.get(args[-1], '1' if args[-1].endswith(('forwarding', 'accept_dad')) else '0')
            return subprocess.CompletedProcess([], 0, value, '')
        manager.ns.side_effect = ns
        self.assertEqual(drift(manager, 4, core), [])
        settings['net/ipv6/conf/all/forwarding'] = '0'
        self.assertTrue(any('forwarding' in e for e in drift(manager, 4, core)))
        settings.clear(); rows[0]['ifname'] = 'eth0'
        self.assertTrue(any('addresses differ' in e for e in drift(manager, 4, core)))
        rows[0]['ifname'] = 'vlan10'; routes[0]['dev'] = 'eth0'
        self.assertTrue(any('routes differ' in e for e in drift(manager, 4, core)))
