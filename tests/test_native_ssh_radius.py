"""Real SSH transport plus independently verified FreeRADIUS decisions."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.examples import radius_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, run, static_busybox_rootfs
from network_labs.appliances.spec import validate
from network_labs.appliances.ssh_radius import alive, stop_worker


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeSSHRadiusTests(unittest.TestCase):
    def test_real_ssh_radius_actions_denials_outages_protected_bridge_and_restart(self):
        self.assertEqual(os.geteuid(), 0)
        for name in ('dropbear', 'freeradius', 'ssh', 'ssh-keygen', 'crun', 'busybox', 'setpriv'):
            self.assertIsNotNone(shutil.which(name), name + ' required')
        host_port_policy = Path('/proc/sys/net/ipv4/ip_unprivileged_port_start').read_text()
        routes = run(['ip', '-j', 'route', 'show']).stdout
        records = []
        secret = 'native-ssh-radius-shared-secret'; password = 'native-radius-login-password'
        with tempfile.TemporaryDirectory() as folder, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder); key = root / 'identity'; wrong = root / 'wrong'
            for path in (key, wrong): run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', path])
            modules = next(p for p in ('/usr/lib/freeradius', '/usr/lib/x86_64-linux-gnu/freeradius')
                           if (Path(p) / 'rlm_pap.so').is_file())
            rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs', dropbear=shutil.which('dropbear'),
                freeradius=shutil.which('freeradius'), freeradius_modules=modules, freeradius_dictionaries='/usr/share/freeradius')
            digest = hashlib.sha256(password.encode()).hexdigest()
            spec = radius_lab(rootfs, secret, digest, ssh_key=key.with_suffix('.pub').read_text().strip())
            spec['name'] = 'ssh-radius-' + str(os.getpid())
            spec['nodes'][0]['radius_access']['users']['viewer'] = ['hostname']
            spec['nodes'][2]['radius_server']['users']['viewer'] = {'password_sha256': digest}
            for username, credential in (('unicode', 'pässword✓'), ('maximum', 'z' * 128)):
                spec['nodes'][0]['radius_access']['users'][username] = ['identity']
                spec['nodes'][2]['radius_server']['users'][username] = {'password_sha256': hashlib.sha256(credential.encode()).hexdigest()}
            spec['nodes'][1]['interfaces']['eth2'] = ''
            spec['nodes'].append({'name': 'PC3', 'runtime': 'oci', 'rootfs': str(rootfs), 'interfaces': {'eth0': '192.0.2.30/24'}})
            spec['links'].append([['SW1', 'eth2'], ['PC3', 'eth0']]); spec = validate(spec)
            manager = Manager(spec['name']); known = root / 'known_hosts'
            def trust_host():
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    result = manager.ns(3, 'ssh-keyscan', '-T', '2', '-t', 'ed25519', '192.0.2.10', check=False, timeout=4)
                    if result.returncode == 0 and 'ssh-ed25519' in result.stdout:
                        known.write_text(result.stdout); return
                    time.sleep(.1)
                self.fail('SSH RADIUS node did not become ready')
            def ssh(action, username='learner', credential=password, identity=key, data=None, extra=()):
                return manager.ns(3, 'ssh', '-F', '/dev/null', '-T', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                                  '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
                                  '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'ConnectTimeout=3', '-o', 'LogLevel=ERROR',
                                  '-i', str(identity), *extra, 'lab@192.0.2.10', action, timeout=20, check=False,
                                  input_text=(username + '\n' + credential + '\n') if data is None else data)
            def allowed():
                result = ssh('identity')
                log = manager.directory / 'PC1.ssh-radius.log'
                self.assertEqual(result.returncode, 0, (result, log.read_text(errors='replace')[-2000:]))
                self.assertIn('uid=65532', result.stdout)
                hostname = ssh('hostname', username='viewer'); self.assertEqual(hostname.returncode, 0, hostname)
                self.assertEqual(hostname.stdout.strip(), 'PC1')
                security = ssh('security-context'); self.assertEqual(security.returncode, 0, security)
                fields = dict(line.split(':', 1) for line in security.stdout.splitlines() if ':' in line)
                self.assertEqual(fields['NoNewPrivs'].strip(), '1'); self.assertEqual(int(fields['CapEff'].strip(), 16), 0)
            try:
                with manager.locked(): manager.start(spec)
                records.append(dict(manager.state['ssh_radius_workers']['PC1']))
                trust_host(); allowed()
                for username, credential in (('unicode', 'pässword✓'), ('maximum', 'z' * 128)):
                    result = ssh('identity', username=username, credential=credential)
                    self.assertEqual(result.returncode, 0, result)
                    self.assertIn('uid=65532', result.stdout)
                # This also exercises an administrative node console which
                # owns the lab lock while its SSH client is running.
                with manager.locked():
                    self.assertEqual(ssh('hostname').returncode, 0)
                for options in ({'credential': 'wrong-password'}, {'username': 'unknown'},
                                {'username': 'viewer'}, {'data': ''}, {'data': 'learner\n'}):
                    denied = ssh('identity', **options)
                    self.assertEqual(denied.returncode, 126, denied); self.assertEqual(denied.stdout, '')
                self.assertNotEqual(ssh('identity', identity=wrong).returncode, 0)
                for command in ('/bin/sh', 'identity; /bin/touch /tmp/bypass', 'scp -t /tmp/file'):
                    self.assertEqual(ssh(command).returncode, 126)
                self.assertEqual(ssh('sftp', extra=('-s',)).returncode, 126)
                report = manager.inspect('PC1')['management']
                self.assertTrue(report['configuration_verified'], report)
                self.assertTrue(report['ssh_radius_worker_available'], report)
                self.assertNotIn(secret, json.dumps(report)); self.assertNotIn(password, json.dumps(report))
                cmdline = Path('/proc/' + str(records[0]['pid']) + '/cmdline').read_text()
                self.assertNotIn(secret, cmdline); self.assertNotIn(password, cmdline)
                for path in ('/lab/ssh-radius-client.sh', '/lab/ssh-dispatch.sh', '/lab/management.json'):
                    content = manager.crun('exec', 'PC1', '/bin/busybox', 'cat', path).stdout
                    self.assertNotIn(secret, content); self.assertNotIn(password, content)
                radius = manager.inspect('PC2')['radius_server']
                manager.crun('exec', 'PC2', '/bin/busybox', 'kill', '-TERM', str(radius['process']['pid']))
                deadline = time.monotonic() + 5
                while manager.inspect('PC2')['radius_server']['udp_socket']['status'] != 'absent':
                    if time.monotonic() >= deadline: self.fail('RADIUS listener remained after stop')
                    time.sleep(.05)
                denied = ssh('identity'); self.assertEqual(denied.returncode, 126, denied)
                self.assertEqual(denied.stdout, '')
                with manager.locked(): stop_worker(manager, 'PC1')
                self.assertFalse(alive(records[0]))
                self.assertFalse(manager.inspect('PC1')['management']['ssh_radius_worker_available'])
                self.assertEqual(ssh('identity').returncode, 126)
                # An unprivileged node process cannot impersonate a dead
                # supervisor and collect subsequent RADIUS passwords.
                code = "import socket; s=socket.socket();\ntry: s.bind(('127.0.0.1',813))\nexcept PermissionError: print('protected')\nelse: raise SystemExit(99)"
                protected = manager.ns(0, 'setpriv', '--reuid', '65532', '--regid', '65532', '--clear-groups',
                                       '/usr/bin/python3', '-I', '-c', code, check=False, timeout=3)
                self.assertEqual(protected.returncode, 0, protected); self.assertEqual(protected.stdout.strip(), 'protected')
                with manager.locked():
                    manager.write_startup(); saved = load_startup(spec['name']); manager.stop(); manager.start(saved)
                records.append(dict(manager.state['ssh_radius_workers']['PC1']))
                self.assertNotEqual(records[0]['token'], records[1]['token'])
                trust_host(); allowed()
                self.assertEqual(ssh('identity', username='viewer').returncode, 126)
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        self.assertTrue(all(not alive(record) for record in records))
        self.assertEqual(Path('/proc/sys/net/ipv4/ip_unprivileged_port_start').read_text(), host_port_policy)
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
