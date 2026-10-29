"""Static IPv6 dot1Q validation and fail-closed encapsulation observations."""
import copy
import json
import subprocess
import unittest
from unittest.mock import Mock

from network_labs.appliances.examples import ipv6_subinterfaces_lab
from network_labs.appliances.ipv6 import configure
from network_labs.appliances.ipv6_subinterfaces import observe, drift
from network_labs.appliances.service_adapters import adapters
from network_labs.appliances.spec import validate


class IPv6SubinterfaceTests(unittest.TestCase):
    def test_numbered_dot1q_and_static_next_hop_use_existing_vlan_devices(self):
        spec = ipv6_subinterfaces_lab('/rootfs'); self.assertEqual(validate(spec), spec)
        router = spec['nodes'][5]
        self.assertEqual(set(router['ipv6']), {'eth0.10', 'eth0.20', 'eth0.100'})
        self.assertEqual(router['interfaces'], {'eth0': ''})
        self.assertFalse(router['forwarding']); self.assertTrue(router['ipv6_forwarding'])
        self.assertTrue(all(not sub['address'] for sub in router['subinterfaces'].values()))
        manager = Mock(); configure(manager, 5, router)
        manager.ns.assert_any_call(5, 'ip', '-6', 'addr', 'add', '2001:db8:20::1/64', 'dev', 'eth0.20')
        manager.ns.assert_any_call(5, 'sysctl', '-w', 'net/ipv6/conf/eth0.100/accept_ra=0')
        self.assertEqual(router['ipv6_routes'][0]['interface'], 'eth0.100')

    def test_unconfigured_parent_addressing_and_unsupported_compositions_are_rejected(self):
        original = ipv6_subinterfaces_lab('/rootfs')
        changes = [lambda r: r['subinterfaces']['eth0.10'].update(vlan=None),
                   lambda r: r['subinterfaces']['eth0.10'].update(parent='eth1'),
                   lambda r: r['subinterfaces']['eth0.20'].update(vlan=10),
                   lambda r: r['subinterfaces']['eth0.20'].update(address='192.0.2.1/24'),
                   lambda r: r['ipv6'].update(eth0='2001:db8:99::1/64'),
                   lambda r: r['ipv6'].pop('eth0.20'),
                   lambda r: r.update(forwarding=True),
                   lambda r: r.update(role='firewall'),
                   lambda r: r.update(subinterfaces=[]),
                   lambda r: r.update(router_advertisements=['eth0.10']),
                   lambda r: r.update(ospfv3={'router_id': '1.1.1.1', 'interfaces': {'eth0.100': {}}}),
                   lambda r: r['ipv6_routes'][0].update(interface='eth0'),
                   lambda r: r['ipv6_routes'][0].update(gateway='2001:db8:20::2')]
        for i, change in enumerate(changes):
            spec = copy.deepcopy(original); change(spec['nodes'][5])
            with self.subTest(case=i), self.assertRaises(ValueError): validate(spec)
        changed = copy.deepcopy(original['nodes'][5]); changed['shutdown'] = ['eth0.20']
        with self.assertRaisesRegex(ValueError, 'recreation'): adapters(changed, original['nodes'][5])

    def test_audit_requires_real_dot1q_parent_and_vlan_even_with_correct_name(self):
        router = ipv6_subinterfaces_lab('/rootfs')['nodes'][5]
        links = [{'ifname': 'eth0', 'ifindex': 7}] + [
            {'ifname': name, 'ifindex': 10 + i, 'link_index': 7,
             'linkinfo': {'info_kind': 'vlan', 'info_data': {'protocol': '802.1Q', 'id': policy['vlan']}}}
            for i, (name, policy) in enumerate(router['subinterfaces'].items())]
        manager = Mock()
        def audit(rows):
            manager.ns.return_value = subprocess.CompletedProcess([], 0, json.dumps(rows), '')
            return drift(manager, 5, router)
        self.assertEqual(audit(links), [])
        for update in ({'id': 99}, {'protocol': '802.1ad'}):
            rows = copy.deepcopy(links); rows[1]['linkinfo']['info_data'].update(update)
            self.assertTrue(audit(rows))
        rows = copy.deepcopy(links); rows[1]['link_index'] = 100
        self.assertFalse(observe(router, rows)['eth0.10']['encapsulation_verified'])
        self.assertTrue(audit(rows)); self.assertTrue(audit(links[:1]))
