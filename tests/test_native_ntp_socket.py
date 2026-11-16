import socket
import struct
import subprocess
import unittest
from unittest.mock import Mock

from network_labs.appliances.ntp_socket import parse_udp_table, observe_socket

HEADER = '  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n'


def row(address, port, state=7):
    code = struct.unpack('=I', socket.inet_aton(address))[0]
    return f'  12: {code:08X}:{port:04X} 00000000:0000 {state:02X} 00000000:00000000 00:00000000 00000000 0 0 123\n'


class NtpSocketTests(unittest.TestCase):
    def manager(self, output, code=0):
        manager = Mock(); manager.read.return_value = {'spec': {'nodes': [{'name': 'PC2'}]}}
        manager.ns.return_value = subprocess.CompletedProcess([], code, output, '')
        return manager

    def test_exact_binding_wildcard_and_unrelated_sockets(self):
        table = HEADER + row('192.0.2.20', 123) + row('0.0.0.0', 123) + row('192.0.2.20', 53)
        manager = self.manager(table); report = observe_socket(manager, {'name': 'PC2'}, '192.0.2.20')
        self.assertEqual(report['status'], 'observed')
        self.assertEqual(report['bindings'], [{'address': '192.0.2.20', 'state': 7}, {'address': '0.0.0.0', 'state': 7}])
        manager.ns.assert_called_once_with(0, 'cat', '/proc/net/udp', check=False, timeout=3)
        report = observe_socket(self.manager(HEADER + row('0.0.0.0', 123)), {'name': 'PC2'}, '192.0.2.20')
        self.assertEqual(report['status'], 'absent'); self.assertEqual(report['bindings'][0]['address'], '0.0.0.0')

    def test_absent_and_unreadable_are_distinct(self):
        node = {'name': 'PC2'}
        self.assertEqual(observe_socket(self.manager(HEADER), node, '192.0.2.20')['status'], 'absent')
        for raw, code in [('', 1), ('bad', 0), (HEADER + 'bad\n', 0), (HEADER + row('192.0.2.20', 123).replace(':007B', ':QQQQ'), 0)]:
            with self.subTest(raw=raw):
                self.assertEqual(observe_socket(self.manager(raw, code), node, '192.0.2.20')['status'], 'unknown')

    def test_real_proc_header_and_rows_can_be_decoded(self):
        with open('/proc/net/udp') as source:
            self.assertIsInstance(parse_udp_table(source.read()), list)
