import hashlib
import io
import json
import socket
import struct
import threading
import time
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from unittest.mock import patch

from network_labs.appliances.tftp_worker import read as wire_read
from network_labs.appliances.tftp import read, render
from network_labs.appliances.__main__ import main
from test_native_verify import manager_for, completed


def exchange(data, *, error=None, inject_other_tid=False, repeat_final=False):
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
                    if len(chunk) < 512:
                        if repeat_final:
                            # Discard the first final ACK as if lost in flight,
                            # then retransmit final DATA after a short delay.
                            time.sleep(.03)
                            transfer.sendto(struct.pack('!HH', 3, block) + chunk, peer)
                            ack, sender = transfer.recvfrom(1024)
                            if (ack, sender) != (struct.pack('!HH', 4, block), peer):
                                raise AssertionError('Missing repeated final ACK')
                        return
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
    def test_final_ack_loss_with_empty_exact_block_and_multiblock_files(self):
        for data in (b'', b'x' * 512, b'bin\x00' * 170):
            with self.subTest(size=len(data)):
                result, _ = exchange(data, repeat_final=True)
                self.assertEqual(result['status'], 'passed', result)
                self.assertEqual(result['bytes_received'], len(data))
                self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
                self.assertEqual(result['final_ack'], {'status': 'elapsed', 'duplicate_acks': 1})
                self.assertEqual(result['retransmissions'], 0)

    def test_dally_ignores_wrong_peer_and_changed_data_and_keeps_packet_budget(self):
        from network_labs.appliances.tftp_worker import dally
        final = struct.pack('!HH', 3, 2) + b'file'; ack = struct.pack('!HH', 4, 2)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client, \
             socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server, \
             socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rogue:
            for sock in (client, server, rogue): sock.bind(('127.0.0.1', 0))
            server.settimeout(.05); rogue.settimeout(.05)
            rogue.sendto(final, client.getsockname())
            server.sendto(final + b'changed', client.getsockname())
            server.sendto(struct.pack('!HH', 3, 3) + b'file', client.getsockname())
            server.sendto(final, client.getsockname())
            result = dally(client, server.getsockname(), final, ack, time.monotonic() + 2, 252)
            self.assertEqual(result, {'status': 'packet_limit', 'duplicate_acks': 1})
            self.assertEqual(server.recvfrom(1024)[0], ack)
            with self.assertRaises(socket.timeout): server.recvfrom(1024)
            with self.assertRaises(socket.timeout): rogue.recvfrom(1024)

    def test_dally_respects_original_deadline_even_with_duplicate_traffic(self):
        from network_labs.appliances.tftp_worker import dally
        final = struct.pack('!HH', 3, 1) + b'file'; ack = struct.pack('!HH', 4, 1)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client, \
             socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            for sock in (client, server): sock.bind(('127.0.0.1', 0))
            server.sendto(final, client.getsockname())
            started = time.monotonic()
            result = dally(client, server.getsockname(), final, ack, started + .08, 1)
            self.assertEqual(result, {'status': 'deadline', 'duplicate_acks': 1})
            self.assertLess(time.monotonic() - started, .6)

    def test_real_udp_recovers_lost_request_data_and_ack_without_double_hashing(self):
        data = b'A' * 512 + b'final block'
        for loss in ('request', 'data', 'ack'):
            with self.subTest(loss=loss), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
                server.bind(('127.0.0.1', 0)); server.settimeout(3)
                faults = []
                def serve():
                    try:
                        rrq, client = server.recvfrom(1024)
                        if loss == 'request':
                            repeated, sender = server.recvfrom(1024)
                            self.assertEqual((repeated, sender), (rrq, client))
                        # Use a separate transfer port, just like a real server.
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as transfer:
                            transfer.bind(('127.0.0.1', 0)); transfer.settimeout(3)
                            first = struct.pack('!HH', 3, 1) + data[:512]
                            transfer.sendto(first, client)
                            ack, sender = transfer.recvfrom(1024)
                            self.assertEqual((ack, sender), (struct.pack('!HH', 4, 1), client))
                            if loss == 'ack':
                                # Simulate an ACK lost on its way to the server.
                                transfer.sendto(first, client)
                                repeated, sender = transfer.recvfrom(1024)
                                self.assertEqual((repeated, sender), (ack, client))
                            if loss == 'data':
                                # DATA 2 is dropped. Client retries ACK 1 to
                                # the selected transfer port, never UDP/69.
                                repeated, sender = transfer.recvfrom(1024)
                                self.assertEqual((repeated, sender), (ack, client))
                            transfer.sendto(struct.pack('!HH', 3, 2) + data[512:], client)
                            final, sender = transfer.recvfrom(1024)
                            self.assertEqual((final, sender), (struct.pack('!HH', 4, 2), client))
                    except Exception as error:
                        faults.append(error)
                thread = threading.Thread(target=serve, daemon=True); thread.start()
                result = wire_read({'source': '127.0.0.1', 'address': '127.0.0.1',
                                    'port': server.getsockname()[1], 'filename': 'f', 'timeout': 3})
                thread.join(4)
                self.assertFalse(thread.is_alive()); self.assertEqual(faults, [])
                self.assertEqual(result['status'], 'passed', result)
                self.assertEqual(result['bytes_received'], len(data))
                self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
                self.assertEqual(result['retransmissions'], 0 if loss == 'ack' else 1)

    def test_retry_limit_and_absolute_deadline_on_silent_real_udp_server(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1', 0)); server.settimeout(.05)
            request = {'source': '127.0.0.1', 'address': '127.0.0.1',
                       'port': server.getsockname()[1], 'filename': 'f', 'timeout': 2}
            with patch('network_labs.appliances.tftp_worker.RETRY_SECONDS', .02):
                result = wire_read(request)
            self.assertEqual(result['error'], 'RETRY_LIMIT', result)
            self.assertEqual(result['retransmissions'], 3)
            packets = []
            try:
                while True: packets.append(server.recvfrom(1024)[0])
            except socket.timeout:
                pass
            self.assertEqual(len(packets), 4)
            self.assertTrue(all(packet == packets[0] for packet in packets))
            request['timeout'] = .12
            started = time.monotonic()
            result = wire_read(request)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['error'], 'TimeoutError')
            self.assertIsNone(result['sha256'])
            self.assertLess(time.monotonic() - started, .7)

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
