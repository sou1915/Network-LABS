"""Static admission must reject incomplete policies and preserve real evidence."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.diagnostics import explain_node
from network_labs.appliances.examples import campus, lacp_lab, port_security_lab
from network_labs.appliances.firewall import fingerprint
from network_labs.appliances.ios import compile_config
from network_labs.appliances.lan import configure
from network_labs.appliances.persistence import drift
from network_labs.appliances.port_security import TABLE, apply, mac_address, observe, render
from network_labs.appliances.runtime import Manager, RuntimeFailure
from network_labs.appliances.spec import validate

MAC = '02:00:00:00:01:10'


def ruleset(packets=0):
    return {'nftables': [
        {'metainfo': {'version': 'test'}},
        {'table': {'family': 'bridge', 'name': TABLE, 'handle': 1}},
        {'chain': {'family': 'bridge', 'table': TABLE, 'name': 'ingress', 'type': 'filter', 'hook': 'prerouting', 'prio': -300, 'policy': 'accept'}},
        {'rule': {'family': 'bridge', 'table': TABLE, 'chain': 'ingress', 'handle': 9, 'comment': 'deny:eth0',
                  'expr': [{'counter': {'packets': packets, 'bytes': packets * 60}}, {'drop': None}]}}]}


class PortSecurityTests(unittest.TestCase):
    def test_canonical_unicast_macs_and_stable_reference_manifest(self):
        self.assertEqual(mac_address('02AB.CDEF.1234'), '02:ab:cd:ef:12:34')
        for invalid in ('01:00:00:00:00:01', 'ff:ff:ff:ff:ff:ff', '00:00:00:00:00:00', '02-00-00-00-00-01', 'bad\nflush ruleset', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                mac_address(invalid)
        spec = port_security_lab('/rootfs')
        self.assertEqual(spec, validate(spec))
        self.assertEqual(spec['nodes'][0]['interface_macs']['eth0'], MAC)
        self.assertEqual(spec['nodes'][1]['port_security']['eth0']['mac_addresses'], [MAC])

    def test_limits_duplicates_roles_and_incomplete_dynamic_slots_fail_closed(self):
        edits = [lambda n: n['port_security']['eth0'].update(maximum=True),
                 lambda n: n['port_security']['eth0'].update(maximum=65),
                 lambda n: n['port_security']['eth0'].update(maximum=2),
                 lambda n: n['port_security']['eth0'].update(mac_addresses=[]),
                 lambda n: n['port_security']['eth0'].update(maximum=2, mac_addresses=[MAC, MAC]),
                 lambda n: n['port_security']['eth0'].update(violation='shutdown'),
                 lambda n: n['switchports']['eth0'].update(mode='trunk'),
                 lambda n: n.update(startup=[['/bin/true']]),
                 lambda n: n['port_security'].update(eth1={'mac_addresses': [MAC]}),
                 lambda n: n.update(interface_macs={'eth9': MAC})]
        for edit in edits:
            spec = port_security_lab('/rootfs'); edit(spec['nodes'][1])
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                validate(spec)
        spec = port_security_lab('/rootfs')
        spec['nodes'][0]['port_security'] = spec['nodes'][1]['port_security']
        with self.assertRaises(ValueError):
            validate(spec)
        spec = lacp_lab('/rootfs')
        sw = next(n for n in spec['nodes'] if n['name'] == 'SW1')
        sw['port_security'] = {'bond1': {'mac_addresses': [MAC]}}
        with self.assertRaises(ValueError):
            validate(spec)

    def test_ios_validates_whole_static_block_and_can_replace_or_disable(self):
        spec = port_security_lab('/rootfs'); original = copy.deepcopy(spec)
        text = 'conf t\ninterface fa0/1\nswitchport port-security maximum 2\nswitchport port-security mac-address 0200.0000.0111\nswitchport port-security violation restrict\nend'
        changed = compile_config(spec, 'SW1', text)
        self.assertEqual(len(changed['nodes'][1]['port_security']['eth0']['mac_addresses']), 2)
        self.assertEqual(spec, original)
        for invalid in ('switchport port-security mac-address sticky', 'switchport port-security violation shutdown',
                        'switchport port-security maximum 2', 'switchport port-security aging time 10'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                compile_config(spec, 'SW1', 'conf t\ninterface fa0/1\nshutdown\n' + invalid)
        disabled = compile_config(spec, 'SW1', 'conf t\ninterface fa0/1\nno switchport port-security\nend')
        self.assertFalse(disabled['nodes'][1]['port_security'])
        with self.assertRaisesRegex(ValueError, 'Static-only'):
            compile_config(disabled, 'SW1', 'conf t\ninterface fa0/1\nswitchport port-security\nend')

    def test_atomic_table_is_scoped_before_fdb_and_unrelated_edits_preserve_counters(self):
        node = port_security_lab('/rootfs')['nodes'][1]
        script = render(node['port_security'], replace=True)
        self.assertIn('delete table bridge ' + TABLE, script)
        self.assertIn('hook prerouting priority -300', script)
        self.assertIn('ether saddr { ' + MAC + ' } counter accept', script)
        self.assertIn('counter drop comment "deny:eth0"', script)
        self.assertNotIn('flush ruleset', script)
        with tempfile.TemporaryDirectory() as folder:
            manager = SimpleNamespace(directory=Path(folder), state={}, ns=Mock())
            with patch('network_labs.appliances.port_security.shutil.which', return_value='/usr/sbin/nft'), \
                 patch('network_labs.appliances.port_security.read_table', side_effect=[None, ruleset()]):
                apply(manager, 1, node)
            self.assertEqual(manager.ns.call_count, 2)
            self.assertEqual(manager.ns.call_args_list[0].args[1:4], ('nft', '-c', '-f'))
            self.assertEqual(manager.ns.call_args_list[1].args[1:3], ('nft', '-f'))
            self.assertEqual(manager.state['port_security_fingerprints']['SW1'], fingerprint(ruleset()))
            manager.ns.reset_mock()
            previous = copy.deepcopy(node); previous['shutdown'] = ['eth0']
            apply(manager, 1, node, previous)
            manager.ns.assert_not_called()

    def test_observation_preserves_unknowns_and_detects_changed_policy_not_counters(self):
        node = port_security_lab('/rootfs')['nodes'][1]
        manager = SimpleNamespace(read=lambda: {'port_security_fingerprints': {'SW1': fingerprint(ruleset())}})
        with patch('network_labs.appliances.port_security.read_table', return_value=ruleset(7)):
            actual = observe(manager, 1, node)
        self.assertTrue(actual['fingerprint_matches'])
        self.assertEqual(actual['ports']['eth0']['dropped_packets'], 7)
        self.assertIsNone(actual['ports']['eth0']['accepted_packets'])
        raw = ruleset(7); raw['nftables'][2]['chain']['hook'] = 'forward'
        with patch('network_labs.appliances.port_security.read_table', return_value=raw):
            self.assertFalse(observe(manager, 1, node)['fingerprint_matches'])
        with patch('network_labs.appliances.port_security.read_table', return_value=None):
            missing = observe(manager, 1, node)
        self.assertFalse(missing['available'])
        self.assertIsNone(missing['ports']['eth0']['dropped_packets'])
        snapshot = {'links': [], 'addresses': [], 'routes': [], 'forwarding': False, 'port_security': actual}
        findings = explain_node(node, snapshot)
        self.assertIn('PORT_SECURITY_DROPS', {f['code'] for f in findings})
        snapshot['port_security'] = missing
        self.assertIn('PORT_SECURITY_UNVERIFIED', {f['code'] for f in explain_node(node, snapshot)})

    def test_declared_macs_are_applied_before_up_and_verified_before_save(self):
        spec = port_security_lab('/rootfs'); host = spec['nodes'][0]
        calls = []
        manager = SimpleNamespace(ns=lambda index, *args, **kw: (calls.append(args) or subprocess.CompletedProcess([], 0, '[]', '')))
        configure(manager, 0, host)
        self.assertLess(calls.index(('ip', 'link', 'set', 'dev', 'eth0', 'address', MAC)),
                        calls.index(('ip', 'link', 'set', 'dev', 'eth0', 'up')))
        actual = {'links': [{'ifname': 'lo'}, {'ifname': 'eth0', 'flags': ['UP'], 'address': '02:00:00:00:01:11'}],
                  'addresses': [{'ifname': 'eth0', 'addr_info': [{'scope': 'global', 'local': '192.0.2.10', 'prefixlen': 24}]}],
                  'routes': [], 'forwarding': False}
        manager = SimpleNamespace(read=lambda: {'spec': {**spec, 'nodes': [host]}}, inspect=lambda name: actual)
        self.assertIn('PC1/eth0: MAC address differs', drift(manager))

    def test_failed_security_apply_uses_existing_transaction_and_keeps_original_spec(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Manager('port-security-lan'); manager.directory = Path(folder)
            spec = port_security_lab('/rootfs')
            manager.state = {'spec': spec, 'phase': 'running', 'revision': 2}
            with patch('network_labs.appliances.lan.configure', side_effect=[RuntimeFailure('nft failure'), None]) as apply_network:
                with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                    manager.configure_ios('SW1', 'conf t\ninterface fa0/1\nno switchport port-security\nend')
            self.assertEqual(apply_network.call_count, 2)
            self.assertEqual(manager.state['spec'], spec)
            self.assertEqual(manager.state['revision'], 2)
            self.assertEqual(manager.state['phase'], 'running')
