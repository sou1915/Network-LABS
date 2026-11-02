"""Regression: native RS must wait for link-local DAD after cold startup."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.runtime import RuntimeFailure
from test_native_integration import solicit_ipv6_router


def snapshot(**extra):
    return SimpleNamespace(stdout=json.dumps([{'addr_info': [dict(
        family='inet6', scope='link', local='fe80::1', preferred_life_time=4294967295, **extra)]}]))


class SolicitationReadinessTests(unittest.TestCase):
    @patch('test_native_integration.time.sleep')
    def test_no_packet_until_missing_and_tentative_source_becomes_usable(self, sleep):
        manager = Mock()
        manager.ns.side_effect = [SimpleNamespace(stdout='[]'), snapshot(tentative=True),
                                  snapshot(flags=['tentative']), snapshot(), SimpleNamespace(stdout='')]
        solicit_ipv6_router(manager, 3)
        self.assertEqual(sleep.call_count, 3)
        self.assertEqual(manager.ns.call_count, 5)
        for call in manager.ns.call_args_list[:-1]:
            self.assertEqual(call.args, (3, 'ip', '-j', '-6', 'addr', 'show', 'dev', 'eth0'))
        self.assertIn('sock.sendto', manager.ns.call_args.args[-1])

    def test_failed_dad_is_fatal_without_sending(self):
        for extra in ({'dadfailed': True}, {'flags': ['dadfailed']}):
            with self.subTest(extra=extra):
                manager = Mock(); manager.ns.return_value = snapshot(**extra)
                with self.assertRaisesRegex(RuntimeFailure, 'failed link-local DAD'):
                    solicit_ipv6_router(manager, 0)
                manager.ns.assert_called_once()

    @patch('test_native_integration.time.monotonic', side_effect=[0, 5])
    def test_unavailable_source_has_bounded_failure(self, clock):
        manager = Mock(); manager.ns.return_value = snapshot(tentative=True)
        with self.assertRaisesRegex(RuntimeFailure, 'requires a usable link-local source'):
            solicit_ipv6_router(manager, 0)
        manager.ns.assert_called_once()

    def test_query_failure_is_not_hidden(self):
        manager = Mock(); manager.ns.side_effect = RuntimeFailure('namespace missing')
        with self.assertRaisesRegex(RuntimeFailure, 'namespace missing'):
            solicit_ipv6_router(manager, 0)
        manager.ns.assert_called_once()
