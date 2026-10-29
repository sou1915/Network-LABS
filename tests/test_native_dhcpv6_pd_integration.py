"""Real Kea IA_PD, finite requesting-router LAN, SLAAC, renewal/expiry and restore."""
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
from network_labs.appliances.dhcpv6_pd import start_server, stop_server
from network_labs.appliances.examples import dhcpv6_pd_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.verify import verify
from test_native_dhcpv6_pd import captured_pd
from test_native_integration import unexpected_host_link_changes, solicit_ipv6_router
from test_native_slaac import captured_ras


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativePDTests(unittest.TestCase):
    def test_actual_pd_slaac_wire_renew_expiry_recovery_drift_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('kea-dhcp6', 'dnsmasq', 'busybox', 'crun', 'ip', 'tcpdump', 'cc'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        baseline = {(kind): run(['ip', '-j', '-6', kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for kind in ('route', 'rule')}
        forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        before = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder); hook = root / 'pd-hook'
            source = Path(__file__).parents[1] / 'network_labs/appliances/dhcpv6_pd_hook.c'
            run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', source, '-o', hook])
            rootfs = static_busybox_rootfs(os.environ.get('NETWORK_LABS_PD_BUSYBOX', shutil.which('busybox')), root / 'rootfs', dnsmasq=shutil.which('dnsmasq'),
                                          kea_dhcp6=shutil.which('kea-dhcp6'), dhcpv6_pd_hook=hook)
            spec = dhcpv6_pd_lab(rootfs); spec['name'] = 'pd-lan-' + str(os.getpid())
            manager = Manager(spec['name']); server = spec['nodes'][2]
            def addresses(index, port):
                return [a for row in json.loads(manager.ns(index, 'ip', '-j', '-6', 'addr', 'show', 'dev', port).stdout)
                        for a in row.get('addr_info', []) if a.get('scope') == 'global']
            def delegated(): return addresses(1, 'eth0')
            def wait(predicate, label, seconds=45):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if predicate(): return
                    time.sleep(.2)
                logs = {str(p.relative_to(manager.directory)): p.read_text(errors='replace')[-5000:]
                        for p in manager.directory.glob('*/*.log')}
                self.fail(label + ': CE=' + repr(manager.inspect('R1')) + '; host=' + repr(manager.inspect('PC1')) + '; logs=' + repr(logs))
            def signal(value):
                manager.crun('exec', 'R1', '/bin/sh', '-c',
                             'pid=$(/bin/busybox cat /run/pd-client.pid); [ "$pid" -gt 1 ]; /bin/busybox kill -' + value + ' "$pid"')
            def ready():
                def configured():
                    gw, host = delegated(), addresses(0, 'eth0')
                    return (len(gw) == 1 and gw[0]['local'] == '2001:db8:10::1' and gw[0]['prefixlen'] == 64 and
                            0 < gw[0].get('valid_life_time', 0) <= 30 and not gw[0].get('tentative') and
                            not gw[0].get('dadfailed') and 'tentative' not in gw[0].get('flags', []) and
                            len(host) == 1 and ipaddress.IPv6Address(host[0]['local']) in ipaddress.IPv6Network('2001:db8:10::/64') and
                            not host[0].get('tentative') and not host[0].get('dadfailed') and 'tentative' not in host[0].get('flags', []))
                wait(configured, 'Delegated gateway and downstream SLAAC did not become ready')
                target = addresses(0, 'eth0')[0]['local']
                for name, destination in (('PC1', '2001:db8:20::20'), ('PC2', target)):
                    wait(lambda: manager.crun('exec', name, '/bin/busybox', 'ping6', '-c', '1', '-W', '1', '-w', '2',
                                             destination, check=False, timeout=4).returncode == 0, 'PD routed delivery unavailable', 12)
                result = verify(manager, 'PC1', 'PC2', family='ipv6', bidirectional=True, count=2)
                self.assertEqual(result['status'], 'passed', result)
                self.assertTrue(all(d['reply_hop_limits'] == [62, 62] for d in result['directions']), result)
            try:
                with manager.locked(): manager.start(spec)
                ready()
                self.assertNotIn('eth0', manager.state['spec']['nodes'][1]['ipv6'])
                events = [threading.Event(), threading.Event()]; paths = [root / 'pd-up.pcap', root / 'pd-lan.pcap']
                futures = [pool.submit(capture, Manager(spec['name']), name, port, path,
                                      seconds=20, packets=400, snaplen=2048, expression='ip6', ready=event.set)
                           for name, port, path, event in zip(('R1', 'PC1'), ('eth1', 'eth0'), paths, events)]
                for event, future in zip(events, futures):
                    if not event.wait(5):
                        if future.done(): future.result()
                        self.fail('PD packet capture did not become ready')
                signal('USR2'); wait(lambda: not delegated(), 'PD release did not remove LAN gateway', 5)
                signal('USR1'); ready(); signal('USR1')
                wait(lambda: delegated() and delegated()[0]['valid_life_time'] >= 28, 'PD renewal did not extend finite gateway lifetime', 10)
                solicit_ipv6_router(manager, 0)
                for future in futures: self.assertGreater(future.result(timeout=25)['captured_packets'], 0)
                packets = captured_pd(paths[0].read_bytes())
                self.assertTrue({1, 2, 3, 5, 7, 8} <= {p['type'] for p in packets}, packets)
                self.assertTrue(all(not p['ia_na'] for p in packets), packets)
                replies = [p for p in packets if p['type'] == 7 and any(q['valid'] == 30 for q in p['prefixes'])]
                for kind in (3, 5):
                    self.assertTrue(any(q['xid'] == r['xid'] and q['client_ids'] == r['client_ids'] and
                                        q['server_ids'] == r['server_ids'] and q['client_ids'] and q['server_ids']
                                        for q in packets if q['type'] == kind for r in replies), packets)
                self.assertTrue(any(q == {'prefix': '2001:db8:10::/64', 'preferred': 30, 'valid': 30}
                                    for r in replies for q in r['prefixes']), packets)
                ras = [r for r in captured_ras(paths[1].read_bytes()) if r['router_lifetime'] > 0]
                self.assertTrue(ras)
                self.assertTrue(all(not r['managed'] and r['hop_limit'] == 255 and 25 not in r['options'] and
                                    any(p['network'] == '2001:db8:10::/64' and p['autonomous'] and p['on_link'] for p in r['prefixes'])
                                    for r in ras), ras)
                # No renewal after server outage: kernel lifetime independently
                # bounds the gateway even if the client process remains alive.
                stop_server(manager, server)
                wait(lambda: not delegated(), 'PD gateway survived lease expiry without its server', 45)
                routes = json.loads(manager.ns(1, 'ip', '-j', '-6', 'route', 'show', 'table', 'main').stdout)
                self.assertFalse(any(r.get('dst') == '2001:db8:10::/64' and r.get('dev') == 'eth0' for r in routes))
                self.assertEqual(addresses(1, 'eth1')[0]['local'], '2001:db8:100::2')
                failed = manager.crun('exec', 'PC2', '/bin/busybox', 'ping6', '-c', '1', '-W', '1', '-w', '2',
                                      addresses(0, 'eth0')[0]['local'] if addresses(0, 'eth0') else '2001:db8:10::123', check=False, timeout=4)
                self.assertNotEqual(failed.returncode, 0)
                start_server(manager, server); signal('USR1'); ready()
                for target in ('R1/files/dhcpv6-pd.policy', 'R1/files/pd-ra.conf', 'R2/files/kea-pd.json'):
                    path = manager.directory / target; original = path.read_text()
                    try:
                        path.write_text(original + '\n')
                        with manager.locked(), self.assertRaises(RuntimeFailure): manager.write_startup()
                    finally: path.write_text(original)
                manager.ns(1, 'ip', '-6', 'addr', 'add', '2001:db8:10::99/64', 'dev', 'eth0')
                with manager.locked(), self.assertRaises(RuntimeFailure): manager.write_startup()
                manager.ns(1, 'ip', '-6', 'addr', 'del', '2001:db8:10::99/64', 'dev', 'eth0')
                with manager.locked():
                    manager.write_startup(); saved = load_startup(spec['name'])
                    self.assertEqual(saved, spec); self.assertNotIn('eth0', saved['nodes'][1]['ipv6'])
                    manager.stop(); manager.start(saved)
                ready()
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
