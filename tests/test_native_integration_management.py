"""Opt-in real OCI boot/packet tests. Appliance management on real containers: SSH and Telnet logins, SNMP v2c and v3
(traps, informs), the syslog collector.

Run as test_native_integration says (NETWORK_LABS_NATIVE_TESTS=1, on a disposable Linux host with sudo).
"""
import os
import json
import sys
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs

from test_native_integration import NATIVE, RealContainerCase


@unittest.skipUnless(NATIVE, 'Opt-in privileged native test')
class ManagementTests(RealContainerCase):
    def test_appliance_aa_admin_ssh_telnet_auth_syslog_capture_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.examples import management_lab
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.management import start_service
        from network_labs.appliances.firewall import fingerprint
        self.assertIsNotNone(shutil.which('dropbear'), 'Install dropbear-bin for native SSH tests')
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        baseline = {(family, kind): run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for family in ('-4', '-6') for kind in ('route', 'rule')}
        forwarding = {key: run(['sysctl', '-n', key]).stdout for key in ('net.ipv4.ip_forward', 'net.ipv6.conf.all.forwarding')}
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            folder = Path(folder)
            key = folder / 'identity'
            wrong = folder / 'wrong'
            for path in (key, wrong):
                run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', path])
            password = 'native-lab-test-password'
            password_hash = run(['openssl', 'passwd', '-6', '-salt', 'NetworkLABS', password]).stdout.strip()
            rootfs = static_busybox_rootfs(shutil.which('busybox'), folder / 'rootfs', dropbear=shutil.which('dropbear'))
            spec = management_lab(rootfs, key.with_suffix('.pub').read_text().strip(), password_hash)
            spec['name'] = 'management-' + str(os.getpid())
            manager = Manager(spec['name'])
            known = folder / 'known_hosts'
            client = Path(__file__).with_name('management_client_worker.py')
            def trust_host():
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    result = manager.ns(0, 'ssh-keyscan', '-T', '2', '-t', 'ed25519', '192.0.2.20', check=False, timeout=4)
                    if result.returncode == 0 and 'ssh-ed25519' in result.stdout:
                        known.write_text(result.stdout)
                        return
                    time.sleep(.2)
                log = manager.directory / 'R1/ssh.log'
                self.fail('SSH not ready: ' + (log.read_text(errors='replace') if log.exists() else 'missing log'))
            def ssh(command, identity=key, tty=False, check=True):
                try:
                    return ssh_once(command, identity, tty, check)
                except Exception as error:
                    # The client runs at LogLevel=ERROR; the server log names the actual refusal.
                    log = manager.directory / 'R1/ssh.log'
                    error.add_note('R1 ssh.log: ' + (log.read_text(errors='replace')[-3000:] if log.exists() else 'missing'))
                    again = ssh_once(command, identity, tty, False, verbose=True)
                    error.add_note(f'verbose retry exit {again.returncode}, stdout {again.stdout[-400:]!r}, stderr tail: ' + again.stderr[
                            -3500:])
                    raise
            def ssh_once(command, identity, tty, check, verbose=False):
                return manager.ns(0, 'ssh', *(['-vvv'] if verbose else []), '-F', '/dev/null', '-o', 'BatchMode=yes', '-o',
                                  'IdentitiesOnly=yes',
                                  '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
                                  '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'ConnectTimeout=3', '-o', 'LogLevel=ERROR',
                                  '-i', str(identity), *(['-tt'] if tty else ['-T']), 'lab@192.0.2.20', command,
                                  timeout=8, check=check)
            def client_request(mode, request):
                return manager.ns(0, sys.executable, '-I', str(client), mode, json.dumps(request), timeout=16)
            def sessions():
                result = ssh('/bin/busybox id -u; /bin/hostname; /bin/echo SSH-COMMAND-OK')
                self.assertIn('65532', result.stdout.splitlines())
                self.assertIn('R1', result.stdout.splitlines())
                self.assertIn('SSH-COMMAND-OK', result.stdout)
                self.assertIn('SSH-PTY-OK', ssh('/bin/busybox test -t 0 && /bin/echo SSH-PTY-OK', tty=True).stdout)
                text = json.loads(client_request('telnet', {'address': '192.0.2.20', 'password': password}).stdout)['output']
                self.assertIn('TELNET-SESSION-OK', text)
                self.assertIn('\n65532', text)
                self.assertIn('\nR1', text)
            def receive_log(token):
                ready = folder / ('ready-' + token)
                future = pool.submit(client_request, 'syslog', {'address': '192.0.2.10', 'ready': str(ready), 'token': token})
                deadline = time.monotonic() + 4
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(ready.exists(), 'Syslog UDP test receiver not ready')
                manager.crun('exec', 'R1', '/bin/busybox', 'logger', '-p', 'local0.notice', '-t', 'network-labs', token)
                rows = json.loads(future.result(timeout=10).stdout)
                found = [r for r in rows if token in r['text']]
                self.assertTrue(found, rows)
                self.assertEqual(found[0]['source'], '192.0.2.20')
                self.assertTrue(found[0]['text'].startswith('<133>'), found)
                self.assertIn(token, manager.crun('exec', 'R1', '/bin/busybox', 'tail', '-n', '20', '/run/messages').stdout)
            try:
                with manager.locked():
                    manager.start(spec)
                    trust_host()
                    sessions()
                event = threading.Event()
                pcap = folder / 'management.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'R1', 'eth0', pcap,
                                     seconds=10, packets=1000, expression='tcp port 22 or tcp port 23 or udp port 514', ready=event.set)
                self.assertTrue(event.wait(5), 'Management capture not ready')
                with manager.locked():
                    sessions()
                    receive_log('SYSLOG-WIRE-OK')
                self.assertGreater(future.result(timeout=13)['captured_packets'], 0)
                raw = pcap.read_bytes()
                self.assertIn(b'SSH-2.0-dropbear', raw)
                self.assertNotIn(b'SSH-COMMAND-OK', raw)
                self.assertIn(b'TELNET-SESSION-OK', raw)
                self.assertIn(b'SYSLOG-WIRE-OK', raw)
                self.assertIn(b'<133>', raw)
                with manager.locked():
                    before = json.loads(json.dumps(manager.read()))
                    rejected = ssh('/bin/echo SHOULD-NOT-RUN', identity=wrong, check=False)
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertIn('Permission denied', rejected.stderr)
                    self.assertNotIn('SHOULD-NOT-RUN', rejected.stdout)
                    self.assertTrue(json.loads(client_request('telnet', {'address': '192.0.2.20', 'password': 'wrong-password',
                                                                         'reject': True}).stdout)['rejected'])
                    keyfile = manager.directory / 'R1/files/authorized_keys'
                    contents = keyfile.read_text()
                    keyfile.write_text('')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    self.assertNotEqual(ssh('/bin/echo SHOULD-NOT-RUN', check=False).returncode, 0)
                    keyfile.write_text(contents)
                    sessions()
                    self.assertTrue(manager.inspect('R1')['management']['configuration_verified'])
                    manager.crun('exec', 'R1', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/dropbear.pid)"')
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if ssh('/bin/echo STOPPED', check=False).returncode != 0:
                            break
                        time.sleep(.1)
                    else: self.fail('SSH still accepts sessions after daemon stop')
                    self.assertTrue(manager.inspect('R1')['management']['configuration_verified'], 'File conformity is not liveness')
                    start_service(manager, manager.read()['spec']['nodes'][2], 'ssh')
                    trust_host()
                    sessions()
                    self.assertEqual(manager.read(), before)
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertEqual(saved['nodes'][2]['management']['telnet_password_hash'], password_hash)
                    self.assertNotIn(password, json.dumps(saved))
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    trust_host()
                    sessions()
                    receive_log('SYSLOG-RESTORE-OK')
                    manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        for (family, kind), expected in baseline.items():
            self.assertEqual(run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, expected)
        for key, expected in forwarding.items():
            self.assertEqual(run(['sysctl', '-n', key]).stdout, expected)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)

    def test_appliance_aa_agent_snmp_link_events_real_interfaces_security_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import re
        from network_labs.appliances.examples import snmp_links_lab
        from network_labs.appliances.snmp import usm_credentials, client_config, start_server
        from network_labs.appliances.snmp_links import UP, DOWN, TABLE, INTERNAL, FILTER
        from network_labs.appliances.snmp_notifications import LOG
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.capture import capture
        from network_labs.appliances.firewall import fingerprint
        from snmp_wire import captured_v3
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        baseline = {(family, kind): run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for family in ('-4', '-6') for kind in ('route', 'rule')}
        forwarding = {key: run(['sysctl', '-n', key]).stdout for key in ('net.ipv4.ip_forward', 'net.ipv6.conf.all.forwarding')}
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            folder = Path(folder)
            user = usm_credentials('monitor', 'native-link-auth', 'native-link-privacy')
            rootfs = static_busybox_rootfs(shutil.which('busybox'), folder / 'rootfs', snmpd=shutil.which('snmpd'),
                                           snmptrapd=shutil.which('snmptrapd'))
            directory = folder / 'client'
            directory.mkdir(mode=0o700)
            path = directory / 'snmp.conf'
            path.write_text(client_config(user))
            path.chmod(0o600)
            for mode in ('trap', 'inform'):
                spec = snmp_links_lab(rootfs, user, mode)
                spec['name'] = 'links-' + mode + '-' + str(os.getpid())
                manager = Manager(spec['name'])
                def logs():
                    return manager.crun('exec', 'PC1', '/bin/busybox', 'cat', LOG, check=False).stdout
                def wait_event(oid, minimum=1):
                    deadline = time.monotonic() + 18
                    while time.monotonic() < deadline:
                        rows = [row for row in logs().splitlines() if 'OID: ' + oid in row]
                        if len(rows) >= minimum:
                            return rows[-1]
                        time.sleep(.2)
                    log = manager.directory / 'R1/snmp.log'
                    self.fail('Missing native link event ' + oid + ': ' + logs() + (log.read_text(errors='replace')[-4000:]
                                                                                    if log.exists() else ''))
                def query(oid, source=0, extra=()):
                    return manager.ns(source, 'env', 'SNMPCONFPATH=' + str(directory), 'snmpget', '-m', '', '-t', '1', '-r', '0',
                                      '-Oqv', *extra, '192.0.2.20', oid, check=False, timeout=4)
                def state(up):
                    manager.ns(2, 'ip', 'link', 'set', 'dev', 'eth1', 'up' if up else 'down')
                def payload(row, index, admin, oper):
                    for column, value in (('1', index), ('7', admin), ('8', oper)):
                        self.assertRegex(row,
                                re.escape(TABLE + column + '.' + str(index)) + r' = INTEGER: (?:[A-Za-z]+\()?' + str(value)
                            + r'\)?(?:\s|$)')
                try:
                    with manager.locked():
                        manager.start(spec)
                        time.sleep(7)
                        self.assertNotIn('OID: ' + UP, logs())
                        self.assertNotIn('OID: ' + DOWN, logs())
                        index = json.loads(manager.ns(2, 'ip', '-j', 'link', 'show', 'dev', 'eth1').stdout)[0]['ifindex']
                        self.assertEqual(query(TABLE + '8.' + str(index)).stdout.strip(), '1')
                        # Same credentials from an IP-reachable unlisted manager
                        # must be denied by the owned-node UDP/161 source rule.
                        manager.crun('exec', 'PC3', '/bin/ping', '-c', '1', '-W', '2', '192.0.2.20')
                        self.assertNotEqual(query(TABLE + '8.' + str(index), source=4).returncode, 0)
                        for level in ('noAuthNoPriv', 'authNoPriv', 'authPriv'):
                            rejected = query(TABLE + '8.' + str(index), extra=('-u', INTERNAL, '-l', level))
                            self.assertTrue(rejected.returncode != 0 or 'No Such' in rejected.stdout)
                        report = manager.inspect('R1')['snmp_agent']
                        self.assertTrue(report['configuration_verified'])
                        self.assertEqual(report['link_events']['provisioned_indices'], {'eth1': index})
                    event = threading.Event()
                    pcap = folder / (mode + '.pcap')
                    future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', pcap, seconds=40, packets=1000,
                                         expression='udp port 162', ready=event.set)
                    self.assertTrue(event.wait(5))
                    with manager.locked():
                        state(False)
                        payload(wait_event(DOWN), index, 2, 2)
                        count = logs().count('OID: ' + DOWN)
                        time.sleep(5)
                        self.assertEqual(logs().count('OID: ' + DOWN), count, 'Stable sampled state must not repeatedly fire')
                        state(True)
                        payload(wait_event(UP), index, 1, 1)
                        manager.crun('exec', 'PC2', '/bin/ping', '-c', '1', '-W', '2', '198.51.100.1')
                    self.assertGreater(future.result(timeout=45)['captured_packets'], 0)
                    packets = captured_v3(pcap.read_bytes(), port=162)
                    requests = [p for p in packets if p['target_port'] == 162 and p['flags'] & 3 == 3]
                    self.assertGreaterEqual(len(requests), 2)
                    for packet in requests:
                        self.assertEqual(packet['data_tag'], 4)
                        self.assertEqual(packet['auth_length'], 24)
                        self.assertEqual(packet['privacy_length'], 8)
                    if mode == 'trap':
                        self.assertFalse(any(p['source_port'] == 162 for p in packets))
                    else:
                        for request in requests:
                            self.assertTrue(any(p['source_port'] == 162 and p['target_port'] == request['source_port'] and
                                                p['message_id'] == request['message_id'] and p['flags'] & 3 == 3 for p in packets))
                    with manager.locked():
                        config = manager.directory / 'R1/files/snmp-link-events.conf'
                        original = config.read_text()
                        config.write_text(original + '# drift\n')
                        with self.assertRaises(RuntimeFailure):
                            manager.write_startup()
                        before = json.dumps(manager.read(), sort_keys=True)
                        with self.assertRaises(RuntimeFailure):
                            start_server(manager, spec['nodes'][2])
                        self.assertEqual(json.dumps(manager.read(), sort_keys=True), before)
                        config.write_text(original)
                        # A daemon stop is not a link event. A stopped monitor
                        # cannot report changes, even if its files still match.
                        manager.crun('exec', 'R1', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/snmpd.pid)"')
                        deadline = time.monotonic() + 5
                        while manager.ns(2, 'ss', '-H', '-lun', 'sport = :161').stdout:
                            if time.monotonic() >= deadline:
                                self.fail('Old monitored agent still listens')
                            time.sleep(.05)
                        count = logs().count('OID: ' + DOWN)
                        state(False)
                        time.sleep(4)
                        self.assertEqual(logs().count('OID: ' + DOWN), count)
                        self.assertTrue(manager.inspect('R1')['snmp_agent']['configuration_verified'])
                        state(True)
                        start_server(manager, spec['nodes'][2])
                        time.sleep(7)
                        self.assertEqual(logs().count('OID: ' + DOWN), count)
                        manager.write_startup()
                        saved = load_startup(spec['name'])
                        for field in ('snmp_link_indices', 'snmp_link_filters'):
                            self.assertNotIn(field, saved)
                        # Structural changes to the managed source table are
                        # detected even when no packet counters are involved.
                        manager.ns(2, 'nft', 'add', 'rule', 'inet', FILTER, 'input', 'ip', 'saddr', '192.0.2.10', 'counter')
                        with self.assertRaises(RuntimeFailure):
                            manager.write_startup()
                        manager.stop()
                    manager = Manager(spec['name'])
                    with manager.locked():
                        manager.start(saved)
                        time.sleep(7)
                        self.assertNotIn('OID: ' + UP, logs())
                        self.assertNotIn('OID: ' + DOWN, logs())
                        index = json.loads(manager.ns(2, 'ip', '-j', 'link', 'show', 'dev', 'eth1').stdout)[0]['ifindex']
                        self.assertEqual(manager.inspect('R1')['snmp_agent']['link_events']['provisioned_indices'], {'eth1': index})
                        state(False)
                        payload(wait_event(DOWN), index, 2, 2)
                        state(True)
                        payload(wait_event(UP), index, 1, 1)
                        manager.write_startup()
                finally:
                    if manager.directory.exists():
                        with manager.locked():
                            manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        for (family, kind), expected in baseline.items():
            self.assertEqual(run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, expected)
        for key, expected in forwarding.items():
            self.assertEqual(run(['sysctl', '-n', key]).stdout, expected)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)

    def test_appliance_aa_agent_snmp_notifications_trap_inform_ack_loss_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import copy
        import threading
        from network_labs.appliances.examples import snmp_notifications_lab
        from network_labs.appliances.snmp import start_server
        from network_labs.appliances.snmp_notifications import start_trapd, LOG, HEARTBEAT, HEARTBEAT_RATE, HEARTBEAT_NAME, client_config
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.capture import capture
        from network_labs.appliances.firewall import fingerprint
        from snmp_wire import captured_notifications
        self.assertIsNotNone(shutil.which('snmptrapd'), 'Install snmptrapd for native notification tests')
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        baseline = {(family, kind): run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for family in ('-4', '-6') for kind in ('route', 'rule')}
        forwarding = {key: run(['sysctl', '-n', key]).stdout for key in ('net.ipv4.ip_forward', 'net.ipv6.conf.all.forwarding')}
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            folder = Path(folder)
            rootfs = static_busybox_rootfs(shutil.which('busybox'), folder / 'rootfs', snmpd=shutil.which('snmpd'),
                                           snmptrapd=shutil.which('snmptrapd'))
            for mode in ('trap', 'inform'):
                spec = snmp_notifications_lab(rootfs, mode)
                spec['name'] = 'notify-' + mode + '-' + str(os.getpid())
                manager = Manager(spec['name'])
                cold = '.1.3.6.1.6.3.1.1.5.1'
                clients = {}
                for label, text in {'good': client_config(spec['nodes'][2]),
                                    'bad': client_config(spec['nodes'][2]).replace('network-labs-notify', 'wrong-notify-token'),
                                    'rogue': client_config(spec['nodes'][2]).replace('192.0.2.20', '192.0.2.30')}.items():
                    directory = folder / (mode + '-' + label)
                    directory.mkdir(mode=0o700)
                    path = directory / 'snmp.conf'
                    path.write_text(text)
                    path.chmod(0o600)
                    clients[label] = directory
                def logs():
                    return manager.crun('exec', 'PC1', '/bin/busybox', 'cat', LOG, check=False).stdout
                def received(token, minimum=1):
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        text = logs()
                        if text.count(token) >= minimum:
                            return text
                        time.sleep(.1)
                    log = manager.directory / 'PC1/snmptrapd.log'
                    self.fail('Notification not logged: ' + token + ': ' + logs() + (log.read_text(errors='replace') if log.exists()
                                                                                     else ''))
                def send(token, *, inform=False, label='good', retries=0):
                    return manager.ns(4 if label == 'rogue' else 2, 'env', 'SNMPCONFPATH=' + str(clients[label]),
                                      'snmptrap', '-m', '', '-t', '1', '-r', str(retries), *(['-Ci'] if inform else []),
                                      '192.0.2.10', '0', HEARTBEAT, HEARTBEAT_RATE, 'i', '30', HEARTBEAT_NAME, 's', token, check=False,
                        timeout=5)
                def loss(chain):
                    manager.ns(0, 'nft', 'add', 'table', 'inet', 'nlab_notification_loss')
                    manager.ns(0, 'nft', 'add', 'chain', 'inet', 'nlab_notification_loss', chain,
                               '{ type filter hook ' + chain + ' priority -5; policy accept; }')
                    manager.ns(0, 'nft', 'add', 'rule', 'inet', 'nlab_notification_loss', chain,
                               'udp', 'dport' if chain == 'input' else 'sport', '162', 'drop')
                try:
                    with manager.locked():
                        manager.start(spec)
                        received(cold)
                    event = threading.Event()
                    pcap = folder / (mode + '.pcap')
                    future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', pcap,
                                         seconds=20, packets=1000, expression='udp port 162', ready=event.set)
                    self.assertTrue(event.wait(5), 'Notification capture not ready')
                    with manager.locked():
                        before = copy.deepcopy(manager.read())
                        previous = logs().count(cold)
                        manager.crun('exec', 'R1', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/snmpd.pid)"')
                        deadline = time.monotonic() + 5
                        while manager.ns(2, 'ss', '-H', '-lun', 'sport = :161').stdout:
                            if time.monotonic() >= deadline:
                                self.fail('Old agent still listens')
                            time.sleep(.05)
                        start_server(manager, spec['nodes'][2])
                        received(cold, previous + 1)
                        self.assertEqual(send('TRAP-OK').returncode, 0)
                        received('TRAP-OK')
                        self.assertEqual(send('INFORM-OK', inform=True).returncode, 0)
                        received('INFORM-OK')
                        self.assertNotEqual(send('WRONG-COMMUNITY', inform=True, label='bad').returncode, 0)
                        manager.crun('exec', 'PC3', '/bin/ping', '-c', '1', '-W', '2', '192.0.2.10')
                        self.assertNotEqual(send('WRONG-SOURCE', inform=True, label='rogue').returncode, 0)
                        self.assertNotIn('WRONG-COMMUNITY', logs())
                        self.assertNotIn('WRONG-SOURCE', logs())
                        loss('input')
                        self.assertEqual(send('DROP-TRAP').returncode, 0)
                        self.assertNotEqual(send('DROP-INFORM', inform=True, retries=1).returncode, 0)
                        self.assertNotIn('DROP-TRAP', logs())
                        self.assertNotIn('DROP-INFORM', logs())
                        manager.ns(0, 'nft', 'delete', 'table', 'inet', 'nlab_notification_loss')
                        loss('output')
                        self.assertNotEqual(send('LOST-ACK', inform=True, retries=1).returncode, 0)
                        received('LOST-ACK')
                        manager.ns(0, 'nft', 'delete', 'table', 'inet', 'nlab_notification_loss')
                        self.assertEqual(manager.read(), before)
                    self.assertGreater(future.result(timeout=23)['captured_packets'], 0)
                    rows = captured_notifications(pcap.read_bytes())
                    def requests(token):
                        return [r for r in rows if r['target_port'] == 162 and token.encode() in r['varbinds']]
                    def replies(request):
                        return [r for r in rows if r['source_port'] == 162 and r['target_port'] == request['source_port']
                                and r['request_id'] == request['request_id'] and r['pdu_tag'] == 0xa2]
                    trap = requests('TRAP-OK')
                    self.assertEqual(len(trap), 1)
                    self.assertEqual(trap[0]['pdu_tag'], 0xa7)
                    self.assertFalse(replies(trap[0]))
                    informs = requests('INFORM-OK')
                    self.assertTrue(informs)
                    self.assertEqual(informs[0]['pdu_tag'], 0xa6)
                    self.assertTrue(replies(informs[0]))
                    self.assertTrue(all(r['error_status'] == 0 for r in replies(informs[0])))
                    for token in ('DROP-INFORM', 'LOST-ACK'):
                        attempts = requests(token)
                        self.assertEqual(len(attempts), 2)
                        self.assertEqual(len({r['request_id'] for r in attempts}), 1)
                        self.assertFalse(replies(attempts[0]))
                    self.assertTrue(requests('WRONG-COMMUNITY'))
                    self.assertTrue(requests('WRONG-SOURCE'))
                    self.assertEqual(requests('WRONG-SOURCE')[0]['source_ip'], '192.0.2.30')
                    starts = [r for r in rows if r['target_port'] == 162 and bytes.fromhex('06092b0601060301010501') in r['varbinds']]
                    self.assertTrue(starts)
                    self.assertEqual(starts[0]['source_ip'], '192.0.2.20')
                    self.assertEqual(starts[0]['pdu_tag'], 0xa7 if mode == 'trap' else 0xa6)
                    if mode == 'inform':
                        self.assertTrue(replies(starts[0]))
                    with manager.locked():
                        # The underlying authCommunity policy also accepts legacy
                        # v1 notifications; polling v1 access remains unchanged.
                        legacy = manager.ns(2, 'env', 'SNMPCONFPATH=' + str(clients['good']), 'snmptrap', '-m', '', '-v1',
                                            '192.0.2.10', '.1.3.6.1.4.1.8072.2.3', '192.0.2.20', '6', '1', '0',
                                            HEARTBEAT_RATE, 'i', '30', HEARTBEAT_NAME, 's', 'LEGACY-V1-LOG', timeout=4)
                        self.assertEqual(legacy.returncode, 0)
                        received('LEGACY-V1-LOG')
                        burst = ['snmptrap', '-m', '', '192.0.2.10', '0', HEARTBEAT, HEARTBEAT_RATE, 'i', '30', HEARTBEAT_NAME, 's']
                        code = ("import os,subprocess,time; os.environ['SNMPCONFPATH']=" + repr(str(clients['good'])) + "; command="
                                + repr(burst) + "; ")
                        code += ("[(subprocess.run(command+['ROTATION-'+str(i)+'-'+('x'*180)],check=True,stdout=subprocess.DEVNULL,"
                                 "stderr=subprocess.PIPE),time.sleep(.002)) for i in range(400)]")
                        manager.ns(2, sys.executable, '-I', '-c', code, timeout=25)
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline:
                            backup = manager.crun('exec', 'PC1', '/bin/busybox', 'wc', '-c', LOG + '.0', check=False)
                            if backup.returncode == 0:
                                break
                            time.sleep(.1)
                        else: self.fail('Notification log did not rotate')
                        self.assertGreater(int(backup.stdout.split()[0]), 60000)
                        self.assertLess(int(backup.stdout.split()[0]), 80000)
                        config = manager.directory / 'PC1/files/snmp-receiver.conf'
                        original = config.read_text()
                        config.write_text(original + '# drift\n')
                        with self.assertRaises(RuntimeFailure):
                            manager.write_startup()
                        config.write_text(original)
                        manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/snmptrapd.pid)"')
                        deadline = time.monotonic() + 5
                        while manager.ns(0, 'ss', '-H', '-lun', 'sport = :162').stdout:
                            if time.monotonic() >= deadline:
                                self.fail('Stopped receiver still listens')
                            time.sleep(.05)
                        self.assertNotEqual(send('RECEIVER-DOWN', inform=True).returncode, 0)
                        self.assertTrue(manager.inspect('PC1')['snmp_receiver']['configuration_verified'])
                        start_trapd(manager, spec['nodes'][0], 0)
                        self.assertEqual(send('RECEIVER-RESTART-OK', inform=True).returncode, 0)
                        received('RECEIVER-RESTART-OK')
                        manager.write_startup()
                        saved = load_startup(spec['name'])
                        manager.stop()
                    manager = Manager(spec['name'])
                    with manager.locked():
                        manager.start(saved)
                        received(cold)
                        self.assertNotIn('RECEIVER-RESTART-OK', logs())
                        self.assertEqual(send('RESTORE-INFORM-OK', inform=True).returncode, 0)
                        received('RESTORE-INFORM-OK')
                        manager.write_startup()
                        self.assertEqual(saved['nodes'][2]['snmp_agent']['notifications']['mode'], mode)
                finally:
                    if manager.directory.exists():
                        with manager.locked():
                            manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        for (family, kind), expected in baseline.items():
            self.assertEqual(run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, expected)
        for key, expected in forwarding.items():
            self.assertEqual(run(['sysctl', '-n', key]).stdout, expected)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)

    def test_appliance_aa_agent_snmp_v3_traps_engine_binding_rotation_loss_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import copy
        import threading
        from network_labs.appliances.examples import snmpv3_traps_lab
        from network_labs.appliances.snmp import usm_credentials, start_server
        from network_labs.appliances.snmp_traps import wire_engine, stop_receiver
        from network_labs.appliances.snmp_notifications import start_trapd, LOG, HEARTBEAT, HEARTBEAT_RATE, HEARTBEAT_NAME
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        from snmp_wire import captured_v3
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        baseline = {(family, kind): run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for family in ('-4', '-6') for kind in ('route', 'rule')}
        forwarding = {key: run(['sysctl', '-n', key]).stdout for key in ('net.ipv4.ip_forward', 'net.ipv6.conf.all.forwarding')}
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            folder = Path(folder)
            auth, privacy = 'native-trap-auth', 'native-trap-privacy'
            user = usm_credentials('notify', auth, privacy)
            rootfs = static_busybox_rootfs(shutil.which('busybox'), folder / 'rootfs', snmpd=shutil.which('snmpd'),
                                           snmptrapd=shutil.which('snmptrapd'))
            spec = snmpv3_traps_lab(rootfs, user)
            spec['name'] = 'trap-v3-' + str(os.getpid())
            manager = Manager(spec['name'])
            spec['nodes'][2]['snmp_agent']['usm'] = usm_credentials('polling', 'native-poll-auth', 'native-poll-privacy')
            # Independent official clients derive keys from the fixture phrases.
            clear = '\n'.join(['defVersion 3', 'defSecurityLevel authPriv', 'defSecurityName notify', 'defAuthType SHA-256',
                                'defPrivType AES', 'defAuthPassphrase ' + auth, 'defPrivPassphrase ' + privacy, ''])
            clients = {}
            for label, text in {'good': clear, 'poll': clear.replace('Name notify', 'Name polling').replace(auth,
                    'native-poll-auth').replace(privacy, 'native-poll-privacy'), 'auth': clear.replace(auth, 'wrong-trap-auth'),
                                'privacy': clear.replace(privacy, 'wrong-trap-privacy'), 'user': clear.replace('Name notify',
                                                                                                               'Name unknown'),
                                'low': clear.replace('authPriv', 'authNoPriv'), 'none': clear.replace('authPriv', 'noAuthNoPriv')}.items():
                directory = folder / label
                directory.mkdir(mode=0o700)
                path = directory / 'snmp.conf'
                path.write_text(text)
                path.chmod(0o600)
                clients[label] = directory
            cold = '.1.3.6.1.6.3.1.1.5.1'
            def logs():
                return manager.crun('exec', 'PC1', '/bin/busybox', 'cat', LOG, check=False).stdout
            def received(token, minimum=1):
                deadline = time.monotonic() + 7
                while time.monotonic() < deadline:
                    if logs().count(token) >= minimum:
                        return
                    time.sleep(.1)
                log = manager.directory / 'PC1/snmptrapd.log'
                self.fail('USM trap not logged: ' + token + ': ' + logs() + (log.read_text(errors='replace') if log.exists() else ''))
            def token(name='R1'):
                return manager.state['snmp_trap_engines'][name]['token']
            def send(marker, *, name='R1', engine=None, label='good', source=None):
                # Fixture-only boots/time 1,1 is within the short live window;
                # it is not an observation or a generic manual-send recipe.
                index = source if source is not None else (2 if name == 'R1' else 5)
                return manager.ns(index, 'env', 'SNMPCONFPATH=' + str(clients[label]), 'snmptrap', '-m', '',
                                  '-e', '0x' + wire_engine(engine or token(name)), '-Z', '1,1', '192.0.2.10', '0', HEARTBEAT,
                                  HEARTBEAT_RATE, 'i', '30', HEARTBEAT_NAME, 's', marker, check=False, timeout=4)
            def stop_agent():
                manager.crun('exec', 'R1', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/snmpd.pid)"')
                deadline = time.monotonic() + 5
                while manager.ns(2, 'ss', '-H', '-lun', 'sport = :161').stdout:
                    if time.monotonic() >= deadline:
                        self.fail('Old trap agent still listens')
                    time.sleep(.05)
            def begin(label, seconds):
                event = threading.Event()
                path = folder / (label + '.pcap')
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', path,
                                     seconds=seconds, packets=1000, expression='udp port 162', ready=event.set)
                self.assertTrue(event.wait(5))
                return path, future
            def evidence(path, future):
                self.assertGreater(future.result(timeout=25)['captured_packets'], 0)
                rows = captured_v3(path.read_bytes(), port=162)
                self.assertTrue(rows)
                self.assertFalse(any(r['source_port'] == 162 for r in rows), 'Unconfirmed traps must not acquire an ACK/report')
                for row in rows:
                    if row['flags'] & 3 == 3:
                        self.assertEqual(row['flags'], 3)
                        self.assertEqual(row['auth_length'], 24)
                        self.assertEqual(row['privacy_length'], 8)
                        self.assertEqual(row['data_tag'], 4)
                for secret in (auth, privacy, user['auth_master_key'], user['privacy_master_key']):
                    self.assertNotIn(secret.encode(), path.read_bytes())
                return rows
            try:
                with manager.locked():
                    manager.start(spec)
                    received(cold, 2)
                    self.assertIn('192.0.2.20', logs())
                    self.assertIn('192.0.2.40', logs())
                    first, peer = token(), token('R2')
                    self.assertNotEqual(first, peer)
                    for label in ('poll', 'good'):
                        result = manager.ns(0, 'env', 'SNMPCONFPATH=' + str(clients[label]), 'snmpget', '-m', '',
                                            '-t', '1', '-r', '0', '-Oqv', '192.0.2.20', '.1.3.6.1.2.1.1.5.0', check=False, timeout=4)
                        if label == 'poll':
                            self.assertEqual(result.returncode, 0)
                            self.assertEqual(result.stdout.strip().strip('"'), 'R1')
                        else:
                            self.assertNotEqual(result.stdout.strip().strip('"'), 'R1')
                            self.assertTrue(result.returncode != 0 or 'No Such' in result.stdout)
                    before = copy.deepcopy(manager.read())
                    with self.assertRaises(RuntimeFailure):
                        start_server(manager, spec['nodes'][2])
                    self.assertEqual(manager.read(), before)
                path, future = begin('rotation-loss', 15)
                with manager.locked():
                    marker = 'PRIVATE-USM-TRAP-NOT-ON-WIRE'
                    self.assertEqual(send(marker).returncode, 0)
                    received(marker)
                    self.assertEqual(send('PEER-BEFORE', name='R2').returncode, 0)
                    received('PEER-BEFORE')
                    for label in ('auth', 'privacy', 'user', 'low', 'none'):
                        self.assertEqual(send('REJECT-' + label, label=label).returncode, 0)
                    self.assertEqual(send('UNKNOWN-ENGINE', engine='f' * 24).returncode, 0)
                    manager.crun('exec', 'PC3', '/bin/ping', '-c', '1', '-W', '2', '192.0.2.10')
                    self.assertEqual(send('WRONG-SOURCE', source=4).returncode, 0)
                    stop_agent()
                    config = manager.directory / 'PC1/files/snmp-trap-users.conf'
                    original = config.read_text()
                    config.write_text(original + '# drift\n')
                    before = copy.deepcopy(manager.read())
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    with self.assertRaises(RuntimeFailure):
                        start_server(manager, spec['nodes'][2])
                    self.assertEqual(manager.read(), before)
                    self.assertTrue(manager.ns(0, 'ss', '-H', '-lun', 'sport = :162').stdout)
                    config.write_text(original)
                    previous = logs().count(cold)
                    start_server(manager, spec['nodes'][2])
                    received(cold, previous + 1)
                    second = token()
                    self.assertNotEqual(second, first)
                    self.assertEqual(token('R2'), peer)
                    self.assertNotIn(wire_engine(first), config.read_text())
                    self.assertIn(wire_engine(peer), config.read_text())
                    self.assertEqual(send('RETIRED-ENGINE', engine=first).returncode, 0)
                    self.assertEqual(send('NEW-ENGINE-OK').returncode, 0)
                    received('NEW-ENGINE-OK')
                    self.assertEqual(send('PEER-PRESERVED', name='R2').returncode, 0)
                    received('PEER-PRESERVED')
                    manager.ns(0, 'nft', 'add', 'table', 'inet', 'nlab_trap_loss')
                    manager.ns(0, 'nft', 'add', 'chain', 'inet', 'nlab_trap_loss', 'input',
                               '{ type filter hook input priority -5; policy accept; }')
                    manager.ns(0, 'nft', 'add', 'rule', 'inet', 'nlab_trap_loss', 'input', 'udp', 'dport', '162', 'drop')
                    try:
                        self.assertEqual(send('DROPPED-TRAP').returncode, 0)
                        time.sleep(.3)
                        self.assertNotIn('DROPPED-TRAP', logs())
                    finally: manager.ns(0, 'nft', 'delete', 'table', 'inet', 'nlab_trap_loss')
                    self.assertEqual(send('RECOVERED-TRAP').returncode, 0)
                    received('RECOVERED-TRAP')
                    for rejected in ('auth', 'privacy', 'user', 'low', 'none'):
                        self.assertNotIn('REJECT-' + rejected, logs())
                    for rejected in ('UNKNOWN-ENGINE', 'WRONG-SOURCE', 'RETIRED-ENGINE'):
                        self.assertNotIn(rejected, logs())
                rows = evidence(path, future)
                for expected in (first, second, peer):
                    self.assertTrue(any(r['engine_id'].hex() == wire_engine(expected) for r in rows))
                self.assertTrue(any(r['source_ip'] == '192.0.2.40' for r in rows))
                self.assertTrue(any(r['source_ip'] == '192.0.2.30' for r in rows))
                self.assertNotIn(marker.encode(), path.read_bytes())
                with manager.locked():
                    # Receiver-only restart reloads current sender bindings;
                    # its own fresh identity is not authoritative for traps.
                    stop_receiver(manager, spec['nodes'][0], 0)
                    start_trapd(manager, spec['nodes'][0], 0)
                    self.assertEqual(send('RECEIVER-RESTART-R1').returncode, 0)
                    received('RECEIVER-RESTART-R1')
                    self.assertEqual(send('RECEIVER-RESTART-R2', name='R2').returncode, 0)
                    received('RECEIVER-RESTART-R2')
                    self.assertEqual(token(), second)
                    self.assertEqual(token('R2'), peer)
                    report = manager.inspect('PC1')['snmp_receiver']
                    self.assertTrue(report['configuration_verified'])
                    self.assertEqual(report['provisioned_trap_engines']['R1'], '0x' + wire_engine(second))
                    for key in (user['auth_master_key'], user['privacy_master_key']):
                        self.assertNotIn(key, json.dumps(report))
                    self.assertNotEqual(manager.ns(2, 'env', 'SNMPCONFPATH=' + str(clients['good']), 'snmptrap', '-m', '',
                                                   '-v2c', '-c', 'network-labs-notify', '-Ci', '-t', '1', '-r', '0', '192.0.2.10', '0',
                        HEARTBEAT,
                                                   HEARTBEAT_RATE, 'i', '30', HEARTBEAT_NAME, 's', 'COMMUNITY-FALLBACK', check=False,
                        timeout=4).returncode, 0)
                    self.assertNotIn('COMMUNITY-FALLBACK', logs())
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertNotIn('snmp_trap_engines', saved)
                    for value in (first, second, peer, auth, privacy, 'native-poll-auth', 'native-poll-privacy'):
                        self.assertNotIn(value, json.dumps(saved))
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    received(cold, 2)
                    self.assertNotIn('RECEIVER-RESTART-R1', logs())
                    third, new_peer = token(), token('R2')
                    self.assertNotIn(third, (first, second, peer))
                    self.assertNotEqual(new_peer, peer)
                path, future = begin('restore', 4)
                with manager.locked():
                    self.assertEqual(send('RESTORED-R1').returncode, 0)
                    received('RESTORED-R1')
                    self.assertEqual(send('RESTORED-R2', name='R2').returncode, 0)
                    received('RESTORED-R2')
                    self.assertEqual(send('OLD-LAB-ENGINE', engine=second).returncode, 0)
                    self.assertEqual(send('RESTORE-BARRIER').returncode, 0)
                    received('RESTORE-BARRIER')
                    self.assertNotIn('OLD-LAB-ENGINE', logs())
                rows = evidence(path, future)
                for expected in (third, new_peer):
                    self.assertTrue(any(r['engine_id'].hex() == wire_engine(expected) for r in rows))
                with manager.locked():
                    manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        for (family, kind), expected in baseline.items():
            self.assertEqual(run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, expected)
        for key, expected in forwarding.items():
            self.assertEqual(run(['sysctl', '-n', key]).stdout, expected)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)

    def test_appliance_aa_agent_snmp_v3_informs_privacy_loss_receiver_restart_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import copy
        import threading
        from network_labs.appliances.examples import snmpv3_informs_lab
        from network_labs.appliances.snmp import usm_credentials, start_server
        from network_labs.appliances.snmp_notifications import start_trapd, client_config, LOG, HEARTBEAT, HEARTBEAT_RATE, HEARTBEAT_NAME
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.capture import capture
        from network_labs.appliances.firewall import fingerprint
        from snmp_wire import captured_v3
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        baseline = {(family, kind): run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for family in ('-4', '-6') for kind in ('route', 'rule')}
        forwarding = {key: run(['sysctl', '-n', key]).stdout for key in ('net.ipv4.ip_forward', 'net.ipv6.conf.all.forwarding')}
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            folder = Path(folder)
            auth, privacy = 'native-notify-auth', 'native-notify-privacy'
            user = usm_credentials('notify', auth, privacy)
            rootfs = static_busybox_rootfs(shutil.which('busybox'), folder / 'rootfs', snmpd=shutil.which('snmpd'),
                                           snmptrapd=shutil.which('snmptrapd'))
            spec = snmpv3_informs_lab(rootfs, user)
            spec['name'] = 'inform-v3-' + str(os.getpid())
            manager = Manager(spec['name'])
            # Official client independently derives keys from fixture passphrases.
            clear = '\n'.join(['defVersion 3', 'defSecurityLevel authPriv', 'defSecurityName notify', 'defAuthType SHA-256',
                                'defPrivType AES', 'defAuthPassphrase ' + auth, 'defPrivPassphrase ' + privacy, 'clientaddr 192.0.2.20',
                ''])
            clients = {}
            for label, text in {'good': clear, 'master': client_config(spec['nodes'][2]),
                                'auth': clear.replace(auth, 'wrong-notify-auth'), 'privacy': clear.replace(privacy, 'wrong-notify-privacy'),
                                'user': clear.replace('Name notify', 'Name unknown'), 'low': clear.replace('authPriv', 'authNoPriv'),
                                'none': clear.replace('authPriv', 'noAuthNoPriv'), 'rogue': clear.replace('192.0.2.20',
                                                                                                          '192.0.2.30')}.items():
                directory = folder / label
                directory.mkdir(mode=0o700)
                path = directory / 'snmp.conf'
                path.write_text(text)
                path.chmod(0o600)
                clients[label] = directory
            cold = '.1.3.6.1.6.3.1.1.5.1'
            def logs():
                return manager.crun('exec', 'PC1', '/bin/busybox', 'cat', LOG, check=False).stdout
            def received(token, minimum=1):
                deadline = time.monotonic() + 7
                while time.monotonic() < deadline:
                    if logs().count(token) >= minimum:
                        return
                    time.sleep(.1)
                log = manager.directory / 'PC1/snmptrapd.log'
                self.fail('USM inform not logged: ' + token + ': ' + logs() + (log.read_text(errors='replace') if log.exists() else ''))
            def send(token, label='good', retries=0, extra=()):
                return manager.ns(4 if label == 'rogue' else 2, 'env', 'SNMPCONFPATH=' + str(clients[label]), 'snmptrap',
                                  '-m', '', '-Ci', '-t', '1', '-r', str(retries), *extra, '192.0.2.10', '0', HEARTBEAT,
                                  HEARTBEAT_RATE, 'i', '30', HEARTBEAT_NAME, 's', token, check=False, timeout=5)
            def stop(name, index, service, port):
                manager.crun('exec', name, '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/' + service + '.pid)"')
                deadline = time.monotonic() + 5
                while manager.ns(index, 'ss', '-H', '-lun', 'sport = :' + str(port)).stdout:
                    if time.monotonic() >= deadline:
                        self.fail('Old daemon still listens')
                    time.sleep(.05)
            def begin(label, seconds):
                event = threading.Event()
                path = folder / (label + '.pcap')
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', path,
                                     seconds=seconds, packets=1000, expression='udp port 162', ready=event.set)
                self.assertTrue(event.wait(5))
                return path, future
            def evidence(path, future):
                self.assertGreater(future.result(timeout=30)['captured_packets'], 0)
                rows = captured_v3(path.read_bytes(), port=162)
                encrypted = [r for r in rows if r['flags'] & 3 == 3]
                self.assertTrue(encrypted)
                for row in encrypted:
                    self.assertEqual(row['data_tag'], 4)
                    self.assertEqual(row['auth_length'], 24)
                    self.assertEqual(row['privacy_length'], 8)
                for secret in (auth, privacy, user['auth_master_key'], user['privacy_master_key']):
                    self.assertNotIn(secret.encode(), path.read_bytes())
                return rows
            def identity(rows):
                responses = [r for r in rows if r['source_port'] == 162 and r['flags'] & 3 == 3]
                self.assertTrue(responses)
                ids = {r['engine_id'] for r in responses}
                self.assertEqual(len(ids), 1)
                return responses[0]
            try:
                with manager.locked():
                    manager.start(spec)
                    received(cold)
                path, future = begin('initial', 20)
                with manager.locked():
                    before = copy.deepcopy(manager.read())
                    previous = logs().count(cold)
                    stop('R1', 2, 'snmpd', 161)
                    start_server(manager, spec['nodes'][2])
                    received(cold, previous + 1)
                    marker = 'PRIVATE-INFORM-PAYLOAD-NOT-ON-WIRE'
                    self.assertEqual(send(marker).returncode, 0)
                    received(marker)
                    self.assertEqual(send('MASTER-KEY-OK', label='master').returncode, 0)
                    received('MASTER-KEY-OK')
                    for label in ('auth', 'privacy', 'user', 'low', 'none', 'rogue'):
                        if label == 'rogue':
                            manager.crun('exec', 'PC3', '/bin/ping', '-c', '1', '-W', '2', '192.0.2.10')
                        token = 'REJECT-' + label
                        self.assertNotEqual(send(token, label).returncode, 0, label)
                        self.assertNotIn(token, logs())
                    self.assertEqual(manager.read(), before)
                rows = evidence(path, future)
                first = identity(rows)
                self.assertTrue(any(r['source_ip'] == '192.0.2.30' for r in rows))
                self.assertNotIn(marker.encode(), path.read_bytes())
                self.assertTrue(any(r['flags'] == 0 for r in rows), 'Expected real engine discovery')
                self.assertTrue(any(r['source_port'] == 162 and r['flags'] & 3 == 3 and
                                    any(q['target_port'] == 162 and q['message_id'] == r['message_id'] and
                                        q['source_port'] == r['target_port'] and q['flags'] & 3 == 3 for q in rows) for r in rows))
                # This fixture has short discovery replies and larger encrypted
                # informs/responses. Let discovery through while dropping the
                # actual encrypted exchange; this is not a general classifier.
                self.assertTrue(all(r['udp_length'] > 180 for r in rows if r['flags'] & 3 == 3))
                self.assertTrue(all(r['udp_length'] <= 180 for r in rows if r['flags'] == 0))
                path, future = begin('loss', 8)
                with manager.locked():
                    for chain, token in (('input', 'INPUT-DROP'), ('output', 'ACK-DROP')):
                        manager.ns(0, 'nft', 'add', 'table', 'inet', 'nlab_usm_loss')
                        manager.ns(0, 'nft', 'add', 'chain', 'inet', 'nlab_usm_loss', chain,
                                   '{ type filter hook ' + chain + ' priority -5; policy accept; }')
                        manager.ns(0, 'nft', 'add', 'rule', 'inet', 'nlab_usm_loss', chain, 'udp',
                                   'dport' if chain == 'input' else 'sport', '162', 'udp', 'length', '>', '180', 'drop')
                        try:
                            self.assertNotEqual(send(token, retries=1).returncode, 0)
                            if chain == 'input':
                                self.assertNotIn(token, logs())
                            else: received(token)
                        finally: manager.ns(0, 'nft', 'delete', 'table', 'inet', 'nlab_usm_loss')
                rows = evidence(path, future)
                self.assertGreaterEqual(len([r for r in rows if r['target_port'] == 162 and r['flags'] & 3 == 3]), 4)
                self.assertFalse(any(r['source_port'] == 162 and r['flags'] & 3 == 3 for r in rows))
                with manager.locked():
                    for version in ('1', '2c'):
                        extra = ('-v', version, '-c', 'network-labs-notify')
                        if version == '1':
                            manager.ns(2, 'snmptrap', '-m', '', *extra, '192.0.2.10', '.1.3.6.1.4.1.8072.2.3',
                                                '192.0.2.20', '6', '1', '0', HEARTBEAT_RATE, 'i', '30', HEARTBEAT_NAME, 's', 'FALLBACK-V1',
                                timeout=4)
                        else: self.assertNotEqual(send('FALLBACK-V2C', extra=extra).returncode, 0)
                    self.assertNotIn('FALLBACK-V1', logs())
                    self.assertNotIn('FALLBACK-V2C', logs())
                    report = json.dumps([manager.inspect('PC1')['snmp_receiver'], manager.inspect('R1')['snmp_agent']])
                    for key in (user['auth_master_key'], user['privacy_master_key']):
                        self.assertNotIn(key, report)
                    config = manager.directory / 'PC1/files/snmp-receiver.conf'
                    original = config.read_text()
                    config.write_text(original + '# drift\n')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    config.write_text(original)
                    stop('PC1', 0, 'snmptrapd', 162)
                    self.assertNotEqual(send('RECEIVER-DOWN').returncode, 0)
                    self.assertTrue(manager.inspect('PC1')['snmp_receiver']['configuration_verified'])
                    start_trapd(manager, spec['nodes'][0], 0)
                path, future = begin('restart', 4)
                with manager.locked():
                    self.assertEqual(send('REDISCOVERED-RECEIVER').returncode, 0)
                    received('REDISCOVERED-RECEIVER')
                    previous = logs().count(cold)
                    stop('R1', 2, 'snmpd', 161)
                    start_server(manager, spec['nodes'][2])
                    received(cold, previous + 1)
                second = identity(evidence(path, future))
                self.assertNotEqual(first['engine_id'], second['engine_id'])
                with manager.locked():
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertNotIn(auth, json.dumps(saved))
                    self.assertNotIn(privacy, json.dumps(saved))
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    received(cold)
                    self.assertNotIn('REDISCOVERED-RECEIVER', logs())
                path, future = begin('restore', 4)
                with manager.locked():
                    self.assertEqual(send('RESTORED-USM-INFORM').returncode, 0)
                    received('RESTORED-USM-INFORM')
                third = identity(evidence(path, future))
                self.assertNotIn(third['engine_id'], (first['engine_id'], second['engine_id']))
                with manager.locked():
                    manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        for (family, kind), expected in baseline.items():
            self.assertEqual(run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, expected)
        for key, expected in forwarding.items():
            self.assertEqual(run(['sysctl', '-n', key]).stdout, expected)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)

    def test_appliance_aa_agent_snmp_v2c_counters_access_fault_capture_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import copy
        import threading
        from network_labs.appliances.examples import snmp_lab
        from network_labs.appliances.snmp import start_server
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        for tool in ('snmpd', 'snmpget', 'snmpwalk', 'snmpset'):
            self.assertIsNotNone(shutil.which(tool), 'Install snmpd and snmp for native SNMP tests')
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        baseline = {(family, kind): run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for family in ('-4', '-6') for kind in ('route', 'rule')}
        forwarding = {key: run(['sysctl', '-n', key]).stdout for key in ('net.ipv4.ip_forward', 'net.ipv6.conf.all.forwarding')}
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=2) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            folder = Path(folder)
            rootfs = static_busybox_rootfs(shutil.which('busybox'), folder / 'rootfs', snmpd=shutil.which('snmpd'))
            spec = snmp_lab(rootfs)
            spec['name'] = 'snmp-' + str(os.getpid())
            manager = Manager(spec['name'])
            name_oid = '.1.3.6.1.2.1.1.5.0'
            uptime_oid = '.1.3.6.1.2.1.1.3.0'
            def query(oid, *, source=0, community='network-labs-ro', version='2c', tool='snmpget', extra=(), check=True):
                return manager.ns(source, tool, '-m', '', '-v', version, '-c', community, '-t', '1', '-r', '0',
                                  '-Oqvte', '192.0.2.20', oid, *extra, check=check, timeout=4)
            def ready():
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    result = query(name_oid, check=False)
                    if result.returncode == 0 and result.stdout.strip().strip('"') == 'R1':
                        return
                    time.sleep(.1)
                log = manager.directory / 'R1/snmp.log'
                self.fail('SNMP not ready: ' + (log.read_text(errors='replace') if log.exists() else 'missing log'))
            def interface():
                return json.loads(manager.ns(2, 'ip', '-j', '-s', 'link', 'show', 'dev', 'eth1').stdout)[0]
            def counter(index):
                return int(query('.1.3.6.1.2.1.31.1.1.1.6.' + str(index)).stdout.strip())
            def identity_and_interfaces():
                self.assertEqual(query(name_oid).stdout.strip().strip('"'), 'R1')
                values = query('.1.3.6.1.2.1.31.1.1.1.1', tool='snmpwalk').stdout.splitlines()
                self.assertEqual({v.strip().strip('"') for v in values}, {'lo', 'eth0', 'eth1'})
                index = interface()['ifindex']
                self.assertEqual(query('.1.3.6.1.2.1.2.2.1.2.' + str(index)).stdout.strip().strip('"'), 'eth1')
                self.assertGreaterEqual(int(query(uptime_oid).stdout.strip()), 0)
                return index
            try:
                with manager.locked():
                    manager.start(spec)
                    ready()
                    index = identity_and_interfaces()
                events = [threading.Event(), threading.Event()]
                pcaps = [folder / 'management.pcap', folder / 'untrusted.pcap']
                futures = [pool.submit(capture, Manager(spec['name']), 'R1', port, pcap, seconds=8, packets=1000,
                                       expression='udp port 161', ready=event.set)
                           for port, pcap, event in zip(('eth0', 'eth1'), pcaps, events)]
                self.assertTrue(all(event.wait(5) for event in events), 'SNMP captures not ready')
                with manager.locked():
                    before = copy.deepcopy(manager.read())
                    identity_and_interfaces()
                    for request in ({'community': 'wrong-network-labs'}, {'version': '1'}, {'source': 3}):
                        if request.get('source') == 3:
                            manager.crun('exec', 'PC2', '/bin/ping', '-c', '1', '-W', '2', '192.0.2.20')
                        result = query(name_oid, check=False, **request)
                        self.assertNotEqual(result.returncode, 0, result)
                        self.assertNotIn('R1', result.stdout)
                    hidden = query('.1.3.6.1.2.1.25.1.1.0').stdout
                    self.assertIn('No Such', hidden)
                    rejected = query('.1.3.6.1.2.1.2.2.1.7.' + str(index), tool='snmpset', extra=('i', '2'), check=False)
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertIn('UP', interface()['flags'])
                    self.assertEqual(manager.read(), before)
                for future in futures:
                    self.assertGreater(future.result(timeout=11)['captured_packets'], 0)
                self.assertIn(b'network-labs-ro', pcaps[0].read_bytes())
                self.assertIn(b'wrong-network-labs', pcaps[0].read_bytes())
                self.assertIn(b'R1', pcaps[0].read_bytes())
                self.assertIn(b'network-labs-ro', pcaps[1].read_bytes())
                with manager.locked():
                    first = counter(index)
                    kernel_before = interface()['stats64']['rx']['bytes']
                    manager.crun('exec', 'PC2', '/bin/ping', '-c', '5', '-i', '0.05', '-s', '512', '198.51.100.1', timeout=5)
                    kernel_after = interface()['stats64']['rx']['bytes']
                    self.assertGreaterEqual(kernel_after - kernel_before, 5 * 512)
                    deadline = time.monotonic() + 12
                    while time.monotonic() < deadline:
                        observed = counter(index)
                        if observed >= kernel_after and observed > first:
                            break
                        time.sleep(.3)
                    else: self.fail('SNMP Counter64 did not observe actual node traffic')
                    self.assertLessEqual(observed, interface()['stats64']['rx']['bytes'])
                    config = manager.directory / 'R1/files/snmpd.conf'
                    original = config.read_text()
                    config.write_text(original + '# drift\n')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    config.write_text(original)
                    uptime = int(query(uptime_oid).stdout.strip())
                    manager.crun('exec', 'R1', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/snmpd.pid)"')
                    deadline = time.monotonic() + 5
                    while manager.ns(2, 'ss', '-H', '-lun', 'sport = :161').stdout:
                        if time.monotonic() >= deadline:
                            self.fail('Stopped SNMP daemon still listens')
                        time.sleep(.1)
                    self.assertNotEqual(query(name_oid, check=False).returncode, 0)
                    self.assertTrue(manager.inspect('R1')['snmp_agent']['configuration_verified'], 'Config conformity is not liveness')
                    start_server(manager, spec['nodes'][2])
                    ready()
                    identity_and_interfaces()
                    self.assertLess(int(query(uptime_oid).stdout.strip()), uptime)
                    self.assertGreaterEqual(counter(index), first, 'Agent restart must not fabricate kernel counter reset')
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    ready()
                    identity_and_interfaces()
                    manager.write_startup()
                    self.assertEqual(saved['nodes'][2]['snmp_agent'], spec['nodes'][2]['snmp_agent'])
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        for (family, kind), expected in baseline.items():
            self.assertEqual(run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, expected)
        for key, expected in forwarding.items():
            self.assertEqual(run(['sysctl', '-n', key]).stdout, expected)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)

    def test_appliance_aa_agent_snmp_v3_authpriv_encryption_engine_restart_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import copy
        import threading
        from network_labs.appliances.examples import snmpv3_lab
        from network_labs.appliances.snmp import usm_credentials, client_config, start_server
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        from snmp_wire import captured_v3
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        baseline = {(family, kind): run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for family in ('-4', '-6') for kind in ('route', 'rule')}
        forwarding = {key: run(['sysctl', '-n', key]).stdout for key in ('net.ipv4.ip_forward', 'net.ipv6.conf.all.forwarding')}
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            folder = Path(folder)
            auth = 'native-auth-password'
            privacy = 'native-privacy-password'
            user = usm_credentials('monitor', auth, privacy)
            rootfs = static_busybox_rootfs(shutil.which('busybox'), folder / 'rootfs', snmpd=shutil.which('snmpd'))
            spec = snmpv3_lab(rootfs, user)
            spec['name'] = 'snmpv3-' + str(os.getpid())
            server = 'R1-ENCRYPTED-NODE'
            spec['nodes'][2]['name'] = server
            for link in spec['links']:
                for endpoint in link:
                    if endpoint[0] == 'R1':
                        endpoint[0] = server
            manager = Manager(spec['name'])
            oid = '.1.3.6.1.2.1.1.5.0'
            # Independent official client derives its own keys from fixture
            # passphrases; it does not share the production password-to-Ku code.
            clear = '\n'.join(['defVersion 3', 'defSecurityLevel authPriv', 'defSecurityName monitor',
                                'defAuthType SHA-256', 'defPrivType AES', 'defAuthPassphrase ' + auth,
                                'defPrivPassphrase ' + privacy, ''])
            clients = {}
            for label, text in {'good': clear, 'master': client_config(user),
                                'auth': clear.replace(auth, 'wrong-auth-password'),
                                'privacy': clear.replace(privacy, 'wrong-privacy-password'),
                                'user': clear.replace('Name monitor', 'Name unknown'),
                                'no_privacy': clear.replace('authPriv', 'authNoPriv'),
                                'no_auth': clear.replace('authPriv', 'noAuthNoPriv')}.items():
                directory = folder / ('client-' + label)
                directory.mkdir(mode=0o700)
                path = directory / 'snmp.conf'
                path.write_text(text)
                path.chmod(0o600)
                clients[label] = directory
            def query(target=oid, *, label='good', source=0, tool='snmpget', extra=(), check=True):
                return manager.ns(source, 'env', 'SNMPCONFPATH=' + str(clients[label]), tool, '-m', '',
                                  '-t', '1', '-r', '0', '-Oqvte', '192.0.2.20', target, *extra, check=check, timeout=4)
            def ready():
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if query(check=False).stdout.strip().strip('"') == server:
                        return
                    time.sleep(.1)
                log = manager.directory / server / 'snmp.log'
                self.fail('SNMPv3 not ready: ' + (log.read_text(errors='replace') if log.exists() else 'missing log'))
            def capture_identity(label):
                event = threading.Event()
                path = folder / (label + '.pcap')
                future = pool.submit(capture, Manager(spec['name']), server, 'eth0', path,
                                     seconds=5, packets=1000, expression='udp port 161', ready=event.set)
                self.assertTrue(event.wait(5), 'SNMPv3 capture not ready')
                with manager.locked():
                    self.assertEqual(query().stdout.strip().strip('"'), server)
                    self.assertEqual(query(label='master').stdout.strip().strip('"'), server)
                    names = query('.1.3.6.1.2.1.31.1.1.1.1', tool='snmpwalk').stdout.splitlines()
                    self.assertEqual({v.strip().strip('"') for v in names}, {'lo', 'eth0', 'eth1'})
                self.assertGreater(future.result(timeout=8)['captured_packets'], 0)
                packets = captured_v3(path.read_bytes())
                encrypted = [p for p in packets if p['flags'] & 3 == 3]
                self.assertTrue(any(p['target_port'] == 161 for p in encrypted))
                responses = [p for p in encrypted if p['source_port'] == 161]
                self.assertTrue(responses)
                identities = {p['engine_id'] for p in responses}
                self.assertEqual(len(identities), 1)
                for packet in encrypted:
                    self.assertEqual(packet['data_tag'], 4)
                    self.assertEqual(packet['auth_length'], 24)
                    self.assertEqual(packet['privacy_length'], 8)
                    self.assertEqual(packet['username'], b'monitor')
                    self.assertGreater(packet['boots'], 0)
                    self.assertTrue(5 <= len(packet['engine_id']) <= 32)
                    self.assertNotIn(server.encode(), packet['data'])
                for secret in (auth, privacy, user['auth_master_key'], user['privacy_master_key']):
                    self.assertNotIn(secret.encode(), path.read_bytes())
                return next(iter(identities))
            try:
                with manager.locked():
                    manager.start(spec)
                    ready()
                first = capture_identity('initial')
                with manager.locked():
                    before = copy.deepcopy(manager.read())
                    for label in ('auth', 'privacy', 'user', 'no_privacy', 'no_auth'):
                        rejected = query(label=label, check=False)
                        self.assertNotEqual(rejected.returncode, 0, label)
                        self.assertNotIn(server, rejected.stdout)
                    manager.crun('exec', 'PC2', '/bin/ping', '-c', '1', '-W', '2', '192.0.2.20')
                    self.assertNotEqual(query(source=3, check=False).returncode, 0)
                    for version in ('1', '2c'):
                        rejected = manager.ns(0, 'snmpget', '-m', '', '-v', version, '-c', 'network-labs-ro',
                                              '-t', '1', '-r', '0', '192.0.2.20', oid, check=False, timeout=4)
                        self.assertNotEqual(rejected.returncode, 0)
                    index = json.loads(manager.ns(2, 'ip', '-j', 'link', 'show', 'dev', 'eth1').stdout)[0]['ifindex']
                    self.assertNotEqual(query('.1.3.6.1.2.1.2.2.1.7.' + str(index), tool='snmpset', extra=('i', '2'),
                                              check=False).returncode, 0)
                    self.assertIn('UP', json.loads(manager.ns(2, 'ip', '-j', 'link', 'show', 'dev', 'eth1').stdout)[0]['flags'])
                    self.assertIn('No Such', query('.1.3.6.1.2.1.25.1.1.0').stdout)
                    counter_oid = '.1.3.6.1.2.1.31.1.1.1.6.' + str(index)
                    initial_bytes = int(query(counter_oid).stdout.strip())
                    manager.crun('exec', 'PC2', '/bin/ping', '-c', '5', '-i', '0.05', '-s', '512', '198.51.100.1')
                    deadline = time.monotonic() + 12
                    while int(query(counter_oid).stdout.strip()) <= initial_bytes:
                        if time.monotonic() >= deadline:
                            self.fail('Encrypted Counter64 did not increase')
                        time.sleep(.3)
                    self.assertEqual(manager.read(), before)
                    config = manager.directory / server / 'files/snmpd.conf'
                    original = config.read_text()
                    config.write_text(original + '# drift\n')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    config.write_text(original)
                    report = manager.inspect(server)['snmp_agent']
                    for secret in user.values():
                        if secret != 'monitor':
                            self.assertNotIn(secret, json.dumps(report))
                    manager.crun('exec', server, '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/snmpd.pid)"')
                    deadline = time.monotonic() + 5
                    while manager.ns(2, 'ss', '-H', '-lun', 'sport = :161').stdout:
                        if time.monotonic() >= deadline:
                            self.fail('Stopped SNMPv3 daemon still listens')
                        time.sleep(.1)
                    self.assertNotEqual(query(check=False).returncode, 0)
                    self.assertTrue(manager.inspect(server)['snmp_agent']['configuration_verified'])
                    start_server(manager, spec['nodes'][2])
                    ready()
                second = capture_identity('restart')
                self.assertNotEqual(first, second)
                with manager.locked():
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    self.assertNotIn(auth, json.dumps(saved))
                    self.assertNotIn(privacy, json.dumps(saved))
                    self.assertEqual(saved['nodes'][2]['snmp_agent']['usm'], user)
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    ready()
                third = capture_identity('restore')
                self.assertNotIn(third, (first, second))
                with manager.locked():
                    manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        for (family, kind), expected in baseline.items():
            self.assertEqual(run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, expected)
        for key, expected in forwarding.items():
            self.assertEqual(run(['sysctl', '-n', key]).stdout, expected)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)

    def test_appliance_aa_collector_udp_allowlist_rotation_fault_capture_and_restore(self):
        from concurrent.futures import ThreadPoolExecutor
        import copy
        import threading
        from network_labs.appliances.examples import syslog_lab
        from network_labs.appliances.syslog_server import start_server
        from network_labs.appliances.show import show
        from network_labs.appliances.spec import validate
        from network_labs.appliances.capture import capture
        from network_labs.appliances.persistence import load_startup
        from network_labs.appliances.firewall import fingerprint
        self.assertIsNotNone(shutil.which('rsyslogd'), 'Install rsyslog for native collector tests')
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        baseline = {(family, kind): run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout
                    for family in ('-4', '-6') for kind in ('route', 'rule')}
        forwarding = {key: run(['sysctl', '-n', key]).stdout for key in ('net.ipv4.ip_forward', 'net.ipv6.conf.all.forwarding')}
        nft = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            folder = Path(folder)
            rootfs = static_busybox_rootfs(shutil.which('busybox'), folder / 'rootfs', rsyslog=shutil.which('rsyslogd'))
            spec = syslog_lab(rootfs)
            spec['name'] = 'syslog-' + str(os.getpid())
            rogue = copy.deepcopy(spec['nodes'][0])
            rogue.update(name='PC2', syslog_server=None, interfaces={'eth0': '192.0.2.30/24'})
            spec['nodes'].append(rogue)
            spec['nodes'][1]['interfaces']['eth2'] = ''
            spec['links'].append([['SW1', 'eth2'], ['PC2', 'eth0']])
            spec = validate(spec)
            manager = Manager(spec['name'])
            def logs():
                return manager.crun('exec', 'PC1', '/bin/busybox', 'cat', '/run/remote-syslog.log', check=False).stdout
            def ready():
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if '192.0.2.10:514' in manager.ns(0, 'ss', '-H', '-lun', 'sport = :514').stdout:
                        return
                    time.sleep(.1)
                log = manager.directory / 'PC1/syslog-server.log'
                self.fail('Collector not listening: ' + (log.read_text(errors='replace') if log.exists() else 'no log'))
            def emit(token):
                manager.crun('exec', 'R1', '/bin/busybox', 'logger', '-p', 'local0.notice', '-t', 'network-labs', token)
            def received(token):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    text = logs()
                    if token in text:
                        self.assertIn('192.0.2.20 <133>', text)
                        return
                    time.sleep(.1)
                self.fail('Collector did not store ' + token + ': ' + logs())
            try:
                with manager.locked():
                    manager.start(spec)
                    ready()
                event = threading.Event()
                pcap = folder / 'syslog.pcap'
                future = pool.submit(capture, Manager(spec['name']), 'PC1', 'eth0', pcap,
                                     seconds=5, packets=1000, expression='udp port 514', ready=event.set)
                self.assertTrue(event.wait(5), 'Syslog capture not ready')
                with manager.locked():
                    before = copy.deepcopy(manager.read())
                    manager.ns(3, sys.executable, '-I', '-c',
                               "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.sendto(b'<133>ROGUE-SYSLOG-MUST-DROP',"
                        "('192.0.2.10',514)); s.close()")
                    emit('SYSLOG-COLLECTOR-WIRE-OK')
                    received('SYSLOG-COLLECTOR-WIRE-OK')
                self.assertGreater(future.result(timeout=8)['captured_packets'], 0)
                self.assertIn(b'ROGUE-SYSLOG-MUST-DROP', pcap.read_bytes())
                self.assertIn(b'SYSLOG-COLLECTOR-WIRE-OK', pcap.read_bytes())
                with manager.locked():
                    self.assertNotIn('ROGUE-SYSLOG-MUST-DROP', logs())
                    self.assertEqual(manager.read(), before)
                    manager.crun('exec', 'R1', '/bin/sh', '-c',
                                 'i=0; while [ "$i" -lt 180 ]; do /bin/busybox logger -p local0.notice -t rotate "ROTATION-$i-' + 'x'
                        * 800 + '"; i=$((i+1)); done', timeout=20)
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        backup = manager.crun('exec', 'PC1', '/bin/busybox', 'wc', '-c', '/run/remote-syslog.log.1', check=False)
                        if backup.returncode == 0:
                            break
                        time.sleep(.1)
                    else: self.fail('Collector did not rotate logs')
                    self.assertGreater(int(backup.stdout.split()[0]), 60000)
                    self.assertLess(int(backup.stdout.split()[0]), 80000)
                    archive = show(manager, 'PC1', 'show logging archive')
                    self.assertEqual(archive['status'], 'observed')
                    self.assertIn('ROTATION-', archive['observation']['text'])
                    self.assertLessEqual(len(archive['observation']['text'].encode()), 8192)
                    emit('AFTER-ROTATION-OK')
                    received('AFTER-ROTATION-OK')
                    config = manager.directory / 'PC1/files/syslog-server.conf'
                    original = config.read_text()
                    config.write_text(original + '# drift\n')
                    with self.assertRaises(RuntimeFailure):
                        manager.write_startup()
                    config.write_text(original)
                    manager.crun('exec', 'PC1', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/rsyslogd.pid)"')
                    deadline = time.monotonic() + 5
                    while '192.0.2.10:514' in manager.ns(0, 'ss', '-H', '-lun', 'sport = :514').stdout:
                        if time.monotonic() >= deadline:
                            self.fail('Stopped collector still listens')
                        time.sleep(.1)
                    emit('COLLECTOR-DOWN-MESSAGE')
                    time.sleep(.3)
                    self.assertNotIn('COLLECTOR-DOWN-MESSAGE', logs())
                    self.assertIn('COLLECTOR-DOWN-MESSAGE', manager.crun('exec', 'R1', '/bin/busybox', 'tail', '-n', '5',
                                                                         '/run/messages').stdout)
                    self.assertTrue(manager.inspect('PC1')['syslog_server']['configuration_verified'], 'Config conformity is not liveness')
                    start_server(manager, spec['nodes'][0])
                    ready()
                    emit('COLLECTOR-RESTART-OK')
                    received('COLLECTOR-RESTART-OK')
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    ready()
                    self.assertNotIn('COLLECTOR-RESTART-OK', logs(), 'Runtime logs are not restored')
                    emit('COLLECTOR-RESTORE-OK')
                    received('COLLECTOR-RESTORE-OK')
                    manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        for (family, kind), expected in baseline.items():
            self.assertEqual(run(['ip', '-j', family, kind, 'show', *(['table', 'all'] if kind == 'route' else [])]).stdout, expected)
        for key, expected in forwarding.items():
            self.assertEqual(run(['sysctl', '-n', key]).stdout, expected)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), nft)


if __name__ == '__main__':
    unittest.main()
