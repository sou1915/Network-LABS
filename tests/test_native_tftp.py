import hashlib
import io
import json
import socket
import struct
import threading
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from unittest.mock import patch

from network_labs.appliances.tftp_worker import read as wire_read
from network_labs.appliances.tftp import read, render
from network_labs.appliances.__main__ import main
from test_native_verify import manager_for, completed


def exchange(data, *, error=None, inject_other_tid=False):
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); listener.bind(('127.0.0.1', 0)); listener.settimeout(3)
    port = listener.getsockname()[1]; received = []; faults = []
    def server():
        try:
            request, peer = listener.recvfrom(1024); received.append(request)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as transfer:
                transfer.bind(('127.0.0.1', 0)); transfer.settimeout(3)
                if error is not None:
                    transfer.sendto(struct.pack('!HH', 5, error) + b'error\x00', peer); return
                block = 1
                while True:
                    chunk = data[(block - 1) * 512:block * 512]
                    if block == 2 and inject_other_tid:
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rogue:
                            rogue.sendto(struct.pack('!HH', 3, block) + b'wrong', peer)
                    transfer.sendto(struct.pack('!HH', 3, block) + chunk, peer)
                    if (block - 1) * 512 + len(chunk) > 65536: return
                    ack, sender = transfer.recvfrom(1024)
                    if sender != peer or ack != struct.pack('!HH', 4, block):
                        raise AssertionError('Incorrect TFTP acknowledgement')
                    if len(chunk) < 512: return
                    block += 1
        except Exception as exc:
            faults.append(str(exc))
    thread = threading.Thread(target=server, daemon=True); thread.start()
    try:
        result = wire_read({'source': '127.0.0.1', 'address': '127.0.0.1', 'port': port, 'filename': 'sample.bin', 'timeout': 3})
        thread.join(4)
        if thread.is_alive(): raise AssertionError('TFTP test server did not finish')
        if faults: raise AssertionError(faults)
        return result, received
    finally:
        listener.close()


class NativeTftpTests(unittest.TestCase):
    def test_real_udp_read_empty_multiblock_and_wrong_transfer_id(self):
        for data in (b'', b'A' * 512, b'hello' * 150, b'z' * 65536):
            with self.subTest(size=len(data)):
                result, packets = exchange(data, inject_other_tid=True)
                self.assertEqual(packets[0], b'\x00\x01sample.bin\x00octet\x00')
                self.assertEqual(result['status'], 'passed')
                self.assertEqual(result['bytes_received'], len(data))
                self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())

    def test_server_error_and_transfer_size_limit_are_not_success(self):
        result, _ = exchange(b'', error=1)
        self.assertEqual(result['status'], 'failed'); self.assertEqual(result['error_code'], 1)
        result, _ = exchange(b'x' * 65537)
        self.assertEqual(result['status'], 'failed'); self.assertEqual(result['error'], 'SIZE_LIMIT')
        self.assertIsNone(result['sha256'])

    def test_manifest_validation_and_hash_mismatch(self):
        manager = manager_for()
        for filename in ('../passwd', '/etc/passwd', 'a/b', '', 'x\n'):
            with self.subTest(filename=filename), self.assertRaises(ValueError): read(manager, 'PC1', '203.0.113.10', filename)
        manager.ns.assert_not_called()
        original = manager.ns.side_effect
        def ns(index, *args, **kwargs):
            if args[1:3] == ('-I', '-c'):
                return completed({'status': 'passed', 'bytes_received': 1, 'sha256': 'a' * 64})
            return original(index, *args, **kwargs)
        manager.ns.side_effect = ns
        report = read(manager, 'PC1', '203.0.113.10', 'image.bin', expected_sha256='b' * 64)
        self.assertEqual(report['status'], 'failed'); self.assertFalse(report['hash_matches'])
        self.assertIn('différent', render(report)); manager.save.assert_not_called()
        report = read(manager, 'PC1', '203.0.113.10', 'image.bin', expected_sha256='A' * 64)
        self.assertEqual(report['status'], 'passed'); self.assertTrue(report['hash_matches'])

    def test_cli_returns_transfer_status_and_requires_literal_server(self):
        manager = manager_for(); manager.locked.return_value = nullcontext(manager)
        result = {'status': 'passed'}
        with patch('network_labs.appliances.__main__.Manager', return_value=manager), \
             patch('network_labs.appliances.tftp.read', return_value=result) as action, \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['tftp-read', 'lab', 'PC1', '192.0.2.1', 'f.bin', '--json']), 0)
        self.assertEqual(json.loads(output.getvalue()), result)
        action.assert_called_once_with(manager, 'PC1', '192.0.2.1', 'f.bin', timeout=5, expected_sha256=None)
        with self.assertRaises(ValueError): read(manager, 'PC1', 'example.test', 'f.bin')
