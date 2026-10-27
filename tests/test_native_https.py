import io
import json
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from network_labs.appliances.service_probe import probe, load_ca
from network_labs.appliances.service_probe_worker import run_probe
from test_native_service_probe import manager_with_probes
from test_native_verify import completed


@unittest.skipUnless(shutil.which('openssl'), 'OpenSSL certificate generation required')
class HttpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.folder.cleanup)
        cls.root = Path(cls.folder.name)
        for name in ('trusted', 'other'):
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-keyout', str(cls.root / (name + '.key')), '-out', str(cls.root / (name + '.pem')),
                            '-subj', '/CN=secure.lab.test', '-addext', 'subjectAltName=DNS:secure.lab.test'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10)
        cls.ca = load_ca(cls.root / 'trusted.pem')

    def exchange(self, target, ca):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.root / 'trusted.pem', self.root / 'trusted.key')
        listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(4)
        port = listener.getsockname()[1]; requests = []; errors = []
        def serve():
            try:
                raw, _ = listener.accept(); raw.settimeout(3)
                with raw:
                    with context.wrap_socket(raw, server_side=True) as channel:
                        requests.append(channel.recv(4096))
                        channel.sendall(b'HTTP/1.0 200 OK\r\nContent-Length: 0\r\n\r\n')
            except ssl.SSLError:
                pass  # Expected when the client rejects our certificate.
            except Exception as error:
                errors.append(str(error))
        thread = threading.Thread(target=serve, daemon=True); thread.start()
        try:
            result = run_probe({'stage': 'https', 'source': '127.0.0.1', 'address': '127.0.0.1',
                                'target': target, 'port': port, 'path': '/', 'timeout': 3, 'ca_pem': ca})
            thread.join(5)
            self.assertFalse(thread.is_alive()); self.assertFalse(errors, errors)
            return result, requests
        finally:
            listener.close()

    def test_real_tls_validates_trust_and_name_before_sending_head(self):
        result, requests = self.exchange('secure.lab.test', self.ca)
        self.assertEqual(result['status'], 'passed', result)
        self.assertTrue(result['certificate_verified']); self.assertEqual(result['http_status'], 200)
        self.assertTrue(requests[0].startswith(b'HEAD / HTTP/1.0'))
        for target, ca in [('wrong.lab.test', self.ca), ('secure.lab.test', load_ca(self.root / 'other.pem'))]:
            result, requests = self.exchange(target, ca)
            self.assertEqual(result['status'], 'failed', result)
            self.assertEqual(result['error'], 'CERTIFICATE_VERIFY_FAILED'); self.assertFalse(requests)

    def test_api_requires_explicit_ca_and_preserves_only_fingerprint_in_report(self):
        manager = manager_with_probes()
        with self.assertRaises(ValueError): probe(manager, 'PC1', 'secure.lab.test', protocol='https')
        with self.assertRaises(ValueError): probe(manager, 'PC1', 'secure.lab.test', protocol='https', ca_pem='PRIVATE KEY')
        with self.assertRaises(ssl.SSLError): probe(manager, 'PC1', 'secure.lab.test', protocol='https', ca_pem='invalid')
        manager.ns.assert_not_called()
        original = manager.ns.side_effect
        def ns(index, *args, **kwargs):
            if args[1:3] == ('-I', '-c') and json.loads(args[-1])['stage'] == 'https':
                return completed({'stage': 'https', 'status': 'passed', 'certificate_verified': True, 'http_status': 200})
            return original(index, *args, **kwargs)
        manager.ns.side_effect = ns
        report = probe(manager, 'PC1', 'secure.lab.test', protocol='https', ca_pem=self.ca)
        self.assertEqual(report['status'], 'passed'); self.assertEqual(report['port'], 443)
        self.assertEqual([s['stage'] for s in report['stages']], ['dns', 'tcp', 'https'])
        self.assertNotIn('BEGIN CERTIFICATE', json.dumps(report)); self.assertIn('ca_sha256', report['stages'][-1]['request'])
        manager.save.assert_not_called()
