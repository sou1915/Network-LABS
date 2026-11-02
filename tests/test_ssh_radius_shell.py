"""SSH shell transport boundaries and existing session-supervisor integration."""
import base64
import hashlib
import socket
import subprocess
import sys
import unittest
import threading
from unittest.mock import Mock, patch

from network_labs.appliances.examples import radius_lab
from network_labs.appliances.ssh_access import dispatcher, key_options, service_process
from network_labs.appliances.ssh_radius_shell import relay, serve_shell
from test_native_management import KEY

SECRET = 'ssh-shell-private-fixture-secret'
DIGEST = hashlib.sha256(b'fixture-password').hexdigest()


class SSHRadiusShellTests(unittest.TestCase):
    def manager(self):
        spec = radius_lab('/rootfs', SECRET, DIGEST, ssh_key=KEY, ssh_shell=True)
        manager = Mock(); manager.state = {'phase': 'running', 'spec': spec}; manager.read.return_value = manager.state
        return manager

    def test_shell_requires_both_explicit_ssh_and_radius_permissions(self):
        manager = self.manager(); node = manager.state['spec']['nodes'][0]
        self.assertIn('shell', node['radius_access']['users']['learner'])
        self.assertIn('shell', node['management']['ssh_actions'])
        self.assertNotIn('no-pty', key_options(node['management']['ssh_actions']))
        self.assertIn('no-pty', key_options(['identity']))
        self.assertIn("''|shell)", dispatcher(['shell'], radius=True, session_seconds=2))
        with self.assertRaises(ValueError): dispatcher(['shell'])
        self.assertIn('CAP_CHOWN', service_process(['/bin/server'], terminal=True)['capabilities']['effective'])
        connection = Mock()
        node['management']['ssh_actions'] = ['identity']
        with patch('network_labs.appliances.ssh_radius_shell.login') as login:
            serve_shell(manager, 'PC1', connection, 'learner', 'password', terminal=False)
            login.assert_not_called(); connection.sendall.assert_called_once_with(b'DENY\n')

    def test_unverified_authentication_never_launches_a_shell(self):
        manager = self.manager(); connection = Mock()
        with patch('network_labs.appliances.radius_login.probe', return_value={'status': 'failed'}), \
             patch('network_labs.appliances.ssh_radius_shell.subprocess.Popen') as launch:
            serve_shell(manager, 'PC1', connection, 'learner', 'incorrect', terminal=False)
            launch.assert_not_called(); connection.sendall.assert_called_once_with(b'DENY\n')

    def test_final_status_follows_supervisor_cleanup_and_disables_signal_override(self):
        manager = self.manager(); events = []; connection = Mock()
        connection.sendall.side_effect = events.append
        process = Mock(); process.poll.return_value = 7
        process.stdin.fileno.return_value = 1; process.stdout.fileno.return_value = 2
        def supervised(*args, **kwargs):
            self.assertFalse(kwargs['handle_signals'])
            self.assertEqual(kwargs['launcher'](['crun', 'exec'], timeout=2), 7)
            events.append('cleanup-and-stop-complete')
            return {'status': 'failed', 'returncode': 7}
        with patch('network_labs.appliances.ssh_radius_shell.login', side_effect=supervised), \
             patch('network_labs.appliances.ssh_radius_shell.subprocess.Popen', return_value=process), \
             patch('network_labs.appliances.ssh_radius_shell.relay', return_value=7):
            serve_shell(manager, 'PC1', connection, 'learner', 'password', terminal=False)
        self.assertEqual(events, [b'SHELL\n', 'cleanup-and-stop-complete', b'E7\n'])

    def test_non_tty_half_close_delivers_input_and_frames_binary_output(self):
        server, client = socket.socketpair()
        process = subprocess.Popen([sys.executable, '-I', '-c',
            'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        payload = b'bytes\x00with\xffnewlines\nand control\x03'
        try:
            client.sendall(payload); client.shutdown(socket.SHUT_WR)
            self.assertEqual(relay(server, process, process.stdout.fileno(), process.stdin.fileno(), terminal=False, seconds=3), 0)
            server.shutdown(socket.SHUT_WR); output = bytearray()
            while True:
                data = client.recv(8192)
                if not data: break
                output.extend(data)
            self.assertEqual(b''.join(base64.b64decode(line[1:]) for line in output.splitlines()), payload)
        finally:
            if process.poll() is None: process.kill()
            process.wait(timeout=1)
            process.stdin.close(); process.stdout.close(); server.close(); client.close()

    def test_fast_large_output_is_drained_without_silent_truncation(self):
        server, client = socket.socketpair(); output = bytearray()
        process = subprocess.Popen([sys.executable, '-I', '-c',
            'import sys; sys.stdout.buffer.write(b"x" * 131072)'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        def consume():
            while True:
                data = client.recv(8192)
                if not data: break
                output.extend(data)
        reader = threading.Thread(target=consume, daemon=True); reader.start()
        try:
            client.shutdown(socket.SHUT_WR)
            self.assertEqual(relay(server, process, process.stdout.fileno(), process.stdin.fileno(), terminal=False, seconds=3), 0)
            server.shutdown(socket.SHUT_WR); reader.join(timeout=2)
            self.assertFalse(reader.is_alive())
            self.assertEqual(b''.join(base64.b64decode(line[1:]) for line in output.splitlines()), b'x' * 131072)
        finally:
            if process.poll() is None: process.kill()
            process.wait(timeout=1)
            process.stdin.close(); process.stdout.close(); server.close(); reader.join(timeout=1); client.close()

    def test_idle_shell_cannot_exceed_deadline(self):
        server, client = socket.socketpair()
        process = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(10)'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                relay(server, process, process.stdout.fileno(), process.stdin.fileno(), terminal=False, seconds=.05)
        finally:
            process.kill(); process.wait(timeout=1)
            process.stdin.close(); process.stdout.close(); server.close(); client.close()
