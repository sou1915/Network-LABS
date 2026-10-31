"""Compile the guest relay and exercise actual duplex I/O without privileges."""
import base64
import os
from pathlib import Path
import pty
import select
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest


@unittest.skipUnless(shutil.which('cc'), 'Host C compiler required')
class SSHRelayClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.folder.cleanup)
        cls.binary = Path(cls.folder.name) / 'relay'
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0)); cls.port = reservation.getsockname()[1]
        source = Path(__file__).parents[1] / 'network_labs/appliances/ssh_radius_relay.c'
        subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-DNL_BRIDGE_PORT=' + str(cls.port),
                        str(source), '-o', str(cls.binary)], check=True, capture_output=True)

    def test_compiled_elf_identity_and_copy_plan_match_the_rootfs_builder(self):
        from network_labs.appliances.ssh_access import relay_assets, RELAY_BINARY
        plan = relay_assets(self.binary)
        self.assertIn((self.binary.resolve(), Path(RELAY_BINARY)), plan)

    def endpoint(self, handler):
        listener = socket.socket(); listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', self.port)); listener.listen(1); listener.settimeout(3)
        errors = []
        def run():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(3)
                    stream = connection.makefile('rb', buffering=0)
                    try:
                        fields = [stream.readline() for _ in range(4)]
                        self.assertEqual(fields[0], b'NLSSH1\n')
                        handler(connection, fields)
                    finally: stream.close()
            except BaseException as error: errors.append(error)
            finally: listener.close()
        thread = threading.Thread(target=run, daemon=True); thread.start()
        return thread, errors

    def finish(self, thread, errors):
        thread.join(timeout=4); self.assertFalse(thread.is_alive())
        if errors: raise errors[0]

    def test_binary_stream_and_exit_record_are_separate(self):
        command = b'exit 7\n'; payload = b'E0\nbytes\x00\xff'
        def peer(connection, fields):
            self.assertEqual(fields[1], b'shell\n')
            connection.sendall(b'SHELL\n'); received = bytearray()
            while True:
                data = connection.recv(4096)
                if not data: break
                received.extend(data)
            self.assertEqual(received, command)
            connection.sendall(b'D' + base64.b64encode(payload) + b'\nE7\n')
        thread, errors = self.endpoint(peer)
        result = subprocess.run([str(self.binary), 'shell', '3'], input=b'learner\nfixture-password\n' + command,
                                capture_output=True, timeout=5)
        self.finish(thread, errors)
        self.assertEqual(result.returncode, 7, result); self.assertEqual(result.stdout, payload)

    def test_denial_never_forwards_pending_shell_commands(self):
        def peer(connection, fields):
            connection.sendall(b'DENY\n')
            self.assertEqual(connection.recv(4096), b'')
        thread, errors = self.endpoint(peer)
        result = subprocess.run([str(self.binary), 'shell', '3'], input=b'learner\nincorrect\nnever-forward-this\n',
                                capture_output=True, timeout=5)
        self.finish(thread, errors)
        self.assertEqual(result.returncode, 126); self.assertEqual(result.stdout, b'')

    def test_missing_or_invalid_final_status_cannot_report_success(self):
        for payload in (b'D' + base64.b64encode(b'partial') + b'\n', b'E999\n', b'D!!!!\n', b'E-1\n'):
            def peer(connection, fields): connection.sendall(b'SHELL\n' + payload)
            thread, errors = self.endpoint(peer)
            result = subprocess.run([str(self.binary), 'shell', '3'], input=b'learner\nfixture-password\n',
                                    capture_output=True, timeout=5)
            self.finish(thread, errors)
            self.assertEqual(result.returncode, 125, result)

    def test_real_tty_prompts_hide_credentials_and_relay_after_grant(self):
        def peer(connection, fields):
            self.assertEqual(fields[1], b'shell-tty\n')
            connection.sendall(b'SHELL\nD' + base64.b64encode(b'$ ') + b'\n')
            self.assertEqual(connection.recv(4096), b'exit\n')
            connection.sendall(b'D' + base64.b64encode(b'TTY-OK\n') + b'\nE0\n')
        thread, errors = self.endpoint(peer)
        master, slave = pty.openpty(); output = bytearray(); stage = 0
        process = subprocess.Popen([str(self.binary), 'shell', '3'], stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        try:
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                readable, _, _ = select.select([master], [], [], .05)
                if readable:
                    try: data = os.read(master, 4096)
                    except OSError: break
                    if not data: break
                    output.extend(data)
                if stage == 0 and b'RADIUS username: ' in output: os.write(master, b'learner\n'); stage = 1
                if stage == 1 and b'RADIUS password: ' in output: os.write(master, b'fixture-password\n'); stage = 2
                if stage == 2 and b'$ ' in output: os.write(master, b'exit\n'); stage = 3
                if process.poll() is not None: break
            self.assertEqual(process.wait(timeout=1), 0)
            self.assertEqual(stage, 3); self.assertIn(b'TTY-OK', output)
            self.assertNotIn(b'fixture-password', output)
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=1)
            os.close(master)
        self.finish(thread, errors)
