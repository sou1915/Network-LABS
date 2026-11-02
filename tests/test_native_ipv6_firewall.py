"""IPv6 policy boundaries, ordered rendering and isolated nft transaction checks."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from network_labs.appliances.examples import ipv6_firewall_lab
from network_labs.appliances.firewall_ipv6 import apply, render
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.service_adapters import adapters
from network_labs.appliances.spec import validate


class IPv6FirewallTests(unittest.TestCase):
    def test_render_is_ipv6_only_ordered_and_keeps_ndp_outside_forward_acl(self):
        spec = ipv6_firewall_lab('/rootfs'); self.assertEqual(validate(spec), spec)
        fw = spec['nodes'][1]; policy = fw['firewall_ipv6']; text = render(policy, replace=True)
        self.assertTrue(text.startswith('delete table ip6 network_labs_ipv6\n'))
        self.assertIn('ip6 saddr 2001:db8:10::10/128', text)
        self.assertIn('meta l4proto ipv6-icmp icmpv6 type echo-request', text)
        self.assertIn('meta l4proto tcp tcp dport 8080', text)
        self.assertLess(text.index('"state"'), text.index('"rule:echo-out"'))
        self.assertLess(text.index('"rule:echo-out"'), text.index('"rule:http-out"'))
        self.assertNotIn('hook input', text); self.assertNotIn('flush ruleset', text); self.assertNotIn('nat', text)
        changed = copy.deepcopy(fw); changed['firewall_ipv6']['stateful'] = False
        self.assertNotIn('established', render(changed['firewall_ipv6']))
        with self.assertRaisesRegex(ValueError, 'recreation'): adapters(changed, fw)

    def test_invalid_rules_and_unvalidated_family_or_topology_compositions_fail(self):
        changes = [lambda p: p.update(nat=[]), lambda p: p.update(default='allow'), lambda p: p.update(stateful=1),
                   lambda p: p['rules'][0].update(source='192.0.2.0/24'),
                   lambda p: p['rules'][0].update(source='fe80::1%eth0/128'),
                   lambda p: p['rules'][0].update(source='::ffff:192.0.2.1/128'),
                   lambda p: p['rules'][0].update(out='eth99'), lambda p: p['rules'][0].update(dport=80),
                   lambda p: p['rules'][1].update(dport=True), lambda p: p['rules'][1].update(icmp_type='echo-request'),
                   lambda p: p['rules'][0].update(icmp_type='nd-router-advert'),
                   lambda p: p['rules'][0].update(protocol='icmp'), lambda p: p['rules'][0].update(action='reject'),
                   lambda p: p['rules'].append(copy.deepcopy(p['rules'][0]))]
        for i, change in enumerate(changes):
            spec = ipv6_firewall_lab('/rootfs'); change(spec['nodes'][1]['firewall_ipv6'])
            with self.subTest(case=i), self.assertRaises(ValueError): validate(spec)
        for update in ({'role': 'router'}, {'forwarding': True}, {'ipv6_forwarding': False},
                       {'startup': [['/bin/true']]}, {'shutdown': ['eth1']},
                       {'interfaces': {'eth0': '192.0.2.1/24', 'eth1': ''}},
                       {'firewall': {'default': 'drop'}}, {'router_advertisements': ['eth0']}):
            spec = ipv6_firewall_lab('/rootfs'); spec['nodes'][1].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)

    def test_udp_and_icmp_errors_have_explicit_protocol_specific_match(self):
        spec = ipv6_firewall_lab('/rootfs'); rules = spec['nodes'][1]['firewall_ipv6']['rules']
        rules.extend([{'name': 'dns', 'action': 'accept', 'protocol': 'udp', 'dport': 53},
                      {'name': 'pmtu', 'action': 'accept', 'protocol': 'icmpv6', 'icmp_type': 'packet-too-big'}])
        policy = validate(spec)['nodes'][1]['firewall_ipv6']
        self.assertIn('meta l4proto udp udp dport 53', render(policy))
        self.assertIn('icmpv6 type packet-too-big', render(policy))

    def test_apply_only_replaces_its_ip6_table_and_checks_before_commit(self):
        node = ipv6_firewall_lab('/rootfs')['nodes'][1]
        with tempfile.TemporaryDirectory() as folder:
            manager = Mock(); manager.directory = Path(folder)
            def ns(index, *args, **kwargs):
                if args == ('nft', '-j', 'list', 'tables'):
                    return subprocess.CompletedProcess([], 0, json.dumps({'nftables': [{'table': {'family': 'ip6', 'name': 'network_labs_ipv6'}}]}), '')
                if args[:3] == ('nft', '-c', '-f'): raise RuntimeFailure('syntax rejected')
                raise AssertionError('Unexpected mutation after failed check: ' + repr(args))
            manager.ns.side_effect = ns
            with self.assertRaisesRegex(RuntimeFailure, 'syntax rejected'): apply(manager, 1, node)
            self.assertEqual(manager.ns.call_count, 2)
            text = (Path(folder) / 'FW1-ipv6.nft').read_text()
            self.assertIn('delete table ip6 network_labs_ipv6', text); self.assertNotIn('table ip ', text)
