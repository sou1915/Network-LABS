"""Real SSH worker death preserves journal evidence until explicit orphan cleanup."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from network_labs.appliances.__main__ import main
from network_labs.appliances.capture import capture
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances import radius_journal as journal, radius_outbox as outbox, ssh_radius
from network_labs.appliances.runtime import Manager, run, static_busybox_rootfs
from network_labs.appliances.spec import namespace
from test_native_radius_accounting_retry_integration import requests
from test_native_radius_accounting_retry import attrs
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeSSHJournalTests(unittest.TestCase):
    def test_real_ssh_worker_sigkill_stop_handoff_stale_runtime_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('dropbear', 'freeradius', 'ssh', 'ssh-keygen', 'cc', 'busybox', 'crun', 'tcpdump'):
            self.assertIsNotNone(shutil.which(tool), tool)
        namespaces = run(['ip', 'netns', 'list']).stdout
        before = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        baseline = {(fam, kind): run(['ip', '-j', fam, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for fam in ('-4', '-6') for kind in ('route', 'rule')}
        secret = 'ssh-journal-native-secret'; password = 'ssh-journal-native-password'; clients = []
        with tempfile.TemporaryDirectory() as d, ThreadPoolExecutor(max_workers=1) as pool, \
                patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(d) / 'saved'):
            root = Path(d); key = root / 'identity'; known = root / 'known_hosts'
            run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', key])
            modules = next(p for p in ('/usr/lib/freeradius', '/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p) / 'rlm_pap.so').is_file())
            relay = root / 'ssh-relay'
            run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', Path(__file__).parents[1] / 'network_labs/appliances/ssh_radius_relay.c', '-o', relay])
            rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs', dropbear=shutil.which('dropbear'), ssh_relay=relay,
                freeradius=shutil.which('freeradius'), freeradius_modules=modules, freeradius_dictionaries='/usr/share/freeradius')
            spec = radius_lab(rootfs, secret, hashlib.sha256(password.encode()).hexdigest(), ssh_key=key.with_suffix('.pub').read_text().strip(),
                              ssh_shell=True, accounting=True, accounting_outbox=True, accounting_journal=True)
            spec['name'] = 'ssh-journal-' + str(os.getpid()); spec['nodes'][0]['radius_access']['session_seconds'] = 60
            spec['nodes'][1]['interfaces']['eth2'] = ''
            spec['nodes'].append({'name': 'PC3', 'runtime': 'oci', 'rootfs': str(rootfs), 'interfaces': {'eth0': '192.0.2.30/24'}})
            spec['links'].append([['SW1', 'eth2'], ['PC3', 'eth0']]); manager = Manager(spec['name'])

            def trust_host():
                until = time.monotonic() + 10
                while time.monotonic() < until:
                    scanned = manager.ns(3, 'ssh-keyscan', '-T', '2', '-t', 'ed25519', '192.0.2.10', check=False, timeout=4)
                    if scanned.returncode == 0 and 'ssh-ed25519' in scanned.stdout:
                        known.write_text(scanned.stdout); return
                    time.sleep(.1)
                self.fail('SSH host did not become ready')

            def arguments():
                return ['ip', 'netns', 'exec', namespace(spec, 3), 'ssh', '-F', '/dev/null', '-o', 'BatchMode=yes',
                        '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
                        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'ConnectTimeout=3', '-o', 'LogLevel=ERROR',
                        '-i', str(key), '-T', 'lab@192.0.2.10', 'shell']

            def orphan():
                old = {r['session_id'] for r in journal.pending(manager)['entries']}
                output = root / ('client-' + str(len(clients)) + '.log')
                with output.open('wb') as log:
                    client = subprocess.Popen(arguments(), stdin=subprocess.PIPE, stdout=log, stderr=log, text=True)
                clients.append(client)
                client.stdin.write('learner\n' + password + '\n/bin/echo SSH-JOURNAL-READY\n/bin/busybox sleep 60 &\nwait\n')
                client.stdin.flush()
                until = time.monotonic() + 12
                while time.monotonic() < until:
                    fresh = [r for r in journal.pending(manager)['entries'] if r['session_id'] not in old]
                    if fresh and 'SSH-JOURNAL-READY' in output.read_text(errors='replace'):
                        sid = fresh[0]['session_id']; record = journal.read(journal.directory(manager) / (sid + '.json'), manager)
                        group = journal.group_path(manager, record)
                        if group.exists() and not journal.empty(group): return client, sid, group, record
                    if client.poll() is not None: self.fail('SSH client exited before journaled shell became active')
                    time.sleep(.05)
                self.fail('SSH session did not become active')

            def kill_owner(record):
                worker = manager.read()['ssh_radius_workers']['PC1']
                self.assertEqual(worker['pid'], record['supervisor_pid'])
                self.assertEqual(worker['starttime'], record['supervisor_start'])
                os.kill(worker['pid'], signal.SIGKILL)  # Only the supervisor, not its process group/payload.
                ssh_radius._PROCESSES[worker['pid']].wait(timeout=3)

            try:
                with manager.locked(): manager.start(spec); manager.write_startup(); saved = load_startup(spec['name'])
                trust_host(); client, sid, group, record = orphan()
                self.assertTrue(str(journal.directory(manager)).startswith(str(root / 'saved')))
                self.assertEqual(record['phase'], 'intent')
                serialized = json.dumps(record); self.assertNotIn(secret, serialized); self.assertNotIn(password, serialized)
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(['radius-accounting-reconcile', spec['name'], sid, '--terminate', '--json']), 1)
                self.assertEqual(json.loads(output.getvalue())['error'], 'SUPERVISOR_STILL_ACTIVE')
                kill_owner(record)
                with manager.locked():
                    refused = journal.reconcile(manager, sid)
                    self.assertEqual(refused['error'], 'SESSION_STILL_POPULATED', refused)
                    self.assertEqual(outbox.pending(manager)['pending'], 0)
                self.assertFalse(journal.empty(group))
                records = manager.crun('exec', 'PC2', '/bin/cat', '/run/network-labs-radius-accounting/sessions').stdout
                self.assertTrue(any(line.startswith('Start|' + sid + '|') for line in records.splitlines()))
                ready = threading.Event(); quiet = root / 'quiet.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', quiet, seconds=3, packets=50,
                                     expression='udp port 1813', ready=ready.set)
                self.assertTrue(ready.wait(5))
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(['radius-accounting-reconcile', spec['name'], sid, '--terminate', '--json']), 0)
                result = json.loads(output.getvalue()); self.assertTrue(result['terminated']); self.assertTrue(result['stop_queued'])
                future.result(timeout=6); self.assertEqual(requests(quiet.read_bytes()), [])
                self.assertFalse(group.exists()); self.assertEqual(journal.pending(manager)['pending'], 0)
                self.assertEqual(manager.crun('exec', 'PC2', '/bin/cat', '/run/network-labs-radius-accounting/sessions').stdout, records)
                stop = outbox.read(outbox.folder(manager) / (sid + '.json'), manager)
                self.assertEqual(stop['session_seconds'], 0); self.assertEqual(stop['terminate_cause'], 9)
                ready = threading.Event(); pcap = root / 'stop.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', pcap, seconds=3, packets=50,
                                     expression='udp port 1813', ready=ready.set)
                self.assertTrue(ready.wait(5))
                with manager.locked(): self.assertEqual(outbox.flush(manager, limit=1)['status'], 'passed')
                future.result(timeout=6); packets = requests(pcap.read_bytes()); self.assertEqual(len(packets), 1)
                self.assertEqual(attrs(packets[0])[44].decode(), sid)
                self.assertEqual(int.from_bytes(attrs(packets[0])[40], 'big'), 2)
                self.assertEqual(int.from_bytes(attrs(packets[0])[49], 'big'), 9)
                client.wait(timeout=3); self.assertNotEqual(client.returncode, 0)
                old_token = manager.read()['ssh_radius_workers']['PC1']['token']
                with manager.locked(): manager.stop(); manager.start(saved)
                self.assertNotEqual(manager.read()['ssh_radius_workers']['PC1']['token'], old_token)
                trust_host(); client, stale, group, record = orphan(); kill_owner(record)
                with manager.locked():
                    manager.stop(); manager.start(saved)
                    refused = journal.reconcile(manager, stale, terminate=True)
                    self.assertEqual(refused['error'], 'RUNTIME_IDENTITY_CHANGED', refused)
                    self.assertEqual(outbox.pending(manager)['pending'], 0)
                self.assertEqual(journal.pending(manager)['pending'], 1)
                trust_host()
                healthy = run(arguments(), input_text='learner\n' + password + '\n/bin/busybox id\nexit\n', check=False, timeout=12)
                self.assertEqual(healthy.returncode, 0, healthy); self.assertIn('uid=65532', healthy.stdout)
                # Healthy final SSH status follows checkpoint, handoff and Stop acknowledgement.
                self.assertEqual(journal.pending(manager)['pending'], 1); self.assertEqual(outbox.pending(manager)['pending'], 0)
                with manager.locked(): manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
                for client in clients:
                    if client.poll() is None: client.kill()
                    client.wait(timeout=3); client.stdin.close()
        self.assertEqual(run(['ip', 'netns', 'list']).stdout, namespaces)
        for (fam, kind), value in baseline.items():
            self.assertEqual(run(['ip', '-j', fam, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, value)
        after = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        hardware = {n for n, _ in after - before if (Path('/sys/class/net') / n / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before, after, hardware), {'removed_or_replaced': set(), 'added_virtual': set()})
