"""Carrier convergence state machine, component boundaries and worker health."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.examples import stp_lacp_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.stp_carrier import Tracker, components, observe, sample


class CarrierWorkerTests(unittest.TestCase):
    def test_two_stable_reads_and_completed_repair_are_required(self):
        tracker = Tracker()
        self.assertFalse(tracker.update('bundle', False))
        self.assertFalse(tracker.update('bundle', True)); self.assertFalse(tracker.update('bundle', True))
        self.assertFalse(tracker.update('spare', False))
        self.assertFalse(tracker.update('spare', True)); self.assertTrue(tracker.update('spare', True))
        # Failure after the first bridge flush must not commit a successful
        # transition; the next stable observation requests repair again.
        self.assertTrue(tracker.update('spare', True))
        tracker.dirty = True
        self.assertFalse(tracker.update('bundle', True)); self.assertTrue(tracker.update('bundle', True))
        tracker.committed('spare'); self.assertFalse(tracker.update('spare', True))
        self.assertFalse(tracker.update('bundle', True)); self.assertTrue(tracker.update('bundle', True))

    def test_opt_in_component_scope_and_unvalidated_profiles(self):
        spec = stp_lacp_lab('/rootfs')
        self.assertEqual([[node['name'] for _, node in group] for group in components(spec)], [['SW1', 'SW2']])
        for index, edit in enumerate((lambda s: s['nodes'][5]['spanning_tree'].update(carrier_recovery=False),
                                      lambda s: s['nodes'][4]['spanning_tree'].update(carrier_recovery=1),
                                      lambda s: s['nodes'][4]['spanning_tree'].update(mode='off'))):
            candidate = copy.deepcopy(spec); edit(candidate)
            with self.subTest(case=index), self.assertRaises(ValueError): validate(candidate)
        for node in spec['nodes'][4:]: node['spanning_tree']['carrier_recovery'] = False
        self.assertEqual(components(validate(spec)), [])

    def test_selected_bond_must_be_ready_and_roots_must_agree(self):
        spec = stp_lacp_lab('/rootfs'); peers = components(spec)[0]; manager = Mock()
        manager.ns.return_value.stdout = '[]'
        tree = {'root_id': '1000.000000000001', 'root_port': 'bond1', 'protocol': 'stp', 'local_state_settled': True,
                'ports': {'bond1': {'state': 'forwarding'}}}
        with patch('network_labs.appliances.spanning_tree.kernel_ids', return_value={}), \
             patch('network_labs.appliances.spanning_tree.observe', return_value=tree), \
             patch('network_labs.appliances.lacp.observe', return_value={'bond1': {'ready': False}}):
            self.assertFalse(sample(manager, peers)[1])
        other = {**tree, 'root_id': '2000.000000000002'}
        with patch('network_labs.appliances.spanning_tree.kernel_ids', return_value={}), \
             patch('network_labs.appliances.spanning_tree.observe', side_effect=[tree, other]), \
             patch('network_labs.appliances.lacp.observe', return_value={'bond1': {'ready': True}}):
            self.assertFalse(sample(manager, peers)[1])

    def test_health_rejects_stale_wrong_token_degraded_and_reused_process(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Mock(); manager.directory = Path(folder)
            manager.read.return_value = {'stp_carrier_worker': {'pid': 100, 'starttime': '1', 'token': 'expected'}}
            baseline = {'token': 'expected', 'status': 'ready', 'observed_monotonic': time.monotonic(), 'repairs': 1}
            def health(report, alive=True):
                (manager.directory / 'stp-carrier.json').write_text(json.dumps(report))
                with patch('network_labs.appliances.stp_carrier.alive', return_value=alive): return observe(manager)
            self.assertTrue(health(baseline)['available'])
            for changes in ({'token': 'wrong'}, {'status': 'degraded'}, {'observed_monotonic': time.monotonic() - 30}):
                self.assertFalse(health({**baseline, **changes})['available'])
            self.assertFalse(health(baseline, alive=False)['available'])
