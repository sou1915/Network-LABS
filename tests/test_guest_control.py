"""Real compiled guest protocol and local transport; not a KVM boot test."""
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
import unittest
from unittest.mock import patch
from network_labs.appliances.guest_control import request


@unittest.skipUnless(shutil.which('gcc'), 'gcc required for actual guest agent tests')
class GuestAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary = Path(cls.temporary.name) / 'agent'
        subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', '-o', str(cls.binary),
                        'network_labs/appliances/guest/agent.c'], check=True)

    def invoke(self, data):
        result = subprocess.run([str(self.binary), '--stdio'], input=data,
                                capture_output=True, timeout=7, check=True)
        header, body = result.stdout.split(b'\n', 1)
        version, code, length = header.split()
        self.assertEqual(version, b'NL1')
        self.assertEqual(len(body), int(length))
        return int(code), body

    def test_ready_does_not_claim_network_readiness(self):
        code, body = self.invoke(b'NL1 READY\n')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(body), {'protocol': 1, 'agent_ready': True, 'network_verified': False})

    def test_rejects_shell_nul_unknown_version_and_overlong_requests(self):
        for data in (b'NL1 ROUTES; id\n', b'NL1 READY\0evil\n', b'NL2 READY\n', b'NL1 PING 127.0.0.1;id\n', b'NL1 PING -c\n', b'x' * 80, b''):
            with self.subTest(data=data):
                self.assertEqual(self.invoke(data)[0], 2)

    def test_fixed_linux_diagnostics_report_real_exit_status(self):
        for operation in ('ADDRESSES', 'ROUTES', 'PING 127.0.0.1'):
            code, body = self.invoke(('NL1 ' + operation + '\n').encode())
            expected = 0 if Path('/bin/busybox').exists() else 127
            if expected == 0 and operation.startswith('PING') and os.geteuid() != 0 and b'permission denied' in body:
                # Raw ICMP needs root. The guest agent has it; an unprivileged test process may not,
                # and BusyBox's own refusal must then come back with its real exit status.
                expected = 1
            self.assertEqual(code, expected, (operation, body))
            if code == 0 and operation == 'ADDRESSES':
                self.assertIn(b'lo', body)

    def test_firewall_changes_and_malformed_rules_are_refused_over_stdio(self):
        for data in (b'NL1 FW_FLUSH\n', b'NL1 FW_POLICY accept\n', b'NL1 FW_STATE invalid\n',
                     b'NL1 FW_RULE accept eth0 eth1 icmp 192.0.2.0/24 - -\n', b'NL1 FW_LIST extra\n'):
            with self.subTest(data=data): self.assertEqual(self.invoke(data)[0], 2)

    def test_kernel_capabilities_are_reported_without_changing_anything(self):
        code, body = self.invoke(b'NL1 KERNEL\n')
        self.assertEqual(code, 0)
        report = dict(line.split('=') for line in body.decode().splitlines())
        self.assertEqual(sorted(report), ['bridge', 'conntrack', 'iptables', 'ipv6_forwarding', 'nftables', 'vlan'])
        self.assertTrue(all(value in ('0', '1') for value in report.values()), report)
        self.assertEqual(self.invoke(b'NL1 KERNEL bridge\n')[0], 2)

    def test_forwarding_is_readable_but_never_writable_over_stdio(self):
        code, body = self.invoke(b'NL1 FORWARDING\n')
        self.assertEqual(code, 0); self.assertIn(body.strip(), (b'0', b'1'))
        before = Path('/proc/sys/net/ipv4/ip_forward').read_text()
        for data in (b'NL1 FORWARD on\n', b'NL1 FORWARD off\n', b'NL1 FORWARD maybe\n', b'NL1 FORWARD on \n'):
            self.assertEqual(self.invoke(data)[0], 2)
        self.assertEqual(Path('/proc/sys/net/ipv4/ip_forward').read_text(), before)

    def test_stdio_cannot_mutate_interfaces(self):
        for data in (b'NL1 LINK eth0 up\n', b'NL1 LINK eth0 down\n', b'NL1 ADDR_ADD 192.0.2.11/24\n', b'NL1 ADDR_DEL 192.0.2.11/24\n', b'NL1 ROUTE_ADD 198.51.100.0/24 192.0.2.20\n', b'NL1 ROUTE_DEL 198.51.100.0/24 192.0.2.20\n', b'NL1 LINK lo down\n', b'NL1 LINK eth0 down;id\n'):
            self.assertEqual(self.invoke(data)[0], 2)

    def test_partial_request_times_out(self):
        with subprocess.Popen([str(self.binary), '--stdio'], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
            child.stdin.write(b'NL1'); child.stdin.flush()
            self.assertNotEqual(child.wait(timeout=7), 0)


class GuestTransportTests(unittest.TestCase):
    def exchange(self, payload, *, handshake=b'OK 19001\n', timeout=1, delay=0, operation='ready', arguments=None, wire=b'NL1 READY\n'):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vsock'
            errors = []
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(path)); server.listen(1); server.settimeout(3)
                def serve():
                    try:
                        with server.accept()[0] as connection:
                            connection.settimeout(3)
                            self.assertEqual(connection.recv(100), b'CONNECT 19001\n')
                            connection.sendall(handshake)
                            if not handshake.startswith(b'OK '): return
                            self.assertEqual(connection.recv(100), wire)
                            time.sleep(delay)
                            for byte in payload: connection.sendall(bytes([byte]))
                    except (BrokenPipeError, ConnectionResetError): pass
                    except Exception as error: errors.append(error)
                worker = threading.Thread(target=serve)
                worker.start()
                try:
                    return request(path, operation, timeout=timeout, **(arguments or {}))
                finally:
                    worker.join(4)
                    self.assertFalse(worker.is_alive())
                    if errors: raise errors[0]

    def test_fragmented_response_and_nonzero_exit_are_preserved(self):
        self.assertEqual(self.exchange(b'NL1 127 4\noops'),
                         {'operation': 'ready', 'exit_code': 127, 'output': 'oops'})

    def test_malformed_oversized_truncated_responses(self):
        for payload in (b'NL2 0 0\n', b'NL1 0 32769\n', b'NL1 256 0\n', b'NL1 0 2\nx', b'x' * 81):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.exchange(payload)
        with self.assertRaises(ValueError): self.exchange(b'', handshake=b'ERR no\n')

    def test_deadline_and_operation_validation(self):
        with self.assertRaises(TimeoutError): self.exchange(b'NL1 0 0\n', timeout=.05, delay=.1)
        with self.assertRaises(ValueError): request('/nonexistent', 'shell')
        with self.assertRaises(ValueError): request('/nonexistent', 'ping', destination='1.2.3.4;id')
        with self.assertRaises(ValueError): request('/nonexistent', 'ready', destination='1.2.3.4')

    def test_typed_link_wire_and_rejections(self):
        result = self.exchange(b'NL1 0 0\n', operation='link', arguments={'interface': 'eth0', 'state': 'down'}, wire=b'NL1 LINK eth0 down\n')
        self.assertEqual(result['exit_code'], 0)
        for interface, state in [('lo', 'down'), ('eth0;id', 'up'), ('eth0', 'down;id'), ('eth0', None)]:
            with self.assertRaises(ValueError):
                request('/missing', 'link', interface=interface, state=state)
        with self.assertRaises(ValueError): request('/missing', 'ready', state='up')

    def test_link_cli_reports_guest_failure(self):
        from network_labs.appliances.__main__ import main
        for code in (0, 2):
            with patch('network_labs.appliances.guest_control.request', return_value={'exit_code': code, 'output': ''}) as call, patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(['microvm-link', '--socket', '/private/guest.vsock', 'down']), 0 if code == 0 else 1)
                call.assert_called_once_with(Path('/private/guest.vsock'), 'link', interface='eth0', state='down')

    def test_address_wire_and_validation(self):
        result = self.exchange(b'NL1 0 0\n', operation='address-add', arguments={'cidr': '192.0.2.11/24'}, wire=b'NL1 ADDR_ADD 192.0.2.11/24\n')
        self.assertEqual(result['exit_code'], 0)
        for cidr in ('192.0.2.11', '192.0.2.11/33', '192.0.2.11/24;id', '::1/128', None):
            with self.assertRaises(ValueError): request('/missing', 'address-add', cidr=cidr)
        with self.assertRaises(ValueError): request('/missing', 'ready', cidr='192.0.2.11/24')

    def test_route_wire_and_validation(self):
        for operation, verb in [('route-add', 'ROUTE_ADD'), ('route-delete', 'ROUTE_DEL')]:
            result = self.exchange(b'NL1 0 0\n', operation=operation, arguments={'network': '198.51.100.0/24', 'gateway': '192.0.2.20'}, wire=('NL1 ' + verb + ' 198.51.100.0/24 192.0.2.20\n').encode())
            self.assertEqual(result['exit_code'], 0)
        for network, gateway in [('198.51.100.1/24', '192.0.2.20'), ('::/0', '192.0.2.20'), ('0.0.0.0/0', '192.0.2.20;id'), ('default', '192.0.2.20'), ('0.0.0.0/0', None)]:
            with self.assertRaises(ValueError): request('/missing', 'route-add', network=network, gateway=gateway)
        with self.assertRaises(ValueError): request('/missing', 'ready', gateway='192.0.2.20')
        for operation, verb in [('route-add', 'IF_ROUTE_ADD'), ('route-delete', 'IF_ROUTE_DEL')]:
            result = self.exchange(b'NL1 0 0\n', operation=operation, arguments={'network': '203.0.113.0/24', 'gateway': '198.51.100.20', 'interface': 'eth1'}, wire=('NL1 ' + verb + ' eth1 203.0.113.0/24 198.51.100.20\n').encode())
            self.assertEqual(result['exit_code'], 0)
        with self.assertRaises(ValueError): request('/missing', 'route-add', network='203.0.113.0/24', gateway='198.51.100.20', interface='eth4')
        with self.assertRaises(ValueError): request('/missing', 'ping', destination='192.0.2.20', interface='eth1')

    def test_forwarding_wire_and_validation(self):
        self.assertEqual(self.exchange(b'NL1 0 2\n1\n', operation='forwarding', arguments={}, wire=b'NL1 FORWARDING\n')['output'], '1\n')
        for state in ('on', 'off'):
            self.assertEqual(self.exchange(b'NL1 0 0\n', operation='forward', arguments={'state': state}, wire=('NL1 FORWARD ' + state + '\n').encode())['exit_code'], 0)
        for arguments in ({}, {'state': 'up'}, {'state': 'on', 'interface': 'eth0'}):
            with self.assertRaises(ValueError): request('/missing', 'forward', **arguments)
        with self.assertRaises(ValueError): request('/missing', 'forwarding', state='on')

    def test_multinic_address_and_link_wire(self):
        for operation, arguments, wire in [('address-add', {'interface':'eth1','cidr':'198.51.100.10/24'}, b'NL1 IF_ADD eth1 198.51.100.10/24\n'), ('address-delete', {'interface':'eth1','cidr':'198.51.100.10/24'}, b'NL1 IF_DEL eth1 198.51.100.10/24\n'), ('link', {'interface':'eth1','state':'down'}, b'NL1 LINK eth1 down\n')]:
            self.assertEqual(self.exchange(b'NL1 0 0\n',operation=operation,arguments=arguments,wire=wire)['exit_code'],0)
        with self.assertRaises(ValueError):request('/missing','address-add',interface='eth4',cidr='198.51.100.10/24')
