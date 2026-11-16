"""Real Telnet PTY sessions use the shared Start gate, cgroup cleanup and Stop journal."""
from concurrent.futures import ThreadPoolExecutor
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
from network_labs.appliances.radius_session import session_parent
from network_labs.appliances import radius_journal as journal, radius_outbox as outbox
from network_labs.appliances.runtime import Manager, run, static_busybox_rootfs
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeTelnetShellTests(unittest.TestCase):
    def test_real_telnet_pty_start_gate_exit_expiry_disconnect_journal_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('freeradius', 'crun', 'busybox', 'ip', 'cc', 'nft'): self.assertIsNotNone(shutil.which(tool), tool)
        namespaces = run(['ip', 'netns', 'list']).stdout
        before = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        baseline = {(fam, kind): run(['ip', '-j', fam, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for fam in ('-4', '-6') for kind in ('route', 'rule')}
        password = 'native-telnet-shell-password'; secret = 'native-telnet-shell-shared-secret'
        with tempfile.TemporaryDirectory() as d, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(d) / 'saved'):
            root = Path(d); binary = root / 'login'
            run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', Path(__file__).parents[1] / 'network_labs/appliances/telnet_radius_login.c', '-o', binary])
            modules = next(p for p in ('/usr/lib/freeradius', '/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p) / 'rlm_pap.so').is_file())
            rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs', telnet_login=binary,
                freeradius=shutil.which('freeradius'), freeradius_modules=modules, freeradius_dictionaries='/usr/share/freeradius')
            digest = hashlib.sha256(password.encode()).hexdigest()
            spec = radius_lab(rootfs, secret, digest, role_policy=True, telnet=True, telnet_shell=True,
                              accounting=True, accounting_outbox=True, accounting_journal=True)
            spec['name'] = 'telnet-shell-' + str(os.getpid()); spec['nodes'][0]['radius_access']['session_seconds'] = 4
            spec['nodes'][0]['radius_access']['user_roles']['viewer'] = ['observer']
            spec['nodes'][2]['radius_server']['users']['viewer'] = {'password_sha256': digest}
            manager = Manager(spec['name']); client = Path(__file__).with_name('telnet_radius_client_worker.py')
            def connection(action='shell', username='learner', credential=password, script=None, marker=None):
                request = dict(address='192.0.2.10', action=action, username=username, password=credential)
                if script is not None: request['shell_script'] = script
                if marker is not None: request['disconnect_marker'] = marker
                result = manager.ns(2, '/usr/bin/python3', '-I', str(client), input_text=json.dumps(request), timeout=15, check=False)
                self.assertEqual(result.returncode, 0, 'Telnet shell peer failed')
                output = json.loads(result.stdout); self.assertTrue(output['closed'])
                self.assertNotIn(password, output['output']); self.assertNotIn(secret, output['output'])
                return output['output']
            def records():
                return manager.crun('exec', 'PC2', '/bin/cat', '/run/network-labs-radius-accounting/sessions', check=False).stdout
            def clean():
                # A following diagnostic is a barrier behind the sequential worker's cleanup/Stop.
                self.assertIn('uid=65532', connection(action='identity'))
                self.assertEqual(list(session_parent(manager, 'PC1').glob('aaa-*')), [])
                self.assertNotIn('sleep 37', manager.crun('exec', 'PC1', '/bin/busybox', 'ps', '-o', 'args').stdout)
                self.assertEqual(journal.pending(manager)['pending'], 0)
            try:
                with manager.locked(): manager.start(spec)
                for options in ({'username': 'viewer'}, {'credential': 'incorrect-password'}):
                    text = connection(script='/bin/touch /tmp/telnet-denied\nexit\n', **options)
                    self.assertIn('Telnet RADIUS request denied or unavailable.', text)
                self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/busybox', 'test', '-e', '/tmp/telnet-denied', check=False).returncode, 0)
                self.assertFalse(records())
                normal = connection(script='/bin/busybox test -t 0 && /bin/echo TELNET-PTY-OK\n/bin/busybox id\n/bin/busybox cat /proc/self/status\n/bin/busybox cat /proc/self/cgroup\n/bin/busybox sleep 37 &\nexit 7\n')
                self.assertIn('TELNET-PTY-OK', normal); self.assertIn('uid=65532', normal)
                fields = dict(line.split(':', 1) for line in normal.splitlines() if ':' in line)
                self.assertEqual(fields['NoNewPrivs'].strip(), '1'); self.assertEqual(int(fields['CapEff'].strip(), 16), 0)
                self.assertRegex(normal, r'aaa-[0-9a-f]{32}'); clean()
                expired = connection(script='/bin/busybox sleep 37 &\nwait\n'); clean()
                disconnected = connection(script='/bin/busybox sleep 37 &\nprintf "BACKGROUND-%s\\n" READY\nwait\n', marker='BACKGROUND-READY')
                self.assertIn('BACKGROUND-READY', disconnected); clean()
                # Lose only accounting responses: Access-Accept still succeeds, but no shell may launch.
                manager.ns(0, 'nft', '-f', '-', input_text='add table inet telnet_loss\nadd chain inet telnet_loss input { type filter hook input priority -10; policy accept; }\nadd rule inet telnet_loss input udp sport 1813 counter drop\n')
                before_records = records()
                denied = connection(script='/bin/touch /tmp/start-bypass\nexit\n')
                self.assertIn('Telnet RADIUS request denied or unavailable.', denied)
                self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/busybox', 'test', '-e', '/tmp/start-bypass', check=False).returncode, 0)
                self.assertIn('Start|', records()[len(before_records):]); clean()
                self.assertEqual(outbox.pending(manager)['pending'], 1)
                manager.ns(0, 'nft', 'delete', 'table', 'inet', 'telnet_loss')
                with manager.locked(): self.assertEqual(outbox.flush(manager, limit=1)['status'], 'passed')
                self.assertEqual(outbox.pending(manager)['pending'], 0)
                rows = [line.split('|') for line in records().splitlines()]
                starts = [row for row in rows if row[0] == 'Start']; stops = [row for row in rows if row[0] == 'Stop']
                self.assertEqual(len(starts), 4); self.assertEqual({r[1] for r in starts}, {r[1] for r in stops})
                self.assertTrue({'5', '6', '9'} <= {r[-1] for r in stops})
                with manager.locked(): manager.write_startup(); saved = load_startup(spec['name']); manager.stop(); manager.start(saved)
                restored = connection(script='/bin/busybox id\nexit\n'); self.assertIn('uid=65532', restored); clean()
                self.assertEqual(outbox.pending(manager)['pending'], 0)
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        self.assertEqual(run(['ip', 'netns', 'list']).stdout, namespaces)
        for (fam, kind), value in baseline.items(): self.assertEqual(run(['ip', '-j', fam, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, value)
        after = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        hardware = {n for n, _ in after - before if (Path('/sys/class/net') / n / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before, after, hardware), {'removed_or_replaced': set(), 'added_virtual': set()})
