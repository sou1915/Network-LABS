"""Real trusted SLAAC, untrusted RA/EH/fragment/tag drops, and cold restore."""
from concurrent.futures import ThreadPoolExecutor
import copy
import ipaddress
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.capture import capture
from network_labs.appliances.examples import ra_guard_lab
from network_labs.appliances.firewall import fingerprint
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.verify import verify
from test_native_integration import solicit_ipv6_router, unexpected_host_link_changes
from test_native_ra_guard import rogue_frames
from test_native_slaac import captured_ras


def pcap_frames(data):
    endian = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>'}.get(data[:4])
    if endian is None or len(data) < 24 or struct.unpack(endian + 'I', data[20:24])[0] != 1:
        raise ValueError('Expected Ethernet pcap')
    result = []; offset = 24
    while offset + 16 <= len(data):
        size = struct.unpack(endian + 'IIII', data[offset:offset + 16])[2]; offset += 16
        frame = data[offset:offset + size]; offset += size
        if len(frame) != size: raise ValueError('Truncated pcap frame')
        result.append(frame)
    return result


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeRAGuardTests(unittest.TestCase):
    def test_trusted_slaac_untrusted_ra_variants_counters_drift_restore_and_trust_control(self):
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
            spec = ra_guard_lab(rootfs); spec['name'] = 'ra-guard-' + str(os.getpid()); manager = Manager(spec['name'])
            def records(index):
                return json.loads(manager.ns(index, 'ip', '-j', '-6', 'addr', 'show', 'dev', 'eth0').stdout)
            def globals_on_client():
                return [a for row in records(0) for a in row.get('addr_info', []) if a.get('scope') == 'global']
            def defaults():
                return [r for r in json.loads(manager.ns(0, 'ip', '-j', '-6', 'route', 'show', 'table', 'main').stdout)
                        if r.get('dst') == 'default' and r.get('protocol') == 'ra' and r.get('expires', 0) > 0]
            def wait(predicate, label, seconds=30):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if predicate(): return
                    time.sleep(.2)
                self.fail(label + ': client=' + repr(manager.inspect('PC1')) + '; guard=' + repr(manager.inspect('SW1')))
            def healthy():
                solicit_ipv6_router(manager, 0)
                wait(lambda: any(ipaddress.IPv6Address(a['local']) in ipaddress.IPv6Network('2001:db8:10::/64') and
                                 a.get('preferred_life_time', 0) > 0 and not a.get('tentative') and
                                 'tentative' not in a.get('flags', []) for a in globals_on_client()) and defaults(), 'Trusted SLAAC/default absent')
                def ping():
                    return manager.crun('exec', 'PC1', '/bin/busybox', 'ping6', '-c', '1', '-W', '1', '-w', '2',
                                        '2001:db8:20::20', check=False, timeout=4).returncode == 0
                wait(ping, 'Trusted router delivery failed', 12)
                result = verify(manager, 'PC1', 'PC2', family='ipv6', bidirectional=True, count=2)
                self.assertEqual(result['status'], 'passed', result)
                self.assertTrue(all(d['reply_hop_limits'] == [62, 62] for d in result['directions']), result)
            def rogue_identity():
                actual = manager.inspect('ROGUE')
                mac = next(r['address'] for r in actual['links'] if r['ifname'] == 'eth0')
                address = next(a['local'] for row in records(4) for a in row.get('addr_info', []) if a.get('scope') == 'link')
                return address, rogue_frames(mac, address)
            def inject(frames, repeats=3):
                code = ('import socket,sys,json,time; s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)); '
                        's.bind(("eth0",0)); frames=json.loads(sys.argv[1]); '
                        '\nfor _ in range(' + str(repeats) + '):\n for frame in frames: s.send(bytes.fromhex(frame)); time.sleep(.05)\ns.close()')
                manager.ns(4, sys.executable, '-I', '-c', code, json.dumps([frame.hex() for frame in frames]), timeout=5)
            def no_poison(address):
                self.assertFalse(any(ipaddress.IPv6Address(a['local']) in ipaddress.IPv6Network('2001:db8:666::/64') for a in globals_on_client()))
                self.assertFalse(any(r.get('gateway') == address for r in defaults()))
            def refuse_save():
                with manager.locked(), self.assertRaises(RuntimeFailure): manager.write_startup()
            try:
                with manager.locked(): manager.start(spec)
                healthy(); address, frames = rogue_identity()
                events = [threading.Event(), threading.Event()]; paths = [root / 'rogue-ingress.pcap', root / 'client-egress.pcap']
                futures = [pool.submit(capture, Manager(spec['name']), name, port, path,
                                      seconds=8, packets=400, snaplen=2048, ready=event.set)
                           for name, port, path, event in zip(('SW1', 'PC1'), ('eth2', 'eth0'), paths, events)]
                for event, future in zip(events, futures):
                    if not event.wait(5):
                        if future.done(): future.result()
                        self.fail('RA Guard capture did not become ready')
                inject(frames.values()); solicit_ipv6_router(manager, 0)
                # Ordinary untrusted IPv6 NDP/echo remains usable.
                target = globals_on_client()[0]['local']
                self.assertEqual(manager.crun('exec', 'ROGUE', '/bin/busybox', 'ping6', '-c', '2', '-W', '1', '-w', '4',
                                             target, check=False, timeout=6).returncode, 0)
                healthy()
                for future in futures: self.assertGreater(future.result(timeout=15)['captured_packets'], 0)
                ingress = pcap_frames(paths[0].read_bytes()); egress = pcap_frames(paths[1].read_bytes())
                for name, frame in frames.items(): self.assertIn(frame, ingress, name)
                source = ipaddress.IPv6Address(address).packed
                malicious = [f for f in egress if len(f) >= 55 and f[12:14] == b'\x86\xdd' and f[22:38] == source and
                             (f[20] in (0, 44, 60) or (f[20] == 58 and f[54] == 134))]
                self.assertEqual(malicious, [], 'Untrusted RA/extension/fragment reached the client')
                ras = captured_ras(paths[1].read_bytes())
                self.assertTrue(any(r['source'] != address and r['hop_limit'] == 255 and
                                    any(p['network'] == '2001:db8:10::/64' for p in r['prefixes']) for r in ras), ras)
                no_poison(address)
                observed = manager.inspect('SW1')['ra_guard']; self.assertTrue(observed['policy_verified'])
                self.assertGreater(observed['ports']['eth2']['counters']['ra']['packets'], 0)
                self.assertGreater(observed['ports']['eth2']['counters']['opaque']['packets'], 0)
                self.assertGreater(observed['ports']['eth2']['counters']['pass']['packets'], 0)
                self.assertGreater(observed['ports']['eth1']['counters']['trusted']['packets'], 0)
                with manager.locked(): manager.write_startup()
                saved = load_startup(spec['name']); self.assertEqual(saved, spec)
                self.assertEqual(saved['nodes'][0]['ipv6'], {}); self.assertEqual(saved['nodes'][0]['ipv6_routes'], [])
                manager.ns(5, 'nft', 'add', 'table', 'bridge', 'unmanaged_guard_test'); refuse_save()
                manager.ns(5, 'nft', 'delete', 'table', 'bridge', 'unmanaged_guard_test')
                manager.ns(5, 'nft', 'flush', 'chain', 'bridge', 'network_labs_ra_guard', 'ingress'); refuse_save()
                with manager.locked(): manager.stop(); manager.start(saved)
                healthy(); address, frames = rogue_identity(); inject(frames.values()); healthy(); no_poison(address)
                self.assertTrue(manager.inspect('SW1')['ra_guard']['policy_verified'])
                with manager.locked(): manager.write_startup()
                # Positive control: the exact valid plain RA must be accepted
                # after explicitly trusting that ingress on a recreated switch.
                trusted = copy.deepcopy(saved); trusted['nodes'][5]['ra_guard']['trusted'].append('eth2')
                with manager.locked(): manager.stop(); manager.start(trusted)
                healthy(); address, frames = rogue_identity(); inject([frames['plain']])
                wait(lambda: any(ipaddress.IPv6Address(a['local']) in ipaddress.IPv6Network('2001:db8:666::/64') for a in globals_on_client()) and
                     any(r.get('gateway') == address for r in defaults()), 'Trusted positive-control RA was not accepted')
                self.assertGreater(manager.inspect('SW1')['ra_guard']['ports']['eth2']['counters']['trusted']['packets'], 0)
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
