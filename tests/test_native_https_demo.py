import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext, redirect_stdout
from unittest.mock import patch

from network_labs.appliances.https_demo import certificate, demo
from network_labs.appliances.service_probe_worker import run_probe
from network_labs.appliances.__main__ import main
from test_native_verify import manager_for


class HttpsDemoTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('openssl'), 'OpenSSL required')
    def test_real_temporary_tls_responder_and_explicit_trust(self):
        worker = Path(__file__).resolve().parents[1] / 'network_labs/appliances/https_demo_worker.py'
        with tempfile.TemporaryDirectory() as folder:
            cert, key = certificate(folder, '127.0.0.1')
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            process = subprocess.Popen([sys.executable, '-I', str(worker), '127.0.0.1', '127.0.0.1', str(cert), str(key), '0'],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                ready = json.loads(process.stdout.readline()); self.assertEqual(ready['status'], 'ready')
                request = {'source': '127.0.0.1', 'address': '127.0.0.1', 'target': '127.0.0.1', 'port': ready['port'], 'timeout': 3}
                self.assertEqual(run_probe({**request, 'stage': 'tcp'})['status'], 'passed')
                result = run_probe({**request, 'stage': 'https', 'ca_pem': cert.read_text(), 'path': '/'})
                self.assertEqual(result['status'], 'passed', result); self.assertTrue(result['certificate_verified'])
                output, error = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, error); self.assertEqual(json.loads(output)['status'], 'responded')
            finally:
                if process.poll() is None: process.kill()
                process.communicate()

    def test_failure_cleans_process_and_temporary_key(self):
        manager = manager_for(); actual_popen = subprocess.Popen; spawned = []; locations = []
        def make_cert(folder, address):
            folder = Path(folder); locations.append(folder)
            cert, key = folder / 'cert', folder / 'key'; cert.write_text('demo CA'); key.write_text('private')
            return cert, key
        def launch(*args, **kwargs):
            code = "import json,time; print(json.dumps({'status':'ready','port':443}),flush=True); time.sleep(30)"
            process = actual_popen([sys.executable, '-c', code], **kwargs); spawned.append(process); return process
        with patch('network_labs.appliances.https_demo.certificate', side_effect=make_cert), \
             patch('network_labs.appliances.https_demo.subprocess.Popen', side_effect=launch), \
             patch('network_labs.appliances.service_probe.probe', return_value={'status': 'failed'}):
            report = demo(manager, 'PC1', 'PC2')
        self.assertEqual(report['status'], 'failed'); self.assertIsNotNone(spawned[0].poll())
        self.assertTrue(all(not path.exists() for path in locations)); self.assertNotIn('private', json.dumps(report))
        manager.save.assert_not_called()

    def test_invalid_pair_and_cli(self):
        manager = manager_for(); manager.locked.return_value = nullcontext(manager)
        with patch('network_labs.appliances.https_demo.certificate') as generate:
            for client, server in [('PC1', 'PC1'), ('PC1', 'missing'), ('PC1', 'SW1')]:
                with self.assertRaises(ValueError): demo(manager, client, server)
            generate.assert_not_called()
        with patch('network_labs.appliances.__main__.Manager', return_value=manager), \
             patch('network_labs.appliances.https_demo.demo', return_value={'status': 'passed'}) as action, \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['https-demo', 'micro-lan', 'PC1', 'PC2', '--json']), 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'passed')
        action.assert_called_once_with(manager, 'PC1', 'PC2')
