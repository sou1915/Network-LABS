"""Opt-in real OCI boot/packet tests. RADIUS (FreeRADIUS), HTTPS, TFTP (dnsmasq), NTP (chrony) and DNS between real
containers.

Run as test_native_integration says (NETWORK_LABS_NATIVE_TESTS=1, on a disposable Linux host with sudo).
"""
import os
import json
import sys
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.spec import example, namespace

from test_native_integration import NATIVE, RealContainerCase


@unittest.skipUnless(NATIVE, 'Opt-in privileged native test')
class ServicesTests(RealContainerCase):
    def test_managed_radius_real_freeradius_policy_and_saved_restart(self):
        import hashlib
        from network_labs.appliances.examples import radius_lab
        from network_labs.appliances.radius import probe as radius_probe
        from network_labs.appliances.persistence import load_startup
        self.assertEqual(os.geteuid(), 0, 'Run this explicit test with sudo')
        for tool in ('crun', 'ip', 'busybox', 'freeradius'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        secret = 'managed-native-test-secret'
        password = 'managed-native-test-password'
        with tempfile.TemporaryDirectory() as folder, \
             patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs',
                freeradius=shutil.which('freeradius'), freeradius_modules='/usr/lib/freeradius',
                freeradius_dictionaries='/usr/share/freeradius')
            spec = radius_lab(rootfs, secret, hashlib.sha256(password.encode()).hexdigest(), allow_shell=True, accounting=True)
            spec['nodes'][0]['radius_access']['users']['learner'] = ['identity', 'security-context', 'shell']
            spec['name'] = 'radius-managed-' + str(os.getpid())
            spec['nodes'][1]['interfaces']['eth2'] = ''
            spec['nodes'].append({'name': 'PC3', 'runtime': 'oci', 'rootfs': str(rootfs), 'interfaces': {'eth0': '192.0.2.30/24'}})
            spec['links'].append([['SW1', 'eth2'], ['PC3', 'eth0']])
            manager = Manager(spec['name'])
            real_crun = manager.crun
            def diagnostic_crun(*args, **options):
                result = real_crun(*args, **options)
                if '-C' in args and result.returncode:
                    # Debug only this synthetic fixture's failed parse, never
                    # production startup or authentication traffic.
                    debug = real_crun(*args, '-X', **options)
                    detail = 'returncode=' + str(result.returncode) + '\n' + debug.stdout + debug.stderr
                    for value in (secret, password, hashlib.sha256(password.encode()).hexdigest()):
                        detail = detail.replace(value, '[redacted]')
                    self.fail('Managed RADIUS fixture parser failed: ' + detail[-3000:])
                return result
            manager.crun = diagnostic_crun
            with manager.locked():
                try:
                    manager.start(spec)
                    for attempted, expected in ((password, 'passed'), ('incorrect-password', 'failed')):
                        result = radius_probe(manager, 'PC1', '192.0.2.20', username='learner', password=attempted, secret=secret)
                        self.assertEqual(result['status'], expected, result)
                        self.assertTrue(result['authentication']['response_verified'])
                    for client, token in (('PC3', secret), ('PC1', 'incorrect-shared-secret')):
                        result = radius_probe(manager, client, '192.0.2.20', username='learner', password=password, secret=token, timeout=1)
                        self.assertEqual(result['status'], 'unknown', result)
                    observed = manager.inspect('PC2')['radius_server']
                    self.assertEqual(observed['process']['status'], 'observed', observed)
                    self.assertEqual(observed['udp_socket']['status'], 'observed', observed)
                    self.assertEqual(observed['accounting']['udp_socket']['status'], 'observed', observed)
                    from network_labs.appliances.radius_exec import execute as radius_execute
                    for action in ('identity', 'security-context'):
                        allowed = radius_execute(manager, 'PC1', '192.0.2.20', action=action,
                                                 username='learner', password=password, secret=secret)
                        self.assertEqual(allowed['status'], 'passed', allowed)
                        if action == 'identity':
                            self.assertIn('uid=65532', allowed['stdout'])
                        else:
                            context = dict(line.split(':', 1) for line in allowed['stdout'].splitlines() if ':' in line)
                            self.assertEqual(context['NoNewPrivs'].strip(), '1')
                            self.assertEqual(context['CapEff'].strip(), '0000000000000000')
                    denied = radius_execute(manager, 'PC1', '192.0.2.20', action='identity',
                                            username='learner', password='incorrect-password', secret=secret)
                    self.assertEqual(denied['status'], 'blocked')
                    self.assertFalse(denied['executed'])
                    denied_action = radius_execute(manager, 'PC1', '192.0.2.20', action='hostname',
                                                   username='learner', password=password, secret=secret)
                    self.assertEqual(denied_action['error'], 'ACTION_NOT_ALLOWED')
                    self.assertFalse(denied_action['executed'])
                    with patch.object(manager, 'crun', wraps=manager.crun) as calls:
                        unavailable = radius_execute(manager, 'PC1', '192.0.2.20', action='identity',
                                                     username='learner', password=password,
                                                     secret='incorrect-shared-secret', timeout=1)
                    self.assertEqual(unavailable['status'], 'blocked')
                    self.assertFalse(unavailable['executed'])
                    self.assertFalse(any('--process' in call.args for call in calls.call_args_list))
                    self.assertTrue(observed['configuration_verified'], observed)
                    self.assertNotIn(secret, json.dumps(observed))
                    self.assertEqual(manager.crun('exec', 'PC2', '/bin/busybox', 'stat', '-c', '%a',
                                                  '/lab/radius/radiusd.conf').stdout.strip(), '600')
                    manager.write_startup()
                    manager.stop()
                    manager.start(load_startup(spec['name']))
                    access = radius_execute(manager, 'PC1', '192.0.2.20', action='identity',
                                            username='learner', password=password, secret=secret)
                    self.assertEqual(access['status'], 'passed', access)
                    self.assertEqual(manager.state['spec']['nodes'][0]['radius_access']['users']['learner'],
                                     ['identity', 'security-context', 'shell'])
                    from network_labs.appliances.radius_login import login as radius_login
                    accounted = []
                    def verify_accounting(session):
                        self.assertTrue(session['accounting']['enabled'])
                        self.assertEqual(session['accounting']['start']['status'], 'passed', session)
                        self.assertEqual(session['accounting']['stop']['status'], 'passed', session)
                        accounted.append(session['session_id'])
                    output = []
                    def shell(args, **options):
                        completed = subprocess.run(args,
                                input='/bin/busybox id\n/bin/busybox cat /proc/self/status\n/bin/busybox cat /proc/self/cgroup\nexit\n',
                                                   capture_output=True, text=True, timeout=min(8, options['timeout']))
                        output.append(completed.stdout)
                        if completed.returncode:
                            print('RADIUS session fixture runtime: ' + completed.stderr[-2000:], file=sys.stderr)
                        return completed.returncode
                    with patch('network_labs.appliances.radius_login.subprocess.call', side_effect=shell):
                        session = radius_login(manager, 'PC1', '192.0.2.20', username='learner', password=password,
                                               secret=secret, terminal=False)
                    self.assertEqual(session['status'], 'passed', session)
                    self.assertTrue(session['cleanup_complete'], session)
                    verify_accounting(session)
                    self.assertIn(session['session_id'], output[0])
                    self.assertIn('uid=65532', output[0])
                    context = dict(line.split(':', 1) for line in output[0].splitlines() if ':' in line)
                    self.assertEqual(context['NoNewPrivs'].strip(), '1')
                    self.assertEqual(context['CapEff'].strip(), '0000000000000000')
                    def tty_shell(args, **options):
                        import pty
                        import select
                        master, slave = pty.openpty()
                        child = None
                        transcript = bytearray()
                        sent = False
                        try:
                            child = subprocess.Popen(args, stdin=slave, stdout=slave, stderr=slave)
                            os.close(slave)
                            slave = None
                            deadline = time.monotonic() + 8
                            while time.monotonic() < deadline:
                                ready, _, _ = select.select([master], [], [], .1)
                                if ready:
                                    try:
                                        data = os.read(master, 4096)
                                    except OSError: break  # Linux PTY EOF is EIO.
                                    if not data:
                                        break
                                    transcript.extend(data)
                                    if not sent and b'$ ' in transcript:
                                        os.write(master, b'/bin/busybox id\nexit\n')
                                        sent = True
                                elif child.poll() is not None:
                                    break
                            code = child.wait(timeout=1)
                            self.assertTrue(sent, 'Interactive non-root prompt unavailable: ' + repr(transcript))
                            self.assertIn(b'uid=65532', transcript)
                            return code
                        finally:
                            if child is not None and child.poll() is None:
                                child.kill()
                                child.wait(timeout=2)
                            os.close(master)
                            if slave is not None:
                                os.close(slave)
                    with patch('network_labs.appliances.radius_login.subprocess.call', side_effect=tty_shell):
                        session = radius_login(manager, 'PC1', '192.0.2.20', username='learner', password=password,
                                               secret=secret, terminal=True)
                    self.assertEqual(session['status'], 'passed', session)
                    self.assertTrue(session['cleanup_complete'], session)
                    verify_accounting(session)
                    from network_labs.appliances.radius_session import session_parent
                    for ending, expected in (('normal', 'passed'), ('expired', 'expired'), ('interrupted', 'interrupted')):
                        transcript = Path(folder) / ('session-' + ending + '.log')
                        script = Path(folder) / 'session-input'
                        script.write_text('/bin/busybox sleep 37 &\necho SESSION-JOB-READY\n' +
                                          ('exit\n' if ending == 'normal' else 'wait\n'))
                        def background(args, **options):
                            with script.open() as source, transcript.open('w') as output_file:
                                child = subprocess.Popen(args, stdin=source, stdout=output_file, stderr=output_file)
                                try:
                                    if ending == 'interrupted':
                                        deadline = time.monotonic() + 3
                                        while 'SESSION-JOB-READY' not in transcript.read_text():
                                            if time.monotonic() >= deadline:
                                                self.fail('Shell job did not start')
                                            time.sleep(.05)
                                        raise KeyboardInterrupt
                                    return child.wait(timeout=options['timeout'])
                                finally:
                                    if child.poll() is None:
                                        child.kill()
                                        child.wait(timeout=2)
                        with patch('network_labs.appliances.radius_login.subprocess.call', side_effect=background):
                            closed = radius_login(manager, 'PC1', '192.0.2.20', username='learner', password=password,
                                                  secret=secret, seconds=2 if ending == 'expired' else 5)
                        self.assertEqual(closed['status'], expected, closed)
                        self.assertIn('SESSION-JOB-READY', transcript.read_text())
                        self.assertTrue(closed['cleanup_complete'], closed)
                        verify_accounting(closed)
                        self.assertFalse((session_parent(manager, 'PC1') / closed['session_id']).exists())
                        processes = manager.crun('exec', 'PC1', '/bin/busybox', 'ps', '-o', 'args').stdout
                        self.assertNotIn('sleep 37', processes, 'Session background job survived cleanup')
                    with patch('network_labs.appliances.radius_login.subprocess.call') as launch:
                        rejected = radius_login(manager, 'PC1', '192.0.2.20', username='learner',
                                                password='incorrect-password', secret=secret)
                    self.assertEqual(rejected['status'], 'blocked')
                    launch.assert_not_called()
                    from network_labs.appliances.radius_server import ACCOUNTING_FILE, ACCOUNTING_DIRECTORY
                    records = manager.crun('exec', 'PC2', '/bin/busybox', 'cat', ACCOUNTING_FILE).stdout
                    for session_id in accounted:
                        self.assertEqual(records.count(session_id), 2)
                    self.assertEqual(sum(line.startswith('Start|') for line in records.splitlines()), len(accounted))
                    self.assertEqual(sum(line.startswith('Stop|') for line in records.splitlines()), len(accounted))
                    self.assertTrue(any(line.endswith('|5') for line in records.splitlines()))
                    self.assertTrue(any(line.endswith('|6') for line in records.splitlines()))
                    self.assertNotIn(secret, records)
                    self.assertNotIn(password, records)
                    modes = manager.crun('exec', 'PC2', '/bin/busybox', 'stat', '-c', '%a', ACCOUNTING_FILE, ACCOUNTING_DIRECTORY).stdout
                    self.assertEqual(modes, '600\n700\n')
                    # A full ephemeral log filesystem must not acknowledge an
                    # unrecorded Start or allow a shell through the gate.
                    full = manager.crun('exec', 'PC2', '/bin/busybox', 'dd', 'if=/dev/zero', 'of=/run/accounting-fill',
                                        'bs=1024', 'count=9000', check=False)
                    self.assertNotEqual(full.returncode, 0)
                    try:
                        # Filling another file can leave a partial block in the
                        # existing log. Consume that bounded tail capacity first.
                        from network_labs.appliances.radius_accounting import send
                        for index in range(128):
                            exhausted = send(manager, 'PC1', '192.0.2.20', username='learner',
                                             secret=secret, session_id='aaa-storage-fill-' + str(index),
                                             event='stop', timeout=1, terminate_cause=9)
                            if exhausted['status'] != 'passed':
                                break
                        else: self.fail('Accounting acknowledged records beyond remaining log block capacity')
                        self.assertEqual(exhausted['status'], 'unknown', exhausted)
                        with patch('network_labs.appliances.radius_login.subprocess.call') as launch:
                            unavailable = radius_login(manager, 'PC1', '192.0.2.20', username='learner',
                                                       password=password, secret=secret, timeout=1)
                        self.assertEqual(unavailable['status'], 'blocked', unavailable)
                        self.assertEqual(unavailable['error'], 'ACCOUNTING_START_UNCONFIRMED')
                        launch.assert_not_called()
                    finally:
                        manager.crun('exec', 'PC2', '/bin/busybox', 'rm', '-f', '/run/accounting-fill')
                    result = radius_probe(manager, 'PC1', '192.0.2.20', username='learner', password=password, secret=secret)
                    self.assertEqual(result['status'], 'passed', result)
                    service = manager.inspect('PC2')['radius_server']
                    self.assertEqual(service['process']['status'], 'observed', service)
                    manager.crun('exec', 'PC2', '/bin/busybox', 'kill', '-TERM', str(service['process']['pid']))
                    deadline = time.monotonic() + 5
                    while True:
                        stopped = manager.inspect('PC2')['radius_server']
                        if stopped['udp_socket']['status'] == 'absent' and stopped['process']['status'] != 'observed':
                            break
                        if time.monotonic() >= deadline:
                            self.fail('RADIUS listener remained after daemon termination')
                        time.sleep(.1)
                    self.assertTrue(stopped['configuration_verified'])
                    self.assertNotEqual(stopped['process']['status'], 'observed')
                    with patch.object(manager, 'crun', wraps=manager.crun) as calls:
                        unavailable = radius_execute(manager, 'PC1', '192.0.2.20', action='identity',
                                                     username='learner', password=password, secret=secret, timeout=1)
                    self.assertEqual(unavailable['status'], 'blocked')
                    self.assertFalse(unavailable['executed'])
                    self.assertFalse(any('--process' in call.args for call in calls.call_args_list))
                finally:
                    if manager.directory.exists():
                        manager.stop()

    def test_radius_pap_accept_and_reject_cross_real_bridge(self):
        import selectors
        from network_labs.appliances.radius import probe as radius_probe
        self.assertEqual(os.geteuid(), 0, 'Run this explicit test with sudo')
        for tool in ('crun', 'ip', 'busybox'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        # A deterministic test responder, not a managed FreeRADIUS service.
        server_code = '''import hashlib,hmac,socket,struct
secret=b"radius-native-test-secret"
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(("192.0.2.20",1812)); s.settimeout(10)
print("ready",flush=True)
for attempt in range(2):
    request,peer=s.recvfrom(4097)
    assert peer[0]=="192.0.2.10" and request[0]==1 and request[20:22]==b"\\x50\\x12"
    unsigned=request[:22]+b"\\0"*16+request[38:]
    assert hmac.compare_digest(request[22:38],hmac.new(secret,unsigned,hashlib.md5).digest())
    attrs={}; pos=20
    while pos<len(request):
        kind,size=request[pos:pos+2]; assert size>=2
        attrs[kind]=request[pos+2:pos+size]; pos+=size
    assert attrs[1]==b"learner"
    encrypted=attrs[2]; previous=request[4:20]; password=b""
    for pos in range(0,len(encrypted),16):
        chunk=encrypted[pos:pos+16]; mask=hashlib.md5(secret+previous).digest()
        password+=bytes(a^b for a,b in zip(chunk,mask)); previous=chunk
    code=2 if password.rstrip(b"\\0")==b"radius-native-test-password" else 3
    header=struct.pack("!BBH",code,request[1],38)
    attributes=b"\\x50\\x12"+b"\\0"*16
    mac=hmac.new(secret,header+request[4:20]+attributes,hashlib.md5).digest()
    attributes=attributes[:2]+mac
    authenticator=hashlib.md5(header+request[4:20]+attributes+secret).digest()
    s.sendto(header+authenticator+attributes,peer)
'''
        with tempfile.TemporaryDirectory() as folder:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = example(rootfs)
            spec['name'] = 'radius-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            process = None
            with manager.locked():
                try:
                    manager.start(spec)
                    process = subprocess.Popen(['ip', 'netns', 'exec', namespace(spec, 2), sys.executable, '-I', '-c', server_code],
                                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        self.assertTrue(selector.select(timeout=5), 'RADIUS test responder not ready')
                        self.assertEqual(process.stdout.readline().strip(), 'ready')
                    for password, status in (('radius-native-test-password', 'passed'), ('incorrect-password', 'failed')):
                        report = radius_probe(manager, 'PC1', '192.0.2.20', username='learner', password=password,
                                              secret='radius-native-test-secret')
                        self.assertEqual(report['status'], status, report)
                        self.assertTrue(report['authentication']['response_verified'])
                    _, error = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, error)
                finally:
                    if process is not None and process.poll() is None:
                        process.kill()
                        process.communicate()
                    if manager.directory.exists():
                        manager.stop()

    def test_https_demo_between_real_nodes(self):
        from network_labs.appliances.https_demo import demo
        self.assertEqual(os.geteuid(), 0, 'Run this explicit test with sudo')
        for tool in ('crun', 'ip', 'busybox', 'openssl'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        with tempfile.TemporaryDirectory() as folder:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = example(rootfs)
            spec['name'] = 'https-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            with manager.locked():
                try:
                    manager.start(spec)
                    result = demo(manager, 'PC1', 'PC2')
                    self.assertEqual(result['status'], 'passed', result)
                    self.assertTrue(result['probe']['stages'][-1]['certificate_verified'])
                    self.assertEqual(result['probe']['stages'][-1]['http_status'], 200)
                    self.assertEqual(manager.ns(2, 'ss', '-H', '-ltn', 'sport = :443').stdout.strip(), '')
                finally:
                    if manager.directory.exists():
                        manager.stop()

    def test_managed_dnsmasq_tftp_read_and_write_rejection(self):
        import hashlib
        from network_labs.appliances.examples import tftp_lab
        from network_labs.appliances.tftp import read as tftp_read
        self.assertEqual(os.geteuid(), 0, 'Run this explicit test with sudo')
        for tool in ('crun', 'ip', 'busybox', 'dnsmasq'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        with tempfile.TemporaryDirectory() as folder:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', dnsmasq=shutil.which('dnsmasq'))
            spec = tftp_lab(rootfs)
            spec['name'] = 'tftp-managed-' + str(os.getpid())
            manager = Manager(spec['name'])
            with manager.locked():
                try:
                    manager.start(spec)
                    expected = hashlib.sha256(b'Network LABS TFTP\n').hexdigest()
                    deadline = time.monotonic() + 12
                    while True:
                        result = tftp_read(manager, 'PC1', '192.0.2.20', 'sample.txt', timeout=2, expected_sha256=expected)
                        if result['status'] == 'passed':
                            break
                        if time.monotonic() >= deadline:
                            self.fail('TFTP service unavailable: ' + json.dumps(result))
                        time.sleep(.2)
                    self.assertTrue(result['hash_matches'])
                    binary = b'\x00\x01\x02\x03\xff'
                    binary_result = tftp_read(manager, 'PC1', '192.0.2.20', 'sample.bin', timeout=2,
                                              expected_sha256=hashlib.sha256(binary).hexdigest())
                    self.assertEqual(binary_result['status'], 'passed', binary_result)
                    self.assertEqual(binary_result['transfer']['bytes_received'], len(binary))
                    self.assertTrue(binary_result['hash_matches'])
                    missing = tftp_read(manager, 'PC1', '192.0.2.20', 'missing.txt', timeout=2)
                    self.assertEqual(missing['status'], 'failed')
                    self.assertEqual(missing['transfer'].get('error_code'), 1)
                    code = ("import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(2); "
                            "s.sendto(b'\\x00\\x02upload.txt\\x00octet\\x00',('192.0.2.20',69)); "
                            "p,a=s.recvfrom(1024); print(p[:2].hex())")
                    rejected = manager.ns(0, sys.executable, '-I', '-c', code, check=False, timeout=4)
                    self.assertTrue(rejected.returncode != 0 or rejected.stdout.strip() == '0005')
                    self.assertTrue(manager.inspect('PC2')['tftp_server']['configuration_verified'])
                finally:
                    if manager.directory.exists():
                        manager.stop()

    def test_tftp_read_crosses_real_veth_and_bridge(self):
        import hashlib
        import selectors
        from network_labs.appliances.tftp import read as tftp_read
        self.assertEqual(os.geteuid(), 0, 'Run this explicit test with sudo')
        for tool in ('crun', 'ip', 'busybox'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        server_code = '''import socket,struct,time
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(("192.0.2.20",69)); s.settimeout(8)
print("ready",flush=True)
request,peer=s.recvfrom(1024)
assert request==b"\\x00\\x01sample.bin\\x00octet\\x00"
t=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); t.bind(("192.0.2.20",0)); t.settimeout(5)
t.sendto(struct.pack("!HH",3,1)+b"TFTP lab\\n",peer)
ack,source=t.recvfrom(1024); assert source==peer and ack==struct.pack("!HH",4,1)
time.sleep(.1)
t.sendto(struct.pack("!HH",3,1)+b"TFTP lab\\n",peer)
ack,source=t.recvfrom(1024); assert source==peer and ack==struct.pack("!HH",4,1)
'''
        with tempfile.TemporaryDirectory() as folder:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = example(rootfs)
            spec['name'] = 'tftp-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            process = None
            with manager.locked():
                try:
                    manager.start(spec)
                    process = subprocess.Popen(['ip', 'netns', 'exec', namespace(spec, 2), sys.executable, '-I', '-c', server_code],
                                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        self.assertTrue(selector.select(timeout=5), 'TFTP test server not ready')
                        self.assertEqual(process.stdout.readline().strip(), 'ready')
                    expected = hashlib.sha256(b'TFTP lab\n').hexdigest()
                    result = tftp_read(manager, 'PC1', '192.0.2.20', 'sample.bin', expected_sha256=expected)
                    self.assertEqual(result['status'], 'passed', result)
                    self.assertTrue(result['hash_matches'])
                    self.assertEqual(result['transfer']['final_ack']['duplicate_acks'], 1)
                    _, error = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, error)
                finally:
                    if process is not None and process.poll() is None:
                        process.kill()
                        process.communicate()
                    if manager.directory.exists():
                        manager.stop()

    def test_ntp_local_reference_relay_and_client_with_real_chronyd(self):
        from network_labs.appliances.examples import ntp_lab
        from network_labs.appliances.service_probe import probe
        self.assertEqual(os.geteuid(), 0, 'Run this explicit test with sudo')
        for tool in ('crun', 'ip', 'busybox', 'chronyd', 'chronyc'):
            self.assertIsNotNone(shutil.which(tool), tool + ' required')
        with tempfile.TemporaryDirectory() as folder:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', chronyd=shutil.which('chronyd'),
                                           chronyc=shutil.which('chronyc'))
            spec = ntp_lab(rootfs)
            spec['name'] = 'ntp-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            with manager.locked():
                try:
                    manager.start(spec)
                    upstream = probe(manager, 'PC2', '192.0.2.30', protocol='sntp', timeout=2)
                    self.assertEqual(upstream['status'], 'passed', upstream)
                    self.assertEqual(upstream['stages'][-1]['stratum'], 10)
                    denied = probe(manager, 'PC1', '192.0.2.30', protocol='sntp', timeout=1)
                    self.assertNotEqual(denied['status'], 'passed', denied)
                    deadline = time.monotonic() + 50
                    while True:
                        downstream = probe(manager, 'PC1', '192.0.2.20', protocol='sntp', timeout=2)
                        if downstream['status'] == 'passed':
                            break
                        if time.monotonic() >= deadline:
                            self.fail('Relay did not synchronize: ' + json.dumps(downstream))
                        time.sleep(.5)
                    self.assertEqual(downstream['stages'][-1]['stratum'], 11)
                    from network_labs.appliances.show import show
                    for cmd in ('show ntp status', 'show ntp associations'):
                        observed = show(manager, 'PC2', cmd)
                        self.assertEqual(observed['status'], 'observed', observed)
                        self.assertTrue(observed['observation']['text'].strip())
                    service = manager.inspect('PC2')['ntp_server']
                    self.assertTrue(service['configuration_verified'])
                    self.assertEqual(service['process']['status'], 'observed', service)
                    self.assertEqual(service['udp_socket']['status'], 'observed', service)
                    pid = service['process']['pid']
                    manager.crun('exec', 'PC2', '/bin/busybox', 'kill', '-TERM', str(pid))
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        stopped = manager.inspect('PC2')['ntp_server']
                        if stopped['process']['status'] != 'observed':
                            break
                        time.sleep(.1)
                    else: self.fail('Stopped chronyd still observed')
                    self.assertTrue(stopped['configuration_verified'])
                    self.assertNotEqual(stopped['process']['status'], 'observed')
                finally:
                    if manager.directory.exists():
                        manager.stop()

    def test_dns_real_udp_tcp_dhcp_resolver_http_failure_config_drift_and_restore(self):
        from network_labs.appliances.examples import dns_lab
        from network_labs.appliances.firewall import fingerprint
        from network_labs.appliances.persistence import load_startup
        from test_native_dns import DNS_QUERY, dns_response
        self.assertIsNotNone(shutil.which('dnsmasq'), 'Install dnsmasq-base for the explicitly requested native DNS test')
        routes = run(['ip', '-j', 'route', 'show']).stdout
        host_links = lambda: {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        links = host_links()
        host_rules = fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(folder) / 'saved'):
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs', dnsmasq=shutil.which('dnsmasq'))
            spec = dns_lab(rootfs)
            spec['name'] = 'dns-test-' + str(os.getpid())
            manager = Manager(spec['name'])
            def query(host='intranet.lab.test', kind=1, transport='udp', check=True):
                return manager.ns(0, sys.executable, '-c', DNS_QUERY, host, str(kind), transport, check=check, timeout=5)
            def ready():
                deadline = time.monotonic() + 15
                last = ''
                while time.monotonic() < deadline:
                    resolver = manager.crun('exec', 'PC1', '/bin/cat', '/etc/resolv.conf', check=False)
                    if resolver.returncode == 0 and 'nameserver 10.10.0.2' in resolver.stdout:
                        result = query(check=False)
                        last = result.stderr
                        if result.returncode == 0:
                            self.assertEqual(dns_response(result.stdout)[1][0][-1], '10.10.0.20')
                            return
                    time.sleep(0.1)
                self.fail('Actual DHCP resolver/DNS not ready: ' + last + '\n' + (manager.directory / 'DNS1' / 'dns.log').read_text())
            def http_by_name():
                for client in ('PC1', 'PC2'):
                    result = manager.crun('exec', client, '/bin/busybox', 'nslookup', '-type=A', 'intranet.lab.test', timeout=10)
                    self.assertIn('10.10.0.20', result.stdout)
                    manager.crun('exec', client, '/bin/ping', '-c', '1', '-W', '1', 'intranet.lab.test', timeout=10)
                    web = manager.crun('exec', client, '/bin/busybox', 'wget', '-T', '3', '-q', '-O', '-', 'http://intranet.lab.test/',
                                       timeout=10)
                    self.assertIn('Network LABS HTTP via DNS', web.stdout)
            try:
                with manager.locked():
                    manager.start(spec)
                    ready()
                    http_by_name()
                    self.assertTrue(manager.inspect('PC2')['resolver']['configuration_verified'])
                    self.assertNotEqual(manager.crun('exec', 'PC2', '/bin/sh', '-c', 'echo changed > /etc/resolv.conf',
                                                     check=False).returncode, 0)
                    for transport in ('udp', 'tcp'):
                        for host, kind, expected_rcode, expected_value in (
                            ('intranet.lab.test', 1, 0, '10.10.0.20'),
                            ('20.0.10.10.in-addr.arpa', 12, 0, 'intranet.lab.test'),
                            ('intranet.lab.test', 28, 0, None),
                            ('missing.lab.test', 1, 3, None)):
                            with self.subTest(transport=transport, host=host, kind=kind):
                                rcode, records = dns_response(query(host, kind, transport).stdout)
                                self.assertEqual(rcode, expected_rcode)
                                if expected_value is None:
                                    self.assertEqual(records, [])
                                else:
                                    self.assertEqual(records, [(host, kind, 1, 60, expected_value)])
                    server = manager.inspect('DNS1')['dns_server']
                    self.assertTrue(server['configuration_verified'])
                    self.assertTrue(any('udp' in row for row in server['listener_snapshot']))
                    self.assertTrue(any('tcp' in row for row in server['listener_snapshot']))
                    # Policy text conformity must not masquerade as daemon health.
                    manager.crun('exec', 'DNS1', '/bin/sh', '-c', '/bin/kill -TERM "$(/bin/cat /run/dnsmasq.pid)"')
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline and manager.inspect('DNS1')['dns_server']['listener_snapshot']:
                        time.sleep(0.1)
                    stopped = manager.inspect('DNS1')['dns_server']
                    self.assertTrue(stopped['configuration_verified'])
                    self.assertEqual(stopped['listener_snapshot'], [])
                    for transport in ('udp', 'tcp'):
                        self.assertNotEqual(query(transport=transport, check=False).returncode, 0)
                    manager.crun('exec', 'PC1', '/bin/ping', '-c', '1', '-W', '1', '10.10.0.20')
                    self.assertIn('Network LABS HTTP via DNS', manager.crun('exec', 'PC1', '/bin/busybox', 'wget', '-T', '3', '-q', '-O',
                                                                            '-', 'http://10.10.0.20/').stdout)
                    # Save stores declared policy; restore launches new services.
                    manager.write_startup()
                    saved = load_startup(spec['name'])
                    manager.stop()
                manager = Manager(spec['name'])
                with manager.locked():
                    manager.start(saved)
                    ready()
                    http_by_name()
                    for relative, equipment, component, message in (
                        ('DNS1/files/dnsmasq.conf', 'DNS1', 'dns_server', 'DNS server'),
                        ('PC2/files/resolv.conf', 'PC2', 'resolver', 'DNS resolver')):
                        path = manager.directory / relative
                        original = path.read_text()
                        try:
                            path.write_text(original + '# external drift\n')
                            self.assertFalse(manager.inspect(equipment)[component]['configuration_verified'])
                            with self.assertRaisesRegex(RuntimeFailure, message):
                                manager.write_startup()
                        finally:
                            path.write_text(original)
                    self.assertEqual(dns_response(query(transport='tcp').stdout)[1][0][-1], '10.10.0.20')
            finally:
                if manager.directory.exists():
                    with manager.locked():
                        manager.stop()
        self.assertHostLinksUnchanged(links, host_links())
        self.assertEqual(run(['ip', '-j', 'route', 'show']).stdout, routes)
        self.assertEqual(fingerprint(json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)), host_rules)


if __name__ == '__main__':
    unittest.main()
