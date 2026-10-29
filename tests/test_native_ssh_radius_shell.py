"""Real RADIUS SSH shells: PTY, lifetime, disconnect, accounting and cleanup."""
import hashlib
import os
from pathlib import Path
import pty
import re
import select
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.examples import radius_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.radius_session import session_parent
from network_labs.appliances.runtime import Manager, run, static_busybox_rootfs
from network_labs.appliances.spec import namespace, validate


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeSSHRadiusShellTests(unittest.TestCase):
    def test_real_shell_pty_background_expiry_disconnect_accounting_and_restart(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('dropbear', 'freeradius', 'ssh', 'busybox', 'crun'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        password = 'native-ssh-shell-password'; secret = 'native-ssh-shell-shared-secret'
        with tempfile.TemporaryDirectory() as folder, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder); key = root / 'identity'; known = root / 'known_hosts'
            run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', key])
            modules = next(p for p in ('/usr/lib/freeradius', '/usr/lib/x86_64-linux-gnu/freeradius')
                           if (Path(p) / 'rlm_pap.so').is_file())
            rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs', dropbear=shutil.which('dropbear'),
                freeradius=shutil.which('freeradius'), freeradius_modules=modules, freeradius_dictionaries='/usr/share/freeradius')
            digest = hashlib.sha256(password.encode()).hexdigest()
            spec = radius_lab(rootfs, secret, digest, ssh_key=key.with_suffix('.pub').read_text().strip(),
                              ssh_shell=True, accounting=True)
            spec['name'] = 'ssh-shell-' + str(os.getpid())
            spec['nodes'][0]['radius_access']['session_seconds'] = 4
            spec['nodes'][0]['radius_access']['users']['viewer'] = ['hostname']
            spec['nodes'][2]['radius_server']['users']['viewer'] = {'password_sha256': digest}
            spec['nodes'][1]['interfaces']['eth2'] = ''
            spec['nodes'].append({'name': 'PC3', 'runtime': 'oci', 'rootfs': str(rootfs), 'interfaces': {'eth0': '192.0.2.30/24'}})
            spec['links'].append([['SW1', 'eth2'], ['PC3', 'eth0']]); spec = validate(spec)
            manager = Manager(spec['name'])
            def trust_host():
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    result = manager.ns(3, 'ssh-keyscan', '-T', '2', '-t', 'ed25519', '192.0.2.10', check=False, timeout=4)
                    if result.returncode == 0 and 'ssh-ed25519' in result.stdout:
                        known.write_text(result.stdout); return
                    time.sleep(.1)
                self.fail('SSH shell server did not become ready')
            def ssh_args(terminal=False, action='shell'):
                return ['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                        '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
                        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'ConnectTimeout=3', '-o', 'LogLevel=ERROR',
                        '-i', str(key), '-tt' if terminal else '-T', 'lab@192.0.2.10', *([] if action is None else [action])]
            def ssh_script(script, username='learner', credential=password):
                return manager.ns(3, *ssh_args(), input_text=username + '\n' + credential + '\n' + script,
                                  check=False, timeout=14)
            def clean():
                self.assertEqual(list(session_parent(manager, 'PC1').glob('aaa-*')), [])
                self.assertNotIn('sleep 37', manager.crun('exec', 'PC1', '/bin/busybox', 'ps', '-o', 'args').stdout)
                directories = manager.crun('exec', 'PC1', '/bin/busybox', 'ls', '/tmp').stdout
                self.assertNotIn('ssh-radius.', directories, 'Guest transport directory leaked')
            def tty_shell(disconnect=False):
                master, slave = pty.openpty(); process = None; output = bytearray()
                user_sent = password_sent = commands_sent = False
                ready_marker = b'SSH-BACKGROUND-READY'
                try:
                    process = subprocess.Popen(['ip', 'netns', 'exec', namespace(spec, 3), *ssh_args(True, None)],
                                               stdin=slave, stdout=slave, stderr=slave)
                    os.close(slave); slave = None
                    deadline = time.monotonic() + 14
                    while time.monotonic() < deadline:
                        readable, _, _ = select.select([master], [], [], .05)
                        if readable:
                            try: data = os.read(master, 8192)
                            except OSError: break
                            if not data: break
                            output.extend(data)
                        elif process.poll() is not None: break
                        if not user_sent and b'RADIUS username: ' in output:
                            os.write(master, b'learner\n'); user_sent = True
                        if not password_sent and b'RADIUS password: ' in output:
                            os.write(master, password.encode() + b'\n'); password_sent = True
                        if not commands_sent and password_sent and b'$ ' in output:
                            commands = ('/bin/busybox test -t 0 && /bin/echo SSH-PTY-OK\n'
                                        '/bin/busybox id\n/bin/busybox cat /proc/self/status\n'
                                        '/bin/busybox cat /proc/self/cgroup\n/bin/busybox sleep 37 &\n'
                                        "printf 'SSH-%s-READY\\n' BACKGROUND\n" + ('' if disconnect else 'exit 0\n'))
                            os.write(master, commands.encode()); commands_sent = True
                        if disconnect and ready_marker in output:
                            self.assertIn(b'SSH-PTY-OK', output)
                            self.assertNotIn(password.encode(), output)
                            process.kill(); process.wait(timeout=2)
                            break
                    else: self.fail('SSH PTY did not finish: ' + repr(output))
                    self.assertTrue(commands_sent, repr(output))
                    if not disconnect: self.assertEqual(process.wait(timeout=2), 0, repr(output))
                    self.assertIn(b'uid=65532', output); self.assertIn(b'SSH-PTY-OK', output)
                    self.assertNotIn(password.encode(), output)
                    self.assertRegex(output, rb'NoNewPrivs:\s+1')
                    self.assertRegex(output, rb'CapEff:\s+0000000000000000')
                    self.assertRegex(output, rb'aaa-[0-9a-f]{32}')
                finally:
                    if slave is not None: os.close(slave)
                    os.close(master)
                    if process is not None and process.poll() is None: process.kill(); process.wait(timeout=2)
            try:
                with manager.locked(): manager.start(spec)
                trust_host()
                denied = ssh_script('/bin/touch /tmp/ssh-denied\n', credential='incorrect-password')
                self.assertNotEqual(denied.returncode, 0); self.assertEqual(denied.stdout, '')
                denied = ssh_script('/bin/touch /tmp/ssh-denied\n', username='viewer')
                self.assertNotEqual(denied.returncode, 0); self.assertEqual(denied.stdout, '')
                self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/busybox', 'test', '-e', '/tmp/ssh-denied', check=False).returncode, 0)
                clean()
                normal = ssh_script('/bin/busybox id\n/bin/busybox cat /proc/self/cgroup\n/bin/busybox sleep 37 &\nprintf "E0\\n"\nexit 7\n')
                self.assertEqual(normal.returncode, 7, normal)
                self.assertIn('uid=65532', normal.stdout); self.assertIn('E0', normal.stdout)
                self.assertRegex(normal.stdout, r'aaa-[0-9a-f]{32}'); clean()
                tty_shell(); clean()
                expired = ssh_script('/bin/busybox sleep 37 &\nwait\n')
                self.assertEqual(expired.returncode, 124, expired); clean()
                tty_shell(disconnect=True)
                deadline = time.monotonic() + 6
                while list(session_parent(manager, 'PC1').glob('aaa-*')) and time.monotonic() < deadline: time.sleep(.05)
                clean()
                barrier = manager.ns(3, *ssh_args(action='identity'), input_text='learner\n' + password + '\n', check=False, timeout=14)
                self.assertEqual(barrier.returncode, 0, barrier)
                records = manager.crun('exec', 'PC2', '/bin/busybox', 'cat', '/run/network-labs-radius-accounting/sessions').stdout
                lines = [line.split('|') for line in records.splitlines()]
                starts = [line for line in lines if line[0] == 'Start']; stops = [line for line in lines if line[0] == 'Stop']
                self.assertEqual(len(starts), 4, records); self.assertEqual(len(stops), 4, records)
                self.assertEqual({line[1] for line in starts}, {line[1] for line in stops})
                self.assertTrue({'1', '5', '6', '9'} <= {line[-1] for line in stops}, records)
                self.assertNotIn(secret, records); self.assertNotIn(password, records)
                with manager.locked():
                    manager.write_startup(); saved = load_startup(spec['name']); manager.stop(); manager.start(saved)
                trust_host()
                restored = ssh_script('/bin/echo RESTORED-SHELL\nexit\n')
                self.assertEqual(restored.returncode, 0, restored); self.assertIn('RESTORED-SHELL', restored.stdout); clean()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
