"""Firewall micro-VM policy: typed requests, exact readback and fail-closed startup."""
import copy
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch
from network_labs.appliances import guest_firewall
from network_labs.appliances.guest_control import _firewall_command, request
from network_labs.appliances.microvm import firewall_example
from network_labs.appliances.spec import validate

POLICY = {'default': 'drop', 'stateful': True, 'nat': [], 'rules': [
    {'name': 'web', 'in': 'eth0', 'out': 'eth1', 'source': '192.0.2.0/24', 'destination': '198.51.100.20/32', 'protocol': 'tcp', 'dport': 443, 'action': 'accept'},
    {'name': 'dns', 'protocol': 'udp', 'dport': 53, 'action': 'accept'},
    {'name': 'ping', 'in': 'eth0', 'protocol': 'icmp', 'action': 'accept'},
    {'name': 'block', 'source': '203.0.113.0/24', 'protocol': 'any', 'action': 'drop'}]}
LISTING = '''-P FORWARD DROP
-A FORWARD -m conntrack --ctstate INVALID -j DROP
-A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
-A FORWARD -s 192.0.2.0/24 -d 198.51.100.20/32 -i eth0 -o eth1 -p tcp -m tcp --dport 443 -j ACCEPT
-A FORWARD -p udp -m udp --dport 53 -j ACCEPT
-A FORWARD -i eth0 -p icmp -j ACCEPT
-A FORWARD -s 203.0.113.0/24 -j DROP
'''


class GuestFirewallTests(unittest.TestCase):
    def node(self):
        node = firewall_example('/kernel', '/disk')['nodes'][0]; node['firewall'] = copy.deepcopy(POLICY); return node

    def test_reference_lab_and_schema_boundaries(self):
        spec = firewall_example('/kernel', '/disk'); firewall = spec['nodes'][0]
        self.assertEqual((firewall['role'], firewall['firewall']['default'], spec['nodes'][1]['gateway']), ('firewall', 'drop', '192.0.2.1'))
        def changed(change):
            candidate = firewall_example('/kernel', '/disk'); change(candidate['nodes']); return candidate
        cases = {'no policy': lambda nodes: nodes[0].pop('firewall'),
                 'policy on a router': lambda nodes: nodes[0].update(role='router'),
                 'policy on a host': lambda nodes: nodes[1].update(firewall=copy.deepcopy(POLICY)),
                 'single port': lambda nodes: nodes[0].update(interfaces={'eth0': '192.0.2.1/24'}),
                 'undeclared port': lambda nodes: nodes[0]['firewall']['rules'][0].update(out='eth2'),
                 'translation': lambda nodes: nodes[0]['firewall']['nat'].append({'name': 'out', 'out': 'eth1', 'type': 'masquerade'})}
        for label, change in cases.items():
            with self.subTest(label), self.assertRaises(ValueError): validate(changed(change))

    def test_readback_of_real_listing_matches_the_declared_policy_exactly(self):
        self.assertEqual(guest_firewall.parse(LISTING), guest_firewall.expected(POLICY))
        for wrong in (LISTING.replace('-P FORWARD DROP', '-P FORWARD ACCEPT'), LISTING.replace('--dport 443', '--dport 80'),
                      LISTING.replace('-A FORWARD -i eth0 -p icmp -j ACCEPT\n', ''), LISTING + '-A FORWARD -j ACCEPT\n',
                      LISTING.replace('RELATED,ESTABLISHED', 'RELATED,ESTABLISHED,NEW')):
            self.assertNotEqual(guest_firewall.parse(wrong), guest_firewall.expected(POLICY))
        for unreadable in ('', '-A INPUT -j ACCEPT\n', '-P FORWARD DROP\n-A FORWARD -j LOG --log-prefix x\n', '-P FORWARD DROP\n-A FORWARD -j\n'):
            with self.subTest(unreadable=unreadable), self.assertRaises(ValueError): guest_firewall.parse(unreadable)
        stateless = dict(POLICY, stateful=False, default='accept')
        self.assertEqual(guest_firewall.expected(stateless)['rules'][0], {'state': {'INVALID'}, 'action': 'drop'})
        self.assertNotIn({'state': {'RELATED', 'ESTABLISHED'}, 'action': 'accept'}, guest_firewall.expected(stateless)['rules'])

    @unittest.skipUnless(os.geteuid() == 0 and shutil.which('iptables-legacy'), 'root and legacy iptables required')
    def test_parser_reads_what_real_iptables_prints(self):
        """Build the same rules in an unattached chain with the real program and read its own listing back."""
        run = lambda *args: subprocess.run(['iptables-legacy', '-w', *args], capture_output=True, text=True)
        chain = 'NLTEST' + str(os.getpid())
        if run('-N', chain).returncode: self.skipTest('iptables cannot create a chain here')
        try:
            for rule in guest_firewall.expected(POLICY)['rules']:
                args = ['-A', chain]
                if 'state' in rule: args += ['-m', 'conntrack', '--ctstate', ','.join(sorted(rule['state'], reverse=True))]
                for option, key in (('-i', 'in'), ('-o', 'out'), ('-p', 'protocol'), ('-s', 'source'), ('-d', 'destination')):
                    if key in rule: args += [option, str(rule[key])]
                if 'dport' in rule: args += ['--dport', str(rule['dport'])]
                added = run(*args, '-j', rule['action'].upper())
                if added.returncode: self.skipTest('iptables cannot add rules here: ' + added.stderr.strip())
            listing = run('-S', chain).stdout.replace(chain, 'FORWARD').replace('-N FORWARD', '-P FORWARD DROP')
            self.assertEqual(guest_firewall.parse(listing), guest_firewall.expected(POLICY), listing)
        finally:
            run('-F', chain); run('-X', chain)

    @unittest.skipUnless(os.geteuid() == 0 and shutil.which('xtables-legacy-multi') and shutil.which('chroot'), 'root, legacy iptables and chroot required')
    def test_image_files_alone_can_install_every_rule_kind(self):
        """A guest has only what the builder copied: a missing library or module must fail here, not at boot."""
        import tempfile
        from pathlib import Path
        from network_labs.appliances.guest_image import install_iptables
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'sbin').mkdir(); (root / 'run').mkdir()
            install_iptables(root, shutil.which('xtables-legacy-multi'))
            self.assertFalse([path for path in root.rglob('*') if path.is_symlink()])
            run = lambda *args: subprocess.run(['chroot', folder, '/sbin/xtables-legacy-multi', 'iptables', '-w', *args], capture_output=True, text=True)
            chain = 'NLIMG' + str(os.getpid())
            if run('-N', chain).returncode: self.skipTest('iptables cannot create a chain here')
            try:
                for rule in guest_firewall.expected(POLICY)['rules']:
                    args = ['-A', chain]
                    if 'state' in rule: args += ['-m', 'conntrack', '--ctstate', ','.join(sorted(rule['state'], reverse=True))]
                    for option, key in (('-i', 'in'), ('-o', 'out'), ('-p', 'protocol'), ('-s', 'source'), ('-d', 'destination')):
                        if key in rule: args += [option, str(rule[key])]
                    if 'dport' in rule: args += ['--dport', str(rule['dport'])]
                    added = run(*args, '-j', rule['action'].upper())
                    self.assertEqual(added.returncode, 0, added.stderr)
                listing = run('-S', chain).stdout.replace(chain, 'FORWARD').replace('-N FORWARD', '-P FORWARD DROP')
                self.assertEqual(guest_firewall.parse(listing), guest_firewall.expected(POLICY), listing)
            finally:
                run('-F', chain); run('-X', chain)

    def test_apply_is_closed_while_changing_and_verifies_the_result(self):
        node = self.node(); calls = []
        def fake(socket, operation, **arguments):
            calls.append((operation, arguments)); return {'exit_code': 0, 'output': LISTING}
        with patch.object(guest_firewall, 'request', side_effect=fake): guest_firewall.apply('/socket', node)
        self.assertEqual([c[0] for c in calls], ['firewall-policy', 'firewall-flush', 'firewall-state', 'firewall-state',
                                                'firewall-rule', 'firewall-rule', 'firewall-rule', 'firewall-rule', 'firewall-policy', 'firewall-list'])
        self.assertEqual((calls[0][1], calls[-2][1]), ({'state': 'drop'}, {'state': 'drop'}))
        self.assertEqual(calls[4][1]['rule'], {'in': 'eth0', 'out': 'eth1', 'protocol': 'tcp', 'source': '192.0.2.0/24', 'destination': '198.51.100.20/32', 'dport': 443, 'action': 'accept'})
        drifted = LISTING.replace('-A FORWARD -s 203.0.113.0/24 -j DROP\n', '')
        with patch.object(guest_firewall, 'request', return_value={'exit_code': 0, 'output': drifted}), self.assertRaisesRegex(ValueError, 'differ'):
            guest_firewall.apply('/socket', node)
        with patch.object(guest_firewall, 'request', return_value={'exit_code': 127, 'output': ''}), self.assertRaisesRegex(ValueError, 'with-firewall'):
            guest_firewall.apply('/socket', node)

    def test_startup_filters_before_forwarding_and_save_rejects_drift(self):
        from network_labs.appliances import guest_startup
        node = self.node(); order = []
        with patch.object(guest_startup, 'query', side_effect=lambda socket, operation, **k: order.append(operation)), \
             patch.object(guest_firewall, 'apply', side_effect=lambda socket, node: order.append('firewall')), \
             patch.object(guest_startup, 'observe', return_value={'addresses': [], 'routes': []}):
            guest_startup.apply('/socket', node)
        self.assertLess(order.index('firewall'), order.index('forward'))
        with patch.object(guest_startup, 'query', return_value='1\n'), patch.object(guest_firewall, 'request', return_value={'exit_code': 0, 'output': '-P FORWARD ACCEPT\n'}), \
             self.assertRaisesRegex(ValueError, 'differ'):
            guest_startup.check_forwarding('/socket', node); guest_firewall.check('/socket', node)

    def test_typed_wire_and_rejections(self):
        self.assertEqual(_firewall_command('firewall-rule', None, {'action': 'accept', 'in': 'eth0', 'out': 'eth1', 'protocol': 'tcp', 'source': '192.0.2.0/24', 'dport': 443}),
                         'FW_RULE accept eth0 eth1 tcp 192.0.2.0/24 - 443')
        self.assertEqual(_firewall_command('firewall-rule', None, {'action': 'drop'}), 'FW_RULE drop - - any - - -')
        self.assertEqual((_firewall_command('firewall-policy', 'drop', None), _firewall_command('firewall-state', 'established', None), _firewall_command('firewall-list', None, None)),
                         ('FW_POLICY drop', 'FW_STATE established', 'FW_LIST'))
        longest = _firewall_command('firewall-rule', None, {'action': 'accept', 'in': 'eth0', 'out': 'eth1', 'protocol': 'tcp', 'source': '255.255.255.255/32', 'destination': '255.255.255.255/32', 'dport': 65535})
        self.assertLess(len('NL1 ' + longest), 159)
        bad = [('firewall-rule', None, {'action': 'allow'}), ('firewall-rule', None, {'action': 'accept', 'in': 'eth9'}), ('firewall-rule', None, {'action': 'accept', 'dport': 80}),
               ('firewall-rule', None, {'action': 'accept', 'protocol': 'tcp', 'dport': 0}), ('firewall-rule', None, {'action': 'accept', 'source': '192.0.2.1/24'}),
               ('firewall-rule', None, {'action': 'accept', 'comment': '; id'}), ('firewall-rule', 'drop', {'action': 'accept'}), ('firewall-rule', None, None),
               ('firewall-policy', 'reject', None), ('firewall-state', 'new', None), ('firewall-flush', 'drop', None), ('firewall-list', None, {'action': 'accept'})]
        for operation, state, rule in bad:
            with self.subTest(operation=operation, state=state, rule=rule), self.assertRaises(ValueError): _firewall_command(operation, state, rule)
        with self.assertRaises(ValueError): request('/missing', 'firewall-list', interface='eth0')
        with self.assertRaises(ValueError): request('/missing', 'ping', destination='192.0.2.1', rule={'action': 'accept'})
