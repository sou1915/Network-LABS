"""Real-probe reporting must distinguish absent evidence from failed delivery."""
import copy
import io
import json
import subprocess
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from network_labs.appliances.examples import ospf_dhcp_multi_lab
from network_labs.appliances.verify import verify, render
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.__main__ import main


def completed(value, code=0):
    return subprocess.CompletedProcess([], code, value if isinstance(value, str) else json.dumps(value), '')


def manager_for():
    manager = Mock(); manager.name = 'verify-test'
    manager.read.return_value = {'spec': ospf_dhcp_multi_lab('/rootfs'), 'phase': 'running', 'revision': 4}
    def ns(index, *args, **kwargs):
        if args[:4] == ('ip', '-j', '-4', 'addr'):
            address = '192.0.2.100' if index == 0 else '203.0.113.10'
            return completed([{'ifname': 'eth0', 'flags': ['UP', 'LOWER_UP'],
                'addr_info': [{'family': 'inet', 'scope': 'global', 'local': address, 'prefixlen': 24}]}])
        return completed([{'dev': 'eth0', 'gateway': '192.0.2.1'}])
    manager.ns.side_effect = ns
    def crun(*args, **kwargs):
        if args[0] == 'state':
            return completed({'status': 'running'})
        return completed('64 bytes from peer: seq=0 ttl=62 time=0.1 ms\n2 packets transmitted, 2 packets received, 0% packet loss\n')
    manager.crun.side_effect = crun
    return manager


class VerifyTests(unittest.TestCase):
    def test_observed_dhcp_target_and_bidirectional_real_commands_preserve_configuration(self):
        manager = manager_for(); before = copy.deepcopy(manager.read())
        report = verify(manager, 'PC1', 'PC2', count=2, bidirectional=True)
        self.assertEqual(report['status'], 'passed'); self.assertEqual(report['probe_commands_attempted'], 2)
        self.assertEqual(report['directions'][1]['destination_address'], '192.0.2.100')
        self.assertEqual(report['directions'][0]['reply_ttls'], [62])
        self.assertEqual(manager.read(), before); manager.save.assert_not_called()
        manager.crun.assert_any_call('exec', 'PC2', '/bin/ping', '-n', '-I', 'eth0', '-c', '2', '-W', '1', '-w', '4', '192.0.2.100', check=False, timeout=7)
        self.assertIn('RÉUSSI', render(report)); self.assertNotIn('convergé', render(report))

    def test_missing_address_and_down_link_block_without_probe_or_manifest_fallback(self):
        for row in ({'ifname': 'eth0', 'flags': ['UP', 'LOWER_UP'], 'addr_info': []},
                    {'ifname': 'eth0', 'flags': [], 'addr_info': []}):
            manager = manager_for(); manager.ns.side_effect = None; manager.ns.return_value = completed([row])
            report = verify(manager, 'PC1', 'PC2')
            self.assertEqual(report['status'], 'blocked'); self.assertEqual(report['probe_commands_attempted'], 0)
            self.assertTrue(all(call.args[0] == 'state' for call in manager.crun.call_args_list))
            self.assertEqual(report['directions'], [])

    def test_missing_malformed_or_ambiguous_observations_stay_unknown(self):
        for value in ('bad json', [{'ifname': 'eth0'}], [{'ifname': 'eth0', 'flags': ['UP', 'LOWER_UP'], 'addr_info':
                [{'family': 'inet', 'scope': 'global', 'local': ip, 'prefixlen': 24} for ip in ('192.0.2.1', '192.0.2.2')]}]):
            manager = manager_for(); manager.ns.side_effect = None; manager.ns.return_value = completed(value)
            report = verify(manager, 'PC1', 'PC2')
            self.assertEqual(report['status'], 'unknown'); self.assertEqual(report['probe_commands_attempted'], 0)

    def test_failed_partial_unparseable_or_timed_out_ping_is_never_passed(self):
        for value, code, expected in [('2 packets transmitted, 0 packets received', 1, 'failed'),
                                      ('2 packets transmitted, 1 received', 0, 'failed'),
                                      ('2 packets transmitted, 3 received', 0, 'unknown'), ('unexpected', 0, 'unknown')]:
            manager = manager_for(); original = manager.crun.side_effect
            manager.crun.side_effect = lambda *a, **k: completed(value, code) if a[0] == 'exec' else original(*a, **k)
            self.assertEqual(verify(manager, 'PC1', 'PC2', count=2)['status'], expected)
        manager = manager_for(); original = manager.crun.side_effect
        def crun(*args, **kwargs):
            if args[0] == 'exec':
                raise subprocess.TimeoutExpired('ping', 7, output=b'partial')
            return original(*args, **kwargs)
        manager.crun.side_effect = crun
        report = verify(manager, 'PC1', 'PC2', count=2)
        self.assertEqual(report['status'], 'unknown'); self.assertEqual(report['directions'][0]['stdout'], 'partial')

    def test_duplicate_addresses_or_local_route_cannot_verify_remote_delivery(self):
        manager = manager_for(); original = manager.ns.side_effect
        def ns(index, *args, **kwargs):
            return original(0 if args[3] == 'addr' else index, *args, **kwargs)
        manager.ns.side_effect = ns
        self.assertEqual(verify(manager, 'PC1', 'PC2')['status'], 'blocked')
        manager = manager_for(); original = manager.ns.side_effect
        manager.ns.side_effect = lambda i, *a, **k: completed([{'type': 'local', 'dev': 'lo'}]) if a[3] == 'route' else original(i, *a, **k)
        report = verify(manager, 'PC1', 'PC2')
        self.assertEqual(report['status'], 'blocked'); self.assertEqual(report['probe_commands_attempted'], 0)

    def test_invalid_arguments_and_pending_state_are_rejected_before_probes(self):
        for source, target, kwargs in [('PC1', 'PC1', {}), ('PC1', 'SW1', {}), ('PC1', 'missing', {}),
                                       ('PC1', 'PC2', {'count': True}), ('PC1', 'PC2', {'count': 6}),
                                       ('PC1', 'PC2', {'bidirectional': 1})]:
            manager = manager_for()
            with self.assertRaises(ValueError):
                verify(manager, source, target, **kwargs)
            manager.ns.assert_not_called(); manager.crun.assert_not_called()
        manager = manager_for(); manager.read.return_value['pending_node'] = 'SW1'
        with self.assertRaises(RuntimeFailure):
            verify(manager, 'PC1', 'PC2')
        manager.crun.assert_not_called()

    def test_cli_failed_report_has_json_and_nonzero_exit(self):
        manager = manager_for(); manager.locked.return_value = nullcontext(manager)
        report = {'status': 'blocked', 'directions': [], 'endpoints': []}
        with patch('network_labs.appliances.__main__.Manager', return_value=manager), \
             patch('network_labs.appliances.verify.verify', return_value=report), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['verify', 'verify-test', 'PC1', 'PC2', '--json']), 1)
            self.assertEqual(json.loads(output.getvalue())['status'], 'blocked')
