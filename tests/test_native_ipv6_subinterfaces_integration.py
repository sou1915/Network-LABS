"""Actual IPv6 router-on-a-stick, static next hops and VLAN failure isolation."""
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
from network_labs.appliances.examples import ipv6_subinterfaces_lab
from network_labs.appliances.ipv6 import wait_addresses
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.show import show
from network_labs.appliances.verify import verify
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeIPv6SubinterfaceTests(unittest.TestCase):
    def test_roas_tags_static_routes_failure_isolation_drift_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('busybox', 'crun', 'ip', 'tcpdump'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        baseline = {kind: run(['ip', '-j', '-6', kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for kind in ('route', 'rule')}
        forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        before = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder); rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs')
            spec = ipv6_subinterfaces_lab(rootfs); spec['name'] = 'ipv6-roas-' + str(os.getpid())
            manager = Manager(spec['name']); router = spec['nodes'][5]
            def ping(target, source='PC1'):
                return manager.crun('exec', source, '/bin/busybox', 'ping6', '-c', '1', '-W', '1', '-w', '2', target,
                                    check=False, timeout=4)
            def healthy():
                for target in ('2001:db8:20::10', '2001:db8:30::10'):
                    deadline = time.monotonic() + 12
                    while ping(target).returncode:
                        if time.monotonic() >= deadline: self.fail('ROAS delivery unavailable: ' + repr(manager.inspect('R1')))
                        time.sleep(.1)
                for target, hops in (('PC2', 64), ('PC3', 63), ('PC4', 62)):
                    result = verify(manager, 'PC1', target, family='ipv6', count=2, bidirectional=True)
                    self.assertEqual(result['status'], 'passed', result)
                    self.assertTrue(all(d['reply_hop_limits'] == [hops, hops] for d in result['directions']), result)
            def refuse_save():
                with manager.locked(), self.assertRaises(RuntimeFailure): manager.write_startup()
            try:
                with manager.locked(): manager.start(spec)
                healthy()
                actual = manager.inspect('R1')
                self.assertEqual(set(actual['subinterfaces_ipv6']), set(router['subinterfaces']))
                self.assertTrue(all(v['encapsulation_verified'] for v in actual['subinterfaces_ipv6'].values()))
                self.assertEqual(actual['forwarding_ipv6'], '1'); self.assertFalse(actual['forwarding'])
                for query in ('show ipv6 interface brief', 'show ipv6 route', 'show ipv6 neighbors'):
                    self.assertEqual(show(manager, 'R1', query)['status'], 'observed')
                event = threading.Event(); path = root / 'roas.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'R1', 'eth0', path,
                                     seconds=8, packets=300, snaplen=512, ready=event.set)
                if not event.wait(5):
                    if future.done(): future.result()
                    self.fail('ROAS capture did not become ready')
                healthy(); self.assertGreater(future.result(timeout=15)['captured_packets'], 0)
                decoded = run(['tcpdump', '-nn', '-e', '-vv', '-r', path]).stdout
                for expected in ('vlan 10', 'vlan 20', 'vlan 100', 'ICMP6, echo request', 'ICMP6, echo reply'):
                    self.assertIn(expected, decoded)
                # Forwarding off preserves same-VLAN traffic.
                manager.ns(5, 'sysctl', '-w', 'net/ipv6/conf/all/forwarding=0')
                self.assertNotEqual(ping('2001:db8:20::10').returncode, 0)
                self.assertEqual(ping('2001:db8:10::20').returncode, 0); refuse_save()
                manager.ns(5, 'sysctl', '-w', 'net/ipv6/conf/all/forwarding=1'); healthy()
                # Prune one VLAN, retaining local L2 and the static transit.
                manager.ns(4, 'bridge', 'vlan', 'del', 'dev', 'eth3', 'vid', '20')
                self.assertNotEqual(ping('2001:db8:20::10').returncode, 0)
                self.assertEqual(ping('2001:db8:30::10').returncode, 0)
                self.assertEqual(ping('2001:db8:10::20').returncode, 0); refuse_save()
                manager.ns(4, 'bridge', 'vlan', 'add', 'dev', 'eth3', 'vid', '20'); healthy()
                # Peer-down is a carrier outage, distinct from local admin DOWN.
                manager.ns(4, 'ip', 'link', 'set', 'dev', 'eth3', 'down')
                self.assertNotEqual(ping('2001:db8:30::10').returncode, 0)
                self.assertEqual(ping('2001:db8:10::20').returncode, 0); refuse_save()
                manager.ns(4, 'ip', 'link', 'set', 'dev', 'eth3', 'up'); healthy()
                # External local admin DOWN may flush static IPv6 state. It
                # remains drift after UP; this profile restores via recreation,
                # never by injecting addresses/routes inside the ping helper.
                with manager.locked(): manager.write_startup()
                manager.ns(5, 'ip', 'link', 'set', 'dev', 'eth0', 'down')
                self.assertNotEqual(ping('2001:db8:30::10').returncode, 0)
                self.assertEqual(ping('2001:db8:10::20').returncode, 0); refuse_save()
                manager.ns(5, 'ip', 'link', 'set', 'dev', 'eth0', 'up')
                refuse_save()
                with manager.locked():
                    saved_before_fault = load_startup(spec['name'])
                    self.assertEqual(saved_before_fault, spec)
                    manager.stop(); manager.start(saved_before_fault)
                healthy()
                # Recreate the right name/address on the WRONG VID: only a link
                # encapsulation audit can distinguish this from declared state.
                def recreate(vid):
                    manager.ns(5, 'ip', 'link', 'del', 'dev', 'eth0.20')
                    manager.ns(5, 'ip', 'link', 'add', 'link', 'eth0', 'name', 'eth0.20', 'type', 'vlan', 'id', str(vid))
                    for key, value in {'disable_ipv6': 0, 'accept_ra': 0, 'autoconf': 0, 'forwarding': 1, 'accept_dad': 1}.items():
                        manager.ns(5, 'sysctl', '-w', 'net/ipv6/conf/eth0.20/' + key + '=' + str(value))
                    manager.ns(5, 'ip', '-6', 'addr', 'add', router['ipv6']['eth0.20'], 'dev', 'eth0.20')
                    manager.ns(5, 'ip', 'link', 'set', 'dev', 'eth0.20', 'up')
                    wait_addresses(manager, 5, router)
                recreate(99)
                self.assertFalse(manager.inspect('R1')['subinterfaces_ipv6']['eth0.20']['encapsulation_verified'])
                refuse_save(); recreate(20); healthy()
                manager.ns(5, 'ip', '-6', 'addr', 'add', '2001:db8:10::99/64', 'dev', 'eth0.10')
                refuse_save(); manager.ns(5, 'ip', '-6', 'addr', 'del', '2001:db8:10::99/64', 'dev', 'eth0.10')
                with manager.locked():
                    manager.write_startup(); saved = load_startup(spec['name']); self.assertEqual(saved, spec)
                    manager.stop(); manager.start(saved)
                healthy()
                with manager.locked(): manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        for kind, value in baseline.items():
            self.assertEqual(run(['ip', '-j', '-6', kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, value)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout, forwarding)
        after = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        hardware = {name for name, _ in after - before if (Path('/sys/class/net') / name / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before, after, hardware), {'removed_or_replaced': set(), 'added_virtual': set()})
