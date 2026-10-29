"""Peer-induced carrier loss without managed edits or FDB reconciliation."""
from concurrent.futures import ThreadPoolExecutor
import copy
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
from network_labs.appliances.examples import stp_lacp_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.verify import verify
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeSTPLACPCarrierTests(unittest.TestCase):
    def test_peer_carrier_cycles_min_links_natural_paths_and_saved_restart(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('busybox', 'crun', 'ip', 'bridge', 'tcpdump'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        self.assertTrue(Path('/sys/module/bonding').exists(), 'Preload bonding with max_bonds=0')
        print('Carrier test kernel: ' + run(['uname', '-r']).stdout.strip(), flush=True)
        baseline = {kind: run(['ip', '-j', '-4', kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for kind in ('route', 'rule')}
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        before = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder); rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs')
            for threshold in (1, 2):
                with self.subTest(min_links=threshold):
                    spec = stp_lacp_lab(rootfs, threshold); spec['name'] = 'carrier-' + str(os.getpid()) + '-' + str(threshold)
                    manager = Manager(spec['name']); mutations = []; marker = '02:aa:bb:00:00:92'
                    def wait(predicate, label, seconds=40):
                        until = time.monotonic() + seconds
                        while time.monotonic() < until:
                            if predicate(): return
                            time.sleep(.2)
                        self.fail(label + ': ' + repr([manager.inspect(name) for name in ('SW1', 'SW2')]))
                    def control(spare, members):
                        left, right = manager.inspect('SW1'), manager.inspect('SW2')
                        return (left['spanning_tree']['local_state_settled'] and right['spanning_tree']['local_state_settled'] and
                                right['spanning_tree']['root_id'] == left['spanning_tree']['bridge_id'] and
                                right['spanning_tree']['root_port'] == ('eth4' if spare else 'bond1') and
                                right['spanning_tree']['ports']['eth4']['state'] == ('forwarding' if spare else 'blocking') and
                                all(len(actual['port_channels']['bond1']['negotiated_members']) == members and
                                    actual['port_channels']['bond1']['ready'] == (members >= threshold)
                                    for actual in (left, right)))
                    def traffic():
                        for source, target in (('PC1', '192.0.2.20'), ('PC3', '192.0.2.10'), ('PC2', '198.18.0.20'), ('PC4', '198.18.0.10')):
                            wait(lambda: manager.crun('exec', source, '/bin/busybox', 'ping', '-c', '1', '-W', '1', '-w', '2',
                                                     target, check=False, timeout=4).returncode == 0,
                                 'Natural carrier packet path failed for ' + source, 20)
                    def capture_path(label, spare):
                        # Warm both directions first, so unknown-unicast flooding
                        # is not mistaken for the selected steady-state path.
                        traffic(); events = [threading.Event(), threading.Event()]
                        paths = [root / f'{threshold}-{label}-{port}.pcap' for port in ('bond1', 'eth4')]
                        futures = [pool.submit(capture, Manager(spec['name']), 'SW1', port, path,
                                              seconds=6, packets=400, snaplen=512, ready=event.set)
                                   for port, path, event in zip(('bond1', 'eth4'), paths, events)]
                        for event, future in zip(events, futures):
                            if not event.wait(5):
                                if future.done(): future.result()
                                self.fail('Carrier-path capture did not become ready')
                        for source, target in (('PC1', 'PC3'), ('PC2', 'PC4')):
                            result = verify(manager, source, target, count=2, bidirectional=True)
                            self.assertEqual(result['status'], 'passed', result)
                            self.assertTrue(all(d['reply_hop_limits'] == [64, 64] for d in result['directions']), result)
                        for future in futures: future.result(timeout=12)
                        decoded = [run(['tcpdump', '-nn', '-e', '-r', path]).stdout for path in paths]
                        active, inactive = (decoded[1], decoded[0]) if spare else decoded
                        for expected in ('vlan 10', 'vlan 20', 'ICMP echo request', 'ICMP echo reply'):
                            self.assertIn(expected, active, active)
                        self.assertNotIn('ICMP echo', inactive, inactive)
                    def peer(port, up):
                        manager.ns(5, 'ip', 'link', 'set', 'dev', port, 'up' if up else 'down')
                    def local_carrier(port, up):
                        rows = json.loads(manager.ns(4, 'ip', '-j', 'link', 'show', 'dev', port).stdout)
                        self.assertIn('UP', rows[0]['flags'], 'Local member was administratively changed')
                        self.assertEqual('LOWER_UP' in rows[0]['flags'], up)
                    def markers():
                        for index in (4, 5):
                            rows = json.loads(manager.ns(index, 'bridge', '-j', 'fdb', 'show').stdout)
                            self.assertTrue(any(r['mac'] == marker for r in rows), rows)
                    try:
                        with manager.locked(): manager.start(spec)
                        saved_state = copy.deepcopy(manager.state['spec']); revision = manager.state['revision']
                        original_ns = manager.ns
                        def observed_ns(index, *args, **options):
                            if args[:3] == ('bridge', 'fdb', 'flush'): self.fail('Carrier test must not repair FDB state')
                            if args[:2] == ('ip', 'link') and 'set' in args: mutations.append((index, args))
                            return original_ns(index, *args, **options)
                        with patch.object(manager, 'ns', side_effect=observed_ns):
                            wait(lambda: control(False, 2), 'Initial common tree/LACP not ready'); traffic()
                            for index in (4, 5): manager.ns(index, 'bridge', 'fdb', 'add', marker, 'dev', 'eth0', 'master', 'static', 'vlan', '10')
                            capture_path('initial', False)
                            for cycle in range(2):
                                peer('eth2', False); wait(lambda: control(threshold == 2, 1), 'One-member carrier threshold failed')
                                local_carrier('eth2', False); traffic()
                                with manager.locked(), self.assertRaises(RuntimeFailure): manager.write_startup()
                                peer('eth3', False); wait(lambda: control(True, 0), 'Complete aggregate carrier loss did not select spare')
                                local_carrier('eth3', False); traffic()
                                if cycle == 0: capture_path('spare', True)
                                peer('eth2', True); wait(lambda: control(threshold == 2, 1), 'Partial carrier return selected wrong path')
                                local_carrier('eth2', True); traffic()
                                peer('eth3', True); wait(lambda: control(False, 2), 'Full carrier return did not restore bundle path')
                                local_carrier('eth3', True); traffic(); markers()
                                if cycle == 0: capture_path('restored', False)
                                self.assertEqual(manager.state['spec'], saved_state); self.assertEqual(manager.state['revision'], revision)
                                self.assertEqual(manager.state['phase'], 'running'); self.assertNotIn('pending_spec', manager.state)
                            self.assertTrue(all(index == 5 and args in tuple(('ip', 'link', 'set', 'dev', port, state)
                                                for port in ('eth2', 'eth3') for state in ('up', 'down')) for index, args in mutations), mutations)
                        with manager.locked():
                            manager.write_startup(); saved = load_startup(spec['name']); self.assertEqual(saved, spec)
                            manager.stop(); manager.start(saved)
                        wait(lambda: control(False, 2), 'Restored saved carrier policy not ready'); traffic()
                        for index in (4, 5):
                            rows = json.loads(manager.ns(index, 'bridge', '-j', 'fdb', 'show').stdout)
                            self.assertFalse(any(r['mac'] == marker for r in rows), 'Runtime static marker entered saved policy')
                        with manager.locked(): manager.write_startup()
                    finally:
                        if manager.directory.exists():
                            with manager.locked(): manager.stop()
        for kind, value in baseline.items():
            self.assertEqual(run(['ip', '-j', '-4', kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, value)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)
        after = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        hardware = {name for name, _ in after - before if (Path('/sys/class/net') / name / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before, after, hardware), {'removed_or_replaced': set(), 'added_virtual': set()})
