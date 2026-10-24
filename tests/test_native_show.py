import copy
import io
import json
import unittest
from contextlib import nullcontext
from unittest.mock import patch
from test_native_verify import manager_for, completed
from network_labs.appliances.show import COMMANDS, show, render
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.__main__ import main


class NativeShowTests(unittest.TestCase):
    def test_allowlisted_reads_preserve_state_and_return_kernel_evidence(self):
        for command, argv in COMMANDS.items():
            manager = manager_for(); before = copy.deepcopy(manager.read())
            manager.ns.side_effect = None; manager.ns.return_value = completed([])
            result = show(manager, 'SW1', command)
            self.assertEqual(result['status'], 'observed')
            manager.ns.assert_called_once_with(1, *argv, check=False, timeout=3)
            self.assertEqual(manager.read(), before); manager.save.assert_not_called()
            self.assertFalse(result['test_packets_sent'])
            self.assertIn('Aucune entrée', render(result))

    def test_invalid_commands_and_pending_state_never_reach_kernel(self):
        for command in ('show running-config', 'show arp; reboot', 'show arp\nshow ip route', ''):
            manager = manager_for()
            with self.assertRaises(ValueError): show(manager, 'PC1', command)
            manager.ns.assert_not_called(); manager.crun.assert_not_called()
        manager = manager_for(); manager.read.return_value['pending_node'] = 'SW1'
        with self.assertRaises(RuntimeFailure): show(manager, 'SW1', 'show arp')
        manager.ns.assert_not_called()
        for role in ('PC1', 'missing'):
            with self.assertRaises(ValueError): show(manager_for(), role, 'show vlan brief')

    def test_unavailable_is_not_empty_or_success(self):
        for payload in ('invalid', '{}', '[1]'):
            manager = manager_for(); manager.ns.side_effect = None; manager.ns.return_value = completed(payload)
            result = show(manager, 'PC1', 'show arp')
            self.assertEqual(result['status'], 'unknown'); self.assertNotIn('Aucune entrée', render(result))
        manager = manager_for(); manager.crun.side_effect = None; manager.crun.return_value = completed({'status': 'stopped'})
        self.assertEqual(show(manager, 'PC1', 'show arp')['status'], 'blocked'); manager.ns.assert_not_called()

    def test_render_keeps_actual_dhcp_address_and_escapes_observed_names(self):
        manager = manager_for(); manager.ns.side_effect = None
        manager.ns.return_value = completed([{'ifname': 'eth0\x1b[31m', 'flags': ['UP'], 'operstate': 'UP',
            'addr_info': [{'family': 'inet', 'local': '192.0.2.100', 'prefixlen': 24}]}])
        report = show(manager, 'PC1', ' SHOW IP INTERFACE BRIEF '); text = render(report)
        self.assertIn('192.0.2.100/24', text); self.assertNotIn('\x1b', text)
        self.assertEqual(report['observation']['records'][0]['ifname'], 'eth0\x1b[31m')

    def test_missing_fields_stay_unknown_and_unresolved_neighbors_visible(self):
        manager = manager_for(); manager.ns.side_effect = None
        manager.ns.return_value = completed([{'dst': '192.0.2.9', 'dev': 'eth0', 'state': ['FAILED']}])
        text = render(show(manager, 'PC1', 'show arp'))
        self.assertIn('FAILED', text); self.assertIn('?', text)
        manager.ns.return_value = completed([{'ifname': 'eth0'}])
        text = render(show(manager, 'PC1', 'show ip interface brief'))
        self.assertNotIn('unassigned', text); self.assertNotIn('down', text)

    def test_cli_json_observation_exit(self):
        manager = manager_for(); manager.locked.return_value = nullcontext(manager)
        with patch('network_labs.appliances.__main__.Manager', return_value=manager), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['show', 'lab', 'PC1', '--text', 'show ip route', '--json']), 0)
            self.assertEqual(json.loads(output.getvalue())['kernel_command'], list(COMMANDS['show ip route']))

    def test_fdb_uses_actual_ifname_and_retains_raw_reachable_state(self):
        manager = manager_for(); manager.ns.side_effect = None
        records = [{'mac': '02:00:00:00:40:01', 'ifname': 'eth0', 'vlan': 10, 'state': '', 'flags': []},
                   {'mac': '33:33:00:00:00:01', 'ifname': 'br0', 'state': 'permanent', 'flags': ['self']},
                   {'mac': '02:00:00:00:40:02', 'dev': 'eth2', 'vlan': 30}]
        manager.ns.return_value = completed(records)
        report = show(manager, 'SW1', 'show mac address-table'); before = copy.deepcopy(report)
        output = render(report)
        for text in ('eth0', 'br0', 'eth2', 'reachable', 'permanent'):
            self.assertIn(text, output)
        self.assertEqual(report, before)
        self.assertEqual(report['observation']['records'], records)

    def test_fdb_filters_keep_snapshot_and_use_only_observed_vlan_or_port(self):
        manager = manager_for(); manager.ns.side_effect = None
        records = [{'mac': '02:00:00:00:40:01', 'ifname': 'eth0', 'vlan': 10},
                   {'mac': '02:00:00:00:40:02', 'ifname': 'eth2', 'vlan': 30},
                   {'mac': '33:33:00:00:00:01', 'ifname': 'eth0'}]
        manager.ns.return_value = completed(records)
        for suffix, wanted in [('vlan 10', records[:1]), ('interface eth2', records[1:2]), ('vlan 20', [])]:
            result = show(manager, 'SW1', 'show mac address-table ' + suffix)
            self.assertEqual(result['display_records'], wanted)
            self.assertEqual(result['observation']['records'], records)
            self.assertEqual(result['kernel_command'], list(COMMANDS['show mac address-table']))
            if not wanted:
                self.assertIn('correspondant au filtre', render(result))
                self.assertNotIn('Aucune entrée retournée par le kernel', render(result))

    def test_fdb_invalid_filters_never_execute(self):
        for suffix in ('vlan 0', 'vlan 4095', 'vlan xxx', 'interface eth99', 'interface eth0; reboot', 'dynamic', 'vlan 10 interface eth0'):
            manager = manager_for()
            with self.assertRaises(ValueError): show(manager, 'SW1', 'show mac address-table ' + suffix)
            manager.ns.assert_not_called(); manager.crun.assert_not_called()

    def test_ospf_queries_use_readonly_daemon_evidence_without_kernel_fallback(self):
        from network_labs.appliances.show import BIRD_COMMANDS
        for command, daemon_command in BIRD_COMMANDS.items():
            manager = manager_for(); before = copy.deepcopy(manager.read())
            raw = '0001 BIRD ready.\n1000 Router ID State\n 2.2.2.2 Full/DR\n'
            with patch('network_labs.appliances.ospf.read_cli', return_value=raw) as read:
                report = show(manager, 'SW1', command)
                read.assert_called_once_with(manager, 'SW1', daemon_command)
            self.assertEqual(report['status'], 'observed'); self.assertEqual(report['observation']['text'], raw)
            self.assertIsNone(report['kernel_command']); manager.ns.assert_not_called()
            self.assertEqual(manager.read(), before)
            self.assertIn('BIRD 2', render(report)); self.assertIn('Full/DR', render(report))

    def test_ospf_unavailable_empty_and_undeclared_process_are_not_empty_tables(self):
        for output in (None, '', '  \n'):
            with patch('network_labs.appliances.ospf.read_cli', return_value=output):
                report = show(manager_for(), 'SW1', 'show ip ospf neighbor')
            self.assertEqual(report['status'], 'unknown')
            self.assertNotIn('Aucune entrée', render(report))
        manager = manager_for()
        with self.assertRaises(ValueError): show(manager, 'PC1', 'show ip ospf')
        manager.crun.assert_not_called(); manager.ns.assert_not_called()

    def test_ospf_control_characters_are_escaped_without_changing_json(self):
        raw = '0001 BIRD\nInterface eth0\x1b[31m\n'
        with patch('network_labs.appliances.ospf.read_cli', return_value=raw):
            report = show(manager_for(), 'SW1', 'show ip ospf interface')
        self.assertNotIn('\x1b', render(report)); self.assertEqual(report['observation']['text'], raw)

    def test_malformed_vlan_entry_is_not_rendered_as_empty_kernel_table(self):
        manager = manager_for(); manager.ns.side_effect = None
        manager.ns.return_value = completed([{'ifname': 'eth0', 'vlans': [None]}])
        text = render(show(manager, 'SW1', 'show vlan brief'))
        self.assertIn('eth0', text); self.assertIn('?', text); self.assertNotIn('Aucune entrée', text)

    def test_lldp_observed_names_ports_and_raw_evidence(self):
        from test_native_lldp_neighbors import payload, record
        manager = manager_for(); manager.read.return_value['spec']['nodes'][1]['lldp'] = {'interfaces': ['eth1']}
        raw = payload(record(name='external-peer\x1b[31m'))
        before = copy.deepcopy(manager.read())
        for command in ('show lldp neighbors', 'show lldp neighbors detail'):
            with patch('network_labs.appliances.lldp.read_cli', return_value=raw) as read:
                result = show(manager, 'SW1', command)
            read.assert_called_once_with(manager, 'SW1', 'neighbors details')
            self.assertEqual(result['status'], 'observed'); self.assertEqual(result['observation']['raw'], raw)
            text = render(result)
            self.assertIn('external-peer', text); self.assertIn('ifname: eth0', text)
            self.assertIn('TTL annoncé', text); self.assertNotIn('\x1b', text)
            manager.ns.assert_not_called(); self.assertEqual(manager.read(), before)

    def test_lldp_partial_empty_and_unknown_remain_distinct(self):
        from test_native_lldp_neighbors import payload, record
        for raw, status in [(payload(), 'observed'), (None, 'unknown'), (payload(record(), None), 'partial')]:
            manager = manager_for(); manager.read.return_value['spec']['nodes'][1]['lldp'] = {'interfaces': ['eth1']}
            with patch('network_labs.appliances.lldp.read_cli', return_value=raw):
                result = show(manager, 'SW1', 'show lldp neighbors')
            self.assertEqual(result['status'], status)
            if status == 'partial':
                self.assertIn('SW2', render(result)); self.assertIn('partielle', render(result))
            elif status == 'unknown':
                self.assertNotIn('Aucun voisin', render(result))
            else:
                self.assertIn('Aucun voisin LLDP annoncé', render(result))
        manager = manager_for()
        with self.assertRaises(ValueError): show(manager, 'PC1', 'show lldp neighbors')
        manager.crun.assert_not_called()

    def test_lldp_read_pipeline_does_not_hide_client_failure(self):
        from network_labs.appliances.lldp import read_cli
        manager = manager_for(); manager.crun.side_effect = None
        manager.crun.return_value = completed('{"lldp":[{}]}', 1)
        self.assertIsNone(read_cli(manager, 'SW1', 'neighbors details'))
        self.assertIn('set -o pipefail;', manager.crun.call_args.args[4])
