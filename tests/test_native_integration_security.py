"""Opt-in real OCI boot/packet tests. Switch and firewall security on real containers: dynamic ARP inspection, IP source
guard, DHCP snooping, static port security, a stateful firewall with NAT.

Run as test_native_integration says (NETWORK_LABS_NATIVE_TESTS=1, on a disposable Linux host with sudo).
"""
import os
import json
import sys
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs

from test_native_integration import NATIVE, RealContainerCase


@unittest.skipUnless(NATIVE, 'Opt-in privileged native test')
class SecurityTests(RealContainerCase):
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
        links = host_links()
        host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        records = []
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = arp_inspection_lab(rootfs)
            spec['name'] = 'arp-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def wait_ping(node='PC1', target='10.10.0.2'):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if manager.crun('exec', node, '/bin/ping', '-c', '1', '-W', '1', target, check=False).returncode == 0:
                        return
                    time.sleep(0.1)
                self.fail('ARP-authorized ping failed: ' + json.dumps(manager.inspect('SW1')) +
                          '\n' + (manager.directory / 'SW1.snooping.log').read_text())
            def inject(index, packet):
                manager.ns(index, sys.executable, '-c',
                           'import socket,sys; s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)); s.bind(("eth0",0)); '
                    's.send(bytes.fromhex(sys.argv[1]))', packet.hex())
            def captured(name, node, expression, count, action):
                ready = threading.Event()
                future = pool.submit(capture, Manager(spec['name']), node, 'eth0', Path(folder) / name,
                                     seconds=2, packets=count, expression=expression, ready=ready.set)
                if not ready.wait(5):
                    future.result(timeout=5)
                    self.fail('ARP capture readiness missing')
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
                    # BusyBox arping binds its source IP; give the rogue a
                    # temporary duplicate address, then remove the test drift.
                    manager.crun('exec', 'ROGUE', '/bin/ip', 'addr', 'add', '10.10.0.2/32', 'dev', 'eth0')
                    try:
                        result = manager.crun('exec', 'ROGUE', '/bin/busybox', 'arping', '-U', '-c', '1', '-w', '1',
                                              '-I', 'eth0', '-s', '10.10.0.2', '10.10.0.2', check=False, timeout=3)
                        self.assertIn(result.returncode, (0, 1), result.stderr)
                        self.assertNotIn('applet not found', result.stderr)
                        self.assertNotIn('invalid option', result.stderr)
                    finally:
                        manager.crun('exec', 'ROGUE', '/bin/ip', 'addr', 'del', '10.10.0.2/32', 'dev', 'eth0')
                self.assertEqual(captured('spoof.pcap', 'PC1', rogue_filter, 100, spoof), 0)
                # A source-IP-only check would accept these; both Ethernet and
                # ARP sender MAC must match the authorized client on eth0.
                client_filter = 'arp and arp[14:4] = 0x' + IPv4Address(lease).packed.hex()
                def mismatched():
                    inject(0, arp_frame(source_mac='02:00:00:00:10:03', sender_mac='02:00:00:00:10:10', sender_ip=lease,
                                        target_ip='10.10.0.2'))
                    inject(0, arp_frame(source_mac='02:00:00:00:10:10', sender_mac='02:00:00:00:10:03', sender_ip=lease,
                                        target_ip='10.10.0.2'))
                self.assertEqual(captured('mismatch.pcap', 'DHCP1', client_filter, 100, mismatched), 0)
                self.assertEqual(captured('static.pcap', 'PC1', 'arp and ether src 02:00:00:00:10:03 and arp[14:4] = 0x0a0a0003', 1,
                                         lambda: inject(3, arp_frame(sender_ip='10.10.0.3', target_ip=lease))), 1)
                with manager.locked():
                    after = manager.inspect('SW1')['arp_inspection']
                    self.assertTrue(any(c['rule'] == 'deny:eth2' and c['packets'] > 0 for c in after['counters']))
                    self.assertTrue(any(c['rule'] == 'deny:eth0' and c['packets'] > 0 for c in after['counters']))
                    neighbours = json.loads(manager.ns(0, 'ip', '-j', 'neigh', 'show').stdout)
                    self.assertTrue(any(n.get('dst') == '10.10.0.2' and n.get('lladdr') == '02:00:00:00:10:02' for n in neighbours),
                                    neighbours)
                    # Valid client leases must keep working on the LAN when
                    # the DHCP server link is lost, until their normal expiry.
                    manager.configure_ios('SW1', 'conf t\ninterface fa0/2\nshutdown\nend')
                    for index in (0, 3):
                        manager.ns(index, 'ip', 'neigh', 'flush', 'dev', 'eth0')
                    wait_ping('PC1', '10.10.0.3')
                    manager.configure_ios('SW1', 'conf t\ninterface fa0/2\nno shutdown\nend')
                    record = dict(manager.state['snooping_workers']['SW1'])
                    os.kill(record['pid'], signal.SIGKILL)
                    time.sleep(2.3)  # Kernel grant lifetime, not a simulated revocation.
                    self.assertFalse(alive(record))
                    for index in (0, 2, 3):
                        manager.ns(index, 'ip', 'neigh', 'flush', 'dev', 'eth0')
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '10.10.0.2',
                                                     check=False).returncode, 0)
                    wait_ping('ROGUE')  # Explicit static binding remains independent.
                    state = manager.inspect('SW1')
                    self.assertTrue(state['arp_inspection']['policy_verified'])
                    self.assertIsNone(state['dhcp_snooping']['bindings'])
                    manager.configure_ios('SW1', 'conf t\ninterface fa0/1\nno shutdown\nend')
                    records.append(dict(manager.state['snooping_workers']['SW1']))
                    manager.crun('exec', 'PC1', '/bin/sh', '-c',
                            '/bin/kill -USR2 "$(/bin/cat /run/udhcpc.pid)"; /bin/busybox sleep 0.2; /bin/kill -USR1 "$(/bin/cat '
                        '/run/udhcpc.pid)"')
                    wait_ping()
                    manager.write_startup()
                    saved = load_startup(spec['name'])
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
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), host_rules)

    def test_ip_source_guard_real_ipv4_spoof_cached_neighbours_modes_timeout_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import signal
        import struct
        import threading
        from network_labs.appliances.capture import capture
        from network_labs.appliances.examples import source_guard_lab
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.snooping import alive
        from network_labs.appliances.source_guard import TABLE
        from test_native_source_guard import ipv4_frame
        from test_native_snooping import frame
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        records = []
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = source_guard_lab(rootfs)
            spec['name'] = 'ipsg-test-' + str(os.getpid())
            # Prove IPv4 protection independently of ARP inspection; static
            # source bindings remain available in the shared manifest store.
            spec['nodes'][1]['arp_inspection']['vlans'] = []
            manager = Manager(spec['name'])
            def wait_ping(node='PC1'):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if manager.crun('exec', node, '/bin/ping', '-c', '1', '-W', '1', '10.10.0.2', check=False).returncode == 0:
                        return
                    time.sleep(0.1)
                self.fail('IP Source Guard legitimate ping failed: ' + json.dumps(manager.inspect('SW1')) +
                          '\n' + (manager.directory / 'SW1.snooping.log').read_text())
            def inject(index, packet):
                manager.ns(index, sys.executable, '-c',
                           'import socket,sys; s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)); s.bind(("eth0",0)); '
                    's.send(bytes.fromhex(sys.argv[1]))', packet.hex())
            def captured(name, expression, count, action):
                ready = threading.Event()
                future = pool.submit(capture, Manager(spec['name']), 'DHCP1', 'eth0', Path(folder) / name,
                                     seconds=2, packets=count, expression=expression, ready=ready.set)
                if not ready.wait(5):
                    future.result(timeout=5)
                    self.fail('IPv4 capture readiness missing')
                with manager.locked():
                    action()
                return future.result(timeout=6)['captured_packets']
            try:
                with manager.locked():
                    manager.start(spec)
                    records.append(dict(manager.state['snooping_workers']['SW1']))
                    wait_ping()
                    wait_ping('ROGUE')
                    observed = manager.inspect('SW1')
                    self.assertTrue(observed['ip_source_guard']['policy_verified'])
                    self.assertNotIn('arp_inspection', observed)
                    lease = observed['dhcp_snooping']['bindings'][0]['address']
                    manager.crun('exec', 'ROGUE', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/udhcpd.pid)"')
                    # Permanent neighbours exclude ARP resolution as an
                    # explanation for either positive or negative delivery.
                    manager.ns(0, 'ip', 'neigh', 'replace', '10.10.0.2', 'lladdr', '02:00:00:00:10:02', 'nud', 'permanent', 'dev', 'eth0')
                    manager.ns(2, 'ip', 'neigh', 'replace', lease, 'lladdr', '02:00:00:00:10:10', 'nud', 'permanent', 'dev', 'eth0')
                    wait_ping()
                    manager.write_startup()
                expression = 'icmp and dst host 10.10.0.2 and icmp[4:2] = 0x1234'
                def spoofed():
                    inject(0, ipv4_frame(source='10.10.0.99'))  # Correct MAC, wrong IP.
                    inject(0, ipv4_frame(source=lease, mac='02:00:00:00:10:99'))  # Right IP, wrong MAC.
                    inject(3, ipv4_frame(source=lease))  # Right IP+MAC, wrong ingress port.
                    inject(3, ipv4_frame(source='10.10.0.99', mac='02:00:00:00:10:03'))
                self.assertEqual(captured('spoof.pcap', expression, 100, spoofed), 0)
                with manager.locked():
                    counters = manager.inspect('SW1')['ip_source_guard']['counters']
                    for port in ('eth0', 'eth2'):
                        self.assertTrue(any(c['rule'] == 'deny:' + port and c['packets'] > 0 for c in counters), counters)
                self.assertEqual(captured('dynamic.pcap', expression, 1, lambda: inject(0, ipv4_frame(source=lease))), 1)
                self.assertEqual(captured('static.pcap', expression, 1,
                                         lambda: inject(3, ipv4_frame(source='10.10.0.3', mac='02:00:00:00:10:03'))), 1)
                # A broad UDP 68->67 exception would leak spoofed nonzero
                # sources; both BOOTP-shaped and malformed traffic must fail.
                def fake_dhcp():
                    payload = bytearray(frame(3)[34:])
                    payload[:4] = struct.pack('!HH', 68, 67)
                    inject(0, ipv4_frame(source='10.10.0.99', destination='255.255.255.255',
                                        destination_mac='ff:ff:ff:ff:ff:ff', protocol=17, payload=payload))
                    inject(0, ipv4_frame(source='0.0.0.0', destination='255.255.255.255',
                                        destination_mac='ff:ff:ff:ff:ff:ff', protocol=17,
                                        payload=struct.pack('!HHHH', 68, 67, 12, 0) + b'fake'))
                self.assertEqual(captured('bootstrap-deny.pcap', 'udp src port 68 and udp dst port 67', 100, fake_dhcp), 0)
                with manager.locked():
                    manager.configure_ios('SW1', 'conf t\ninterface fa0/1\nip verify source\nend')
                    # Changing policy restarts volatile correlation. Acquire a
                    # fresh lease before evaluating the new mode.
                    manager.crun('exec', 'PC1', '/bin/sh', '-c',
                            '/bin/kill -USR2 "$(/bin/cat /run/udhcpc.pid)"; /bin/busybox sleep 0.2; /bin/kill -USR1 "$(/bin/cat '
                        '/run/udhcpc.pid)"')
                    wait_ping()
                    lease = manager.inspect('SW1')['dhcp_snooping']['bindings'][0]['address']
                    records.append(dict(manager.state['snooping_workers']['SW1']))
                self.assertEqual(captured('ip-only.pcap', expression, 1,
                                         lambda: inject(0, ipv4_frame(source=lease, mac='02:00:00:00:10:99'))), 1)
                with manager.locked():
                    # The forged MAC may move the FDB entry; refresh both
                    # neighbour entries and legitimate forwarding first.
                    manager.ns(0, 'ip', 'neigh', 'replace', '10.10.0.2', 'lladdr', '02:00:00:00:10:02', 'nud', 'permanent', 'dev', 'eth0')
                    manager.ns(2, 'ip', 'neigh', 'replace', lease, 'lladdr', '02:00:00:00:10:10', 'nud', 'permanent', 'dev', 'eth0')
                    wait_ping()
                    wait_ping('ROGUE')
                    state = manager.inspect('SW1')['ip_source_guard']
                    self.assertTrue(state['policy_verified'])
                    # eth0 counters reset on the intentional mode change;
                    # eth2 static traffic still has its own accept counter.
                    self.assertTrue(any(c['rule'] == 'static:eth2' and c['packets'] > 0 for c in state['counters']))
                    record = dict(manager.state['snooping_workers']['SW1'])
                    os.kill(record['pid'], signal.SIGKILL)
                    time.sleep(2.3)
                    self.assertFalse(alive(record))
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '10.10.0.2',
                                                     check=False).returncode, 0)
                    neighbours = json.loads(manager.ns(0, 'ip', '-j', 'neigh', 'show').stdout)
                    self.assertTrue(any(n.get('dst') == '10.10.0.2' and 'PERMANENT' in n.get('state', []) for n in neighbours), neighbours)
                    wait_ping('ROGUE')  # Static source authorization survives.
                    self.assertIsNone(manager.inspect('SW1')['dhcp_snooping']['bindings'])
                    manager.configure_ios('SW1', 'conf t\nip arp inspection vlan 10\ninterface fa0/1\nno shutdown\nend')
                    records.append(dict(manager.state['snooping_workers']['SW1']))
                    manager.crun('exec', 'PC1', '/bin/sh', '-c',
                            '/bin/kill -USR2 "$(/bin/cat /run/udhcpc.pid)"; /bin/busybox sleep 0.2; /bin/kill -USR1 "$(/bin/cat '
                        '/run/udhcpc.pid)"')
                    # The repaired observer now refreshes both ARP and IPv4
                    # grants. Flush cached neighbours to exercise both filters.
                    for index in (0, 2):
                        manager.ns(index, 'ip', 'neigh', 'flush', 'dev', 'eth0', 'nud', 'all')
                    wait_ping()
                    self.assertTrue(manager.inspect('SW1')['arp_inspection']['policy_verified'])
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.ns(1, 'nft', 'delete', 'table', 'bridge', TABLE)
                    with self.assertRaisesRegex(RuntimeFailure, 'IP Source Guard'):
                        manager.write_startup()
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    records.append(dict(manager.state['snooping_workers']['SW1']))
                    wait_ping()
                    wait_ping('ROGUE')
                    restored = manager.inspect('SW1')
                    self.assertTrue(restored['ip_source_guard']['policy_verified'])
                    self.assertTrue(restored['arp_inspection']['policy_verified'])
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertTrue(all(not alive(r) for r in records))
        self.assertHostLinksUnchanged(links, host_links())
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
            spec = dhcp_snooping_lab(rootfs)
            spec['name'] = 'snoop-test-' + str(os.getpid())
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
                           'import socket,sys; s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)); s.bind(("eth0",0)); '
                    's.send(bytes.fromhex(sys.argv[1]))', packet.hex())
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
                    future.result(timeout=5)
                    self.fail('Capture never became ready')
                with manager.locked():
                    action()
                return future.result(timeout=6)['captured_packets']
            try:
                with manager.locked():
                    manager.start(spec)
                    record = dict(manager.state['snooping_workers']['SW1'])
                    records.append(record)
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
                    record = dict(manager.state['snooping_workers']['SW1'])
                    records.append(record)
                    self.assertNotEqual(record['token'], records[0]['token'])
                    binding()
                    os.kill(record['pid'], signal.SIGKILL)
                    deadline = time.monotonic() + 2
                    while alive(record) and time.monotonic() < deadline:
                        time.sleep(0.02)
                    state = manager.inspect('SW1')['dhcp_snooping']
                    self.assertTrue(state['policy_verified'])
                    self.assertFalse(state['observer_available'])
                    self.assertIsNone(state['bindings'])
                    denied = sum(c['packets'] for c in state['counters'] if c['rule'] == 'server:eth2')
                    inject(3, ack)
                    after = manager.inspect('SW1')['dhcp_snooping']
                    self.assertGreater(sum(c['packets'] for c in after['counters'] if c['rule'] == 'server:eth2'), denied)
                    configure('interface fa0/1\nno shutdown')
                    record = dict(manager.state['snooping_workers']['SW1'])
                    records.append(record)
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
        self.assertHostLinksUnchanged(links, host_links())
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
            spec = port_security_lab(rootfs)
            spec['name'] = 'secure-test-' + str(os.getpid())
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

    def test_stateful_firewall_nat_policy_drift_and_restore(self):
        import copy
        from network_labs.appliances.examples import firewall_lab
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        before = fingerprint(json.loads(run(['nft', '-j', '-n', 'list', 'ruleset']).stdout))
        routes = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = firewall_lab(rootfs)
            spec['name'] = 'firewall-test-' + str(os.getpid())
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
                    server('PC1', 80)
                    server('SRV1', 80)
                    server('SRV1', 8081)
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
                    stateless = copy.deepcopy(policy)
                    stateless['stateful'] = False
                    update(stateless)
                    self.assertNotEqual(get('PC1', '198.51.100.10').returncode, 0)
                    update(policy)
                    self.assertEqual(get('PC1', '198.51.100.10').returncode, 0)
                    # The server has no route to 10.42.0.0/24, so NAT is necessary.
                    no_nat = copy.deepcopy(policy)
                    no_nat['nat'] = []
                    update(no_nat)
                    self.assertNotEqual(get('PC1', '198.51.100.10').returncode, 0)
                    snat = copy.deepcopy(policy)
                    snat['nat'][0].update(type='snat', to='198.51.100.1')
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
                    server('PC1', 80)
                    server('SRV1', 80)
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


if __name__ == '__main__':
    unittest.main()
