"""Real FreeRADIUS and SSH enforce reusable local roles without privilege elevation."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.capture import capture
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.radius import probe
from network_labs.appliances.radius_exec import execute
from network_labs.appliances.radius_login import login
from network_labs.appliances import radius_journal as journal, radius_outbox as outbox
from network_labs.appliances.radius_server import start_servers
from network_labs.appliances.runtime import Manager, run, static_busybox_rootfs
from network_labs.appliances.spec import validate
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeRadiusRoleTests(unittest.TestCase):
    def test_real_roles_cli_ssh_denial_packets_accounting_outage_and_cold_restore(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('freeradius', 'dropbear', 'ssh', 'ssh-keygen', 'cc', 'crun', 'busybox', 'ip', 'tcpdump'):
            self.assertIsNotNone(shutil.which(tool), tool)
        namespaces = run(['ip', 'netns', 'list']).stdout
        before = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        baseline = {(fam, kind): run(['ip', '-j', fam, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for fam in ('-4', '-6') for kind in ('route', 'rule')}
        port_policy = Path('/proc/sys/net/ipv4/ip_unprivileged_port_start').read_text()
        secret = 'native-radius-role-shared-secret'; password = 'native-radius-role-password'
        with tempfile.TemporaryDirectory() as d, ThreadPoolExecutor(max_workers=1) as pool, \
                patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(d) / 'saved'):
            root = Path(d); key = root / 'identity'; known = root / 'known_hosts'
            run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', key])
            modules = next(p for p in ('/usr/lib/freeradius', '/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p) / 'rlm_pap.so').is_file())
            relay = root / 'ssh-relay'
            run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', Path(__file__).parents[1] / 'network_labs/appliances/ssh_radius_relay.c', '-o', relay])
            rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs', dropbear=shutil.which('dropbear'), ssh_relay=relay,
                freeradius=shutil.which('freeradius'), freeradius_modules=modules, freeradius_dictionaries='/usr/share/freeradius')
            digest = hashlib.sha256(password.encode()).hexdigest()
            spec = radius_lab(rootfs, secret, digest, role_policy=True, ssh_key=key.with_suffix('.pub').read_text().strip(),
                              ssh_shell=True, accounting=True, accounting_outbox=True, accounting_journal=True,
                              ssh_actions=['identity', 'security-context', 'shell'])
            spec['name'] = 'radius-roles-' + str(os.getpid())
            access = spec['nodes'][0]['radius_access']; access['session_seconds'] = 10
            access['user_roles'] = {'reader': ['observer'], 'auditor': ['auditor'], 'combined': ['observer', 'auditor'], 'session-user': ['session']}
            spec['nodes'][2]['radius_server']['users'] = {name: {'password_sha256': digest} for name in (*access['user_roles'], 'backend-only')}
            spec['nodes'][1]['interfaces']['eth2'] = ''
            spec['nodes'].append({'name': 'PC3', 'runtime': 'oci', 'rootfs': str(rootfs), 'interfaces': {'eth0': '192.0.2.30/24'}})
            spec['links'].append([['SW1', 'eth2'], ['PC3', 'eth0']]); spec = validate(spec); manager = Manager(spec['name'])

            def trust_host():
                until = time.monotonic() + 10
                while time.monotonic() < until:
                    result = manager.ns(3, 'ssh-keyscan', '-T', '2', '-t', 'ed25519', '192.0.2.10', check=False, timeout=4)
                    if result.returncode == 0 and 'ssh-ed25519' in result.stdout:
                        known.write_text(result.stdout); return
                    time.sleep(.1)
                self.fail('SSH host did not become ready')

            def cli(action, user='reader', credential=password):
                with manager.locked():
                    return execute(manager, 'PC1', '192.0.2.20', action=action, username=user, password=credential, secret=secret, timeout=1)

            def ssh(action, user='reader', credential=password, script=''):
                return manager.ns(3, 'ssh', '-F', '/dev/null', '-T', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                    '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known), '-o', 'GlobalKnownHostsFile=/dev/null',
                    '-o', 'ConnectTimeout=3', '-o', 'LogLevel=ERROR', '-i', str(key), 'lab@192.0.2.10', action,
                    input_text=user + '\n' + credential + '\n' + script, check=False, timeout=15)

            def positives():
                reader = cli('identity'); self.assertEqual(reader['status'], 'passed', reader)
                self.assertEqual(reader['authorization'], {'mode': 'roles', 'roles': ['observer'], 'actions': ['hostname', 'identity']})
                self.assertIn('uid=65532', reader['stdout'])
                self.assertEqual(cli('hostname')['stdout'].strip(), 'PC1')
                auditor = cli('security-context', 'auditor'); self.assertEqual(auditor['status'], 'passed', auditor)
                fields = dict(line.split(':', 1) for line in auditor['stdout'].splitlines() if ':' in line)
                self.assertEqual(fields['NoNewPrivs'].strip(), '1'); self.assertEqual(int(fields['CapEff'].strip(), 16), 0)
                for action in ('identity', 'security-context'):
                    combined = cli(action, 'combined'); self.assertEqual(combined['status'], 'passed', combined)
                    self.assertEqual(combined['authorization']['roles'], ['auditor', 'observer'])
                self.assertEqual(ssh('identity').returncode, 0)
                self.assertEqual(ssh('security-context', 'auditor').returncode, 0)
                self.assertEqual(ssh('security-context', 'combined').returncode, 0)

            def denials():
                for user, action in (('reader', 'security-context'), ('auditor', 'identity'), ('session-user', 'identity'), ('backend-only', 'hostname'), ('unknown', 'identity')):
                    result = cli(action, user); self.assertEqual(result['error'], 'ACTION_NOT_ALLOWED', result)
                    self.assertFalse(result['executed']); self.assertIsNone(result['authentication'])
                for user, action in (('reader', 'security-context'), ('auditor', 'identity'), ('session-user', 'identity'), ('backend-only', 'identity'), ('reader', 'hostname')):
                    denied = ssh(action, user); self.assertEqual(denied.returncode, 126, denied); self.assertEqual(denied.stdout, '')
                with manager.locked():
                    denied = login(manager, 'PC1', '192.0.2.20', username='reader', password=password, secret=secret)
                    self.assertEqual(denied['error'], 'ACTION_NOT_ALLOWED'); self.assertFalse(denied['session_attempted'])
                denied = ssh('shell', 'reader', script='/bin/touch /tmp/role-denied\n')
                self.assertEqual(denied.returncode, 126, denied)
                self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/busybox', 'test', '-e', '/tmp/role-denied', check=False).returncode, 0)

            try:
                with manager.locked(): manager.start(spec)
                trust_host()
                # Positive packet control uses the same filter/capture point as local-denial evidence.
                ready = threading.Event(); future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', root / 'allowed.pcap',
                    seconds=2, packets=100, expression='udp port 1812', ready=ready.set)
                self.assertTrue(ready.wait(5)); self.assertEqual(cli('identity')['status'], 'passed')
                self.assertGreater(future.result(timeout=5)['captured_packets'], 0)
                positives()
                with manager.locked():
                    backend_only = probe(manager, 'PC1', '192.0.2.20', username='backend-only', password=password, secret=secret, timeout=2)
                self.assertEqual(backend_only['authentication']['decision'], 'accepted')
                self.assertTrue(backend_only['authentication']['response_verified'])
                ready = threading.Event(); future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', root / 'denied.pcap',
                    seconds=5, packets=100, expression='udp port 1812 or udp port 1813', ready=ready.set)
                self.assertTrue(ready.wait(5)); started = time.monotonic(); denials()
                self.assertLess(time.monotonic() - started, 5, 'Denials must finish within the capture window')
                self.assertEqual(future.result(timeout=7)['captured_packets'], 0)
                wrong = cli('identity', credential='incorrect-password'); self.assertFalse(wrong['executed'])
                self.assertEqual(wrong['authentication']['authentication']['decision'], 'rejected')
                self.assertEqual(ssh('identity', credential='incorrect-password').returncode, 126)
                shell = ssh('shell', 'session-user', script='/bin/busybox id\n/bin/busybox cat /proc/self/status\nexit\n')
                self.assertEqual(shell.returncode, 0, shell); self.assertIn('uid=65532', shell.stdout)
                fields = dict(line.split(':', 1) for line in shell.stdout.splitlines() if ':' in line)
                self.assertEqual(fields['NoNewPrivs'].strip(), '1'); self.assertEqual(int(fields['CapEff'].strip(), 16), 0)
                launched = []
                def launch(args, **options):
                    process = subprocess.run(args, input='/bin/busybox id\nexit\n', capture_output=True, text=True, timeout=options['timeout'])
                    self.assertIn('uid=65532', process.stdout); launched.append(1); return process.returncode
                with manager.locked():
                    local = login(manager, 'PC1', '192.0.2.20', username='session-user', password=password, secret=secret, seconds=5, launcher=launch)
                self.assertEqual(local['status'], 'passed', local); self.assertEqual(local['authorization']['roles'], ['session'])
                self.assertEqual(len(launched), 1); self.assertEqual(local['accounting']['journal']['status'], 'handed_off')
                self.assertEqual(journal.pending(manager)['pending'], 0); self.assertEqual(outbox.pending(manager)['pending'], 0)
                records = manager.crun('exec', 'PC2', '/bin/cat', '/run/network-labs-radius-accounting/sessions').stdout
                starts = [l.split('|')[1] for l in records.splitlines() if l.startswith('Start|')]
                stops = [l.split('|')[1] for l in records.splitlines() if l.startswith('Stop|')]
                self.assertEqual(len(starts), 2); self.assertEqual(set(starts), set(stops))
                self.assertNotIn(secret, records); self.assertNotIn(password, records)
                observed = manager.inspect('PC2')['radius_server']
                manager.crun('exec', 'PC2', '/bin/busybox', 'kill', '-TERM', str(observed['process']['pid']))
                until = time.monotonic() + 5
                while manager.inspect('PC2')['radius_server']['udp_socket']['status'] != 'absent':
                    if time.monotonic() >= until: self.fail('RADIUS listener remained after stop')
                    time.sleep(.05)
                unavailable = cli('identity'); self.assertFalse(unavailable['executed'])
                denied = ssh('shell', 'session-user', script='/bin/touch /tmp/backend-bypass\n')
                self.assertEqual(denied.returncode, 126, denied)
                self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/busybox', 'test', '-e', '/tmp/backend-bypass', check=False).returncode, 0)
                with manager.locked(): start_servers(manager)
                until = time.monotonic() + 5
                while manager.inspect('PC2')['radius_server']['udp_socket']['status'] == 'absent':
                    if time.monotonic() >= until: self.fail('RADIUS listener did not recover')
                    time.sleep(.05)
                self.assertEqual(cli('identity')['status'], 'passed')
                with manager.locked():
                    manager.write_startup(); saved = load_startup(spec['name'])
                    self.assertEqual(saved['nodes'][0]['radius_access']['user_roles'], spec['nodes'][0]['radius_access']['user_roles'])
                    self.assertNotIn('users', saved['nodes'][0]['radius_access'])
                    manager.stop(); manager.start(saved)
                trust_host(); positives(); denials()
                restricted = copy.deepcopy(saved); restricted['nodes'][0]['radius_access']['roles']['observer'] = ['hostname']
                with manager.locked(): manager.stop(); manager.start(restricted)
                trust_host()
                self.assertEqual(cli('identity')['error'], 'ACTION_NOT_ALLOWED')
                self.assertEqual(ssh('identity').returncode, 126)
                self.assertEqual(cli('hostname')['status'], 'passed')
                with manager.locked(): manager.stop(); manager.start(saved)
                trust_host(); self.assertEqual(ssh('identity').returncode, 0)
                self.assertEqual(journal.pending(manager)['pending'], 0); self.assertEqual(outbox.pending(manager)['pending'], 0)
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        self.assertEqual(run(['ip', 'netns', 'list']).stdout, namespaces)
        self.assertEqual(Path('/proc/sys/net/ipv4/ip_unprivileged_port_start').read_text(), port_policy)
        for (fam, kind), value in baseline.items():
            self.assertEqual(run(['ip', '-j', fam, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, value)
        after = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        hardware = {n for n, _ in after - before if (Path('/sys/class/net') / n / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before, after, hardware), {'removed_or_replaced': set(), 'added_virtual': set()})
