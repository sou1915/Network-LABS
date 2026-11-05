"""Measurement attribution, topology contracts and cleanup on failed workload."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from network_labs.appliances.benchmark import benchmark, cgroup_context, group_snapshot, kernel_memory_peak, sample, summarize
from network_labs.appliances.examples import enterprise
from network_labs.appliances.runtime import Manager, RuntimeFailure
from network_labs.appliances.spec import MIB, validate


class BenchmarkTests(unittest.TestCase):
    def test_twenty_node_topology_and_return_routes(self):
        spec = enterprise('/rootfs')
        self.assertEqual(len(spec['nodes']), 20)
        self.assertEqual(len(spec['links']), 19)
        self.assertEqual(sum(n['role'] == 'switch' for n in spec['nodes']), 4)
        self.assertEqual(sum(n['name'].startswith('PC') for n in spec['nodes']), 12)
        self.assertLessEqual(sum(n['memory_mib'] for n in spec['nodes']) + spec['reserve_mib'], 2048)
        firewall = next(n for n in spec['nodes'] if n['name'] == 'FW1')
        self.assertEqual({r['destination'] for r in firewall['routes']}, {'10.10.10.0/24', '10.20.20.0/24'})
        self.assertEqual(validate(spec), spec)

    def test_static_routes_reject_unreachable_unknown_duplicate_and_connected(self):
        for edit in (lambda r: r.update(gateway='192.0.2.9'), lambda r: r.update(gateway='172.31.255.1'),
                     lambda r: r.update(destination='0.0.0.0/0'), lambda r: r.update(interface='eth9'),
                     lambda r: r.update(destination='198.51.100.0/24'), lambda r: r.update(destination='10.20.20.0/24')):
            spec = enterprise('/rootfs'); firewall = next(n for n in spec['nodes'] if n['name'] == 'FW1')
            edit(firewall['routes'][0])
            with self.assertRaises(ValueError):
                validate(spec)

    def test_cpu_normalization_and_memory_attribution(self):
        first = {'time': 10, 'lab_cgroup': {'memory_bytes': 10 * MIB, 'swap_bytes': 0, 'cpu_usage_usec': 1000000,
                                         'memory_events': {'oom_kill': 0}},
                 'runner_pss_bytes': 2 * MIB, 'runner_cpu_seconds': 1,
                 'host': {'cpu_ticks_total': 1000, 'cpu_ticks_busy': 100, 'memory_available_bytes': 50 * MIB}}
        last = copy.deepcopy(first); last['time'] = 12
        last['lab_cgroup'].update(memory_bytes=20 * MIB, cpu_usage_usec=2000000)
        last['host'].update(cpu_ticks_total=1800, cpu_ticks_busy=300)
        last['runner_cpu_seconds'] = 1.1
        report = summarize([first, last])
        self.assertEqual(report['lab_cgroup_cpu_percent_one_core'], 50)
        self.assertEqual(report['host_busy_percent_total_capacity'], 25)
        self.assertEqual(report['lab_cgroup_memory_sampled_peak_bytes'], 20 * MIB)
        self.assertEqual(report['lab_cgroup_memory_mean_bytes'], 15 * MIB)
        self.assertEqual(report['lab_memory_event_deltas']['oom_kill'], 0)
        self.assertNotIn('total_application_memory_bytes', report)

    def test_pss_parser_accepts_smaps_header(self):
        with tempfile.TemporaryDirectory() as folder:
            proc = Path(folder); (proc / 'self').mkdir()
            (proc / 'self' / 'smaps_rollup').write_text('000000-fffff ---p 00000000 00:00 0 [rollup]\nRss: 8192 kB\nPss: 4096 kB\n')
            manager = Manager('enterprise-20'); manager.state = {'spec': enterprise('/rootfs')}
            with patch('network_labs.appliances.benchmark.PROC_ROOT', proc), patch('network_labs.appliances.benchmark.group_snapshot', return_value={}), patch('network_labs.appliances.benchmark.host_snapshot', return_value={}):
                self.assertEqual(sample(manager)['runner_pss_bytes'], 4 * MIB)

    def test_missing_cgroup_data_is_error_instead_of_zero_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                group_snapshot(Path(folder))

    def test_kernel_peak_missing_is_unknown_but_corrupt_or_inaccessible_is_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.assertIsNone(kernel_memory_peak(root))
            (root/'memory.peak').write_text('12582912\n');self.assertEqual(kernel_memory_peak(root),12*MIB)
            for invalid in ('','max','-1','3.5'):
                (root/'memory.peak').write_text(invalid)
                with self.subTest(value=invalid),self.assertRaises(ValueError):kernel_memory_peak(root)
            with patch.object(Path,'read_text',side_effect=PermissionError('denied')),self.assertRaises(PermissionError):kernel_memory_peak(root)

    def test_existing_populated_parent_is_refused_and_empty_parent_keeps_history_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertFalse(cgroup_context(root/'new')['existed_before_start'])
            (root/'cgroup.events').write_text('populated 1\nfrozen 0\n')
            with self.assertRaisesRegex(RuntimeFailure,'populated'):cgroup_context(root)
            (root/'cgroup.events').write_text('populated 0\nfrozen 0\n')
            (root/'memory.peak').write_text('12345\n')
            context=cgroup_context(root);self.assertTrue(context['existed_before_start'])
            self.assertEqual(context['memory_peak_before_start_bytes'],12345)
            self.assertEqual(context['memory_peak_scope'],'cgroup-lifetime-including-prior-runs')

    def test_kernel_peak_assessment_stays_unknown_without_support_or_with_prior_history(self):
        for existed,peak,expected in ((False,None,None),(False,12*MIB,True),(True,12*MIB,None),(False,3*1024*MIB,False)):
            manager=MagicMock();manager.locked.return_value.__enter__.return_value=manager
            manager.directory.exists.side_effect=[False,True,False]
            manager.status.return_value={'nodes':[{'state':{'status':'running'}}]}
            metrics={'lab_cgroup_memory_sampled_peak_bytes':100,'host_available_min_bytes':1000}
            snapshot={'memory_peak_bytes':peak,'memory_events':{'oom_kill':0}}
            with self.subTest(existed=existed,peak=peak), \
                 patch('network_labs.appliances.benchmark.Manager',return_value=manager), \
                 patch('network_labs.appliances.benchmark.cgroup_context',return_value={'existed_before_start':existed}), \
                 patch('network_labs.appliances.benchmark.host_snapshot',return_value={'memory_available_bytes':1000}), \
                 patch('network_labs.appliances.benchmark.wait_ready'), \
                 patch('network_labs.appliances.benchmark.measure',return_value=metrics), \
                 patch('network_labs.appliances.benchmark.workload',return_value={'metrics':metrics,'all_packets_received':True}), \
                 patch('network_labs.appliances.benchmark.group_snapshot',return_value=snapshot):
                report=benchmark(enterprise('/rootfs'),target='198.51.100.10')
            self.assertEqual(report['assessment']['lab_cgroup_current_run_kernel_peak_under_target'],expected)
            if peak is None:self.assertIsNone(report['assessment']['lab_cgroup_lifetime_peak_under_target'])
            elif peak==3*1024*MIB:self.assertFalse(report['assessment']['lab_cgroup_lifetime_peak_under_target'])
            else:self.assertTrue(report['assessment']['lab_cgroup_lifetime_peak_under_target'])
            self.assertEqual(report['assessment']['total_application_under_target'],'unverified')

    def test_bad_workload_rejected_before_starting_lab(self):
        for kwargs in ({'target': '8.8.8.8'}, {'target': '198.51.100.10', 'seconds': 0},
                       {'target': '198.51.100.10', 'sources': ['PC1', 'PC1']},
                       {'target': '198.51.100.10', 'sources': ['FW1']}):
            with patch.object(Manager, 'start') as start, self.assertRaises(ValueError):
                benchmark(enterprise('/rootfs'), **kwargs)
            start.assert_not_called()

    def test_existing_lab_never_stopped_and_failure_cleans_up_owned_lab(self):
        manager = MagicMock()
        manager.locked.return_value.__enter__.return_value = manager
        manager.directory.exists.return_value = True
        with patch('network_labs.appliances.benchmark.Manager', return_value=manager), patch('network_labs.appliances.benchmark.host_snapshot', return_value={}):
            with self.assertRaisesRegex(RuntimeFailure, 'stopped lab'):
                benchmark(enterprise('/rootfs'), target='198.51.100.10')
            manager.start.assert_not_called(); manager.stop.assert_not_called()
            manager.directory.exists.side_effect = [False, True]
            with patch('network_labs.appliances.benchmark.wait_ready', side_effect=RuntimeFailure('failed readiness')):
                with self.assertRaisesRegex(RuntimeFailure, 'failed readiness'):
                    benchmark(enterprise('/rootfs'), target='198.51.100.10')
            manager.stop.assert_called_once()
