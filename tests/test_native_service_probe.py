"""Bounded service diagnostics: protocol evidence, fault boundaries and no mutation."""
import copy
import io
import json
import socket
import struct
import subprocess
import threading
import unittest
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from network_labs.appliances.service_probe import probe, render
from network_labs.appliances.service_probe_worker import dns_answers, run_probe, ntp_encode, ntp_decode, sntp_response
from network_labs.appliances.__main__ import main
from test_native_verify import manager_for, completed


def manager_with_probes():
    manager = manager_for(); original_ns = manager.ns.side_effect; original_crun = manager.crun.side_effect
    def ns(index, *args, **kwargs):
        if len(args) > 2 and args[1:3] == ('-I', '-c'):
            request = json.loads(args[-1]); stage = request['stage']
            return completed({'stage': stage, 'status': 'passed', **({'rcode': 0, 'addresses': ['203.0.113.10']} if stage == 'dns' else {'connected': True}), **({'http_status': 200} if stage == 'http' else {}), **({'offset_seconds': .25, 'round_trip_seconds': .1, 'stratum': 2} if stage == 'sntp' else {})})
        return original_ns(index, *args, **kwargs)
    manager.ns.side_effect = ns
    manager.crun.side_effect = lambda *a, **k: completed('nameserver 198.18.0.4\n') if a[:3] == ('exec', 'PC1', '/bin/cat') else original_crun(*a, **k)
    return manager


class ServiceProbeTests(unittest.TestCase):
    def test_sntp_selection_uses_udp_stage_without_tcp_or_clock_mutation(self):
        manager = manager_with_probes(); before = copy.deepcopy(manager.read())
        result = probe(manager, 'PC1', '203.0.113.10', protocol='sntp')
        self.assertEqual([s['stage'] for s in result['stages']], ['sntp'])
        self.assertEqual(result['port'], 123); self.assertEqual(manager.read(), before)
        self.assertIn('+0.250000 s', render(result))
        manager.save.assert_not_called()
        with self.assertRaises(ValueError): probe(manager, 'PC1', '203.0.113.10', protocol='sntp', port=123)

    def test_sntp_response_checks_matching_and_2036_era(self):
        t1 = 2085978497.0; sent = ntp_encode(t1)
        packet = bytearray(48); packet[0] = 0x24; packet[1] = 2
        packet[24:32] = sent; packet[32:40] = ntp_encode(t1 + .2); packet[40:48] = ntp_encode(t1 + .3)
        result = sntp_response(bytes(packet), sent, t1, t1 + .5)
        self.assertAlmostEqual(result['offset_seconds'], 0, places=5)
        self.assertAlmostEqual(result['round_trip_seconds'], .4, places=5)
        self.assertAlmostEqual(ntp_decode(ntp_encode(t1), t1), t1, places=5)
        for index, value in ((0, 0xe4), (0, 0x23), (1, 0), (24, packet[24] ^ 1)):
            bad = bytearray(packet); bad[index] = value
            with self.assertRaises(ValueError): sntp_response(bytes(bad), sent, t1, t1 + .5)
        with self.assertRaises(ValueError): sntp_response(bytes(packet[:47]), sent, t1, t1 + .5)

    def test_sntp_real_udp_exchange_with_isolated_test_responder(self):
        import time
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); server.bind(('127.0.0.1', 0)); server.settimeout(3)
        port = server.getsockname()[1]; seen = []
        def respond():
            request, peer = server.recvfrom(1024); seen.append(request)
            reply = bytearray(48); reply[0] = 0x24; reply[1] = 2
            reply[24:32] = request[40:48]; reply[32:40] = ntp_encode(time.time()); reply[40:48] = ntp_encode(time.time())
            server.sendto(reply, peer)
        thread = threading.Thread(target=respond); thread.start()
        real_socket = socket.socket
        class TestSocket:
            def __init__(self, *args): self.sock = real_socket(*args)
            def __enter__(self): return self
            def __exit__(self, *args): self.sock.close()
            def __getattr__(self, name): return getattr(self.sock, name)
            def connect(self, address): self.sock.connect((address[0], port))
        try:
            with patch('network_labs.appliances.service_probe_worker.socket.socket', TestSocket):
                result = run_probe({'stage': 'sntp', 'source': '127.0.0.1', 'address': '127.0.0.1', 'timeout': 2})
            thread.join(3)
            self.assertEqual(result['status'], 'passed'); self.assertEqual(result['stratum'], 2)
            self.assertEqual(len(seen[0]), 48); self.assertEqual(seen[0][0], 0x23)
        finally:
            thread.join(3); server.close()
    def test_layered_success_uses_guest_resolver_and_observed_source_without_mutation(self):
        manager = manager_with_probes(); before = copy.deepcopy(manager.read())
        result = probe(manager, 'PC1', 'web.lab.test')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual([s['stage'] for s in result['stages']], ['dns', 'tcp', 'http'])
        self.assertEqual(result['stages'][0]['request']['server'], '198.18.0.4')
        self.assertTrue(all(s['request']['source'] == '192.0.2.100' for s in result['stages']))
        self.assertEqual(manager.read(), before); manager.save.assert_not_called()
        self.assertIn('RÉUSSI', render(result))
        result = probe(manager, 'PC1', '203.0.113.10', protocol='tcp', port=80)
        self.assertEqual([s['stage'] for s in result['stages']], ['tcp'])

    def test_failed_layer_stops_later_probes_and_unknown_worker_is_not_failure(self):
        for failed in ('dns', 'tcp', 'http'):
            manager = manager_with_probes(); original = manager.ns.side_effect
            def ns(index, *args, **kwargs):
                if len(args) > 2 and args[1:3] == ('-I', '-c') and json.loads(args[-1])['stage'] == failed:
                    return completed({'stage': failed, 'status': 'failed'})
                return original(index, *args, **kwargs)
            manager.ns.side_effect = ns
            report = probe(manager, 'PC1', 'web.lab.test')
            self.assertEqual(report['status'], 'failed'); self.assertEqual(report['stages'][-1]['stage'], failed)
        for output in ('invalid', '[]', '{}'):
            manager = manager_with_probes(); original = manager.ns.side_effect
            manager.ns.side_effect = lambda i, *a, **k: completed(output) if a[1:3] == ('-I', '-c') else original(i, *a, **k)
            self.assertEqual(probe(manager, 'PC1', 'web.lab.test')['status'], 'unknown')

    def test_missing_multiple_or_host_resolver_never_falls_back(self):
        for resolver in ('', 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n', 'nameserver ::1\n', 'nameserver 127.0.0.1\n'):
            manager = manager_with_probes(); original = manager.crun.side_effect
            manager.crun.side_effect = lambda *a, **k: completed(resolver) if a[0] == 'exec' else original(*a, **k)
            report = probe(manager, 'PC1', 'web.lab.test')
            self.assertEqual(report['status'], 'unknown')
            self.assertFalse(any(c.args[1:3] == ('-I', '-c') for c in manager.ns.call_args_list))

    def test_validation_and_pending_state_precede_probes(self):
        for target, kwargs in [('http://web.lab.test', {}), ('127.0.0.1', {}), ('999.1.1.1', {}),
                               ('web.lab.test', {'timeout': True}), ('web.lab.test', {'port': 0}),
                               ('web.lab.test', {'path': '/\r\nHost: injected'}), ('web.lab.test', {'protocol': 'tcp'}),
                               ('203.0.113.10', {'protocol': 'dns'})]:
            manager = manager_with_probes()
            with self.assertRaises(ValueError):
                probe(manager, 'PC1', target, **kwargs)
            manager.ns.assert_not_called(); manager.crun.assert_not_called()
        manager = manager_with_probes(); manager.read.return_value['pending_spec'] = {}
        from network_labs.appliances.runtime import RuntimeFailure
        with self.assertRaises(RuntimeFailure):
            probe(manager, 'PC1', 'web.lab.test')
        manager.ns.assert_not_called()

    def test_cli_json_and_exit_code(self):
        manager = manager_with_probes(); manager.locked.return_value = nullcontext(manager)
        with patch('network_labs.appliances.__main__.Manager', return_value=manager), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['probe', 'verify-test', 'PC1', 'web.lab.test', '--json']), 0)
            self.assertEqual(json.loads(output.getvalue())['stages'][-1]['http_status'], 200)

    def test_dns_wire_validation_and_negative_answers(self):
        name = 'web.lab.test'; question = b'\x03web\x03lab\x04test\x00\x00\x01\x00\x01'
        answer = b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 60, 4) + socket.inet_aton('203.0.113.10')
        packet = struct.pack('!6H', 42, 0x8180, 1, 1, 0, 0) + question + answer
        self.assertEqual(dns_answers(packet, 42, name), (0, ['203.0.113.10']))
        self.assertEqual(dns_answers(struct.pack('!6H', 42, 0x8183, 1, 0, 0, 0) + question, 42, name), (3, []))
        for bad in (packet[:6], packet[:-1], packet[:12] + b'\xc0\x0c', struct.pack('!6H', 42, 0x8380, 1, 1, 0, 0) + question + answer):
            with self.assertRaises(ValueError):
                dns_answers(bad, 42, name)
        with self.assertRaises(ValueError):
            dns_answers(packet, 43, name)
        with self.assertRaises(ValueError):
            dns_answers(packet, 42, 'other.lab.test')

    def test_real_tcp_and_http_status_without_redirect_following(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_HEAD(self):
                seen.append(self.path)
                self.send_response(200 if self.path == '/' else 302 if self.path == '/redirect' else 404)
                self.send_header('Location', 'http://example.invalid/'); self.end_headers()
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        request = dict(source='127.0.0.1', address='127.0.0.1', target='web.lab.test', port=server.server_port, timeout=1, path='/')
        try:
            self.assertEqual(run_probe(dict(request, stage='tcp'))['status'], 'passed')
            for path, code in (('/', 200), ('/missing', 404), ('/redirect', 302)):
                report = run_probe(dict(request, stage='http', path=path))
                self.assertEqual(report['http_status'], code)
                self.assertEqual(report['status'], 'passed' if code == 200 else 'failed')
            self.assertEqual(seen, ['/', '/missing', '/redirect'])
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertEqual(run_probe(dict(request, stage='tcp'))['status'], 'failed')

    def test_http_stall_and_non_http_listener_do_not_pass(self):
        for payload in (b'SSH-2.0-example\r\n', None):
            listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(1)
            release = threading.Event()
            def serve():
                with listener.accept()[0] as connection:
                    connection.recv(2048)
                    if payload is not None:
                        connection.sendall(payload)
                    else:
                        release.wait(3)
            thread = threading.Thread(target=serve, daemon=True); thread.start()
            try:
                report = run_probe(dict(stage='http', source='127.0.0.1', address='127.0.0.1', target='web.lab.test',
                                        port=listener.getsockname()[1], timeout=1, path='/'))
                self.assertEqual(report['status'], 'unknown' if payload else 'failed')
                self.assertTrue(report['connected'])
            finally:
                release.set(); thread.join(4); listener.close()

    def test_ambiguous_dns_and_local_target_block_transport(self):
        manager = manager_with_probes(); original = manager.ns.side_effect
        def ns(index, *args, **kwargs):
            if args[1:3] == ('-I', '-c'):
                return completed({'stage': 'dns', 'status': 'passed', 'addresses': ['203.0.113.10', '203.0.113.11']})
            return original(index, *args, **kwargs)
        manager.ns.side_effect = ns
        self.assertEqual(probe(manager, 'PC1', 'web.lab.test')['status'], 'blocked')
        self.assertEqual(probe(manager_with_probes(), 'PC1', '192.0.2.100')['status'], 'blocked')
