import copy
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from network_labs.appliances.examples import lacp_lab
from network_labs.appliances.stp_recovery import component, reconcile, restored_channels
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.spec import validate


def setup():
    spec = lacp_lab('/rootfs')
    for node in spec['nodes'][4:]:
        node['spanning_tree'] = {'mode': 'stp', 'hello_time': 1, 'max_age': 6, 'forward_delay': 4}
    spec = validate(spec); node = spec['nodes'][4]; previous = copy.deepcopy(node)
    previous['shutdown'] = ['eth2', 'eth3']
    manager = Mock(); manager.state = {'spec': spec}
    manager.ns.return_value = subprocess.CompletedProcess([], 0, '[]', '')
    return spec, node, previous, manager


class StpRecoveryTests(unittest.TestCase):
    def test_only_recovery_across_declared_carrier_threshold_requests_cleanup(self):
        _, node, previous, manager = setup()
        self.assertEqual(restored_channels(node, previous), ['bond1'])
        previous['shutdown'] = ['eth2']
        self.assertEqual(restored_channels(node, previous), [])
        self.assertIsNone(reconcile(manager, 4, node, previous)); manager.ns.assert_not_called()
        node['port_channels']['bond1']['min_links'] = 2
        previous = copy.deepcopy(node); previous['shutdown'] = ['eth2']
        self.assertEqual(restored_channels(node, previous), ['bond1'])
        node['shutdown'] = ['bond1']
        self.assertEqual(restored_channels(node, previous), [])

    def test_component_excludes_disconnected_bridges_and_admin_down_links(self):
        spec, node, _, _ = setup()
        self.assertEqual([n['name'] for _, n in component(spec, node)], ['SW1', 'SW2'])
        spec['nodes'][5]['shutdown'] = ['eth2', 'eth3']
        self.assertEqual([n['name'] for _, n in component(spec, node)], ['SW1'])

    def test_two_stable_reads_then_dynamic_only_flush_on_both_bridges(self):
        _, node, previous, manager = setup()
        tree = {'protocol': 'stp', 'local_state_settled': True, 'root_id': '1000.001122334455',
                'root_port': 'bond1', 'ports': {'bond1': {'state': 'forwarding'}}}
        with patch('network_labs.appliances.spanning_tree.kernel_ids', return_value={}), \
             patch('network_labs.appliances.spanning_tree.observe', return_value=tree) as observe, \
             patch('network_labs.appliances.lacp.observe', return_value={'bond1': {'ready': True}}), \
             patch('network_labs.appliances.stp_recovery.time.sleep'):
            result = reconcile(manager, 4, node, previous)
        self.assertEqual(observe.call_count, 4)
        self.assertEqual(result['bridges'], ['SW1', 'SW2']); self.assertTrue(result['dynamic_only'])
        flushes = [call.args for call in manager.ns.call_args_list if 'flush' in call.args]
        self.assertEqual(flushes, [(i, 'bridge', 'fdb', 'flush', 'dev', 'br0', 'dynamic') for i in (4, 5)])
        self.assertTrue(all(0 < call.kwargs['timeout'] <= 3 for call in manager.ns.call_args_list))

    def test_timeout_and_malformed_reads_never_flush_or_report_success(self):
        _, node, previous, manager = setup()
        with patch('network_labs.appliances.stp_recovery.time.monotonic', side_effect=[0, 1000]):
            with self.assertRaises(RuntimeFailure): reconcile(manager, 4, node, previous)
        manager.ns.assert_not_called()
        manager.ns.return_value.stdout = 'not-json'
        with self.assertRaises(RuntimeFailure): reconcile(manager, 4, node, previous)
        self.assertFalse(any('flush' in call.args for call in manager.ns.call_args_list))
