"""Opt-in real OCI boot/packet test. Run on a disposable Linux host with sudo.

NETWORK_LABS_NATIVE_TESTS=1 requires crun, iproute2 and busybox-static. These
tests are deliberately never replaced with mocks when explicitly requested.
"""
import os
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
            def ping(source, target):
                return manager.crun('exec', source, '/bin/ping', '-c', '1', '-W', '1', target, check=False).returncode == 0
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
                    if manager.directory.exists():
                        manager.stop()
            self.assertFalse(manager.directory.exists())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, before)

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
