"""Real compiled guest protocol and local transport; not a KVM boot test."""
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
import unittest
from network_labs.appliances.guest_control import request


@unittest.skipUnless(shutil.which('gcc'), 'gcc required for actual guest agent tests')
class GuestAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary = Path(cls.temporary.name) / 'agent'
        subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', '-o', str(cls.binary),
                        'network_labs/appliances/guest/agent.c'], check=True)

    def invoke(self, data):
        result = subprocess.run([str(self.binary), '--stdio'], input=data,
                                capture_output=True, timeout=7, check=True)
        header, body = result.stdout.split(b'\n', 1)
        version, code, length = header.split()
        self.assertEqual(version, b'NL1')
        self.assertEqual(len(body), int(length))
        return int(code), body

    def test_ready_does_not_claim_network_readiness(self):
        code, body = self.invoke(b'NL1 READY\n')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(body), {'protocol': 1, 'agent_ready': True, 'network_verified': False})

    def test_rejects_shell_nul_unknown_version_and_overlong_requests(self):
        for data in (b'NL1 ROUTES; id\n', b'NL1 READY\0evil\n', b'NL2 READY\n', b'NL1 PING 127.0.0.1;id\n', b'NL1 PING -c\n', b'x' * 80, b''):
            with self.subTest(data=data):
                self.assertEqual(self.invoke(data)[0], 2)

    def test_fixed_linux_diagnostics_report_real_exit_status(self):
        for operation in ('ADDRESSES', 'ROUTES', 'PING 127.0.0.1'):
            code, body = self.invoke(('NL1 ' + operation + '\n').encode())
            self.assertEqual(code, 0 if Path('/bin/busybox').exists() else 127)
            if code == 0 and operation == 'ADDRESSES':
                self.assertIn(b'lo', body)

    def test_partial_request_times_out(self):
        with subprocess.Popen([str(self.binary), '--stdio'], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
            child.stdin.write(b'NL1'); child.stdin.flush()
            self.assertNotEqual(child.wait(timeout=7), 0)


class GuestTransportTests(unittest.TestCase):
    def exchange(self, payload, *, handshake=b'OK 19001\n', timeout=1, delay=0):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vsock'
            errors = []
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(path)); server.listen(1); server.settimeout(3)
                def serve():
                    try:
                        with server.accept()[0] as connection:
                            connection.settimeout(3)
                            self.assertEqual(connection.recv(100), b'CONNECT 19001\n')
                            connection.sendall(handshake)
                            if not handshake.startswith(b'OK '): return
                            self.assertEqual(connection.recv(100), b'NL1 READY\n')
                            time.sleep(delay)
                            for byte in payload: connection.sendall(bytes([byte]))
                    except (BrokenPipeError, ConnectionResetError): pass
                    except Exception as error: errors.append(error)
                worker = threading.Thread(target=serve)
                worker.start()
                try:
                    return request(path, 'ready', timeout=timeout)
                finally:
                    worker.join(4)
                    self.assertFalse(worker.is_alive())
                    if errors: raise errors[0]

    def test_fragmented_response_and_nonzero_exit_are_preserved(self):
        self.assertEqual(self.exchange(b'NL1 127 4\noops'),
                         {'operation': 'ready', 'exit_code': 127, 'output': 'oops'})

    def test_malformed_oversized_truncated_responses(self):
        for payload in (b'NL2 0 0\n', b'NL1 0 32769\n', b'NL1 256 0\n', b'NL1 0 2\nx', b'x' * 81):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.exchange(payload)
        with self.assertRaises(ValueError): self.exchange(b'', handshake=b'ERR no\n')

    def test_deadline_and_operation_validation(self):
        with self.assertRaises(TimeoutError): self.exchange(b'NL1 0 0\n', timeout=.05, delay=.1)
        with self.assertRaises(ValueError): request('/nonexistent', 'shell')
        with self.assertRaises(ValueError): request('/nonexistent', 'ping', destination='1.2.3.4;id')
        with self.assertRaises(ValueError): request('/nonexistent', 'ready', destination='1.2.3.4')
