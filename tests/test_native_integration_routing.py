"""Opt-in real OCI boot/packet tests. Routing on real containers: static routes, OSPF (adjacencies, broadcast election,
timers, SVIs), L3 switch gateways, routed LAN services, a twenty-node network.

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
class RoutingTests(RealContainerCase):
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
        links = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                bird=shutil.which('bird'), birdc=shutil.which('birdc'), dnsmasq=shutil.which('dnsmasq'),
                lldpd=shutil.which('lldpd'), lldpcli=shutil.which('lldpcli'))
            spec = lan_services_lab(rootfs)
            spec['name'] = 'services-' + str(os.getpid())
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
                        'ip', '-j', '-4', 'addr', 'show', 'dev', 'eth0').stdout) for a in row.get('addr_info', [])),
                        'DHCP address ' + client)
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
                    manager.start(spec)
                    ready()
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
                event = threading.Event()
                path = Path(folder) / 'services.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', path,
                    seconds=6, packets=100, expression='udp port 53 or tcp port 53 or tcp port 80', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5)
                    self.fail('Services capture not ready')
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
                    wait(lambda: query(check=False).returncode == 0, 'DNS restart')
                    ready()
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
                    wait(lambda: not json.loads(manager.ns(1, 'ip', '-j', 'route', 'show', '203.0.113.0/24').stdout),
                         'OSPF remote route withdrawal')
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
                    ready()
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    ready()
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
        links = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                bird=shutil.which('bird'), birdc=shutil.which('birdc'), dnsmasq=shutil.which('dnsmasq'),
                lldpd=shutil.which('lldpd'), lldpcli=shutil.which('lldpcli'))
            spec = ospf_dhcp_lldp_lab(rootfs)
            spec['name'] = 'lldp-ospf-' + str(os.getpid())
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
                lease(0, '192.0.2.100')
                lease(6, '198.51.100.100')
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
                    manager.start(spec)
                    neighbors(expected)
                    traffic()
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
                    bird = pid('SW1', '/run/bird.pid')
                    relay = pid('SW1', '/run/dhcp-relay.pid')
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
                self.assertIn('vlan 20', decoded)
                self.assertIn('OSPFv2', decoded)
                self.assertFalse(any('vlan ' in line and 'LLDP' in line for line in decoded.splitlines()), decoded)
                with manager.locked():
                    manager.ns(1, 'ip', 'link', 'set', 'eth1', 'down')
                    neighbors({'SW1': set(), 'SW2': {('eth1', 'R1', 'eth0')}, 'R1': expected['R1']})
                    wait(lambda: 'Full' not in (ospf_read(manager, 'SW1', 'show ospf neighbors') or ''), 'OSPF expiry after trunk loss')
                    self.assertNotEqual(ping('PC1', '203.0.113.10', check=False).returncode, 0)
                    manager.ns(1, 'ip', 'link', 'set', 'eth1', 'up')
                    neighbors(expected)
                    traffic()
                    self.assertEqual(lldp_pids(), identities)
                    for name in expected:
                        self.assertTrue(manager.inspect(name)['lldp']['policy_verified'])
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    neighbors(expected)
                    traffic()
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

    def test_appliance_ad_ospf_real_adjacencies_routes_failure_recovery_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import ospf_lab
        from network_labs.appliances.ospf import start_servers, read_cli
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', bird=shutil.which('bird'),
                                           birdc=shutil.which('birdc'))
            spec = ospf_lab(rootfs)
            spec['name'] = 'ospf-test-' + str(os.getpid())
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
                wait(lambda: all((read_cli(manager, node, 'show ospf neighbors') or '').lower().count('full') >= 2 for node in ('R1', 'R2',
                        'R3')), 'all real OSPF adjacencies Full')
                wait(lambda: (route() or {}).get('gateway') == '10.0.12.2', 'primary OSPF FIB route')
                self.assertIn(route().get('protocol'), ('bird', 192, '192'))
                ping(62)
            def record(filename, node, interface, expression='ip proto 89', action=None):
                event = threading.Event()
                path = Path(folder) / filename
                future = pool.submit(capture, Manager(spec['name']), node, interface, path,
                                     seconds=3, packets=100, expression=expression, ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5)
                    self.fail('OSPF capture not ready')
                if action is not None:
                    action()
                result = future.result(timeout=7)
                return result['captured_packets'], run(['tcpdump', '-nn', '-vv', '-r', str(path)]).stdout
            try:
                def before_daemons(actual_manager):
                    self.assertIsNone(route())
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10',
                                                     check=False).returncode, 0)
                    start_servers(actual_manager)
                with manager.locked():
                    with patch('network_labs.appliances.ospf.start_servers', side_effect=before_daemons):
                        manager.start(spec)
                    converged()
                count, packets = record('ospf-transit.pcap', 'R1', 'eth0')
                self.assertGreater(count, 0)
                self.assertIn('OSPFv2', packets)
                count, _ = record('ospf-passive.pcap', 'PC1', 'eth0')
                self.assertEqual(count, 0)
                with manager.locked():
                    manager.ns(2, 'ip', 'link', 'set', 'eth0', 'down')
                    wait(lambda: (route() or {}).get('gateway') == '10.0.13.2', 'backup next hop learned by OSPF')
                    ping(61)
                    manager.ns(2, 'ip', 'link', 'set', 'eth1', 'down')
                    wait(lambda: route() is None, 'OSPF route withdrawn after isolation')
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10',
                                                     check=False).returncode, 0)
                    manager.ns(2, 'ip', 'link', 'set', 'eth0', 'up')
                    wait(lambda: (route() or {}).get('gateway') == '10.0.12.2', 'primary recovered')
                    ping(62)
                    manager.ns(2, 'ip', 'link', 'set', 'eth1', 'up')
                    converged()
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
                self.assertGreater(count, 0)
                self.assertIn('ttl 61', packets)
                self.assertIn('echo request', packets)
                reverse = json.loads(manager.ns(3, 'ip', '-j', 'route', 'show', '192.0.2.0/24').stdout)
                self.assertEqual(reverse[0]['gateway'], '10.0.12.1')
                with manager.locked():
                    self.assertEqual(identity(), original_identity)
                    self.assertTrue(cli('interface eth0\nip ospf cost 100')['unchanged'])
                    self.assertEqual(manager.read()['revision'], changed['revision'])
                    cli('interface eth0\nip ospf cost 10')
                    converged()
                    cli('router ospf 1\npassive-interface eth0')
                    wait(lambda: (route() or {}).get('gateway') == '10.0.13.2', 'passive transit removes primary adjacency')
                    ping(61)
                    cli('router ospf 1\nno passive-interface eth0')
                    converged()
                    cli('router ospf 1\nnetwork 10.0.12.1 0.0.0.0 area 0\nno network 10.0.12.0 0.0.0.3 area 0')
                    converged()  # Exact-host selector still enables eth0.
                    cli('router ospf 1\nno network 10.0.12.1 0.0.0.0 area 0')
                    wait(lambda: (route() or {}).get('gateway') == '10.0.13.2', 'network removal disables OSPF on eth0')
                    ping(61)
                    self.assertEqual(manager.read()['spec']['nodes'][2]['ospf']['interfaces']['eth0']['cost'], 10)
                    cli('router ospf 1\nnetwork 10.0.12.0 0.0.0.3 area 0')
                    converged()
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
                    self.assertEqual(calls, [100, 10])
                    self.assertEqual(manager.read()['revision'], before)
                    self.assertEqual(manager.read()['phase'], 'running')
                    converged()
                    def fail_both(actual_manager, index, node, previous):
                        apply_change(actual_manager, index, node, previous)
                        raise RuntimeFailure('injected post-reload apply and rollback failure')
                    with patch('network_labs.appliances.ospf.apply_change', side_effect=fail_both):
                        with self.assertRaisesRegex(RuntimeFailure, 'rollback failed'):
                            cli('interface eth0\nip ospf cost 100')
                    self.assertEqual(manager.read()['phase'], 'configuration-failed')
                    manager.recover()
                    self.assertEqual(manager.read()['phase'], 'running')
                    converged()
                    self.assertEqual(identity(), original_identity)
                    path = manager.directory / 'R1/files/bird.conf'
                    original = path.read_text()
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
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertTrue(all(not node['routes'] for node in saved['nodes']))
                    manager.crun('exec', 'R1', '/usr/sbin/birdc', '-s', '/run/bird.ctl', 'down')
                    wait(lambda: read_cli(manager, 'R1', 'show status') is None, 'BIRD stopped')
                    wait(lambda: route() is None, 'daemon-owned routes removed on shutdown')
                    observed = manager.inspect('R1')['ospf']
                    self.assertTrue(observed['configuration_verified'])
                    self.assertIsNone(observed['neighbors'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    converged()
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
                    before = manager.read()['revision']
                    calls = []
                    def fail_after_lifecycle(actual_manager, index, node, previous):
                        apply_change(actual_manager, index, node, previous)
                        calls.append(node.get('ospf') is not None)
                        if len(calls) == 1:
                            raise RuntimeFailure('injected failure after actual OSPF lifecycle change')
                    with patch('network_labs.appliances.ospf.apply_change', side_effect=fail_after_lifecycle):
                        with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                            cli(remove)
                    self.assertEqual(calls, [False, True])
                    self.assertEqual(manager.read()['revision'], before)
                    converged()
                    self.assertEqual(identity()[1:], baseline)
                    # A forged PID file pointing at init must not select it.
                    manager.crun('exec', 'R1', '/bin/sh', '-c', 'echo 1 > /run/bird.pid')
                    cli(remove)
                    wait(lambda: route() is None, 'CLI removal withdraws BIRD routes')
                    self.assertEqual(processes(manager, manager.read()['spec']['nodes'][2], managed=False), [])
                    self.assertFalse((manager.directory / 'R1/files/bird.conf').exists())
                    self.assertIsNone(read_cli(manager, 'R1', 'show status'))
                    self.assertEqual(json.loads(manager.crun('state', 'R1').stdout)['status'], 'running')
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10',
                                                     check=False).returncode, 0)
                    # A separate real BIRD process must stay untouched, and
                    # block managed creation instead of being adopted/killed.
                    manager.crun('exec', 'R1', '/bin/sh', '-c',
                                 'echo "router id 9.9.9.9; log stderr all; protocol device { scan time 1; }" > /tmp/foreign-bird.conf')
                    manager.crun('exec', '--detach', 'R1', '/usr/sbin/bird', '-f', '-c', '/tmp/foreign-bird.conf',
                                 '-s', '/run/foreign-bird.ctl', '-P', '/run/foreign-bird.pid',
                        log=manager.directory / 'R1/foreign-bird.log')
                    before = manager.read()['revision']
                    with self.assertRaisesRegex(RuntimeFailure, 'Unmanaged BIRD'):
                        cli(create)
                    self.assertEqual(manager.read()['revision'], before)
                    self.assertEqual(manager.read()['phase'], 'running')
                    manager.crun('exec', 'R1', '/usr/sbin/birdc', '-s', '/run/foreign-bird.ctl', 'show', 'status')
                    manager.crun('exec', 'R1', '/usr/sbin/birdc', '-s', '/run/foreign-bird.ctl', 'down')
                    wait(lambda: not processes(manager, manager.read()['spec']['nodes'][2], managed=False),
                         'foreign daemon stopped by its own control socket')
                    before = manager.read()['revision']
                    calls.clear()
                    with patch('network_labs.appliances.ospf.apply_change', side_effect=fail_after_lifecycle):
                        with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                            cli(create)
                    self.assertEqual(calls, [True, False])
                    self.assertEqual(manager.read()['revision'], before)
                    self.assertIsNone(manager.read()['spec']['nodes'][2]['ospf'])
                    self.assertEqual(processes(manager, manager.read()['spec']['nodes'][2], managed=False), [])
                    self.assertFalse((manager.directory / 'R1/files/bird.conf').exists())
                    with patch('network_labs.appliances.ospf.apply_change', side_effect=fail_both):
                        with self.assertRaisesRegex(RuntimeFailure, 'rollback failed'):
                            cli(create)
                    self.assertEqual(manager.read()['phase'], 'configuration-failed')
                    manager.recover()
                    self.assertEqual(manager.read()['phase'], 'running')
                    self.assertIsNone(manager.read()['spec']['nodes'][2]['ospf'])
                    self.assertEqual(processes(manager, manager.read()['spec']['nodes'][2], managed=False), [])
                    manager.write_startup()
                    disabled = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(disabled)
                    self.assertIsNone(manager.read()['spec']['nodes'][2]['ospf'])
                    self.assertIsNone(route())
                    self.assertIsNone(read_cli(manager, 'R1', 'show status'))
                    cli(create)
                    converged()
                    manager.write_startup()
                    created = load_startup(spec['name'])
                    self.assertEqual(created['nodes'][2]['ospf'], saved['nodes'][2]['ospf'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(created)
                    converged()

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
        links = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', bird=shutil.which('bird'),
                                           birdc=shutil.which('birdc'))
            spec = ospf_broadcast_lab(rootfs)
            spec['name'] = 'ospf-bcast-' + str(os.getpid())
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
                wait(lambda: all(field(name, 'Designated router (ID)') == dr and field(name,
                        'Backup designated router (ID)') == bdr for name in names), 'observed DR=' + dr + ', BDR=' + bdr)
            def route():
                rows = json.loads(manager.ns(5, 'ip', '-j', 'route', 'show', '198.51.100.0/24').stdout)
                return rows[0] if rows else {}
            def traffic():
                # One read for both fields: during re-election BIRD may withdraw and reinstall the route between two reads.
                wait(lambda: (lambda row: row.get('gateway') == '10.0.100.4' and row.get('protocol') in ('bird', 192, '192'))(route()),
                     'R3 kernel next hop directly to R4, not through DR, installed by BIRD')
                def ping():
                    result = manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10', check=False)
                    return result.returncode == 0 and 'ttl=62' in result.stdout
                wait(ping, 'real PC1/PC2 traffic across the shared LAN')
            def initial():
                elected('1.1.1.1', '2.2.2.2')
                wait(lambda: field('R1', 'State') == 'DR' and field('R2', 'State') == 'Backup' and
                     field('R3', 'State') == field('R4', 'State') == 'DROther', 'initial interface roles')
                wait(lambda: neighbor('R3', 4) == neighbor('R4', 3) == '2-Way', 'normal DROther-to-DROther 2-Way')
                wait(lambda: all(neighbor(name, other) == 'Full' for name in ('R3', 'R4') for other in (1, 2)),
                     'Full adjacencies with DR and BDR')
                self.assertEqual(field('R4', 'Priority'), '0')
                traffic()
            try:
                with manager.locked():
                    manager.start(spec)
                    initial()
                event = threading.Event()
                path = Path(folder) / 'ospf-broadcast.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'R3', 'eth0', path, seconds=3, packets=100,
                                     expression='ip proto 89', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5)
                    self.fail('Broadcast OSPF capture not ready')
                captured = future.result(timeout=7)
                packets = run(['tcpdump', '-nn', '-vv', '-r', str(path)]).stdout
                self.assertGreater(captured['captured_packets'], 0)
                self.assertIn('OSPFv2', packets)
                self.assertIn('Hello', packets)
                self.assertIn('224.0.0.5', packets)
                with manager.locked():
                    manager.ns(3, 'ip', 'link', 'set', 'eth0', 'down')
                    elected('2.2.2.2', '3.3.3.3', ('R2', 'R3', 'R4'))
                    wait(lambda: field('R2', 'State') == 'DR' and field('R3', 'State') == 'Backup',
                         'BDR promoted, eligible DROther becomes BDR')
                    self.assertEqual(field('R4', 'Priority'), '0')
                    self.assertEqual(field('R4', 'State'), 'DROther')
                    traffic()
                    manager.ns(3, 'ip', 'link', 'set', 'eth0', 'up')
                    elected('2.2.2.2', '3.3.3.3')
                    wait(lambda: neighbor('R1', 2) == neighbor('R1', 3) == 'Full' and neighbor('R1', 4) == '2-Way',
                         'returning higher-priority router does not preempt')
                    self.assertEqual(field('R1', 'State'), 'DROther')
                    self.assertEqual(field('R1', 'Priority'), '200')
                    traffic()
                    def cli(text):
                        return manager.configure_ios('R4', 'conf t\ninterface eth0\n' + text + '\nend')
                    cli('ip ospf priority 255')
                    wait(lambda: field('R4', 'Priority') == '255', 'CLI priority reached actual daemon')
                    elected('2.2.2.2', '3.3.3.3')
                    wait(lambda: neighbor('R4', 2) == neighbor('R4', 3) == 'Full', 'priority change rejoins elected routers')
                    self.assertEqual(field('R4', 'State'), 'DROther')
                    traffic()
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
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertEqual(saved['nodes'][6]['ospf']['interfaces']['eth0']['priority'], 0)
                    self.assertEqual(saved['nodes'][6]['ospf']['interfaces']['eth0']['network_type'], 'broadcast')
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    initial()
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

    def test_appliance_aj_multi_vlan_ospf_dhcp_isolation_helpers_scoped_recovery_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import ospf_dhcp_multi_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.ospf import apply_change as apply_ospf, read_cli
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                bird=shutil.which('bird'), birdc=shutil.which('birdc'), dnsmasq=shutil.which('dnsmasq'))
            spec = ospf_dhcp_multi_lab(rootfs)
            spec['name'] = 'multi-ospf-' + str(os.getpid())
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
                signal(node, 'USR2')
                wait(lambda: not addresses(node), 'released ' + node)
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
                lease('PC1')
                lease('PC3')
                learned()
                for node, address in (('PC1', '192.0.2.100'), ('PC3', '198.51.100.100')):
                    ping(node, '203.0.113.10', 62)
                    ping('PC2', address, 62)
                ping('PC1', '198.51.100.100', 63)
                ping('PC3', '192.0.2.100', 63)
            def pid(path):
                return manager.crun('exec', 'SW1', '/bin/cat', path).stdout
            def capture_start(label, node):
                event = threading.Event()
                path = Path(folder) / (label + '.pcap')
                future = pool.submit(capture, Manager(spec['name']), node, 'eth0', path,
                    seconds=4, packets=100, expression='udp and (port 67 or port 68)', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5)
                    self.fail('Multi-VLAN capture not ready')
                return path, future
            def decoded(item):
                path, future = item
                result = future.result(timeout=8)
                return result, run(['tcpdump', '-nn', '-vvv', '-r', str(path)]).stdout
            def helper(remove=False):
                return manager.configure_ios('SW1',
                                             'conf t\ninterface vlan10\n' + ('no ' if remove else '') + 'ip helper-address 198.18.0.3\nend')
            try:
                with manager.locked():
                    manager.start(spec)
                    traffic()
                    bird_pid = pid('/run/bird.pid')
                    release('PC1')
                    release('PC3')
                isolated = capture_start('vlan10-isolation', 'PC1')
                other = capture_start('vlan30-dora', 'DHCP1')
                with manager.locked():
                    signal('PC3', 'USR1')
                result, _ = decoded(isolated)
                self.assertEqual(result['captured_packets'], 0)
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
                    traffic()
                    helper(True)
                    self.assertEqual(manager.state['spec']['nodes'][1]['dhcp_relay']['interface'], 'vlan30')
                    self.assertEqual(bird_pid, pid('/run/bird.pid'))
                    traffic()
                    release('PC1')
                missing = capture_start('vlan10-no-helper', 'PC1')
                with manager.locked():
                    signal('PC1', 'USR1')
                _, text = decoded(missing)
                self.assertIn('Discover', text)
                self.assertNotIn('Offer', text)
                with manager.locked():
                    self.assertEqual(addresses('PC1'), [])
                    release('PC3')
                    learned()
                available = capture_start('vlan30-helper-still-works', 'DHCP1')
                with manager.locked():
                    signal('PC3', 'USR1')
                _, text = decoded(available)
                self.assertIn('Offer', text)
                self.assertIn('ACK', text)
                self.assertIn('Gateway-IP 198.51.100.1', text)
                with manager.locked():
                    lease('PC3')
                    ping('PC3', '203.0.113.10', 62)
                    helper()
                    traffic()
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
                    self.assertNotIn('pending_node', manager.state)
                    self.assertNotIn('pending_spec', manager.state)
                    self.assertEqual(identities, (pid('/run/bird.pid'), pid('/run/dhcp-relay.pid')))
                    self.assertEqual(bird_pid, pid('/run/bird.pid'))
                    traffic()
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertEqual(len(saved['nodes'][1]['dhcp_relay']), 2)
                    self.assertEqual(len(saved['nodes'][5]['dhcp_pools']['pools']), 2)
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    traffic()
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
        links = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                bird=shutil.which('bird'), birdc=shutil.which('birdc'), dnsmasq=shutil.which('dnsmasq'))
            spec = ospf_dhcp_lab(rootfs)
            spec['name'] = 'ospf-dhcp-' + str(os.getpid())
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
                lease()
                full()
                for node, destination in (('PC1', '203.0.113.10'), ('PC2', '192.0.2.100')):
                    def ping():
                        result = manager.crun('exec', node, '/bin/ping', '-c', '1', '-W', '1', destination, check=False)
                        return result.returncode == 0 and 'ttl=62' in result.stdout
                    wait(ping, 'actual bidirectional routed DHCP-client traffic')
            def signal(value):
                manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -' + value + ' "$(/bin/cat /run/udhcpc.pid)"')
            def release():
                signal('USR2')
                wait(lambda: not addresses(), 'lease release')
            def cli(text):
                return manager.configure_ios('SW1', 'conf t\n' + text + '\nend')
            def pid(path):
                return manager.crun('exec', 'SW1', '/bin/cat', path).stdout
            def helper(remove=False):
                return cli('interface vlan10\n' + ('no ' if remove else '') + 'ip helper-address 198.18.0.3')
            def packets(filename, node, action):
                event = threading.Event()
                path = Path(folder) / filename
                future = pool.submit(capture, Manager(spec['name']), node, 'eth0', path,
                    seconds=4, packets=100, expression='udp and (port 67 or port 68)', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5)
                    self.fail('DHCP/OSPF composition capture not ready')
                with manager.locked():
                    action()
                future.result(timeout=8)
                return run(['tcpdump', '-nn', '-vvv', '-r', str(path)]).stdout
            try:
                with manager.locked():
                    manager.start(spec)
                    traffic()
                    bird_pid = pid('/run/bird.pid')
                    relay_pid = pid('/run/dhcp-relay.pid')
                    cli('interface vlan20\nip ospf cost 40')
                    self.assertEqual(relay_pid, pid('/run/dhcp-relay.pid'))
                    self.assertEqual(bird_pid, pid('/run/bird.pid'))
                    traffic()
                    release()
                dora = packets('dora.pcap', 'DHCP1', lambda: signal('USR1'))
                for message in ('Discover', 'Offer', 'Request', 'ACK', 'Gateway-IP 192.0.2.1'):
                    self.assertIn(message, dora)
                with manager.locked():
                    traffic()
                    helper(True)
                    self.assertEqual(bird_pid, pid('/run/bird.pid'))
                    traffic()
                    release()
                missing = packets('no-helper.pcap', 'PC1', lambda: signal('USR1'))
                self.assertIn('Discover', missing)
                self.assertNotIn('Offer', missing)
                with manager.locked():
                    self.assertEqual(addresses(), [])
                    full()
                    helper()
                    traffic()
                    self.assertEqual(bird_pid, pid('/run/bird.pid'))
                    revision = manager.state['revision']
                    calls = []
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
                    self.assertEqual(bird_pid, pid('/run/bird.pid'))
                    traffic()
                    release()
                    signal('USR1')
                    lease()
                    relay_pid = pid('/run/dhcp-relay.pid')
                    cli('no router ospf 1')
                    self.assertEqual(relay_pid, pid('/run/dhcp-relay.pid'))
                    wait(lambda: not json.loads(manager.ns(2, 'ip', '-j', 'route', 'show', '192.0.2.0/24').stdout),
                         'remote OSPF return route withdrawn')
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '203.0.113.10',
                                                     check=False).returncode, 0)
                    release()
                independent = packets('dhcp-without-ospf.pcap', 'DHCP1', lambda: signal('USR1'))
                self.assertIn('Offer', independent)
                self.assertIn('ACK', independent)
                with manager.locked():
                    lease()
                    cli('router ospf 1\nrouter-id 1.1.1.1\nnetwork 192.0.2.0 0.0.0.255 area 0\nnetwork 198.18.0.0 0.0.0.7 area '
                        '0\npassive-interface vlan10\ninterface vlan20\nip ospf network broadcast\nip ospf cost 40')
                    self.assertEqual(relay_pid, pid('/run/dhcp-relay.pid'))
                    traffic()
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertEqual(saved['nodes'][1]['ospf']['interfaces']['vlan20']['cost'], 40)
                    self.assertEqual(saved['nodes'][1]['dhcp_relay'], spec['nodes'][1]['dhcp_relay'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    traffic()
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
        links = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', bird=shutil.which('bird'),
                                           birdc=shutil.which('birdc'))
            spec = ospf_svi_lab(rootfs)
            spec['name'] = 'ospf-svi-' + str(os.getpid())
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
                    manager.start(spec)
                    full()
                    identities = (manager.crun('exec', 'SW1', '/bin/cat', '/run/bird.pid').stdout,
                                  manager.ns(1, 'ip', '-j', 'link', 'show', 'dev', 'vlan20').stdout)
                captures = []
                for name, port, expression in (('SW1', 'eth1', 'vlan 20 and ip proto 89'), ('PC1', 'eth0', 'ip proto 89')):
                    event = threading.Event()
                    path = Path(folder) / (name + '.pcap')
                    future = pool.submit(capture, Manager(spec['name']), name, port, path,
                                         seconds=3, packets=100, expression=expression, ready=event.set)
                    if not event.wait(5):
                        future.result(timeout=5)
                        self.fail('SVI capture not ready')
                    captures.append((name, path, future))
                for name, path, future in captures:
                    result = future.result(timeout=8)
                    if name == 'PC1':
                        self.assertEqual(result['captured_packets'], 0)
                    else:
                        self.assertGreater(result['captured_packets'], 0)
                        text = run(['tcpdump', '-e', '-nn', '-vv', '-r', str(path)]).stdout
                        self.assertIn('vlan 20', text)
                        self.assertIn('OSPFv2', text)
                        self.assertIn('Hello', text)
                with manager.locked():
                    cli('interface vlan 20\nip ospf cost 40')
                    wait(lambda: 'Cost: 40' in (read_cli(manager, 'SW1', 'show ospf interface ospf4 "vlan20"') or ''),
                         'actual SVI cost reload')
                    self.assertEqual(identities, (manager.crun('exec', 'SW1', '/bin/cat', '/run/bird.pid').stdout,
                        manager.ns(1, 'ip', '-j', 'link', 'show', 'dev', 'vlan20').stdout))
                    full()
                    # Disabling the sole transit is invalid. Remove the process to test withdrawal.
                    cli('no router ospf 1')
                    wait(lambda: not route(1, '203.0.113.0/24') and not route(2, '192.0.2.0/24'), 'route withdrawal')
                    self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '203.0.113.10',
                                                     check=False).returncode, 0)
                    cli('router ospf 1\nrouter-id 1.1.1.1\nnetwork 192.0.2.0 0.0.0.255 area 0\nnetwork 198.18.0.0 0.0.0.7 area '
                        '0\npassive-interface vlan10\ninterface vlan20\nip ospf network broadcast\nip ospf cost 40')
                    full()
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertEqual(saved['nodes'][1]['ospf']['interfaces']['vlan20']['cost'], 40)
                    self.assertEqual(saved['nodes'][1]['svis'], spec['nodes'][1]['svis'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    full()
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
        links = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', bird=shutil.which('bird'),
                                           birdc=shutil.which('birdc'))
            spec = ospf_lab(rootfs)
            spec['name'] = 'ospf-timers-' + str(os.getpid())
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
                return manager.configure_ios(node,
                                             f'conf t\ninterface eth0\nip ospf hello-interval {hello}\nip ospf dead-interval {dead}\nend')
            def identities():
                return [(json.loads(manager.crun('state', node).stdout)['pid'],
                         manager.crun('exec', node, '/bin/cat', '/run/bird.pid').stdout,
                         [(r['ifname'], r['ifindex']) for r in json.loads(manager.ns(index, 'ip', '-j', 'link', 'show').stdout)])
                        for node, index in (('R1', 2), ('R2', 3))]
            try:
                with manager.locked():
                    manager.start(spec)
                    primary()
                    original = identities()
                    revision = manager.read()['revision']
                    with self.assertRaisesRegex(ValueError, 'dead must exceed hello'):
                        manager.configure_ios('R1', 'conf t\ninterface eth0\nip ospf hello-interval 5\nend')
                    self.assertEqual(manager.read()['revision'], revision)
                    self.assertEqual(manager.read()['phase'], 'running')
                    configure('R1', 2, 8)
                    wait(lambda: neighbor_is('R1', '2.2.2.2', False) and neighbor_is('R2', '1.1.1.1', False),
                         'timer mismatch breaks only primary adjacency')
                    wait(lambda: neighbor_is('R1', '3.3.3.3', True) and neighbor_is('R2', '3.3.3.3', True),
                         'other interfaces retain Full adjacency')
                    traffic('10.0.13.2', 61)
                    wait(lambda: interface_timers('R1', 'eth0', 2, 8), 'real changed timers')
                    self.assertTrue(interface_timers('R1', 'eth1', 1, 4))
                    self.assertEqual(identities(), original)
                # Decode the real Hello on the mismatched wire, not the manifest.
                event = threading.Event()
                path = Path(folder) / 'ospf-timers.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'R1', 'eth0', path, seconds=3, packets=100,
                                     expression='ip proto 89 and src host 10.0.12.1', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5)
                    self.fail('OSPF timer capture not ready')
                captured = future.result(timeout=7)
                packets = run(['tcpdump', '-nn', '-vv', '-r', str(path)]).stdout
                self.assertGreater(captured['captured_packets'], 0)
                self.assertIn('OSPFv2', packets)
                self.assertIn('Hello Timer 2s', packets)
                self.assertIn('Dead Timer 8s', packets)
                with manager.locked():
                    configure('R2', 2, 8)
                    primary()
                    self.assertTrue(interface_timers('R2', 'eth0', 2, 8))
                    self.assertTrue(interface_timers('R2', 'eth1', 1, 4))
                    self.assertEqual(identities(), original)
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    for index in (2, 3):
                        policy = saved['nodes'][index]['ospf']
                        self.assertEqual((policy['hello'], policy['dead']), (1, 4))
                        self.assertEqual((policy['interfaces']['eth0']['hello'], policy['interfaces']['eth0']['dead']), (2, 8))
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    primary()
                    self.assertTrue(interface_timers('R1', 'eth0', 2, 8))
                    before = identities()
                    revision = manager.read()['revision']
                    calls = []
                    def fail_after_reload(actual_manager, index, node, previous):
                        apply_change(actual_manager, index, node, previous)
                        calls.append(node['ospf']['interfaces']['eth0']['hello'])
                        if len(calls) == 1:
                            raise RuntimeFailure('injected failure after actual timer reload')
                    with patch('network_labs.appliances.ospf.apply_change', side_effect=fail_after_reload):
                        with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                            configure('R1', 3, 12)
                    self.assertEqual(calls, [3, 2])
                    self.assertEqual(manager.read()['revision'], revision)
                    self.assertEqual(manager.read()['phase'], 'running')
                    wait(lambda: interface_timers('R1', 'eth0', 2, 8), 'rollback reloads actual old timers')
                    primary()
                    self.assertEqual(identities(), before)
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
        links = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = static_routing_lab(rootfs)
            spec['name'] = 'routes-test-' + str(os.getpid())
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
                    manager.start(spec)
                    ping(False)
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
                ready = threading.Event()
                pcap = Path(folder) / 'missing-return.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC2', 'eth0', pcap,
                                     seconds=5, packets=1, expression='icmp and icmp[0] = 8', ready=ready.set)
                self.assertTrue(ready.wait(5))
                with manager.locked():
                    ping(False)
                self.assertEqual(future.result(timeout=8)['captured_packets'], 1)
                decoded = run(['tcpdump', '-n', '-vv', '-r', pcap]).stdout
                self.assertIn('192.0.2.10 > 203.0.113.10', decoded)
                self.assertIn('echo request', decoded)
                self.assertIn('ttl 62', decoded)
                with manager.locked():
                    config('R1', backward)
                    manager.ns(2, 'sysctl', '-w', *[key + '=' + value for key, value in zip(rpf_keys, rpf_before)])
                    ping()
                    ping(client='PC2', target='192.0.2.10')
                    actual = manager.inspect('SW1')['routes']
                    self.assertTrue(any(r.get('dst') == '203.0.113.0/24' and r.get('dev') == 'vlan20' and
                                        r.get('gateway') == '198.18.0.2' and r.get('protocol') == 'static' for r in actual))
                    # Failure after the actual /24 deletion must re-create that route.
                    original_ns = manager.ns
                    armed = [True]
                    deleted = [False]
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
                    self.assertTrue(deleted[0])
                    self.assertFalse(armed[0])
                    self.assertEqual(manager.state['revision'], revision)
                    ping()
                    # An observed extra route must not silently enter a saved manifest.
                    manager.ns(1, 'ip', 'route', 'add', '203.0.113.10/32', 'via', '198.18.0.3', 'dev', 'vlan20', 'proto', 'static')
                    with self.assertRaisesRegex(RuntimeFailure, 'static routes'):
                        manager.write_startup()
                    manager.ns(1, 'ip', 'route', 'del', '203.0.113.10/32')
                    config('SW1', default + '\nno ' + forward)
                    ping()
                    config('SW1', narrow)
                    ping(False)
                    config('SW1', 'no ' + narrow)
                    ping()
                    config('SW1', forward + '\nno ' + default)
                    ping()
                    self.assertFalse(any(r.get('dst') == 'default' for r in manager.inspect('SW1')['routes']))
                    config('SW1', default)
                    config('R1', 'no ' + backward)
                    ping(False)
                    config('R1', backward)
                    ping()
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    ping()
                    ping(client='PC2', target='192.0.2.10')
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
        links = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', '-4', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        host_settings = run(['sysctl', '-n', 'net.ipv4.ip_forward', 'net.ipv4.conf.all.rp_filter']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = static_routing_lab(rootfs)
            spec['name'] = 'lookup-test-' + str(os.getpid())
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
                    self.assertIn('IPV4_SOURCE_VALIDATION', {row['code'] for row in explain_node(manager.state['spec']['nodes'][1],
                                                                                                 actual)})
                    report = query()
                    self.assertEqual(report['selected']['gateway'], '198.18.0.2')
                    self.assertEqual(report['selected']['dev'], 'vlan20')
                    self.assertEqual(prefix(report), '203.0.113.0/24')
                    local = lookup(manager, 'SW1', '192.0.2.1')
                    self.assertEqual(local['selected']['type'], 'local')
                    self.assertIsNone(local['neighbors'])
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
                    self.assertIsNotNone(report['selected'])
                    self.assertEqual(report['packet_delivery'], 'not_tested')
                    ping(False)
                    manager.ns(1, 'sysctl', '-w', 'net.ipv4.conf.vlan10.forwarding=1')
                    ping()
                    # Use an external policy table to prove the observation
                    # follows the real RPDB, not the declared topology/routes.
                    manager.ns(1, 'ip', 'route', 'add', 'blackhole', '203.0.113.0/24', 'table', '100')
                    manager.ns(1, 'ip', 'rule', 'add', 'priority', '100', 'to', '203.0.113.0/24', 'lookup', '100')
                    report = lookup(manager, 'SW1', '203.0.113.10')
                    self.assertEqual(report['lookup']['status'], 'command_failed')
                    self.assertIsNone(report['selected'])
                    self.assertTrue(any(row.get('priority') == 100 and str(row.get('table')) == '100'
                                        for row in report['rules']['records']))
                    ping(False)
                    manager.ns(1, 'ip', 'rule', 'del', 'priority', '100', 'to', '203.0.113.0/24', 'lookup', '100')
                    manager.ns(1, 'ip', 'route', 'del', 'blackhole', '203.0.113.0/24', 'table', '100')
                    ping()
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
                    self.assertEqual(prefix(query()), '203.0.113.0/24')
                    ping()
                    manager.configure_ios('SW1', 'conf t\ninterface vlan10\nshutdown\nend')
                    self.assertIn('INGRESS_ADMIN_DOWN', {row['code'] for row in query()['findings']})
                    ping(False)
                    manager.configure_ios('SW1', 'conf t\ninterface vlan10\nno shutdown\nend')
                    ping()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(run(['ip', '-j', '-4', 'rule', 'show']).stdout, rules)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward', 'net.ipv4.conf.all.rp_filter']).stdout, host_settings)

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
        links = host_links()
        host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = svi_lab(rootfs)
            spec['name'] = 'svi-test-' + str(os.getpid())
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
                    future.result(timeout=5)
                    self.fail('SVI/trunk capture did not become ready')
                with manager.locked():
                    ping('PC2', '198.51.100.20')
                result = future.result(timeout=8)
                self.assertEqual(result['captured_packets'], count)
                return run(['tcpdump', '-n', '-e', '-vv', '-r', Path(folder) / filename]).stdout
            try:
                with manager.locked():
                    manager.start(spec)
                    ping('PC1', '192.0.2.20')
                    ping('PC3', '198.51.100.20')
                    ping('PC1', '192.0.2.1')
                    ping('PC3', '198.51.100.1')
                    ping('PC1', '198.51.100.10', success=False)
                    # A gateway in another VLAN must not answer ARP on VLAN10.
                    arp = manager.crun('exec', 'PC1', '/bin/busybox', 'arping', '-I', 'eth0', '-c', '1', '-w', '1', '198.51.100.1',
                                       check=False)
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
                self.assertIn('vlan 10', decoded)
                self.assertIn('vlan 20', decoded)
                self.assertIn('ttl 63', decoded)
                self.assertIn('ICMP', captured('vlan10', 'svi-interface.pcap', 'icmp', 2))
                with manager.locked():
                    manager.configure_ios('SW1', 'conf t\nno ip routing\nend')
                    ping('PC1', '198.51.100.10', success=False)
                    ping('PC1', '192.0.2.20')
                    ping('PC3', '198.51.100.20')
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
                    original_ns = manager.ns
                    armed = [True]
                    def interrupted(index, *args, **kwargs):
                        if armed[0] and args[:2] == ('sysctl', '-w') and any('.arp_ignore=' in str(arg) for arg in args):
                            armed[0] = False
                            raise RuntimeFailure('Injected failure after actual SVI removal')
                        return original_ns(index, *args, **kwargs)
                    revision = manager.state['revision']
                    with patch.object(manager, 'ns', side_effect=interrupted), self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                        manager.configure_ios('SW1', 'conf t\nno interface vlan20\nend')
                    self.assertFalse(armed[0])
                    self.assertEqual(manager.state['phase'], 'running')
                    self.assertEqual(manager.state['revision'], revision)
                    wait_routed()
                    manager.configure_ios('SW1', 'conf t\nno interface vlan 20\nend')
                    self.assertNotIn('vlan20', {r['ifname'] for r in manager.inspect('SW1')['links']})
                    ping('PC1', '198.51.100.10', success=False)
                    ping('PC3', '198.51.100.20')
                    manager.configure_ios('SW1', 'conf t\ninterface vlan20\nip address 198.51.100.1 255.255.255.0\nno shutdown\nend')
                    wait_routed()
                    manager.configure_ios('SW1', 'conf t\ninterface vlan20\nshutdown\nend')
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    self.assertNotIn('UP', manager.inspect('SW1')['svis']['vlan20']['flags'])
                    ping('PC1', '198.51.100.10', success=False)
                    ping('PC3', '198.51.100.20')
                    manager.configure_ios('SW1', 'conf t\ninterface vlan20\nno shutdown\nend')
                    wait_routed()
                    manager.write_startup()
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
        self.assertEqual(run(['sysctl', '-n', 'net.ipv4.ip_forward', 'net.ipv4.conf.all.arp_ignore',
                              'net.ipv4.conf.all.arp_announce']).stdout, host_sysctl)

    def test_enterprise_twenty_nodes_benchmark_and_real_return_routes(self):
        from network_labs.appliances.benchmark import benchmark, wait_ready
        from network_labs.appliances.examples import enterprise
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        before = fingerprint(json.loads(run(['nft', '-j', '-n', 'list', 'ruleset']).stdout))
        routes = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = enterprise(rootfs)
            spec['name'] = 'enterprise-test-' + str(os.getpid())
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
                return manager.crun('exec', node, '/bin/busybox', 'wget', '-T', '1', '-q', '-O', '-', 'http://' + address + '/',
                                    check=False)
            with manager.locked():
                try:
                    manager.start(spec)
                    wait_ready(manager)
                    self.assertEqual(len(manager.status()['nodes']), 20)
                    for node in ('WAN1', 'DHCP1'):
                        manager.crun('exec', node, '/bin/sh', '-c',
                                     'mkdir -p /tmp/www; echo ' + node + ' > /tmp/www/index.html; /bin/busybox httpd -p 80 -h /tmp/www')
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
                    manager.ns(firewall_index, 'ip', '-4', 'route', 'add', '10.10.10.0/24', 'via', '172.31.255.2', 'dev', 'eth0', 'proto',
                               'static')
                    self.assertTrue(ping('PC1'))
                    manager.write_startup()
                    manager.stop()
                    manager.start(load_startup(spec['name']))
                    wait_ready(manager)
                    self.assertTrue(ping('PC1'))
                    self.assertTrue(ping('PC12'))
                finally:
                    if manager.directory.exists():
                        manager.stop()
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', '-n', 'list', 'ruleset']).stdout)), before)
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)


if __name__ == '__main__':
    unittest.main()
