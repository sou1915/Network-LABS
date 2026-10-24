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
