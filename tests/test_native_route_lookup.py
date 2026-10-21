"""Routing evidence remains local to the kernel query and never predicts delivery."""
import copy
from contextlib import nullcontext
import io
import json
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.__main__ import main
from network_labs.appliances.diagnostics import explain_node
from network_labs.appliances.examples import static_routing_lab
from network_labs.appliances.route_lookup import ipv4_settings, lookup, render
from network_labs.appliances.runtime import RuntimeFailure


def completed(value, code=0, error=''):
    return subprocess.CompletedProcess([], code, value if isinstance(value, str) else json.dumps(value), error)


def manager_for(spec=None):
    spec = spec or static_routing_lab('/rootfs')
    state = {'phase': 'running', 'revision': 9, 'spec': spec}
    node = spec['nodes'][1]
    def ns(index, *args, **kwargs):
        assert index == 1 and kwargs == {'check': False, 'timeout': 3}
        if args[0] == 'sysctl':
            return completed('\n'.join(key + ' = ' + ('2' if key.endswith('rp_filter') else '1') for key in args[1:]))
        if args == ('ip', '-j', '-d', 'link', 'show'):
            return completed([{'ifname': name, 'flags': ['UP', 'LOWER_UP'], 'operstate': 'UP'}
                              for name in ('eth0', 'eth1', 'br0', 'vlan10', 'vlan20', 'lo')])
        if args[:5] == ('ip', '-j', '-4', 'route', 'get'):
            row = {'dst': '203.0.113.0/24' if args[5] == 'fibmatch' else '203.0.113.10',
                   'gateway': '198.18.0.2', 'dev': 'vlan20', 'prefsrc': '198.18.0.1'}
            return completed([row])
        if args == ('ip', '-j', '-4', 'rule', 'show'):
            return completed([{'priority': 0, 'table': 'local'}, {'priority': 32766, 'table': 'main'}])
        if args == ('ip', '-j', '-4', 'neigh', 'show', 'nud', 'all', 'to', '198.18.0.2', 'dev', 'vlan20'):
            return completed([{'dst': '198.18.0.2', 'dev': 'vlan20', 'state': ['FAILED']}])
        raise AssertionError('Unexpected diagnostic operation: ' + repr(args))
    manager = SimpleNamespace(name=spec['name'], read=lambda: state,
                              crun=Mock(return_value=completed({'status': 'running'})), ns=Mock(side_effect=ns))
    manager.locked = lambda: nullcontext(manager)
    return manager


class RouteLookupTests(unittest.TestCase):
    def test_sysctl_slash_paths_preserve_subinterface_dots_and_partial_results(self):
        node = static_routing_lab('/rootfs')['nodes'][2]
        node['subinterfaces']['eth0.20'] = {'parent': 'eth0', 'vlan': 20, 'address': ''}
        manager = Mock()
        manager.ns.return_value = completed('net.ipv4.conf.all.rp_filter = 1\n'
            'net.ipv4.conf.eth0.rp_filter = 2\nnet.ipv4.conf.eth0.forwarding = 1\n'
            'net.ipv4.conf.eth0/20.rp_filter = 0\nnet.ipv4.conf.eth0/20.forwarding = 0\n', 1, 'missing eth1')
        settings = ipv4_settings(manager, 2, node)
        self.assertIn('net/ipv4/conf/eth0.20/rp_filter', manager.ns.call_args.args)
        self.assertEqual(settings['interfaces']['eth0']['effective_rp_filter'], 2)
        self.assertEqual(settings['interfaces']['eth0.20']['effective_rp_filter'], 1)
        self.assertEqual(settings['interfaces']['eth0.20']['forwarding'], 0)
        self.assertIsNone(settings['interfaces']['eth1']['effective_rp_filter'])
        self.assertFalse(settings['available'])

    def test_duplicate_invalid_and_unavailable_sysctls_never_become_disabled(self):
        node = static_routing_lab('/rootfs')['nodes'][2]
        manager = Mock()
        for value in ('net.ipv4.conf.all.rp_filter = 0\nnet.ipv4.conf.all.rp_filter = 0',
                      'net.ipv4.conf.all.rp_filter = 9', 'net.ipv4.conf.all.rp_filter = disabled'):
            manager.ns.return_value = completed(value)
            settings = ipv4_settings(manager, 2, node)
            self.assertIsNone(settings['all_rp_filter'])
            self.assertTrue(all(row['rp_filter_mode'] is None for row in settings['interfaces'].values()))
        manager.ns.side_effect = subprocess.TimeoutExpired('sysctl', 1)
        self.assertFalse(ipv4_settings(manager, 2, node)['available'])

    def test_forwarded_lookup_uses_actual_kernel_context_fib_and_neighbor_records(self):
        manager = manager_for(); original = copy.deepcopy(manager.read())
        report = lookup(manager, 'SW1', '203.0.113.10', source='192.0.2.10', ingress='vlan10')
        self.assertEqual(report['selected']['gateway'], '198.18.0.2')
        self.assertEqual(report['fibmatch']['records'][0]['dst'], '203.0.113.0/24')
        self.assertEqual(report['neighbors']['records'][0]['state'], ['FAILED'])
        self.assertFalse(report['test_packets_sent']); self.assertEqual(report['packet_delivery'], 'not_tested')
        self.assertIn('ne prouve pas la livraison', render(report))
        self.assertEqual(manager.read(), original)
        manager.ns.assert_any_call(1, 'ip', '-j', '-4', 'route', 'get', '203.0.113.10', 'from', '192.0.2.10', 'iif', 'vlan10', check=False, timeout=3)
        self.assertTrue(all(call.args[:2] == ('state', 'SW1') for call in manager.crun.call_args_list))

    def test_kernel_rejection_malformed_json_and_partial_fib_do_not_trigger_a_manifest_fallback(self):
        manager = manager_for(); original = manager.ns.side_effect
        def ns(index, *args, **kwargs):
            if args[:5] == ('ip', '-j', '-4', 'route', 'get'):
                return completed([], 2, 'RTNETLINK answers: Network is unreachable')
            return original(index, *args, **kwargs)
        manager.ns.side_effect = ns
        report = lookup(manager, 'SW1', '203.0.113.10')
        self.assertIsNone(report['selected']); self.assertIsNone(report['neighbors'])
        self.assertEqual(report['lookup']['status'], 'command_failed')
        def malformed(index, *args, **kwargs):
            if args[:6] == ('ip', '-j', '-4', 'route', 'get', 'fibmatch'):
                return completed('{broken')
            return original(index, *args, **kwargs)
        manager.ns.side_effect = malformed
        report = lookup(manager, 'SW1', '203.0.113.10')
        self.assertIsNotNone(report['selected'])
        self.assertEqual(report['fibmatch']['status'], 'unavailable')
        self.assertEqual(report['fibmatch']['returncode'], 0)
        self.assertIn('FIB observée : indisponible', render(report))
        for records in ([], [{}], [{'dst': '203.0.113.10'}], [None], {'dst': '203.0.113.10'}):
            def incomplete(index, *args, **kwargs):
                if args[:5] == ('ip', '-j', '-4', 'route', 'get'):
                    return completed(records)
                return original(index, *args, **kwargs)
            manager.ns.side_effect = incomplete
            self.assertIsNone(lookup(manager, 'SW1', '203.0.113.10')['selected'])

    def test_local_destination_has_no_ethernet_neighbor_verdict(self):
        manager = manager_for(); original = manager.ns.side_effect
        def ns(index, *args, **kwargs):
            if args[:5] == ('ip', '-j', '-4', 'route', 'get'):
                return completed([{'type': 'local', 'dst': '192.0.2.1', 'dev': 'lo'}])
            return original(index, *args, **kwargs)
        manager.ns.side_effect = ns
        report = lookup(manager, 'SW1', '192.0.2.1')
        self.assertEqual(report['selected']['type'], 'local')
        self.assertIsNone(report['neighbors']); self.assertIsNone(report['neighbor_target'])
        def ipv6_via(index, *args, **kwargs):
            if args[:5] == ('ip', '-j', '-4', 'route', 'get'):
                return completed([{'dst': '203.0.113.10', 'dev': 'vlan20', 'via': {'family': 'inet6', 'addr': 'fe80::1'}}])
            return original(index, *args, **kwargs)
        manager.ns.side_effect = ipv6_via
        report = lookup(manager, 'SW1', '203.0.113.10')
        self.assertEqual(report['selected']['via']['addr'], 'fe80::1')
        self.assertIsNone(report['neighbors']); self.assertIsNone(report['neighbor_target'])

    def test_invalid_context_stopped_dead_unknown_and_vm_nodes_do_not_query_routes(self):
        for kwargs in ({'destination': 'not-an-ip'}, {'destination': '224.0.0.1'},
                       {'destination': '203.0.113.10', 'ingress': 'vlan10'},
                       {'destination': '203.0.113.10', 'source': '192.0.2.10', 'ingress': 'eno1'}):
            manager = manager_for()
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                lookup(manager, 'SW1', **kwargs)
            manager.ns.assert_not_called()
        for condition in ('stopped', 'dead', 'unknown', 'vm'):
            manager = manager_for(); name = 'SW1'
            if condition == 'stopped': manager.read()['phase'] = 'failed'
            if condition == 'dead': manager.crun.return_value = completed({'status': 'stopped'})
            if condition == 'unknown': name = 'missing'
            if condition == 'vm': manager.read()['spec']['nodes'][1]['runtime'] = 'firecracker'
            with self.subTest(condition=condition), self.assertRaises((RuntimeFailure, ValueError)):
                lookup(manager, name, '203.0.113.10')
            manager.ns.assert_not_called()

    def test_absent_ingress_is_not_assumed_from_declared_manifest(self):
        manager = manager_for(); original = manager.ns.side_effect
        manager.ns.side_effect = lambda index, *args, **kwargs: completed([]) if args == ('ip', '-j', '-d', 'link', 'show') else original(index, *args, **kwargs)
        with self.assertRaisesRegex(RuntimeFailure, 'absent'):
            lookup(manager, 'SW1', '203.0.113.10', source='192.0.2.10', ingress='vlan10')
        self.assertEqual(manager.ns.call_count, 1)

    def test_diagnostics_explain_observed_source_validation_without_a_packet_verdict(self):
        manager = manager_for(); node = manager.read()['spec']['nodes'][1]
        settings = ipv4_settings(manager, 1, node)
        actual = {'links': [], 'addresses': [], 'routes': [], 'forwarding': True, 'ipv4_settings': settings}
        findings = explain_node(node, actual)
        found = next(row for row in findings if row['code'] == 'IPV4_SOURCE_VALIDATION')
        self.assertIn('aucun verdict', found['message'])
        self.assertEqual(found['severity'], 'info')
        settings['available'] = False
        self.assertEqual(next(row for row in explain_node(node, actual) if row['code'] == 'IPV4_SOURCE_VALIDATION')['severity'], 'unknown')

    def test_cli_json_and_text_are_the_same_observation_not_a_packet_test(self):
        manager = manager_for()
        with patch('network_labs.appliances.__main__.Manager', return_value=manager), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['route', manager.name, 'SW1', '203.0.113.10', '--json']), 0)
            self.assertEqual(json.loads(output.getvalue())['packet_delivery'], 'not_tested')
            output.seek(0); output.truncate()
            self.assertEqual(main(['route', manager.name, 'SW1', '203.0.113.10']), 0)
            self.assertIn('Entrée FIB observée : 203.0.113.0/24', output.getvalue())
