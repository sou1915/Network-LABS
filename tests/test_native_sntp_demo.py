import json
import io
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from contextlib import nullcontext, redirect_stdout

from network_labs.appliances.service_probe_worker import ntp_encode, sntp_response
from network_labs.appliances.sntp_demo import demo
from test_native_verify import manager_for


class SntpDemoTests(unittest.TestCase):
    def test_cli_passes_offset_without_interpreting_it_as_clock_setting(self):
        from network_labs.appliances.__main__ import main
        manager = manager_for(); manager.locked.return_value = nullcontext(manager)
        report = {'status': 'passed', 'server_offset_seconds': 45}
        with patch('network_labs.appliances.__main__.Manager', return_value=manager), \
             patch('network_labs.appliances.sntp_demo.demo', return_value=report) as run_demo, \
             redirect_stdout(io.StringIO()) as output:
            code = main(['sntp-demo', 'micro-lan', 'PC1', 'PC2', '--server-offset-seconds', '45', '--samples', '3', '--json'])
        self.assertEqual(code, 0); self.assertEqual(json.loads(output.getvalue()), report)
        run_demo.assert_called_once_with(manager, 'PC1', 'PC2', server_offset_seconds=45, samples=3)

    def test_temporary_server_uses_real_udp_and_exits_after_valid_request(self):
        for offset in (-30, 0, 45):
            with self.subTest(offset=offset):
                self.check_wire_offset(offset)

    def check_wire_offset(self, offset):
        path = Path(__file__).resolve().parents[1] / 'network_labs/appliances/sntp_demo_worker.py'
        process = subprocess.Popen([sys.executable, '-I', str(path), '127.0.0.1', '127.0.0.1', '0', str(offset), '3'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            ready = json.loads(process.stdout.readline()); self.assertEqual(ready['status'], 'ready')
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(2); client.connect(('127.0.0.1', ready['port']))
                client.send(b'bad')
                for _ in range(3):
                    t1 = time.time(); sent = ntp_encode(t1)
                    client.send(b'\x23' + bytes(39) + sent)
                    reply = client.recv(1024); t4 = time.time()
                    measurement = sntp_response(reply, sent, t1, t4)
                    self.assertEqual(measurement['stratum'], 2)
                    self.assertAlmostEqual(measurement['offset_seconds'], offset, delta=.5)
            output, _ = process.communicate(timeout=3)
            self.assertEqual(json.loads(output), {'status': 'responded', 'count': 3}); self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None: process.kill()
            process.communicate()

    def test_invalid_selection_never_launches_server(self):
        manager = manager_for()
        with patch('network_labs.appliances.sntp_demo.subprocess.Popen') as launch:
            for client, server in [('PC1', 'PC1'), ('PC1', 'missing'), ('PC1', 'SW1')]:
                with self.assertRaises(ValueError): demo(manager, client, server)
            for value in (-86401, 86401, True, 1.5):
                with self.assertRaises(ValueError): demo(manager, 'PC1', 'PC2', server_offset_seconds=value)
            for value in (0, 6, True, 1.5):
                with self.assertRaises(ValueError): demo(manager, 'PC1', 'PC2', samples=value)
            launch.assert_not_called()
        manager.save.assert_not_called()

    def test_multiple_samples_stop_on_failure_and_cleanup_responder(self):
        manager = manager_for(); real_popen = subprocess.Popen; spawned = []
        def launch(*args, **kwargs):
            code = "import json,time; print(json.dumps({'status':'ready','port':123}),flush=True); time.sleep(30)"
            process = real_popen([sys.executable, '-c', code], **kwargs); spawned.append(process); return process
        outcomes = [{'status': 'passed'}, {'status': 'failed'}]
        with patch('network_labs.appliances.sntp_demo.subprocess.Popen', side_effect=launch), \
             patch('network_labs.appliances.service_probe.probe', side_effect=outcomes) as call:
            report = demo(manager, 'PC1', 'PC2', samples=3)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(len(report['probes']), 2); self.assertEqual(call.call_count, 2)
        self.assertIsNotNone(spawned[0].poll()); manager.save.assert_not_called()

    def test_multiple_samples_require_matching_responder_count(self):
        manager = manager_for(); real_popen = subprocess.Popen
        for count, expected in ((3, 'passed'), (2, 'unknown')):
            def launch(*args, **kwargs):
                code = ("import json,time; print(json.dumps({'status':'ready','port':123}),flush=True); "
                        "time.sleep(.1); print(json.dumps({'status':'responded','count':" + str(count) + "}),flush=True)")
                return real_popen([sys.executable, '-c', code], **kwargs)
            with patch('network_labs.appliances.sntp_demo.subprocess.Popen', side_effect=launch), \
                 patch('network_labs.appliances.service_probe.probe', return_value={'status': 'passed'}) as call:
                report = demo(manager, 'PC1', 'PC2', samples=3)
            self.assertEqual(report['status'], expected); self.assertEqual(len(report['probes']), 3)
            self.assertEqual(call.call_count, 3)
