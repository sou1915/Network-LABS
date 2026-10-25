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
from network_labs.appliances.verify import verify


def unexpected_host_link_changes(before, after, hardware_names=()):
    return {'removed_or_replaced': before - after,
            'added_virtual': {entry for entry in after - before if entry[0] not in hardware_names}}


def solicit_ipv6_router(manager, index):
    """Send a real Router Solicitation after capture readiness, not a fake RA.

    A fixed capture window need not overlap an unsolicited advertisement.
    Linux supplies the ICMPv6 checksum and the interface link-local source.
    """
    code = (
        "import socket; index=socket.if_nametoindex('eth0'); "
        "sock=socket.socket(socket.AF_INET6,socket.SOCK_RAW,socket.IPPROTO_ICMPV6); "
        "sock.settimeout(2); sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_MULTICAST_IF,index); "
        "sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_MULTICAST_HOPS,255); "
        "sock.sendto(bytes([133,0,0,0,0,0,0,0]),('ff02::2',0,0,index)); sock.close()"
    )
    manager.ns(index, sys.executable, '-I', '-c', code, timeout=3)


def ipv6_default_expired(manager, index, destination):
    """Expired fib6 entries may remain observable until GC releases them.

    Require actual elapsed lifetime (or absence) AND failed kernel selection;
    never flush the route or confuse an absent source address with this check.
    """
    routes = json.loads(manager.ns(index, 'ip', '-j', '-6', 'route', 'show', 'table', 'main').stdout)
    defaults = [r for r in routes if r.get('dst') == 'default']
    if any(type(r.get('expires')) is not int or r['expires'] > 0 for r in defaults):
        return False
    return manager.ns(index, 'ip', '-6', 'route', 'get', destination, check=False, timeout=3).returncode != 0


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class RealContainerTests(unittest.TestCase):
    def assertHostLinksUnchanged(self, before, after):
        # Hosted runners may hotplug a hardware-backed Azure VF mid-job.
        # Preserve every baseline identity and reject all added virtual links;
        # the engine cannot create a PCI device. Do not whitelist by name.
        hardware = {name for name, _ in after - before if (Path('/sys/class/net') / name / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before, after, hardware),
                         {'removed_or_replaced': set(), 'added_virtual': set()})

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
        links = host_links(); routes = run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout
        rules = run(['ip', '-j', '-6', 'rule', 'show']).stdout
        forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', dnsmasq=shutil.which('dnsmasq'))
            spec = dhcpv6_lab(rootfs); spec['name'] = 'dhcpv6-' + str(os.getpid())
            manager = Manager(spec['name'])
            def addresses():
                return [a for row in json.loads(manager.ns(0, 'ip', '-j', '-6', 'addr', 'show', 'dev', 'eth0').stdout)
                        for a in row.get('addr_info', []) if a.get('scope') == 'global']
            def defaults():
                return [r for r in json.loads(manager.ns(0, 'ip', '-j', '-6', 'route', 'show', 'table', 'main').stdout) if r.get('dst') == 'default' and (type(r.get('expires')) is not int or r['expires'] > 0)]
            def wait(predicate, label, seconds=30):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if predicate(): return
                    time.sleep(.2)
                logs = [(manager.directory / p).read_text(errors='replace')[-4000:] for p in ('PC1/dhcpv6.log', 'R1/ra.log') if (manager.directory / p).exists()]
                self.fail('DHCPv6 timeout: ' + label + '; PC1=' + json.dumps(manager.inspect('PC1')) + '; logs=' + repr(logs))
            def ready():
                def acquired():
                    ips, routes = addresses(), defaults()
                    return (len(ips) == 1 and ipaddress.IPv6Address('2001:db8:10::100') <= ipaddress.IPv6Address(ips[0]['local']) <= ipaddress.IPv6Address('2001:db8:10::10f') and
                            ips[0]['prefixlen'] == 128 and isinstance(ips[0].get('valid_life_time'), int) and 0 < ips[0]['valid_life_time'] <= 120 and
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
                with manager.locked(): manager.start(spec); ready()
                event = threading.Event(); pcap = Path(folder) / 'dhcpv6.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', pcap,
                                     seconds=12, packets=300, expression='ip6', ready=event.set)
                self.assertTrue(event.wait(5), 'DHCPv6 capture did not become ready')
                with manager.locked():
                    solicit_ipv6_router(manager, 0)
                    signal('USR2'); wait(lambda: not addresses(), 'release removes global address')
                    report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
                    self.assertEqual(report['status'], 'blocked', report)
                    self.assertEqual(report['probe_commands_attempted'], 0)
                    self.assertTrue(defaults(), 'DHCPv6 release must preserve RA default')
                    signal('USR1'); learned = ready()
                    signal('USR1'); time.sleep(1); ready()
                self.assertGreater(future.result(timeout=15)['captured_packets'], 0)
                data = pcap.read_bytes(); packets = captured_dhcpv6(data)
                decoded = run(['tcpdump', '-nn', '-vv', '-r', str(pcap)]).stdout
                for evidence in (learned, '2001:db8:20::20', 'echo request', 'echo reply', 'hlim 62'):
                    self.assertIn(evidence, decoded)
                self.assertTrue({1, 2, 3, 5, 7}.issubset({p['type'] for p in packets}), packets)
                for kind in (3, 5):
                    requests = [p for p in packets if p['type'] == kind]
                    self.assertTrue(any(q['xid'] == r['xid'] and q['client_ids'] == r['client_ids'] and q['server_ids'] == r['server_ids']
                                        and q['client_ids'] and q['server_ids'] for q in requests for r in packets if r['type'] == 7), packets)
                self.assertTrue(any(a['address'] == learned and a['preferred'] == a['valid'] == 120 for p in packets if p['type'] == 7 for a in p['addresses']), packets)
                announcements = [r for r in captured_ras(data) if any(p['network'] == '2001:db8:10::/64' for p in r['prefixes'])]
                self.assertTrue(announcements)
                for ra in announcements:
                    self.assertEqual(ra['hop_limit'], 255); self.assertTrue(ra['managed'])
                    self.assertEqual(ra['router_lifetime'], 15); self.assertNotIn(25, ra['options'])
                    self.assertTrue(all(not p['autonomous'] and p['on_link'] for p in ra['prefixes']))
                with manager.locked():
                    self.assertIn(defaults()[0]['gateway'], {r['source'] for r in announcements})
                    manager.ns(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/autoconf=1')
                    with self.assertRaises(RuntimeFailure): manager.write_startup()
                    manager.ns(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/autoconf=0')
                    hook = manager.directory / 'PC1/files/dhcpv6-client.sh'
                    hook.write_text('# changed\n')
                    with self.assertRaises(RuntimeFailure): manager.write_startup()
                    hook.write_text(CLIENT_SCRIPT)
                    manager.crun('exec', 'R1', '/bin/busybox', 'killall', '-TERM', 'dnsmasq')
                    signal('USR2'); wait(lambda: not addresses(), 'released while server absent')
                    signal('USR1'); time.sleep(4); self.assertFalse(addresses())
                    self.assertTrue(manager.inspect('R1')['router_advertisements']['configuration_verified'])
                    wait(lambda: ipv6_default_expired(manager, 0, '2001:db8:20::20'), 'RA expiry and failed kernel route selection while server stopped', seconds=25)
                    start_ra(manager); ready()
                    # Without either daemon the kernel must expire the leased address.
                    signal('TERM')
                    manager.crun('exec', 'R1', '/bin/busybox', 'killall', '-TERM', 'dnsmasq')
                    wait(lambda: not addresses(), 'finite DHCPv6 address expiry without client/server', seconds=130)
                    report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
                    self.assertEqual(report['status'], 'blocked', report)
                    self.assertEqual(report['probe_commands_attempted'], 0)
                    result = manager.crun('exec', 'PC1', '/bin/busybox', 'ping6', '-c', '1', '-W', '1', '-w', '2', '2001:db8:20::20', check=False, timeout=4)
                    self.assertNotEqual(result.returncode, 0)
                    start_ra(manager); start_clients(manager); ready()
                    manager.write_startup(); saved = load_startup(spec['name'])
                    self.assertEqual(saved['nodes'][0]['ipv6'], {}); self.assertEqual(saved['nodes'][0]['ipv6_routes'], [])
                    self.assertEqual(saved['nodes'][0]['dhcpv6_clients'], ['eth0'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked(): manager.start(saved); ready(); manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
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
        links = host_links(); routes = run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout
        rules = run(['ip', '-j', '-6', 'rule', 'show']).stdout
        forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = ipv6_routed_lab(rootfs); spec['name'] = 'ipv6-route-' + str(os.getpid())
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
                    manager.start(spec); healthy()
                    report = show(manager, 'R1', 'show ipv6 route')
                    self.assertEqual(report['status'], 'observed', report)
                    self.assertTrue(any(r.get('dst') == '2001:db8:20::/64' and r.get('gateway') == '2001:db8:100::2'
                                        for r in report['observation']['records']), report)
                    self.assertEqual(manager.inspect('R1')['forwarding_ipv6'], '1')
                    self.assertEqual(manager.inspect('PC1')['forwarding_ipv6'], '0')
                event = threading.Event(); pcap = Path(folder) / 'routed-ipv6.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC2', 'eth0', pcap,
                                     seconds=4, packets=100, expression='icmp6', ready=event.set)
                self.assertTrue(event.wait(5), 'Routed IPv6 capture did not become ready')
                with manager.locked(): healthy()
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
                    with self.assertRaises(RuntimeFailure): manager.write_startup()
                    manager.ns(1, 'sysctl', '-w', 'net/ipv6/conf/all/forwarding=1'); healthy()
                    # Remove the forward route, then the far host's return route.
                    manager.ns(1, 'ip', '-6', 'route', 'del', '2001:db8:20::/64')
                    self.assertNotEqual(ping(check=False).returncode, 0)
                    report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
                    self.assertEqual(report['status'], 'failed', report)
                    with self.assertRaises(RuntimeFailure): manager.write_startup()
                    manager.ns(1, 'ip', '-6', 'route', 'add', '2001:db8:20::/64', 'via', '2001:db8:100::2', 'dev', 'eth1', 'proto', 'static')
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
                    manager.write_startup(); saved = load_startup(spec['name']); manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); healthy(); manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
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
        links = host_links(); routes = run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout
        rules = run(['ip', '-j', '-6', 'rule', 'show']).stdout
        forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', dnsmasq=shutil.which('dnsmasq'))
            spec = slaac_lab(rootfs); spec['name'] = 'slaac-' + str(os.getpid())
            manager = Manager(spec['name'])
            def addresses():
                return [a for row in json.loads(manager.ns(0, 'ip', '-j', '-6', 'addr', 'show', 'dev', 'eth0').stdout)
                        for a in row.get('addr_info', []) if a.get('scope') == 'global']
            def defaults():
                return [r for r in json.loads(manager.ns(0, 'ip', '-j', '-6', 'route', 'show', 'table', 'main').stdout) if r.get('dst') == 'default' and (type(r.get('expires')) is not int or r['expires'] > 0)]
            def wait(predicate, label, seconds=30):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if predicate(): return
                    time.sleep(.2)
                ra_log = manager.directory / 'R1' / 'ra.log'
                self.fail('SLAAC timeout: ' + label + '; PC1=' + json.dumps(manager.inspect('PC1')) + '; R1=' + json.dumps(manager.inspect('R1')) + '; RA log=' + (ra_log.read_text(errors='replace')[-4000:] if ra_log.exists() else 'missing'))
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
                    manager.start(spec); ready()
                    self.assertEqual(manager.read()['spec']['nodes'][0]['ipv6'], {})
                    self.assertEqual(manager.read()['spec']['nodes'][0]['ipv6_routes'], [])
                event = threading.Event(); pcap = Path(folder) / 'slaac.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', pcap,
                                     seconds=8, packets=200, expression='icmp6', ready=event.set)
                self.assertTrue(event.wait(5), 'SLAAC capture did not become ready')
                with manager.locked():
                    solicit_ipv6_router(manager, 0); ready()
                self.assertGreater(future.result(timeout=11)['captured_packets'], 0)
                announcements = captured_ras(pcap.read_bytes())
                relevant = [r for r in announcements if any(p['network'] == '2001:db8:10::/64' for p in r['prefixes'])]
                self.assertTrue(relevant, announcements)
                for ra in relevant:
                    self.assertEqual(ra['hop_limit'], 255)
                    self.assertEqual(ra['router_lifetime'], 15)
                    self.assertTrue(ipaddress.IPv6Address(ra['source']).is_link_local)
                    self.assertFalse(ra['managed']); self.assertFalse(ra['other'])
                    self.assertNotIn(25, ra['options'], 'No RDNSS should be advertised without DNS service')
                    self.assertTrue(all(p['autonomous'] and p['on_link'] for p in ra['prefixes']))
                with manager.locked():
                    self.assertIn(defaults()[0]['gateway'], {r['source'] for r in relevant})
                    self.assertTrue(manager.inspect('R1')['router_advertisements']['configuration_verified'])
                    manager.ns(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/accept_ra=0')
                    with self.assertRaises(RuntimeFailure): manager.write_startup()
                    manager.ns(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/accept_ra=1'); ready()
                    # Stopped service has intact declarations but no renewed defaults.
                    manager.crun('exec', 'R1', '/bin/busybox', 'killall', '-TERM', 'dnsmasq')
                    wait(lambda: ipv6_default_expired(manager, 0, '2001:db8:20::20'), 'RA default withdrawal/expiry and failed kernel route selection', seconds=25)
                    result = manager.crun('exec', 'PC1', '/bin/busybox', 'ping6', '-c', '1', '-W', '1', '-w', '2',
                                          '2001:db8:20::20', check=False, timeout=4)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue(manager.inspect('R1')['router_advertisements']['configuration_verified'])
                    manager.ns(0, 'ip', '-6', 'addr', 'flush', 'dev', 'eth0', 'scope', 'global')
                    time.sleep(3)
                    self.assertFalse(addresses()); self.assertTrue(ipv6_default_expired(manager, 0, '2001:db8:20::20'))
                    report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
                    self.assertEqual(report['status'], 'blocked', report)
                    self.assertEqual(report['probe_commands_attempted'], 0)
                    start_ra(manager); ready()
                    manager.write_startup(); saved = load_startup(spec['name'])
                    self.assertEqual(saved['nodes'][0]['ipv6'], {})
                    self.assertEqual(saved['nodes'][0]['ipv6_routes'], [])
                    self.assertEqual(saved['nodes'][0]['slaac'], ['eth0'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); ready(); manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
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
        links = host_links(); routes = run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout
        rules = run(['ip', '-j', '-6', 'rule', 'show']).stdout
        forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = ipv6_vlan_lab(rootfs); spec['name'] = 'ipv6-' + str(os.getpid())
            manager = Manager(spec['name'])
            def ping(source, address, check=True):
                return manager.crun('exec', source, '/bin/busybox', 'ping6', '-c', '2', '-W', '1', '-w', '4', address,
                                    check=check, timeout=6)
            def ready():
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    rows = [r for i in range(4) for r in json.loads(manager.ns(i, 'ip', '-j', '-6', 'addr', 'show', 'dev', 'eth0').stdout)]
                    global_ips = [a for r in rows for a in r.get('addr_info', []) if a.get('scope') == 'global']
                    if len(global_ips) == 4 and not any(a.get('tentative') or a.get('dadfailed') or any(f in a.get('flags', []) for f in ('tentative', 'dadfailed')) for a in global_ips):
                        break
                    time.sleep(.2)
                else:
                    self.fail('IPv6 DAD did not complete')
                for source, target in (('PC1', '2001:db8:10::20'), ('PC2', '2001:db8:10::10'),
                                       ('PC3', '2001:db8:20::20'), ('PC4', '2001:db8:20::10')):
                    self.assertIn('0% packet loss', ping(source, target).stdout)
            try:
                with manager.locked():
                    manager.start(spec); ready()
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
                event = threading.Event(); pcap = Path(folder) / 'ipv6.pcap'
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
                    with self.assertRaises(RuntimeFailure): manager.write_startup()
                    manager.ns(0, 'ip', '-6', 'addr', 'del', '2001:db8:10::99/64', 'dev', 'eth0')
                    manager.write_startup(); saved = load_startup(spec['name']); manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); ready()
                    manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout, routes)
        self.assertEqual(run(['ip', '-j', '-6', 'rule', 'show']).stdout, rules)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout, forwarding)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)

    def test_appliance_aa_lan_services_routed_dns_http_failures_pcap_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import lan_services_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.dns import start_servers as start_dns
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.verify import verify
        from network_labs.appliances.service_probe import probe
        from network_labs.appliances.firewall import fingerprint
        from test_native_dns import DNS_QUERY, dns_response
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                bird=shutil.which('bird'), birdc=shutil.which('birdc'), dnsmasq=shutil.which('dnsmasq'),
                lldpd=shutil.which('lldpd'), lldpcli=shutil.which('lldpcli'))
            spec = lan_services_lab(rootfs); spec['name'] = 'services-' + str(os.getpid())
            manager = Manager(spec['name'])
            def wait(predicate, label):
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.2)
                details = {n: manager.inspect(n) for n in ('PC1', 'PC3', 'SW1', 'R1', 'DNS1', 'PC2')}
                self.fail('Timed out: ' + label + '; observations=' + json.dumps(details))
            def query(index=0, host='web.lab.test', kind=1, transport='udp', check=True):
                return manager.ns(index, sys.executable, '-c', DNS_QUERY, host, str(kind), transport,
                                  '198.18.0.4', check=check, timeout=5)
            def web(client='PC1', host='web.lab.test', check=True):
                return manager.crun('exec', client, '/bin/busybox', 'timeout', '8', '/bin/busybox',
                    'wget', '-T', '3', '-q', '-O', '-', 'http://' + host + '/', check=check, timeout=11)
            def ready():
                for client, address in (('PC1', '192.0.2.100'), ('PC3', '198.51.100.100')):
                    index = 0 if client == 'PC1' else 6
                    wait(lambda: any(a.get('local') == address for row in json.loads(manager.ns(index,
                        'ip', '-j', '-4', 'addr', 'show', 'dev', 'eth0').stdout) for a in row.get('addr_info', [])), 'DHCP address ' + client)
                    resolver = manager.crun('exec', client, '/bin/cat', '/etc/resolv.conf').stdout
                    self.assertEqual(resolver, 'nameserver 198.18.0.4\n')
                wait(lambda: web(host='203.0.113.10', check=False).returncode == 0, 'actual routed HTTP delivery')
                for client in ('PC1', 'PC3'):
                    self.assertIn('Network LABS routed HTTP', web(client).stdout)
                    before = json.dumps(manager.read(), sort_keys=True)
                    application = probe(manager, client, 'web.lab.test')
                    self.assertEqual(application['status'], 'passed', application)
                    self.assertEqual([stage['stage'] for stage in application['stages']], ['dns', 'tcp', 'http'])
                    self.assertEqual(application['stages'][-1]['http_status'], 200)
                    self.assertEqual(json.dumps(manager.read(), sort_keys=True), before)
                self.assertEqual(verify(manager, 'PC1', 'PC2', count=1, bidirectional=True)['status'], 'passed')
                observed = manager.inspect('SW2')['lldp']['neighbor_summary']
                self.assertEqual(observed['status'], 'observed')
                self.assertEqual({n['system_name'] for n in observed['neighbors']}, {'SW1', 'R1'})
            try:
                with manager.locked():
                    manager.start(spec); ready()
                    from network_labs.appliances.show import show, render as render_show
                    before_show = json.dumps(manager.read(), sort_keys=True)
                    for command in ('show lldp neighbors', 'show lldp neighbors detail'):
                        discovery = show(manager, 'SW2', command)
                        self.assertEqual(discovery['status'], 'observed', discovery)
                        self.assertEqual({n['system_name'] for n in discovery['observation']['summary']['neighbors']}, {'SW1', 'R1'})
                        self.assertIn('SW1', render_show(discovery))
                        self.assertIn('R1', render_show(discovery))
                    for command in ('show ip ospf neighbor', 'show ip ospf interface', 'show ip ospf', 'show ip route ospf'):
                        bird_show = show(manager, 'SW1', command)
                        self.assertEqual(bird_show['status'], 'observed', bird_show)
                        self.assertIn('BIRD 2', render_show(bird_show))
                        if command == 'show ip ospf neighbor':
                            self.assertIn('Full', bird_show['observation']['text'])
                        if command == 'show ip route ospf':
                            self.assertIn('203.0.113.0/24', bird_show['observation']['text'])
                    brief = show(manager, 'PC1', 'show ip interface brief')
                    self.assertEqual(brief['status'], 'observed', brief)
                    self.assertIn('192.0.2.100/24', render_show(brief))
                    routes_show = show(manager, 'SW1', 'show ip route')
                    self.assertEqual(routes_show['status'], 'observed', routes_show)
                    self.assertTrue(any(row.get('dst') == '203.0.113.0/24' for row in routes_show['observation']['records']))
                    for command in ('show arp', 'show vlan brief', 'show mac address-table'):
                        observed = show(manager, 'SW1', command)
                        self.assertEqual(observed['status'], 'observed', observed)
                        self.assertTrue(observed['observation']['records'], observed)
                        self.assertIn('Source : Linux kernel', render_show(observed))
                    fdb = show(manager, 'SW1', 'show mac address-table')
                    client_mac = '02:00:00:00:40:01'
                    learned = [row for row in fdb['observation']['records'] if row.get('mac') == client_mac and row.get('vlan') == 10]
                    self.assertTrue(learned, fdb)
                    self.assertTrue(all(row.get('ifname') == 'eth0' for row in learned), learned)
                    for suffix in ('vlan 10', 'interface eth0'):
                        selected = show(manager, 'SW1', 'show mac address-table ' + suffix)
                        self.assertTrue(any(row.get('mac') == client_mac for row in selected['display_records']), selected)
                        text = render_show(selected)
                        self.assertTrue(any(client_mac in line and 'eth0' in line for line in text.splitlines()), text)
                    self.assertEqual(json.dumps(manager.read(), sort_keys=True), before_show)
                    missing = probe(manager, 'PC1', 'web.lab.test', path='/missing-probe-page')
                    self.assertEqual(missing['status'], 'failed', missing)
                    self.assertEqual(missing['stages'][-1]['http_status'], 404)
                    negative = probe(manager, 'PC1', 'missing.lab.test', protocol='dns')
                    self.assertEqual(negative['status'], 'failed', negative)
                    self.assertEqual(negative['stages'][0]['rcode'], 3)
                    for index in (0, 6, 3):
                        for transport in ('udp', 'tcp'):
                            for host, kind, code, value in (
                                ('web.lab.test', 1, 0, '203.0.113.10'),
                                ('10.113.0.203.in-addr.arpa', 12, 0, 'web.lab.test'),
                                ('web.lab.test', 28, 0, None), ('missing.lab.test', 1, 3, None)):
                                rcode, answers = dns_response(query(index, host, kind, transport).stdout)
                                self.assertEqual(rcode, code)
                                self.assertEqual(answers, [] if value is None else [(host, kind, 1, 60, value)])
                event = threading.Event(); path = Path(folder) / 'services.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', path,
                    seconds=6, packets=100, expression='udp port 53 or tcp port 53 or tcp port 80', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5); self.fail('Services capture not ready')
                with manager.locked():
                    for transport in ('udp', 'tcp'):
                        self.assertEqual(dns_response(query(transport=transport).stdout)[1][0][-1], '203.0.113.10')
                    self.assertIn('Network LABS routed HTTP', web().stdout)
                self.assertGreater(future.result(timeout=9)['captured_packets'], 0)
                decoded = run(['tcpdump', '-nn', '-vv', '-A', '-r', str(path)]).stdout
                for text in ('web.lab.test', '198.18.0.4.53', '203.0.113.10.80', 'GET / HTTP/', 'HTTP/1.', 'Network LABS routed HTTP'):
                    self.assertIn(text, decoded)
                with manager.locked():
                    # A correct route and ICMP do not establish DNS availability.
                    manager.crun('exec', 'DNS1', '/bin/busybox', 'killall', '-TERM', 'dnsmasq')
                    wait(lambda: manager.inspect('DNS1')['dns_server']['listener_snapshot'] == [], 'DNS daemon shutdown')
                    for transport in ('udp', 'tcp'):
                        self.assertNotEqual(query(transport=transport, check=False).returncode, 0)
                    self.assertTrue(manager.inspect('DNS1')['dns_server']['configuration_verified'])
                    self.assertEqual(verify(manager, 'PC1', 'PC2', count=1, bidirectional=True)['status'], 'passed')
                    self.assertIn('Network LABS routed HTTP', web(host='203.0.113.10').stdout)
                    self.assertNotEqual(web(check=False).returncode, 0)
                    application = probe(manager, 'PC1', 'web.lab.test', timeout=1)
                    self.assertEqual(application['status'], 'failed', application)
                    self.assertEqual([s['stage'] for s in application['stages']], ['dns'])
                    self.assertEqual(probe(manager, 'PC1', '203.0.113.10')['status'], 'passed')
                    start_dns(manager)
                    wait(lambda: query(check=False).returncode == 0, 'DNS restart'); ready()
                    # Successful name resolution does not establish HTTP availability.
                    # BusyBox applets may keep the comm name "busybox". Match
                    # the exact applet/port/root argv, never kill all BusyBox
                    # processes (the container init is BusyBox too).
                    stopped = manager.crun('exec', 'PC2', '/bin/sh', '-c', r'''for proc in /proc/[0-9]*; do
                        pid=${proc##*/}; [ "$pid" -gt 1 ] || continue
                        /bin/busybox tr '\000' '\n' < "$proc/cmdline" | /bin/busybox awk '
                            $0 == "httpd" { applet = 1 }
                            previous == "-p" { port = $0 }
                            previous == "-h" { directory = $0 }
                            { previous = $0 }
                            END { exit !(applet && port == "80" && directory == "/tmp/www") }
                        ' || continue
                        /bin/kill -TERM "$pid" || exit 1
                        echo "$pid"
                    done''')
                    self.assertTrue(stopped.stdout.strip(), 'No matching HTTP process observed')
                    wait(lambda: not manager.ns(3, 'ss', '-H', '-lnt', '( sport = :80 )').stdout.strip(), 'HTTP listener shutdown')
                    self.assertEqual(dns_response(query().stdout)[1][0][-1], '203.0.113.10')
                    self.assertEqual(verify(manager, 'PC1', 'PC2', count=1, bidirectional=True)['status'], 'passed')
                    self.assertNotEqual(web(check=False).returncode, 0)
                    application = probe(manager, 'PC1', 'web.lab.test', timeout=1)
                    self.assertEqual(application['status'], 'failed', application)
                    self.assertEqual([s['stage'] for s in application['stages']], ['dns', 'tcp'])
                    self.assertEqual(application['stages'][0]['status'], 'passed')
                    manager.crun('exec', 'PC2', '/bin/busybox', 'httpd', '-p', '80', '-h', '/tmp/www')
                    ready()
                    # DNS on the connected transit survives remote route withdrawal.
                    manager.configure_ios('R1', 'conf t\nno router ospf 1\nend')
                    wait(lambda: not json.loads(manager.ns(1, 'ip', '-j', 'route', 'show', '203.0.113.0/24').stdout), 'OSPF remote route withdrawal')
                    self.assertEqual(dns_response(query().stdout)[1][0][-1], '203.0.113.10')
                    self.assertNotEqual(web(check=False).returncode, 0)
                    self.assertEqual(verify(manager, 'PC1', 'PC2', count=1)['status'], 'failed')
                    application = probe(manager, 'PC1', 'web.lab.test', timeout=1)
                    self.assertEqual(application['status'], 'failed', application)
                    self.assertEqual(application['stages'][0]['status'], 'passed')
                    self.assertEqual(application['stages'][-1]['stage'], 'tcp')
                    manager.configure_ios('R1', 'conf t\nrouter ospf 1\nrouter-id 2.2.2.2\n'
                        'network 198.18.0.0 0.0.0.7 area 0\nnetwork 203.0.113.0 0.0.0.255 area 0\n'
                        'passive-interface eth1\ninterface eth0\nip ospf network broadcast\nend')
                    ready(); manager.write_startup(); saved = load_startup(spec['name']); manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); ready()
                    self.assertEqual(dns_response(query(index=6, transport='tcp').stdout)[1][0][-1], '203.0.113.10')
                    self.assertTrue(manager.inspect('DNS1')['dns_server']['configuration_verified'])
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(run(['ip', '-j', 'rule', 'show']).stdout, rules)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)

    def test_appliance_aa_lldp_trunk_ospf_dhcp_service_edits_loss_and_restore(self):
        import copy
        from network_labs.appliances.examples import ospf_dhcp_lldp_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.lldp import read_cli as lldp_read
        from network_labs.appliances.ospf import read_cli as ospf_read
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                bird=shutil.which('bird'), birdc=shutil.which('birdc'), dnsmasq=shutil.which('dnsmasq'),
                lldpd=shutil.which('lldpd'), lldpcli=shutil.which('lldpcli'))
            spec = ospf_dhcp_lldp_lab(rootfs); spec['name'] = 'lldp-ospf-' + str(os.getpid())
            manager = Manager(spec['name'])
            expected = {'SW1': {('eth1', 'SW2', 'eth0')},
                        'SW2': {('eth0', 'SW1', 'eth1'), ('eth1', 'R1', 'eth0')},
                        'R1': {('eth0', 'SW2', 'eth1')}}
            def wait(predicate, label):
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.2)
                details = {name: manager.inspect(name) for name in ('SW1', 'SW2', 'R1', 'PC1', 'PC3')}
                self.fail('Timed out: ' + label + '; observations=' + json.dumps(details))
            def peers(name):
                # Only actual daemon output; never walk the manifest links.
                from network_labs.appliances.lldp_neighbors import normalize_neighbors
                raw = lldp_read(manager, name, 'neighbors details')
                summary = normalize_neighbors(raw)
                self.assertEqual(summary['status'], 'observed', json.dumps(raw))
                self.assertTrue(all(n['port_id']['type'] == 'ifname' for n in summary['neighbors']))
                # Startup can retain an earlier announcement until refreshed.
                # Wait for the declared TTL on received records, never rewrite it.
                if any(n['ttl_seconds'] != 6 for n in summary['neighbors']):
                    return None
                return {(n['local_port'], n['system_name'], n['port_id']['value']) for n in summary['neighbors']}
            def neighbors(wanted):
                wait(lambda: {name: peers(name) for name in wanted} == wanted, 'actual LLDP port/peer pairs')
            def lease(index, address):
                wait(lambda: any(a.get('local') == address for row in json.loads(manager.ns(index,
                    'ip', '-j', '-4', 'addr', 'show', 'dev', 'eth0').stdout) for a in row.get('addr_info', [])), 'DHCP ' + address)
            def ping(source, address, check=True):
                return manager.crun('exec', source, '/bin/ping', '-c', '1', '-W', '1', address, check=check)
            def traffic():
                lease(0, '192.0.2.100'); lease(6, '198.51.100.100')
                wait(lambda: 'Full' in (ospf_read(manager, 'SW1', 'show ospf neighbors') or ''), 'OSPF Full')
                wait(lambda: ping('PC1', '203.0.113.10', check=False).returncode == 0, 'OSPF forward delivery')
                for source, destination in (('PC1', '203.0.113.10'), ('PC3', '203.0.113.10'),
                                            ('PC2', '192.0.2.100'), ('PC2', '198.51.100.100')):
                    self.assertIn('ttl=62', ping(source, destination).stdout)
            def pid(name, path):
                return manager.crun('exec', name, '/bin/cat', path).stdout.strip()
            def lldp_pids():
                # lldpd privilege separation restricts container /proc/exe reads.
                # The privileged test reads only PIDs in this node's owned
                # cgroup, matching its actual executable inode and start time.
                from network_labs.appliances.runtime import process_identity
                from network_labs.appliances.spec import prefix
                identities = {}
                for name in expected:
                    group = Path('/sys/fs/cgroup/network-labs') / prefix(spec) / name
                    actual = []
                    for value in (group / 'cgroup.procs').read_text().split():
                        try:
                            if (Path('/proc') / value / 'exe').samefile(manager.directory / name / 'rootfs/usr/sbin/lldpd'):
                                actual.append((int(value), process_identity(int(value))))
                        except FileNotFoundError:
                            continue  # An unrelated short-lived exec may finish.
                    self.assertTrue(actual, name + ': no observed LLDP process')
                    self.assertTrue(all(start is not None for _, start in actual))
                    identities[name] = sorted(actual)
                return identities
            try:
                with manager.locked():
                    manager.start(spec); neighbors(expected); traffic()
                    from network_labs.appliances.diagnostics import explain, render
                    before = copy.deepcopy(manager.read())
                    report = explain(manager, 'SW2')
                    self.assertEqual(manager.read(), before)
                    self.assertEqual(report['packet_delivery'], 'not_tested')
                    findings = [f for item in report['nodes'] for f in item['findings'] if f['code'] == 'LLDP_NEIGHBOR']
                    self.assertEqual({(f['evidence']['local_port'], f['evidence']['system_name'], f['evidence']['port_id']['value'])
                                      for f in findings}, expected['SW2'])
                    self.assertIn('TTL annoncé 6 s', render(report))
                    self.assertEqual(manager.inspect('SW2')['lldp']['neighbor_summary']['status'], 'observed')
                    identities = lldp_pids()
                    bird = pid('SW1', '/run/bird.pid'); relay = pid('SW1', '/run/dhcp-relay.pid')
                    manager.configure_ios('SW1', 'conf t\ninterface vlan20\nip ospf cost 55\nend')
                    self.assertEqual(pid('SW1', '/run/bird.pid'), bird)
                    self.assertEqual(pid('SW1', '/run/dhcp-relay.pid'), relay)
                    for prefix in ('no ', ''):
                        manager.configure_ios('SW1', 'conf t\ninterface vlan10\n' + prefix + 'ip helper-address 198.18.0.3\nend')
                        self.assertEqual(pid('SW1', '/run/bird.pid'), bird)
                        self.assertEqual(lldp_pids(), identities)
                        neighbors(expected)
                    # Fresh acquisition confirms the helper still works beside LLDP.
                    manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -USR2 "$(/bin/cat /run/udhcpc.pid)"')
                    wait(lambda: not any(row.get('addr_info') for row in json.loads(manager.ns(0,
                        'ip', '-j', '-4', 'addr', 'show', 'dev', 'eth0').stdout)), 'released PC1 IPv4')
                    manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -USR1 "$(/bin/cat /run/udhcpc.pid)"')
                    traffic()
                    before = copy.deepcopy(manager.read())
                    for command in ('interface eth1\nshutdown', 'interface vlan20\nip ospf cost 56\ninterface eth1\nshutdown'):
                        with self.assertRaises(ValueError):
                            manager.configure_ios('SW1', 'conf t\n' + command + '\nend')
                        self.assertEqual(manager.read(), before)
                # A physical trunk carries untagged LLDP and VLAN20-tagged OSPF.
                path = Path(folder) / 'trunk.pcap'
                # Keep the bounded trunk capture unfiltered: mixing a VLAN
                # qualifier with an untagged branch changes BPF offsets. Decode
                # and assert both actual encapsulations offline instead.
                cap = capture(Manager(spec['name']), 'SW1', 'eth1', path, seconds=5, packets=100)
                self.assertGreater(cap['captured_packets'], 0)
                decoded = run(['tcpdump', '-e', '-nn', '-vv', '-r', str(path)]).stdout
                self.assertIn('ethertype LLDP (0x88cc)', decoded)
                self.assertIn('vlan 20', decoded); self.assertIn('OSPFv2', decoded)
                self.assertFalse(any('vlan ' in line and 'LLDP' in line for line in decoded.splitlines()), decoded)
                with manager.locked():
                    manager.ns(1, 'ip', 'link', 'set', 'eth1', 'down')
                    neighbors({'SW1': set(), 'SW2': {('eth1', 'R1', 'eth0')}, 'R1': expected['R1']})
                    wait(lambda: 'Full' not in (ospf_read(manager, 'SW1', 'show ospf neighbors') or ''), 'OSPF expiry after trunk loss')
                    self.assertNotEqual(ping('PC1', '203.0.113.10', check=False).returncode, 0)
                    manager.ns(1, 'ip', 'link', 'set', 'eth1', 'up')
                    neighbors(expected); traffic()
                    self.assertEqual(lldp_pids(), identities)
                    for name in expected:
                        self.assertTrue(manager.inspect(name)['lldp']['policy_verified'])
                    manager.write_startup(); saved = load_startup(spec['name']); manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); neighbors(expected); traffic()
                    self.assertEqual(manager.read()['spec']['nodes'][1]['ospf']['interfaces']['vlan20']['cost'], 55)
                    for name in expected:
                        self.assertTrue(manager.inspect(name)['lldp']['policy_verified'])
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(run(['ip', '-j', 'rule', 'show']).stdout, rules)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)

    def test_appliance_ab_dhcp_relay_real_dora_renew_loss_drift_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import dhcp_relay_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.dhcp_relay import start_servers
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', dnsmasq=shutil.which('dnsmasq'))
            spec = dhcp_relay_lab(rootfs); spec['name'] = 'relay-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def addresses(index):
                return [a['local'] for link in json.loads(manager.ns(index, 'ip', '-j', '-4', 'addr', 'show', 'dev', 'eth0').stdout)
                        for a in link.get('addr_info', []) if a.get('scope') == 'global']
            def wait_for(predicate, label, seconds=15):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.1)
                self.fail('Timed out waiting for ' + label)
            def ready():
                wait_for(lambda: addresses(0) == ['192.0.2.100'] and bool(addresses(1)), 'real remote DHCP leases')
                self.assertNotEqual(addresses(0), addresses(1))
                self.assertTrue(addresses(1)[0].startswith('192.0.2.'))
                for index in (0, 1):
                    default = json.loads(manager.ns(index, 'ip', '-j', 'route', 'show', 'default').stdout)
                    self.assertTrue(any(row.get('gateway') == '192.0.2.1' for row in default))
            def signal_client(signal):
                manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -' + signal + ' "$(/bin/cat /run/udhcpc.pid)"')
            def release():
                signal_client('USR2')
                wait_for(lambda: not addresses(0), 'released address removed')
            def packets(filename, node, interface, action):
                event = threading.Event(); path = Path(folder) / filename
                future = pool.submit(capture, Manager(spec['name']), node, interface, path,
                                     seconds=4, packets=100, expression='udp and (port 67 or port 68)', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5); self.fail('DHCP capture not ready')
                with manager.locked():
                    action()
                result = future.result(timeout=8)
                self.assertGreater(result['captured_packets'], 0)
                return run(['tcpdump', '-nn', '-vvv', '-r', str(path)]).stdout
            try:
                with manager.locked():
                    manager.start(spec); ready()
                    manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10')
                    self.assertTrue(manager.inspect('SW1')['dhcp_relay']['configuration_verified'])
                    release()
                dora = packets('dora.pcap', 'DHCP1', 'eth0', lambda: signal_client('USR1'))
                for message in ('Discover', 'Offer', 'Request', 'ACK', 'Gateway-IP 192.0.2.1'):
                    self.assertIn(message, dora)
                with manager.locked():
                    ready()
                renew = packets('renew.pcap', 'DHCP1', 'eth0', lambda: signal_client('USR1'))
                self.assertIn('Request', renew); self.assertIn('ACK', renew)
                with manager.locked():
                    ready()
                    manager.crun('exec', 'SW1', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/dhcp-relay.pid)"')
                    wait_for(lambda: manager.inspect('SW1')['dhcp_relay']['listener_snapshot'] == [], 'relay stopped')
                    self.assertTrue(manager.inspect('SW1')['dhcp_relay']['configuration_verified'])
                    manager.crun('exec', 'PC2', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10')
                    release()
                outage = packets('outage.pcap', 'PC1', 'eth0', lambda: signal_client('USR1'))
                self.assertIn('Discover', outage)
                self.assertNotIn('Offer', outage); self.assertNotIn('ACK', outage)
                with manager.locked():
                    self.assertEqual(addresses(0), [])
                    start_servers(manager); ready()
                    # CLI removes and restores the real service without touching links.
                    from network_labs.appliances.dhcp_relay import processes, apply_change
                    def helper(remove=False):
                        return manager.configure_ios('SW1', 'conf t\ninterface vlan10\n' +
                            ('no ' if remove else '') + 'ip helper-address 198.51.100.10\nend')
                    initial_pids = {n['name']: json.loads(manager.crun('state', n['name']).stdout)['pid'] for n in spec['nodes']}
                    link_ids = lambda: [(r['ifindex'], r['ifname']) for r in json.loads(manager.ns(2, 'ip', '-j', 'link', 'show').stdout)]
                    before_links = link_ids()
                    relay_pids = processes(manager, manager.state['spec']['nodes'][2])
                    revision = manager.state['revision']
                    self.assertTrue(helper()['unchanged'])
                    self.assertEqual(manager.state['revision'], revision)
                    self.assertEqual(processes(manager, manager.state['spec']['nodes'][2]), relay_pids)
                    # A forged pidfile must not kill PID 1 or leave the actual daemon alive.
                    manager.crun('exec', 'SW1', '/bin/sh', '-c', 'echo 1 > /run/dhcp-relay.pid')
                    helper(True)
                    self.assertEqual(processes(manager, manager.state['spec']['nodes'][2]), [])
                    self.assertFalse((manager.directory / 'SW1/files/dhcp-relay.conf').exists())
                    manager.crun('exec', 'PC2', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10')
                    release()
                no_helper = packets('no-helper.pcap', 'PC1', 'eth0', lambda: signal_client('USR1'))
                self.assertIn('Discover', no_helper); self.assertNotIn('Offer', no_helper)
                with manager.locked():
                    self.assertEqual(addresses(0), [])
                    helper(); ready()
                    self.assertEqual(link_ids(), before_links)
                    self.assertEqual({n['name']: json.loads(manager.crun('state', n['name']).stdout)['pid'] for n in spec['nodes']}, initial_pids)
                    # Fail after actual service removal, then prove real rollback.
                    calls = []
                    def fail_removed(*args):
                        calls.append(True)
                        apply_change(*args)
                        if len(calls) == 1:
                            raise RuntimeFailure('Injected after actual helper removal')
                    revision = manager.state['revision']
                    with patch('network_labs.appliances.dhcp_relay.apply_change', side_effect=fail_removed):
                        with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                            helper(True)
                    self.assertEqual(manager.state['revision'], revision)
                    self.assertEqual(manager.state['phase'], 'running')
                    self.assertTrue(manager.inspect('SW1')['dhcp_relay']['configuration_verified'])
                    release(); signal_client('USR1'); ready()
                    # Failed rollback retains the journal for explicit recovery.
                    calls.clear()
                    def fail_rollback(*args):
                        calls.append(True)
                        if len(calls) == 1:
                            apply_change(*args)
                        raise RuntimeFailure('Injected apply/rollback failure')
                    with patch('network_labs.appliances.dhcp_relay.apply_change', side_effect=fail_rollback):
                        with self.assertRaisesRegex(RuntimeFailure, 'rollback failed'):
                            helper(True)
                    self.assertEqual(manager.state['phase'], 'configuration-failed')
                    self.assertIn('pending_spec', manager.state)
                    manager.recover()
                    self.assertEqual(manager.state['phase'], 'running')
                    self.assertNotIn('pending_spec', manager.state)
                    self.assertEqual(manager.state['revision'], revision)
                    release(); signal_client('USR1'); ready()
                    self.assertEqual(link_ids(), before_links)
                    path = manager.directory / 'SW1/files/dhcp-relay.conf'
                    original = path.read_text()
                    try:
                        path.write_text(original + '# external drift\n')
                        self.assertFalse(manager.inspect('SW1')['dhcp_relay']['configuration_verified'])
                        with self.assertRaisesRegex(RuntimeFailure, 'drift'):
                            helper(True)
                        with self.assertRaisesRegex(RuntimeFailure, 'DHCP relay'):
                            manager.write_startup()
                    finally:
                        path.write_text(original)
                    manager.write_startup(); saved = load_startup(spec['name']); manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); ready()
                    manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10')
            except Exception:
                for node, filename in (('SW1', 'dhcp-relay.log'), ('DHCP1', 'dhcp.log'), ('PC1', 'dhcp.log')):
                    path = manager.directory / node / filename
                    if path.exists():
                        print(node + ': ' + path.read_text()[-6000:])
                raise
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), rules)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)

    def test_appliance_ac_dhcp_multiple_vlan_pools_real_packets_and_helper_isolation(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import ipaddress
        from network_labs.appliances.examples import dhcp_multi_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        baseline_links = links(); baseline_routes = run(['ip', '-j', 'route', 'show']).stdout
        baseline_nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        baseline_forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', dnsmasq=shutil.which('dnsmasq'))
            spec = dhcp_multi_lab(rootfs); spec['name'] = 'pools-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def addresses(index):
                return [a for link in json.loads(manager.ns(index, 'ip', '-j', '-4', 'addr', 'show', 'dev', 'eth0').stdout)
                        for a in link.get('addr_info', []) if a.get('scope') == 'global']
            def wait(predicate, label):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.1)
                self.fail('Timed out: ' + label)
            def signal(index, value):
                manager.crun('exec', 'PC' + str(index + 1), '/bin/sh', '-c', '/bin/kill -' + value + ' "$(/bin/cat /run/udhcpc.pid)"')
            def release(index):
                signal(index, 'USR2'); wait(lambda: not addresses(index), 'DHCP release')
            def ready(index):
                wait(lambda: bool(addresses(index)), 'DHCP pool acquisition')
                address = addresses(index)[0]
                prefix = ('192.0.2.', '198.18.0.')[index]
                self.assertEqual(address['prefixlen'], 24)
                self.assertTrue(ipaddress.IPv4Address(prefix + '100') <= ipaddress.IPv4Address(address['local']) <= ipaddress.IPv4Address(prefix + '110'))
                if index == 0:
                    self.assertEqual(address['local'], '192.0.2.100')
                default = json.loads(manager.ns(index, 'ip', '-j', 'route', 'show', 'default').stdout)
                self.assertTrue(any(row.get('gateway') == prefix + '1' for row in default))
                resolver = manager.crun('exec', 'PC' + str(index + 1), '/bin/cat', '/etc/resolv.conf').stdout
                self.assertEqual(resolver, 'nameserver ' + prefix + '53\n')
            def recorded(filename, node, action):
                event = threading.Event(); path = Path(folder) / filename
                future = pool.submit(capture, Manager(spec['name']), node, 'eth0', path,
                                     seconds=4, packets=100, expression='udp and (port 67 or port 68)', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5); self.fail('DHCP capture not ready')
                with manager.locked():
                    action()
                result = future.result(timeout=8)
                return result['captured_packets'], run(['tcpdump', '-nn', '-vvv', '-r', str(path)]).stdout
            def helper(remove=False):
                manager.configure_ios('SW1', 'conf t\ninterface vlan10\n' + ('no ' if remove else '') + 'ip helper-address 198.51.100.10\nend')
            try:
                with manager.locked():
                    manager.start(spec); ready(0); ready(1)
                for index, gateway in ((0, '192.0.2.1'), (1, '198.18.0.1')):
                    with manager.locked():
                        release(index)
                    count, packets = recorded('pool' + str(index) + '.pcap', 'DHCP1', lambda: signal(index, 'USR1'))
                    self.assertGreater(count, 0)
                    for expected in ('Discover', 'Offer', 'Request', 'ACK', 'Gateway-IP ' + gateway):
                        self.assertIn(expected, packets)
                    with manager.locked():
                        ready(index)
                # Client broadcasts from VLAN10 must not leak onto VLAN20.
                with manager.locked():
                    release(0)
                count, _ = recorded('isolated.pcap', 'PC2', lambda: signal(0, 'USR1'))
                self.assertEqual(count, 0)
                with manager.locked():
                    ready(0); ready(1)
                    helper(True); release(0)
                count, packets = recorded('removed.pcap', 'PC1', lambda: signal(0, 'USR1'))
                self.assertGreater(count, 0); self.assertIn('Discover', packets)
                self.assertNotIn('Offer', packets); self.assertNotIn('ACK', packets)
                with manager.locked():
                    self.assertEqual(addresses(0), [])
                    release(1); signal(1, 'USR1'); ready(1)
                    self.assertEqual(addresses(0), [])
                    helper(); ready(0)
                    for node in ('PC1', 'PC2'):
                        manager.crun('exec', node, '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10')
                # Capture real Request/ACK for each client's renewal, not just
                # the existing address left behind by its prior lease.
                for index in (0, 1):
                    count, packets = recorded('renew-pool' + str(index) + '.pcap', 'DHCP1', lambda: signal(index, 'USR1'))
                    self.assertGreater(count, 0)
                    for expected in ('Request', 'ACK', '02:00:00:00:20:0' + str(index + 1)):
                        self.assertIn(expected, packets)
                    with manager.locked():
                        ready(index)
                with manager.locked():
                    config = manager.directory / 'DHCP1/files/dhcp-pools.conf'
                    original = config.read_text()
                    try:
                        config.write_text(original + '# drift\n')
                        self.assertFalse(manager.inspect('DHCP1')['dhcp_pools']['configuration_verified'])
                        with self.assertRaisesRegex(RuntimeFailure, 'DHCP pools'):
                            manager.write_startup()
                    finally:
                        config.write_text(original)
                    manager.write_startup(); saved = load_startup(spec['name']); manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); ready(0); ready(1)
                    self.assertTrue(manager.inspect('DHCP1')['dhcp_pools']['configuration_verified'])
            except Exception:
                for node, filename in (('SW1', 'dhcp-relay.log'), ('DHCP1', 'dhcp-pools.log'), ('PC1', 'dhcp.log'), ('PC2', 'dhcp.log')):
                    path = manager.directory / node / filename
                    if path.exists():
                        print(node + ': ' + path.read_text()[-6000:])
                raise
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(baseline_links, links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, baseline_routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), baseline_nft)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, baseline_forwarding)

    def test_appliance_ad_ospf_real_adjacencies_routes_failure_recovery_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import ospf_lab
        from network_labs.appliances.ospf import start_servers, read_cli
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', bird=shutil.which('bird'), birdc=shutil.which('birdc'))
            spec = ospf_lab(rootfs); spec['name'] = 'ospf-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def route():
                rows = json.loads(manager.ns(2, 'ip', '-j', 'route', 'show', '198.51.100.0/24').stdout)
                return rows[0] if rows else None
            def wait(predicate, label):
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.2)
                self.fail('Timed out: ' + label + '; routes=' + repr(route()))
            def ping(ttl):
                def delivered():
                    result = manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10', check=False)
                    return result.returncode == 0 and 'ttl=' + str(ttl) in result.stdout
                wait(delivered, 'routed ping TTL ' + str(ttl))
            def converged():
                wait(lambda: all((read_cli(manager, node, 'show ospf neighbors') or '').lower().count('full') >= 2 for node in ('R1', 'R2', 'R3')), 'all real OSPF adjacencies Full')
                wait(lambda: (route() or {}).get('gateway') == '10.0.12.2', 'primary OSPF FIB route')
                self.assertIn(route().get('protocol'), ('bird', 192, '192'))
                ping(62)
            def record(filename, node, interface, expression='ip proto 89', action=None):
                event = threading.Event(); path = Path(folder) / filename
                future = pool.submit(capture, Manager(spec['name']), node, interface, path,
                                     seconds=3, packets=100, expression=expression, ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5); self.fail('OSPF capture not ready')
                if action is not None:
                    action()
                result = future.result(timeout=7)
                return result['captured_packets'], run(['tcpdump', '-nn', '-vv', '-r', str(path)]).stdout
            try:
                def before_daemons(actual_manager):
                    self.assertIsNone(route())
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10', check=False).returncode, 0)
                    start_servers(actual_manager)
                with manager.locked():
                    with patch('network_labs.appliances.ospf.start_servers', side_effect=before_daemons):
                        manager.start(spec)
                    converged()
                count, packets = record('ospf-transit.pcap', 'R1', 'eth0')
                self.assertGreater(count, 0); self.assertIn('OSPFv2', packets)
                count, _ = record('ospf-passive.pcap', 'PC1', 'eth0')
                self.assertEqual(count, 0)
                with manager.locked():
                    manager.ns(2, 'ip', 'link', 'set', 'eth0', 'down')
                    wait(lambda: (route() or {}).get('gateway') == '10.0.13.2', 'backup next hop learned by OSPF')
                    ping(61)
                    manager.ns(2, 'ip', 'link', 'set', 'eth1', 'down')
                    wait(lambda: route() is None, 'OSPF route withdrawn after isolation')
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10', check=False).returncode, 0)
                    manager.ns(2, 'ip', 'link', 'set', 'eth0', 'up')
                    wait(lambda: (route() or {}).get('gateway') == '10.0.12.2', 'primary recovered')
                    ping(62)
                    manager.ns(2, 'ip', 'link', 'set', 'eth1', 'up'); converged()
                    # Reconfigure the real daemon through the managed IOS subset.
                    from network_labs.appliances.ospf import apply_change
                    def cli(text):
                        return manager.configure_ios('R1', 'conf t\n' + text + '\nend')
                    def identity():
                        pid = manager.crun('exec', 'R1', '/bin/cat', '/run/bird.pid').stdout
                        state = json.loads(manager.crun('state', 'R1').stdout)
                        ports = {(row['ifname'], row['ifindex']) for row in json.loads(manager.ns(2, 'ip', '-j', 'link', 'show').stdout)}
                        return pid, state['pid'], ports
                    original_identity = identity()
                    changed = cli('interface eth0\nip ospf cost 100')
                    wait(lambda: (route() or {}).get('gateway') == '10.0.13.2', 'CLI cost selects backup without physical failure')
                # Cost is directional: request crosses three routers, reply two.
                # Capture outside the manager lock so the observer can initialize.
                count, packets = record('ospf-cost-request.pcap', 'PC2', 'eth0',
                                        expression='icmp and src host 192.0.2.10 and icmp[0] = 8', action=lambda: ping(62))
                self.assertGreater(count, 0); self.assertIn('ttl 61', packets)
                self.assertIn('echo request', packets)
                reverse = json.loads(manager.ns(3, 'ip', '-j', 'route', 'show', '192.0.2.0/24').stdout)
                self.assertEqual(reverse[0]['gateway'], '10.0.12.1')
                with manager.locked():
                    self.assertEqual(identity(), original_identity)
                    self.assertTrue(cli('interface eth0\nip ospf cost 100')['unchanged'])
                    self.assertEqual(manager.read()['revision'], changed['revision'])
                    cli('interface eth0\nip ospf cost 10'); converged()
                    cli('router ospf 1\npassive-interface eth0')
                    wait(lambda: (route() or {}).get('gateway') == '10.0.13.2', 'passive transit removes primary adjacency')
                    ping(61)
                    cli('router ospf 1\nno passive-interface eth0'); converged()
                    cli('router ospf 1\nnetwork 10.0.12.1 0.0.0.0 area 0\nno network 10.0.12.0 0.0.0.3 area 0')
                    converged()  # Exact-host selector still enables eth0.
                    cli('router ospf 1\nno network 10.0.12.1 0.0.0.0 area 0')
                    wait(lambda: (route() or {}).get('gateway') == '10.0.13.2', 'network removal disables OSPF on eth0')
                    ping(61)
                    self.assertEqual(manager.read()['spec']['nodes'][2]['ospf']['interfaces']['eth0']['cost'], 10)
                    cli('router ospf 1\nnetwork 10.0.12.0 0.0.0.3 area 0'); converged()
                    # Apply genuinely loads the changed policy before an injected
                    # failure; rollback reloads the old file without killing BIRD.
                    before = manager.read()['revision']
                    calls = []
                    def fail_after_reload(actual_manager, index, node, previous):
                        apply_change(actual_manager, index, node, previous)
                        calls.append(node['ospf']['interfaces']['eth0']['cost'])
                        if len(calls) == 1:
                            raise RuntimeFailure('injected failure after actual OSPF reload')
                    with patch('network_labs.appliances.ospf.apply_change', side_effect=fail_after_reload):
                        with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                            cli('interface eth0\nip ospf cost 100')
                    self.assertEqual(calls, [100, 10]); self.assertEqual(manager.read()['revision'], before)
                    self.assertEqual(manager.read()['phase'], 'running'); converged()
                    def fail_both(actual_manager, index, node, previous):
                        apply_change(actual_manager, index, node, previous)
                        raise RuntimeFailure('injected post-reload apply and rollback failure')
                    with patch('network_labs.appliances.ospf.apply_change', side_effect=fail_both):
                        with self.assertRaisesRegex(RuntimeFailure, 'rollback failed'):
                            cli('interface eth0\nip ospf cost 100')
                    self.assertEqual(manager.read()['phase'], 'configuration-failed')
                    manager.recover(); self.assertEqual(manager.read()['phase'], 'running'); converged()
                    self.assertEqual(identity(), original_identity)
                    path = manager.directory / 'R1/files/bird.conf'; original = path.read_text()
                    try:
                        path.write_text(original + '# drift\n')
                        before = manager.read()['revision']
                        with self.assertRaisesRegex(RuntimeFailure, 'OSPF configuration drift'):
                            cli('interface eth0\nip ospf cost 100')
                        self.assertEqual(manager.read()['revision'], before)
                        self.assertEqual(manager.read()['phase'], 'running')
                        with self.assertRaisesRegex(RuntimeFailure, 'OSPF'):
                            manager.write_startup()
                    finally:
                        path.write_text(original)
                    # Non-BIRD injected routes still fail the static-route audit.
                    manager.ns(2, 'ip', 'route', 'add', '203.0.113.0/24', 'via', '10.0.12.2', 'proto', 'static')
                    try:
                        with self.assertRaisesRegex(RuntimeFailure, 'static routes'):
                            manager.write_startup()
                    finally:
                        manager.ns(2, 'ip', 'route', 'del', '203.0.113.0/24')
                    manager.write_startup(); saved = load_startup(spec['name'])
                    self.assertTrue(all(not node['routes'] for node in saved['nodes']))
                    manager.crun('exec', 'R1', '/usr/sbin/birdc', '-s', '/run/bird.ctl', 'down')
                    wait(lambda: read_cli(manager, 'R1', 'show status') is None, 'BIRD stopped')
                    wait(lambda: route() is None, 'daemon-owned routes removed on shutdown')
                    observed = manager.inspect('R1')['ospf']
                    self.assertTrue(observed['configuration_verified']); self.assertIsNone(observed['neighbors'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); converged()
                    # Lifecycle: the real process can be removed and recreated
                    # without replacing its container or network interfaces.
                    from network_labs.appliances.ospf import processes
                    baseline = identity()[1:]
                    create = ('router ospf 1\nrouter-id 1.1.1.1\n'
                              'network 10.0.12.0 0.0.0.3 area 0\n'
                              'network 10.0.13.0 0.0.0.3 area 0\n'
                              'network 192.0.2.0 0.0.0.255 area 0\n'
                              'passive-interface eth2\ninterface eth1\nip ospf cost 30')
                    remove = 'no router ospf 1'
                    before = manager.read()['revision']; calls = []
                    def fail_after_lifecycle(actual_manager, index, node, previous):
                        apply_change(actual_manager, index, node, previous)
                        calls.append(node.get('ospf') is not None)
                        if len(calls) == 1:
                            raise RuntimeFailure('injected failure after actual OSPF lifecycle change')
                    with patch('network_labs.appliances.ospf.apply_change', side_effect=fail_after_lifecycle):
                        with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                            cli(remove)
                    self.assertEqual(calls, [False, True]); self.assertEqual(manager.read()['revision'], before)
                    converged(); self.assertEqual(identity()[1:], baseline)
                    # A forged PID file pointing at init must not select it.
                    manager.crun('exec', 'R1', '/bin/sh', '-c', 'echo 1 > /run/bird.pid')
                    cli(remove)
                    wait(lambda: route() is None, 'CLI removal withdraws BIRD routes')
                    self.assertEqual(processes(manager, manager.read()['spec']['nodes'][2], managed=False), [])
                    self.assertFalse((manager.directory / 'R1/files/bird.conf').exists())
                    self.assertIsNone(read_cli(manager, 'R1', 'show status'))
                    self.assertEqual(json.loads(manager.crun('state', 'R1').stdout)['status'], 'running')
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10', check=False).returncode, 0)
                    # A separate real BIRD process must stay untouched, and
                    # block managed creation instead of being adopted/killed.
                    manager.crun('exec', 'R1', '/bin/sh', '-c', 'echo "router id 9.9.9.9; log stderr all; protocol device { scan time 1; }" > /tmp/foreign-bird.conf')
                    manager.crun('exec', '--detach', 'R1', '/usr/sbin/bird', '-f', '-c', '/tmp/foreign-bird.conf',
                                 '-s', '/run/foreign-bird.ctl', '-P', '/run/foreign-bird.pid', log=manager.directory / 'R1/foreign-bird.log')
                    before = manager.read()['revision']
                    with self.assertRaisesRegex(RuntimeFailure, 'Unmanaged BIRD'):
                        cli(create)
                    self.assertEqual(manager.read()['revision'], before)
                    self.assertEqual(manager.read()['phase'], 'running')
                    manager.crun('exec', 'R1', '/usr/sbin/birdc', '-s', '/run/foreign-bird.ctl', 'show', 'status')
                    manager.crun('exec', 'R1', '/usr/sbin/birdc', '-s', '/run/foreign-bird.ctl', 'down')
                    wait(lambda: not processes(manager, manager.read()['spec']['nodes'][2], managed=False), 'foreign daemon stopped by its own control socket')
                    before = manager.read()['revision']; calls.clear()
                    with patch('network_labs.appliances.ospf.apply_change', side_effect=fail_after_lifecycle):
                        with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                            cli(create)
                    self.assertEqual(calls, [True, False]); self.assertEqual(manager.read()['revision'], before)
                    self.assertIsNone(manager.read()['spec']['nodes'][2]['ospf'])
                    self.assertEqual(processes(manager, manager.read()['spec']['nodes'][2], managed=False), [])
                    self.assertFalse((manager.directory / 'R1/files/bird.conf').exists())
                    with patch('network_labs.appliances.ospf.apply_change', side_effect=fail_both):
                        with self.assertRaisesRegex(RuntimeFailure, 'rollback failed'):
                            cli(create)
                    self.assertEqual(manager.read()['phase'], 'configuration-failed')
                    manager.recover(); self.assertEqual(manager.read()['phase'], 'running')
                    self.assertIsNone(manager.read()['spec']['nodes'][2]['ospf'])
                    self.assertEqual(processes(manager, manager.read()['spec']['nodes'][2], managed=False), [])
                    manager.write_startup(); disabled = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(disabled)
                    self.assertIsNone(manager.read()['spec']['nodes'][2]['ospf'])
                    self.assertIsNone(route()); self.assertIsNone(read_cli(manager, 'R1', 'show status'))
                    cli(create); converged()
                    manager.write_startup(); created = load_startup(spec['name'])
                    self.assertEqual(created['nodes'][2]['ospf'], saved['nodes'][2]['ospf'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(created); converged()

            except Exception:
                for node in ('R1', 'R2', 'R3'):
                    path = manager.directory / node / 'ospf.log'
                    if path.exists():
                        print(node + ': ' + path.read_text()[-6000:])
                raise
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(run(['ip', '-j', 'rule', 'show']).stdout, rules)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)

    def test_appliance_af_ospf_broadcast_real_election_two_way_failover_cli_and_restore(self):
        import re
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from network_labs.appliances.examples import ospf_broadcast_lab
        from network_labs.appliances.ospf import read_cli
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', bird=shutil.which('bird'), birdc=shutil.which('birdc'))
            spec = ospf_broadcast_lab(rootfs); spec['name'] = 'ospf-bcast-' + str(os.getpid())
            manager = Manager(spec['name'])
            def iface(node):
                return read_cli(manager, node, 'show ospf interface ospf4 "eth0"') or ''
            def field(node, label):
                match = re.search(re.escape(label) + r':\s+(\S+)', iface(node))
                return match[1] if match else None
            def neighbor(node, other):
                text = read_cli(manager, node, 'show ospf neighbors') or ''
                value = str(other) + '.' + str(other) + '.' + str(other) + '.' + str(other)
                match = re.search(re.escape(value) + r'\s+\d+\s+(\S+)', text)
                return match[1].split('/')[0] if match else None
            def wait(predicate, label):
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.2)
                self.fail('Timed out: ' + label + '; interface snapshots=' + repr({name: iface(name) for name in ('R1', 'R2', 'R3', 'R4')}))
            def elected(dr, bdr, names=('R1', 'R2', 'R3', 'R4')):
                wait(lambda: all(field(name, 'Designated router (ID)') == dr and field(name, 'Backup designated router (ID)') == bdr for name in names), 'observed DR=' + dr + ', BDR=' + bdr)
            def route():
                rows = json.loads(manager.ns(5, 'ip', '-j', 'route', 'show', '198.51.100.0/24').stdout)
                return rows[0] if rows else {}
            def traffic():
                wait(lambda: route().get('gateway') == '10.0.100.4', 'R3 kernel next hop directly to R4, not through DR')
                self.assertIn(route().get('protocol'), ('bird', 192, '192'))
                def ping():
                    result = manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10', check=False)
                    return result.returncode == 0 and 'ttl=62' in result.stdout
                wait(ping, 'real PC1/PC2 traffic across the shared LAN')
            def initial():
                elected('1.1.1.1', '2.2.2.2')
                wait(lambda: field('R1', 'State') == 'DR' and field('R2', 'State') == 'Backup' and
                     field('R3', 'State') == field('R4', 'State') == 'DROther', 'initial interface roles')
                wait(lambda: neighbor('R3', 4) == neighbor('R4', 3) == '2-Way', 'normal DROther-to-DROther 2-Way')
                wait(lambda: all(neighbor(name, other) == 'Full' for name in ('R3', 'R4') for other in (1, 2)), 'Full adjacencies with DR and BDR')
                self.assertEqual(field('R4', 'Priority'), '0'); traffic()
            try:
                with manager.locked():
                    manager.start(spec); initial()
                event = threading.Event(); path = Path(folder) / 'ospf-broadcast.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'R3', 'eth0', path, seconds=3, packets=100,
                                     expression='ip proto 89', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5); self.fail('Broadcast OSPF capture not ready')
                captured = future.result(timeout=7)
                packets = run(['tcpdump', '-nn', '-vv', '-r', str(path)]).stdout
                self.assertGreater(captured['captured_packets'], 0)
                self.assertIn('OSPFv2', packets); self.assertIn('Hello', packets); self.assertIn('224.0.0.5', packets)
                with manager.locked():
                    manager.ns(3, 'ip', 'link', 'set', 'eth0', 'down')
                    elected('2.2.2.2', '3.3.3.3', ('R2', 'R3', 'R4'))
                    wait(lambda: field('R2', 'State') == 'DR' and field('R3', 'State') == 'Backup', 'BDR promoted, eligible DROther becomes BDR')
                    self.assertEqual(field('R4', 'Priority'), '0')
                    self.assertEqual(field('R4', 'State'), 'DROther'); traffic()
                    manager.ns(3, 'ip', 'link', 'set', 'eth0', 'up')
                    elected('2.2.2.2', '3.3.3.3')
                    wait(lambda: neighbor('R1', 2) == neighbor('R1', 3) == 'Full' and neighbor('R1', 4) == '2-Way', 'returning higher-priority router does not preempt')
                    self.assertEqual(field('R1', 'State'), 'DROther')
                    self.assertEqual(field('R1', 'Priority'), '200'); traffic()
                    def cli(text):
                        return manager.configure_ios('R4', 'conf t\ninterface eth0\n' + text + '\nend')
                    cli('ip ospf priority 255')
                    wait(lambda: field('R4', 'Priority') == '255', 'CLI priority reached actual daemon')
                    elected('2.2.2.2', '3.3.3.3')
                    wait(lambda: neighbor('R4', 2) == neighbor('R4', 3) == 'Full', 'priority change rejoins elected routers')
                    self.assertEqual(field('R4', 'State'), 'DROther'); traffic()
                    cli('no ip ospf priority\nip ospf network point-to-point')
                    wait(lambda: field('R4', 'Type') == 'ptp', 'actual CLI network type change')
                    cli('ip ospf network broadcast\nip ospf priority 0')
                    wait(lambda: field('R4', 'Type') == 'broadcast' and field('R4', 'Priority') == '0', 'broadcast profile restored')
                    elected('2.2.2.2', '3.3.3.3')
                    wait(lambda: neighbor('R4', 2) == neighbor('R4', 3) == 'Full', 'broadcast adjacencies recovered')
                    traffic()
                    observation = manager.inspect('R4')['ospf']
                    self.assertIn('Type: broadcast', observation['interfaces'])
                    self.assertTrue(observation['configuration_verified'])
                    manager.write_startup(); saved = load_startup(spec['name'])
                    self.assertEqual(saved['nodes'][6]['ospf']['interfaces']['eth0']['priority'], 0)
                    self.assertEqual(saved['nodes'][6]['ospf']['interfaces']['eth0']['network_type'], 'broadcast')
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); initial()
            except Exception:
                for name in ('R1', 'R2', 'R3', 'R4'):
                    path = manager.directory / name / 'ospf.log'
                    if path.exists():
                        print(name + ': ' + path.read_text()[-5000:])
                raise
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(run(['ip', '-j', 'rule', 'show']).stdout, rules)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)

    def test_appliance_aa_verify_real_dhcp_endpoints_pcap_loss_blocked_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import copy
        from network_labs.appliances.examples import ospf_dhcp_multi_lab
        from network_labs.appliances.verify import verify, render
        from network_labs.appliances.capture import capture
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                bird=shutil.which('bird'), birdc=shutil.which('birdc'), dnsmasq=shutil.which('dnsmasq'))
            spec = ospf_dhcp_multi_lab(rootfs); spec['name'] = 'verify-' + str(os.getpid())
            manager = Manager(spec['name'])
            def wait(predicate, label):
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.2)
                details = {'verification': verify(manager, 'PC1', 'PC2', count=1, bidirectional=True)}
                for name in ('PC1', 'SW1', 'R1', 'PC2'):
                    details[name] = manager.inspect(name)
                    for filename in ('dhcp.log', 'dhcp-relay.log', 'ospf.log'):
                        path = manager.directory / name / filename
                        if path.exists():
                            details[name][filename] = path.read_text()[-4000:]
                self.fail('Timed out: ' + label + '; observations=' + json.dumps(details))
            def address():
                return [a['local'] for row in json.loads(manager.ns(0, 'ip', '-j', '-4', 'addr', 'show', 'dev', 'eth0').stdout)
                        for a in row.get('addr_info', []) if a.get('scope') == 'global']
            def signal(value):
                manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -' + value + ' "$(/bin/cat /run/udhcpc.pid)"')
            def check(**options):
                before = copy.deepcopy(manager.read())
                report = verify(manager, 'PC1', 'PC2', count=2, **options)
                self.assertEqual(before, manager.read())
                return report
            try:
                with manager.locked():
                    manager.start(spec)
                    wait(lambda: address() == ['192.0.2.100'], 'observed DHCP address')
                    wait(lambda: manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '203.0.113.10', check=False).returncode == 0,
                         'actual route convergence and ARP warmup')
                event = threading.Event(); path = Path(folder) / 'verify.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', path,
                    seconds=5, packets=100, expression='icmp', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5); self.fail('Verification capture not ready')
                with manager.locked():
                    report = check(bidirectional=True)
                    self.assertEqual(report['status'], 'passed'); self.assertEqual(report['probe_commands_attempted'], 2)
                    self.assertEqual(report['directions'][1]['destination_address'], '192.0.2.100')
                    for direction in report['directions']:
                        self.assertEqual((direction['transmitted'], direction['received']), (2, 2))
                        self.assertEqual(direction['reply_ttls'], [62, 62])
                    self.assertIn('RÉUSSI', render(report))
                self.assertGreater(future.result(timeout=8)['captured_packets'], 0)
                text = run(['tcpdump', '-nn', '-r', str(path)]).stdout
                self.assertIn('ICMP echo request', text); self.assertIn('ICMP echo reply', text)
                with manager.locked():
                    initial = manager.ns(3, 'sysctl', '-n', 'net.ipv4.icmp_echo_ignore_all').stdout.strip()
                    try:
                        manager.ns(3, 'sysctl', '-w', 'net.ipv4.icmp_echo_ignore_all=1')
                        report = check()
                        self.assertEqual(report['status'], 'failed')
                        self.assertEqual(report['directions'][0]['received'], 0)
                        self.assertEqual(report['directions'][0]['route']['status'], 'observed')
                    finally:
                        manager.ns(3, 'sysctl', '-w', 'net.ipv4.icmp_echo_ignore_all=' + initial)
                    manager.ns(3, 'ip', 'link', 'set', 'eth0', 'down')
                    report = check()
                    self.assertEqual(report['status'], 'blocked', json.dumps(report)); self.assertEqual(report['probe_commands_attempted'], 0)
                    self.assertIn('INTERFACE_DOWN', report['endpoints'][1]['reasons'])
                    manager.ns(3, 'ip', 'link', 'set', 'eth0', 'up')
                    # Administrative link-down can remove the endpoint default route.
                    # Make that return-path fault explicit, then restore the fixture.
                    manager.ns(3, 'ip', 'route', 'del', 'default', check=False)
                    report = check(bidirectional=True)
                    self.assertEqual(report['status'], 'failed', json.dumps(report))
                    self.assertEqual(report['directions'][1]['route']['status'], 'command_failed')
                    manager.ns(3, 'ip', 'route', 'replace', 'default', 'via', spec['nodes'][3]['gateway'], 'dev', 'eth0')
                    manager.configure_ios('SW1', 'conf t\ninterface vlan10\nno ip helper-address 198.18.0.3\nend')
                    signal('USR2'); wait(lambda: not address(), 'released DHCP address')
                    report = check()
                    self.assertEqual(report['status'], 'blocked', json.dumps(report)); self.assertEqual(report['probe_commands_attempted'], 0)
                    self.assertIn('NO_USABLE_IPV4', report['endpoints'][0]['reasons'])
                    manager.configure_ios('SW1', 'conf t\ninterface vlan10\nip helper-address 198.18.0.3\nend')
                    signal('USR1'); wait(lambda: address() == ['192.0.2.100'], 'DHCP reacquisition')
                    wait(lambda: manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '203.0.113.10', check=False).returncode == 0,
                         'connectivity after restoring destination link/default gateway and DHCP')
                    self.assertEqual(check(bidirectional=True)['status'], 'passed')
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(run(['ip', '-j', 'rule', 'show']).stdout, rules)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)

    def test_appliance_aj_multi_vlan_ospf_dhcp_isolation_helpers_scoped_recovery_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import ospf_dhcp_multi_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.ospf import apply_change as apply_ospf, read_cli
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                bird=shutil.which('bird'), birdc=shutil.which('birdc'), dnsmasq=shutil.which('dnsmasq'))
            spec = ospf_dhcp_multi_lab(rootfs); spec['name'] = 'multi-ospf-' + str(os.getpid())
            manager = Manager(spec['name'])
            def wait(predicate, label):
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.2)
                self.fail('Timed out: ' + label)
            def addresses(node):
                index = 0 if node == 'PC1' else 6
                return [a['local'] for row in json.loads(manager.ns(index, 'ip', '-j', '-4', 'addr', 'show', 'dev', 'eth0').stdout)
                        for a in row.get('addr_info', []) if a.get('scope') == 'global']
            def lease(node):
                address, gateway, index = ('192.0.2.100', '192.0.2.1', 0) if node == 'PC1' else ('198.51.100.100', '198.51.100.1', 6)
                wait(lambda: addresses(node) == [address], 'actual lease ' + node)
                default = json.loads(manager.ns(index, 'ip', '-j', 'route', 'show', 'default').stdout)
                self.assertTrue(any(row.get('gateway') == gateway for row in default))
            def signal(node, value):
                manager.crun('exec', node, '/bin/sh', '-c', '/bin/kill -' + value + ' "$(/bin/cat /run/udhcpc.pid)"')
            def release(node):
                signal(node, 'USR2'); wait(lambda: not addresses(node), 'released ' + node)
            def ping(node, destination, ttl):
                def probe():
                    result = manager.crun('exec', node, '/bin/ping', '-c', '1', '-W', '1', destination, check=False)
                    return result.returncode == 0 and 'ttl=' + str(ttl) in result.stdout
                wait(probe, 'routed traffic from ' + node)
            def learned():
                wait(lambda: 'Full' in (read_cli(manager, 'SW1', 'show ospf neighbors') or ''), 'OSPF adjacency')
                for prefix in ('192.0.2.0/24', '198.51.100.0/24'):
                    def route():
                        rows = json.loads(manager.ns(2, 'ip', '-j', 'route', 'show', prefix).stdout)
                        return any(r.get('gateway') == '198.18.0.1' and r.get('protocol') in ('bird', 192, '192') for r in rows)
                    wait(route, 'learned client VLAN route ' + prefix)
            def traffic():
                lease('PC1'); lease('PC3'); learned()
                for node, address in (('PC1', '192.0.2.100'), ('PC3', '198.51.100.100')):
                    ping(node, '203.0.113.10', 62); ping('PC2', address, 62)
                ping('PC1', '198.51.100.100', 63); ping('PC3', '192.0.2.100', 63)
            def pid(path):
                return manager.crun('exec', 'SW1', '/bin/cat', path).stdout
            def capture_start(label, node):
                event = threading.Event(); path = Path(folder) / (label + '.pcap')
                future = pool.submit(capture, Manager(spec['name']), node, 'eth0', path,
                    seconds=4, packets=100, expression='udp and (port 67 or port 68)', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5); self.fail('Multi-VLAN capture not ready')
                return path, future
            def decoded(item):
                path, future = item; result = future.result(timeout=8)
                return result, run(['tcpdump', '-nn', '-vvv', '-r', str(path)]).stdout
            def helper(remove=False):
                return manager.configure_ios('SW1', 'conf t\ninterface vlan10\n' + ('no ' if remove else '') + 'ip helper-address 198.18.0.3\nend')
            try:
                with manager.locked():
                    manager.start(spec); traffic()
                    bird_pid = pid('/run/bird.pid'); release('PC1'); release('PC3')
                isolated = capture_start('vlan10-isolation', 'PC1')
                other = capture_start('vlan30-dora', 'DHCP1')
                with manager.locked():
                    signal('PC3', 'USR1')
                result, _ = decoded(isolated); self.assertEqual(result['captured_packets'], 0)
                _, text = decoded(other)
                for message in ('Discover', 'Offer', 'Request', 'ACK', 'Gateway-IP 198.51.100.1'):
                    self.assertIn(message, text)
                first = capture_start('vlan10-dora', 'DHCP1')
                with manager.locked():
                    signal('PC1', 'USR1')
                _, text = decoded(first)
                for message in ('Discover', 'Offer', 'Request', 'ACK', 'Gateway-IP 192.0.2.1'):
                    self.assertIn(message, text)
                with manager.locked():
                    traffic(); helper(True)
                    self.assertEqual(manager.state['spec']['nodes'][1]['dhcp_relay']['interface'], 'vlan30')
                    self.assertEqual(bird_pid, pid('/run/bird.pid')); traffic(); release('PC1')
                missing = capture_start('vlan10-no-helper', 'PC1')
                with manager.locked():
                    signal('PC1', 'USR1')
                _, text = decoded(missing)
                self.assertIn('Discover', text); self.assertNotIn('Offer', text)
                with manager.locked():
                    self.assertEqual(addresses('PC1'), []); release('PC3'); learned()
                available = capture_start('vlan30-helper-still-works', 'DHCP1')
                with manager.locked():
                    signal('PC3', 'USR1')
                _, text = decoded(available)
                self.assertIn('Offer', text); self.assertIn('ACK', text); self.assertIn('Gateway-IP 198.51.100.1', text)
                with manager.locked():
                    lease('PC3'); ping('PC3', '203.0.113.10', 62)
                    helper(); traffic()
                    identities = (pid('/run/bird.pid'), pid('/run/dhcp-relay.pid'))
                    calls = []
                    def fail_rollback(*args):
                        calls.append(True)
                        if len(calls) == 1:
                            apply_ospf(*args)
                        raise RuntimeFailure('Injected router OSPF reload/rollback failure')
                    with patch('network_labs.appliances.ospf.apply_change', side_effect=fail_rollback):
                        with self.assertRaisesRegex(RuntimeFailure, 'rollback failed'):
                            manager.configure_ios('R1', 'conf t\ninterface eth0\nip ospf cost 40\nend')
                    self.assertEqual(manager.read()['pending_node'], 'R1')
                    manager.recover()
                    self.assertNotIn('pending_node', manager.state); self.assertNotIn('pending_spec', manager.state)
                    self.assertEqual(identities, (pid('/run/bird.pid'), pid('/run/dhcp-relay.pid')))
                    self.assertEqual(bird_pid, pid('/run/bird.pid')); traffic()
                    manager.write_startup(); saved = load_startup(spec['name'])
                    self.assertEqual(len(saved['nodes'][1]['dhcp_relay']), 2)
                    self.assertEqual(len(saved['nodes'][5]['dhcp_pools']['pools']), 2)
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); traffic()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(run(['ip', '-j', 'rule', 'show']).stdout, rules)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)

    def test_appliance_ai_ospf_and_dhcp_relay_real_independent_edits_recover_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import ospf_dhcp_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.ospf import read_cli
        from network_labs.appliances.dhcp_relay import apply_change as apply_relay
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                bird=shutil.which('bird'), birdc=shutil.which('birdc'), dnsmasq=shutil.which('dnsmasq'))
            spec = ospf_dhcp_lab(rootfs); spec['name'] = 'ospf-dhcp-' + str(os.getpid())
            manager = Manager(spec['name'])
            def wait(predicate, label):
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.2)
                self.fail('Timed out: ' + label)
            def addresses():
                return [a['local'] for row in json.loads(manager.ns(0, 'ip', '-j', '-4', 'addr', 'show', 'dev', 'eth0').stdout)
                        for a in row.get('addr_info', []) if a.get('scope') == 'global']
            def lease():
                wait(lambda: addresses() == ['192.0.2.100'], 'actual reserved DHCP lease')
                default = json.loads(manager.ns(0, 'ip', '-j', 'route', 'show', 'default').stdout)
                self.assertTrue(any(row.get('gateway') == '192.0.2.1' for row in default))
            def full():
                wait(lambda: 'Full' in (read_cli(manager, 'SW1', 'show ospf neighbors') or ''), 'OSPF Full')
            def traffic():
                lease(); full()
                for node, destination in (('PC1', '203.0.113.10'), ('PC2', '192.0.2.100')):
                    def ping():
                        result = manager.crun('exec', node, '/bin/ping', '-c', '1', '-W', '1', destination, check=False)
                        return result.returncode == 0 and 'ttl=62' in result.stdout
                    wait(ping, 'actual bidirectional routed DHCP-client traffic')
            def signal(value):
                manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -' + value + ' "$(/bin/cat /run/udhcpc.pid)"')
            def release():
                signal('USR2'); wait(lambda: not addresses(), 'lease release')
            def cli(text):
                return manager.configure_ios('SW1', 'conf t\n' + text + '\nend')
            def pid(path):
                return manager.crun('exec', 'SW1', '/bin/cat', path).stdout
            def helper(remove=False):
                return cli('interface vlan10\n' + ('no ' if remove else '') + 'ip helper-address 198.18.0.3')
            def packets(filename, node, action):
                event = threading.Event(); path = Path(folder) / filename
                future = pool.submit(capture, Manager(spec['name']), node, 'eth0', path,
                    seconds=4, packets=100, expression='udp and (port 67 or port 68)', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5); self.fail('DHCP/OSPF composition capture not ready')
                with manager.locked():
                    action()
                future.result(timeout=8)
                return run(['tcpdump', '-nn', '-vvv', '-r', str(path)]).stdout
            try:
                with manager.locked():
                    manager.start(spec); traffic()
                    bird_pid = pid('/run/bird.pid'); relay_pid = pid('/run/dhcp-relay.pid')
                    cli('interface vlan20\nip ospf cost 40')
                    self.assertEqual(relay_pid, pid('/run/dhcp-relay.pid'))
                    self.assertEqual(bird_pid, pid('/run/bird.pid')); traffic(); release()
                dora = packets('dora.pcap', 'DHCP1', lambda: signal('USR1'))
                for message in ('Discover', 'Offer', 'Request', 'ACK', 'Gateway-IP 192.0.2.1'):
                    self.assertIn(message, dora)
                with manager.locked():
                    traffic(); helper(True)
                    self.assertEqual(bird_pid, pid('/run/bird.pid')); traffic(); release()
                missing = packets('no-helper.pcap', 'PC1', lambda: signal('USR1'))
                self.assertIn('Discover', missing); self.assertNotIn('Offer', missing)
                with manager.locked():
                    self.assertEqual(addresses(), []); full(); helper(); traffic()
                    self.assertEqual(bird_pid, pid('/run/bird.pid'))
                    revision = manager.state['revision']; calls = []
                    def fail_rollback(*args):
                        calls.append(True)
                        if len(calls) == 1:
                            apply_relay(*args)
                        raise RuntimeFailure('Injected helper failure with co-located OSPF')
                    with patch('network_labs.appliances.dhcp_relay.apply_change', side_effect=fail_rollback):
                        with self.assertRaisesRegex(RuntimeFailure, 'rollback failed'):
                            helper(True)
                    self.assertEqual(manager.state['phase'], 'configuration-failed')
                    manager.recover()
                    self.assertEqual(manager.state['revision'], revision)
                    self.assertEqual(bird_pid, pid('/run/bird.pid')); traffic()
                    release(); signal('USR1'); lease()
                    relay_pid = pid('/run/dhcp-relay.pid')
                    cli('no router ospf 1')
                    self.assertEqual(relay_pid, pid('/run/dhcp-relay.pid'))
                    wait(lambda: not json.loads(manager.ns(2, 'ip', '-j', 'route', 'show', '192.0.2.0/24').stdout), 'remote OSPF return route withdrawn')
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '203.0.113.10', check=False).returncode, 0)
                    release()
                independent = packets('dhcp-without-ospf.pcap', 'DHCP1', lambda: signal('USR1'))
                self.assertIn('Offer', independent); self.assertIn('ACK', independent)
                with manager.locked():
                    lease()
                    cli('router ospf 1\nrouter-id 1.1.1.1\nnetwork 192.0.2.0 0.0.0.255 area 0\nnetwork 198.18.0.0 0.0.0.7 area 0\npassive-interface vlan10\ninterface vlan20\nip ospf network broadcast\nip ospf cost 40')
                    self.assertEqual(relay_pid, pid('/run/dhcp-relay.pid')); traffic()
                    manager.write_startup(); saved = load_startup(spec['name'])
                    self.assertEqual(saved['nodes'][1]['ospf']['interfaces']['vlan20']['cost'], 40)
                    self.assertEqual(saved['nodes'][1]['dhcp_relay'], spec['nodes'][1]['dhcp_relay'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); traffic()
                    observed = manager.inspect('SW1')
                    self.assertTrue(observed['ospf']['configuration_verified'])
                    self.assertTrue(observed['dhcp_relay']['configuration_verified'])
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(run(['ip', '-j', 'rule', 'show']).stdout, rules)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)

    def test_appliance_ah_ospf_svi_real_trunk_routes_cli_withdrawal_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import ospf_svi_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.ospf import read_cli
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', bird=shutil.which('bird'), birdc=shutil.which('birdc'))
            spec = ospf_svi_lab(rootfs); spec['name'] = 'ospf-svi-' + str(os.getpid())
            manager = Manager(spec['name'])
            def wait(predicate, label):
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.2)
                self.fail('Timed out: ' + label + '; neighbors=' + repr(read_cli(manager, 'SW1', 'show ospf neighbors')))
            def route(index, prefix):
                rows = json.loads(manager.ns(index, 'ip', '-j', 'route', 'show', prefix).stdout)
                return rows[0] if rows else {}
            def traffic():
                wait(lambda: route(1, '203.0.113.0/24').get('gateway') == '198.18.0.2' and
                     route(2, '192.0.2.0/24').get('gateway') == '198.18.0.1', 'both learned routes')
                self.assertEqual(route(1, '203.0.113.0/24')['dev'], 'vlan20')
                self.assertIn(route(1, '203.0.113.0/24')['protocol'], ('bird', 192, '192'))
                for node, destination in (('PC1', '203.0.113.10'), ('PC2', '192.0.2.10')):
                    def ping():
                        result = manager.crun('exec', node, '/bin/ping', '-c', '1', '-W', '1', destination, check=False)
                        return result.returncode == 0 and 'ttl=62' in result.stdout
                    wait(ping, 'bidirectional routed traffic ' + node)
            def full():
                wait(lambda: 'Full' in (read_cli(manager, 'SW1', 'show ospf neighbors') or '') and
                     'Full' in (read_cli(manager, 'R1', 'show ospf neighbors') or ''), 'real SVI adjacency')
                traffic()
            def cli(text):
                return manager.configure_ios('SW1', 'conf t\n' + text + '\nend')
            try:
                with manager.locked():
                    manager.start(spec); full()
                    identities = (manager.crun('exec', 'SW1', '/bin/cat', '/run/bird.pid').stdout,
                                  manager.ns(1, 'ip', '-j', 'link', 'show', 'dev', 'vlan20').stdout)
                captures = []
                for name, port, expression in (('SW1', 'eth1', 'vlan 20 and ip proto 89'), ('PC1', 'eth0', 'ip proto 89')):
                    event = threading.Event(); path = Path(folder) / (name + '.pcap')
                    future = pool.submit(capture, Manager(spec['name']), name, port, path,
                                         seconds=3, packets=100, expression=expression, ready=event.set)
                    if not event.wait(5):
                        future.result(timeout=5); self.fail('SVI capture not ready')
                    captures.append((name, path, future))
                for name, path, future in captures:
                    result = future.result(timeout=8)
                    if name == 'PC1':
                        self.assertEqual(result['captured_packets'], 0)
                    else:
                        self.assertGreater(result['captured_packets'], 0)
                        text = run(['tcpdump', '-e', '-nn', '-vv', '-r', str(path)]).stdout
                        self.assertIn('vlan 20', text); self.assertIn('OSPFv2', text); self.assertIn('Hello', text)
                with manager.locked():
                    cli('interface vlan 20\nip ospf cost 40')
                    wait(lambda: 'Cost: 40' in (read_cli(manager, 'SW1', 'show ospf interface ospf4 "vlan20"') or ''), 'actual SVI cost reload')
                    self.assertEqual(identities, (manager.crun('exec', 'SW1', '/bin/cat', '/run/bird.pid').stdout,
                        manager.ns(1, 'ip', '-j', 'link', 'show', 'dev', 'vlan20').stdout))
                    full()
                    # Disabling the sole transit is invalid. Remove the process to test withdrawal.
                    cli('no router ospf 1')
                    wait(lambda: not route(1, '203.0.113.0/24') and not route(2, '192.0.2.0/24'), 'route withdrawal')
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '203.0.113.10', check=False).returncode, 0)
                    cli('router ospf 1\nrouter-id 1.1.1.1\nnetwork 192.0.2.0 0.0.0.255 area 0\nnetwork 198.18.0.0 0.0.0.7 area 0\npassive-interface vlan10\ninterface vlan20\nip ospf network broadcast\nip ospf cost 40')
                    full()
                    manager.write_startup(); saved = load_startup(spec['name'])
                    self.assertEqual(saved['nodes'][1]['ospf']['interfaces']['vlan20']['cost'], 40)
                    self.assertEqual(saved['nodes'][1]['svis'], spec['nodes'][1]['svis'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); full()
                    self.assertTrue(manager.inspect('SW1')['ospf']['configuration_verified'])
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(run(['ip', '-j', 'rule', 'show']).stdout, rules)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)

    def test_appliance_ag_ospf_interface_timers_real_mismatch_backup_capture_rollback_restore(self):
        import re
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from network_labs.appliances.examples import ospf_lab
        from network_labs.appliances.ospf import read_cli, apply_change
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', bird=shutil.which('bird'), birdc=shutil.which('birdc'))
            spec = ospf_lab(rootfs); spec['name'] = 'ospf-timers-' + str(os.getpid())
            manager = Manager(spec['name'])
            def route():
                rows = json.loads(manager.ns(2, 'ip', '-j', 'route', 'show', '198.51.100.0/24').stdout)
                return rows[0] if rows else {}
            def wait(predicate, label):
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.2)
                self.fail('Timed out: ' + label + '; route=' + repr(route()))
            def neighbor_is(node, peer, full):
                text = read_cli(manager, node, 'show ospf neighbors')
                if text is None:
                    return False
                rows = [line for line in text.splitlines() if peer in line]
                return any('Full' in line for line in rows) if full else not any('Full' in line for line in rows)
            def interface_timers(node, interface, hello, dead):
                text = read_cli(manager, node, 'show ospf interface ospf4 "' + interface + '"') or ''
                return re.search(r'Hello timer:\s+' + str(hello) + r'\b', text) and re.search(r'Dead timer:\s+' + str(dead) + r'\b', text)
            def traffic(gateway, ttl):
                wait(lambda: route().get('gateway') == gateway, 'actual next hop ' + gateway)
                def ping():
                    result = manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10', check=False)
                    return result.returncode == 0 and 'ttl=' + str(ttl) in result.stdout
                wait(ping, 'actual traffic reply TTL ' + str(ttl))
            def primary():
                wait(lambda: neighbor_is('R1', '2.2.2.2', True) and neighbor_is('R2', '1.1.1.1', True), 'matched-timer Full adjacency')
                traffic('10.0.12.2', 62)
            def configure(node, hello, dead):
                return manager.configure_ios(node, f'conf t\ninterface eth0\nip ospf hello-interval {hello}\nip ospf dead-interval {dead}\nend')
            def identities():
                return [(json.loads(manager.crun('state', node).stdout)['pid'],
                         manager.crun('exec', node, '/bin/cat', '/run/bird.pid').stdout,
                         [(r['ifname'], r['ifindex']) for r in json.loads(manager.ns(index, 'ip', '-j', 'link', 'show').stdout)])
                        for node, index in (('R1', 2), ('R2', 3))]
            try:
                with manager.locked():
                    manager.start(spec); primary()
                    original = identities(); revision = manager.read()['revision']
                    with self.assertRaisesRegex(ValueError, 'dead must exceed hello'):
                        manager.configure_ios('R1', 'conf t\ninterface eth0\nip ospf hello-interval 5\nend')
                    self.assertEqual(manager.read()['revision'], revision)
                    self.assertEqual(manager.read()['phase'], 'running')
                    configure('R1', 2, 8)
                    wait(lambda: neighbor_is('R1', '2.2.2.2', False) and neighbor_is('R2', '1.1.1.1', False), 'timer mismatch breaks only primary adjacency')
                    wait(lambda: neighbor_is('R1', '3.3.3.3', True) and neighbor_is('R2', '3.3.3.3', True), 'other interfaces retain Full adjacency')
                    traffic('10.0.13.2', 61)
                    wait(lambda: interface_timers('R1', 'eth0', 2, 8), 'real changed timers')
                    self.assertTrue(interface_timers('R1', 'eth1', 1, 4))
                    self.assertEqual(identities(), original)
                # Decode the real Hello on the mismatched wire, not the manifest.
                event = threading.Event(); path = Path(folder) / 'ospf-timers.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'R1', 'eth0', path, seconds=3, packets=100,
                                     expression='ip proto 89 and src host 10.0.12.1', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5); self.fail('OSPF timer capture not ready')
                captured = future.result(timeout=7)
                packets = run(['tcpdump', '-nn', '-vv', '-r', str(path)]).stdout
                self.assertGreater(captured['captured_packets'], 0)
                self.assertIn('OSPFv2', packets)
                self.assertIn('Hello Timer 2s', packets); self.assertIn('Dead Timer 8s', packets)
                with manager.locked():
                    configure('R2', 2, 8); primary()
                    self.assertTrue(interface_timers('R2', 'eth0', 2, 8))
                    self.assertTrue(interface_timers('R2', 'eth1', 1, 4))
                    self.assertEqual(identities(), original)
                    manager.write_startup(); saved = load_startup(spec['name'])
                    for index in (2, 3):
                        policy = saved['nodes'][index]['ospf']
                        self.assertEqual((policy['hello'], policy['dead']), (1, 4))
                        self.assertEqual((policy['interfaces']['eth0']['hello'], policy['interfaces']['eth0']['dead']), (2, 8))
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); primary()
                    self.assertTrue(interface_timers('R1', 'eth0', 2, 8))
                    before = identities(); revision = manager.read()['revision']; calls = []
                    def fail_after_reload(actual_manager, index, node, previous):
                        apply_change(actual_manager, index, node, previous)
                        calls.append(node['ospf']['interfaces']['eth0']['hello'])
                        if len(calls) == 1:
                            raise RuntimeFailure('injected failure after actual timer reload')
                    with patch('network_labs.appliances.ospf.apply_change', side_effect=fail_after_reload):
                        with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                            configure('R1', 3, 12)
                    self.assertEqual(calls, [3, 2]); self.assertEqual(manager.read()['revision'], revision)
                    self.assertEqual(manager.read()['phase'], 'running')
                    wait(lambda: interface_timers('R1', 'eth0', 2, 8), 'rollback reloads actual old timers')
                    primary(); self.assertEqual(identities(), before)
            except Exception:
                for name in ('R1', 'R2', 'R3'):
                    path = manager.directory / name / 'ospf.log'
                    if path.exists():
                        print(name + ': ' + path.read_text()[-5000:])
                raise
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(run(['ip', '-j', 'rule', 'show']).stdout, rules)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)

    def test_appliance_a_static_route_cli_return_path_longest_prefix_rollback_and_restore(self):
        from network_labs.appliances.examples import static_routing_lab
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.capture import capture
        from network_labs.appliances.firewall import fingerprint
        from concurrent.futures import ThreadPoolExecutor
        import threading
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = static_routing_lab(rootfs); spec['name'] = 'routes-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def config(node, text):
                return manager.configure_ios(node, 'conf t\n' + text + '\nend')
            def ping(success=True, client='PC1', target='203.0.113.10'):
                result = manager.crun('exec', client, '/bin/ping', '-c', '1', '-W', '1', target, check=False)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                if success:
                    self.assertIn('ttl=62', result.stdout)
                return result
            forward = 'ip route 203.0.113.0 255.255.255.0 198.18.0.2'
            backward = 'ip route 192.0.2.0 255.255.255.0 gi0/0 198.18.0.1'
            default = 'ip route 0.0.0.0 0.0.0.0 198.18.0.2'
            narrow = 'ip route 203.0.113.10 255.255.255.255 vlan20 198.18.0.3'
            try:
                with manager.locked():
                    manager.start(spec); ping(False)
                    config('SW1', forward)
                    # Some Linux distributions inherit loose/strict reverse-path
                    # filtering into namespaces. Isolate missing-return-route
                    # behavior from that separate source-validation policy.
                    rpf_keys = ('net.ipv4.conf.all.rp_filter', 'net.ipv4.conf.eth0.rp_filter')
                    rpf_before = manager.ns(2, 'sysctl', '-n', *rpf_keys).stdout.splitlines()
                    self.assertEqual(len(rpf_before), len(rpf_keys))
                    print('STATIC ROUTE R1 initial rp_filter: ' + repr(rpf_before), flush=True)
                    manager.ns(2, 'sysctl', '-w', *[key + '=0' for key in rpf_keys])
                    self.assertEqual(manager.ns(2, 'sysctl', '-n', *rpf_keys).stdout.splitlines(), ['0', '0'])
                # The request really arrives at PC2; only the return route is missing.
                ready = threading.Event(); pcap = Path(folder) / 'missing-return.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC2', 'eth0', pcap,
                                     seconds=5, packets=1, expression='icmp and icmp[0] = 8', ready=ready.set)
                self.assertTrue(ready.wait(5))
                with manager.locked():
                    ping(False)
                self.assertEqual(future.result(timeout=8)['captured_packets'], 1)
                decoded = run(['tcpdump', '-n', '-vv', '-r', pcap]).stdout
                self.assertIn('192.0.2.10 > 203.0.113.10', decoded)
                self.assertIn('echo request', decoded); self.assertIn('ttl 62', decoded)
                with manager.locked():
                    config('R1', backward)
                    manager.ns(2, 'sysctl', '-w', *[key + '=' + value for key, value in zip(rpf_keys, rpf_before)])
                    ping(); ping(client='PC2', target='192.0.2.10')
                    actual = manager.inspect('SW1')['routes']
                    self.assertTrue(any(r.get('dst') == '203.0.113.0/24' and r.get('dev') == 'vlan20' and
                                        r.get('gateway') == '198.18.0.2' and r.get('protocol') == 'static' for r in actual))
                    # Failure after the actual /24 deletion must re-create that route.
                    original_ns = manager.ns; armed = [True]; deleted = [False]
                    def interrupted(index, *args, **kwargs):
                        if armed[0] and index == 1 and args[:4] == ('ip', '-4', 'route', 'replace'):
                            deleted[0] = not any(r.get('dst') == '203.0.113.0/24' for r in
                                                 json.loads(original_ns(1, 'ip', '-j', '-4', 'route', 'show').stdout))
                            armed[0] = False
                            raise RuntimeFailure('Injected route failure after real deletion')
                        return original_ns(index, *args, **kwargs)
                    revision = manager.state['revision']
                    with patch.object(manager, 'ns', side_effect=interrupted), self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                        config('SW1', 'no ' + forward + '\n' + narrow)
                    self.assertTrue(deleted[0]); self.assertFalse(armed[0])
                    self.assertEqual(manager.state['revision'], revision); ping()
                    # An observed extra route must not silently enter a saved manifest.
                    manager.ns(1, 'ip', 'route', 'add', '203.0.113.10/32', 'via', '198.18.0.3', 'dev', 'vlan20', 'proto', 'static')
                    with self.assertRaisesRegex(RuntimeFailure, 'static routes'):
                        manager.write_startup()
                    manager.ns(1, 'ip', 'route', 'del', '203.0.113.10/32')
                    config('SW1', default + '\nno ' + forward); ping()
                    config('SW1', narrow); ping(False)
                    config('SW1', 'no ' + narrow); ping()
                    config('SW1', forward + '\nno ' + default); ping()
                    self.assertFalse(any(r.get('dst') == 'default' for r in manager.inspect('SW1')['routes']))
                    config('SW1', default)
                    config('R1', 'no ' + backward); ping(False)
                    config('R1', backward); ping()
                    manager.write_startup(); saved = load_startup(spec['name']); manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved); ping(); ping(client='PC2', target='192.0.2.10')
                    actual = manager.inspect('SW1')['routes']
                    self.assertTrue(any(r.get('dst') == 'default' and r.get('gateway') == '198.18.0.2' for r in actual))
                    manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), rules)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout, forwarding)

    def test_appliance_aa_route_lookup_kernel_policy_no_packets_and_forwarding_context(self):
        from network_labs.appliances.examples import static_routing_lab
        from network_labs.appliances.route_lookup import lookup
        from network_labs.appliances.diagnostics import explain_node
        from network_labs.appliances.capture import capture
        from network_labs.appliances.firewall import fingerprint
        from concurrent.futures import ThreadPoolExecutor
        import ipaddress
        import threading
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', '-4', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        host_settings = run(['sysctl', '-n', 'net.ipv4.ip_forward', 'net.ipv4.conf.all.rp_filter']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = static_routing_lab(rootfs); spec['name'] = 'lookup-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def ping(success=True):
                result = manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '203.0.113.10', check=False)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
            def query():
                return lookup(manager, 'SW1', '203.0.113.10', source='192.0.2.10', ingress='vlan10')
            def prefix(report):
                return str(ipaddress.IPv4Network(report['fibmatch']['records'][0]['dst'], strict=False))
            try:
                with manager.locked():
                    manager.start(spec)
                    missing = lookup(manager, 'SW1', '203.0.113.10')
                    self.assertEqual(missing['lookup']['status'], 'command_failed')
                    self.assertIsNone(missing['selected'])
                    manager.configure_ios('SW1', 'conf t\nip route 203.0.113.0 255.255.255.0 198.18.0.2\nend')
                    manager.configure_ios('R1', 'conf t\nip route 192.0.2.0 255.255.255.0 198.18.0.1\nend')
                    ping()
                    actual = manager.inspect('SW1')
                    self.assertTrue(actual['ipv4_settings']['available'])
                    self.assertEqual(actual['ipv4_settings']['interfaces']['vlan10']['forwarding'], 1)
                    self.assertIn('IPV4_SOURCE_VALIDATION', {row['code'] for row in explain_node(manager.state['spec']['nodes'][1], actual)})
                    report = query()
                    self.assertEqual(report['selected']['gateway'], '198.18.0.2')
                    self.assertEqual(report['selected']['dev'], 'vlan20')
                    self.assertEqual(prefix(report), '203.0.113.0/24')
                    local = lookup(manager, 'SW1', '192.0.2.1')
                    self.assertEqual(local['selected']['type'], 'local'); self.assertIsNone(local['neighbors'])
                    # A route lookup must not resolve an empty Ethernet cache
                    # by sending ARP, nor send an ICMP probe under the hood.
                    manager.ns(1, 'ip', '-4', 'neigh', 'flush', 'dev', 'vlan20')
                    self.assertEqual(json.loads(manager.ns(1, 'ip', '-j', '-4', 'neigh', 'show', 'dev', 'vlan20').stdout), [])
                    revision = manager.state['revision']
                    before_routes = manager.ns(1, 'ip', '-j', '-4', 'route', 'show', 'table', 'all').stdout
                    before_rules = manager.ns(1, 'ip', '-j', '-4', 'rule', 'show').stdout
                ready = threading.Event()
                future = pool.submit(capture, Manager(spec['name']), 'SW1', 'vlan20', Path(folder) / 'passive-lookup.pcap',
                                     seconds=2, packets=10, expression='arp or icmp', ready=ready.set)
                self.assertTrue(ready.wait(5))
                with manager.locked():
                    for _ in range(3):
                        report = query()
                        self.assertEqual(report['neighbors']['records'], [])
                        self.assertIn('NEIGHBOR_NOT_CACHED', {row['code'] for row in report['findings']})
                        self.assertFalse(report['test_packets_sent'])
                        self.assertEqual(report['packet_delivery'], 'not_tested')
                    self.assertEqual(manager.state['revision'], revision)
                    self.assertEqual(manager.ns(1, 'ip', '-j', '-4', 'route', 'show', 'table', 'all').stdout, before_routes)
                    self.assertEqual(manager.ns(1, 'ip', '-j', '-4', 'rule', 'show').stdout, before_rules)
                self.assertEqual(future.result(timeout=6)['captured_packets'], 0)
                with manager.locked():
                    ping()
                    # A local FIB decision can exist while ingress forwarding
                    # is disabled and actual transit packets are refused.
                    manager.ns(1, 'sysctl', '-w', 'net.ipv4.conf.vlan10.forwarding=0')
                    actual = manager.inspect('SW1')
                    self.assertTrue(actual['forwarding'])
                    self.assertEqual(actual['ipv4_settings']['interfaces']['vlan10']['forwarding'], 0)
                    self.assertIn('vlan10=off', next(row for row in explain_node(manager.state['spec']['nodes'][1], actual)
                                                   if row['code'] == 'IPV4_INGRESS_FORWARDING')['message'])
                    self.assertIn('INGRESS_FORWARDING_DISABLED', {row['code'] for row in query()['findings']})
                    report = lookup(manager, 'SW1', '203.0.113.10')
                    self.assertIsNotNone(report['selected']); self.assertEqual(report['packet_delivery'], 'not_tested')
                    ping(False)
                    manager.ns(1, 'sysctl', '-w', 'net.ipv4.conf.vlan10.forwarding=1'); ping()
                    # Use an external policy table to prove the observation
                    # follows the real RPDB, not the declared topology/routes.
                    manager.ns(1, 'ip', 'route', 'add', 'blackhole', '203.0.113.0/24', 'table', '100')
                    manager.ns(1, 'ip', 'rule', 'add', 'priority', '100', 'to', '203.0.113.0/24', 'lookup', '100')
                    report = lookup(manager, 'SW1', '203.0.113.10')
                    self.assertEqual(report['lookup']['status'], 'command_failed'); self.assertIsNone(report['selected'])
                    self.assertTrue(any(row.get('priority') == 100 and str(row.get('table')) == '100' for row in report['rules']['records']))
                    ping(False)
                    manager.ns(1, 'ip', 'rule', 'del', 'priority', '100', 'to', '203.0.113.0/24', 'lookup', '100')
                    manager.ns(1, 'ip', 'route', 'del', 'blackhole', '203.0.113.0/24', 'table', '100'); ping()
                    manager.configure_ios('SW1', 'conf t\nip route 203.0.113.10 255.255.255.255 198.18.0.3\nend')
                    report = query()
                    self.assertEqual(prefix(report), '203.0.113.10/32')
                    self.assertEqual(report['selected']['gateway'], '198.18.0.3')
                    self.assertEqual(report['neighbors']['records'], [])
                    ping(False)
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        report = query()
                        if any(row['code'] == 'NEIGHBOR_FAILED' for row in report['findings']):
                            break
                        time.sleep(0.1)
                    self.assertIn('NEIGHBOR_FAILED', {row['code'] for row in report['findings']})
                    # NOARP is normally omitted by ip neigh show's defaults.
                    # It remains a cached kernel state, never a delivery claim.
                    manager.ns(1, 'ip', 'neigh', 'replace', '198.18.0.3', 'lladdr', '02:00:00:aa:bb:cc',
                               'nud', 'noarp', 'dev', 'vlan20')
                    report = query()
                    self.assertTrue(any('NOARP' in row.get('state', []) for row in report['neighbors']['records']))
                    self.assertIn('NEIGHBOR_CACHED', {row['code'] for row in report['findings']})
                    self.assertEqual(report['packet_delivery'], 'not_tested')
                    manager.ns(1, 'ip', 'neigh', 'del', '198.18.0.3', 'dev', 'vlan20')
                    manager.configure_ios('SW1', 'conf t\nno ip route 203.0.113.10 255.255.255.255 198.18.0.3\nend')
                    self.assertEqual(prefix(query()), '203.0.113.0/24'); ping()
                    manager.configure_ios('SW1', 'conf t\ninterface vlan10\nshutdown\nend')
                    self.assertIn('INGRESS_ADMIN_DOWN', {row['code'] for row in query()['findings']}); ping(False)
                    manager.configure_ios('SW1', 'conf t\ninterface vlan10\nno shutdown\nend'); ping()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(run(['ip', '-j', '-4', 'rule', 'show']).stdout, rules)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward', 'net.ipv4.conf.all.rp_filter']).stdout, host_settings)

    def test_appliance_ovs_real_rstp_bpdus_failover_vlan_drift_and_restore(self):
        from network_labs.appliances.examples import rstp_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.ovs import vsctl
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        host_db = run(['ovs-vsctl', '--timeout=2', '--format=json', 'list', 'Bridge'], check=False).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', openvswitch=True)
            spec = rstp_lab(rootfs); spec['name'] = 'rstp-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def wait_tree(root_port='eth1', alternate=True):
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    actual = {name: manager.inspect(name)['spanning_tree'] for name in ('SW1', 'SW2', 'SW3')}
                    root = actual['SW1']['bridge_id']
                    if root and all(t['protocol'] == 'rstp' and t['root_id'] == root and
                                    len(t['ports']) == 3 and all(p['state'] in ('forwarding', 'discarding', 'disabled') for p in t['ports'].values()) for t in actual.values()) and actual['SW3']['root_port'] == root_port and (not alternate or any(p['role'] == 'Alternate' and p['state'] == 'discarding' for t in actual.values() for p in t['ports'].values())):
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
                    first = wait_tree(); wait_ping()
                    self.assertTrue(first['SW1']['is_root'])
                    self.assertFalse(first['SW3']['is_root'])
                    self.assertEqual(first['SW3']['root_port'], 'eth1')
                    self.assertTrue(any(p['role'] == 'Alternate' and p['state'] == 'discarding' for t in first.values() for p in t['ports'].values()))
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
                    wait_tree(); wait_ping()
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
                    manager.write_startup(); saved = load_startup(spec['name'])
                    manager.crun('exec', 'SW3', '/bin/sh', '-c', '/bin/kill -KILL "$(/bin/cat /run/ovs/vswitchd.pid)"')
                    self.assertFalse(manager.inspect('SW3')['ovs']['controller_available'])
                    self.assertEqual(manager.inspect('SW3')['spanning_tree']['protocol'], 'unavailable')
                    with self.assertRaisesRegex(RuntimeFailure, 'OVS'):
                        manager.write_startup()
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    restored = wait_tree(); wait_ping()
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

    def test_appliance_l3_svis_real_gateways_intervlan_trunk_shutdown_rollback_and_restore(self):
        from network_labs.appliances.examples import svi_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        from concurrent.futures import ThreadPoolExecutor
        import threading
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_sysctl = run(['sysctl', '-n', 'net.ipv4.ip_forward', 'net.ipv4.conf.all.arp_ignore', 'net.ipv4.conf.all.arp_announce']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = svi_lab(rootfs); spec['name'] = 'svi-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def ping(client, target, success=True):
                result = manager.crun('exec', client, '/bin/ping', '-c', '1', '-W', '1', target, check=False)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                return result
            def wait_routed():
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    result = manager.crun('exec', 'PC2', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.20', check=False)
                    if result.returncode == 0:
                        self.assertIn('ttl=63', result.stdout)
                        return
                    time.sleep(0.1)
                self.fail('Real routed SVI/trunk traffic did not recover: ' + result.stdout)
            def captured(interface, filename, expression, count):
                ready = threading.Event()
                future = pool.submit(capture, Manager(spec['name']), 'SW1', interface, Path(folder) / filename,
                                     seconds=5, packets=count, expression=expression, ready=ready.set)
                if not ready.wait(5):
                    future.result(timeout=5); self.fail('SVI/trunk capture did not become ready')
                with manager.locked():
                    ping('PC2', '198.51.100.20')
                result = future.result(timeout=8)
                self.assertEqual(result['captured_packets'], count)
                return run(['tcpdump', '-n', '-e', '-vv', '-r', Path(folder) / filename]).stdout
            try:
                with manager.locked():
                    manager.start(spec)
                    ping('PC1', '192.0.2.20'); ping('PC3', '198.51.100.20')
                    ping('PC1', '192.0.2.1'); ping('PC3', '198.51.100.1')
                    ping('PC1', '198.51.100.10', success=False)
                    # A gateway in another VLAN must not answer ARP on VLAN10.
                    arp = manager.crun('exec', 'PC1', '/bin/busybox', 'arping', '-I', 'eth0', '-c', '1', '-w', '1', '198.51.100.1', check=False)
                    self.assertNotEqual(arp.returncode, 0)
                    self.assertIn('Sent 1 probe', arp.stdout)
                    self.assertIn('Received 0 response', arp.stdout)
                    manager.configure_ios('SW1', 'conf t\nip routing\nend')
                    wait_routed()
                    observed = manager.inspect('SW1')
                    self.assertTrue(observed['forwarding'])
                    self.assertTrue(all(r['encapsulation_verified'] and r['arp_verified'] for r in observed['svis'].values()))
                    connected = {(r.get('dst'), r.get('dev')) for r in observed['routes'] if r.get('protocol') == 'kernel'}
                    self.assertTrue({('192.0.2.0/24', 'vlan10'), ('198.51.100.0/24', 'vlan20')} <= connected)
                decoded = captured('eth2', 'svi-trunk.pcap', 'vlan and icmp', 4)
                self.assertIn('vlan 10', decoded); self.assertIn('vlan 20', decoded); self.assertIn('ttl 63', decoded)
                self.assertIn('ICMP', captured('vlan10', 'svi-interface.pcap', 'icmp', 2))
                with manager.locked():
                    manager.configure_ios('SW1', 'conf t\nno ip routing\nend')
                    ping('PC1', '198.51.100.10', success=False)
                    ping('PC1', '192.0.2.20'); ping('PC3', '198.51.100.20')
                    self.assertTrue(all(r['arp_verified'] for r in manager.inspect('SW1')['svis'].values()))
                    manager.configure_ios('SW1', 'conf t\nip routing\ninterface vlan 20\nshutdown\nend')
                    ping('PC1', '198.51.100.10', success=False)
                    ping('PC3', '198.51.100.20')  # SVI shutdown must preserve L2.
                    manager.configure_ios('SW1', 'conf t\ninterface Vlan20\nno shutdown\nend')
                    wait_routed()
                    # Refuse external changes to CPU/self VLAN membership and ARP settings.
                    manager.ns(4, 'bridge', 'vlan', 'add', 'dev', 'br0', 'vid', '30', 'self')
                    with self.assertRaisesRegex(RuntimeFailure, 'SVI'):
                        manager.write_startup()
                    manager.ns(4, 'bridge', 'vlan', 'del', 'dev', 'br0', 'vid', '30', 'self')
                    manager.ns(4, 'sysctl', '-w', 'net.ipv4.conf.vlan10.arp_ignore=0')
                    with self.assertRaisesRegex(RuntimeFailure, 'SVI'):
                        manager.write_startup()
                    manager.ns(4, 'sysctl', '-w', 'net.ipv4.conf.vlan10.arp_ignore=1')
                    # A failure after deleting vlan20 must recreate its real
                    # interface, CPU membership, address and forwarding path.
                    original_ns = manager.ns; armed = [True]
                    def interrupted(index, *args, **kwargs):
                        if armed[0] and args[:2] == ('sysctl', '-w') and any('.arp_ignore=' in str(arg) for arg in args):
                            armed[0] = False
                            raise RuntimeFailure('Injected failure after actual SVI removal')
                        return original_ns(index, *args, **kwargs)
                    revision = manager.state['revision']
                    with patch.object(manager, 'ns', side_effect=interrupted), self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                        manager.configure_ios('SW1', 'conf t\nno interface vlan20\nend')
                    self.assertFalse(armed[0]); self.assertEqual(manager.state['phase'], 'running')
                    self.assertEqual(manager.state['revision'], revision)
                    wait_routed()
                    manager.configure_ios('SW1', 'conf t\nno interface vlan 20\nend')
                    self.assertNotIn('vlan20', {r['ifname'] for r in manager.inspect('SW1')['links']})
                    ping('PC1', '198.51.100.10', success=False); ping('PC3', '198.51.100.20')
                    manager.configure_ios('SW1', 'conf t\ninterface vlan20\nip address 198.51.100.1 255.255.255.0\nno shutdown\nend')
                    wait_routed()
                    manager.configure_ios('SW1', 'conf t\ninterface vlan20\nshutdown\nend')
                    manager.write_startup(); saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    self.assertNotIn('UP', manager.inspect('SW1')['svis']['vlan20']['flags'])
                    ping('PC1', '198.51.100.10', success=False); ping('PC3', '198.51.100.20')
                    manager.configure_ios('SW1', 'conf t\ninterface vlan20\nno shutdown\nend')
                    wait_routed(); manager.write_startup()
            except BaseException:
                if manager.directory.exists():
                    try:
                        print('SVI OBSERVATION: ' + json.dumps(manager.inspect('SW1')))
                    except Exception as exc:
                        print('SVI observation unavailable: ' + str(exc))
                raise
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), host_rules)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward', 'net.ipv4.conf.all.arp_ignore', 'net.ipv4.conf.all.arp_announce']).stdout, host_sysctl)

    def test_appliance_lldp_real_neighbors_pcap_link_loss_daemon_loss_policy_drift_and_restore(self):
        from network_labs.appliances.examples import lldp_lab
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.capture import capture
        self.assertIsNotNone(shutil.which('lldpd'))
        self.assertIsNotNone(shutil.which('lldpcli'))
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                                          lldpd=shutil.which('lldpd'), lldpcli=shutil.which('lldpcli'))
            spec = lldp_lab(rootfs); spec['name'] = 'lldp-test-' + str(os.getpid())
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
                    wait_peers(expected); ping()
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
                    wait_peers(expected); ping()
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
                    path = manager.directory / 'SW1/files/lldpd.conf'; original = path.read_text()
                    try:
                        path.write_text(original + '# drift\n')
                        with self.assertRaisesRegex(RuntimeFailure, 'LLDP'):
                            manager.write_startup()
                    finally:
                        path.write_text(original)
                    manager.write_startup(); saved = load_startup(spec['name'])
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
                    wait_peers(expected); ping()
                    for name in expected:
                        self.assertTrue(manager.inspect(name)['lldp']['policy_verified'])
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), host_rules)

    def test_dns_real_udp_tcp_dhcp_resolver_http_failure_config_drift_and_restore(self):
        from network_labs.appliances.examples import dns_lab
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        from test_native_dns import DNS_QUERY, dns_response
        self.assertIsNotNone(shutil.which('dnsmasq'), 'Install dnsmasq-base for the explicitly requested native DNS test')
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', dnsmasq=shutil.which('dnsmasq'))
            spec = dns_lab(rootfs); spec['name'] = 'dns-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def query(host='intranet.lab.test', kind=1, transport='udp', check=True):
                return manager.ns(0, sys.executable, '-c', DNS_QUERY, host, str(kind), transport, check=check, timeout=5)
            def ready():
                deadline = time.monotonic() + 15
                last = ''
                while time.monotonic() < deadline:
                    resolver = manager.crun('exec', 'PC1', '/bin/cat', '/etc/resolv.conf', check=False)
                    if resolver.returncode == 0 and 'nameserver 10.10.0.2' in resolver.stdout:
                        result = query(check=False)
                        last = result.stderr
                        if result.returncode == 0:
                            self.assertEqual(dns_response(result.stdout)[1][0][-1], '10.10.0.20')
                            return
                    time.sleep(0.1)
                self.fail('Actual DHCP resolver/DNS not ready: ' + last + '\n' + (manager.directory / 'DNS1' / 'dns.log').read_text())
            def http_by_name():
                for client in ('PC1', 'PC2'):
                    result = manager.crun('exec', client, '/bin/busybox', 'nslookup', '-type=A', 'intranet.lab.test', timeout=10)
                    self.assertIn('10.10.0.20', result.stdout)
                    manager.crun('exec', client, '/bin/ping', '-c', '1', '-W', '1', 'intranet.lab.test', timeout=10)
                    web = manager.crun('exec', client, '/bin/busybox', 'wget', '-T', '3', '-q', '-O', '-', 'http://intranet.lab.test/', timeout=10)
                    self.assertIn('Network LABS HTTP via DNS', web.stdout)
            try:
                with manager.locked():
                    manager.start(spec)
                    ready(); http_by_name()
                    self.assertTrue(manager.inspect('PC2')['resolver']['configuration_verified'])
                    self.assertNotEqual(manager.crun('exec', 'PC2', '/bin/sh', '-c', 'echo changed > /etc/resolv.conf', check=False).returncode, 0)
                    for transport in ('udp', 'tcp'):
                        for host, kind, expected_rcode, expected_value in (
                            ('intranet.lab.test', 1, 0, '10.10.0.20'),
                            ('20.0.10.10.in-addr.arpa', 12, 0, 'intranet.lab.test'),
                            ('intranet.lab.test', 28, 0, None),
                            ('missing.lab.test', 1, 3, None)):
                            with self.subTest(transport=transport, host=host, kind=kind):
                                rcode, records = dns_response(query(host, kind, transport).stdout)
                                self.assertEqual(rcode, expected_rcode)
                                if expected_value is None:
                                    self.assertEqual(records, [])
                                else:
                                    self.assertEqual(records, [(host, kind, 1, 60, expected_value)])
                    server = manager.inspect('DNS1')['dns_server']
                    self.assertTrue(server['configuration_verified'])
                    self.assertTrue(any('udp' in row for row in server['listener_snapshot']))
                    self.assertTrue(any('tcp' in row for row in server['listener_snapshot']))
                    # Policy text conformity must not masquerade as daemon health.
                    manager.crun('exec', 'DNS1', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/dnsmasq.pid)"')
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline and manager.inspect('DNS1')['dns_server']['listener_snapshot']:
                        time.sleep(0.1)
                    stopped = manager.inspect('DNS1')['dns_server']
                    self.assertTrue(stopped['configuration_verified'])
                    self.assertEqual(stopped['listener_snapshot'], [])
                    for transport in ('udp', 'tcp'):
                        self.assertNotEqual(query(transport=transport, check=False).returncode, 0)
                    manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '10.10.0.20')
                    self.assertIn('Network LABS HTTP via DNS', manager.crun('exec', 'PC1', '/bin/busybox', 'wget', '-T', '3', '-q', '-O', '-', 'http://10.10.0.20/').stdout)
                    # Save stores declared policy; restore launches new services.
                    manager.write_startup(); saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    ready(); http_by_name()
                    for relative, equipment, component, message in (
                        ('DNS1/files/dnsmasq.conf', 'DNS1', 'dns_server', 'DNS server'),
                        ('PC2/files/resolv.conf', 'PC2', 'resolver', 'DNS resolver')):
                        path = manager.directory / relative
                        original = path.read_text()
                        try:
                            path.write_text(original + '# external drift\n')
                            self.assertFalse(manager.inspect(equipment)[component]['configuration_verified'])
                            with self.assertRaisesRegex(RuntimeFailure, message):
                                manager.write_startup()
                        finally:
                            path.write_text(original)
                    self.assertEqual(dns_response(query(transport='tcp').stdout)[1][0][-1], '10.10.0.20')
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), host_rules)

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
        links = host_links(); host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        records = []
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = source_guard_lab(rootfs); spec['name'] = 'ipsg-test-' + str(os.getpid())
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
                           'import socket,sys; s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)); s.bind(("eth0",0)); s.send(bytes.fromhex(sys.argv[1]))', packet.hex())
            def captured(name, expression, count, action):
                ready = threading.Event()
                future = pool.submit(capture, Manager(spec['name']), 'DHCP1', 'eth0', Path(folder) / name,
                                     seconds=2, packets=count, expression=expression, ready=ready.set)
                if not ready.wait(5):
                    future.result(timeout=5); self.fail('IPv4 capture readiness missing')
                with manager.locked():
                    action()
                return future.result(timeout=6)['captured_packets']
            try:
                with manager.locked():
                    manager.start(spec)
                    records.append(dict(manager.state['snooping_workers']['SW1']))
                    wait_ping(); wait_ping('ROGUE')
                    observed = manager.inspect('SW1')
                    self.assertTrue(observed['ip_source_guard']['policy_verified'])
                    self.assertNotIn('arp_inspection', observed)
                    lease = observed['dhcp_snooping']['bindings'][0]['address']
                    manager.crun('exec', 'ROGUE', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/udhcpd.pid)"')
                    # Permanent neighbours exclude ARP resolution as an
                    # explanation for either positive or negative delivery.
                    manager.ns(0, 'ip', 'neigh', 'replace', '10.10.0.2', 'lladdr', '02:00:00:00:10:02', 'nud', 'permanent', 'dev', 'eth0')
                    manager.ns(2, 'ip', 'neigh', 'replace', lease, 'lladdr', '02:00:00:00:10:10', 'nud', 'permanent', 'dev', 'eth0')
                    wait_ping(); manager.write_startup()
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
                    manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -USR2 "$(/bin/cat /run/udhcpc.pid)"; /bin/busybox sleep 0.2; /bin/kill -USR1 "$(/bin/cat /run/udhcpc.pid)"')
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
                    os.kill(record['pid'], signal.SIGKILL); time.sleep(2.3)
                    self.assertFalse(alive(record))
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '10.10.0.2', check=False).returncode, 0)
                    neighbours = json.loads(manager.ns(0, 'ip', '-j', 'neigh', 'show').stdout)
                    self.assertTrue(any(n.get('dst') == '10.10.0.2' and 'PERMANENT' in n.get('state', []) for n in neighbours), neighbours)
                    wait_ping('ROGUE')  # Static source authorization survives.
                    self.assertIsNone(manager.inspect('SW1')['dhcp_snooping']['bindings'])
                    manager.configure_ios('SW1', 'conf t\nip arp inspection vlan 10\ninterface fa0/1\nno shutdown\nend')
                    records.append(dict(manager.state['snooping_workers']['SW1']))
                    manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -USR2 "$(/bin/cat /run/udhcpc.pid)"; /bin/busybox sleep 0.2; /bin/kill -USR1 "$(/bin/cat /run/udhcpc.pid)"')
                    # The repaired observer now refreshes both ARP and IPv4
                    # grants. Flush cached neighbours to exercise both filters.
                    for index in (0, 2):
                        manager.ns(index, 'ip', 'neigh', 'flush', 'dev', 'eth0', 'nud', 'all')
                    wait_ping()
                    self.assertTrue(manager.inspect('SW1')['arp_inspection']['policy_verified'])
                    manager.write_startup(); saved = load_startup(spec['name'])
                    manager.ns(1, 'nft', 'delete', 'table', 'bridge', TABLE)
                    with self.assertRaisesRegex(RuntimeFailure, 'IP Source Guard'):
                        manager.write_startup()
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    records.append(dict(manager.state['snooping_workers']['SW1']))
                    wait_ping(); wait_ping('ROGUE')
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

    def test_dhcp_reservations_real_pool_exclusion_renewal_file_drift_and_restore(self):
        import copy
        from network_labs.appliances.examples import dhcp_reservations_lab
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links(); host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = dhcp_reservations_lab(rootfs); spec['name'] = 'res-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def wait_clients(reserved='10.10.0.100'):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    installed = {}
                    for name in ('PRN1', 'PC1', 'PC2'):
                        observation = manager.inspect(name)
                        ips = [a['local'] for r in observation['addresses'] if r['ifname'] == 'eth0'
                               for a in r.get('addr_info', []) if a.get('scope') == 'global']
                        if len(ips) == 1:
                            installed[name] = ips[0]
                    observed = manager.inspect('SW1')['dhcp_snooping']
                    bindings = {b['mac']: b['address'] for b in observed.get('bindings') or []}
                    expected = {n['name']: n['interface_macs']['eth0'] for n in manager.state['spec']['nodes'] if n['name'] in ('PRN1', 'PC1', 'PC2')}
                    if installed.get('PRN1') == reserved and len(installed) == 3 and all(bindings.get(expected[name]) == ip for name, ip in installed.items()):
                        self.assertEqual(len(set(installed.values())), 3, installed)
                        for name in ('PC1', 'PC2'):
                            self.assertIn(installed[name], ('10.10.0.100', '10.10.0.101', '10.10.0.102'))
                            self.assertNotEqual(installed[name], reserved)
                        return installed
                    time.sleep(0.1)
                self.fail('Real DHCP reservation/client/ACK mismatch: ' + json.dumps({'installed': installed, 'snooping': observed}) +
                          '\n' + (manager.directory / 'DHCP1' / 'dhcp.log').read_text())
            def reservation_stamp():
                bindings = manager.inspect('SW1')['dhcp_snooping'].get('bindings') or []
                return next((b['until'] for b in bindings if b['mac'] == '02:00:00:00:10:03'), 0)
            def wait_ack(previous):
                deadline = time.monotonic() + 8
                while reservation_stamp() <= previous:
                    if time.monotonic() >= deadline:
                        self.fail('No actual trusted DHCPACK observed after client signal.')
                    time.sleep(0.1)
            try:
                with manager.locked():
                    manager.start(spec)
                    installed = wait_clients()
                    # PC1 starts before the reserved client. Even then, the
                    # first pool IP is withheld from dynamic allocation.
                    self.assertEqual(set(installed.values()), {'10.10.0.100', '10.10.0.101', '10.10.0.102'})
                    server = manager.inspect('DHCP1')['dhcp_server']
                    self.assertTrue(server['configuration_verified'])
                    for name in ('PC1', 'PC2'):
                        manager.crun('exec', name, '/bin/ping', '-c', '1', '-W', '1', '10.10.0.100')
                    manager.crun('exec', 'PRN1', '/bin/ping', '-c', '1', '-W', '1', '10.10.0.2')
                    acknowledgments = reservation_stamp()
                    manager.crun('exec', 'PRN1', '/bin/sh', '-c', '/bin/kill -USR1 "$(/bin/cat /run/udhcpc.pid)"')
                    wait_ack(acknowledgments)
                    self.assertEqual(wait_clients()['PRN1'], '10.10.0.100')
                    # Release/reacquire also retains the explicit MAC/IP policy.
                    acknowledgments = reservation_stamp()
                    manager.crun('exec', 'PRN1', '/bin/sh', '-c', '/bin/kill -USR2 "$(/bin/cat /run/udhcpc.pid)"; /bin/busybox sleep 0.2; /bin/kill -USR1 "$(/bin/cat /run/udhcpc.pid)"')
                    wait_ack(acknowledgments)
                    self.assertEqual(wait_clients()['PRN1'], '10.10.0.100')
                    manager.write_startup(); saved = load_startup(spec['name'])
                    config = manager.directory / 'DHCP1' / 'files' / 'udhcpd.conf'
                    original = config.read_text(); config.write_text(original + '# host-side unmanaged change\n')
                    self.assertFalse(manager.inspect('DHCP1')['dhcp_server']['configuration_verified'])
                    with self.assertRaisesRegex(RuntimeFailure, 'DHCP server configuration'):
                        manager.write_startup()
                    config.write_text(original)
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    self.assertEqual(wait_clients()['PRN1'], '10.10.0.100')
                    self.assertTrue(manager.inspect('DHCP1')['dhcp_server']['configuration_verified'])
                    manager.stop()
                # Explicit reservations outside the dynamic pool are supported
                # too. A new generation has no old lease-file snapshot.
                outside = copy.deepcopy(saved)
                outside['nodes'][2]['dhcp_server']['reservations'][0]['address'] = '10.10.0.50'
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(outside)
                    self.assertEqual(wait_clients('10.10.0.50')['PRN1'], '10.10.0.50')
                    manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '10.10.0.50')
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
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
        links = host_links(); host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        group = '239.10.10.10'
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = multicast_lab(rootfs); spec['name'] = 'mcast-test-' + str(os.getpid())
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
                    future.result(timeout=5); self.fail('Multicast socket readiness missing')
                return future
            def send(selected=group):
                return probe(Manager(spec['name']), 'TX1', group=selected, text='Network LABS multicast', count=3)
            def captured(filename, selected=group, count=100):
                ready = threading.Event()
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', Path(folder) / filename,
                                     seconds=2, packets=count, expression='udp and dst host ' + selected + ' and dst port 5000', ready=ready.set)
                if not ready.wait(5):
                    future.result(timeout=5); self.fail('Multicast PCAP readiness missing')
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
                    queries.result(timeout=5); self.fail('IGMP query capture readiness missing')
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
                router = copy.deepcopy(policy); router['ports']['eth2']['router'] = 'permanent'
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
                    manager.write_startup(); saved = load_startup(spec['name'])
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
                receiver = receive(2); membership(True); send()
                self.assertGreater(receiver.result(timeout=5)['received_packets'], 0); receiver = None
                # Stop can acquire the lock while a bounded receiver is alive;
                # a pinned namespace never falls back to the host namespace.
                receiver = receive(2)
                with manager.locked():
                    manager.stop()
                self.assertEqual(receiver.result(timeout=5)['received_packets'], 0); receiver = None
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
                if receiver is not None:
                    receiver.result(timeout=35)
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
                    from network_labs.appliances.show import show, render as render_show
                    before_show = json.dumps(manager.read(), sort_keys=True)
                    stp_show = show(manager, 'SW3', 'show spanning-tree')
                    self.assertEqual(stp_show['status'], 'observed', stp_show)
                    self.assertEqual(stp_show['observation']['tree']['root_id'], tree['SW1']['bridge_id'])
                    self.assertIn('blocking', render_show(stp_show))
                    self.assertEqual(json.dumps(manager.read(), sort_keys=True), before_show)
                    self.assertTrue(ping('PC1', '192.0.2.30')); self.assertTrue(ping('PC2', '198.18.0.30'))
                    # Cutting the direct root link unblocks the alternate path through SW2.
                    apply('SW1', 'interface fa0/4\nshutdown')
                    tree = wait_tree('SW1', blocked=0)
                    self.assertEqual(tree['SW3']['root_port'], 'eth3')
                    stp_show = show(manager, 'SW3', 'show spanning-tree')
                    self.assertEqual(stp_show['status'], 'observed', stp_show)
                    self.assertEqual(stp_show['observation']['tree']['root_port'], 'eth3')
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
