"""Opt-in real OCI boot/packet tests. The lab itself on real containers: packet capture from the CLI, persistence,
namespace isolation and cleanup.

Run as test_native_integration says (NETWORK_LABS_NATIVE_TESTS=1, on a disposable Linux host with sudo).
"""
import os
import json
import sys
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.spec import example, namespace

from test_native_integration import NATIVE, RealContainerCase


@unittest.skipUnless(NATIVE, 'Opt-in privileged native test')
class LabTests(RealContainerCase):
    def test_capture_real_icmp_concurrent_cli_deadline_invalid_filter_and_stop(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.capture import capture
        from network_labs.appliances.monitor import monitor as monitor_ports
        before = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links_before = host_links()
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = example(rootfs)
            spec['name'] = 'capture-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            try:
                with manager.locked():
                    manager.start(spec)
                    switch_before = manager.inspect('SW1')
                active = threading.Event()
                output = Path(folder) / 'icmp.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'SW1', 'eth0', output,
                                     seconds=8, packets=4, expression='icmp', ready=active.set)
                if not active.wait(5):
                    future.result(timeout=10)
                    self.fail('Capture readiness callback missing')
                # The real CLI must acquire the same lab lock while capture is
                # active. Holding it for recording would deadlock this command.
                ping = run([sys.executable, '-m', 'network_labs.appliances', 'exec', spec['name'], 'PC1', '--',
                            '/bin/ping', '-c', '2', '-i', '0.1', '-W', '1', '192.0.2.20'], timeout=4)
                self.assertIn('2 packets received', ping.stdout)
                report = future.result(timeout=10)
                self.assertEqual(report['captured_packets'], 4)
                self.assertEqual(report['stop_reason'], 'completed')
                self.assertEqual(report['linktype'], 1)
                decoded = run(['tcpdump', '-nn', '-r', str(output)]).stdout
                self.assertEqual(decoded.count('ICMP echo request'), 2)
                self.assertEqual(decoded.count('ICMP echo reply'), 2)
                self.assertIn('192.0.2.10', decoded)
                self.assertIn('192.0.2.20', decoded)
                with manager.locked():
                    switch_after = manager.inspect('SW1')
                    self.assertEqual(manager.state.get('revision', 0), 0)
                get_port = lambda data: next(r for r in data['links'] if r['ifname'] == 'eth0')
                self.assertEqual(get_port(switch_before)['promiscuity'], get_port(switch_after)['promiscuity'])
                sampled = threading.Event()
                monitoring = pool.submit(monitor_ports, spec['name'], 'PC1', 'eth0', seconds=2, ready=sampled.set)
                if not sampled.wait(5):
                    monitoring.result(timeout=5)
                    self.fail('Monitoring first sample missing')
                traffic = run([sys.executable, '-m', 'network_labs.appliances', 'exec', spec['name'], 'PC1', '--',
                               '/bin/ping', '-c', '2', '-i', '0.1', '-W', '1', '192.0.2.20'], timeout=4)
                self.assertIn('2 packets received', traffic.stdout)
                measured = monitoring.result(timeout=5)
                self.assertTrue(measured['second_observation_available'])
                self.assertTrue(measured['passive'])
                self.assertEqual(measured['packet_delivery'], 'not_tested')
                self.assertGreater(measured['elapsed_seconds'], 1.5)
                port = measured['ports'][0]
                self.assertEqual(port['status'], 'measured')
                for direction in ('rx', 'tx'):
                    self.assertGreaterEqual(port['delta'][direction + '_packets'], 2)
                    self.assertGreater(port['rates'][direction + '_bits_per_second'], 0)
                quiet = capture(Manager(spec['name']), 'PC1', 'eth0', Path(folder) / 'quiet.pcap',
                                seconds=1, expression='ether proto 0x88b5')
                self.assertEqual(quiet['captured_packets'], 0)
                self.assertEqual(quiet['bytes'], 24)
                self.assertEqual(quiet['stop_reason'], 'duration')
                with self.assertRaisesRegex(RuntimeFailure, 'Capture startup failed'):
                    capture(Manager(spec['name']), 'PC1', 'eth0', Path(folder) / 'bad-filter.pcap',
                            expression='not a valid filter ???')
                with manager.locked():
                    manager.configure_spanning_tree('SW1', {'mode': 'stp', 'hello_time': 1, 'max_age': 6, 'forward_delay': 4})
                bpdu_file = Path(folder) / 'bpdu.pcap'
                bpdu = capture(Manager(spec['name']), 'PC1', 'eth0', bpdu_file, seconds=3, packets=1,
                               expression='ether dst 01:80:c2:00:00:00')
                self.assertEqual(bpdu['captured_packets'], 1)
                self.assertIn('STP', run(['tcpdump', '-nn', '-r', str(bpdu_file)]).stdout)
                # The independent timeout must close capture even if the Python
                # CLI is killed. Record identities to avoid confusing PID reuse.
                from network_labs.appliances.runtime import process_identity
                import select
                orphan_file = Path(folder) / 'parent-killed.pcap'
                wrapper = subprocess.Popen([sys.executable, '-m', 'network_labs.appliances', 'capture', spec['name'],
                                            'PC1', 'eth0', '--seconds', '3', '--filter', 'ether proto 0x88b5',
                                            '--output', str(orphan_file)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           start_new_session=True, bufsize=0)
                try:
                    log = b''
                    deadline = time.monotonic() + 5
                    while b'Capture active' not in log and time.monotonic() < deadline:
                        if select.select([wrapper.stderr], [], [], 0.2)[0]:
                            part = os.read(wrapper.stderr.fileno(), 4096)
                            log += part
                            if not part:
                                break
                    self.assertIn(b'Capture active', log)
                    children = lambda pid: [int(p) for p in Path(f'/proc/{pid}/task/{pid}/children').read_text().split()]
                    monitor = children(wrapper.pid)
                    self.assertEqual(len(monitor), 1)
                    workers = monitor + children(monitor[0])
                    self.assertEqual(len(workers), 2)
                    identities = {pid: process_identity(pid) for pid in workers}
                    wrapper.kill()
                    wrapper.wait(timeout=2)
                    def alive(pid):
                        if process_identity(pid) != identities[pid]:
                            return False
                        try:
                            return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
                        except FileNotFoundError:
                            return False
                    deadline = time.monotonic() + 6
                    while any(alive(pid) for pid in workers) and time.monotonic() < deadline:
                        time.sleep(0.1)
                    self.assertFalse(any(alive(pid) for pid in workers), 'Capture worker outlived its independent deadline')
                    run(['tcpdump', '-nn', '-r', str(orphan_file)])
                finally:
                    if wrapper.poll() is None:
                        wrapper.kill()
                        wrapper.wait(timeout=2)
                    wrapper.stdout.close()
                    wrapper.stderr.close()
                active.clear()
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', Path(folder) / 'stop.pcap',
                                     seconds=2, expression='ether proto 0x88b5', ready=active.set)
                if not active.wait(5):
                    future.result(timeout=5)
                    self.fail('Capture readiness callback missing before stop')
                sampled.clear()
                monitoring = pool.submit(monitor_ports, spec['name'], 'PC1', 'eth0', seconds=2, ready=sampled.set)
                if not sampled.wait(5):
                    monitoring.result(timeout=5)
                    self.fail('Monitoring first sample missing before stop')
                run([sys.executable, '-m', 'network_labs.appliances', 'stop', spec['name']], timeout=5)
                try:
                    stopped = future.result(timeout=7)
                    self.assertEqual(stopped['captured_packets'], 0)
                except RuntimeFailure as error:
                    # libpcap may report the removed interface as an error;
                    # it must terminate rather than switch namespaces/devices.
                    self.assertIn('tcpdump failed', str(error))
                stopped_monitor = monitoring.result(timeout=5)
                self.assertFalse(stopped_monitor['second_observation_available'])
                self.assertIsNone(stopped_monitor['elapsed_seconds'])
                for port in stopped_monitor['ports']:
                    self.assertEqual(port['status'], 'observation_unavailable')
                    self.assertTrue(all(value is None for value in port['rates'].values()))
                self.assertFalse(manager.directory.exists())
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertEqual(host_links(), links_before)
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, before)

    def test_packets_persistence_namespace_isolation_and_cleanup(self):
        self.assertEqual(os.geteuid(), 0, 'Run this explicit test with sudo')
        for tool in ('crun', 'ip', 'busybox'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        before = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = example(rootfs)
            spec['name'] = 'integration-' + str(os.getpid())
            manager = Manager(spec['name'])
            with manager.locked():
                try:
                    manager.start(spec)
                    self.assertTrue(all(n['state']['status'] == 'running' for n in manager.status()['nodes']))
                    # Actual ICMP request/reply crosses two veth pairs and an in-namespace bridge.
                    self.assertEqual(manager.execute('PC1', ['/bin/ping', '-c', '2', '-W', '2', '192.0.2.20']), 0)
                    from network_labs.appliances.sntp_demo import demo
                    result = demo(manager, 'PC1', 'PC2', server_offset_seconds=45, samples=3)
                    self.assertEqual(result['status'], 'passed', result)
                    self.assertEqual(result['responder']['status'], 'responded')
                    self.assertEqual(len(result['probes']), 3)
                    self.assertAlmostEqual(result['probe']['stages'][-1]['offset_seconds'], 45, delta=1)
                    self.assertEqual(manager.ns(2, 'ss', '-H', '-lun', 'sport = :123').stdout.strip(), '')
                    self.assertEqual(manager.execute('PC1', ['/bin/sh', '-c', 'echo persistent > /root/marker']), 0)
                    value = manager.crun('exec', 'PC1', '/bin/cat', '/root/marker').stdout
                    self.assertEqual(value.strip(), 'persistent')
                    self.assertNotEqual(manager.crun('exec', 'PC2', '/bin/cat', '/root/marker', check=False).returncode, 0)
                    # A namespace-bound interface change affects the real packet path.
                    manager.ns(1, 'ip', 'link', 'set', 'eth1', 'down')
                    self.assertNotEqual(manager.execute('PC1', ['/bin/ping', '-c', '1', '-W', '1', '192.0.2.20']), 0)
                    manager.ns(1, 'ip', 'link', 'set', 'eth1', 'up')
                    self.assertEqual(manager.execute('PC1', ['/bin/ping', '-c', '1', '-W', '2', '192.0.2.20']), 0)
                    self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, before)
                finally:
                    if manager.directory.exists():
                        manager.stop()
            self.assertFalse(manager.directory.exists())
            namespaces = run(['ip', 'netns', 'list']).stdout
            self.assertTrue(all(namespace(spec, i) not in namespaces for i in range(3)))
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, before)


if __name__ == '__main__':
    unittest.main()
