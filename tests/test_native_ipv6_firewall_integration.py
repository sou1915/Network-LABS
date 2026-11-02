"""Actual IPv6 filter/conntrack, packet evidence, failure isolation and cold restore."""
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
from network_labs.appliances.examples import ipv6_firewall_lab
from network_labs.appliances.firewall import fingerprint
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeIPv6FirewallTests(unittest.TestCase):
    def test_stateful_allow_deny_wire_stateless_controls_drift_and_cold_restore(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('busybox', 'crun', 'ip', 'nft', 'conntrack', 'tcpdump'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        baseline = {kind: run(['ip', '-j', '-6', kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for kind in ('route', 'rule')}
        forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        host_nft = fingerprint(json.loads(run(['nft', '-j', '-n', 'list', 'ruleset']).stdout))
        before = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder); rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs')
            spec = ipv6_firewall_lab(rootfs); spec['name'] = 'ipv6-fw-' + str(os.getpid())
            manager = Manager(spec['name'])
            def ping(source='PC1', destination='2001:db8:20::20'):
                return manager.crun('exec', source, '/bin/busybox', 'ping6', '-c', '1', '-W', '1', '-w', '2', destination,
                                    check=False, timeout=4)
            def http(port=8080, source='PC1'):
                return manager.crun('exec', source, '/bin/busybox', 'wget', '-q', '-T', '2', '-O', '-',
                                    f'http://[2001:db8:20::20]:{port}/', check=False, timeout=5)
            def start_http():
                manager.crun('exec', 'PC2', '/bin/sh', '-c', 'mkdir -p /tmp/www; printf ipv6-firewall-ok > /tmp/www/index.html')
                for port in (8080, 8081):
                    manager.crun('exec', '--detach', 'PC2', '/bin/busybox', 'httpd', '-f', '-p', '[::]:' + str(port), '-h', '/tmp/www',
                                 log=manager.directory / 'PC2' / ('http-' + str(port) + '.log'))
                deadline = time.monotonic() + 5
                while http(8081, 'PC2').returncode:
                    if time.monotonic() >= deadline: self.fail('Independent blocked-port listener unavailable')
                    time.sleep(.1)
            def healthy():
                deadline = time.monotonic() + 10
                while ping().returncode:
                    if time.monotonic() >= deadline: self.fail('Allowed ICMPv6 failed: ' + repr(manager.inspect('FW1')))
                    time.sleep(.1)
                result = http(); self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'ipv6-firewall-ok')
            def counters():
                return {row['rule']['comment']: sum(e['counter']['packets'] for e in row['rule']['expr'] if 'counter' in e)
                        for row in manager.inspect('FW1')['firewall_ipv6']['nftables'] if 'rule' in row}
            def refuse_save():
                with manager.locked(), self.assertRaises(RuntimeFailure): manager.write_startup()
            try:
                with manager.locked(): manager.start(spec)
                start_http(); healthy()
                # This is a forward ACL: local NDP and traffic to the firewall
                # itself remain outside it, even from the untrusted side.
                self.assertEqual(ping('PC2', '2001:db8:20::1').returncode, 0)
                events = [threading.Event(), threading.Event()]; paths = [root / 'fw-in.pcap', root / 'fw-out.pcap']
                futures = [pool.submit(capture, Manager(spec['name']), 'FW1', port, path,
                                      seconds=8, packets=400, snaplen=1024, expression='ip6', ready=event.set)
                           for port, path, event in zip(('eth0', 'eth1'), paths, events)]
                for event, future in zip(events, futures):
                    if not event.wait(5):
                        if future.done(): future.result()
                        self.fail('Firewall packet capture did not become ready')
                healthy()
                self.assertNotEqual(http(8081).returncode, 0)
                self.assertNotEqual(ping('PC2', '2001:db8:10::10').returncode, 0)
                self.assertEqual(http(8081, 'PC2').returncode, 0)
                for future in futures: self.assertGreater(future.result(timeout=15)['captured_packets'], 0)
                wire = [run(['tcpdump', '-nn', '-vv', '-r', path]).stdout for path in paths]
                for decoded in wire:
                    self.assertIn('2001:db8:20::20.8080:', decoded)
                    self.assertIn('ICMP6, echo reply', decoded)
                self.assertIn('2001:db8:20::20.8081:', wire[0])
                self.assertNotIn('2001:db8:20::20.8081:', wire[1])
                counts = counters()
                for name in ('state', 'rule:echo-out', 'rule:http-out', 'default'): self.assertGreater(counts[name], 0, counts)
                sessions = manager.ns(1, 'conntrack', '-L', '-f', 'ipv6', '-p', 'tcp').stdout
                self.assertIn('src=2001:db8:10::10', sessions); self.assertIn('dport=8080', sessions)
                with manager.locked(): manager.write_startup()
                saved = load_startup(spec['name']); self.assertEqual(saved, spec)
                manager.ns(1, 'nft', 'add', 'table', 'ip6', 'unmanaged_test'); refuse_save()
                manager.ns(1, 'nft', 'delete', 'table', 'ip6', 'unmanaged_test')
                manager.ns(1, 'nft', 'flush', 'chain', 'ip6', 'network_labs_ipv6', 'forward'); refuse_save()
                with manager.locked(): manager.stop(); manager.start(saved)
                self.assertTrue(all(count == 0 for count in counters().values()))
                start_http(); healthy()
                with manager.locked(): manager.write_startup()
                # A stateless policy with only an explicit ICMP return rule
                # allows echo replies, but cannot complete the same TCP flow.
                stateless = copy.deepcopy(saved); policy = stateless['nodes'][1]['firewall_ipv6']; policy['stateful'] = False
                policy['rules'].append({'name': 'echo-return', 'action': 'accept', 'in': 'eth1', 'out': 'eth0',
                                        'source': '2001:db8:20::20/128', 'destination': '2001:db8:10::10/128',
                                        'protocol': 'icmpv6', 'icmp_type': 'echo-reply'})
                with manager.locked(): manager.stop(); manager.start(stateless)
                start_http()
                deadline = time.monotonic() + 10
                while ping().returncode:
                    if time.monotonic() >= deadline: self.fail('Explicit stateless ICMP return failed')
                self.assertNotEqual(http().returncode, 0)
                self.assertNotEqual(ping('PC2', '2001:db8:10::10').returncode, 0)
                counts = counters(); self.assertNotIn('state', counts)
                self.assertGreater(counts['rule:http-out'], 0); self.assertGreater(counts['rule:echo-return'], 0)
                self.assertGreater(counts['default'], 0)
                with manager.locked(): manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        for kind, value in baseline.items():
            self.assertEqual(run(['ip', '-j', '-6', kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, value)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout, forwarding)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', '-n', 'list', 'ruleset']).stdout)), host_nft)
        after = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        hardware = {name for name, _ in after - before if (Path('/sys/class/net') / name / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before, after, hardware), {'removed_or_replaced': set(), 'added_virtual': set()})
