"""Co-located services must retain separate live transactions and recovery."""
import copy
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.examples import ospf_dhcp_lab
from network_labs.appliances.ios import compile_config
from network_labs.appliances.runtime import Manager
from network_labs.appliances.service_adapters import adapters


class ServiceAdapterTests(unittest.TestCase):
    def test_cli_selects_only_changed_service_and_preserves_other_policy(self):
        spec = ospf_dhcp_lab('/rootfs'); before = copy.deepcopy(spec)
        for text, expected in [('interface vlan20\nip ospf cost 40', 'ospf'),
                               ('interface vlan10\nno ip helper-address 198.18.0.3', 'dhcp_relay')]:
            result = compile_config(spec, 'SW1', 'conf t\n' + text + '\nend')
            selected = adapters(result['nodes'][1], spec['nodes'][1])
            self.assertEqual([a.__name__.rsplit('.', 1)[-1] for a in selected], [expected])
            other = 'dhcp_relay' if expected == 'ospf' else 'ospf'
            self.assertEqual(result['nodes'][1][other], spec['nodes'][1][other])
        self.assertEqual(spec, before)

    def test_combined_service_or_network_edits_refused_before_journal(self):
        spec = ospf_dhcp_lab('/rootfs'); node = spec['nodes'][1]
        candidate = copy.deepcopy(spec)
        candidate['nodes'][1]['ospf']['interfaces']['vlan20']['cost'] = 40
        candidate['nodes'][1]['dhcp_relay'] = None
        manager = Mock(); manager.read.return_value = {'spec': spec, 'phase': 'running'}
        with self.assertRaisesRegex(ValueError, 'separate service transactions'):
            Manager._configure_network(manager, 'SW1', candidate, 'test')
        manager.save.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'separate service transactions'):
            compile_config(spec, 'SW1', 'conf t\ninterface vlan20\nip ospf cost 40\ninterface vlan10\nno ip helper-address 198.18.0.3\nend')
        candidate = copy.deepcopy(node); candidate['svis']['vlan10']['address'] = '192.0.2.2/24'
        with self.assertRaisesRegex(ValueError, 'service adapter'):
            adapters(candidate, node)

    def test_noop_preflights_both_services_without_reload(self):
        spec = ospf_dhcp_lab('/rootfs')
        manager = Mock(); manager.read.return_value = {'spec': spec, 'phase': 'running', 'revision': 2}
        with patch('network_labs.appliances.ospf.preflight_change') as ospf, \
             patch('network_labs.appliances.dhcp_relay.preflight_change') as relay, \
             patch('network_labs.appliances.ospf.apply_change') as ospf_apply, \
             patch('network_labs.appliances.dhcp_relay.apply_change') as relay_apply:
            result = Manager._configure_network(manager, 'SW1', copy.deepcopy(spec), 'test')
            ospf.assert_called_once(); relay.assert_called_once()
            ospf_apply.assert_not_called(); relay_apply.assert_not_called()
        self.assertTrue(result['unchanged']); self.assertEqual(result['revision'], 2)
        manager.save.assert_not_called()

    def test_recover_helper_transaction_does_not_choose_ospf(self):
        spec = ospf_dhcp_lab('/rootfs'); pending = copy.deepcopy(spec)
        pending['nodes'][1]['dhcp_relay'] = None
        state = {'phase': 'configuration-failed', 'spec': spec, 'pending_spec': pending}
        manager = Mock(); manager.read.return_value = state
        with patch('network_labs.appliances.ospf.apply_change') as ospf, \
             patch('network_labs.appliances.dhcp_relay.apply_change') as relay, \
             patch('network_labs.appliances.lan.configure'):
            Manager.recover(manager)
            relay.assert_called_once_with(manager, 1, spec['nodes'][1], pending['nodes'][1])
            self.assertNotIn('SW1', [call.args[2]['name'] for call in ospf.call_args_list])
        self.assertEqual(state['phase'], 'running'); self.assertNotIn('pending_spec', state)
