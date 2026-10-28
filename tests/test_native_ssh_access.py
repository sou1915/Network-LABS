"""Opt-in Dropbear key-auth command policy over real SSH connections."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.examples import management_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.spec import validate


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeSSHAccessTests(unittest.TestCase):
    def test_real_key_auth_fixed_actions_denials_drift_and_saved_restart(self):
        self.assertEqual(os.geteuid(), 0)
        for name in ('dropbear', 'ssh', 'ssh-keygen', 'ssh-keyscan', 'crun', 'busybox'):
            self.assertIsNotNone(shutil.which(name), name + ' required')
        host_routes = run(['ip', '-j', 'route', 'show']).stdout
        with tempfile.TemporaryDirectory() as folder, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder); key = root / 'identity'; wrong = root / 'wrong'
            for path in (key, wrong): run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', path])
            rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs', dropbear=shutil.which('dropbear'))
            spec = management_lab(rootfs, key.with_suffix('.pub').read_text().strip(),
                                  ssh_actions=['identity', 'hostname', 'security-context'])
            spec['name'] = 'ssh-actions-' + str(os.getpid()); manager = Manager(spec['name'])
            known = root / 'known_hosts'
            def trust_host():
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    result = manager.ns(0, 'ssh-keyscan', '-T', '2', '-t', 'ed25519', '192.0.2.20', check=False, timeout=4)
                    if result.returncode == 0 and 'ssh-ed25519' in result.stdout:
                        known.write_text(result.stdout); return
                    time.sleep(.1)
                self.fail('SSH did not become ready')
            def ssh(command=None, identity=key, extra=()):
                return manager.ns(0, 'ssh', '-F', '/dev/null', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                                  '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
                                  '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'ConnectTimeout=3', '-o', 'LogLevel=ERROR',
                                  '-i', str(identity), *extra, 'lab@192.0.2.20',
                                  *([] if command is None else [command]), check=False, timeout=8, input_text='')
            def allowed():
                identity = ssh('identity')
                self.assertEqual(identity.returncode, 0, identity)
                self.assertIn('uid=65532', identity.stdout); self.assertIn('gid=65532', identity.stdout)
                hostname = ssh('hostname')
                self.assertEqual(hostname.returncode, 0, hostname); self.assertEqual(hostname.stdout.strip(), 'R1')
                security = ssh('security-context')
                self.assertEqual(security.returncode, 0, security)
                fields = dict(line.split(':', 1) for line in security.stdout.splitlines() if ':' in line)
                self.assertEqual(fields['NoNewPrivs'].strip(), '1')
                self.assertEqual(int(fields['CapEff'].strip(), 16), 0)
            try:
                with manager.locked():
                    manager.start(spec); trust_host(); allowed()
                    bad_key = ssh('identity', identity=wrong)
                    self.assertNotEqual(bad_key.returncode, 0, bad_key)
                    self.assertNotIn('uid=65532', bad_key.stdout)
                    for command in (None, '/bin/sh', 'identity --help', 'scp -t /tmp/file',
                                    'identity; /bin/touch /tmp/ssh-policy-bypass',
                                    'identity\n/bin/touch /tmp/ssh-policy-bypass',
                                    '$(/bin/touch /tmp/ssh-policy-bypass)'):
                        denied = ssh(command)
                        self.assertEqual(denied.returncode, 126, denied)
                        self.assertEqual(denied.stdout, '', denied)
                    self.assertEqual(ssh('sftp', extra=('-s',)).returncode, 126)
                    pty = ssh('identity', extra=('-tt',))
                    self.assertIn('pty allocation request failed', pty.stderr.lower(), pty)
                    forward = ssh(extra=('-W', '192.0.2.10:22'))
                    self.assertNotEqual(forward.returncode, 0, forward)
                    self.assertNotEqual(manager.crun('exec', 'R1', '/bin/busybox', 'test', '-e',
                                                    '/tmp/ssh-policy-bypass', check=False).returncode, 0)
                    # Other unprivileged sessions sharing uid 65532 cannot
                    # replace a writable ancestor of authorized_keys.
                    rename = manager.crun('exec', '--user', '65532:65532', 'R1', '/bin/busybox', 'mv',
                                          '/home/lab/.ssh', '/home/lab/replaced-ssh', check=False)
                    self.assertNotEqual(rename.returncode, 0, rename)
                    self.assertTrue(manager.inspect('R1')['management']['configuration_verified'])
                    manager.crun('exec', 'R1', '/bin/busybox', 'chmod', '777', '/home/lab')
                    self.assertFalse(manager.inspect('R1')['management']['configuration_verified'])
                    with self.assertRaises(RuntimeFailure): manager.write_startup()
                    manager.crun('exec', 'R1', '/bin/busybox', 'chmod', '755', '/home/lab')
                    script = manager.directory / 'R1/files/ssh-dispatch.sh'; original = script.read_text()
                    script.write_text('#!/bin/sh\nexit 126\n')
                    self.assertFalse(manager.inspect('R1')['management']['configuration_verified'])
                    self.assertEqual(ssh('identity').returncode, 126)
                    with self.assertRaises(RuntimeFailure): manager.write_startup()
                    script.write_text(original); allowed()
                    manager.write_startup(); saved = load_startup(spec['name']); manager.stop()
                    self.assertEqual(saved['nodes'][2]['management']['ssh_actions'],
                                     ['hostname', 'identity', 'security-context'])
                    manager.start(saved); trust_host(); allowed()
                    self.assertEqual(ssh('/bin/sh').returncode, 126)
                    manager.stop()
                    saved['nodes'][2]['management']['ssh_actions'] = []
                    manager.start(validate(saved)); trust_host()
                    self.assertEqual(ssh('identity').returncode, 126)
                    self.assertEqual(ssh().returncode, 126)
                    self.assertTrue(manager.inspect('R1')['management']['configuration_verified'])
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, host_routes)
