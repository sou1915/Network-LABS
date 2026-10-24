"""Bounded remote DHCP pool and relay policy, without mocked lease claims."""
import copy
import subprocess
import unittest
from unittest.mock import Mock

from network_labs.appliances.spec import validate
from network_labs.appliances.examples import dhcp_relay_lab
from network_labs.appliances.dhcp import server_config as dhcp_config
from network_labs.appliances.dhcp_relay import server_config, observe
from network_labs.appliances.ios import compile_config


class DHCPRelayTests(unittest.TestCase):
    def test_remote_pool_and_relay_configuration(self):
        spec = validate(dhcp_relay_lab('/rootfs'))
        relay, server = spec['nodes'][2:]
        self.assertIn('dhcp-relay=192.0.2.1,198.51.100.10,vlan20\n', server_config(relay))
        self.assertIn('port=0\n', server_config(relay))
        self.assertNotIn('dhcp-range', server_config(relay))
        config = dhcp_config(server)
        self.assertIn('option subnet 255.255.255.0', config)
        self.assertIn('option router 192.0.2.1', config)
        self.assertIn('start 192.0.2.100', config)

    def test_relay_rejects_unrepresentable_policy(self):
        changes = [dict(interface='vlan99'), dict(interface='vlan20'),
                   dict(server='198.51.100.1'), dict(server='198.51.100.255'),
                   dict(server='198.51.100.0'), dict(server='203.0.113.10'),
                   dict(server=123), dict(server='198.51.100.10\nport=53'),
                   dict(upstream_interface='eth2'), dict(option82=True)]
        for change in changes:
            spec = dhcp_relay_lab('/rootfs')
            spec['nodes'][2]['dhcp_relay'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(spec)
        for change in (dict(forwarding=False), dict(shutdown=['vlan10']),
                       dict(shutdown=['vlan20']), dict(startup=[['/bin/true']])):
            spec = dhcp_relay_lab('/rootfs'); spec['nodes'][2].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(spec)

    def test_explicit_pool_rejects_ambiguous_or_unusable_networks(self):
        for network in (123, '192.0.2.1/24', '0.0.0.0/0', '127.0.0.0/8',
                        '224.0.0.0/4', '198.51.100.0/25', '192.0.2.100/31'):
            spec = dhcp_relay_lab('/rootfs'); spec['nodes'][3]['dhcp_server']['network'] = network
            with self.subTest(network=network), self.assertRaises(ValueError):
                validate(spec)

    def test_remote_pool_netmask_is_not_server_interface_netmask(self):
        spec = dhcp_relay_lab('/rootfs')
        spec['nodes'][3]['dhcp_server']['network'] = '192.0.2.0/25'
        self.assertIn('option subnet 255.255.255.128', dhcp_config(validate(spec)['nodes'][3]))

    def test_no_false_daemon_health_from_config_or_socket(self):
        node = validate(dhcp_relay_lab('/rootfs'))['nodes'][2]
        for code, contents, expected in ((0, server_config(node), True), (0, 'drift', False), (1, '', False)):
            manager = Mock()
            manager.crun.return_value = subprocess.CompletedProcess([], code, contents, '')
            manager.ns.return_value = subprocess.CompletedProcess([], 1, '', '')
            result = observe(manager, 2, node)
            self.assertEqual(result['configuration_verified'], expected)
            self.assertIsNone(result['listener_snapshot'])
            self.assertNotIn('running', result)
            self.assertNotIn('ready', result)

    def test_live_cli_cannot_silently_leave_relay_config_stale(self):
        spec = dhcp_relay_lab('/rootfs'); spec['nodes'][2]['dialect'] = 'ios-basic'
        before = copy.deepcopy(spec)
        with self.assertRaisesRegex(ValueError, 'UP static'):
            compile_config(spec, 'SW1', 'conf t\ninterface vlan10\nshutdown\nend')
        self.assertEqual(spec, before)

    def test_live_network_guard_precedes_journal_and_apply(self):
        from network_labs.appliances.runtime import Manager
        from unittest.mock import patch
        spec = dhcp_relay_lab('/rootfs')
        state = {'spec': spec, 'phase': 'running', 'revision': 0}
        before = copy.deepcopy(state)
        manager = Mock()
        manager.read.return_value = state
        candidate = copy.deepcopy(spec)
        candidate['nodes'][2]['multicast'] = {'snooping': True, 'querier': True, 'ports': {}}
        with patch('network_labs.appliances.lan.configure') as apply:
            with self.assertRaisesRegex(ValueError, 'service adapter'):
                Manager._configure_network(manager, 'SW1', candidate, 'test')
            apply.assert_not_called()
            manager.save.assert_not_called()
        self.assertEqual(state, before)

    def test_helper_add_remove_idempotence_and_upstream_resolution(self):
        spec = dhcp_relay_lab('/rootfs')
        spec['nodes'][2]['dhcp_relay'] = None
        before = copy.deepcopy(spec)
        added = compile_config(spec, 'SW1', 'conf t\ninterface vlan10\nip helper-address 198.51.100.10\nend')
        self.assertEqual(added['nodes'][2]['dhcp_relay'], {
            'interface': 'vlan10', 'upstream_interface': 'vlan20', 'server': '198.51.100.10'})
        self.assertEqual(spec, before)
        repeated = compile_config(added, 'SW1', 'conf t\ninterface vlan10\nip helper-address 198.51.100.10\nend')
        self.assertEqual(repeated, added)
        wrong = compile_config(added, 'SW1', 'conf t\ninterface vlan10\nno ip helper-address 198.51.100.11\nend')
        self.assertEqual(wrong, added)
        removed = compile_config(added, 'SW1', 'conf t\ninterface vlan10\nno ip helper-address 198.51.100.10\nend')
        self.assertIsNone(removed['nodes'][2]['dhcp_relay'])

    def test_helper_refuses_multiple_offlink_local_or_wrong_context(self):
        spec = dhcp_relay_lab('/rootfs')
        for commands in ('interface vlan10\nip helper-address 198.51.100.11',
                         'ip helper-address 198.51.100.10',
                         'interface vlan20\nip helper-address 192.0.2.100'):
            with self.subTest(commands=commands), self.assertRaises(ValueError):
                compile_config(spec, 'SW1', 'conf t\n' + commands + '\nend')
        spec['nodes'][2]['dhcp_relay'] = None
        for address in ('203.0.113.10', '198.51.100.1', '198.51.100.255', '::1', 'nope'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                compile_config(spec, 'SW1', 'conf t\ninterface vlan10\nip helper-address ' + address + '\nend')

    def test_live_drift_refusal_happens_before_journal(self):
        from network_labs.appliances.runtime import Manager, RuntimeFailure
        spec = dhcp_relay_lab('/rootfs')
        state = {'spec': spec, 'phase': 'running', 'revision': 0}
        candidate = copy.deepcopy(spec); candidate['nodes'][2]['dhcp_relay'] = None
        manager = Mock(); manager.read.return_value = state
        manager.crun.return_value = subprocess.CompletedProcess([], 0, 'drift', '')
        with self.assertRaisesRegex(RuntimeFailure, 'drift'):
            Manager._configure_network(manager, 'SW1', candidate, 'test')
        manager.save.assert_not_called()
        self.assertEqual(state['phase'], 'running')
