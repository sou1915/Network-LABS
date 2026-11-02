"""Actual IPv6 SVI routing, tagged trunk, negative controls and saved restart."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.capture import capture
from network_labs.appliances.examples import ipv6_svi_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.show import show
from network_labs.appliances.verify import verify
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeIPv6SVITests(unittest.TestCase):
    def test_actual_svi_routing_trunk_forwarding_drift_capture_and_saved_restart(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('busybox', 'crun', 'ip', 'tcpdump'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        host_routes = run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout
        host_rules = run(['ip', '-j', '-6', 'rule', 'show']).stdout
        host_forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        host_links = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder)
            rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs')
            spec = ipv6_svi_lab(rootfs); spec['name'] = 'ipv6-svi-' + str(os.getpid())
            manager = Manager(spec['name'])
            def ping(source, target):
                return manager.crun('exec', source, '/bin/busybox', 'ping6', '-c', '1', '-W', '1', '-w', '2', target,
                                    check=False, timeout=4)
            def wait_delivery(source='PC1', target='2001:db8:20::20'):
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    if ping(source, target).returncode == 0: return
                    time.sleep(.1)
                self.fail('IPv6 SVI delivery unavailable: ' + repr(manager.inspect('SW1')))
            def healthy():
                wait_delivery(); wait_delivery('PC4', '2001:db8:10::10')
                routed = verify(manager, 'PC1', 'PC4', family='ipv6', count=2, bidirectional=True)
                self.assertEqual(routed['status'], 'passed', routed)
                self.assertTrue(all(d['reply_hop_limits'] == [63, 63] for d in routed['directions']), routed)
                local = verify(manager, 'PC1', 'PC2', family='ipv6', count=2, bidirectional=True)
                self.assertEqual(local['status'], 'passed', local)
                self.assertTrue(all(d['reply_hop_limits'] == [64, 64] for d in local['directions']), local)
            def refuse_save():
                with manager.locked(), self.assertRaises(RuntimeFailure): manager.write_startup()
            try:
                with manager.locked(): manager.start(spec)
                healthy()
                actual = manager.inspect('SW1')
                self.assertEqual(actual['forwarding_ipv6'], '1'); self.assertFalse(actual['forwarding'])
                self.assertEqual(set(actual['svis']), {'vlan10', 'vlan20'})
                self.assertTrue(all(s['encapsulation_verified'] for s in actual['svis'].values()))
                for query in ('show ipv6 interface brief', 'show ipv6 route', 'show ipv6 neighbors', 'show vlan brief'):
                    report = show(manager, 'SW1', query)
                    self.assertEqual(report['status'], 'observed', report)
                event = threading.Event(); path = root / 'ipv6-svi.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'SW1', 'eth2', path,
                                     seconds=8, packets=200, snaplen=512, ready=event.set)
                if not event.wait(5):
                    if future.done(): future.result()  # Preserve capture startup errors.
                    self.fail('Trunk capture did not become ready')
                healthy()
                self.assertGreater(future.result(timeout=15)['captured_packets'], 0)
                decoded = run(['tcpdump', '-nn', '-e', '-vv', '-r', path]).stdout
                for expected in ('vlan 10', 'vlan 20', 'ICMP6, echo request', 'ICMP6, echo reply'):
                    self.assertIn(expected, decoded)
                # Forwarding and L2 trunk membership are independent controls.
                manager.ns(4, 'sysctl', '-w', 'net/ipv6/conf/all/forwarding=0')
                self.assertNotEqual(ping('PC1', '2001:db8:20::20').returncode, 0)
                self.assertEqual(ping('PC1', '2001:db8:10::20').returncode, 0)
                refuse_save()
                manager.ns(4, 'sysctl', '-w', 'net/ipv6/conf/all/forwarding=1'); healthy()
                manager.ns(4, 'bridge', 'vlan', 'del', 'dev', 'eth2', 'vid', '20')
                self.assertNotEqual(ping('PC1', '2001:db8:20::20').returncode, 0)
                self.assertEqual(ping('PC1', '2001:db8:10::20').returncode, 0)
                self.assertEqual(ping('PC1', '2001:db8:20::10').returncode, 0)
                refuse_save()
                manager.ns(4, 'bridge', 'vlan', 'add', 'dev', 'eth2', 'vid', '20'); healthy()
                manager.ns(4, 'bridge', 'vlan', 'del', 'dev', 'br0', 'vid', '20', 'self')
                self.assertNotEqual(ping('PC1', '2001:db8:20::20').returncode, 0)
                refuse_save()
                manager.ns(4, 'bridge', 'vlan', 'add', 'dev', 'br0', 'vid', '20', 'self'); healthy()
                manager.ns(4, 'ip', '-6', 'addr', 'add', '2001:db8:10::99/64', 'dev', 'vlan10')
                refuse_save()
                manager.ns(4, 'ip', '-6', 'addr', 'del', '2001:db8:10::99/64', 'dev', 'vlan10')
                with manager.locked():
                    manager.write_startup(); saved = load_startup(spec['name'])
                    self.assertEqual(saved, spec)
                    manager.stop(); manager.start(saved)
                healthy()
                with manager.locked(): manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        self.assertEqual(run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout, host_routes)
        self.assertEqual(run(['ip', '-j', '-6', 'rule', 'show']).stdout, host_rules)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout, host_forwarding)
        after = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        hardware = {name for name, _ in after - host_links if (Path('/sys/class/net') / name / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(host_links, after, hardware), {'removed_or_replaced': set(), 'added_virtual': set()})
