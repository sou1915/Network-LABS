"""Real TCP framing, collector allowlist, outage/restart and declarative restore."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from network_labs.appliances.capture import capture
from network_labs.appliances.examples import syslog_tcp_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.spec import validate
from network_labs.appliances.syslog_send import send, frame
from network_labs.appliances.syslog_server import LOG, start_server
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeSyslogTCPTests(unittest.TestCase):
    def test_framing_rejection_rotation_outage_and_saved_restart(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('busybox', 'rsyslogd', 'crun', 'ip', 'tcpdump'): self.assertIsNotNone(shutil.which(tool), tool)
        baseline = {kind: run(['ip', '-j', '-4', kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout for kind in ('route', 'rule')}
        namespaces = run(['ip', 'netns', 'list']).stdout
        before = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            root = Path(folder)
            rootfs = static_busybox_rootfs(shutil.which('busybox'), root / 'rootfs', rsyslog=shutil.which('rsyslogd'), rsyslog_tcp=True)
            spec = syslog_tcp_lab(rootfs); spec['name'] = 'syslog-tcp-' + str(os.getpid())
            rogue = copy.deepcopy(spec['nodes'][2]); rogue.update(name='PC3', interfaces={'eth0': '192.0.2.30/24'})
            spec['nodes'].append(rogue); spec['nodes'][1]['interfaces']['eth2'] = ''; spec['links'].append([['SW1', 'eth2'], ['PC3', 'eth0']]); spec = validate(spec)
            manager = Manager(spec['name'])
            def logs(path=LOG): return manager.crun('exec', 'PC1', '/bin/busybox', 'cat', path, check=False).stdout
            def wait(predicate, label, seconds=8):
                until = time.monotonic() + seconds
                while time.monotonic() < until:
                    if predicate(): return
                    time.sleep(.1)
                self.fail(label + ': ' + (manager.directory / 'PC1/syslog-server.log').read_text(errors='replace'))
            def ready():
                wait(lambda: '192.0.2.10:514' in manager.ns(0, 'ss', '-H', '-ltn', 'sport = :514').stdout, 'TCP listener not ready')
                self.assertEqual(manager.ns(0, 'ss', '-H', '-lun', 'sport = :514').stdout, '', 'TCP profile must not silently listen on UDP')
            def wire(payload, chunks=False):
                script = "import socket,sys,time; s=socket.create_connection(('192.0.2.10',514),3); p=sys.stdin.buffer.read(); "
                script += "\nfor i in range(0,len(p),7): s.sendall(p[i:i+7]); time.sleep(.001)\n" if chunks else 's.sendall(p); '
                script += '\ns.close()'
                manager.ns(2, sys.executable, '-I', '-c', script, input_text=payload, timeout=5)
            try:
                with manager.locked(): manager.start(spec)
                ready(); state = copy.deepcopy(manager.read())
                event = threading.Event(); pcap = root / 'syslog-tcp.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', pcap, seconds=6, packets=1000, expression='tcp port 514', ready=event.set)
                self.assertTrue(event.wait(5))
                with manager.locked():
                    result = send(manager, 'PC2', 'PC1', 'TCP-STORED-OK'); self.assertEqual(result['status'], 'passed', result)
                    denied = send(manager, 'PC3', 'PC1', 'TCP-ROGUE-MUST-DROP'); self.assertEqual(denied['status'], 'unknown', denied)
                    self.assertTrue(denied['transmitted']); self.assertFalse(denied['collector_observed'])
                    wire(frame('<133>FRAMED-FIRST') + frame('<133>FRAMED-SECOND'), chunks=True)
                    wire('<133>LF-FRAMED-OK\n')
                    wait(lambda: all(t in logs() for t in ('FRAMED-FIRST', 'FRAMED-SECOND', 'LF-FRAMED-OK')), 'Stream framing lost messages')
                    self.assertNotIn(denied['token'], logs()); self.assertEqual(manager.read(), state)
                future.result(timeout=10)
                self.assertIn(b'TCP-STORED-OK', pcap.read_bytes()); self.assertIn(b'TCP-ROGUE-MUST-DROP', pcap.read_bytes())
                for token in ('FRAMED-FIRST', 'FRAMED-SECOND', 'LF-FRAMED-OK'): self.assertEqual(logs().count(token), 1)
                wire(''.join(frame('<133>ROTATE-' + str(i) + '-' + 'x'*800) for i in range(180)))
                wait(lambda: bool(logs(LOG + '.1')), 'TCP logs did not rotate')
                backup = manager.crun('exec', 'PC1', '/bin/busybox', 'wc', '-c', LOG + '.1').stdout
                self.assertTrue(60000 < int(backup.split()[0]) < 80000, backup)
                with manager.locked():
                    config = manager.directory / 'PC1/files/syslog-server.conf'; original = config.read_text(); config.write_text(original + '# drift\n')
                    with self.assertRaises(RuntimeFailure): manager.write_startup()
                    config.write_text(original)
                    manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/rsyslogd.pid)"')
                    wait(lambda: not manager.ns(0, 'ss', '-H', '-ltn', 'sport = :514').stdout, 'Stopped TCP collector still listens')
                    failed = send(manager, 'PC2', 'PC1', 'DOWN-MUST-NOT-PASS'); self.assertEqual(failed['status'], 'failed', failed)
                    self.assertTrue(manager.inspect('PC1')['syslog_server']['configuration_verified'])
                    start_server(manager, spec['nodes'][0]); ready()
                    self.assertEqual(send(manager, 'PC2', 'PC1', 'RESTART-OK')['status'], 'passed')
                    manager.write_startup(); saved = load_startup(spec['name']); self.assertEqual(saved, spec); manager.stop(); manager.start(saved)
                    ready(); self.assertNotIn('RESTART-OK', logs()); self.assertEqual(logs(LOG + '.1'), '')
                    self.assertEqual(send(manager, 'PC2', 'PC1', 'RESTORE-OK')['status'], 'passed'); manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        self.assertEqual(run(['ip', 'netns', 'list']).stdout, namespaces)
        for kind, value in baseline.items(): self.assertEqual(run(['ip', '-j', '-4', kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, value)
        after = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        hardware = {n for n, _ in after - before if (Path('/sys/class/net') / n / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before, after, hardware), {'removed_or_replaced': set(), 'added_virtual': set()})
