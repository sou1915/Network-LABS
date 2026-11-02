"""Native manifest, lifecycle failure handling and honest backend boundaries."""
import copy
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from network_labs.appliances.__main__ import main
from network_labs.appliances.catalog import capabilities
from network_labs.appliances.runtime import Manager, RuntimeFailure, firecracker_config, oci_config, plan, static_busybox_rootfs
from network_labs.appliances.spec import MIB, example, namespace, validate


class ManifestTests(unittest.TestCase):
    def test_plan_is_read_only_and_accounts_for_reserve(self):
        data = example('/missing/rootfs'); original = copy.deepcopy(data)
        with patch('subprocess.run', side_effect=AssertionError('host command')):
            result = plan(data)
        self.assertEqual(data, original)
        self.assertEqual(result['allocated_node_mib'], 192)
        self.assertEqual(result['reserve_mib'], 512)
        self.assertTrue(all(n['exec'] for n in result['nodes']))

    def test_reject_unknown_runtime_budget_typos_and_bad_links(self):
        changes = [lambda s: s['nodes'][0].update(runtime='libkrun'),
                   lambda s: s.update(budget_mib=512),
                   lambda s: s['nodes'][0].update(memroy_mib=32),
                   lambda s: s['links'].append(s['links'][0]),
                   lambda s: s['links'][0][0].__setitem__(1, 'eth90'),
                   lambda s: s['nodes'][0].update(command='echo unsafe'),
                   lambda s: s['nodes'][0].update(rootfs='/'),
                   lambda s: s['nodes'][0].update(name='../escape'),
                   lambda s: s['nodes'][0].update(interfaces={'eth0': 0}),
                   lambda s: s['nodes'][0].update(gateway='203.0.113.1'),
                   lambda s: s['nodes'][0].update(role='firewall'),
                   lambda s: s['nodes'][1].update(interfaces={'eth0': '192.0.2.1/24', 'eth1': ''})]
        for change in changes:
            with self.subTest(change=change):
                data = example('/missing/rootfs'); change(data)
                with self.assertRaises(ValueError):
                    validate(data)

    def test_switch_cycle_rejected_before_host_changes(self):
        spec = example('/rootfs'); spec['nodes'][1]['interfaces'].update(eth2='', eth3='')
        sw2 = copy.deepcopy(spec['nodes'][1]); sw2['name'] = 'SW2'; spec['nodes'].append(sw2)
        spec['links'].extend([[['SW1', 'eth2'], ['SW2', 'eth0']], [['SW1', 'eth3'], ['SW2', 'eth1']]])
        with self.assertRaisesRegex(ValueError, 'loop'):
            validate(spec)

    def test_vm_is_distinct_and_does_not_claim_exec_or_readiness(self):
        spec = example('/rootfs')
        node = {'name': 'VM1', 'runtime': 'firecracker', 'kernel': '/assets/vmlinux',
                'disk': '/assets/root.ext4', 'interfaces': {'eth0': '192.0.2.30/24'}, 'gateway': '192.0.2.1'}
        spec['nodes'].append(node)
        spec = validate(spec)
        self.assertFalse(plan(spec)['nodes'][-1]['exec'])
        config = firecracker_config(spec['nodes'][-1], Path('/assets/vmlinux'), Path('/private/root.ext4'))
        self.assertEqual(config['network-interfaces'][0]['host_dev_name'], 'tap0')
        self.assertIn('ip=192.0.2.30::192.0.2.1:255.255.255.0:VM1:eth0:off', config['boot-source']['boot_args'])
        self.assertEqual(config['drives'][0]['path_on_host'], '/private/root.ext4')
        spec['nodes'][-1]['interfaces']['eth1'] = ''
        with self.assertRaisesRegex(ValueError, 'one static'):
            validate(spec)

    def test_oci_spec_isolates_namespaces_and_limits_resources(self):
        spec = example('/rootfs'); node = spec['nodes'][0]
        config = oci_config(spec, node, 0, Path('/private/PC1/rootfs'))
        ns = {n['type']: n.get('path') for n in config['linux']['namespaces']}
        self.assertEqual(ns['network'], '/run/netns/' + namespace(spec, 0))
        self.assertEqual(set(ns), {'network', 'pid', 'mount', 'uts', 'ipc', 'cgroup'})
        self.assertEqual(config['linux']['resources']['memory']['limit'], 64 * MIB)
        self.assertEqual(config['linux']['resources']['pids']['limit'], 128)
        self.assertNotIn('CAP_SYS_ADMIN', config['process']['capabilities']['effective'])
        self.assertFalse(any(m.get('source') in ('/', '/home', '/var/run/docker.sock') for m in config['mounts']))

    def test_research_technologies_never_report_implemented(self):
        report = capabilities()
        for runtime in report['runtimes']:
            if runtime['id'] in ('libkrun', 'unikraft', 'wasi-0.3', 'netkit-ebpf', 'hyperlight-nanvix'):
                self.assertEqual(runtime['implementation'], 'research')
                self.assertFalse(runtime['prerequisites_detected'])

    def test_cli_example_and_plan_need_no_display_or_privileges(self):
        with io.StringIO() as output, patch('sys.stdout', output):
            self.assertEqual(main(['example', '--rootfs', '/tmp/rootfs']), 0)
            spec = json.loads(output.getvalue())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lab.json'; path.write_text(json.dumps(spec))
            with patch('os.geteuid', return_value=1000), patch('subprocess.run', side_effect=AssertionError('host command')), patch('sys.stdout', io.StringIO()):
                self.assertEqual(main(['plan', str(path)]), 0)

    def test_busybox_rootfs_rejects_dynamic_elf_without_running_it(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'busybox'; target = Path(folder) / 'rootfs'
            elf = bytearray(128); elf[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<Q', elf, 32, 64); struct.pack_into('<HH', elf, 54, 56, 1)
            struct.pack_into('<I', elf, 64, 3); binary.write_bytes(elf)
            with self.assertRaisesRegex(ValueError, 'dynamically linked'):
                static_busybox_rootfs(binary, target)
            self.assertFalse(target.exists())
            struct.pack_into('<I', elf, 64, 1); binary.write_bytes(elf)
            with patch('subprocess.run', side_effect=AssertionError('executed ELF')):
                self.assertEqual(static_busybox_rootfs(binary, target), target)
            self.assertEqual((target / 'bin/sh').readlink(), Path('busybox'))


class LifecycleTests(unittest.TestCase):
    def test_startup_failure_rolls_back_only_owned_resources(self):
        calls, namespaces = [], set()
        def fake_run(args, **options):
            args = [str(a) for a in args]; calls.append(args)
            if args[:3] == ['ip', 'netns', 'list']:
                return subprocess.CompletedProcess(args, 0, 'unrelated\n' + '\n'.join(namespaces), '')
            if args[:3] == ['ip', 'netns', 'add']:
                namespaces.add(args[3])
            if args[:3] == ['ip', 'netns', 'delete']:
                namespaces.discard(args[3])
            if args[:3] == ['ip', 'link', 'show']:
                return subprocess.CompletedProcess(args, 1, '', 'not found')
            if args[0] == 'crun' and 'run' in args:
                raise RuntimeFailure('injected boot failure')
            return subprocess.CompletedProcess(args, 0, '', '')
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / 'state'; base.mkdir()
            rootfs = Path(folder) / 'rootfs'; rootfs.mkdir()
            spec = example(rootfs)
            with patch('network_labs.appliances.runtime.STATE_ROOT', base), \
                 patch('network_labs.appliances.runtime.run', side_effect=fake_run), \
                 patch.object(Manager, 'preflight'), patch('os.geteuid', return_value=0):
                manager = Manager(spec['name'])
                with self.assertRaisesRegex(RuntimeFailure, 'injected'):
                    manager.start(spec)
                self.assertFalse((base / spec['name']).exists())
        self.assertFalse(namespaces)
        self.assertFalse(any('unrelated' in command for command in calls))
        self.assertTrue(any(command[0] == 'crun' and 'delete' in command for command in calls))

    def test_unprivileged_lifecycle_is_rejected_before_host_changes(self):
        with patch('os.geteuid', return_value=1000), patch('pathlib.Path.mkdir', side_effect=AssertionError('host change')):
            with self.assertRaisesRegex(RuntimeFailure, 'requires sudo'):
                with Manager('test').locked():
                    self.fail('unprivileged lock acquired')

    def test_exec_keeps_argv_boundaries_and_rejects_vm(self):
        manager = Manager('test')
        manager.state = {'phase': 'running', 'spec': {'nodes': [{'name': 'PC1', 'runtime': 'oci'}, {'name': 'VM1', 'runtime': 'firecracker'}]}}
        with patch('subprocess.call', return_value=0) as call:
            self.assertEqual(manager.execute('PC1', ['/bin/echo', '$(do-not-run); test']), 0)
            self.assertEqual(call.call_args.args[0][-1], '$(do-not-run); test')
            with self.assertRaisesRegex(RuntimeFailure, 'guest agent'):
                manager.execute('VM1', ['/bin/sh'])
            self.assertEqual(call.call_count, 1)

    def test_stop_does_not_signal_reused_vm_pid(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Manager('test'); manager.directory = Path(folder) / 'test'; manager.directory.mkdir()
            manager.state = {'spec': {}, 'vms': [{'name': 'VM1', 'pid': 123, 'starttime': 'old'}],
                             'containers': [], 'namespaces': [], 'host_links': [], 'mounts': []}
            with patch('network_labs.appliances.runtime.process_identity', return_value='new'), patch('os.kill') as kill:
                manager.stop()
                kill.assert_not_called()


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class NativeGUITests(unittest.TestCase):
    def test_workbench_can_validate_without_native_dependencies(self):
        import tkinter as tk
        from network_labs.__main__ import App
        root = tk.Tk(); app = App(root); errors = []
        root.report_callback_exception = lambda *e: errors.append(str(e))
        try:
            with patch('subprocess.Popen', side_effect=AssertionError('unexpected launch')):
                window = app.open_native_lab(); root.update()
                self.assertEqual(len(window.table.get_children()), 8)
                self.assertTrue(window.preview()); root.update()
                self.assertIn('allocated_node_mib', window.output.get('1.0', 'end'))
                self.assertIs(app.open_native_lab(), window)
                self.assertEqual(app.lab.execution_backend, 'model')
        finally:
            app.pause(); root.destroy()
        self.assertEqual(errors, [])
