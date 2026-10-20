"""Opt-in real OCI boot/packet test. Run on a disposable Linux host with sudo.

NETWORK_LABS_NATIVE_TESTS=1 requires crun, iproute2, busybox-static, nftables and conntrack. These
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


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class RealContainerTests(unittest.TestCase):
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
