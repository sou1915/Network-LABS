"""Comparable counter epochs, integer deltas and unlocked bounded observation."""
import copy
from contextlib import contextmanager
import io
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.__main__ import main
from network_labs.appliances.interface_stats import FIELDS
from network_labs.appliances.monitor import compare, monitor, render
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.spec import example


def sample(value=0, tick=0):
    return {'monotonic_ns': tick, 'generation': {'pid': 123, 'process_starttime': '456', 'netns_inode': 7, 'netns_device': 4},
            'ports': {'eth0': {'ifindex': 2, 'width_bits': 64, 'address': '02:00:00:00:00:01', 'kind': 'veth',
                               'link_type': 'ether', 'counters': {f: value for f in FIELDS}}}}


class MonitorTests(unittest.TestCase):
    def test_exact_integer_deltas_and_actual_elapsed_time_precede_float_rates(self):
        a, b = sample(2**60, 0), sample(2**60 + 12, 3_000_000_000)
        original = copy.deepcopy((a, b))
        elapsed, (row,) = compare(a, b, ['eth0'])
        self.assertEqual(elapsed, 3)
        self.assertEqual(row['delta']['rx_packets'], 12)
        self.assertEqual(row['rates']['rx_packets_per_second'], 4)
        self.assertEqual(row['rates']['tx_bits_per_second'], 32)
        self.assertEqual(row['status'], 'measured')
        self.assertEqual((a, b), original)

    def test_generation_interface_and_source_changes_invalidate_the_whole_port(self):
        changes = [('generation', 'pid', 124), ('generation', 'process_starttime', '999'),
                   ('generation', 'netns_inode', 8), ('port', 'ifindex', 3),
                   ('port', 'address', '02:00:00:00:00:02'), ('port', 'width_bits', 32), ('port', 'ifindex', None)]
        for section, key, value in changes:
            a, b = sample(10), sample(20, 1_000_000_000)
            (b['generation'] if section == 'generation' else b['ports']['eth0'])[key] = value
            with self.subTest(key=key):
                _, (row,) = compare(a, b, ['eth0'])
                self.assertNotEqual(row['status'], 'measured')
                self.assertTrue(all(v is None for v in row['delta'].values()))
                self.assertTrue(all(v is None for v in row['rates'].values()))

    def test_a_single_decrease_is_not_treated_as_a_wrap_or_mixed_epoch_rate(self):
        a, b = sample(100), sample(200, 2_000_000_000)
        b['ports']['eth0']['counters']['tx_dropped'] = 0
        _, (row,) = compare(a, b, ['eth0'])
        self.assertEqual(row['status'], 'counter_decreased')
        self.assertTrue(all(v is None for v in row['delta'].values()))

    def test_missing_fields_allow_partial_rates_but_missing_samples_do_not_invent_zero(self):
        a, b = sample(10), sample(15, 1_000_000_000)
        a['ports']['eth0']['counters']['rx_packets'] = None
        _, (row,) = compare(a, b, ['eth0'])
        self.assertEqual(row['status'], 'partial')
        self.assertIsNone(row['rates']['rx_packets_per_second'])
        self.assertEqual(row['rates']['tx_packets_per_second'], 5)
        for after in (None, {**b, 'ports': {}}):
            _, (row,) = compare(a, after, ['eth0'])
            self.assertTrue(all(v is None for v in row['rates'].values()))
        _, (row,) = compare(a, {**b, 'monotonic_ns': 0}, ['eth0'])
        self.assertEqual(row['status'], 'time_unavailable')

    def test_invalid_interval_and_interface_do_not_start_a_wait(self):
        with patch('network_labs.appliances.monitor._sample') as read, patch('network_labs.appliances.monitor.time.sleep') as sleep:
            for seconds in (0, 31, True):
                with self.assertRaises(ValueError):
                    monitor('lab', 'PC1', seconds=seconds)
            read.assert_not_called()
            read.return_value = sample()
            with self.assertRaises(ValueError):
                monitor('lab', 'PC1', 'host-eno1')
            sleep.assert_not_called()

    def test_second_observation_failure_produces_an_explicit_unknown_report(self):
        with patch('network_labs.appliances.monitor._sample', side_effect=[sample(), RuntimeFailure('lab stopped')]), \
             patch('network_labs.appliances.monitor.time.sleep') as sleep:
            report = monitor('lab', 'PC1', seconds=2)
        sleep.assert_called_once_with(2)
        self.assertFalse(report['second_observation_available'])
        self.assertIsNone(report['elapsed_seconds'])
        self.assertEqual(report['packet_delivery'], 'not_tested')
        self.assertEqual(report['ports'][0]['status'], 'observation_unavailable')
        self.assertIn('lab stopped', render(report))

    def test_each_sample_uses_a_fresh_manager_and_waits_without_a_lock(self):
        spec = example('/rootfs'); held = []
        @contextmanager
        def locked():
            held.append(True)
            try:
                yield manager
            finally:
                held.pop()
        values = []
        for value in (10, 20):
            stats = {d: {m: value for m in ('packets', 'bytes', 'errors', 'dropped')} for d in ('rx', 'tx')}
            values.append(subprocess.CompletedProcess([], 0, json.dumps([{'ifname': 'eth0', 'ifindex': 2, 'stats64': stats}]), ''))
        manager = SimpleNamespace(locked=locked, read=lambda: {'phase': 'running', 'spec': spec},
                                  crun=Mock(return_value=subprocess.CompletedProcess([], 0, '{"status":"running","pid":123}', '')),
                                  ns=Mock(side_effect=values))
        def check_unlocked(*args):
            self.assertFalse(held)
        with patch('network_labs.appliances.monitor.Manager', return_value=manager) as factory, \
             patch('network_labs.appliances.monitor.process_identity', return_value='456'), \
             patch('network_labs.appliances.monitor.os.stat', return_value=SimpleNamespace(st_dev=4, st_ino=7)), \
             patch('network_labs.appliances.monitor.time.sleep', side_effect=check_unlocked):
            report = monitor('micro-lan', 'PC1', 'eth0', seconds=1, ready=check_unlocked)
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(report['ports'][0]['delta']['rx_packets'], 10)
        self.assertTrue(all(call.args == (0, 'ip', '-j', '-s', '-d', 'link', 'show') for call in manager.ns.call_args_list))
        self.assertTrue(all(call.args == ('state', 'PC1') for call in manager.crun.call_args_list))

    def test_cli_json_text_and_interruption(self):
        with patch('network_labs.appliances.monitor._sample', side_effect=[sample(), sample(1, 1_000_000_000)]), \
             patch('network_labs.appliances.monitor.time.sleep'):
            report = monitor('lab', 'PC1')
        with patch('network_labs.appliances.monitor.monitor', return_value=report), patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(main(['monitor', 'lab', 'PC1', '--json']), 0)
            self.assertTrue(json.loads(out.getvalue())['passive'])
            out.seek(0); out.truncate()
            self.assertEqual(main(['monitor', 'lab', 'PC1']), 0)
            self.assertIn('bit/s', out.getvalue())
        with patch('network_labs.appliances.monitor.monitor', side_effect=KeyboardInterrupt), patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(main(['monitor', 'lab', 'PC1']), 130)
