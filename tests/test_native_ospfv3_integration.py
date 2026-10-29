"""Real OSPFv3 adjacency, kernel delivery, withdrawal and saved restart."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.examples import ospfv3_lab
from network_labs.appliances.ospf import start_one, stop_one
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.show import show
from network_labs.appliances.verify import verify


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeOSPFv3Tests(unittest.TestCase):
    def test_real_adjacency_delivery_withdrawal_drift_and_saved_restart(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('bird', 'birdc', 'busybox', 'crun', 'ip'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        host_routes = run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout
        host_rules = run(['ip', '-j', '-6', 'rule', 'show']).stdout
        host_forwarding = run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout
        host_links = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        with tempfile.TemporaryDirectory() as folder, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder)
            rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs',
                                         bird=shutil.which('bird'), birdc=shutil.which('birdc'))
            spec = ospfv3_lab(rootfs); spec['name'] = 'ospfv3-' + str(os.getpid())
            manager = Manager(spec['name'])
            def wait(predicate, label):
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if predicate(): return
                    time.sleep(.2)
                self.fail(label + ': ' + repr({name: manager.inspect(name) for name in ('R1', 'R2')}))
            def remote_routes(name='R1'):
                prefix = '2001:db8:20::/64' if name == 'R1' else '2001:db8:10::/64'
                return [r for r in manager.inspect(name)['routes_ipv6'] if r.get('dst') == prefix]
            def healthy():
                for name in ('R1', 'R2'):
                    wait(lambda: 'Full' in (manager.inspect(name)['ospfv3']['neighbors'] or ''), 'OSPFv3 adjacency')
                    # A Full adjacency or one router's FIB does not establish
                    # the return path after the peer daemon has restarted.
                    wait(lambda: bool(remote_routes(name)), name + ' OSPFv3 kernel route not installed')
                    for query in ('show ipv6 ospf neighbor', 'show ipv6 ospf interface', 'show ipv6 ospf', 'show ipv6 route ospf'):
                        report = show(manager, name, query)
                        self.assertEqual(report['status'], 'observed', report)
                    learned = remote_routes(name)[0]
                    self.assertIn(learned.get('protocol'), ('bird', 192, '192'))
                    self.assertTrue(learned.get('gateway', '').startswith('fe80:'), learned)
                report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2, bidirectional=True)
                self.assertEqual(report['status'], 'passed', report)
            try:
                with manager.locked(): manager.start(spec)
                healthy()
                router = spec['nodes'][2]
                stop_one(manager, router)
                wait(lambda: not remote_routes(), 'Dead neighbor route not withdrawn')
                failed = manager.crun('exec', 'PC1', '/bin/busybox', 'ping6', '-c', '1', '-W', '1', '-w', '2',
                                      '2001:db8:20::20', check=False, timeout=4)
                self.assertNotEqual(failed.returncode, 0)
                start_one(manager, router); healthy()
                # A manually inserted route must not be saved as OSPF policy.
                manager.ns(1, 'ip', '-6', 'route', 'add', '2001:db8:99::/64', 'via', '2001:db8:100::2', 'dev', 'eth1', 'proto', 'static')
                with manager.locked(), self.assertRaises(RuntimeFailure): manager.write_startup()
                manager.ns(1, 'ip', '-6', 'route', 'del', '2001:db8:99::/64', 'via', '2001:db8:100::2', 'dev', 'eth1')
                with manager.locked():
                    manager.write_startup(); saved = load_startup(spec['name'])
                    self.assertEqual(saved, spec)
                    self.assertTrue(all(not n['ipv6_routes'] for n in saved['nodes'][1:3]))
                    manager.stop(); manager.start(saved)
                healthy()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        self.assertEqual(run(['ip', '-j', '-6', 'route', 'show', 'table', 'all']).stdout, host_routes)
        self.assertEqual(run(['ip', '-j', '-6', 'rule', 'show']).stdout, host_rules)
        self.assertEqual(run(['sysctl', '-n', 'net.ipv6.conf.all.forwarding']).stdout, host_forwarding)
        self.assertEqual({(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}, host_links)
