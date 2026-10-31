"""Peer-induced carrier loss with opt-in automatic dynamic FDB recovery."""
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


class STPLACPPathScenario:
    def exercise(self, control_loss=False, receiver=4, strict=False, thresholds=(1, 2)):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('busybox', 'crun', 'ip', 'bridge', 'tcpdump', *(['tc'] if control_loss else [])):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        self.assertTrue(Path('/sys/module/bonding').exists(), 'Preload bonding with max_bonds=0')
        print(('One-way control' if control_loss else 'Carrier') + ' test kernel: ' + run(['uname', '-r']).stdout.strip(), flush=True)
        baseline = {kind: run(['ip', '-j', '-4', kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for kind in ('route', 'rule')}
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        before = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder); rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs')
            for threshold in thresholds:
                with self.subTest(min_links=threshold):
                    spec = stp_lacp_lab(rootfs, threshold, True if strict else None); spec['name'] = ('control-' if control_loss else 'carrier-') + str(os.getpid()) + '-' + str(threshold)
                    manager = Manager(spec['name']); mutations = []; marker = '02:aa:bb:00:00:92'
                    def wait(predicate, label, seconds=40):
                        until = time.monotonic() + seconds
                        while time.monotonic() < until:
                            if predicate(): return
                            time.sleep(.2)
                        self.fail(label + ': ' + repr([manager.inspect(name) for name in ('SW1', 'SW2')]))
                    def control(spare, members):
                        left, right = manager.inspect('SW1'), manager.inspect('SW2')
                        if strict:
                            for actual in (left, right):
                                self.assertIs(actual['port_channels']['bond1']['lacp_strict'], True)
                        expected = [[actual['name'], actual['spanning_tree']['root_id'], actual['spanning_tree']['root_port'],
                                     sorted([[name, p['state']] for name, p in actual['spanning_tree']['ports'].items()])]
                                    for actual in (left, right)]
                        worker = left['stp_carrier_recovery']
                        return (worker['available'] and worker.get('paths') == [expected] and left['spanning_tree']['local_state_settled'] and right['spanning_tree']['local_state_settled'] and
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
                                 'Automatic carrier packet path failed for ' + source, 20)
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
                            self.assertTrue(all(d['reply_ttls'] == [64, 64] for d in result['directions']), result)
                        for future in futures: future.result(timeout=12)
                        decoded = [run(['tcpdump', '-nn', '-e', '-r', path]).stdout for path in paths]
                        active, inactive = (decoded[1], decoded[0]) if spare else decoded
                        for expected in ('vlan 10', 'vlan 20', 'ICMP echo request', 'ICMP echo reply'):
                            self.assertIn(expected, active, active)
                        self.assertNotIn('ICMP echo', inactive, inactive)
                    def peer(port, up):
                        if not control_loss:
                            manager.ns(5, 'ip', 'link', 'set', 'dev', port, 'up' if up else 'down')
                            return
                        # One receive direction only. Match Slow Protocol multicast (including
                        # LACP); IP/ARP/data and the reverse direction are untouched.
                        if up:
                            rows = json.loads(manager.ns(receiver, 'tc', '-j', '-s', 'filter', 'show', 'dev', port, 'ingress').stdout)
                            actions = [a for r in rows for a in r.get('options', {}).get('actions', [])]
                            self.assertTrue(any(a.get('stats', {}).get('drops', 0) > 0 for a in actions), rows)
                            manager.ns(receiver, 'tc', 'qdisc', 'del', 'dev', port, 'clsact')
                        else:
                            manager.ns(receiver, 'tc', 'qdisc', 'add', 'dev', port, 'clsact')
                            manager.ns(receiver, 'tc', 'filter', 'add', 'dev', port, 'ingress', 'protocol', '0x8809',
                                       'pref', '1', 'flower', 'skip_hw', 'dst_mac', '01:80:c2:00:00:02', 'action', 'drop')
                    def all_carriers_up():
                        for index in (4, 5):
                            for port in ('eth2', 'eth3'):
                                row = json.loads(manager.ns(index, 'ip', '-j', 'link', 'show', 'dev', port).stdout)[0]
                                self.assertTrue({'UP', 'LOWER_UP'}.issubset(row['flags']), row)
                                if control_loss:
                                    self.assertTrue(next(m for m in manager.inspect('SW1' if index == 4 else 'SW2')
                                                         ['port_channels']['bond1']['members'] if m['name'] == port)['mii_up'])
                    def local_carrier(port, up):
                        if control_loss:
                            all_carriers_up(); return
                        rows = json.loads(manager.ns(4, 'ip', '-j', 'link', 'show', 'dev', port).stdout)
                        self.assertIn('UP', rows[0]['flags'], 'Local member was administratively changed')
                        self.assertEqual('LOWER_UP' in rows[0]['flags'], up)
                    def markers():
                        for index in (4, 5):
                            rows = json.loads(manager.ns(index, 'bridge', '-j', 'fdb', 'show').stdout)
                            self.assertTrue(any(r['mac'] == marker for r in rows), rows)
                    try:
                        with manager.locked(): manager.start(spec)
                        from network_labs.appliances.snooping import alive
                        worker_record = copy.deepcopy(manager.state['stp_carrier_worker'])
                        saved_state = copy.deepcopy(manager.state['spec']); revision = manager.state['revision']
                        original_ns = manager.ns
                        def observed_ns(index, *args, **options):
                            if args[:3] == ('bridge', 'fdb', 'flush'): self.fail('Test helper must not repair FDB state; only the managed worker may do so')
                            if args[:2] == ('ip', 'link') and 'set' in args: mutations.append((index, args))
                            return original_ns(index, *args, **options)
                        with patch.object(manager, 'ns', side_effect=observed_ns):
                            wait(lambda: control(False, 2), 'Initial common tree/LACP not ready'); traffic()
                            qdiscs = {(i, p): json.loads(manager.ns(i, 'tc', '-j', 'qdisc', 'show', 'dev', p).stdout)
                                      for i in (4, 5) for p in ('eth2', 'eth3')} if control_loss else {}
                            for index in (4, 5): manager.ns(index, 'bridge', 'fdb', 'add', marker, 'dev', 'eth0', 'master', 'static', 'vlan', '10')
                            capture_path('initial', False)
                            for cycle in range(2):
                                peer('eth2', False); wait(lambda: control(threshold == 2, 1), 'One-member carrier threshold failed')
                                local_carrier('eth2', False); traffic()
                                if not control_loss:
                                    with manager.locked(), self.assertRaises(RuntimeFailure): manager.write_startup()
                                # External tc filters are not part of persisted policy.
                                # Do not claim save audits this injection.
                                # On this kernel min-links 1 can fall back to an
                                # individual carrier-up link without negotiated LACP.
                                # Reproduce that boundary rather than call it failover.
                                fallback = control_loss and threshold == 1 and not strict
                                peer('eth3', False); wait(lambda: control(not fallback, 0),
                                                         'Complete control/carrier loss selected unexpected path')
                                if fallback:
                                    for name in ('SW1', 'SW2'):
                                        bundle = manager.inspect(name)['port_channels']['bond1']
                                        self.assertTrue(bundle['carrier_without_ready_lacp'], bundle)
                                        self.assertFalse(bundle['ready'], bundle)
                                    print('min-links 1: reproduced carrier without negotiated LACP; spare not selected', flush=True)
                                local_carrier('eth3', False)
                                if not fallback:
                                    traffic()
                                    if cycle == 0: capture_path('spare', True)
                                peer('eth2', True); wait(lambda: control(threshold == 2, 1), 'Partial carrier return selected wrong path')
                                local_carrier('eth2', True); traffic()
                                peer('eth3', True); wait(lambda: control(False, 2), 'Full recovery did not restore bundle path')
                                if control_loss:
                                    all_carriers_up()
                                    for (i, p), expected in qdiscs.items():
                                        self.assertEqual(json.loads(manager.ns(i, 'tc', '-j', 'qdisc', 'show', 'dev', p).stdout), expected)
                                local_carrier('eth3', True); traffic(); markers()
                                if cycle == 0: capture_path('restored', False)
                                self.assertEqual(manager.state['spec'], saved_state); self.assertEqual(manager.state['revision'], revision)
                                self.assertEqual(manager.state['phase'], 'running'); self.assertNotIn('pending_spec', manager.state)
                            recovery = manager.inspect('SW1')['stp_carrier_recovery']
                            self.assertTrue(recovery['available'], recovery)
                            if not control_loss or threshold == 2 or strict:
                                self.assertGreaterEqual(recovery['repairs'], 2, recovery)
                                self.assertTrue(recovery['last_event']['complete'], recovery)
                                self.assertEqual(recovery['last_event']['bridges'], ['SW1', 'SW2'])
                            if control_loss: self.assertEqual(mutations, [], 'Control-loss test must never flap a link')
                            self.assertTrue(all(index == 5 and args in tuple(('ip', 'link', 'set', 'dev', port, state)
                                                for port in ('eth2', 'eth3') for state in ('up', 'down')) for index, args in mutations), mutations)
                        with manager.locked():
                            manager.write_startup(); saved = load_startup(spec['name']); self.assertEqual(saved, spec)
                            manager.stop(); self.assertFalse(alive(worker_record)); manager.start(saved)
                        wait(lambda: control(False, 2), 'Restored saved carrier policy not ready'); traffic()
                        for index in (4, 5):
                            rows = json.loads(manager.ns(index, 'bridge', '-j', 'fdb', 'show').stdout)
                            self.assertFalse(any(r['mac'] == marker for r in rows), 'Runtime static marker entered saved policy')
                        self.assertNotEqual(manager.state['stp_carrier_worker']['token'], worker_record['token'])
                        self.assertTrue(manager.inspect('SW1')['stp_carrier_recovery']['available'])
                        with manager.locked(): manager.write_startup()
                    finally:
                        if manager.directory.exists():
                            final_worker = copy.deepcopy(manager.state.get('stp_carrier_worker'))
                            with manager.locked(): manager.stop()
                            self.assertFalse(alive(final_worker))
        for kind, value in baseline.items():
            self.assertEqual(run(['ip', '-j', '-4', kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, value)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)
        after = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        hardware = {name for name, _ in after - before if (Path('/sys/class/net') / name / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before, after, hardware), {'removed_or_replaced': set(), 'added_virtual': set()})


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeSTPLACPCarrierTests(STPLACPPathScenario, unittest.TestCase):
    def test_peer_carrier_cycles_min_links_automatic_paths_and_saved_restart(self):
        self.exercise()
