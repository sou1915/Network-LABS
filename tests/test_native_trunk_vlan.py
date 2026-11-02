"""Opt-in real trunk VLAN edits, wire tags, rollback and saved restart."""
from concurrent.futures import ThreadPoolExecutor
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
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.spec import validate


def trunk_spec(rootfs, bundled):
    nodes = [{'name': name, 'runtime': 'oci', 'rootfs': str(rootfs), 'interfaces': {'eth0': address}}
             for name, address in (('PC1', '192.0.2.10/24'), ('PC2', '198.18.0.10/24'),
                                   ('PC3', '192.0.2.20/24'), ('PC4', '198.18.0.20/24'))]
    for name in ('SW1', 'SW2'):
        trunk = 'bond1' if bundled else 'eth2'
        nodes.append({'name': name, 'runtime': 'oci', 'role': 'switch', 'rootfs': str(rootfs),
                      'dialect': 'ios-basic', 'interfaces': {'eth' + str(i): '' for i in range(4 if bundled else 3)},
                      'vlans': [1, 10, 20], 'port_channels': {'bond1': {'members': ['eth2', 'eth3'], 'mode': 'active'}} if bundled else {},
                      'switchports': {'eth0': {'mode': 'access', 'vlan': 10}, 'eth1': {'mode': 'access', 'vlan': 20},
                                      trunk: {'mode': 'trunk', 'native_vlan': 1, 'allowed': 'all'}}})
    links = [[['PC1', 'eth0'], ['SW1', 'eth0']], [['PC2', 'eth0'], ['SW1', 'eth1']],
             [['PC3', 'eth0'], ['SW2', 'eth0']], [['PC4', 'eth0'], ['SW2', 'eth1']],
             [['SW1', 'eth2'], ['SW2', 'eth2']]]
    if bundled: links.append([['SW1', 'eth3'], ['SW2', 'eth3']])
    return validate({'version': 2, 'name': 'vlan-edit-' + str(os.getpid()) + ('-bond' if bundled else '-plain'),
                     'nodes': nodes, 'links': links})


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeTrunkVLANTests(unittest.TestCase):
    def test_vlan_activation_tags_native_filtering_rollback_and_restart(self):
        self.assertEqual(os.geteuid(), 0, 'Run explicit native test with sudo')
        for tool in ('busybox', 'crun', 'ip', 'bridge', 'tcpdump'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        host_routes = run(['ip', '-j', 'route', 'show']).stdout
        for bundled in (False, True):
            with self.subTest(bundled=bundled), tempfile.TemporaryDirectory() as folder, \
                 patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'), \
                 ThreadPoolExecutor(max_workers=1) as pool:
                rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
                spec = trunk_spec(rootfs, bundled); manager = Manager(spec['name'])
                trunk = 'bond1' if bundled else 'eth2'
                cli_trunk = 'port-channel1' if bundled else 'eth2'
                def apply(name, text):
                    return manager.configure_ios(name, 'conf t\n' + text + '\nend')
                def ping(source, address, expected=True):
                    result = manager.crun('exec', source, '/bin/ping', '-c', '1', '-W', '1', address, check=False)
                    self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)
                def wait_pairs():
                    stable = 0
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        results = [manager.crun('exec', source, '/bin/ping', '-c', '1', '-W', '1', target, check=False)
                                   for source, target in (('PC1', '192.0.2.20'), ('PC2', '198.18.0.20'))]
                        # One successful packet can precede the final LACP
                        # aggregator selection. Require both members on both
                        # peers plus repeated packet success before capture.
                        negotiated = True
                        if bundled:
                            reports = [manager.inspect(name)['port_channels']['bond1'] for name in ('SW1', 'SW2')]
                            negotiated = all(report['ready'] and len(report['negotiated_members']) == 2 for report in reports)
                        stable = stable + 1 if negotiated and all(result.returncode == 0 for result in results) else 0
                        if stable >= 2: return
                        time.sleep(.2)
                    self.fail('VLAN packet path did not recover: ' + repr(results))
                def wire(filename, expression):
                    ready = threading.Event(); path = Path(folder) / filename
                    future = pool.submit(capture, Manager(spec['name']), 'SW1', trunk, path,
                                         seconds=5, packets=2, expression=expression, ready=ready.set)
                    if not ready.wait(5):
                        future.result(timeout=3); self.fail('Trunk capture did not become ready')
                    with manager.locked(): ping('PC2', '198.18.0.20')
                    self.assertEqual(future.result(timeout=8)['captured_packets'], 2)
                    return run(['tcpdump', '-n', '-e', '-r', path]).stdout
                def table(name):
                    index = next(i for i, node in enumerate(spec['nodes']) if node['name'] == name)
                    return json.loads(manager.ns(index, 'bridge', '-j', 'vlan', 'show', 'dev', trunk).stdout)
                try:
                    with manager.locked():
                        manager.start(spec); wait_pairs()
                        # Reserve VLAN30 in one unchanged explicit allowed list;
                        # the other trunk uses all active VLANs.
                        apply('SW2', 'interface ' + cli_trunk + '\nswitchport trunk allowed vlan 10,20,30')
                        original_ns = manager.ns; injected = []
                        def fail_activation(index, *args, **kwargs):
                            if not injected and args[:3] == ('bridge', 'vlan', 'add') and '30' in args:
                                injected.append(True); raise RuntimeFailure('Injected VLAN activation failure')
                            return original_ns(index, *args, **kwargs)
                        with patch.object(manager, 'ns', side_effect=fail_activation):
                            with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                                apply('SW1', 'vlan 30')
                        self.assertTrue(injected)
                        self.assertNotIn(30, next(n for n in manager.read()['spec']['nodes'] if n['name'] == 'SW1')['vlans'])
                        self.assertFalse(any(v['vlan'] == 30 for row in table('SW1') for v in row['vlans']))
                        wait_pairs()
                        for name in ('SW1', 'SW2'):
                            apply(name, 'vlan 30')
                            self.assertTrue(any(v['vlan'] == 30 for row in table(name) for v in row['vlans']))
                            apply(name, 'interface eth1\nswitchport access vlan 30')
                        wait_pairs()
                        arp = manager.crun('exec', 'PC1', '/bin/busybox', 'arping', '-I', 'eth0', '-c', '1', '-w', '1',
                                           '198.18.0.20', check=False)
                        self.assertNotEqual(arp.returncode, 0)
                        self.assertIn('Received 0 response', arp.stdout)
                    self.assertIn('vlan 30', wire('tagged.pcap', 'vlan 30 and icmp'))
                    with manager.locked():
                        for name in ('SW1', 'SW2'):
                            apply(name, 'interface ' + cli_trunk + '\nswitchport trunk native vlan 30')
                        wait_pairs()
                    self.assertNotIn('vlan 30', wire('native.pcap', 'icmp and host 198.18.0.20'))
                    with manager.locked():
                        # Prune the native VLAN too: untagged ingress must no
                        # longer gain admission, while VLAN10 still forwards.
                        apply('SW1', 'interface ' + cli_trunk + '\nswitchport trunk allowed vlan 10,20')
                        ping('PC2', '198.18.0.20', expected=False); ping('PC1', '192.0.2.20')
                        apply('SW1', 'interface ' + cli_trunk + '\nswitchport trunk allowed vlan none')
                        ping('PC1', '192.0.2.20', expected=False)
                        apply('SW1', 'interface ' + cli_trunk + '\nswitchport trunk allowed vlan all')
                        wait_pairs(); manager.write_startup(); manager.stop()
                        manager.start(load_startup(spec['name'])); wait_pairs()
                        self.assertTrue(any(v['vlan'] == 30 and 'PVID' in v.get('flags', [])
                                            and 'Egress Untagged' in v.get('flags', [])
                                            for row in table('SW1') for v in row['vlans']))
                finally:
                    with manager.locked(): manager.stop()
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, host_routes)
