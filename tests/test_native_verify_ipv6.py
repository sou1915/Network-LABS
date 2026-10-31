"""IPv6 verification consumes kernel evidence and never guesses an endpoint."""
import copy
import io
import json
import subprocess
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch
from network_labs.appliances.examples import dhcpv6_lab, slaac_lab
from network_labs.appliances.verify import verify, render
from network_labs.appliances.__main__ import main


def completed(value, code=0):
    return subprocess.CompletedProcess([], code, value if isinstance(value, str) else json.dumps(value), '')


def address(value, **extra):
    return {'family': 'inet6', 'scope': 'global', 'local': value, 'prefixlen': 128,
            'valid_life_time': 110, **extra}


def manager_for(example=dhcpv6_lab):
    manager = Mock(); manager.name = 'verify-ipv6'
    manager.read.return_value = {'spec': example('/rootfs'), 'phase': 'running', 'revision': 2}
    def ns(index, *args, **kwargs):
        if args[:3] == ('ip', '-j', 'link'):
            return completed([{'ifname': 'eth0', 'flags': ['UP', 'LOWER_UP']}])
        if args[:4] == ('ip', '-j', '-6', 'addr'):
            return completed([{'ifname': 'eth0', 'addr_info': [address('2001:db8:10::10a' if index == 0 else '2001:db8:20::20')]}])
        if args[:4] == ('ip', '-j', '-6', 'route'):
            return completed([{'dev': 'eth0', 'gateway': 'fe80::1'}])
        raise AssertionError('Unexpected command: ' + repr(args))
    manager.ns.side_effect = ns
    manager.crun.side_effect = lambda *a, **k: completed({'status': 'running'}) if a[0] == 'state' else completed(
        '64 bytes from peer: seq=0 ttl=62 time=0.1 ms\n2 packets transmitted, 2 packets received, 0% packet loss\n')
    return manager


class IPv6VerifyTests(unittest.TestCase):
    def test_observed_dhcpv6_addresses_exact_source_binding_and_source_aware_lookup(self):
        manager = manager_for(); before = copy.deepcopy(manager.read())
        report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2, bidirectional=True)
        self.assertEqual(report['status'], 'passed'); self.assertEqual(report['address_family'], 'ipv6')
        self.assertTrue(report['endpoints'][0]['dhcpv6_client_configured'])
        self.assertEqual(report['directions'][0]['source_address'], '2001:db8:10::10a')
        self.assertEqual(report['directions'][0]['reply_hop_limits'], [62])
        self.assertEqual(report['directions'][0]['reply_ttls'], [])
        manager.ns.assert_any_call(0, 'ip', '-j', '-6', 'route', 'get', '2001:db8:20::20', 'from', '2001:db8:10::10a', check=False, timeout=3)
        manager.crun.assert_any_call('exec', 'PC1', '/bin/busybox', 'ping6', '-n', '-I', '2001:db8:10::10a',
                                    '-c', '2', '-W', '1', '-w', '4', '2001:db8:20::20', check=False, timeout=7)
        self.assertEqual(report['directions'][1]['destination_address'], '2001:db8:10::10a')
        self.assertIn('IPv6', render(report)); self.assertIn('RÉUSSI', render(report))
        self.assertEqual(manager.read(), before); manager.save.assert_not_called()

    def test_slaac_observation_is_used_without_manifest_fallback(self):
        manager = manager_for(slaac_lab)
        self.assertEqual(manager.read()['spec']['nodes'][0]['ipv6'], {})
        report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
        self.assertEqual(report['status'], 'passed'); self.assertTrue(report['endpoints'][0]['slaac_client_configured'])
        self.assertEqual(report['endpoints'][0]['address'], '2001:db8:10::10a')
        self.assertFalse(report['endpoints'][0]['dhcpv6_client_configured'])

    def test_dad_and_expiry_block_before_any_probe(self):
        for extra, reason in (({'tentative': True}, 'IPV6_DAD_INCOMPLETE'),
                              ({'flags': ['tentative']}, 'IPV6_DAD_INCOMPLETE'),
                              ({'dadfailed': True}, 'IPV6_DAD_FAILED'),
                              ({'flags': ['dadfailed']}, 'IPV6_DAD_FAILED'),
                              ({'valid_life_time': 0}, 'IPV6_ADDRESS_EXPIRED')):
            manager = manager_for(); original = manager.ns.side_effect
            manager.ns.side_effect = lambda i, *a, **k: completed([{'ifname': 'eth0', 'addr_info': [address('2001:db8:10::10a', **extra)]}]) if a[:4] == ('ip', '-j', '-6', 'addr') else original(i, *a, **k)
            report = verify(manager, 'PC1', 'PC2', family='ipv6')
            self.assertEqual(report['status'], 'blocked'); self.assertEqual(report['probe_commands_attempted'], 0)
            self.assertEqual(report['endpoints'][0]['reasons'], [reason]); render(report)
            self.assertTrue(all(c.args[0] == 'state' for c in manager.crun.call_args_list))

    def test_no_address_or_unusable_address_never_falls_back_to_static_endpoint(self):
        for entries in ([], [address('fe80::1')], [address('::1')], [address('ff02::1')],
                        [address('::')], [address('::ffff:192.0.2.1')]):
            manager = manager_for(); original = manager.ns.side_effect
            manager.ns.side_effect = lambda i, *a, **k: completed([{'ifname': 'eth0', 'addr_info': entries}]) if a[:4] == ('ip', '-j', '-6', 'addr') else original(i, *a, **k)
            report = verify(manager, 'PC1', 'PC2', family='ipv6')
            self.assertEqual(report['status'], 'blocked'); self.assertEqual(report['probe_commands_attempted'], 0)
            self.assertIn('NO_USABLE_IPV6', report['endpoints'][1]['reasons'])

    def test_ambiguous_or_malformed_addresses_remain_unknown(self):
        rows = [[address('2001:db8:10::10a'), address('2001:db8:10::10b')],
                [address('2001:db8:10::10a', prefixlen=True)], [address('bad')],
                [address('2001:db8:10::10a%eth0')], [address('2001:db8:10::10a', flags='tentative')],
                [address('2001:db8:10::10a', tentative='false')], [address('2001:db8:10::10a', valid_life_time=None)]]
        for entries in rows:
            manager = manager_for(); original = manager.ns.side_effect
            manager.ns.side_effect = lambda i, *a, **k: completed([{'ifname': 'eth0', 'addr_info': entries}]) if a[:4] == ('ip', '-j', '-6', 'addr') else original(i, *a, **k)
            report = verify(manager, 'PC1', 'PC2', family='ipv6')
            self.assertEqual(report['status'], 'unknown'); self.assertEqual(report['probe_commands_attempted'], 0)

    def test_duplicate_and_local_or_unsupported_egress_block_probes(self):
        manager = manager_for(); original = manager.ns.side_effect
        manager.ns.side_effect = lambda i, *a, **k: original(0 if a[3] == 'addr' else i, *a, **k)
        report = verify(manager, 'PC1', 'PC2', family='ipv6')
        self.assertEqual(report['status'], 'blocked'); self.assertEqual(report['endpoints'][0]['reasons'], ['DUPLICATE_ENDPOINT_IPV6'])
        for route in ({'type': 'local', 'dev': 'lo'}, {'dev': 'eth99'}):
            manager = manager_for(); original = manager.ns.side_effect
            manager.ns.side_effect = lambda i, *a, **k: completed([route]) if a[3] == 'route' else original(i, *a, **k)
            report = verify(manager, 'PC1', 'PC2', family='ipv6')
            self.assertEqual(report['status'], 'blocked'); self.assertEqual(report['probe_commands_attempted'], 0)

    def test_partial_and_malformed_stats_timeout_and_failed_route_are_not_success(self):
        for value, code, expected in [('2 packets transmitted, 1 packets received', 0, 'failed'),
                                      ('2 packets transmitted, 0 received', 1, 'failed'),
                                      ('2 packets transmitted, 3 received', 0, 'unknown'),
                                      ('9' * 5000 + ' packets transmitted, 2 received', 0, 'unknown'),
                                      ('unsupported applet', 127, 'unknown')]:
            manager = manager_for(); original = manager.crun.side_effect
            manager.crun.side_effect = lambda *a, **k: completed(value, code) if a[0] == 'exec' else original(*a, **k)
            self.assertEqual(verify(manager, 'PC1', 'PC2', family='ipv6', count=2)['status'], expected)
        manager = manager_for(); original = manager.ns.side_effect
        manager.ns.side_effect = lambda i, *a, **k: completed('Network unreachable', 2) if a[3] == 'route' else original(i, *a, **k)
        original_crun = manager.crun.side_effect
        def timed_out(*args, **kwargs):
            if args[0] == 'exec': raise subprocess.TimeoutExpired('ping6', 7, output=b'partial')
            return original_crun(*args, **kwargs)
        manager.crun.side_effect = timed_out
        report = verify(manager, 'PC1', 'PC2', family='ipv6', count=2)
        self.assertEqual(report['status'], 'unknown'); self.assertTrue(report['directions'][0]['attempted'])
        self.assertEqual(report['directions'][0]['route']['status'], 'command_failed')

    def test_cli_family_selection_and_failed_exit(self):
        for status, expected in (('passed', 0), ('blocked', 1), ('unknown', 1), ('failed', 1)):
            manager = manager_for(); manager.locked.return_value = nullcontext(manager)
            with patch('network_labs.appliances.__main__.Manager', return_value=manager), \
                 patch('network_labs.appliances.verify.verify', return_value={'status': status}) as call, \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(main(['verify', 'verify-ipv6', 'PC1', 'PC2', '--family', 'ipv6', '--json']), expected)
                self.assertEqual(call.call_args.kwargs['family'], 'ipv6')
                self.assertEqual(json.loads(output.getvalue())['status'], status)
        manager = manager_for()
        with self.assertRaises(ValueError): verify(manager, 'PC1', 'PC2', family='auto')
        manager.read.assert_not_called()
