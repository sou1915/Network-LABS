"""RADIUS wire interoperability, authenticated decisions and credential handling."""
import copy
import hashlib
import hmac
import io
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import nullcontext, redirect_stdout
from unittest.mock import patch

from network_labs.appliances.radius import load_credential, probe, validate_credentials
from network_labs.appliances.radius_worker import authenticate, hide_password, response_code
from network_labs.appliances.runtime import run
from network_labs.appliances.__main__ import main
from test_native_verify import manager_for, completed

SECRET = 'private-lab-shared-token'
PASSWORD = 'test-password-longer-than-one-block'


def response(request, code=2, *, attributes=b'', secret=SECRET, bad_mac=False):
    # Independent server implementation: sign MA first using request auth,
    # then calculate the final response authenticator over those attributes.
    attributes = b'\x50\x12' + b'\0' * 16 + attributes
    header = struct.pack('!BBH', code, request[1], 20 + len(attributes))
    signature = hmac.new(secret.encode(), header + request[4:20] + attributes, hashlib.md5).digest()
    if bad_mac: signature = bytes([signature[0] ^ 1]) + signature[1:]
    attributes = attributes[:2] + signature + attributes[18:]
    digest = hashlib.md5(header + request[4:20] + attributes + secret.encode()).digest()
    return header + digest + attributes


def exchange(*, code=2, bad_first=False, subprocess_worker=False, password=PASSWORD):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind(('127.0.0.1', 0)); server.settimeout(3); faults = []
        def serve():
            try:
                request, peer = server.recvfrom(4097)
                assert struct.unpack('!H', request[2:4])[0] == len(request)
                assert request[0] == 1 and request[20:22] == b'\x50\x12'
                unsigned = request[:22] + b'\0' * 16 + request[38:]
                assert hmac.compare_digest(request[22:38], hmac.new(SECRET.encode(), unsigned, hashlib.md5).digest())
                attributes = {}; offset = 20
                while offset < len(request):
                    kind, length = request[offset:offset + 2]
                    assert length >= 2
                    attributes[kind] = request[offset + 2:offset + length]; offset += length
                assert attributes[1] == b'learner'
                assert attributes[4] == socket.inet_aton('127.0.0.1')
                encrypted = attributes[2]; previous = request[4:20]; clear = b''
                for offset in range(0, len(encrypted), 16):
                    chunk = encrypted[offset:offset + 16]
                    mask = hashlib.md5(SECRET.encode() + previous).digest()
                    clear += bytes(x ^ y for x, y in zip(chunk, mask)); previous = chunk
                assert clear.rstrip(b'\0') == password.encode('utf-8')
                assert password.encode() not in request
                if bad_first:
                    server.sendto(response(request, bad_mac=True), peer)
                    server.sendto(b'bad packet', peer)
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rogue:
                        rogue.sendto(response(request), peer)
                server.sendto(response(request, code), peer)
            except Exception as error:
                faults.append(error)
        thread = threading.Thread(target=serve, daemon=True); thread.start()
        request = dict(source='127.0.0.1', address='127.0.0.1', port=server.getsockname()[1],
                       username='learner', password=password, secret=SECRET, timeout=2)
        if subprocess_worker:
            worker = Path(__file__).resolve().parents[1] / 'network_labs/appliances/radius_worker.py'
            process = run([sys.executable, '-I', str(worker)], input_text=json.dumps(request), timeout=4)
            result = json.loads(process.stdout)
            assert SECRET not in str(process.args) and password not in str(process.args)
        else:
            result = authenticate(request)
        thread.join(4)
        if thread.is_alive() or faults: raise AssertionError(faults or 'Server did not finish')
        return result


class RadiusTests(unittest.TestCase):
    def test_pap_matches_rfc2865_section_7_1_known_vector(self):
        authenticator = bytes.fromhex('0f403f9473978057bd83d5cb98f4227a')
        encrypted = hide_password(b'arctangent', b'xyzzy5461', authenticator)
        self.assertEqual(encrypted.hex(), '0dbe708d93d413ce3196e43f782a0aee')

    def test_actual_udp_accept_reject_challenge_and_multiblock_password(self):
        for code, status, decision in ((2, 'passed', 'accepted'), (3, 'failed', 'rejected'), (11, 'blocked', 'challenge')):
            with self.subTest(code=code):
                result = exchange(code=code)
                self.assertEqual(result['status'], status, result)
                self.assertEqual(result['decision'], decision)
                self.assertTrue(result['response_verified'])
                self.assertEqual(result['requests_sent'], 1)

    def test_worker_stdin_and_utf8_password_with_invalid_packets_before_valid_reply(self):
        result = exchange(bad_first=True, subprocess_worker=True, password='mot-é-secret-123456789')
        self.assertEqual(result['status'], 'passed', result)
        # UDP ordering across the rogue socket is unspecified; the two invalid
        # packets sent on the real server socket must precede the valid reply.
        self.assertGreaterEqual(result['discarded_responses'], 2)
        self.assertNotIn(SECRET, json.dumps(result))

    def test_response_requires_both_authenticators_valid_id_and_well_formed_attributes(self):
        request = b'\x01\x17\x00\x14' + bytes(range(16)); secret = SECRET.encode()
        valid = response(request)
        self.assertEqual(response_code(valid, request, secret), 2)
        corrupted = bytearray(valid); corrupted[4] ^= 1
        wrong_id = bytearray(valid); wrong_id[1] ^= 1
        malformed = [b'', b'x' * 4097, bytes(corrupted), bytes(wrong_id), valid + b'x',
                     response(request, bad_mac=True), response(request, attributes=b'\x01\x01'),
                     response(request, attributes=b'\x01\x04x'),
                     response(request, attributes=b'\x50\x12' + b'\0' * 16),
                     response(request, attributes=b'\x50\x03x'), response(request, code=5)]
        for packet in malformed:
            with self.subTest(packet=packet.hex()):
                self.assertIsNone(response_code(packet, request, secret))
        self.assertIsNone(response_code(valid, request, b'wrong-secret'))
        # A valid legacy response authenticator alone must never be sufficient.
        header = b'\x02\x17\x00\x14'
        legacy = header + hashlib.md5(header + request[4:20] + secret).digest()
        self.assertIsNone(response_code(legacy, request, secret))

    def test_silent_server_times_out_without_retry_or_acceptance(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1', 0)); server.settimeout(.05)
            result = authenticate(dict(source='127.0.0.1', address='127.0.0.1', port=server.getsockname()[1],
                                       username='learner', password=PASSWORD, secret=SECRET, timeout=.08))
            self.assertEqual(result['error'], 'TIMEOUT'); self.assertFalse(result['response_verified'])
            self.assertEqual(result['requests_sent'], 1)
            server.recvfrom(4097)
            with self.assertRaises(socket.timeout): server.recvfrom(4097)

    def test_invalid_response_flood_stops_at_packet_limit(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1', 0)); server.settimeout(2)
            faults = []
            def flood():
                try:
                    _, peer = server.recvfrom(4097)
                    for _ in range(64): server.sendto(b'invalid', peer)
                except Exception as error:
                    faults.append(error)
            thread = threading.Thread(target=flood, daemon=True); thread.start()
            result = authenticate(dict(source='127.0.0.1', address='127.0.0.1', port=server.getsockname()[1],
                                       username='learner', password=PASSWORD, secret=SECRET, timeout=2))
            thread.join(3)
            self.assertFalse(thread.is_alive()); self.assertEqual(faults, [])
            self.assertEqual(result['status'], 'unknown'); self.assertEqual(result['error'], 'PACKET_LIMIT')
            self.assertEqual(result['discarded_responses'], 64); self.assertFalse(result['response_verified'])

    def test_nonready_local_targets_and_pending_changes_do_not_send_authentication(self):
        options = dict(username='learner', password=PASSWORD, secret=SECRET)
        manager = manager_for(); manager.read.return_value['pending_spec'] = {}
        with self.assertRaises(RuntimeError): probe(manager, 'PC1', '203.0.113.10', **options)
        manager.ns.assert_not_called()
        manager = manager_for()
        result = probe(manager, 'PC1', '192.0.2.100', **options)
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(all('input_text' not in call.kwargs for call in manager.ns.call_args_list))
        manager = manager_for()
        with patch('network_labs.appliances.radius._endpoint', return_value={'status': 'blocked'}):
            result = probe(manager, 'PC1', '203.0.113.10', **options)
        self.assertEqual(result['status'], 'blocked'); manager.ns.assert_not_called()

    def test_credential_files_private_bounded_and_validation_precedes_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'password'; path.write_text(PASSWORD + '\n'); path.chmod(0o600)
            self.assertEqual(load_credential(path), PASSWORD)
            path.chmod(0o644)
            with self.assertRaises(ValueError): load_credential(path)
            path.chmod(0o600); path.write_bytes(b'x' * 131)
            with self.assertRaises(ValueError): load_credential(path)
            link = Path(folder) / 'link'; link.symlink_to(path)
            with self.assertRaises(OSError): load_credential(link)
        for username, password, secret in (('bad\n', PASSWORD, SECRET), ('learner', '', SECRET),
                ('learner', 'é' * 65, SECRET), ('learner', 'a\0b', SECRET), ('learner', PASSWORD, 'short')):
            manager = manager_for()
            with self.subTest(username=username), self.assertRaises(ValueError):
                probe(manager, 'PC1', '203.0.113.10', username=username, password=password, secret=secret)
            manager.read.assert_not_called(); manager.ns.assert_not_called()
        validate_credentials('learner', 'é' * 64, SECRET)

    def test_api_sends_secrets_only_on_stdin_and_does_not_change_state(self):
        manager = manager_for(); before = copy.deepcopy(manager.read())
        original = manager.ns.side_effect
        success = dict(status='passed', decision='accepted', response_verified=True,
                       requests_sent=1, discarded_responses=0, response_code=2)
        def ns(index, *args, **options):
            if 'input_text' in options:
                self.assertNotIn(SECRET, str(args)); self.assertNotIn(PASSWORD, str(args))
                request = json.loads(options['input_text'])
                self.assertEqual(request['secret'], SECRET); self.assertEqual(request['password'], PASSWORD)
                return completed(dict(success, extra=SECRET))
            return original(index, *args, **options)
        manager.ns.side_effect = ns
        result = probe(manager, 'PC1', '203.0.113.10', username='learner', password=PASSWORD, secret=SECRET)
        self.assertEqual(result['status'], 'passed', result)
        self.assertNotIn(SECRET, json.dumps(result)); self.assertNotIn(PASSWORD, json.dumps(result))
        self.assertEqual(manager.read(), before); manager.save.assert_not_called()
        success['response_verified'] = False
        result = probe(manager, 'PC1', '203.0.113.10', username='learner', password=PASSWORD, secret=SECRET)
        self.assertEqual(result['status'], 'unknown')
        success.update(status='unknown', error=SECRET)
        result = probe(manager, 'PC1', '203.0.113.10', username='learner', password=PASSWORD, secret=SECRET)
        self.assertEqual(result['error'], 'WORKER_UNAVAILABLE')
        self.assertNotIn(SECRET, json.dumps(result))

    def test_cli_and_runtime_reject_persistent_logging_of_stdin_payload(self):
        manager = manager_for(); manager.locked.return_value = nullcontext(manager)
        with patch('network_labs.appliances.__main__.Manager', return_value=manager), \
             patch('network_labs.appliances.radius.load_credential', side_effect=[PASSWORD, SECRET]), \
             patch('network_labs.appliances.radius.probe', return_value={'status': 'passed'}) as action, \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['radius-auth', 'lab', 'PC1', '192.0.2.20', '--username', 'learner',
                                  '--password-file', 'password', '--secret-file', 'secret', '--json']), 0)
        self.assertEqual(json.loads(output.getvalue()), {'status': 'passed'})
        action.assert_called_once_with(manager, 'PC1', '192.0.2.20', username='learner', password=PASSWORD, secret=SECRET, timeout=3)
        with tempfile.TemporaryDirectory() as folder:
            logfile = Path(folder) / 'log'
            with self.assertRaises(ValueError): run(['echo'], log=logfile, input_text=SECRET)
            self.assertFalse(logfile.exists())
