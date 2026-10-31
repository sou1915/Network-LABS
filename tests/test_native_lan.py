"""Contracts for the headless native LAN, independent of simulator CLI/model."""
import copy
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from network_labs.appliances.dhcp import CLIENT_SCRIPT, server_config
from network_labs.appliances.examples import campus
from network_labs.appliances.ios import compile_config
from network_labs.appliances.lan import configure, memberships
from network_labs.appliances.runtime import Manager, RuntimeFailure
from network_labs.appliances.spec import validate


class LANContracts(unittest.TestCase):
    def test_campus_is_eight_real_nodes_with_compatible_allocation(self):
        spec = campus('/rootfs')
        self.assertEqual(len(spec['nodes']), 8)
        self.assertTrue(all(n['runtime'] == 'oci' for n in spec['nodes']))
        self.assertEqual(len(spec['links']), 7)
        self.assertEqual(sum(n['memory_mib'] for n in spec['nodes']), 512)
        self.assertEqual(spec['nodes'][0]['dhcp_clients'], ['eth0'])

    def test_vlans_pending_encapsulation_dhcp_and_roles_fail_closed(self):
        edits = [lambda s: s['nodes'][4]['switchports']['eth0'].update(vlan=30),
                 lambda s: s['nodes'][4]['switchports']['eth2'].update(allowed=[10, 10]),
                 lambda s: s['nodes'][6]['subinterfaces']['eth0.20'].update(vlan=10),
                 lambda s: s['nodes'][6]['subinterfaces']['eth0.20'].update(vlan=None),
                 lambda s: s['nodes'][0]['interfaces'].update(eth0='10.10.10.5/24'),
                 lambda s: s['nodes'][0].update(forwarding=True),
                 lambda s: s['nodes'][7]['dhcp_server'].update(start='10.10.10.1'),
                 lambda s: s['nodes'][7]['dhcp_server'].update(end='10.20.20.10'),
                 lambda s: s['nodes'][7]['dhcp_server'].update(router='203.0.113.1'),
                 lambda s: s['nodes'][4].update(shutdown=['eth99'])]
        for edit in edits:
            with self.subTest(edit=edit):
                spec = campus('/rootfs'); edit(spec)
                with self.assertRaises(ValueError):
                    validate(spec)

    def test_untagged_access_and_native_trunk_have_distinct_memberships(self):
        node = campus('/rootfs')['nodes'][4]
        self.assertEqual(memberships(node, node['switchports']['eth0']), [(10, True, True)])
        self.assertEqual(memberships(node, node['switchports']['eth2']), [(10, False, False), (20, False, False)])
        port = {'mode': 'trunk', 'native_vlan': 10, 'allowed': [10, 20]}
        self.assertEqual(memberships(node, port), [(10, True, True), (20, False, False)])
        port['allowed'] = []
        self.assertEqual(memberships(node, port), [])

    def test_ios_block_changes_native_configuration_not_model(self):
        spec = campus('/rootfs'); before = copy.deepcopy(spec)
        result = compile_config(spec, 'SW1', 'enable\nconfigure terminal\ninterface FastEthernet0/3\nswitchport trunk allowed vlan 10\nshutdown\nend')
        self.assertEqual(spec, before)
        switch = result['nodes'][4]
        self.assertEqual(switch['switchports']['eth2']['allowed'], [10])
        self.assertIn('eth2', switch['shutdown'])
        result = compile_config(result, 'SW1', 'conf t\ninterface fa0/3\nno shutdown\nend')
        self.assertNotIn('eth2', result['nodes'][4]['shutdown'])

    def test_editing_one_trunk_cannot_modify_another_shared_template(self):
        spec = campus('/rootfs')
        result = compile_config(spec, 'SW1', 'conf t\ninterface fa0/4\nswitchport trunk allowed vlan 10\nend')
        self.assertEqual(result['nodes'][4]['switchports']['eth3']['allowed'], [10])
        self.assertEqual(result['nodes'][4]['switchports']['eth2']['allowed'], [10, 20])
        self.assertEqual(result['nodes'][5]['switchports']['eth2']['allowed'], [10, 20])
        self.assertEqual(spec['nodes'][4]['switchports']['eth3']['allowed'], [10, 20])

    def test_ios_subinterface_requires_encapsulation_before_address(self):
        spec = campus('/rootfs')
        pending = compile_config(spec, 'R1', 'conf t\ninterface fa0/0.30\nend')
        self.assertIsNone(pending['nodes'][6]['subinterfaces']['eth0.30']['vlan'])
        configured = compile_config(pending, 'R1', 'conf t\ninterface fa0/0.30\nencapsulation dot1Q 300\nip address 10.30.30.1 255.255.255.0\nend')
        sub = configured['nodes'][6]['subinterfaces']['eth0.30']
        self.assertEqual(sub['vlan'], 300)
        self.assertEqual(sub['address'], '10.30.30.1/24')
        self.assertFalse(compile_config(spec, 'R1', 'conf t\nno ip routing\nend')['nodes'][6]['forwarding'])

    def test_bad_import_never_partially_applies_shutdown(self):
        spec = campus('/rootfs'); original = copy.deepcopy(spec)
        for text in ('conf t\ninterface fa0/1\nshutdown\npretend unsupported',
                     'conf t\ninterface fa0/1 ignored\nshutdown',
                     'interface fa0/1\nshutdown',
                     'conf t\nspanning-tree mode rapid-pvst'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'Line'):
                compile_config(spec, 'SW1', text)
        self.assertEqual(spec, original)

    def test_dhcp_config_contains_real_pool_netmask_router_and_lease_files(self):
        spec = campus('/rootfs')
        config = server_config(spec['nodes'][7])
        for expected in ('interface eth0', 'start 10.10.10.100', 'end 10.10.10.150',
                         'option subnet 255.255.255.0', 'option router 10.10.10.1',
                         'lease_file /run/udhcpd.leases'):
            self.assertIn(expected, config)
        self.assertNotIn('option dns', config)
        self.assertIn('bound|renew)', CLIENT_SCRIPT)
        self.assertNotIn('eval', CLIENT_SCRIPT)

    def test_configuration_failure_rolls_back_and_keeps_running_spec(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Manager('campus-lan'); manager.directory = Path(folder)
            spec = campus('/rootfs')
            manager.state = {'spec': spec, 'phase': 'running', 'revision': 7}
            with patch('network_labs.appliances.lan.configure', side_effect=[RuntimeFailure('injected'), None]) as apply:
                with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                    manager.configure_ios('R1', 'conf t\nno ip routing\nend')
            self.assertEqual(apply.call_count, 2)
            self.assertTrue(manager.state['spec']['nodes'][6]['forwarding'])
            self.assertEqual(manager.state['revision'], 7)
            self.assertEqual(manager.state['phase'], 'running')
            self.assertNotIn('pending_spec', manager.state)

    def test_trunk_edit_does_not_flap_unrelated_ports(self):
        previous = campus('/rootfs')['nodes'][4]
        desired = copy.deepcopy(previous); desired['switchports']['eth3']['allowed'] = [10]
        class FakeManager:
            def __init__(self):
                self.calls = []
            def ns(self, index, *args, **kwargs):
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 0, '[]', '')
        manager = FakeManager(); configure(manager, 4, desired, previous)
        down = [args[4] for args in manager.calls if args[:4] == ('ip', 'link', 'set', 'dev') and args[-1] == 'down']
        self.assertEqual(down, ['eth3'])
        self.assertFalse(any(args[:3] == ('ip', '-4', 'addr') for args in manager.calls))

    def test_vlan_table_edits_refresh_effective_trunks_and_rollback(self):
        from network_labs.appliances.examples import lacp_lab
        for bundled in (False, True):
            for allowed in ('all', [10, 20, 30], [10, 20]):
                previous = (lacp_lab('/rootfs') if bundled else campus('/rootfs'))['nodes'][4]
                port = 'bond1' if bundled else 'eth3'
                previous['switchports'][port].update(allowed=allowed, native_vlan=30)
                desired = copy.deepcopy(previous); desired['vlans'].append(30)
                class FakeManager:
                    def __init__(self): self.calls = []
                    def ns(self, index, *args, **kwargs):
                        self.calls.append(args)
                        return subprocess.CompletedProcess(args, 0, '[]', '')
                manager = FakeManager()
                with patch('network_labs.appliances.lacp.configure', return_value=set()):
                    configure(manager, 4, desired, previous)
                edits = [args for args in manager.calls if args[:3] == ('bridge', 'vlan', 'add')]
                expected = [] if allowed == [10, 20] else [
                    ('bridge', 'vlan', 'add', 'dev', port, 'vid', '30', 'pvid', 'untagged')]
                self.assertEqual([args for args in edits if args[6] == '30'], expected,
                                 (bundled, allowed, edits))
                self.assertTrue(all(args[4] == port for args in edits), edits)
                # Undoing a partially applied VLAN declaration must also visit
                # the trunk, even though its switchport object never changed.
                manager.calls.clear()
                with patch('network_labs.appliances.lacp.configure', return_value=set()):
                    configure(manager, 4, previous, desired)
                reads = [args for args in manager.calls if args[:4] == ('bridge', '-j', 'vlan', 'show')]
                self.assertEqual(reads, [] if not expected else [('bridge', '-j', 'vlan', 'show', 'dev', port)])

    def test_failed_rollback_retains_recoverable_state(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Manager('campus-lan'); manager.directory = Path(folder)
            manager.state = {'spec': campus('/rootfs'), 'phase': 'running', 'revision': 0}
            with patch('network_labs.appliances.lan.configure', side_effect=RuntimeFailure('injected')):
                with self.assertRaisesRegex(RuntimeFailure, 'rollback failed'):
                    manager.configure_ios('R1', 'conf t\nno ip routing\nend')
            self.assertEqual(manager.state['phase'], 'configuration-failed')
            self.assertIn('pending_spec', manager.state)
            with patch('network_labs.appliances.lan.configure'):
                manager.recover()
            self.assertEqual(manager.state['phase'], 'running')
            self.assertNotIn('pending_spec', manager.state)
