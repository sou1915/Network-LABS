import hashlib
import json
import socket
import struct
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.radius_accounting_worker import accounting_request, verified_response, account
from network_labs.appliances.radius_accounting import send
from network_labs.appliances.examples import radius_lab

SECRET = 'accounting-test-secret'


def request(**changes):
    return {**dict(source='127.0.0.1', address='127.0.0.1', port=1813, username='learner', secret=SECRET,
                   session_id='aaa-example', event='start', session_seconds=0, terminate_cause=1, timeout=1), **changes}


def reply(packet, attrs=b'', secret=SECRET):
    header = struct.pack('!BBH', 5, packet[1], 20 + len(attrs))
    return header + hashlib.md5(header + packet[4:20] + attrs + secret.encode()).digest() + attrs


class RadiusAccountingTests(unittest.TestCase):
    def test_wire_attributes_and_rfc_authenticators(self):
        for event in ('start', 'stop'):
            packet = accounting_request(request(event=event, session_seconds=12, terminate_cause=5))
            self.assertEqual(packet[0], 4)
            self.assertEqual(struct.unpack('!H', packet[2:4])[0], len(packet))
            self.assertEqual(packet[4:20], hashlib.md5(packet[:4] + b'\0' * 16 + packet[20:] + SECRET.encode()).digest())
            attrs = {}; offset = 20
            while offset < len(packet):
                kind, size = packet[offset:offset + 2]; attrs[kind] = packet[offset + 2:offset + size]; offset += size
            self.assertFalse(set(attrs) & {2, 3, 18, 24})
            self.assertEqual(attrs[44], b'aaa-example')
            self.assertEqual(struct.unpack('!I', attrs[40])[0], 1 if event == 'start' else 2)
            if event == 'stop':
                self.assertEqual(struct.unpack('!I', attrs[46])[0], 12)
                self.assertEqual(struct.unpack('!I', attrs[49])[0], 5)
            else: self.assertFalse(set(attrs) & {46, 49})
            valid = reply(packet)
            self.assertTrue(verified_response(valid, packet, SECRET.encode()))
            for invalid in (valid[:-1], bytes([2]) + valid[1:], valid[:1] + bytes([(packet[1] + 1) % 256]) + valid[2:],
                            reply(packet, b'\x01\x01'), reply(packet, b'\x00\x02'), reply(packet, secret='incorrect-secret')):
                self.assertFalse(verified_response(invalid, packet, SECRET.encode()))

    def test_real_udp_start_stop_discard_bad_mac_and_wrong_peer(self):
        errors = []; received = []
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1', 0)); server.settimeout(2)
            def responder():
                try:
                    for _ in range(2):
                        packet, peer = server.recvfrom(4096); received.append(packet)
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:
                            other.sendto(reply(packet), peer)
                        server.sendto(reply(packet, secret='wrong-secret'), peer)
                        server.sendto(reply(packet), peer)
                except BaseException as error: errors.append(error)
            thread = threading.Thread(target=responder); thread.start()
            for event in ('start', 'stop'):
                result = account(request(port=server.getsockname()[1], event=event))
                self.assertEqual(result['status'], 'passed', result); self.assertTrue(result['response_verified'])
                self.assertGreaterEqual(result['discarded_responses'], 1)
                self.assertNotIn(SECRET, str(result))
            thread.join(3)
            self.assertFalse(thread.is_alive()); self.assertEqual(errors, [])
            self.assertEqual(len(received), 2)

    def test_silence_and_bad_packet_flood_are_bounded_without_retries(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1', 0)); server.settimeout(1)
            result = account(request(port=server.getsockname()[1], timeout=.05))
            self.assertEqual(result['error'], 'TIMEOUT'); server.recvfrom(4096)
            server.settimeout(.02)
            with self.assertRaises(TimeoutError): server.recvfrom(4096)
            def flood():
                packet, peer = server.recvfrom(4096)
                for _ in range(64): server.sendto(reply(packet, secret='wrong-secret'), peer)
            server.settimeout(1); thread = threading.Thread(target=flood); thread.start()
            result = account(request(port=server.getsockname()[1]))
            thread.join(2)
            self.assertEqual(result['error'], 'PACKET_LIMIT'); self.assertEqual(result['discarded_responses'], 64)
            self.assertEqual(result['requests_sent'], 1)

    def test_wrapper_keeps_secret_on_stdin_and_rejects_unverified_worker_output(self):
        manager = Mock(); manager.read.return_value = {'phase': 'running', 'spec': radius_lab(
            '/rootfs', SECRET, 'a' * 64, allow_shell=True, accounting=True)}
        valid = {'status': 'passed', 'response_verified': True, 'requests_sent': 1,
                 'discarded_responses': 0, 'response_code': 5, 'error': None, 'unexpected': SECRET}
        manager.ns.return_value = subprocess.CompletedProcess([], 0, json.dumps(valid), '')
        with patch('network_labs.appliances.radius_accounting._endpoint', return_value={'status': 'ready', 'address': '192.0.2.10'}), \
             patch('network_labs.appliances.radius_accounting._json_read', return_value={'records': [{'dev': 'eth0'}]}):
            result = send(manager, 'PC1', '192.0.2.20', username='learner', secret=SECRET, session_id='aaa-test', event='start')
            self.assertEqual(result['status'], 'passed'); self.assertNotIn(SECRET, str(result))
            self.assertNotIn(SECRET, str(manager.ns.call_args.args))
            self.assertEqual(json.loads(manager.ns.call_args.kwargs['input_text'])['secret'], SECRET)
            valid['response_verified'] = False
            manager.ns.return_value.stdout = json.dumps(valid)
            result = send(manager, 'PC1', '192.0.2.20', username='learner', secret=SECRET, session_id='aaa-test', event='stop')
            self.assertEqual(result['error'], 'WORKER_UNAVAILABLE'); self.assertNotIn(SECRET, str(result))
