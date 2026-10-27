import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from network_labs.appliances.service_probe_worker import ntp_encode, sntp_response
from network_labs.appliances.sntp_demo import demo
from test_native_verify import manager_for


class SntpDemoTests(unittest.TestCase):
    def test_temporary_server_uses_real_udp_and_exits_after_valid_request(self):
        path = Path(__file__).resolve().parents[1] / 'network_labs/appliances/sntp_demo_worker.py'
        process = subprocess.Popen([sys.executable, '-I', str(path), '127.0.0.1', '127.0.0.1', '0'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            ready = json.loads(process.stdout.readline()); self.assertEqual(ready['status'], 'ready')
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(2); client.connect(('127.0.0.1', ready['port']))
                client.send(b'bad')
                t1 = time.time(); sent = ntp_encode(t1)
                client.send(b'\x23' + bytes(39) + sent)
                reply = client.recv(1024); t4 = time.time()
                self.assertEqual(sntp_response(reply, sent, t1, t4)['stratum'], 2)
            output, _ = process.communicate(timeout=3)
            self.assertEqual(json.loads(output)['status'], 'responded'); self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None: process.kill()
            process.communicate()

    def test_invalid_selection_never_launches_server(self):
        manager = manager_for()
        with patch('network_labs.appliances.sntp_demo.subprocess.Popen') as launch:
            for client, server in [('PC1', 'PC1'), ('PC1', 'missing'), ('PC1', 'SW1')]:
                with self.assertRaises(ValueError): demo(manager, client, server)
            launch.assert_not_called()
        manager.save.assert_not_called()
