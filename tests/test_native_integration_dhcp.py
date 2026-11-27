"""Opt-in real OCI boot/packet tests. DHCP on real containers: the relay, several pools per VLAN, reservations, the
endpoints checked.

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

from test_native_integration import NATIVE, RealContainerCase


@unittest.skipUnless(NATIVE, 'Opt-in privileged native test')
class DHCPTests(RealContainerCase):
    def test_appliance_ab_dhcp_relay_real_dora_renew_loss_drift_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import dhcp_relay_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.dhcp_relay import start_servers
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', dnsmasq=shutil.which('dnsmasq'))
            spec = dhcp_relay_lab(rootfs)
            spec['name'] = 'relay-test-' + str(os.getpid())
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
                event = threading.Event()
                path = Path(folder) / filename
                future = pool.submit(capture, Manager(spec['name']), node, interface, path,
                                     seconds=4, packets=100, expression='udp and (port 67 or port 68)', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5)
                    self.fail('DHCP capture not ready')
                with manager.locked():
                    action()
                result = future.result(timeout=8)
                self.assertGreater(result['captured_packets'], 0)
                return run(['tcpdump', '-nn', '-vvv', '-r', str(path)]).stdout
            try:
                with manager.locked():
                    manager.start(spec)
                    ready()
                    manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10')
                    self.assertTrue(manager.inspect('SW1')['dhcp_relay']['configuration_verified'])
                    release()
                dora = packets('dora.pcap', 'DHCP1', 'eth0', lambda: signal_client('USR1'))
                for message in ('Discover', 'Offer', 'Request', 'ACK', 'Gateway-IP 192.0.2.1'):
                    self.assertIn(message, dora)
                with manager.locked():
                    ready()
                renew = packets('renew.pcap', 'DHCP1', 'eth0', lambda: signal_client('USR1'))
                self.assertIn('Request', renew)
                self.assertIn('ACK', renew)
                with manager.locked():
                    ready()
                    manager.crun('exec', 'SW1', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/dhcp-relay.pid)"')
                    wait_for(lambda: manager.inspect('SW1')['dhcp_relay']['listener_snapshot'] == [], 'relay stopped')
                    self.assertTrue(manager.inspect('SW1')['dhcp_relay']['configuration_verified'])
                    manager.crun('exec', 'PC2', '/bin/ping', '-c', '1', '-W', '1', '198.51.100.10')
                    release()
                outage = packets('outage.pcap', 'PC1', 'eth0', lambda: signal_client('USR1'))
                self.assertIn('Discover', outage)
                self.assertNotIn('Offer', outage)
                self.assertNotIn('ACK', outage)
                with manager.locked():
                    self.assertEqual(addresses(0), [])
                    start_servers(manager)
                    ready()
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
                self.assertIn('Discover', no_helper)
                self.assertNotIn('Offer', no_helper)
                with manager.locked():
                    self.assertEqual(addresses(0), [])
                    helper()
                    ready()
                    self.assertEqual(link_ids(), before_links)
                    self.assertEqual({n['name']: json.loads(manager.crun('state', n['name']).stdout)['pid'] for n in spec['nodes']},
                                     initial_pids)
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
                    release()
                    signal_client('USR1')
                    ready()
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
                    release()
                    signal_client('USR1')
                    ready()
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
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    ready()
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
        baseline_links = links()
        baseline_routes = run(['ip', '-j', 'route', 'show']).stdout
        baseline_nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        baseline_forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', dnsmasq=shutil.which('dnsmasq'))
            spec = dhcp_multi_lab(rootfs)
            spec['name'] = 'pools-test-' + str(os.getpid())
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
                signal(index, 'USR2')
                wait(lambda: not addresses(index), 'DHCP release')
            def ready(index):
                wait(lambda: bool(addresses(index)), 'DHCP pool acquisition')
                address = addresses(index)[0]
                prefix = ('192.0.2.', '198.18.0.')[index]
                self.assertEqual(address['prefixlen'], 24)
                self.assertTrue(ipaddress.IPv4Address(prefix + '100') <= ipaddress.IPv4Address(address['local'])
                                <= ipaddress.IPv4Address(prefix + '110'))
                if index == 0:
                    self.assertEqual(address['local'], '192.0.2.100')
                default = json.loads(manager.ns(index, 'ip', '-j', 'route', 'show', 'default').stdout)
                self.assertTrue(any(row.get('gateway') == prefix + '1' for row in default))
                resolver = manager.crun('exec', 'PC' + str(index + 1), '/bin/cat', '/etc/resolv.conf').stdout
                self.assertEqual(resolver, 'nameserver ' + prefix + '53\n')
            def recorded(filename, node, action):
                event = threading.Event()
                path = Path(folder) / filename
                future = pool.submit(capture, Manager(spec['name']), node, 'eth0', path,
                                     seconds=4, packets=100, expression='udp and (port 67 or port 68)', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5)
                    self.fail('DHCP capture not ready')
                with manager.locked():
                    action()
                result = future.result(timeout=8)
                return result['captured_packets'], run(['tcpdump', '-nn', '-vvv', '-r', str(path)]).stdout
            def helper(remove=False):
                manager.configure_ios('SW1',
                                      'conf t\ninterface vlan10\n' + ('no ' if remove else '') + 'ip helper-address 198.51.100.10\nend')
            try:
                with manager.locked():
                    manager.start(spec)
                    ready(0)
                    ready(1)
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
                    ready(0)
                    ready(1)
                    helper(True)
                    release(0)
                count, packets = recorded('removed.pcap', 'PC1', lambda: signal(0, 'USR1'))
                self.assertGreater(count, 0)
                self.assertIn('Discover', packets)
                self.assertNotIn('Offer', packets)
                self.assertNotIn('ACK', packets)
                with manager.locked():
                    self.assertEqual(addresses(0), [])
                    release(1)
                    signal(1, 'USR1')
                    ready(1)
                    self.assertEqual(addresses(0), [])
                    helper()
                    ready(0)
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
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    ready(0)
                    ready(1)
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

    def test_appliance_aa_verify_real_dhcp_endpoints_pcap_loss_blocked_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import copy
        from network_labs.appliances.examples import ospf_dhcp_multi_lab
        from network_labs.appliances.verify import verify, render
        from network_labs.appliances.capture import capture
        from network_labs.appliances.firewall import fingerprint
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        rules = run(['ip', '-j', 'rule', 'show']).stdout
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        forwarding = run(['sysctl', '-n', 'net.ipv4.ip_forward']).stdout
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                bird=shutil.which('bird'), birdc=shutil.which('birdc'), dnsmasq=shutil.which('dnsmasq'))
            spec = ospf_dhcp_multi_lab(rootfs)
            spec['name'] = 'verify-' + str(os.getpid())
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
                    wait(lambda: manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '203.0.113.10',
                                              check=False).returncode == 0,
                         'actual route convergence and ARP warmup')
                event = threading.Event()
                path = Path(folder) / 'verify.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', path,
                    seconds=5, packets=100, expression='icmp', ready=event.set)
                if not event.wait(5):
                    future.result(timeout=5)
                    self.fail('Verification capture not ready')
                with manager.locked():
                    report = check(bidirectional=True)
                    self.assertEqual(report['status'], 'passed')
                    self.assertEqual(report['probe_commands_attempted'], 2)
                    self.assertEqual(report['directions'][1]['destination_address'], '192.0.2.100')
                    for direction in report['directions']:
                        self.assertEqual((direction['transmitted'], direction['received']), (2, 2))
                        self.assertEqual(direction['reply_ttls'], [62, 62])
                    self.assertIn('RÉUSSI', render(report))
                self.assertGreater(future.result(timeout=8)['captured_packets'], 0)
                text = run(['tcpdump', '-nn', '-r', str(path)]).stdout
                self.assertIn('ICMP echo request', text)
                self.assertIn('ICMP echo reply', text)
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
                    self.assertEqual(report['status'], 'blocked', json.dumps(report))
                    self.assertEqual(report['probe_commands_attempted'], 0)
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
                    signal('USR2')
                    wait(lambda: not address(), 'released DHCP address')
                    report = check()
                    self.assertEqual(report['status'], 'blocked', json.dumps(report))
                    self.assertEqual(report['probe_commands_attempted'], 0)
                    self.assertIn('NO_USABLE_IPV4', report['endpoints'][0]['reasons'])
                    manager.configure_ios('SW1', 'conf t\ninterface vlan10\nip helper-address 198.18.0.3\nend')
                    signal('USR1')
                    wait(lambda: address() == ['192.0.2.100'], 'DHCP reacquisition')
                    wait(lambda: manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '203.0.113.10',
                                              check=False).returncode == 0,
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

    def test_dhcp_reservations_real_pool_exclusion_renewal_file_drift_and_restore(self):
        import copy
        from network_labs.appliances.examples import dhcp_reservations_lab
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = dhcp_reservations_lab(rootfs)
            spec['name'] = 'res-test-' + str(os.getpid())
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
                    expected = {n['name']: n['interface_macs']['eth0'] for n in manager.state['spec']['nodes'] if n['name'] in ('PRN1',
                            'PC1', 'PC2')}
                    if installed.get('PRN1') == reserved and len(installed) == 3 and all(bindings.get(expected[name]) == ip for name,
                                                                                         ip in installed.items()):
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
                    manager.crun('exec', 'PRN1', '/bin/sh', '-c',
                            '/bin/kill -USR2 "$(/bin/cat /run/udhcpc.pid)"; /bin/busybox sleep 0.2; /bin/kill -USR1 "$(/bin/cat '
                        '/run/udhcpc.pid)"')
                    wait_ack(acknowledgments)
                    self.assertEqual(wait_clients()['PRN1'], '10.10.0.100')
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    config = manager.directory / 'DHCP1' / 'files' / 'udhcpd.conf'
                    original = config.read_text()
                    config.write_text(original + '# host-side unmanaged change\n')
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


if __name__ == '__main__':
    unittest.main()
