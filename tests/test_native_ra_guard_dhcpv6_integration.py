"""Local IA_NA and RA across RA Guard: real wire identity, outage and restore."""
from concurrent.futures import ThreadPoolExecutor
import copy
import ipaddress
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.capture import capture
from network_labs.appliances.dhcpv6 import CLIENT_SCRIPT
from network_labs.appliances.dhcpv6_relay import PROCESS_SCRIPT
from network_labs.appliances.examples import ra_guard_dhcpv6_lab
from network_labs.appliances.firewall import fingerprint
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.slaac import start_servers
from network_labs.appliances.verify import verify
from test_native_dhcpv6 import captured_dhcpv6
from test_native_integration import ipv6_default_expired, solicit_ipv6_router, unexpected_host_link_changes
from test_native_ra_guard import rogue_frames
from test_native_ra_guard_integration import pcap_frames
from test_native_slaac import captured_ras


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeRAGuardDHCPv6Tests(unittest.TestCase):
    def test_local_ia_na_ra_guard_renew_release_outage_wire_and_saved_restart(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('busybox', 'crun', 'ip', 'nft', 'tcpdump', 'dnsmasq'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        baseline = {kind: run(['ip', '-j', '-6', kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for kind in ('route', 'rule')}
        forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        host_nft = fingerprint(json.loads(run(['nft', '-j', '-n', 'list', 'ruleset']).stdout))
        before = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder); rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs', dnsmasq=shutil.which('dnsmasq'))
            spec = ra_guard_dhcpv6_lab(rootfs); spec['name'] = 'guard-dhcp6-' + str(os.getpid()); manager = Manager(spec['name'])
            def addresses():
                return [a for row in json.loads(manager.ns(0, 'ip', '-j', '-6', 'addr', 'show', 'dev', 'eth0').stdout)
                        for a in row.get('addr_info', []) if a.get('scope') == 'global']
            def defaults():
                return [r for r in json.loads(manager.ns(0, 'ip', '-j', '-6', 'route', 'show', 'table', 'main').stdout)
                        if r.get('dst') == 'default' and r.get('protocol') == 'ra' and r.get('expires', 0) > 0]
            def wait(predicate, label, seconds=40):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if predicate(): return
                    time.sleep(.2)
                logs = {str(p.relative_to(manager.directory)): p.read_text(errors='replace')[-3000:]
                        for p in manager.directory.glob('*/*.log')}
                self.fail(label + ': client=' + repr(manager.inspect('PC1')) + '; guard=' + repr(manager.inspect('SW1')) + '; logs=' + repr(logs))
            def signal(value):
                manager.crun('exec', 'PC1', '/bin/sh', '-c',
                             'pid=$(/bin/busybox cat /run/udhcpc6.pid); [ "$pid" -gt 1 ]; /bin/busybox kill -' + value + ' "$pid"')
            def ready():
                last_rs = 0
                def acquired():
                    nonlocal last_rs
                    values = addresses(); routes = defaults()
                    good = (len(values) == 1 and values[0]['prefixlen'] == 128 and
                            ipaddress.IPv6Address('2001:db8:10::100') <= ipaddress.IPv6Address(values[0]['local']) <= ipaddress.IPv6Address('2001:db8:10::10f') and
                            0 < values[0].get('preferred_life_time', 0) <= values[0].get('valid_life_time', 0) <= 120 and
                            not values[0].get('tentative') and not values[0].get('dadfailed') and
                            not any(f in values[0].get('flags', []) for f in ('tentative', 'dadfailed')) and len(routes) == 1 and
                            routes[0].get('dev') == 'eth0' and ipaddress.IPv6Address(routes[0].get('gateway', '::')).is_link_local)
                    if not good and time.monotonic() - last_rs >= 4:
                        solicit_ipv6_router(manager, 0); last_rs = time.monotonic()
                    return good
                wait(acquired, 'Finite IA_NA/DAD/RA default not ready')
                report = verify(manager, 'PC1', 'PC2', family='ipv6', bidirectional=True, count=2)
                self.assertEqual(report['status'], 'passed', report)
                self.assertTrue(all(d['reply_hop_limits'] == [62, 62] for d in report['directions']), report)
                self.assertEqual(manager.ns(0, 'sysctl', '-n', 'net/ipv6/conf/eth0/autoconf').stdout.strip(), '0')
                return addresses()[0]['local']
            def rogue_identity():
                actual = manager.inspect('ROGUE')
                mac = next(r['address'] for r in actual['links'] if r['ifname'] == 'eth0')
                source = next(a['local'] for row in actual['addresses_ipv6'] for a in row.get('addr_info', []) if a.get('scope') == 'link')
                return source, rogue_frames(mac, source)
            def inject(frames):
                code = ('import socket,sys,json,time; s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)); s.bind(("eth0",0)); '
                        '\nfor frame in json.loads(sys.argv[1]): s.send(bytes.fromhex(frame)); time.sleep(.05)\ns.close()')
                manager.ns(4, sys.executable, '-I', '-c', code, json.dumps([f.hex() for f in frames]), timeout=3)
            def no_rogue_default(source):
                self.assertFalse(any(r.get('gateway') == source for r in defaults()))
            def processes(action='list', selector='--conf-file=/lab/ra.conf'):
                return manager.crun('exec', 'R1', '/bin/sh', '-c', PROCESS_SCRIPT, 'ra-dhcp6-service', action, selector, timeout=3).stdout.splitlines()
            def refuse_save():
                with manager.locked(), self.assertRaises(RuntimeFailure): manager.write_startup()
            try:
                with manager.locked(): manager.start(spec)
                ready(); source, frames = rogue_identity()
                events = [threading.Event(), threading.Event()]; paths = [root / 'client.pcap', root / 'rogue.pcap']
                futures = [pool.submit(capture, Manager(spec['name']), name, port, path,
                                      seconds=16, packets=500, snaplen=2048, ready=event.set)
                           for name, port, path, event in zip(('PC1', 'SW1'), ('eth0', 'eth2'), paths, events)]
                for event, future in zip(events, futures):
                    if not event.wait(5):
                        if future.done(): future.result()
                        self.fail('DHCPv6/RA Guard capture did not become ready')
                signal('USR2'); wait(lambda: not addresses(), 'Release failed', 5)
                self.assertTrue(defaults(), 'DHCPv6 release removed the independent RA default')
                blocked = verify(manager, 'PC1', 'PC2', family='ipv6', count=1)
                self.assertEqual(blocked['status'], 'blocked'); self.assertEqual(blocked['probe_commands_attempted'], 0)
                signal('USR1'); learned = ready(); signal('USR1')
                wait(lambda: addresses() and addresses()[0]['valid_life_time'] >= 117, 'Renew did not refresh finite lease', 10)
                inject(frames.values()); solicit_ipv6_router(manager, 0); ready(); no_rogue_default(source)
                for future in futures: self.assertGreater(future.result(timeout=22)['captured_packets'], 0)
                data = paths[0].read_bytes(); packets = captured_dhcpv6(data)
                self.assertTrue({1, 2, 3, 5, 7, 8} <= {p['type'] for p in packets}, packets)
                for kind in (3, 5):
                    self.assertTrue(any(q['xid'] == r['xid'] and q['client_ids'] == r['client_ids'] and q['server_ids'] == r['server_ids'] and
                                        q['client_ids'] and q['server_ids'] for q in packets if q['type'] == kind for r in packets if r['type'] == 7), packets)
                self.assertTrue(any(a['address'] == learned and a['preferred'] == a['valid'] == 120 for p in packets if p['type'] == 7 for a in p['addresses']), packets)
                ras = [r for r in captured_ras(data) if any(p['network'] == '2001:db8:10::/64' for p in r['prefixes'])]
                self.assertTrue(ras); self.assertTrue(all(r['source'] != source and r['managed'] and r['hop_limit'] == 255 and 25 not in r['options'] and
                                                        all(not p['autonomous'] and p['on_link'] for p in r['prefixes']) for r in ras), ras)
                self.assertIn(defaults()[0]['gateway'], {r['source'] for r in ras})
                ingress = pcap_frames(paths[1].read_bytes())
                for name, frame in frames.items(): self.assertIn(frame, ingress, name)
                raw_source = ipaddress.IPv6Address(source).packed
                self.assertFalse(any(len(f) >= 55 and f[12:14] == b'\x86\xdd' and f[22:38] == raw_source and
                                     (f[20] in (0, 44, 60) or (f[20] == 58 and f[54] == 134)) for f in pcap_frames(data)))
                guard = manager.inspect('SW1')['ra_guard']; self.assertTrue(guard['policy_verified'])
                for reason in ('ra', 'opaque'): self.assertGreater(guard['ports']['eth2']['counters'][reason]['packets'], 0)
                self.assertGreater(guard['ports']['eth0']['counters']['pass']['packets'], 0)
                # Stop the matched local RA+DHCP service, preserving topology
                # and the installed guard. No address/default is seeded.
                self.assertEqual(processes(), processes(selector='all')); self.assertEqual(len(processes()), 1)
                processes('stop'); wait(lambda: not processes(), 'Managed service did not stop', 5)
                signal('USR2'); wait(lambda: not addresses(), 'Release while service absent failed', 5); signal('USR1')
                until = time.monotonic() + 6
                while time.monotonic() < until:
                    self.assertFalse(addresses(), 'Lease acquired with no server'); time.sleep(.2)
                inject(frames.values())
                wait(lambda: ipv6_default_expired(manager, 0, '2001:db8:20::20'), 'RA default did not expire during combined outage', 25)
                no_rogue_default(source); self.assertTrue(manager.inspect('SW1')['ra_guard']['policy_verified'])
                self.assertTrue(manager.inspect('R1')['router_advertisements']['configuration_verified'])
                start_servers(manager); signal('USR1'); ready()
                manager.ns(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/autoconf=1'); refuse_save()
                manager.ns(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/autoconf=0')
                hook = manager.directory / 'PC1/files/dhcpv6-client.sh'; hook.write_text('# changed\n'); refuse_save(); hook.write_text(CLIENT_SCRIPT)
                config = manager.directory / 'R1/files/ra.conf'; original = config.read_text(); config.write_text(original + '\n'); refuse_save(); config.write_text(original)
                with manager.locked(): manager.write_startup()
                saved = load_startup(spec['name']); self.assertEqual(saved, spec)
                self.assertEqual(saved['nodes'][0]['ipv6'], {}); self.assertEqual(saved['nodes'][0]['ipv6_routes'], [])
                self.assertEqual(saved['nodes'][0]['dhcpv6_clients'], ['eth0'])
                manager.ns(5, 'nft', 'flush', 'chain', 'bridge', 'network_labs_ra_guard', 'ingress'); refuse_save()
                with manager.locked(): manager.stop(); manager.start(saved)
                ready(); source, frames = rogue_identity(); inject(frames.values()); ready(); no_rogue_default(source)
                with manager.locked(): manager.write_startup()
                # With autoconf=0, absence of a rogue SLAAC address alone would
                # prove nothing. Explicitly trusting the same sender must let
                # the valid RA install its default while IA_NA stays separate.
                trusted = copy.deepcopy(saved); trusted['nodes'][5]['ra_guard']['trusted'].append('eth2')
                with manager.locked(): manager.stop(); manager.start(trusted)
                ready(); source, frames = rogue_identity(); inject([frames['plain']])
                wait(lambda: any(r.get('gateway') == source for r in defaults()), 'Trusted rogue RA positive control failed')
                self.assertEqual(len(addresses()), 1); self.assertEqual(addresses()[0]['prefixlen'], 128)
                self.assertEqual(manager.ns(0, 'sysctl', '-n', 'net/ipv6/conf/eth0/autoconf').stdout.strip(), '0')
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
