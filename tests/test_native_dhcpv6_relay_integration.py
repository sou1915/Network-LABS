"""Actual relayed IA_NA, independent managed RA, outages, wire evidence and restore."""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
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
from network_labs.appliances.dhcpv6_relay import processes, start_one, stop_one
from network_labs.appliances.examples import dhcpv6_relay_lab
from network_labs.appliances.ospf import processes as bird_processes
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.verify import verify
from test_native_dhcpv6_relay import captured_relays
from test_native_integration import unexpected_host_link_changes
from test_native_slaac import captured_ras


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeDHCPv6RelayTests(unittest.TestCase):
    def test_real_remote_ia_na_relay_ra_packets_outages_drift_and_saved_restart(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('dnsmasq', 'bird', 'birdc', 'busybox', 'crun', 'ip', 'tcpdump'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        host_routes = run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout
        host_rules = run(['ip', '-j', '-6', 'rule', 'show']).stdout
        host_forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        host_links = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder)
            rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs',
                        dnsmasq=shutil.which('dnsmasq'), bird=shutil.which('bird'), birdc=shutil.which('birdc'))
            spec = dhcpv6_relay_lab(rootfs); spec['name'] = 'dhcp6-relay-' + str(os.getpid())
            relay, server = spec['nodes'][1:3]; manager = Manager(spec['name'])
            def addresses():
                return [a for row in json.loads(manager.ns(0, 'ip', '-j', '-6', 'addr', 'show', 'dev', 'eth0').stdout)
                        for a in row.get('addr_info', []) if a.get('scope') == 'global']
            def defaults():
                return [r for r in json.loads(manager.ns(0, 'ip', '-j', '-6', 'route', 'show', 'table', 'main').stdout)
                        if r.get('dst') == 'default' and r.get('protocol') == 'ra' and r.get('dev') == 'eth0' and
                           ipaddress.IPv6Address(r.get('gateway', '::')).is_link_local]
            def wait(predicate, label, seconds=40):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if predicate(): return
                    time.sleep(.2)
                logs = {str(p.relative_to(manager.directory)): p.read_text(errors='replace')[-4000:]
                        for p in manager.directory.glob('*/*.log')}
                self.fail(label + ': addresses=' + repr(addresses()) + '; routes=' + repr(defaults()) + '; logs=' + repr(logs))
            def signal(value):
                manager.crun('exec', 'PC1', '/bin/sh', '-c',
                             'pid=$(/bin/busybox cat /run/udhcpc6.pid); [ "$pid" -gt 1 ]; /bin/busybox kill -' + value + ' "$pid"')
            def ready():
                def acquired():
                    values = addresses()
                    return (len(values) == 1 and
                            ipaddress.IPv6Address('2001:db8:10::100') <= ipaddress.IPv6Address(values[0]['local']) <= ipaddress.IPv6Address('2001:db8:10::10f') and
                            values[0]['prefixlen'] == 128 and 0 < values[0].get('valid_life_time', 0) <= 120 and
                            not values[0].get('tentative') and not values[0].get('dadfailed') and
                            not any(f in values[0].get('flags', []) for f in ('tentative', 'dadfailed')) and bool(defaults()))
                wait(acquired, 'Relayed finite IA_NA and RA default not acquired')
                learned = addresses()[0]['local']
                for source, target in (('PC1', '2001:db8:20::20'), ('PC2', learned)):
                    wait(lambda: manager.crun('exec', source, '/bin/busybox', 'ping6', '-c', '1', '-W', '1', '-w', '2',
                                             target, check=False, timeout=4).returncode == 0, 'DHCPv6 routed delivery unavailable', 12)
                report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2, bidirectional=True)
                self.assertEqual(report['status'], 'passed', report)
                self.assertTrue(all(d['reply_hop_limits'] == [62, 62] for d in report['directions']), report)
                return learned
            def release():
                signal('USR2'); wait(lambda: not addresses(), 'DHCPv6 release did not remove address', 5)
                self.assertTrue(defaults(), 'DHCPv6 release must preserve independent RA default')
            def no_allocation():
                signal('USR1')
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    self.assertFalse(addresses(), 'Client acquired a lease despite the missing relay/server')
                    time.sleep(.2)
                self.assertTrue(defaults(), 'DHCP service outage must not stop RA')
                report = verify(manager, 'PC1', 'PC2', family='ipv6', count=1)
                self.assertEqual(report['status'], 'blocked', report)
                self.assertEqual(report['probe_commands_attempted'], 0)
            try:
                with manager.locked(): manager.start(spec)
                initial_lease = ready()
                self.assertTrue(manager.inspect('R1')['dhcpv6_relay']['configuration_verified'])
                self.assertTrue(manager.inspect('R2')['dhcpv6_remote_server']['configuration_verified'])
                upstream, downstream = root / 'relay-up.pcap', root / 'relay-client.pcap'
                up_ready, down_ready = threading.Event(), threading.Event()
                up = pool.submit(capture, Manager(spec['name']), 'R1', 'eth1', upstream,
                                 seconds=15, packets=400, snaplen=2048, expression='ip6', ready=up_ready.set)
                down = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', downstream,
                                   seconds=15, packets=400, snaplen=2048, expression='ip6', ready=down_ready.set)
                for event, future in ((up_ready, up), (down_ready, down)):
                    if not event.wait(5):
                        if future.done(): future.result()
                        self.fail('DHCPv6 relay capture did not become ready')
                release(); signal('USR1'); learned = ready()
                self.assertGreater(up.result(timeout=20)['captured_packets'], 0)
                self.assertGreater(down.result(timeout=20)['captured_packets'], 0)
                packets = captured_relays(upstream.read_bytes())
                self.assertTrue({12, 13} <= {p['type'] for p in packets}, packets)
                self.assertTrue({1, 2, 3, 7} <= {p['inner_type'] for p in packets}, packets)
                self.assertTrue(all(p['link'] == '2001:db8:10::1' and p['hop_count'] == 0 for p in packets), packets)
                for packet in packets:
                    # Solicit/Advertise/Request use the client's link-local
                    # source. Release and its Reply may use its leased address.
                    peer = ipaddress.IPv6Address(packet['peer'])
                    self.assertTrue(peer.is_link_local or
                                    (packet['inner_type'] in (8, 7) and str(peer) == initial_lease), packet)
                requests = [p for p in packets if p['type'] == 12 and p['inner_type'] == 3]
                replies = [p for p in packets if p['type'] == 13 and p['inner_type'] == 7 and p['addresses']]
                self.assertTrue(any(q['xid'] == r['xid'] and q['client_ids'] == r['client_ids'] and
                                    q['server_ids'] == r['server_ids'] and q['client_ids'] and q['server_ids']
                                    for q in requests for r in replies), packets)
                self.assertTrue(any(a['address'] == learned and a['preferred'] == a['valid'] == 120
                                    for p in replies for a in p['addresses']), packets)
                ras = [r for r in captured_ras(downstream.read_bytes())
                       if any(p['network'] == '2001:db8:10::/64' for p in r['prefixes'])]
                self.assertTrue(ras)
                for ra in ras:
                    self.assertEqual(ra['hop_limit'], 255); self.assertTrue(ra['managed']); self.assertFalse(ra['other'])
                    self.assertTrue(ipaddress.IPv6Address(ra['source']).is_link_local)
                    self.assertGreater(ra['router_lifetime'], 0); self.assertNotIn(25, ra['options'])
                    self.assertTrue(all(not p['autonomous'] and p['on_link'] for p in ra['prefixes']))
                # Keep RA and server unchanged while the actual relay stops.
                server_pids = processes(manager, server); ra_pids = bird_processes(manager, relay)
                stop_one(manager, relay); release(); no_allocation()
                self.assertEqual(processes(manager, server), server_pids)
                self.assertEqual(bird_processes(manager, relay), ra_pids)
                start_one(manager, relay); ready()
                # Separately stop the allocator: the relay must not invent leases.
                stop_one(manager, server); release(); no_allocation()
                start_one(manager, server); ready()
                for target in ('R1/files/dhcpv6-relay.conf', 'R1/files/bird.conf', 'R2/files/dhcpv6-remote.conf'):
                    path = manager.directory / target; original = path.read_text()
                    try:
                        path.write_text(original + '# external drift\n')
                        with manager.locked(), self.assertRaises(RuntimeFailure): manager.write_startup()
                    finally: path.write_text(original)
                with manager.locked():
                    manager.write_startup(); saved = load_startup(spec['name'])
                    self.assertEqual(saved, spec); self.assertEqual(saved['nodes'][0]['ipv6'], {})
                    manager.stop(); manager.start(saved)
                ready()
                with manager.locked(): manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        self.assertEqual(run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout, host_routes)
        self.assertEqual(run(['ip', '-j', '-6', 'rule', 'show']).stdout, host_rules)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout, host_forwarding)
        after = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        # Hosted Azure runners can hotplug a physical VF. Verify hardware via
        # sysfs, preserve every baseline link identity and reject added virtual
        # interfaces; never exempt a device merely because of its name.
        hardware = {name for name, _ in after - host_links if (Path('/sys/class/net') / name / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(host_links, after, hardware),
                         {'removed_or_replaced': set(), 'added_virtual': set()})
