"""Opt-in real OCI boot/packet tests. Switching on real containers: RSTP (Open vSwitch), classic STP and its guards,
LACP, LLDP, IGMP snooping, a campus with live VLAN changes.

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
from unittest.mock import patch

from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.spec import namespace

from test_native_integration import NATIVE, RealContainerCase


@unittest.skipUnless(NATIVE, 'Opt-in privileged native test')
class SwitchingTests(RealContainerCase):
    def test_appliance_ovs_real_rstp_bpdus_failover_vlan_drift_and_restore(self):
        from network_labs.appliances.examples import rstp_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.ovs import vsctl
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        host_db = run(['ovs-vsctl', '--timeout=2', '--format=json', 'list', 'Bridge'], check=False).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', openvswitch=True)
            spec = rstp_lab(rootfs)
            spec['name'] = 'rstp-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def wait_tree(root_port='eth1', alternate=True):
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    actual = {name: manager.inspect(name)['spanning_tree'] for name in ('SW1', 'SW2', 'SW3')}
                    root = actual['SW1']['bridge_id']
                    if root and all(t['protocol'] == 'rstp' and t['root_id'] == root and
                                    len(t['ports']) == 3 and all(p['state'] in ('forwarding', 'discarding',
                                            'disabled') for p in t['ports'].values())
                        for t in actual.values()) and actual['SW3']['root_port'] == root_port and (not alternate or any(p['role']
                                == 'Alternate' and p['state'] == 'discarding' for t in actual.values() for p in t['ports'].values())):
                        return actual
                    time.sleep(0.2)
                self.fail('Actual OVS RSTP status did not settle: ' + repr(actual))
            def wait_ping():
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    result = manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '192.0.2.30', check=False)
                    if result.returncode == 0:
                        return
                    time.sleep(0.1)
                self.fail('RSTP-protected LAN did not deliver actual ICMP')
            try:
                with manager.locked():
                    manager.start(spec)
                    first = wait_tree()
                    wait_ping()
                    self.assertTrue(first['SW1']['is_root'])
                    self.assertFalse(first['SW3']['is_root'])
                    self.assertEqual(first['SW3']['root_port'], 'eth1')
                    self.assertTrue(any(p['role'] == 'Alternate' and p['state'] == 'discarding' for t in first.values()
                                        for p in t['ports'].values()))
                cap = capture(Manager(spec['name']), 'SW1', 'eth1', Path(folder) / 'rstp.pcap',
                              seconds=5, packets=1, expression='ether dst 01:80:c2:00:00:00')
                self.assertEqual(cap['captured_packets'], 1)
                decoded = run(['tcpdump', '-n', '-vv', '-r', Path(folder) / 'rstp.pcap']).stdout
                self.assertIn('802.1w', decoded)
                payload = (Path(folder) / 'rstp.pcap').read_bytes()[40:]
                self.assertEqual(payload[14:21], b'\x42\x42\x03\x00\x00\x02\x02')
                with manager.locked():
                    start = time.monotonic()
                    manager.ns(5, 'ip', 'link', 'set', 'eth1', 'down')
                    wait_ping()
                    elapsed = time.monotonic() - start
                    self.assertLess(elapsed, 15)
                    after = wait_tree('eth2', alternate=False)
                    self.assertEqual(after['SW3']['root_port'], 'eth2')
                    print('RSTP_FAILOVER_PING_OBSERVED_SECONDS=' + str(round(elapsed, 3)))
                    manager.ns(5, 'ip', 'link', 'set', 'eth1', 'up')
                    wait_tree()
                    wait_ping()
                    vsctl(manager, 'SW3', 'set', 'Port', 'eth0', 'tag=20')
                    deadline = time.monotonic() + 8
                    while True:
                        result = manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '192.0.2.30', check=False)
                        if result.returncode or time.monotonic() >= deadline:
                            break
                        time.sleep(0.1)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(manager.inspect('SW3')['ovs']['policy_verified'])
                    with self.assertRaisesRegex(RuntimeFailure, 'OVS'):
                        manager.write_startup()
                    vsctl(manager, 'SW3', 'set', 'Port', 'eth0', 'tag=10')
                    wait_ping()
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.crun('exec', 'SW3', '/bin/sh', '-c', '/bin/kill -KILL "$(/bin/cat /run/ovs/vswitchd.pid)"')
                    self.assertFalse(manager.inspect('SW3')['ovs']['controller_available'])
                    self.assertEqual(manager.inspect('SW3')['spanning_tree']['protocol'], 'unavailable')
                    with self.assertRaisesRegex(RuntimeFailure, 'OVS'):
                        manager.write_startup()
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    restored = wait_tree()
                    wait_ping()
                    self.assertTrue(restored['SW1']['is_root'])
                    self.assertTrue(all(manager.inspect(n)['ovs']['policy_verified'] for n in ('SW1', 'SW2', 'SW3')))
            except BaseException:
                for node in ('SW1', 'SW2', 'SW3'):
                    path = manager.directory / node / 'ovs.log'
                    if path.exists():
                        print(node + ' OVS LOG:\n' + path.read_text(errors='replace')[-5000:])
                raise
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), host_rules)
        self.assertEqual(run(['ovs-vsctl', '--timeout=2', '--format=json', 'list', 'Bridge'], check=False).stdout, host_db)

    def test_appliance_lldp_real_neighbors_pcap_link_loss_daemon_loss_policy_drift_and_restore(self):
        from network_labs.appliances.examples import lldp_lab
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.capture import capture
        self.assertIsNotNone(shutil.which('lldpd'))
        self.assertIsNotNone(shutil.which('lldpcli'))
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                                          lldpd=shutil.which('lldpd'), lldpcli=shutil.which('lldpcli'))
            spec = lldp_lab(rootfs)
            spec['name'] = 'lldp-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def strings(value):
                if isinstance(value, str):
                    return [value]
                if isinstance(value, dict):
                    return [v for item in value.values() for v in strings(item)]
                if isinstance(value, list):
                    return [v for item in value for v in strings(item)]
                return []
            def peers(equipment):
                # Only the received lldpcli output, never topology links.
                received = manager.inspect(equipment)['lldp']['neighbors']
                self.assertIsNotNone(received)
                return set(strings(received)) & {'PC1', 'PC2', 'SW1', 'SW2'}
            def wait_peers(expected):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    actual = {node: peers(node) for node in expected}
                    if actual == expected:
                        return
                    time.sleep(0.2)
                self.fail('Received LLDP neighbors did not converge: ' + repr(actual))
            def ping(check=True):
                return manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '192.0.2.20', check=check)
            expected = {'PC1': {'SW1'}, 'PC2': {'SW2'}, 'SW1': {'PC1', 'SW2'}, 'SW2': {'PC2', 'SW1'}}
            try:
                with manager.locked():
                    manager.start(spec)
                    wait_peers(expected)
                    ping()
                    for name in expected:
                        self.assertTrue(manager.inspect(name)['lldp']['policy_verified'])
                # Bounded real LLDP capture with offline tcpdump decoding.
                cap = capture(Manager(spec['name']), 'PC1', 'eth0', Path(folder) / 'lldp.pcap',
                              seconds=5, packets=1, expression='ether proto 0x88cc')
                self.assertEqual(cap['captured_packets'], 1)
                decoded = run(['tcpdump', '-n', '-vv', '-r', Path(folder) / 'lldp.pcap']).stdout
                self.assertIn('LLDP', decoded)
                self.assertTrue('SW1' in decoded or 'PC1' in decoded, decoded)
                with manager.locked():
                    manager.ns(2, 'ip', 'link', 'set', 'eth1', 'down')
                    wait_peers({'SW1': {'PC1'}, 'SW2': {'PC2'}})
                    self.assertNotEqual(ping(check=False).returncode, 0)
                    manager.ns(2, 'ip', 'link', 'set', 'eth1', 'up')
                    wait_peers(expected)
                    ping()
                    # Real control CLI edits are visible and cannot silently
                    # become saved declarative policy.
                    manager.crun('exec', 'SW1', '/usr/sbin/lldpcli', 'configure', 'lldp', 'tx-interval', '7')
                    self.assertFalse(manager.inspect('SW1')['lldp']['policy_verified'])
                    with self.assertRaisesRegex(RuntimeFailure, 'LLDP'):
                        manager.write_startup()
                    manager.crun('exec', 'SW1', '/usr/sbin/lldpcli', 'configure', 'lldp', 'tx-interval', '2')
                    manager.crun('exec', 'SW1', '/usr/sbin/lldpcli', 'configure', 'ports', 'eth0', 'lldp', 'status', 'disabled')
                    self.assertFalse(manager.inspect('SW1')['lldp']['policy_verified'])
                    manager.crun('exec', 'SW1', '/usr/sbin/lldpcli', 'configure', 'ports', 'eth0', 'lldp', 'status', 'rx-and-tx')
                    wait_peers(expected)
                    self.assertTrue(manager.inspect('SW1')['lldp']['policy_verified'])
                    path = manager.directory / 'SW1/files/lldpd.conf'
                    original = path.read_text()
                    try:
                        path.write_text(original + '# drift\n')
                        with self.assertRaisesRegex(RuntimeFailure, 'LLDP'):
                            manager.write_startup()
                    finally:
                        path.write_text(original)
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.crun('exec', 'SW2', '/bin/busybox', 'killall', '-9', 'lldpd')
                    wait_peers({'SW1': {'PC1'}})  # Actual advertised TTL expiry.
                    self.assertIsNone(manager.inspect('SW2')['lldp']['neighbors'])
                    self.assertEqual(manager.inspect('SW2')['lldp']['neighbor_summary']['status'], 'unknown')
                    self.assertFalse(manager.inspect('SW2')['lldp']['policy_verified'])
                    ping()  # Linux bridging is independent of the LLDP daemon.
                    with self.assertRaisesRegex(RuntimeFailure, 'LLDP'):
                        manager.write_startup()
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    wait_peers(expected)
                    ping()
                    for name in expected:
                        self.assertTrue(manager.inspect(name)['lldp']['policy_verified'])
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), host_rules)

    def test_multicast_real_igmp_membership_forwarding_router_flood_leave_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import copy
        import threading
        from network_labs.appliances.capture import capture
        from network_labs.appliances.examples import multicast_lab
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.multicast_probe import probe
        from network_labs.appliances.persistence import load_startup
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        group = '239.10.10.10'
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = multicast_lab(rootfs)
            spec['name'] = 'mcast-test-' + str(os.getpid())
            spec['nodes'][0]['multicast']['ports']['eth1']['fast_leave'] = True  # One host, not an uplink.
            spec['nodes'][0]['multicast']['querier'] = False
            manager = Manager(spec['name'])
            receiver = None
            def walk(value):
                if isinstance(value, dict):
                    yield value
                    for child in value.values():
                        yield from walk(child)
                elif isinstance(value, list):
                    for child in value:
                        yield from walk(child)
            def has_member():
                return any(r.get('grp') == group and r.get('port') == 'eth1' for r in walk(manager.inspect('SW1')['multicast']['mdb']))
            def membership(expected):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with manager.locked():
                        if has_member() is expected:
                            return
                    time.sleep(0.1)
                self.fail('Actual MDB membership mismatch: ' + json.dumps(manager.inspect('SW1')))
            def receive(seconds):
                ready = threading.Event()
                future = pool.submit(probe, Manager(spec['name']), 'RX1', group=group, seconds=seconds, ready=ready.set)
                if not ready.wait(5):
                    future.result(timeout=5)
                    self.fail('Multicast socket readiness missing')
                return future
            def send(selected=group):
                return probe(Manager(spec['name']), 'TX1', group=selected, text='Network LABS multicast', count=3)
            def captured(filename, selected=group, count=100):
                ready = threading.Event()
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', Path(folder) / filename,
                                     seconds=2, packets=count, expression='udp and dst host ' + selected + ' and dst port 5000',
                    ready=ready.set)
                if not ready.wait(5):
                    future.result(timeout=5)
                    self.fail('Multicast PCAP readiness missing')
                self.assertEqual(send(selected)['sent_packets'], 3)
                return future.result(timeout=6)['captured_packets']
            try:
                with manager.locked():
                    manager.start(spec)
                    observed = manager.inspect('SW1')['multicast']
                    self.assertTrue(observed['policy_verified'], json.dumps(observed))
                    manager.ns(2, 'sysctl', '-w', 'net.ipv4.conf.eth0.force_igmp_version=2')
                query_ready = threading.Event()
                queries = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', Path(folder) / 'queries.pcap',
                                      seconds=3, packets=1, expression='igmp and igmp[0] = 0x11', ready=query_ready.set)
                if not query_ready.wait(5):
                    queries.result(timeout=5)
                    self.fail('IGMP query capture readiness missing')
                with manager.locked():
                    manager.configure_ios('SW1', 'conf t\nip igmp snooping querier\nend')
                    policy = copy.deepcopy(manager.state['spec']['nodes'][0]['multicast'])
                self.assertEqual(queries.result(timeout=6)['captured_packets'], 1, json.dumps(manager.inspect('SW1')['multicast']))
                receiver = receive(30)
                membership(True)
                # The Linux querier's initial other-querier delay is its query
                # response interval. Let the actual default 10 s elapse before
                # asserting selective forwarding; no accelerated fake timers.
                with manager.locked():
                    observed = manager.inspect('SW1')['multicast']['bridge']
                    response = observed['mcast_query_response_intvl'] / os.sysconf('SC_CLK_TCK')
                    self.assertLessEqual(response, 12)
                time.sleep(response + 0.5)
                self.assertEqual(captured('member-only.pcap'), 0)  # PC1 never joined; flood=True.
                # Router ports deliberately receive known multicast even
                # without a local listener; test the actual egress behaviour.
                router = copy.deepcopy(policy)
                router['ports']['eth2']['router'] = 'permanent'
                with manager.locked():
                    manager.configure_multicast('SW1', router)
                self.assertGreater(captured('router.pcap', count=1), 0)
                # Explicit off removes router forwarding immediately; auto
                # may legitimately retain recently detected router state.
                policy['ports']['eth2']['router'] = 'off'
                with manager.locked():
                    manager.configure_multicast('SW1', policy)
                # With an active querier, unknown non-link-local IPv4
                # multicast follows mrouter-only forwarding, not a promise
                # that flood=True forces delivery to every nonmember.
                unknown = '239.10.10.99'
                self.assertEqual(captured('unknown-querier.pcap', unknown), 0)
                with manager.locked():
                    manager.write_startup()  # Dynamic MDB is not startup policy drift.
                result = receiver.result(timeout=32)
                self.assertGreater(result['received_packets'], 0)
                self.assertTrue(any(s['source'] == '192.0.2.10' for s in result['samples']))
                receiver = None
                membership(False)  # Closing membership socket causes real IGMP leave.
                self.assertEqual(captured('after-leave.pcap'), 0)  # No member/router on PC1.
                with manager.locked():
                    manager.configure_ios('SW1', 'conf t\nno ip igmp snooping querier\nno ip igmp snooping\nend')
                    observed = manager.inspect('SW1')['multicast']
                    self.assertTrue(observed['policy_verified'], json.dumps(observed))
                # In flooding mode, the per-port unknown multicast flag is
                # exercised with positive and negative actual captures.
                self.assertGreater(captured('unknown-flood.pcap', unknown, 1), 0)
                restricted = copy.deepcopy(policy)
                restricted.update(snooping=False, querier=False)
                restricted['ports']['eth2']['flood'] = False
                with manager.locked():
                    manager.configure_multicast('SW1', restricted)
                self.assertEqual(captured('unknown-deny.pcap', unknown), 0)
                with manager.locked():
                    manager.configure_multicast('SW1', policy)
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.ns(0, 'ip', 'link', 'set', 'dev', 'br0', 'type', 'bridge', 'mcast_querier', '0')
                    with self.assertRaisesRegex(RuntimeFailure, 'multicast'):
                        manager.write_startup()
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    observed = manager.inspect('SW1')['multicast']
                    self.assertTrue(observed['policy_verified'], json.dumps(observed))
                    self.assertFalse(has_member())  # Memberships were not snapshotted.
                    manager.ns(2, 'sysctl', '-w', 'net.ipv4.conf.eth0.force_igmp_version=2')
                receiver = receive(2)
                membership(True)
                send()
                self.assertGreater(receiver.result(timeout=5)['received_packets'], 0)
                receiver = None
                # Stop can acquire the lock while a bounded receiver is alive;
                # a pinned namespace never falls back to the host namespace.
                receiver = receive(2)
                with manager.locked():
                    manager.stop()
                self.assertEqual(receiver.result(timeout=5)['received_packets'], 0)
                receiver = None
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
                if receiver is not None:
                    receiver.result(timeout=35)
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), host_rules)

    def test_lacp_negotiation_vlan_trunk_failover_minlinks_and_restore(self):
        from network_labs.appliances.diagnostics import explain
        from network_labs.appliances.examples import lacp_lab
        from network_labs.appliances.persistence import load_startup
        spec_name = 'lacp-test-' + str(os.getpid())
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        before = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = lacp_lab(rootfs)
            spec['name'] = spec_name
            manager = Manager(spec_name)
            def ping(vlan):
                source, target = ('PC1', '192.0.2.20') if vlan == 10 else ('PC2', '198.18.0.20')
                return manager.crun('exec', source, '/bin/ping', '-c', '1', '-W', '1', target, check=False).returncode == 0
            def apply(node, text):
                return manager.configure_ios(node, 'conf t\n' + text + '\nend')
            def wait_members(count, ready=True, nodes=('SW1', 'SW2')):
                deadline = time.monotonic() + 20
                while True:
                    state = {n: manager.inspect(n)['port_channels']['bond1'] for n in nodes}
                    if all(len(s['negotiated_members']) == count and s['ready'] == ready for s in state.values()):
                        return
                    if time.monotonic() >= deadline:
                        self.fail('LACP state did not converge: ' + json.dumps(state))
                    time.sleep(0.2)
            with manager.locked():
                try:
                    manager.start(spec)
                    wait_members(2)
                    findings = explain(manager, 'SW1')['nodes'][0]['findings']
                    self.assertIn('LACP_READY', {f['code'] for f in findings})
                    audit, = explain(manager)['link_checks']
                    self.assertEqual(audit['status'], 'compatible', audit)
                    self.assertEqual(len(audit['declared_physical_links']), 2)
                    self.assertTrue(ping(10))
                    self.assertTrue(ping(20))
                    # Active/passive was negotiated; now exercise active/active.
                    apply('SW2', 'interface fa0/3\nchannel-group 1 mode active')
                    wait_members(2)
                    manager.write_startup()
                    apply('SW1', 'interface port-channel1\nswitchport trunk allowed vlan 10')
                    self.assertTrue(ping(10))
                    self.assertFalse(ping(20))
                    audit, = explain(manager)['link_checks']
                    self.assertEqual(audit['status'], 'attention', audit)
                    mismatch, = [f for f in audit['findings'] if f['code'] == 'VLAN_TAGGED_NOT_ADMITTED']
                    self.assertEqual(mismatch['evidence']['vlans'], [20])
                    self.assertEqual(mismatch['evidence']['direction'], 'SW2/bond1 → SW1/bond1')
                    apply('SW1', 'interface po1\nswitchport trunk allowed vlan 10,20')
                    self.assertTrue(ping(20))
                    self.assertEqual(explain(manager)['link_checks'][0]['status'], 'compatible')
                    counters = [f['evidence'] for f in explain(manager, 'SW1')['nodes'][0]['findings'] if f['code'] == 'PORT_COUNTERS']
                    bond = next(c for c in counters if c['port'] == 'bond1')
                    self.assertGreater(bond['counters']['rx_packets'], 0)
                    self.assertGreater(bond['counters']['tx_packets'], 0)
                    self.assertTrue(bond['cumulative'])
                    # Same VID list can still fail when one side sends untagged
                    # frames and its peer has no ingress PVID.
                    apply('SW1', 'interface po1\nswitchport trunk native vlan 20')
                    self.assertTrue(ping(10))
                    self.assertFalse(ping(20))
                    audit, = explain(manager)['link_checks']
                    self.assertIn('VLAN_UNTAGGED_NO_PVID', {f['code'] for f in audit['findings']})
                    apply('SW2', 'interface po1\nswitchport trunk native vlan 20')
                    self.assertTrue(ping(20))
                    self.assertEqual(explain(manager)['link_checks'][0]['status'], 'compatible')
                    apply('SW2', 'interface po1\nswitchport trunk native vlan 10')
                    self.assertFalse(ping(20))
                    audit, = explain(manager)['link_checks']
                    self.assertIn('VLAN_UNTAGGED_RECLASSIFIED', {f['code'] for f in audit['findings']})
                    for switch in ('SW1', 'SW2'):
                        apply(switch, 'interface po1\nswitchport trunk native vlan 1')
                    self.assertTrue(ping(10))
                    self.assertTrue(ping(20))
                    # A surviving negotiated member carries both VLANs.
                    apply('SW1', 'interface fa0/3\nshutdown')
                    wait_members(1)
                    self.assertIn('LACP_DEGRADED', {f['code'] for f in explain(manager, 'SW1')['nodes'][0]['findings']})
                    self.assertTrue(ping(10))
                    self.assertTrue(ping(20))
                    # The threshold is a real kernel carrier gate, not a fake ping rule.
                    apply('SW1', 'interface po1\nport-channel min-links 2')
                    wait_members(1, ready=False, nodes=('SW1',))
                    self.assertIn('LACP_NOT_READY', {f['code'] for f in explain(manager, 'SW1')['nodes'][0]['findings']})
                    self.assertFalse(ping(10))
                    apply('SW1', 'interface po1\nno port-channel min-links')
                    wait_members(1)
                    self.assertTrue(ping(10))
                    apply('SW1', 'interface fa0/4\nshutdown')
                    self.assertFalse(ping(10))
                    self.assertFalse(ping(20))
                    apply('SW1', 'interface fa0/3\nno shutdown')
                    wait_members(1)
                    self.assertTrue(ping(10))
                    apply('SW1', 'interface fa0/4\nno shutdown')
                    wait_members(2)
                    # Unsupported commands are rejected before changing Linux.
                    with self.assertRaises(ValueError):
                        apply('SW1', 'interface po1\nport-channel min-links 3')
                    self.assertTrue(ping(20))
                    manager.write_startup()
                    manager.ns(4, 'ip', 'link', 'set', 'dev', 'bond1', 'type', 'bond', 'miimon', '200')
                    with self.assertRaisesRegex(RuntimeFailure, 'bonding configuration differs'):
                        manager.write_startup()
                    manager.stop()
                    manager.start(load_startup(spec_name))
                    wait_members(2)
                    self.assertTrue(ping(10))
                    self.assertTrue(ping(20))
                except BaseException:
                    if manager.directory.exists():
                        print('LACP diagnostics:', manager.inspect('SW1'), manager.inspect('SW2'), file=sys.stderr)
                    raise
                finally:
                    if manager.directory.exists():
                        manager.stop()
        self.assertEqual(host_links(), before)
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)

    def test_classic_stp_triangle_election_failover_priority_cost_and_saved_restore(self):
        from network_labs.appliances.examples import stp_lab
        from network_labs.appliances.persistence import load_startup
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        before = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = stp_lab(rootfs)
            spec['name'] = 'stp-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def snapshot():
                return {n: manager.inspect(n)['spanning_tree'] for n in ('SW1', 'SW2', 'SW3')}
            def wait_tree(root, blocked=1):
                deadline = time.monotonic() + 30
                while True:
                    state = snapshot()
                    root_id = state[root]['bridge_id']
                    states = [s['ports'][p]['state'] for s in state.values() for p in ('eth2', 'eth3')]
                    if (state[root]['is_root'] and all(s['root_id'] == root_id and s['local_state_settled'] for s in state.values())
                            and states.count('blocking') == blocked and states.count('forwarding') == (5 if blocked else 4)):
                        return state
                    if time.monotonic() >= deadline:
                        self.fail('Classic STP did not converge: ' + json.dumps(state))
                    time.sleep(0.2)
            last_probe = []
            def ping(source, target):
                deadline = time.monotonic() + 10
                while True:
                    probe = manager.crun('exec', source, '/bin/ping', '-c', '1', '-W', '1', target, check=False)
                    last_probe[:] = [source, target, probe.returncode, probe.stdout, probe.stderr]
                    if probe.returncode == 0:
                        return True
                    if time.monotonic() >= deadline:
                        return False
                    time.sleep(0.1)
            def apply(node, commands):
                return manager.configure_ios(node, 'conf t\n' + commands + '\nend')
            with manager.locked():
                try:
                    manager.start(spec)
                    tree = wait_tree('SW1')
                    self.assertEqual(tree['SW3']['ports']['eth3']['state'], 'blocking')
                    from network_labs.appliances.show import show, render as render_show
                    before_show = json.dumps(manager.read(), sort_keys=True)
                    stp_show = show(manager, 'SW3', 'show spanning-tree')
                    self.assertEqual(stp_show['status'], 'observed', stp_show)
                    self.assertEqual(stp_show['observation']['tree']['root_id'], tree['SW1']['bridge_id'])
                    self.assertIn('blocking', render_show(stp_show))
                    self.assertEqual(json.dumps(manager.read(), sort_keys=True), before_show)
                    self.assertTrue(ping('PC1', '192.0.2.30'))
                    self.assertTrue(ping('PC2', '198.18.0.30'))
                    # Cutting the direct root link unblocks the alternate path through SW2.
                    apply('SW1', 'interface fa0/4\nshutdown')
                    tree = wait_tree('SW1', blocked=0)
                    self.assertEqual(tree['SW3']['root_port'], 'eth3')
                    stp_show = show(manager, 'SW3', 'show spanning-tree')
                    self.assertEqual(stp_show['status'], 'observed', stp_show)
                    self.assertEqual(stp_show['observation']['tree']['root_port'], 'eth3')
                    self.assertTrue(ping('PC1', '192.0.2.30'))
                    self.assertTrue(ping('PC2', '198.18.0.30'))
                    apply('SW1', 'interface fa0/4\nno shutdown')
                    wait_tree('SW1')
                    manager.configure_spanning_tree('SW3', priority=0)
                    wait_tree('SW3')
                    self.assertTrue(ping('PC3', '192.0.2.30'))
                    sw2_index = next(i for i, n in enumerate(spec['nodes']) if n['name'] == 'SW2')
                    marker = '02:aa:bb:cc:dd:ee'
                    manager.ns(sw2_index, 'bridge', 'fdb', 'add', marker, 'dev', 'eth0', 'master', 'static', 'vlan', '10')
                    apply('SW2', 'interface fa0/4\nspanning-tree cost 1000\ninterface fa0/3\nspanning-tree port-priority 64')
                    self.assertTrue(any(f['mac'] == marker for f in manager.inspect('SW2')['fdb']))
                    manager.ns(sw2_index, 'bridge', 'fdb', 'del', marker, 'dev', 'eth0', 'master', 'vlan', '10')
                    tree = wait_tree('SW3')
                    self.assertEqual(tree['SW2']['root_port'], 'eth2')
                    self.assertEqual(tree['SW2']['root_path_cost'], 200)
                    self.assertEqual(tree['SW2']['ports']['eth2']['priority'], 64)
                    self.assertTrue(ping('PC3', '192.0.2.30'))
                    self.assertTrue(ping('PC4', '198.18.0.30'))
                    revision = manager.state['revision']
                    with self.assertRaises(ValueError):
                        manager.configure_spanning_tree('SW1', {'mode': 'off'})
                    self.assertEqual(manager.state['revision'], revision)
                    manager.write_startup()
                    index = next(i for i, n in enumerate(spec['nodes']) if n['name'] == 'SW3')
                    manager.ns(index, 'ip', 'link', 'set', 'dev', 'br0', 'type', 'bridge', 'priority', '16384')
                    with self.assertRaisesRegex(RuntimeFailure, 'spanning-tree bridge parameters differ'):
                        manager.write_startup()
                    manager.stop()
                    manager.start(load_startup(spec['name']))
                    tree = wait_tree('SW3')
                    self.assertEqual(tree['SW2']['root_port'], 'eth2')
                    self.assertTrue(ping('PC1', '192.0.2.30'))
                    self.assertTrue(ping('PC2', '198.18.0.30'))
                except BaseException:
                    if manager.directory.exists():
                        print('STP diagnostics:', last_probe, {n: manager.inspect(n) for n in ('SW1', 'SW2', 'SW3')}, file=sys.stderr)
                    raise
                finally:
                    if manager.directory.exists():
                        manager.stop()
        self.assertEqual(host_links(), before)
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)

    def test_stp_root_and_bpdu_guards_block_real_traffic_and_recover(self):
        from network_labs.appliances.diagnostics import explain
        from network_labs.appliances.examples import stp_lab
        from network_labs.appliances.persistence import load_startup
        before = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = stp_lab(rootfs)
            spec['name'] = 'guard-test-' + str(os.getpid())
            sw3 = next(n for n in spec['nodes'] if n['name'] == 'SW3')
            for p in ('eth2', 'eth3'):
                sw3['spanning_tree']['ports'][p]['root_guard'] = True
            manager = Manager(spec['name'])
            def tree():
                return manager.inspect('SW3')['spanning_tree']
            def wait(predicate):
                deadline = time.monotonic() + 30
                while True:
                    state = tree()
                    if predicate(state):
                        return state
                    if time.monotonic() >= deadline:
                        self.fail('Protection did not settle: ' + json.dumps(state))
                    time.sleep(0.2)
            def probe(source, target):
                return manager.crun('exec', source, '/bin/ping', '-c', '1', '-W', '1', target, check=False).returncode == 0
            def connected():
                deadline = time.monotonic() + 15
                while not (probe('PC1', '192.0.2.30') and probe('PC2', '198.18.0.30')):
                    if time.monotonic() >= deadline:
                        self.fail('Packets did not recover after removing protection')
                    time.sleep(0.2)
            def both(commands):
                return manager.configure_ios('SW3', 'conf t\ninterface fa0/3\n' + commands + '\ninterface fa0/4\n' + commands + '\nend')
            with manager.locked():
                try:
                    manager.start(spec)
                    wait(lambda t: t['is_root'] and all(t['ports'][p]['state'] in ('listening',
                            'blocking') and t['ports'][p]['root_guard'] for p in ('eth2', 'eth3'))
                         and all(t['ports'][p]['state'] == 'forwarding' for p in ('eth0', 'eth1')))
                    # Repeated superior BPDUs hold Linux root-protected ports
                    # in listening, rearming forward_delay. Verify data remains
                    # blocked beyond that delay, not just during startup.
                    time.sleep(5)
                    self.assertTrue(tree()['is_root'])
                    self.assertTrue(all(tree()['ports'][p]['state'] in ('listening', 'blocking') for p in ('eth2', 'eth3')))
                    report = explain(manager, 'SW3')
                    self.assertTrue(report['observation_complete'])
                    self.assertTrue(report['passive'])
                    self.assertEqual(report['packet_delivery'], 'not_tested')
                    self.assertEqual(len([f for f in report['nodes'][0]['findings'] if f['code'] == 'STP_PROTECTION']), 2)
                    self.assertFalse(probe('PC1', '192.0.2.30'))
                    self.assertFalse(probe('PC2', '198.18.0.30'))
                    both('spanning-tree guard none')
                    wait(lambda t: not t['is_root'] and t['root_port'] == 'eth2' and t['local_state_settled'])
                    connected()
                    both('spanning-tree bpduguard enable')
                    wait(lambda t: all(t['ports'][p]['state'] == 'disabled' and t['ports'][p]['bpdu_guard'] for p in ('eth2', 'eth3')))
                    revision = manager.state['revision']
                    report = explain(manager, 'SW3')
                    disabled = [f for f in report['nodes'][0]['findings'] if f['code'] == 'STP_DISABLED_WITH_BPDU_GUARD']
                    self.assertEqual({f['evidence']['port'] for f in disabled}, {'eth2', 'eth3'})
                    self.assertTrue(all(f['evidence']['state'] == 'disabled' for f in disabled))
                    self.assertEqual(manager.state['revision'], revision)
                    self.assertFalse(probe('PC1', '192.0.2.30'))
                    self.assertFalse(probe('PC2', '198.18.0.30'))
                    # Disabled protocol state is not administrative drift. Persist
                    # policy, then require real BPDUs to trigger protection again.
                    manager.write_startup()
                    index = next(i for i, n in enumerate(spec['nodes']) if n['name'] == 'SW3')
                    manager.ns(index, 'bridge', 'link', 'set', 'dev', 'eth2', 'guard', 'off')
                    with self.assertRaisesRegex(RuntimeFailure, 'spanning-tree port parameters differ'):
                        manager.write_startup()
                    manager.stop()
                    manager.start(load_startup(spec['name']))
                    wait(lambda t: all(t['ports'][p]['state'] == 'disabled' and t['ports'][p]['bpdu_guard'] for p in ('eth2', 'eth3')))
                    both('spanning-tree bpduguard disable\nshutdown')
                    both('no shutdown')
                    wait(lambda t: not t['is_root'] and t['root_port'] == 'eth2' and t['local_state_settled'])
                    connected()
                    manager.write_startup()
                except BaseException:
                    if manager.directory.exists():
                        print('Guard diagnostics:', {n: manager.inspect(n) for n in ('SW1', 'SW2', 'SW3')}, file=sys.stderr)
                    raise
                finally:
                    if manager.directory.exists():
                        manager.stop()
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, before)

    def test_common_stp_uses_lacp_as_one_port_and_fails_over_to_spare_trunk(self):
        from network_labs.appliances.examples import lacp_lab
        from network_labs.appliances.spec import validate
        from network_labs.appliances.persistence import load_startup
        with tempfile.TemporaryDirectory() as folder, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = lacp_lab(rootfs)
            spec['name'] = 'stp-lacp-' + str(os.getpid())
            for i, node in enumerate(spec['nodes'][4:]):
                node['interfaces']['eth4'] = ''
                node['interface_aliases']['fa0/5'] = 'eth4'
                node['switchports']['eth4'] = {'mode': 'trunk', 'native_vlan': 1, 'allowed': [10, 20]}
                node['spanning_tree'] = {'mode': 'stp', 'priority': (i+1)*4096, 'hello_time': 1, 'max_age': 6,
                                         'forward_delay': 4, 'ports': {'eth4': {'cost': 1000}}}
            spec['links'].append([['SW1', 'eth4'], ['SW2', 'eth4']])
            spec = validate(spec)
            manager = Manager(spec['name'])
            captures = []
            def stop_captures():
                for process, path in captures:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
            def trace_restore():
                for name in ('SW1', 'SW2', 'PC1', 'PC3'):
                    index = next(i for i, n in enumerate(spec['nodes']) if n['name'] == name)
                    path = Path(folder) / (name + '-restore.log')
                    with path.open('w') as output:
                        process = subprocess.Popen(['ip', 'netns', 'exec', namespace(spec, index),
                            'tcpdump', '-l', '-nn', '-e', '-i', 'any', '-s', '128', '-c', '1024'],
                            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT)
                    captures.append((process, path))
            def wait_path(spare, members):
                deadline = time.monotonic() + 30
                while True:
                    actual = manager.inspect('SW2')
                    peer = manager.inspect('SW1')
                    tree = actual['spanning_tree']
                    channel = actual['port_channels']['bond1']
                    if (peer['spanning_tree']['local_state_settled']
                            and tree['root_id'] == peer['spanning_tree']['bridge_id']
                            and tree['root_port'] == ('eth4' if spare else 'bond1') and tree['local_state_settled']
                            and tree['ports']['eth4']['state'] == ('forwarding' if spare else 'blocking')
                            and (members is None or len(channel['negotiated_members']) == members)):
                        return
                    if time.monotonic() >= deadline:
                        self.fail('STP/LACP did not converge: ' + json.dumps(actual))
                    time.sleep(0.2)
            def ping(reverse=False):
                pairs = (('PC3', '192.0.2.10'), ('PC4', '198.18.0.10')) if reverse else (('PC1', '192.0.2.20'), ('PC2', '198.18.0.20'))
                for source, target in pairs:
                    deadline = time.monotonic() + 10
                    while True:
                        probe = manager.crun('exec', source, '/bin/ping', '-c', '1', '-W', '1', target, check=False)
                        if probe.returncode == 0:
                            break
                        if time.monotonic() >= deadline:
                            self.fail('STP packet path did not recover: ' + probe.stdout + probe.stderr)
                        time.sleep(0.1)
            with manager.locked():
                try:
                    manager.start(spec)
                    wait_path(False, 2)
                    ping()
                    marker = '02:aa:bb:00:00:91'
                    for index in (4, 5):
                        manager.ns(index, 'bridge', 'fdb', 'add', marker, 'dev', 'eth0', 'master', 'static', 'vlan', '10')
                    for cycle in range(3):
                        manager.configure_ios('SW1', 'conf t\ninterface fa0/3\nshutdown\nend')
                        wait_path(False, 1)
                        ping()
                        manager.configure_ios('SW1', 'conf t\ninterface fa0/4\nshutdown\nend')
                        wait_path(True, 0)
                        ping()
                        trace_restore()
                        restore = 'conf t\ninterface fa0/3\nno shutdown\ninterface fa0/4\nno shutdown\nend'
                        if cycle == 0:
                            # Fail only after the first bridge's real dynamic
                            # flush. Rollback restores policy, not lost learning.
                            original_ns = manager.ns
                            flushed = []
                            armed = [True]
                            def interrupted(index, *args, **kwargs):
                                if args == ('bridge', 'fdb', 'flush', 'dev', 'br0', 'dynamic'):
                                    if index == 5 and armed[0]:
                                        armed[0] = False
                                        raise RuntimeFailure('Injected second-bridge FDB flush failure')
                                    result = original_ns(index, *args, **kwargs)
                                    flushed.append(index)
                                    return result
                                return original_ns(index, *args, **kwargs)
                            before = json.loads(json.dumps(manager.state['spec']))
                            revision = manager.state['revision']
                            with patch.object(manager, 'ns', side_effect=interrupted), \
                                 self.assertRaisesRegex(RuntimeFailure, 'rolled back.*second-bridge'):
                                manager.configure_ios('SW1', restore)
                            self.assertEqual(flushed, [4])
                            self.assertFalse(armed[0])
                            persisted = manager.read()
                            self.assertEqual(persisted['spec'], before)
                            self.assertEqual(persisted['revision'], revision)
                            self.assertEqual(persisted['phase'], 'running')
                            self.assertNotIn('pending_spec', persisted)
                            self.assertNotIn('pending_node', persisted)
                            wait_path(True, 0)
                            ping()
                            ping(reverse=True)
                        restored = manager.configure_ios('SW1', restore)
                        self.assertEqual(restored['stp_recovery']['bridges'], ['SW1', 'SW2'])
                        wait_path(False, 2)
                        ping(reverse=True)
                        ping()
                        for index in (4, 5):
                            records = json.loads(manager.ns(index, 'bridge', '-j', 'fdb', 'show').stdout)
                            self.assertTrue(any(row['mac'] == marker for row in records), 'Static FDB entry lost during recovery')
                        stop_captures()
                        captures.clear()
                    # Carrier can also disappear with one negotiated member:
                    # the declared minimum is two, so recovery of just the
                    # missing member must reconcile the former spare path.
                    manager.configure_ios('SW1', 'conf t\ninterface po1\nport-channel min-links 2\nend')
                    wait_path(False, 2)
                    ping()
                    ping(reverse=True)
                    degraded = manager.configure_ios('SW1', 'conf t\ninterface fa0/3\nshutdown\nend')
                    self.assertNotIn('stp_recovery', degraded)
                    wait_path(True, 1)
                    ping()
                    ping(reverse=True)
                    bundle = manager.inspect('SW1')['port_channels']['bond1']
                    self.assertEqual(len(bundle['negotiated_members']), 1)
                    self.assertFalse(bundle['ready'])
                    self.assertNotIn('LOWER_UP', bundle['kernel']['flags'])
                    trace_restore()
                    restored = manager.configure_ios('SW1', 'conf t\ninterface fa0/3\nno shutdown\nend')
                    self.assertEqual(restored['stp_recovery']['channels'], ['bond1'])
                    self.assertEqual(restored['stp_recovery']['bridges'], ['SW1', 'SW2'])
                    wait_path(False, 2)
                    ping(reverse=True)
                    ping()
                    self.assertTrue(manager.inspect('SW1')['port_channels']['bond1']['ready'])
                    for index in (4, 5):
                        records = json.loads(manager.ns(index, 'bridge', '-j', 'fdb', 'show').stdout)
                        self.assertTrue(any(row['mac'] == marker for row in records), 'Static FDB entry lost at min-links recovery')
                    stop_captures()
                    captures.clear()
                    # Shutting down the logical port must keep both physical
                    # members administratively up; LACP state while the bond
                    # is down is evidence, not a required negotiated count.
                    disabled = manager.configure_ios('SW1', 'conf t\ninterface po1\nshutdown\nend')
                    self.assertNotIn('stp_recovery', disabled)
                    wait_path(True, None)
                    ping()
                    ping(reverse=True)
                    actual = manager.inspect('SW1')
                    self.assertNotIn('UP', actual['port_channels']['bond1']['kernel']['flags'])
                    physical = {row['ifname']: row for row in actual['links']}
                    for member in ('eth2', 'eth3'):
                        self.assertIn('UP', physical[member]['flags'])
                    trace_restore()
                    enabled = manager.configure_ios('SW1', 'conf t\ninterface po1\nno shutdown\nend')
                    self.assertEqual(enabled['stp_recovery']['channels'], ['bond1'])
                    self.assertEqual(enabled['stp_recovery']['bridges'], ['SW1', 'SW2'])
                    wait_path(False, 2)
                    ping(reverse=True)
                    ping()
                    for index in (4, 5):
                        records = json.loads(manager.ns(index, 'bridge', '-j', 'fdb', 'show').stdout)
                        self.assertTrue(any(row['mac'] == marker for row in records), 'Static FDB entry lost at logical-port recovery')
                    stop_captures()
                    captures.clear()
                    # Save the deliberately disabled logical bundle. Restart
                    # must preserve its policy, rebuild the STP spare path and
                    # discard the manually added runtime-only static marker.
                    manager.configure_ios('SW1', 'conf t\ninterface po1\nshutdown\nend')
                    wait_path(True, None)
                    ping()
                    ping(reverse=True)
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    saved_switch = next(n for n in saved['nodes'] if n['name'] == 'SW1')
                    self.assertIn('bond1', saved_switch['shutdown'])
                    self.assertEqual(saved_switch['port_channels']['bond1']['min_links'], 2)
                    manager.stop()
                    manager.start(saved)
                    wait_path(True, None)
                    ping()
                    ping(reverse=True)
                    actual = manager.inspect('SW1')
                    self.assertNotIn('UP', actual['port_channels']['bond1']['kernel']['flags'])
                    for index in (4, 5):
                        records = json.loads(manager.ns(index, 'bridge', '-j', 'fdb', 'show').stdout)
                        self.assertFalse(any(row['mac'] == marker for row in records), 'Runtime FDB marker entered saved configuration')
                    trace_restore()
                    enabled = manager.configure_ios('SW1', 'conf t\ninterface po1\nno shutdown\nend')
                    self.assertEqual(enabled['stp_recovery']['bridges'], ['SW1', 'SW2'])
                    wait_path(False, 2)
                    ping(reverse=True)
                    ping()
                    stop_captures()
                    captures.clear()
                except BaseException:
                    stop_captures()
                    for _, path in captures:
                        lines = path.read_text().splitlines()
                        evidence = '\n'.join(lines[:4] + [line for line in lines if 'ICMP' in line or 'ARP' in line])
                        print('STP/LACP restore capture ' + path.name + ':\n' + evidence[-6000:], file=sys.stderr)
                    if manager.directory.exists():
                        print('STP/LACP diagnostics:', manager.inspect('SW1'), manager.inspect('SW2'), file=sys.stderr)
                    raise
                finally:
                    stop_captures()
                    if manager.directory.exists():
                        manager.stop()

    def test_campus_vlan_routing_dhcp_live_configuration_and_saved_restore(self):
        from network_labs.appliances.examples import campus
        from network_labs.appliances.persistence import load_startup, startup_path
        before = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = campus(rootfs)
            spec['name'] = 'campus-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            last_probe = []
            def ping(source, target):
                probe = manager.crun('exec', source, '/bin/ping', '-c', '1', '-W', '1', target, check=False)
                last_probe[:] = [source, target, probe.returncode, probe.stdout, probe.stderr]
                return probe.returncode == 0
            def wait_lease():
                for _ in range(80):
                    observed = manager.inspect('PC1')
                    ips = [a['local'] for item in observed['addresses'] if item['ifname'] == 'eth0'
                           for a in item.get('addr_info', []) if a.get('scope') == 'global']
                    if ips:
                        self.assertTrue(100 <= int(ips[0].split('.')[-1]) <= 150, ips)
                        self.assertTrue(any(r.get('gateway') == '10.10.10.1' for r in observed['routes']))
                        return ips[0]
                    time.sleep(0.1)
                logs = [(manager.directory / n / 'dhcp.log').read_text(errors='replace') for n in ('PC1', 'SRV1')]
                self.fail('Real DHCP lease not received: ' + str(logs))
            def apply(name, commands):
                return manager.configure_ios(name, 'configure terminal\n' + commands + '\nend')
            with manager.locked():
                try:
                    manager.start(spec)
                    lease = wait_lease()
                    self.assertTrue(ping('PC1', '10.20.20.40'))
                    self.assertTrue(ping('PC3', '10.20.20.40'))
                    self.assertTrue(ping('PC2', '10.20.20.40'))
                    # Different VLANs still communicate only while the real router forwards.
                    apply('R1', 'no ip routing')
                    self.assertFalse(ping('PC3', '10.20.20.40'))
                    self.assertTrue(ping('PC3', lease))
                    self.assertTrue(ping('PC2', '10.20.20.40'))
                    apply('R1', 'ip routing')
                    self.assertTrue(ping('PC3', '10.20.20.40'))
                    # Same subnet cannot bypass a wrong access VLAN by going through the router.
                    apply('SW2', 'interface fa0/2\nswitchport access vlan 10')
                    self.assertFalse(ping('PC2', '10.20.20.40'))
                    apply('SW2', 'interface fa0/2\nswitchport access vlan 20')
                    self.assertTrue(ping('PC2', '10.20.20.40'))
                    # Trunk allowed list has an actual forwarding effect.
                    apply('SW1', 'interface fa0/4\nswitchport trunk allowed vlan 10')
                    self.assertFalse(ping('PC3', '10.20.20.40'))
                    self.assertTrue(ping('PC2', '10.20.20.40'))
                    apply('SW1', 'interface fa0/4\nswitchport trunk allowed vlan 10,20')
                    self.assertTrue(ping('PC3', '10.20.20.40'))
                    apply('SW1', 'interface fa0/4\nshutdown')
                    self.assertFalse(ping('PC3', '10.20.20.40'))
                    apply('SW1', 'interface fa0/4\nno shutdown')
                    self.assertTrue(ping('PC3', '10.20.20.40'))
                    revision = manager.state['revision']
                    with self.assertRaisesRegex(ValueError, 'Line'):
                        apply('SW1', 'interface fa0/4\nshutdown\nunsupported command')
                    self.assertEqual(manager.state['revision'], revision)
                    self.assertTrue(ping('PC3', '10.20.20.40'))
                    # Save is durable and refuses to silently serialize stale declared state.
                    manager.write_startup()
                    saved = startup_path(spec['name']).read_text()
                    manager.crun('exec', 'PC2', '/bin/ip', 'addr', 'add', '10.20.20.222/24', 'dev', 'eth0')
                    with self.assertRaisesRegex(RuntimeFailure, 'Unmanaged'):
                        manager.write_startup()
                    self.assertEqual(startup_path(spec['name']).read_text(), saved)
                    manager.crun('exec', 'PC2', '/bin/ip', 'addr', 'del', '10.20.20.222/24', 'dev', 'eth0')
                    apply('SW2', 'interface fa0/2\nswitchport access vlan 10')
                    manager.stop()
                    self.assertTrue(startup_path(spec['name']).exists())
                    restored = Manager(spec['name'])
                    manager = restored
                    manager.start(load_startup(spec['name']))
                    wait_lease()
                    self.assertTrue(ping('PC2', '10.20.20.40'))
                    self.assertTrue(ping('PC3', '10.20.20.40'))
                    self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, before)
                    print('Native campus: real DHCP, VLAN isolation, trunks, routing, shutdown, atomic parse and saved restore verified.')
                finally:
                    if sys.exc_info()[0] is not None and manager.directory.exists():
                        print('Unexpected native failure; last probe:', last_probe)
                        for name in ('PC2', 'PC4', 'SW1', 'SW2', 'R1'):
                            print(name, json.dumps(manager.inspect(name)))
                    if manager.directory.exists():
                        manager.stop()
            self.assertFalse(manager.directory.exists())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, before)


if __name__ == '__main__':
    unittest.main()
