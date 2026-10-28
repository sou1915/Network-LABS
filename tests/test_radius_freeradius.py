"""Opt-in interoperability against a real, isolated FreeRADIUS 3 daemon."""
import os
import hashlib
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import unittest

from network_labs.appliances.radius_worker import access_request, authenticate
from network_labs.appliances.radius_server import config_text

SECRET = 'isolated-radius-interop-secret'
PASSWORDS = {'learner': 'interop-password-two-blocks-long',
             'unicode': 'mot-é-secret-123456789', 'maximum': 'z' * 128}


class FreeRadiusInterop(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('NETWORK_LABS_RADIUS_INTEROP') == '1', 'Opt-in real FreeRADIUS interoperability')
    def test_real_pap_accept_reject_utf8_maximum_password_and_shutdown(self):
        # An optional package extraction prefix makes the test usable without
        # installing or starting any host service in restricted development.
        prefix = Path(os.environ.get('NETWORK_LABS_FREERADIUS_ROOT', '/'))
        binary = prefix / 'usr/sbin/freeradius'
        if not binary.is_file():
            found = shutil.which('freeradius') or shutil.which('radiusd')
            self.assertIsNotNone(found, 'Explicit interop test requires FreeRADIUS 3')
            binary = Path(found)
        modules = next((path for path in (prefix / 'usr/lib/freeradius',
                         prefix / 'usr/lib/x86_64-linux-gnu/freeradius', prefix / 'usr/lib64/freeradius')
                        if (path / 'rlm_pap.so').is_file()), None)
        self.assertIsNotNone(modules, 'Installed FreeRADIUS PAP module required')
        dictionary = prefix / 'usr/share/freeradius'
        self.assertTrue((dictionary / 'dictionary').is_file(), 'Installed FreeRADIUS dictionaries required')
        environment = os.environ.copy()
        if prefix != Path('/'):
            environment['LD_LIBRARY_PATH'] = ':'.join(str(p) for p in
                (modules, prefix / 'usr/lib/x86_64-linux-gnu', prefix / 'usr/lib'))
        version = subprocess.run([str(binary), '-v'], env=environment, capture_output=True, text=True, timeout=5)
        self.assertEqual(version.returncode, 0, 'FreeRADIUS executable or libraries unavailable')
        self.assertRegex(version.stdout + version.stderr, r'(?:FreeRADIUS Version|radiusd: FreeRADIUS Version) 3\.')
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
            reservation.bind(('127.0.0.1', 0)); port = reservation.getsockname()[1]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as accounting_reservation:
                accounting_reservation.bind(('127.0.0.1', 0)); accounting_port = accounting_reservation.getsockname()[1]
        with tempfile.TemporaryDirectory(prefix='radius-interop-') as folder:
            root = Path(folder); root.chmod(0o700)
            # Exercise identical executable bytes without attaching a host
            # service's pathname-based profile to this private test config.
            executable = root / 'freeradius'
            shutil.copyfile(binary, executable); executable.chmod(0o755)
            logfile = root / 'daemon.log'; logfile.touch(mode=0o600)
            node = {'interfaces': {'eth0': '127.0.0.1/8'}, 'radius_server': {
                'accounting': True,
                'interface': 'eth0', 'clients': [{'address': '127.0.0.1', 'secret': SECRET}],
                'users': {name: {'password_sha256': hashlib.sha256(password.encode()).hexdigest()}
                          for name, password in PASSWORDS.items()}}}
            # Same generated policy used by native nodes; only paths/port and
            # loopback endpoints are adapted to this unprivileged fixture.
            self.assertTrue((modules / 'rlm_detail.so').is_file(), 'Accounting detail module required')
            (root / 'network-labs-radius-accounting').mkdir(mode=0o700)
            config = config_text(node, modules=str(modules), run_directory=str(root), port=port, accounting_port=accounting_port)
            path = root / 'radiusd.conf'; path.write_text(config); path.chmod(0o600)
            (root / 'dictionary').write_text('# Isolated test; installed base dictionary is loaded with -D.\n')
            args = [str(executable), '-f', '-s', '-d', str(root), '-D', str(dictionary)]
            with logfile.open('a') as output:
                process = subprocess.Popen(args, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail('FreeRADIUS exited before readiness: ' + self.safe_log(logfile))
                    if 'Ready to process requests' in logfile.read_text(errors='replace'):
                        break
                    time.sleep(.05)
                else:
                    self.fail('FreeRADIUS not ready: ' + self.safe_log(logfile))
                cases = [(name, password, 'passed') for name, password in PASSWORDS.items()]
                from network_labs.appliances.radius_accounting_worker import account
                for event in ('start', 'stop'):
                    receipt = account(dict(source='127.0.0.1', address='127.0.0.1', port=accounting_port,
                                           username='learner', secret=SECRET, session_id='aaa-independent', event=event,
                                           session_seconds=2, terminate_cause=1, timeout=2))
                    self.assertEqual(receipt['status'], 'passed', receipt)
                records = root / 'network-labs-radius-accounting/sessions'
                text = records.read_text()
                self.assertEqual(text.count('aaa-independent'), 2)
                self.assertIn('Acct-Status-Type = Start', text); self.assertIn('Acct-Status-Type = Stop', text)
                self.assertEqual(records.stat().st_mode & 0o777, 0o600)
                self.assertNotIn(SECRET, text)
                bad = account(dict(source='127.0.0.1', address='127.0.0.1', port=accounting_port,
                                   username='learner', secret='incorrect-shared-secret', session_id='aaa-wrong-secret',
                                   event='start', session_seconds=0, terminate_cause=1, timeout=.1))
                self.assertEqual(bad['status'], 'unknown')
                self.assertNotIn('aaa-wrong-secret', records.read_text())
                cases += [('learner', 'incorrect-password', 'failed'), ('unknown', 'incorrect-password', 'failed')]
                for username, password, expected in cases:
                    with self.subTest(username=username, expected=expected):
                        result = authenticate(dict(source='127.0.0.1', address='127.0.0.1', port=port,
                                                   username=username, password=password, secret=SECRET, timeout=2))
                        self.assertEqual(result['status'], expected, result)
                        self.assertTrue(result['response_verified'], result)
                        self.assertEqual(result['requests_sent'], 1)
                        self.assertEqual(result['discarded_responses'], 0)
                # This is also a server-side check: a correct PAP password
                # must not bypass the client's mandatory MA policy.
                request = access_request(dict(source='127.0.0.1', username='learner',
                                              password=PASSWORDS['learner'], secret=SECRET))
                bad_mac = bytearray(request); bad_mac[22] ^= 1
                without_mac = request[:2] + (len(request) - 18).to_bytes(2, 'big') + request[4:20] + request[38:]
                for packet in (bytes(bad_mac), without_mac):
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                        client.bind(('127.0.0.1', 0)); client.settimeout(.2)
                        client.sendto(packet, ('127.0.0.1', port))
                        with self.assertRaises(socket.timeout): client.recvfrom(4097)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=3)
            self.assertIsNotNone(process.poll())
            # Process shutdown releases the exact ephemeral listener.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as check:
                check.bind(('127.0.0.1', port))

    @staticmethod
    def safe_log(path):
        text = path.read_text(errors='replace')[-3000:]
        for secret in (SECRET, *PASSWORDS.values()): text = text.replace(secret, '[redacted]')
        return text
