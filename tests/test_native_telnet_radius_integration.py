"""Actual BusyBox Telnet/RADIUS diagnostics, pre-auth privilege drop and isolation."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
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
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.radius import probe
from network_labs.appliances.radius_server import start_servers
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.ssh_radius import alive, stop_worker
from network_labs.appliances.telnet_radius import LOGIN, PORT
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeTelnetRadiusTests(unittest.TestCase):
    def test_actual_telnet_privileges_roles_denials_outage_worker_and_saved_restore(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('freeradius', 'crun', 'busybox', 'ip', 'cc', 'tcpdump'):
            self.assertIsNotNone(shutil.which(tool), tool)
        namespaces = run(['ip', 'netns', 'list']).stdout
        before = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        baseline = {(fam, kind): run(['ip', '-j', fam, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for fam in ('-4', '-6') for kind in ('route', 'rule')}
        host_policy = Path('/proc/sys/net/ipv4/ip_unprivileged_port_start').read_text()
        password = 'native-telnet-radius-password'; secret = 'native-telnet-radius-secret'; workers = []
        with tempfile.TemporaryDirectory() as d, ThreadPoolExecutor(max_workers=2) as pool, \
                patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(d) / 'saved'):
            root = Path(d); binary = root / 'telnet-login'
            run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', Path(__file__).parents[1] / 'network_labs/appliances/telnet_radius_login.c', '-o', binary])
            modules = next(p for p in ('/usr/lib/freeradius', '/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p) / 'rlm_pap.so').is_file())
            rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs', telnet_login=binary,
                freeradius=shutil.which('freeradius'), freeradius_modules=modules, freeradius_dictionaries='/usr/share/freeradius')
            digest = hashlib.sha256(password.encode()).hexdigest()
            spec = radius_lab(rootfs, secret, digest, telnet=True, role_policy=True); spec['name'] = 'telnet-radius-' + str(os.getpid())
            access = spec['nodes'][0]['radius_access']; access['user_roles'].update(viewer=['observer'], auditor=['auditor'])
            for name in ('viewer', 'auditor', 'backend-only'): spec['nodes'][2]['radius_server']['users'][name] = {'password_sha256': digest}
            spec['nodes'][0]['management']['telnet_actions'] = ['identity', 'security-context']
            manager = Manager(spec['name']); client = Path(__file__).with_name('telnet_radius_client_worker.py')

            def telnet(action='identity', username='learner', credential=password, **options):
                request = dict(address='192.0.2.10', action=action, username=username, password=credential, **options)
                result = manager.ns(2, '/usr/bin/python3', '-I', str(client), input_text=json.dumps(request), check=False, timeout=14)
                self.assertEqual(result.returncode, 0, 'Telnet test peer failed without diagnostic output')
                output = json.loads(result.stdout); self.assertTrue(output['closed'])
                self.assertNotIn(password, output['output']); self.assertNotIn(secret, output['output'])
                return output['output']

            def denied(**options):
                text = telnet(**options)
                self.assertIn('Telnet RADIUS request denied or unavailable.', text)
                self.assertNotIn('uid=65532', text); self.assertNotIn('NoNewPrivs:', text)

            def positives():
                self.assertIn('uid=65532', telnet())
                self.assertIn('uid=65532', telnet(username='viewer'))
                text = telnet(action='security-context', username='auditor')
                fields = dict(line.split(':', 1) for line in text.splitlines() if ':' in line)
                self.assertEqual(fields['NoNewPrivs'].strip(), '1'); self.assertEqual(int(fields['CapEff'].strip(), 16), 0)

            def wait_listener(present=True):
                until = time.monotonic() + 5
                while time.monotonic() < until:
                    if (manager.inspect('PC2')['radius_server']['udp_socket']['status'] != 'absent') == present: return
                    time.sleep(.05)
                self.fail('RADIUS listener state did not settle')

            try:
                with manager.locked(): manager.start(spec)
                workers.append(dict(manager.state['telnet_radius_workers']['PC1']))
                self.assertNotIn('PC1', manager.state.get('ssh_radius_workers', {}))
                listeners = manager.ns(0, 'ss', '-H', '-lnt').stdout
                self.assertIn('192.0.2.10:23', listeners); self.assertIn('127.0.0.1:' + str(PORT), listeners)
                self.assertNotIn(':22 ', listeners); self.assertNotIn('127.0.0.1:813', listeners)
                # Keep the actual login process before credential input and inspect its privileges.
                future = pool.submit(telnet, ready=str(root / 'ready'), release=str(root / 'release'), disconnect=True)
                until = time.monotonic() + 5
                while not (root / 'ready').exists() and time.monotonic() < until: time.sleep(.05)
                self.assertTrue((root / 'ready').exists(), 'Telnet helper did not reach the pre-auth action prompt')
                rows = manager.crun('exec', 'PC1', '/bin/busybox', 'ps', '-o', 'pid,args').stdout.splitlines()
                pids = [row.split()[0] for row in rows if LOGIN in row and 'telnetd' not in row]
                self.assertEqual(len(pids), 1, 'Expected one actual Telnet login helper')
                status = manager.crun('exec', 'PC1', '/bin/cat', '/proc/' + pids[0] + '/status').stdout
                fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
                self.assertEqual(fields['Uid'].split(), ['65532'] * 4); self.assertEqual(fields['Gid'].split(), ['65532'] * 4)
                self.assertEqual(fields['Groups'].strip(), ''); self.assertEqual(fields['NoNewPrivs'].strip(), '1')
                for key in ('CapEff', 'CapPrm', 'CapInh', 'CapBnd', 'CapAmb'): self.assertEqual(int(fields[key].strip(), 16), 0)
                (root / 'release').touch(); future.result(timeout=5)
                # A real successful request establishes that the packet capture can see RADIUS.
                event = threading.Event(); future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', root / 'allowed.pcap',
                    seconds=2, packets=100, expression='udp port 1812', ready=event.set)
                self.assertTrue(event.wait(5)); self.assertIn('uid=65532', telnet())
                self.assertGreater(future.result(timeout=5)['captured_packets'], 0)
                positives()
                with manager.locked():
                    backend = probe(manager, 'PC1', '192.0.2.20', username='backend-only', password=password, secret=secret, timeout=2)
                self.assertEqual(backend['authentication']['decision'], 'accepted')
                event = threading.Event(); future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', root / 'denied.pcap',
                    seconds=5, packets=100, expression='udp port 1812 or udp port 1813', ready=event.set)
                self.assertTrue(event.wait(5)); started = time.monotonic()
                denied(action='security-context', username='viewer'); denied(action='hostname')
                denied(username='backend-only'); denied(action='identity; /bin/touch /tmp/telnet-bypass')
                self.assertLess(time.monotonic() - started, 5)
                self.assertEqual(future.result(timeout=7)['captured_packets'], 0)
                denied(credential='incorrect-password'); denied(username='unknown')
                self.assertNotEqual(manager.crun('exec', 'PC1', '/bin/busybox', 'test', '-e', '/tmp/telnet-bypass', check=False).returncode, 0)
                report = manager.inspect('PC1')['management']; self.assertTrue(report['configuration_verified'], report)
                self.assertTrue(report['telnet_radius_worker_available']); self.assertTrue(report['telnet_radius'])
                files = (manager.directory / 'PC1' / 'files' / 'management.json')
                original = files.read_text(); files.write_text('{}\n')
                with manager.locked(), self.assertRaises(RuntimeFailure): manager.write_startup()
                files.write_text(original)
                observed = manager.inspect('PC2')['radius_server']
                manager.crun('exec', 'PC2', '/bin/busybox', 'kill', '-TERM', str(observed['process']['pid'])); wait_listener(False)
                denied(); self.assertIn('192.0.2.10:23', manager.ns(0, 'ss', '-H', '-lnt').stdout)
                with manager.locked(): start_servers(manager)
                wait_listener(); self.assertIn('uid=65532', telnet())
                with manager.locked(): stop_worker(manager, 'PC1', transport='telnet')
                self.assertFalse(alive(workers[-1])); denied()
                protected = manager.ns(0, 'setpriv', '--reuid', '65532', '--regid', '65532', '--clear-groups', '/usr/bin/python3', '-I', '-c',
                    "import socket;s=socket.socket();\ntry:s.bind(('127.0.0.1',814))\nexcept PermissionError:print('protected')\nelse:raise SystemExit(99)", check=False, timeout=3)
                self.assertEqual(protected.returncode, 0); self.assertEqual(protected.stdout.strip(), 'protected')
                # Restart only through declarative lifecycle; stale bridge generations cannot be borrowed.
                with manager.locked():
                    manager.write_startup(); saved = load_startup(spec['name']); manager.stop(); manager.start(saved)
                workers.append(dict(manager.state['telnet_radius_workers']['PC1']))
                self.assertNotEqual(workers[0]['token'], workers[-1]['token']); self.assertTrue(saved['nodes'][0]['management']['telnet_radius'])
                self.assertEqual(saved['nodes'][0]['management']['telnet_password_hash'], '')
                positives(); denied(action='security-context', username='viewer')
                log = (manager.directory / 'PC1.telnet-radius.log').read_text()
                self.assertNotIn(password, log); self.assertNotIn(secret, log)
                cmdline = Path('/proc/' + str(workers[-1]['pid']) + '/cmdline').read_text()
                self.assertNotIn(password, cmdline); self.assertNotIn(secret, cmdline)
                config = (manager.directory / 'PC1.telnet-radius-config.json').read_text()
                self.assertNotIn(password, config); self.assertNotIn(secret, config)
            finally:
                (root / 'release').touch()
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        self.assertTrue(all(not alive(record) for record in workers))
        self.assertEqual(run(['ip', 'netns', 'list']).stdout, namespaces)
        self.assertEqual(Path('/proc/sys/net/ipv4/ip_unprivileged_port_start').read_text(), host_policy)
        for (fam, kind), value in baseline.items():
            self.assertEqual(run(['ip', '-j', fam, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, value)
        after = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        hardware = {n for n, _ in after - before if (Path('/sys/class/net') / n / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before, after, hardware), {'removed_or_replaced': set(), 'added_virtual': set()})
