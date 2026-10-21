"""Opt-in real OCI boot/packet test. Run on a disposable Linux host with sudo.

NETWORK_LABS_NATIVE_TESTS=1 requires crun, iproute2, busybox-static, nftables, conntrack, tcpdump and nsenter. These
tests are deliberately never replaced with mocks when explicitly requested.
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
from network_labs.appliances.spec import example, namespace


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class RealContainerTests(unittest.TestCase):
    def test_arp_inspection_real_dynamic_static_spoofing_timeout_drift_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import signal
        import threading
        from network_labs.appliances.capture import capture
        from network_labs.appliances.examples import arp_inspection_lab
        from ipaddress import IPv4Address
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.snooping import alive
        from network_labs.appliances.arp_inspection import TABLE
        from test_native_arp_inspection import arp_frame
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        records = []
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = arp_inspection_lab(rootfs); spec['name'] = 'arp-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def wait_ping(node='PC1'):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if manager.crun('exec', node, '/bin/ping', '-c', '1', '-W', '1', '10.10.0.2', check=False).returncode == 0:
                        return
                    time.sleep(0.1)
                self.fail('ARP-authorized ping failed: ' + json.dumps(manager.inspect('SW1')) +
                          '\n' + (manager.directory / 'SW1.snooping.log').read_text())
            def inject(index, packet):
                manager.ns(index, sys.executable, '-c',
                           'import socket,sys; s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)); s.bind(("eth0",0)); s.send(bytes.fromhex(sys.argv[1]))', packet.hex())
            def captured(name, node, expression, count, action):
                ready = threading.Event()
                future = pool.submit(capture, Manager(spec['name']), node, 'eth0', Path(folder) / name,
                                     seconds=2, packets=count, expression=expression, ready=ready.set)
                if not ready.wait(5):
                    future.result(timeout=5); self.fail('ARP capture readiness missing')
                with manager.locked():
                    action()
                return future.result(timeout=6)['captured_packets']
            try:
                with manager.locked():
                    manager.start(spec)
                    records.append(dict(manager.state['snooping_workers']['SW1']))
                    wait_ping()
                    observed = manager.inspect('SW1')
                    self.assertTrue(observed['arp_inspection']['policy_verified'])
                    self.assertTrue(any(c['rule'] == 'dynamic:eth0' and c['packets'] > 0 for c in observed['arp_inspection']['counters']))
                    self.assertTrue(any(r.get('elem') for r in observed['arp_inspection']['dynamic_sets'] if r['name'] == 'dhcp_eth0'))
                    lease = observed['dhcp_snooping']['bindings'][0]['address']
                    manager.crun('exec', 'ROGUE', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/udhcpd.pid)"')
                    manager.write_startup()  # Dynamic set elements must not look like policy drift.
                rogue_filter = 'arp and ether src 02:00:00:00:10:03 and arp[14:4] = 0x0a0a0002'
                def spoof():
                    inject(3, arp_frame(target_ip=lease))
                    inject(3, arp_frame(target_ip=lease, operation=2, destination='02:00:00:00:10:10', target_mac='02:00:00:00:10:10'))
                    # Real container CLI tool as well as controlled raw frames.
                    result = manager.crun('exec', 'ROGUE', '/bin/busybox', 'arping', '-U', '-c', '1', '-w', '1',
                                          '-I', 'eth0', '-s', '10.10.0.2', '10.10.0.2', check=False, timeout=3)
                    self.assertIn(result.returncode, (0, 1), result.stderr)
                    self.assertNotIn('applet not found', result.stderr)
                    self.assertNotIn('invalid option', result.stderr)
                self.assertEqual(captured('spoof.pcap', 'PC1', rogue_filter, 100, spoof), 0)
                # A source-IP-only check would accept these; both Ethernet and
                # ARP sender MAC must match the authorized client on eth0.
                client_filter = 'arp and arp[14:4] = 0x' + IPv4Address(lease).packed.hex()
                def mismatched():
                    inject(0, arp_frame(source_mac='02:00:00:00:10:03', sender_mac='02:00:00:00:10:10', sender_ip=lease, target_ip='10.10.0.2'))
                    inject(0, arp_frame(source_mac='02:00:00:00:10:10', sender_mac='02:00:00:00:10:03', sender_ip=lease, target_ip='10.10.0.2'))
                self.assertEqual(captured('mismatch.pcap', 'DHCP1', client_filter, 100, mismatched), 0)
                self.assertEqual(captured('static.pcap', 'PC1', 'arp and ether src 02:00:00:00:10:03 and arp[14:4] = 0x0a0a0003', 1,
                                         lambda: inject(3, arp_frame(sender_ip='10.10.0.3', target_ip=lease))), 1)
                with manager.locked():
                    after = manager.inspect('SW1')['arp_inspection']
                    self.assertTrue(any(c['rule'] == 'deny:eth2' and c['packets'] > 0 for c in after['counters']))
                    self.assertTrue(any(c['rule'] == 'deny:eth0' and c['packets'] > 0 for c in after['counters']))
                    neighbours = json.loads(manager.ns(0, 'ip', '-j', 'neigh', 'show').stdout)
                    self.assertTrue(any(n.get('dst') == '10.10.0.2' and n.get('lladdr') == '02:00:00:00:10:02' for n in neighbours), neighbours)
                    record = dict(manager.state['snooping_workers']['SW1'])
                    os.kill(record['pid'], signal.SIGKILL)
                    time.sleep(2.3)  # Kernel grant lifetime, not a simulated revocation.
                    self.assertFalse(alive(record))
                    for index in (0, 2, 3):
                        manager.ns(index, 'ip', 'neigh', 'flush', 'dev', 'eth0')
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '10.10.0.2', check=False).returncode, 0)
                    wait_ping('ROGUE')  # Explicit static binding remains independent.
                    state = manager.inspect('SW1')
                    self.assertTrue(state['arp_inspection']['policy_verified'])
                    self.assertIsNone(state['dhcp_snooping']['bindings'])
                    manager.configure_ios('SW1', 'conf t\ninterface fa0/1\nno shutdown\nend')
                    records.append(dict(manager.state['snooping_workers']['SW1']))
                    manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -USR2 "$(/bin/cat /run/udhcpc.pid)"; /bin/busybox sleep 0.2; /bin/kill -USR1 "$(/bin/cat /run/udhcpc.pid)"')
                    wait_ping()
                    manager.write_startup(); saved = load_startup(spec['name'])
                    manager.ns(1, 'nft', 'delete', 'table', 'bridge', TABLE)
                    with self.assertRaisesRegex(RuntimeFailure, 'ARP inspection'):
                        manager.write_startup()
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    records.append(dict(manager.state['snooping_workers']['SW1']))
                    wait_ping()
                    self.assertTrue(manager.inspect('SW1')['arp_inspection']['policy_verified'])
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertTrue(all(not alive(r) for r in records))
        self.assertEqual(host_links(), links)
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), host_rules)

    def test_dhcp_snooping_real_trust_binding_rogue_filter_worker_loss_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import signal
        from network_labs.appliances.capture import capture
        from network_labs.appliances.examples import dhcp_snooping_lab
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.snooping import TABLE, alive
        from test_native_snooping import frame
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        records = []
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = dhcp_snooping_lab(rootfs); spec['name'] = 'snoop-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def binding(address=None):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    observed = manager.inspect('SW1')['dhcp_snooping']
                    for entry in observed['bindings'] or []:
                        if address is None or entry['address'] == address:
                            return entry
                    time.sleep(0.1)
                self.fail('No matching wire binding: ' + json.dumps(observed) + '\n' + (manager.directory / 'SW1.snooping.log').read_text())
            def inject(index, packet):
                manager.ns(index, sys.executable, '-c',
                           'import socket,sys; s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)); s.bind(("eth0",0)); s.send(bytes.fromhex(sys.argv[1]))', packet.hex())
            def configure(commands):
                result = manager.configure_ios('SW1', 'conf t\n' + commands + '\nend')
                record = manager.state.get('snooping_workers', {}).get('SW1')
                if record and all(r['token'] != record['token'] for r in records):
                    records.append(dict(record))
                return result
            def captured(name, packets, action):
                ready = threading.Event()
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', Path(folder) / name,
                                     seconds=2, packets=packets, expression='ether src 02:00:00:00:10:02', ready=ready.set)
                if not ready.wait(5):
                    future.result(timeout=5); self.fail('Capture never became ready')
                with manager.locked():
                    action()
                return future.result(timeout=6)['captured_packets']
            try:
                with manager.locked():
                    manager.start(spec)
                    record = dict(manager.state['snooping_workers']['SW1']); records.append(record)
                    self.assertTrue(alive(record))
                    lease = binding()
                    self.assertEqual((lease['port'], lease['vlan'], lease['server_port']), ('eth0', 10, 'eth1'))
                    self.assertTrue(100 <= int(lease['address'].split('.')[-1]) <= 110)
                    deadline = time.monotonic() + 5
                    while True:
                        observed = manager.inspect('PC1')
                        installed = [a['local'] for r in observed['addresses'] for a in r.get('addr_info', [])]
                        if lease['address'] in installed or time.monotonic() >= deadline:
                            break
                        time.sleep(0.05)
                    self.assertIn(lease['address'], installed)
                    self.assertEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '10.10.0.2').returncode, 0)
                    counters = manager.inspect('SW1')['dhcp_snooping']['counters']
                    self.assertTrue(any(c['rule'] == 'server:eth2' and c['packets'] > 0 for c in counters), counters)
                    configure('interface fa0/1\nno shutdown')
                    self.assertEqual(manager.state['snooping_workers']['SW1']['token'], record['token'])
                    self.assertEqual(binding()['address'], lease['address'])
                    with self.assertRaises(ValueError):
                        configure('ip dhcp snooping information option')
                    manager.write_startup()
                    configure('interface fa0/2\nshutdown')
                    # Both real servers participated above. Isolate crafted packet
                    # probes from the rogue daemon's own ACK/NAK state machine.
                    manager.crun('exec', 'ROGUE', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/udhcpd.pid)"')
                request = frame(xid=999, requested='10.10.0.77', server='10.10.0.3')
                ack = frame(5, xid=999, yiaddr='10.10.0.77', server='10.10.0.3')
                def rogue_packets():
                    inject(0, request)
                    inject(3, ack)
                    inject(3, frame(5, xid=999, yiaddr='10.10.0.77', server='10.10.0.3', sport=68))
                    inject(3, ack[:12] + b'\x81\x00\x00\x0a' + ack[12:])
                    inject(3, ack[:12] + b'\x88\xa8\x00\x0a\x81\x00\x00\x0a' + ack[12:])
                self.assertEqual(captured('rogue.pcap', 100, rogue_packets), 0, 'Untrusted/tagged BOOTREPLY reached client')
                with manager.locked():
                    self.assertFalse(any(b['address'] == '10.10.0.77' for b in manager.inspect('SW1')['dhcp_snooping']['bindings'] or []))
                    configure('interface fa0/3\nip dhcp snooping trust')
                self.assertEqual(captured('trusted.pcap', 1, lambda: (inject(0, request), inject(3, ack))), 1)
                with manager.locked():
                    accepted = binding('10.10.0.77')
                    self.assertEqual(accepted['server_port'], 'eth2')
                    configure('interface fa0/3\nno ip dhcp snooping trust\ninterface fa0/2\nno shutdown')
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertNotIn('bindings', saved['nodes'][1]['dhcp_snooping'])
                    manager.stop()
                    self.assertFalse(alive(record))
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    record = dict(manager.state['snooping_workers']['SW1']); records.append(record)
                    self.assertNotEqual(record['token'], records[0]['token'])
                    binding()
                    os.kill(record['pid'], signal.SIGKILL)
                    deadline = time.monotonic() + 2
                    while alive(record) and time.monotonic() < deadline:
                        time.sleep(0.02)
                    state = manager.inspect('SW1')['dhcp_snooping']
                    self.assertTrue(state['policy_verified'])
                    self.assertFalse(state['observer_available']); self.assertIsNone(state['bindings'])
                    denied = sum(c['packets'] for c in state['counters'] if c['rule'] == 'server:eth2')
                    inject(3, ack)
                    after = manager.inspect('SW1')['dhcp_snooping']
                    self.assertGreater(sum(c['packets'] for c in after['counters'] if c['rule'] == 'server:eth2'), denied)
                    configure('interface fa0/1\nno shutdown')
                    record = dict(manager.state['snooping_workers']['SW1']); records.append(record)
                    self.assertTrue(alive(record))
                    manager.ns(1, 'nft', 'delete', 'table', 'bridge', TABLE)
                    self.assertIsNone(manager.inspect('SW1')['dhcp_snooping']['bindings'])
                    with self.assertRaisesRegex(RuntimeFailure, 'DHCP snooping'):
                        manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertTrue(all(not alive(r) for r in records))
        self.assertEqual(host_links(), links)
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), host_rules)

    def test_static_port_security_real_source_rejection_live_policy_drift_and_restore(self):
        from network_labs.appliances.examples import port_security_lab
        from network_labs.appliances.diagnostics import explain
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.port_security import TABLE
        before_routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        before_links = host_links()
        host_policy = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = port_security_lab(rootfs); spec['name'] = 'secure-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            original, extra = '02:00:00:00:01:10', '02:00:00:00:01:99'
            def ping():
                return manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '192.0.2.20', check=False).returncode == 0
            def wait_for_ping(context):
                # Rejected ARP may leave an outstanding neighbour probe/backoff.
                # Test eventual actual delivery after admission, without weakening
                # any of the negative probes or changing policy during retries.
                deadline = time.monotonic() + 5
                attempts = 0
                neighbours = manager.ns(0, 'ip', '-j', 'neigh', 'show', 'dev', 'eth0').stdout
                while True:
                    attempts += 1
                    if ping():
                        print('Port security admission:', context, 'attempts=', attempts, 'initial_neighbours=', neighbours, flush=True)
                        return
                    if time.monotonic() >= deadline:
                        self.fail(context + ': ' + json.dumps({'security': manager.inspect('SW1').get('port_security'),
                                  'pc1': manager.inspect('PC1'), 'neighbours': manager.ns(0, 'ip', '-j', 'neigh', 'show').stdout}))
                    time.sleep(0.1)
            def set_mac(address):
                manager.crun('exec', 'PC1', '/bin/ip', 'link', 'set', 'dev', 'eth0', 'address', address)
                for index in (0, 2):
                    manager.ns(index, 'ip', 'neigh', 'flush', 'dev', 'eth0')
            def configure(text):
                return manager.configure_ios('SW1', 'conf t\ninterface fa0/1\n' + text + '\nend')
            try:
                with manager.locked():
                    manager.start(spec)
                    self.assertTrue(ping())
                    before = manager.inspect('SW1')['port_security']
                    self.assertTrue(before['fingerprint_matches'])
                    self.assertGreater(before['ports']['eth0']['accepted_packets'], 0)
                    self.assertEqual(next(l for l in manager.inspect('PC1')['links'] if l['ifname'] == 'eth0')['address'], original)
                    set_mac(extra)
                    self.assertFalse(ping(), 'Unknown source MAC crossed the protected access port')
                    denied = manager.inspect('SW1')['port_security']
                    self.assertTrue(denied['fingerprint_matches'])
                    self.assertGreater(denied['ports']['eth0']['dropped_packets'], before['ports']['eth0']['dropped_packets'])
                    switch = manager.inspect('SW1')
                    self.assertTrue('UP' in next(l for l in switch['links'] if l['ifname'] == 'eth0')['flags'])
                    self.assertNotIn(extra, [entry.get('mac') for entry in switch['fdb']])
                    findings = explain(manager, 'SW1')['nodes'][0]['findings']
                    self.assertIn('PORT_SECURITY_DROPS', {f['code'] for f in findings})
                    revision = manager.state['revision']
                    with self.assertRaises(ValueError):
                        configure('shutdown\nswitchport port-security maximum 2')
                    self.assertEqual(manager.state['revision'], revision)
                    self.assertFalse(ping())
                    configure('switchport port-security maximum 2\nswitchport port-security mac-address ' + extra)
                    self.assertTrue(manager.inspect('SW1')['port_security']['fingerprint_matches'])
                    wait_for_ping('New explicitly admitted MAC did not recover packet delivery')
                    counters = manager.inspect('SW1')['port_security']['ports']['eth0']['accepted_packets']
                    configure('no shutdown')
                    self.assertGreaterEqual(manager.inspect('SW1')['port_security']['ports']['eth0']['accepted_packets'], counters)
                    set_mac(original)
                    self.assertTrue(ping())
                    manager.write_startup()
                    manager.ns(1, 'nft', 'delete', 'table', 'bridge', TABLE)
                    self.assertFalse(manager.inspect('SW1')['port_security']['available'])
                    self.assertIn('PORT_SECURITY_UNVERIFIED', {f['code'] for f in explain(manager, 'SW1')['nodes'][0]['findings']})
                    with self.assertRaisesRegex(RuntimeFailure, 'port security'):
                        manager.write_startup()
                    # Explicitly remove/recreate policy after out-of-band drift.
                    configure('no switchport port-security')
                    configure('switchport port-security\nswitchport port-security mac-address ' + original)
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    self.assertTrue(ping(), 'Stable client MAC and secure policy did not survive restore')
                    self.assertTrue(manager.inspect('SW1')['port_security']['fingerprint_matches'])
                    set_mac(extra)
                    self.assertFalse(ping(), 'Restored static policy admitted an unlisted MAC')
                    set_mac(original)
                    configure('no switchport port-security')
                    from network_labs.appliances.port_security import read_table
                    self.assertIsNone(read_table(manager, 1))
                    set_mac(extra)
                    wait_for_ping('Removing security left a hidden drop policy')
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertEqual(host_links(), before_links)
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, before_routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), host_policy)

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
            spec = example(rootfs); spec['name'] = 'capture-test-' + str(os.getpid())
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
                self.assertIn('192.0.2.10', decoded); self.assertIn('192.0.2.20', decoded)
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
                    log = b''; deadline = time.monotonic() + 5
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
                    wrapper.kill(); wrapper.wait(timeout=2)
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
                        wrapper.kill(); wrapper.wait(timeout=2)
                    wrapper.stdout.close(); wrapper.stderr.close()
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

    def test_campus_vlan_routing_dhcp_live_configuration_and_saved_restore(self):
        from network_labs.appliances.examples import campus
        from network_labs.appliances.persistence import load_startup, startup_path
        before = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = campus(rootfs); spec['name'] = 'campus-test-' + str(os.getpid())
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
                    restored = Manager(spec['name']); manager = restored
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

    def test_stateful_firewall_nat_policy_drift_and_restore(self):
        import copy
        from network_labs.appliances.examples import firewall_lab
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        before = fingerprint(json.loads(run(['nft', '-j', '-n', 'list', 'ruleset']).stdout))
        routes = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = firewall_lab(rootfs); spec['name'] = 'firewall-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            policy = copy.deepcopy(spec['nodes'][1]['firewall'])
            def server(node, port):
                manager.crun('exec', node, '/bin/sh', '-c', 'mkdir -p /tmp/www; echo ' + node + ' > /tmp/www/index.html')
                manager.crun('exec', '--detach', node, '/bin/busybox', 'httpd', '-f', '-p', str(port), '-h', '/tmp/www',
                             log=manager.directory / (node + '-' + str(port) + '.http.log'))
                for _ in range(40):
                    if get(node, '127.0.0.1:' + str(port)).returncode == 0:
                        return
                    time.sleep(0.05)
                self.fail('HTTP server did not become ready: ' + node + ':' + str(port))
            def get(node, address):
                return manager.crun('exec', node, '/bin/busybox', 'wget', '-T', '1', '-q', '-O', '-',
                                    'http://' + address + '/', check=False)
            def update(value):
                manager.configure_firewall('FW1', value)
                manager.sessions('FW1', clear=True)
            with manager.locked():
                try:
                    manager.start(spec)
                    server('PC1', 80); server('SRV1', 80); server('SRV1', 8081)
                    self.assertEqual(get('PC1', '198.51.100.10').stdout.strip(), 'SRV1')
                    sessions = manager.sessions('FW1')['output']
                    self.assertIn('src=10.42.0.10', sessions)
                    self.assertIn('dst=198.51.100.1', sessions)
                    # A listening service on an unpermitted port is actually filtered.
                    self.assertEqual(get('SRV1', '198.51.100.10:8081').returncode, 0)
                    self.assertNotEqual(get('PC1', '198.51.100.10:8081').returncode, 0)
                    rules = manager.inspect('FW1')['firewall']['nftables']
                    default = next(v['rule'] for v in rules if v.get('rule', {}).get('comment') == 'default')
                    self.assertGreater(sum(x.get('counter', {}).get('packets', 0) for x in default['expr']), 0)
                    # DNAT is matched by forwarding rules after destination translation.
                    self.assertEqual(get('SRV1', '198.51.100.1:8080').stdout.strip(), 'PC1')
                    # The reply has no explicit reverse allow rule: conntrack supplies it.
                    stateless = copy.deepcopy(policy); stateless['stateful'] = False
                    update(stateless)
                    self.assertNotEqual(get('PC1', '198.51.100.10').returncode, 0)
                    update(policy)
                    self.assertEqual(get('PC1', '198.51.100.10').returncode, 0)
                    # The server has no route to 10.42.0.0/24, so NAT is necessary.
                    no_nat = copy.deepcopy(policy); no_nat['nat'] = []
                    update(no_nat)
                    self.assertNotEqual(get('PC1', '198.51.100.10').returncode, 0)
                    snat = copy.deepcopy(policy); snat['nat'][0].update(type='snat', to='198.51.100.1')
                    update(snat)
                    self.assertEqual(get('PC1', '198.51.100.10').returncode, 0)
                    denied = copy.deepcopy(policy)
                    denied['rules'].insert(0, {'name': 'deny-first', 'action': 'drop', 'in': 'eth0', 'protocol': 'tcp', 'dport': 80})
                    update(denied)
                    self.assertNotEqual(get('PC1', '198.51.100.10').returncode, 0)
                    update(policy)
                    self.assertEqual(get('PC1', '198.51.100.10').returncode, 0)
                    # Counter updates alone never make saved configuration stale.
                    manager.write_startup()
                    manager.ns(1, 'nft', 'add', 'table', 'ip', 'unmanaged')
                    with self.assertRaisesRegex(RuntimeFailure, 'firewall rules differ'):
                        manager.write_startup()
                    manager.ns(1, 'nft', 'delete', 'table', 'ip', 'unmanaged')
                    manager.stop()
                    manager.start(load_startup(spec['name']))
                    server('PC1', 80); server('SRV1', 80)
                    self.assertEqual(get('PC1', '198.51.100.10').stdout.strip(), 'SRV1')
                    self.assertEqual(get('SRV1', '198.51.100.1:8080').stdout.strip(), 'PC1')
                except BaseException:
                    if manager.directory.exists():
                        print('Firewall diagnostics:', manager.inspect('FW1'), file=sys.stderr)
                    raise
                finally:
                    if manager.directory.exists():
                        manager.stop()
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', '-n', 'list', 'ruleset']).stdout)), before)
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)

    def test_enterprise_twenty_nodes_benchmark_and_real_return_routes(self):
        from network_labs.appliances.benchmark import benchmark, wait_ready
        from network_labs.appliances.examples import enterprise
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        before = fingerprint(json.loads(run(['nft', '-j', '-n', 'list', 'ruleset']).stdout))
        routes = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = enterprise(rootfs); spec['name'] = 'enterprise-test-' + str(os.getpid())
            next(n for n in spec['nodes'] if n['name'] == 'FW1')['routes'].append(
                {'destination': '10.10.10.2/32', 'gateway': '172.31.255.2', 'interface': 'eth0'})
            report = benchmark(spec, target='198.51.100.10', seconds=2)
            self.assertEqual(report['node_count'], 20)
            self.assertTrue(report['cleanup_complete'])
            self.assertTrue(report['all_nodes_running_after_load'])
            self.assertTrue(report['load']['all_packets_received'], report['load']['flows'])
            self.assertEqual(len(report['load']['flows']), 12)
            self.assertFalse(report['assessment']['oom_kill_observed'])
            self.assertGreater(report['idle']['lab_cgroup_memory_sampled_peak_bytes'], 0)
            self.assertGreater(report['load']['metrics']['lab_cgroup_cpu_percent_one_core'], 0)
            self.assertEqual(report['assessment']['total_application_under_target'], 'unverified')
            print('ENTERPRISE_BENCHMARK ' + json.dumps(report), file=sys.stderr)
            manager = Manager(spec['name'])
            def ping(source):
                return manager.crun('exec', source, '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10', check=False).returncode == 0
            def get(node, address):
                return manager.crun('exec', node, '/bin/busybox', 'wget', '-T', '1', '-q', '-O', '-', 'http://' + address + '/', check=False)
            with manager.locked():
                try:
                    manager.start(spec); wait_ready(manager)
                    self.assertEqual(len(manager.status()['nodes']), 20)
                    for node in ('WAN1', 'DHCP1'):
                        manager.crun('exec', node, '/bin/sh', '-c', 'mkdir -p /tmp/www; echo ' + node + ' > /tmp/www/index.html; /bin/busybox httpd -p 80 -h /tmp/www')
                    manager.crun('exec', 'WAN1', '/bin/busybox', 'httpd', '-p', '8081', '-h', '/tmp/www')
                    self.assertEqual(get('PC12', '198.51.100.10').stdout.strip(), 'WAN1')
                    self.assertEqual(get('WAN1', '198.51.100.10:8081').returncode, 0)
                    self.assertNotEqual(get('PC12', '198.51.100.10:8081').returncode, 0)
                    self.assertEqual(get('WAN1', '198.51.100.1:8080').stdout.strip(), 'DHCP1')
                    firewall_index = next(i for i, n in enumerate(spec['nodes']) if n['name'] == 'FW1')
                    manager.ns(firewall_index, 'ip', '-4', 'route', 'del', '10.10.10.0/24')
                    self.assertFalse(ping('PC1'))
                    self.assertTrue(ping('PC2'))
                    with self.assertRaisesRegex(RuntimeFailure, 'static routes differ'):
                        manager.write_startup()
                    manager.ns(firewall_index, 'ip', '-4', 'route', 'add', '10.10.10.0/24', 'via', '172.31.255.2', 'dev', 'eth0', 'proto', 'static')
                    self.assertTrue(ping('PC1'))
                    manager.write_startup(); manager.stop()
                    manager.start(load_startup(spec['name'])); wait_ready(manager)
                    self.assertTrue(ping('PC1')); self.assertTrue(ping('PC12'))
                finally:
                    if manager.directory.exists():
                        manager.stop()
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', '-n', 'list', 'ruleset']).stdout)), before)
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)

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
            spec = lacp_lab(rootfs); spec['name'] = spec_name
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
                    self.assertTrue(ping(10)); self.assertTrue(ping(20))
                    # Active/passive was negotiated; now exercise active/active.
                    apply('SW2', 'interface fa0/3\nchannel-group 1 mode active')
                    wait_members(2)
                    manager.write_startup()
                    apply('SW1', 'interface port-channel1\nswitchport trunk allowed vlan 10')
                    self.assertTrue(ping(10)); self.assertFalse(ping(20))
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
                    self.assertTrue(ping(10)); self.assertFalse(ping(20))
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
                    self.assertTrue(ping(10)); self.assertTrue(ping(20))
                    # A surviving negotiated member carries both VLANs.
                    apply('SW1', 'interface fa0/3\nshutdown')
                    wait_members(1)
                    self.assertIn('LACP_DEGRADED', {f['code'] for f in explain(manager, 'SW1')['nodes'][0]['findings']})
                    self.assertTrue(ping(10)); self.assertTrue(ping(20))
                    # The threshold is a real kernel carrier gate, not a fake ping rule.
                    apply('SW1', 'interface po1\nport-channel min-links 2')
                    wait_members(1, ready=False, nodes=('SW1',))
                    self.assertIn('LACP_NOT_READY', {f['code'] for f in explain(manager, 'SW1')['nodes'][0]['findings']})
                    self.assertFalse(ping(10))
                    apply('SW1', 'interface po1\nno port-channel min-links')
                    wait_members(1)
                    self.assertTrue(ping(10))
                    apply('SW1', 'interface fa0/4\nshutdown')
                    self.assertFalse(ping(10)); self.assertFalse(ping(20))
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
                    self.assertTrue(ping(10)); self.assertTrue(ping(20))
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
        before = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = stp_lab(rootfs); spec['name'] = 'stp-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def snapshot():
                return {n: manager.inspect(n)['spanning_tree'] for n in ('SW1', 'SW2', 'SW3')}
            def wait_tree(root, blocked=1):
                deadline = time.monotonic() + 30
                while True:
                    state = snapshot(); root_id = state[root]['bridge_id']
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
                    self.assertTrue(ping('PC1', '192.0.2.30')); self.assertTrue(ping('PC2', '198.18.0.30'))
                    # Cutting the direct root link unblocks the alternate path through SW2.
                    apply('SW1', 'interface fa0/4\nshutdown')
                    tree = wait_tree('SW1', blocked=0)
                    self.assertEqual(tree['SW3']['root_port'], 'eth3')
                    self.assertTrue(ping('PC1', '192.0.2.30')); self.assertTrue(ping('PC2', '198.18.0.30'))
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
                    self.assertTrue(ping('PC3', '192.0.2.30')); self.assertTrue(ping('PC4', '198.18.0.30'))
                    revision = manager.state['revision']
                    with self.assertRaises(ValueError):
                        manager.configure_spanning_tree('SW1', {'mode': 'off'})
                    self.assertEqual(manager.state['revision'], revision)
                    manager.write_startup()
                    index = next(i for i, n in enumerate(spec['nodes']) if n['name'] == 'SW3')
                    manager.ns(index, 'ip', 'link', 'set', 'dev', 'br0', 'type', 'bridge', 'priority', '16384')
                    with self.assertRaisesRegex(RuntimeFailure, 'spanning-tree bridge parameters differ'):
                        manager.write_startup()
                    manager.stop(); manager.start(load_startup(spec['name']))
                    tree = wait_tree('SW3')
                    self.assertEqual(tree['SW2']['root_port'], 'eth2')
                    self.assertTrue(ping('PC1', '192.0.2.30')); self.assertTrue(ping('PC2', '198.18.0.30'))
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
            spec = stp_lab(rootfs); spec['name'] = 'guard-test-' + str(os.getpid())
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
                    wait(lambda t: t['is_root'] and all(t['ports'][p]['state'] in ('listening', 'blocking') and t['ports'][p]['root_guard'] for p in ('eth2', 'eth3'))
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
                    manager.stop(); manager.start(load_startup(spec['name']))
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
        with tempfile.TemporaryDirectory() as folder:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = lacp_lab(rootfs); spec['name'] = 'stp-lacp-' + str(os.getpid())
            for i, node in enumerate(spec['nodes'][4:]):
                node['interfaces']['eth4'] = ''
                node['interface_aliases']['fa0/5'] = 'eth4'
                node['switchports']['eth4'] = {'mode': 'trunk', 'native_vlan': 1, 'allowed': [10, 20]}
                node['spanning_tree'] = {'mode': 'stp', 'priority': (i+1)*4096, 'hello_time': 1, 'max_age': 6,
                                         'forward_delay': 4, 'ports': {'eth4': {'cost': 1000}}}
            spec['links'].append([['SW1', 'eth4'], ['SW2', 'eth4']]); spec = validate(spec)
            manager = Manager(spec['name'])
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
                            and len(channel['negotiated_members']) == members):
                        return
                    if time.monotonic() >= deadline:
                        self.fail('STP/LACP did not converge: ' + json.dumps(actual))
                    time.sleep(0.2)
            def ping():
                for source, target in (('PC1', '192.0.2.20'), ('PC2', '198.18.0.20')):
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
                    manager.start(spec); wait_path(False, 2); ping()
                    manager.configure_ios('SW1', 'conf t\ninterface fa0/3\nshutdown\nend')
                    wait_path(False, 1); ping()
                    manager.configure_ios('SW1', 'conf t\ninterface fa0/4\nshutdown\nend')
                    wait_path(True, 0); ping()
                    manager.configure_ios('SW1', 'conf t\ninterface fa0/3\nno shutdown\ninterface fa0/4\nno shutdown\nend')
                    wait_path(False, 2); ping()
                except BaseException:
                    if manager.directory.exists():
                        print('STP/LACP diagnostics:', manager.inspect('SW1'), manager.inspect('SW2'), file=sys.stderr)
                    raise
                finally:
                    if manager.directory.exists():
                        manager.stop()

    def test_packets_persistence_namespace_isolation_and_cleanup(self):
        self.assertEqual(os.geteuid(), 0, 'Run this explicit test with sudo')
        for tool in ('crun', 'ip', 'busybox'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        before = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = example(rootfs); spec['name'] = 'integration-' + str(os.getpid())
            manager = Manager(spec['name'])
            with manager.locked():
                try:
                    manager.start(spec)
                    self.assertTrue(all(n['state']['status'] == 'running' for n in manager.status()['nodes']))
                    # Actual ICMP request/reply crosses two veth pairs and an in-namespace bridge.
                    self.assertEqual(manager.execute('PC1', ['/bin/ping', '-c', '2', '-W', '2', '192.0.2.20']), 0)
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
