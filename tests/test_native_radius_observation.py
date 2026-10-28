import subprocess
import unittest
from unittest.mock import Mock

from network_labs.appliances.ntp_socket import parse_udp_table
from network_labs.appliances.radius_observation import observe_process
from network_labs.appliances.radius_server import command


class RadiusObservationTests(unittest.TestCase):
    def test_pid_requires_exact_invocation_and_does_not_echo_unknown_argv(self):
        for args, status in [(command(), 'observed'), (['wrong', 'private-secret'], 'mismatch'), ([], 'unknown')]:
            manager = Mock()
            manager.crun.side_effect = [subprocess.CompletedProcess([], 0, '42\n', ''),
                                       subprocess.CompletedProcess([], 0, '\0'.join(args) + ('\0' if args else ''), '')]
            result = observe_process(manager, {'name': 'PC2'})
            self.assertEqual(result['status'], status)
            self.assertNotIn('private-secret', str(result))
        for pid in ('-1', '0', '2147483648', 'not-a-pid'):
            manager = Mock(); manager.crun.return_value = subprocess.CompletedProcess([], 0, pid, '')
            self.assertEqual(observe_process(manager, {'name': 'PC2'})['status'], 'unknown')
            self.assertEqual(manager.crun.call_count, 1)

    def test_unavailable_process_is_unknown_without_echoing_error(self):
        manager = Mock(); manager.crun.side_effect = OSError('private-secret')
        result = observe_process(manager, {'name': 'PC2'})
        self.assertEqual(result['status'], 'unknown'); self.assertNotIn('private-secret', str(result))

    def test_radius_socket_selection_does_not_confuse_ntp_or_wildcard(self):
        text = 'sl local_address rem_address st\n0: 140200C0:0714 00000000:0000 07\n1: 00000000:007B 00000000:0000 07\n'
        self.assertEqual(parse_udp_table(text, 1812), [{'address': '192.0.2.20', 'state': 7}])
        self.assertEqual(parse_udp_table(text), [{'address': '0.0.0.0', 'state': 7}])
