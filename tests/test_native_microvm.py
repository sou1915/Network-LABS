"""Opt-in KVM acceptance: real guests, vsock, bidirectional packets and cleanup.

Explicit selection fails on missing prerequisites; it never substitutes mocks.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.guest_control import request
from network_labs.appliances.guest_image import build
from network_labs.appliances.microvm import example
from network_labs.appliances.runtime import Manager, process_identity
from network_labs.appliances.spec import namespace


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class RealMicroVMTests(unittest.TestCase):
    def test_two_guests_packets_link_loss_restore_and_cleanup(self):
        self.assertEqual(os.geteuid(), 0, 'Run with sudo on a disposable KVM host')
        self.assertTrue(Path('/dev/kvm').exists(), 'Real KVM required; no fallback')
        for tool in ('firecracker', 'ip', 'busybox', 'gcc', 'mke2fs', 'debugfs'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        kernel = Path(os.environ.get('NETWORK_LABS_MICROVM_KERNEL', '/missing-kernel'))
        self.assertTrue(kernel.is_file(), 'Set NETWORK_LABS_MICROVM_KERNEL')
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence'))
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlvm-') as temporary:
            root = Path(temporary)
            report = build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = example(kernel, root / 'base.ext4')
            records = []
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'):
                manager = Manager(spec['name'])
                with manager.locked():
                    try:
                        manager.start(spec)
                        records = manager.state['vms'][:]
                        self.assertEqual(len({r['pid'] for r in records}), 2)
                        sockets = [manager.directory / name / 'guest.vsock' for name in ('VM1', 'VM2')]
                        results = {'image': report, 'nodes': {}, 'probes': []}
                        for index, name in enumerate(('VM1', 'VM2')):
                            deadline = time.monotonic() + 40
                            while True:
                                try:
                                    ready = request(sockets[index], 'ready', timeout=2)
                                    self.assertEqual(ready['exit_code'], 0)
                                    self.assertTrue(json.loads(ready['output'])['agent_ready'])
                                    break
                                except (OSError, ValueError):
                                    if time.monotonic() >= deadline: raise
                                    time.sleep(.2)
                            addresses = request(sockets[index], 'addresses')
                            self.assertEqual(addresses['exit_code'], 0)
                            self.assertIn(f'192.0.2.{10 + index * 10}/24', addresses['output'])
                            config = json.loads((manager.directory / name / 'firecracker.json').read_text())
                            self.assertEqual(config['machine-config'], {'vcpu_count': 1, 'mem_size_mib': 128})
                            self.assertNotEqual((manager.directory / name / 'rootfs.ext4').stat().st_ino,
                                                (root / 'base.ext4').stat().st_ino)
                            results['nodes'][name] = {'ready': ready, 'addresses': addresses, 'configured_resources': config['machine-config']}
                        def probe(index, address, expected):
                            result = request(sockets[index], 'ping', destination=address)
                            results['probes'].append(result)
                            self.assertEqual(result['exit_code'] == 0, expected, result)
                        probe(0, '192.0.2.20', True)
                        probe(1, '192.0.2.10', True)
                        manager.ns(0, 'ip', 'link', 'set', 'eth0', 'down')
                        probe(0, '192.0.2.20', False)
                        manager.ns(0, 'ip', 'link', 'set', 'eth0', 'up')
                        probe(0, '192.0.2.20', True)
                        with (root / 'base.ext4').open('rb') as stream:
                            self.assertEqual(hashlib.file_digest(stream, 'sha256').hexdigest(), report['sha256'])
                        (evidence / 'result.json').write_text(json.dumps(results, indent=2))
                    finally:
                        for name in ('VM1', 'VM2'):
                            console = manager.directory / name / 'console.log'
                            if console.exists(): shutil.copyfile(console, evidence / (name + '.log'))
                        if manager.directory.exists(): manager.stop()
                self.assertFalse(manager.directory.exists())
                for record in records:
                    self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                namespaces = subprocess.run(['ip', 'netns', 'list'], check=True, capture_output=True, text=True).stdout
                for index in range(2): self.assertNotIn(namespace(spec, index), namespaces)
                (evidence / 'cleanup.txt').write_text('VMM processes, owned namespaces and private node bundles removed.\n')
