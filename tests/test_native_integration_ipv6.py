"""Opt-in real OCI boot/packet tests. IPv6 on real containers: dual stack, routed LANs, SLAAC, DHCPv6 IA_NA, NDP
isolation per VLAN.

Run as test_native_integration says (NETWORK_LABS_NATIVE_TESTS=1, on a disposable Linux host with sudo).
"""
import os
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.verify import verify

from test_native_integration import NATIVE, RealContainerCase, ipv6_default_expired, solicit_ipv6_router


@unittest.skipUnless(NATIVE, 'Opt-in privileged native test')
class IPv6Tests(RealContainerCase):
    def test_appliance_aa_dual_stack_independent_forwarding_routes_capture_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import dual_stack_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        baseline = {(family, kind): run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for family in ('-4', '-6') for kind in ('route', 'rule')}
        sysctls = {key: run(['sysctl', '-n', key]).stdout for key in ('net.ipv4.ip_forward', 'net.ipv6.conf.all.forwarding')}
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = dual_stack_lab(rootfs)
            spec['name'] = 'dual-' + str(os.getpid())
            manager = Manager(spec['name'])
            def check(family, expected='passed'):
                report = verify(manager, 'PC1', 'PC2', family=family, count=2, bidirectional=True)
                self.assertEqual(report['status'], expected, report)
                if expected == 'passed':
                    key = 'reply_ttls' if family == 'ipv4' else 'reply_hop_limits'
                    self.assertTrue(all(d[key] == [62, 62] and d['received'] == d['transmitted'] == 2 for d in report['directions']),
                                    report)
                self.assertFalse(report['configuration_changed'])
                return report
            def healthy():
                check('ipv4')
                check('ipv6')
            try:
                with manager.locked():
                    manager.start(spec)
                    healthy()
                    before = json.loads(json.dumps(manager.read()))
                    for name in ('R1', 'R2'):
                        observed = manager.inspect(name)
                        self.assertTrue(observed['forwarding'])
                        self.assertEqual(observed['forwarding_ipv6'], '1')
                event = threading.Event()
                pcap = Path(folder) / 'dual-stack.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC2', 'eth0', pcap,
                                     seconds=7, packets=200, expression='icmp or icmp6', ready=event.set)
                self.assertTrue(event.wait(5), 'Dual-stack capture did not become ready')
                with manager.locked():
                    healthy()
                self.assertGreater(future.result(timeout=10)['captured_packets'], 0)
                decoded = run(['tcpdump', '-nn', '-vv', '-r', str(pcap)]).stdout
                for evidence in ('192.0.2.10', '198.51.100.20', '2001:db8:10::10', '2001:db8:20::20',
                                 'ttl 62', 'hlim 62', 'echo request', 'echo reply'):
                    self.assertIn(evidence, decoded)
                with manager.locked():
                    manager.ns(1, 'sysctl', '-w', 'net.ipv4.ip_forward=0')
                    check('ipv4', 'failed')
                    check('ipv6')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    manager.ns(1, 'sysctl', '-w', 'net.ipv4.ip_forward=1')
                    healthy()
                    manager.ns(1, 'sysctl', '-w', 'net/ipv6/conf/all/forwarding=0')
                    check('ipv6', 'failed')
                    check('ipv4')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    manager.ns(1, 'sysctl', '-w', 'net/ipv6/conf/all/forwarding=1')
                    healthy()
                    manager.ns(1, 'ip', '-4', 'route', 'del', '198.51.100.0/24')
                    check('ipv4', 'failed')
                    check('ipv6')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    manager.ns(1, 'ip', '-4', 'route', 'add', '198.51.100.0/24', 'via', '198.18.0.2', 'dev', 'eth1', 'proto', 'static')
                    healthy()
                    manager.ns(1, 'ip', '-6', 'route', 'del', '2001:db8:20::/64')
                    check('ipv6', 'failed')
                    check('ipv4')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    manager.ns(1, 'ip', '-6', 'route', 'add', '2001:db8:20::/64', 'via', '2001:db8:100::2', 'dev', 'eth1', 'proto',
                               'static')
                    healthy()
                    self.assertEqual(manager.read(), before)
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertTrue(saved['nodes'][1]['forwarding'])
                    self.assertTrue(saved['nodes'][1]['ipv6_forwarding'])
                    self.assertEqual(saved['nodes'][0]['gateway'], '192.0.2.1')
                    self.assertEqual(saved['nodes'][0]['ipv6_routes'][0]['gateway'], '2001:db8:10::1')
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    healthy()
                    manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        for (family, kind), expected in baseline.items():
            self.assertEqual(run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, expected)
        for key, expected in sysctls.items():
            self.assertEqual(run(['sysctl', '-n', key]).stdout, expected)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)

    def test_appliance_aa_ipv6_dhcpv6_ia_na_ra_renew_expiry_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import ipaddress
        from network_labs.appliances.examples import dhcpv6_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.slaac import start_servers as start_ra
        from network_labs.appliances.dhcpv6 import start_clients, CLIENT_SCRIPT
        from network_labs.appliances.firewall import fingerprint
        from test_native_slaac import captured_ras
        from test_native_dhcpv6 import captured_dhcpv6
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        routes = run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout
        rules = run(['ip', '-j', '-6', 'rule', 'show']).stdout
        forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', dnsmasq=shutil.which('dnsmasq'))
            spec = dhcpv6_lab(rootfs)
            spec['name'] = 'dhcpv6-' + str(os.getpid())
            manager = Manager(spec['name'])
            def addresses():
                return [a for row in json.loads(manager.ns(0, 'ip', '-j', '-6', 'addr', 'show', 'dev', 'eth0').stdout)
                        for a in row.get('addr_info', []) if a.get('scope') == 'global']
            def defaults():
                return [r for r in json.loads(manager.ns(0, 'ip', '-j', '-6', 'route', 'show', 'table',
                        'main').stdout) if r.get('dst') == 'default' and (type(r.get('expires')) is not int or r['expires'] > 0)]
            def wait(predicate, label, seconds=30):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(.2)
                logs = [(manager.directory / p).read_text(errors='replace')[-4000:] for p in ('PC1/dhcpv6.log',
                        'R1/ra.log') if (manager.directory / p).exists()]
                self.fail('DHCPv6 timeout: ' + label + '; PC1=' + json.dumps(manager.inspect('PC1')) + '; logs=' + repr(logs))
            def ready():
                def acquired():
                    ips, routes = addresses(), defaults()
                    return (len(ips) == 1 and ipaddress.IPv6Address('2001:db8:10::100') <= ipaddress.IPv6Address(ips[0]['local'])
                            <= ipaddress.IPv6Address('2001:db8:10::10f') and
                            ips[0]['prefixlen'] == 128 and isinstance(ips[0].get('valid_life_time'),
                                                                      int) and 0 < ips[0]['valid_life_time'] <= 120 and
                            not ips[0].get('tentative') and not ips[0].get('dadfailed') and
                            not any(f in ips[0].get('flags', []) for f in ('tentative', 'dadfailed')) and
                            len(routes) == 1 and routes[0].get('protocol') == 'ra' and routes[0].get('dev') == 'eth0' and
                            ipaddress.IPv6Address(routes[0].get('gateway', '::')).is_link_local)
                wait(acquired, 'actual DHCPv6 /128 with finite lifetime, DAD and RA default')
                observed = addresses()[0]['local']
                report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2, bidirectional=True)
                self.assertEqual(report['status'], 'passed', report)
                self.assertEqual(report['endpoints'][0]['address'], observed)
                self.assertEqual(report['directions'][1]['destination_address'], observed)
                self.assertTrue(all(d['reply_hop_limits'] == [62, 62] for d in report['directions']), report)
                self.assertFalse(report['configuration_changed'])
                return observed
            def signal(value):
                manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -' + value + ' "$(/bin/cat /run/udhcpc6.pid)"')
            try:
                with manager.locked():
                    manager.start(spec)
                    ready()
                event = threading.Event()
                pcap = Path(folder) / 'dhcpv6.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', pcap,
                                     seconds=12, packets=300, expression='ip6', ready=event.set)
                self.assertTrue(event.wait(5), 'DHCPv6 capture did not become ready')
                with manager.locked():
                    solicit_ipv6_router(manager, 0)
                    signal('USR2')
                    wait(lambda: not addresses(), 'release removes global address')
                    report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
                    self.assertEqual(report['status'], 'blocked', report)
                    self.assertEqual(report['probe_commands_attempted'], 0)
                    self.assertTrue(defaults(), 'DHCPv6 release must preserve RA default')
                    signal('USR1')
                    learned = ready()
                    signal('USR1')
                    time.sleep(1)
                    ready()
                self.assertGreater(future.result(timeout=15)['captured_packets'], 0)
                data = pcap.read_bytes()
                packets = captured_dhcpv6(data)
                decoded = run(['tcpdump', '-nn', '-vv', '-r', str(pcap)]).stdout
                for evidence in (learned, '2001:db8:20::20', 'echo request', 'echo reply', 'hlim 62'):
                    self.assertIn(evidence, decoded)
                self.assertTrue({1, 2, 3, 5, 7}.issubset({p['type'] for p in packets}), packets)
                for kind in (3, 5):
                    requests = [p for p in packets if p['type'] == kind]
                    self.assertTrue(any(q['xid'] == r['xid'] and q['client_ids'] == r['client_ids'] and q['server_ids'] == r['server_ids']
                                        and q['client_ids'] and q['server_ids'] for q in requests for r in packets if r['type'] == 7),
                        packets)
                self.assertTrue(any(a['address'] == learned and a['preferred'] == a['valid'] == 120 for p in packets if p['type'] == 7
                                    for a in p['addresses']), packets)
                announcements = [r for r in captured_ras(data) if any(p['network'] == '2001:db8:10::/64' for p in r['prefixes'])]
                self.assertTrue(announcements)
                for ra in announcements:
                    self.assertEqual(ra['hop_limit'], 255)
                    self.assertTrue(ra['managed'])
                    self.assertEqual(ra['router_lifetime'], 15)
                    self.assertNotIn(25, ra['options'])
                    self.assertTrue(all(not p['autonomous'] and p['on_link'] for p in ra['prefixes']))
                with manager.locked():
                    self.assertIn(defaults()[0]['gateway'], {r['source'] for r in announcements})
                    manager.ns(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/autoconf=1')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    manager.ns(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/autoconf=0')
                    hook = manager.directory / 'PC1/files/dhcpv6-client.sh'
                    hook.write_text('# changed\n')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    hook.write_text(CLIENT_SCRIPT)
                    manager.crun('exec', 'R1', '/bin/busybox', 'killall', '-TERM', 'dnsmasq')
                    signal('USR2')
                    wait(lambda: not addresses(), 'released while server absent')
                    signal('USR1')
                    time.sleep(4)
                    self.assertFalse(addresses())
                    self.assertTrue(manager.inspect('R1')['router_advertisements']['configuration_verified'])
                    wait(lambda: ipv6_default_expired(manager, 0, '2001:db8:20::20'),
                         'RA expiry and failed kernel route selection while server stopped', seconds=25)
                    start_ra(manager)
                    ready()
                    # Without either daemon the kernel must expire the leased address.
                    signal('TERM')
                    manager.crun('exec', 'R1', '/bin/busybox', 'killall', '-TERM', 'dnsmasq')
                    wait(lambda: not addresses(), 'finite DHCPv6 address expiry without client/server', seconds=130)
                    report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
                    self.assertEqual(report['status'], 'blocked', report)
                    self.assertEqual(report['probe_commands_attempted'], 0)
                    result = manager.crun('exec', 'PC1', '/bin/busybox', 'ping6', '-c', '1', '-W', '1', '-w', '2', '2001:db8:20::20',
                                          check=False, timeout=4)
                    self.assertNotEqual(result.returncode, 0)
                    start_ra(manager)
                    start_clients(manager)
                    ready()
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertEqual(saved['nodes'][0]['ipv6'], {})
                    self.assertEqual(saved['nodes'][0]['ipv6_routes'], [])
                    self.assertEqual(saved['nodes'][0]['dhcpv6_clients'], ['eth0'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    ready()
                    manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout, routes)
        self.assertEqual(run(['ip', '-j', '-6', 'rule', 'show']).stdout, rules)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout, forwarding)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)

    def test_appliance_aa_ipv6_routed_lans_forwarding_routes_capture_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import ipv6_routed_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.show import show
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        routes = run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout
        rules = run(['ip', '-j', '-6', 'rule', 'show']).stdout
        forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = ipv6_routed_lab(rootfs)
            spec['name'] = 'ipv6-route-' + str(os.getpid())
            manager = Manager(spec['name'])
            def ping(source='PC1', target='2001:db8:20::20', check=True):
                return manager.crun('exec', source, '/bin/busybox', 'ping6', '-c', '2', '-W', '1', '-w', '4', target,
                                    check=check, timeout=6)
            def healthy():
                report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2, bidirectional=True)
                self.assertEqual(report['status'], 'passed', report)
                self.assertTrue(all(d['reply_hop_limits'] == [62, 62] for d in report['directions']), report)
            try:
                with manager.locked():
                    manager.start(spec)
                    healthy()
                    report = show(manager, 'R1', 'show ipv6 route')
                    self.assertEqual(report['status'], 'observed', report)
                    self.assertTrue(any(r.get('dst') == '2001:db8:20::/64' and r.get('gateway') == '2001:db8:100::2'
                                        for r in report['observation']['records']), report)
                    self.assertEqual(manager.inspect('R1')['forwarding_ipv6'], '1')
                    self.assertEqual(manager.inspect('PC1')['forwarding_ipv6'], '0')
                event = threading.Event()
                pcap = Path(folder) / 'routed-ipv6.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC2', 'eth0', pcap,
                                     seconds=4, packets=100, expression='icmp6', ready=event.set)
                self.assertTrue(event.wait(5), 'Routed IPv6 capture did not become ready')
                with manager.locked():
                    healthy()
                self.assertGreater(future.result(timeout=7)['captured_packets'], 0)
                decoded = run(['tcpdump', '-nn', '-vv', '-r', str(pcap)]).stdout
                for value in ('2001:db8:10::10', '2001:db8:20::20', 'hlim 62', 'echo request', 'echo reply'):
                    self.assertIn(value, decoded)
                with manager.locked():
                    # A route alone does not prove IPv6 forwarding is enabled.
                    manager.ns(1, 'sysctl', '-w', 'net/ipv6/conf/all/forwarding=0')
                    self.assertNotEqual(ping(check=False).returncode, 0)
                    report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
                    self.assertEqual(report['status'], 'failed', report)
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    manager.ns(1, 'sysctl', '-w', 'net/ipv6/conf/all/forwarding=1')
                    healthy()
                    # Remove the forward route, then the far host's return route.
                    manager.ns(1, 'ip', '-6', 'route', 'del', '2001:db8:20::/64')
                    self.assertNotEqual(ping(check=False).returncode, 0)
                    report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
                    self.assertEqual(report['status'], 'failed', report)
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    manager.ns(1, 'ip', '-6', 'route', 'add', '2001:db8:20::/64', 'via', '2001:db8:100::2', 'dev', 'eth1', 'proto',
                               'static')
                    healthy()
                    manager.ns(3, 'ip', '-6', 'route', 'del', 'default')
                    self.assertNotEqual(ping(check=False).returncode, 0)
                    report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
                    self.assertEqual(report['status'], 'failed', report)
                    manager.ns(3, 'ip', '-6', 'route', 'add', 'default', 'via', '2001:db8:20::1', 'dev', 'eth0', 'proto', 'static')
                    healthy()
                    before = json.loads(json.dumps(manager.read()))
                    manager.ns(0, 'ip', 'link', 'set', 'eth0', 'down')
                    report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
                    self.assertEqual(report['status'], 'blocked', report)
                    self.assertEqual(report['probe_commands_attempted'], 0)
                    manager.ns(0, 'ip', 'link', 'set', 'eth0', 'up')
                    # Linux may remove global IPv6 addresses on admin-down.
                    # Restore declared policy explicitly; verify never repairs it.
                    manager.ns(0, 'ip', '-6', 'addr', 'replace', '2001:db8:10::10/64', 'dev', 'eth0')
                    from network_labs.appliances.ipv6 import wait_addresses
                    wait_addresses(manager, 0, manager.read()['spec']['nodes'][0])
                    manager.ns(0, 'ip', '-6', 'route', 'replace', 'default', 'via', '2001:db8:10::1', 'dev', 'eth0', 'proto', 'static')
                    healthy()
                    manager.ns(0, 'ip', '-6', 'addr', 'add', '2001:db8:10::99/64', 'dev', 'eth0')
                    report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
                    self.assertEqual(report['status'], 'unknown', report)
                    self.assertIn('AMBIGUOUS_IPV6', report['endpoints'][0]['reasons'])
                    self.assertEqual(report['probe_commands_attempted'], 0)
                    manager.ns(0, 'ip', '-6', 'addr', 'del', '2001:db8:10::99/64', 'dev', 'eth0')
                    self.assertEqual(manager.read(), before)
                    healthy()
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    healthy()
                    manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout, routes)
        self.assertEqual(run(['ip', '-j', '-6', 'rule', 'show']).stdout, rules)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout, forwarding)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)

    def test_appliance_aa_ipv6_slaac_real_ra_defaults_expiry_reacquire_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import ipaddress
        from network_labs.appliances.examples import slaac_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.slaac import start_servers as start_ra
        from network_labs.appliances.firewall import fingerprint
        from test_native_slaac import captured_ras
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        routes = run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout
        rules = run(['ip', '-j', '-6', 'rule', 'show']).stdout
        forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', dnsmasq=shutil.which('dnsmasq'))
            spec = slaac_lab(rootfs)
            spec['name'] = 'slaac-' + str(os.getpid())
            manager = Manager(spec['name'])
            def addresses():
                return [a for row in json.loads(manager.ns(0, 'ip', '-j', '-6', 'addr', 'show', 'dev', 'eth0').stdout)
                        for a in row.get('addr_info', []) if a.get('scope') == 'global']
            def defaults():
                return [r for r in json.loads(manager.ns(0, 'ip', '-j', '-6', 'route', 'show', 'table',
                        'main').stdout) if r.get('dst') == 'default' and (type(r.get('expires')) is not int or r['expires'] > 0)]
            def wait(predicate, label, seconds=30):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(.2)
                ra_log = manager.directory / 'R1' / 'ra.log'
                self.fail('SLAAC timeout: ' + label + '; PC1=' + json.dumps(manager.inspect('PC1')) + '; R1='
                        + json.dumps(manager.inspect('R1')) + '; RA log=' + (ra_log.read_text(errors='replace')[-4000:]
                                                                             if ra_log.exists() else 'missing'))
            def ready():
                def acquired():
                    ips, routes = addresses(), defaults()
                    return (len(ips) == 1 and ipaddress.IPv6Address(ips[0]['local']) in ipaddress.IPv6Network('2001:db8:10::/64') and
                            not ips[0].get('tentative') and not ips[0].get('dadfailed') and
                            not any(f in ips[0].get('flags', []) for f in ('tentative', 'dadfailed')) and
                            len(routes) == 1 and routes[0].get('protocol') == 'ra' and routes[0].get('dev') == 'eth0' and
                            ipaddress.IPv6Address(routes[0].get('gateway', '::')).is_link_local)
                wait(acquired, 'actual global address, completed DAD and RA default')
                observed = addresses()[0]['local']
                report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2, bidirectional=True)
                self.assertEqual(report['status'], 'passed', report)
                self.assertEqual(report['endpoints'][0]['address'], observed)
                self.assertEqual(report['directions'][1]['destination_address'], observed)
                self.assertTrue(all(d['reply_hop_limits'] == [62, 62] for d in report['directions']), report)
                self.assertFalse(report['configuration_changed'])
                return observed
            try:
                with manager.locked():
                    manager.start(spec)
                    ready()
                    self.assertEqual(manager.read()['spec']['nodes'][0]['ipv6'], {})
                    self.assertEqual(manager.read()['spec']['nodes'][0]['ipv6_routes'], [])
                event = threading.Event()
                pcap = Path(folder) / 'slaac.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', pcap,
                                     seconds=8, packets=200, expression='icmp6', ready=event.set)
                self.assertTrue(event.wait(5), 'SLAAC capture did not become ready')
                with manager.locked():
                    solicit_ipv6_router(manager, 0)
                    ready()
                self.assertGreater(future.result(timeout=11)['captured_packets'], 0)
                announcements = captured_ras(pcap.read_bytes())
                relevant = [r for r in announcements if any(p['network'] == '2001:db8:10::/64' for p in r['prefixes'])]
                self.assertTrue(relevant, announcements)
                for ra in relevant:
                    self.assertEqual(ra['hop_limit'], 255)
                    self.assertEqual(ra['router_lifetime'], 15)
                    self.assertTrue(ipaddress.IPv6Address(ra['source']).is_link_local)
                    self.assertFalse(ra['managed'])
                    self.assertFalse(ra['other'])
                    self.assertNotIn(25, ra['options'], 'No RDNSS should be advertised without DNS service')
                    self.assertTrue(all(p['autonomous'] and p['on_link'] for p in ra['prefixes']))
                with manager.locked():
                    self.assertIn(defaults()[0]['gateway'], {r['source'] for r in relevant})
                    self.assertTrue(manager.inspect('R1')['router_advertisements']['configuration_verified'])
                    manager.ns(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/accept_ra=0')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    manager.ns(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/accept_ra=1')
                    ready()
                    # Stopped service has intact declarations but no renewed defaults.
                    manager.crun('exec', 'R1', '/bin/busybox', 'killall', '-TERM', 'dnsmasq')
                    wait(lambda: ipv6_default_expired(manager, 0, '2001:db8:20::20'),
                         'RA default withdrawal/expiry and failed kernel route selection', seconds=25)
                    result = manager.crun('exec', 'PC1', '/bin/busybox', 'ping6', '-c', '1', '-W', '1', '-w', '2',
                                          '2001:db8:20::20', check=False, timeout=4)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue(manager.inspect('R1')['router_advertisements']['configuration_verified'])
                    manager.ns(0, 'ip', '-6', 'addr', 'flush', 'dev', 'eth0', 'scope', 'global')
                    time.sleep(3)
                    self.assertFalse(addresses())
                    self.assertTrue(ipv6_default_expired(manager, 0, '2001:db8:20::20'))
                    report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
                    self.assertEqual(report['status'], 'blocked', report)
                    self.assertEqual(report['probe_commands_attempted'], 0)
                    start_ra(manager)
                    ready()
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertEqual(saved['nodes'][0]['ipv6'], {})
                    self.assertEqual(saved['nodes'][0]['ipv6_routes'], [])
                    self.assertEqual(saved['nodes'][0]['slaac'], ['eth0'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    ready()
                    manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout, routes)
        self.assertEqual(run(['ip', '-j', '-6', 'rule', 'show']).stdout, rules)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout, forwarding)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)

    def test_appliance_aa_ipv6_vlan_ndp_isolation_capture_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import ipv6_vlan_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.show import show
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        routes = run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout
        rules = run(['ip', '-j', '-6', 'rule', 'show']).stdout
        forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = ipv6_vlan_lab(rootfs)
            spec['name'] = 'ipv6-' + str(os.getpid())
            manager = Manager(spec['name'])
            def ping(source, address, check=True):
                return manager.crun('exec', source, '/bin/busybox', 'ping6', '-c', '2', '-W', '1', '-w', '4', address,
                                    check=check, timeout=6)
            def ready():
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    rows = [r for i in range(4) for r in json.loads(manager.ns(i, 'ip', '-j', '-6', 'addr', 'show', 'dev', 'eth0').stdout)]
                    global_ips = [a for r in rows for a in r.get('addr_info', []) if a.get('scope') == 'global']
                    if len(global_ips) == 4 and not any(a.get('tentative') or a.get('dadfailed') or any(f in a.get('flags',
                            []) for f in ('tentative', 'dadfailed')) for a in global_ips):
                        break
                    time.sleep(.2)
                else:
                    self.fail('IPv6 DAD did not complete')
                for source, target in (('PC1', '2001:db8:10::20'), ('PC2', '2001:db8:10::10'),
                                       ('PC3', '2001:db8:20::20'), ('PC4', '2001:db8:20::10')):
                    self.assertIn('0% packet loss', ping(source, target).stdout)
            try:
                with manager.locked():
                    manager.start(spec)
                    ready()
                    self.assertEqual(show(manager, 'PC1', 'show ipv6 interface brief')['status'], 'observed')
                    self.assertEqual(show(manager, 'PC1', 'show ipv6 neighbors')['status'], 'observed')
                    # Deliberately put a same-prefix address in the other VLAN.
                    # A failed off-subnet ping alone would not prove VLAN isolation.
                    manager.ns(2, 'ip', '-6', 'addr', 'add', '2001:db8:10::30/64', 'dev', 'eth0')
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        addresses = [a for row in json.loads(manager.ns(2, 'ip', '-j', '-6', 'addr', 'show', 'dev', 'eth0').stdout)
                                     for a in row.get('addr_info', []) if a.get('local') == '2001:db8:10::30']
                        if len(addresses) == 1 and not (addresses[0].get('tentative') or addresses[0].get('dadfailed') or
                                any(f in addresses[0].get('flags', []) for f in ('tentative', 'dadfailed'))):
                            break
                        time.sleep(.2)
                    else:
                        self.fail('Cross-VLAN test address did not finish DAD')
                    self.assertNotEqual(ping('PC1', '2001:db8:10::30', check=False).returncode, 0)
                    manager.ns(2, 'ip', '-6', 'addr', 'del', '2001:db8:10::30/64', 'dev', 'eth0')
                    manager.ns(0, 'ip', '-6', 'neigh', 'flush', 'dev', 'eth0')
                event = threading.Event()
                pcap = Path(folder) / 'ipv6.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'SW1', 'eth2', pcap,
                                     seconds=5, packets=200, expression='', ready=event.set)
                self.assertTrue(event.wait(5), 'IPv6 capture did not become ready')
                with manager.locked():
                    ready()
                self.assertGreater(future.result(timeout=8)['captured_packets'], 0)
                decoded = run(['tcpdump', '-nn', '-e', '-vv', '-r', str(pcap)]).stdout
                for expected in ('vlan 10', 'vlan 20', 'IPv6', 'neighbor solicitation', 'neighbor advertisement'):
                    self.assertIn(expected, decoded)
                with manager.locked():
                    manager.ns(0, 'ip', '-6', 'addr', 'add', '2001:db8:10::99/64', 'dev', 'eth0')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    manager.ns(0, 'ip', '-6', 'addr', 'del', '2001:db8:10::99/64', 'dev', 'eth0')
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    ready()
                    manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout, routes)
        self.assertEqual(run(['ip', '-j', '-6', 'rule', 'show']).stdout, rules)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout, forwarding)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)


if __name__ == '__main__':
    unittest.main()
