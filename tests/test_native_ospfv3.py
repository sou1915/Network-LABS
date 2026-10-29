"""OSPFv3 declaration boundaries, observations and IPv6 audit scoping."""
import copy
import json
import subprocess
import unittest
from unittest.mock import Mock

from network_labs.appliances.examples import ospfv3_lab, ospfv3_svi_lab, ipv6_routed_lab
from network_labs.appliances.ipv6 import drift
from network_labs.appliances.ospfv3 import config, observe
from network_labs.appliances.service_adapters import adapters
from network_labs.appliances.spec import validate
from network_labs.appliances.show import show


class OSPFv3Tests(unittest.TestCase):
    def test_svi_transit_example_roundtrips_and_advertises_only_declared_routed_ports(self):
        spec = ospfv3_svi_lab('/rootfs')
        self.assertEqual(validate(spec), spec)
        core = spec['nodes'][1]
        self.assertEqual(core['name'], 'SW1'); self.assertEqual(core['role'], 'switch')
        self.assertEqual(core['ipv6_routes'], [])
        self.assertTrue(core['ipv6_forwarding']); self.assertFalse(core['forwarding'])
        text = config(core)
        self.assertIn('interface "vlan10" { type ptp; cost 10; stub yes;', text)
        self.assertIn('interface "vlan100" { type ptp; cost 10; stub no;', text)
        self.assertNotIn('interface "eth', text)
        self.assertTrue(all(not p['address'] for p in core['svis'].values()))
        changed = copy.deepcopy(core); changed['ospfv3']['interfaces']['vlan100']['cost'] = 30
        with self.assertRaisesRegex(ValueError, 'recreation'): adapters(changed, core)

    def test_svi_ospfv3_rejects_unnumbered_physical_shutdown_and_wrong_role_interfaces(self):
        for update in ({'interfaces': {'eth1': {}}}, {'interfaces': {'br0': {}}},
                       {'interfaces': {'vlan99': {}}}, {'interfaces': {'vlan10': {'passive': True}}}):
            spec = ospfv3_svi_lab('/rootfs'); spec['nodes'][1]['ospfv3'].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)
        for update in ({'shutdown': ['vlan100']}, {'ipv6_forwarding': False}, {'switch_backend': 'ovs'},
                       {'svis': {}}, {'role': 'host'}, {'forwarding': True}):
            spec = ospfv3_svi_lab('/rootfs'); spec['nodes'][1].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)

    def test_router_prefixes_have_no_static_fallback_and_example_roundtrips(self):
        spec = ospfv3_lab('/rootfs')
        self.assertEqual(validate(spec), spec)
        for node in spec['nodes'][1:3]:
            self.assertEqual(node['ipv6_routes'], [])
            self.assertTrue(node['ipv6_forwarding'])
            self.assertFalse(node['forwarding'])
            text = config(node)
            self.assertIn('protocol ospf v3 ospf6', text)
            self.assertIn('protocol kernel kernel6', text)
            self.assertIn('ipv6 { import where source = RTS_OSPF; export none; }', text)
            self.assertNotIn('ipv4 {', text)
            self.assertNotIn('persist;', text)
            self.assertNotIn('interface "*"', text)
        self.assertIn('interface "eth0" { type ptp; cost 10; stub yes;', config(spec['nodes'][1]))

    def test_invalid_policies_and_unsupported_compositions_are_rejected(self):
        for update in ({'router_id': True}, {'router_id': '::1'}, {'router_id': '224.0.0.1'},
                       {'router_id': '0.0.0.0'}, {'hello': True}, {'hello': 5, 'dead': 4},
                       {'interfaces': {}}, {'interfaces': {'eth9': {}}},
                       {'interfaces': {'eth0': {'cost': 0}}},
                       {'interfaces': {'eth0': {'passive': 'yes'}}},
                       {'interfaces': {'eth0': {'passive': True}}},
                       {'interfaces': {'eth0': {'network_type': 'broadcast'}}}, {'area': 1}):
            spec = ospfv3_lab('/rootfs'); spec['nodes'][1]['ospfv3'].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)
        for update in ({'ipv6_forwarding': False}, {'shutdown': ['eth1']},
                       {'interfaces': {'eth0': '192.0.2.1/24', 'eth1': ''}},
                       {'ipv6_routes': ipv6_routed_lab('/rootfs')['nodes'][1]['ipv6_routes']},
                       {'router_advertisements': ['eth0']}):
            spec = ospfv3_lab('/rootfs'); spec['nodes'][1].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)
        spec = ospfv3_lab('/rootfs'); spec['nodes'][2]['ospfv3']['router_id'] = '1.1.1.1'
        with self.assertRaisesRegex(ValueError, 'unique'): validate(spec)
        spec = ospfv3_lab('/rootfs'); spec['nodes'][0]['ospfv3'] = spec['nodes'][1]['ospfv3']
        with self.assertRaises(ValueError): validate(spec)

    def test_control_failure_remains_unknown_and_live_edits_require_recreation(self):
        node = ospfv3_lab('/rootfs')['nodes'][1]; manager = Mock()
        manager.crun.side_effect = [subprocess.CompletedProcess([], 0, config(node), '')] + [
            subprocess.CompletedProcess([], 1, '', 'missing socket')] * 4
        result = observe(manager, node)
        self.assertTrue(result['configuration_verified'])
        self.assertIsNone(result['neighbors']); self.assertIsNone(result['routes'])
        self.assertNotIn('converged', result)
        changed = copy.deepcopy(node); changed['ospfv3']['interfaces']['eth1']['cost'] = 50
        with self.assertRaisesRegex(ValueError, 'recreation'): adapters(changed, node)

    def test_show_uses_the_matching_address_family_process(self):
        spec = ospfv3_lab('/rootfs'); manager = Mock(); manager.name = spec['name']
        manager.read.return_value = {'spec': spec, 'phase': 'running'}
        manager.crun.side_effect = [subprocess.CompletedProcess([], 0, '{"status":"running"}', ''),
                                   subprocess.CompletedProcess([], 0, '1002-Neighbor state Full\n', '')]
        result = show(manager, 'R1', 'show ipv6 ospf neighbor')
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(result['daemon_command'], 'show ospf neighbors ospf6')
        with self.assertRaises(ValueError): show(manager, 'R1', 'show ip ospf neighbor')

    def test_audit_exempts_only_bird_routes_on_declared_v3_routers(self):
        node = ospfv3_lab('/rootfs')['nodes'][1]; manager = Mock()
        rows = [{'ifname': port, 'addr_info': [{'family': 'inet6', 'scope': 'global',
                 'local': value.split('/')[0], 'prefixlen': 64}]} for port, value in node['ipv6'].items()]
        routes = [{'dst': value.split('::')[0] + '::/64', 'dev': port, 'protocol': 'kernel'}
                  for port, value in node['ipv6'].items()]
        learned = {'dst': '2001:db8:20::/64', 'gateway': 'fe80::2', 'dev': 'eth1', 'protocol': 'bird'}
        routes.append(learned)
        def ns(index, *args, **kwargs):
            if args[:5] == ('ip', '-j', '-6', 'route', 'show'): value = json.dumps(routes)
            elif args[:2] == ('ip', '-j'): value = json.dumps(rows)
            else: value = '1' if args[-1].endswith(('forwarding', 'accept_dad')) else '0'
            return subprocess.CompletedProcess([], 0, value, '')
        manager.ns.side_effect = ns
        self.assertEqual(drift(manager, 1, node), [])
        learned['protocol'] = 'static'
        self.assertTrue(any('routes differ' in error for error in drift(manager, 1, node)))
        learned['protocol'] = 'bird'; node['ospfv3'] = None
        self.assertTrue(any('unmanaged' in error for error in drift(manager, 1, node)))
