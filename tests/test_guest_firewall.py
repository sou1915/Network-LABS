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


NAT_EMPTY = '-P PREROUTING ACCEPT\n-P INPUT ACCEPT\n-P OUTPUT ACCEPT\n-P POSTROUTING ACCEPT\n'
NAT_LISTING = NAT_EMPTY + '''-A PREROUTING -d 198.51.100.1/32 -i eth1 -p icmp -j DNAT --to-destination 192.0.2.20
-A PREROUTING -d 198.51.100.1/32 -i eth1 -p tcp -m tcp --dport 8080 -j DNAT --to-destination 192.0.2.20:80
-A POSTROUTING -s 192.0.2.0/24 -o eth1 -j MASQUERADE
-A POSTROUTING -s 192.0.2.30/32 -o eth1 -j SNAT --to-source 198.51.100.1
'''
NAT_POLICY = [{'name': 'hide', 'type': 'masquerade', 'out': 'eth1', 'source': '192.0.2.0/24'},
              {'name': 'pin', 'type': 'snat', 'out': 'eth1', 'source': '192.0.2.30/32', 'to': '198.51.100.1'},
              {'name': 'ping', 'type': 'dnat', 'in': 'eth1', 'destination': '198.51.100.1/32', 'protocol': 'icmp', 'to': '192.0.2.20'},
              {'name': 'web', 'type': 'dnat', 'in': 'eth1', 'destination': '198.51.100.1/32', 'protocol': 'tcp', 'dport': 8080, 'to': '192.0.2.20', 'to_port': 80}]


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
                 'source NAT matching the input port': lambda nodes: nodes[0]['firewall']['nat'].append({'name': 'out', 'in': 'eth0', 'out': 'eth1', 'type': 'masquerade'}),
                 'NAT on an undeclared port': lambda nodes: nodes[0]['firewall']['nat'].append({'name': 'out', 'out': 'eth2', 'type': 'masquerade'})}
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

    @unittest.skipUnless(os.geteuid() == 0 and shutil.which('xtables-legacy-multi') and shutil.which('chroot'), 'root, legacy iptables and chroot required')
    def test_image_files_alone_can_install_every_nat_kind(self):
        """The NAT targets are links to one module; the image must hold them under the names iptables loads."""
        import tempfile
        from pathlib import Path
        from network_labs.appliances.guest_image import install_iptables
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'sbin').mkdir(); (root / 'run').mkdir()
            install_iptables(root, shutil.which('xtables-legacy-multi'))
            run = lambda *args: subprocess.run(['chroot', folder, '/sbin/xtables-legacy-multi', 'iptables', '-w', '-t', 'nat', *args], capture_output=True, text=True)
            chain = 'NLNAT' + str(os.getpid())
            if run('-N', chain).returncode: self.skipTest('iptables cannot create a nat chain here')
            try:
                for line in NAT_LISTING.splitlines():
                    words = line.split()
                    if words[0] != '-A': continue
                    added = run('-A', chain, *words[2:])
                    self.assertEqual(added.returncode, 0, (line, added.stderr))
                listing = run('-S', chain).stdout
                self.assertEqual(len([l for l in listing.splitlines() if l.startswith('-A')]), 4, listing)
            finally:
                run('-F', chain); run('-X', chain)

    def test_apply_is_closed_while_changing_and_verifies_the_result(self):
        node = self.node(); calls = []
        def fake(socket, operation, **arguments):
            calls.append((operation, arguments)); return {'exit_code': 0, 'output': NAT_EMPTY if operation == 'firewall-nat-list' else LISTING}
        with patch.object(guest_firewall, 'request', side_effect=fake): guest_firewall.apply('/socket', node)
        self.assertEqual([c[0] for c in calls], ['firewall-policy', 'firewall-flush', 'firewall-state', 'firewall-state',
                                                'firewall-rule', 'firewall-rule', 'firewall-rule', 'firewall-rule', 'firewall-nat-flush',
                                                'firewall-policy', 'firewall-list', 'firewall-nat-list'])
        self.assertEqual((calls[0][1], calls[-3][1]), ({'state': 'drop'}, {'state': 'drop'}))
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

    def test_web_management_offers_and_validates_the_policy_page_for_firewall_guests(self):
        from network_labs.appliances.management_options import configure_section, sections
        spec = firewall_example('/kernel', '/disk')
        self.assertEqual([item['id'] for item in sections(spec['nodes'][0])], ['vmresources', 'firewall'])
        self.assertEqual([item['id'] for item in sections(spec['nodes'][1])], ['vmresources'])
        policy = copy.deepcopy(spec['nodes'][0]['firewall'])
        policy['rules'].append({'name': 'inside-web', 'in': 'eth0', 'out': 'eth1', 'protocol': 'tcp', 'dport': 443, 'action': 'accept'})
        saved = configure_section(spec, 'FW1', 'firewall', {'firewall': policy})
        self.assertEqual([rule['name'] for rule in saved['nodes'][0]['firewall']['rules']], ['inside-ping-out', 'inside-web'])
        self.assertEqual(spec['nodes'][0]['firewall']['rules'][-1]['name'], 'inside-ping-out')  # The draft is replaced, never edited in place.
        translated = copy.deepcopy(policy); translated['nat'].append({'name': 'hide', 'out': 'eth1', 'type': 'masquerade'})
        self.assertEqual(configure_section(spec, 'FW1', 'firewall', {'firewall': translated})['nodes'][0]['firewall']['nat'][0]['type'], 'masquerade')
        translated['nat'][0]['in'] = 'eth0'
        with self.assertRaisesRegex(ValueError, 'outbound'): configure_section(spec, 'FW1', 'firewall', {'firewall': translated})
        with self.assertRaises(ValueError): configure_section(spec, 'VM2', 'firewall', {'firewall': policy})


class LiveGuestFirewallTests(unittest.TestCase):
    """configure_firewall on a running firewall micro-VM: rebuilt in the guest, rolled back on failure, recoverable."""
    def manager(self, root):
        import json
        from pathlib import Path
        from network_labs.appliances import runtime
        spec = firewall_example('/kernel', '/disk')
        manager = runtime.Manager(spec['name']); manager.directory = Path(root) / spec['name']; manager.directory.mkdir()
        state = {'spec': spec, 'phase': 'running', 'revision': 3, 'vms': [], 'containers': [], 'namespaces': [], 'host_links': [], 'mounts': [], 'firewall_fingerprints': {}}
        (manager.directory / 'state.json').write_text(json.dumps(state))
        return manager, spec

    def policy(self, spec):
        policy = copy.deepcopy(spec['nodes'][0]['firewall'])
        policy['rules'].append({'name': 'inside-web', 'in': 'eth0', 'out': 'eth1', 'protocol': 'tcp', 'dport': 443, 'action': 'accept'})
        return policy

    def test_new_policy_is_applied_in_the_guest_and_recorded(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            manager, spec = self.manager(root)
            with patch('network_labs.appliances.guest_firewall.apply') as apply:
                result = manager.configure_firewall('FW1', self.policy(spec))
            self.assertEqual(apply.call_count, 1)
            self.assertEqual(apply.call_args.args[0], manager.directory / 'FW1' / 'guest.vsock')
            self.assertEqual(apply.call_args.args[1]['firewall']['rules'][-1]['name'], 'inside-web')
            manager.state = None; state = manager.read()
            self.assertEqual((state['revision'], state['phase'], result['revision']), (4, 'running', 4))
            self.assertEqual(state['spec']['nodes'][0]['firewall']['rules'][-1]['name'], 'inside-web')
            self.assertNotIn('FW1', state['firewall_fingerprints']); self.assertIn('read back', result['note'])

    def test_failed_change_restores_the_previous_policy_and_keeps_the_revision(self):
        import tempfile
        from network_labs.appliances.runtime import RuntimeFailure
        with tempfile.TemporaryDirectory() as root:
            manager, spec = self.manager(root)
            with patch('network_labs.appliances.guest_firewall.apply', side_effect=[ValueError('readback differs'), None]) as apply, \
                 self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                manager.configure_firewall('FW1', self.policy(spec))
            self.assertEqual(apply.call_args_list[1].args[1]['firewall'], spec['nodes'][0]['firewall'])
            manager.state = None; state = manager.read()
            self.assertEqual((state['revision'], state['phase']), (3, 'running'))
            self.assertEqual(state['spec'], spec); self.assertNotIn('pending_spec', state)

    def test_failed_rollback_leaves_a_recoverable_journal(self):
        import tempfile
        from network_labs.appliances.runtime import RuntimeFailure
        with tempfile.TemporaryDirectory() as root:
            manager, spec = self.manager(root)
            with patch('network_labs.appliances.guest_firewall.apply', side_effect=ValueError('agent gone')), self.assertRaisesRegex(RuntimeFailure, 'rollback failed'):
                manager.configure_firewall('FW1', self.policy(spec))
            manager.state = None; self.assertEqual(manager.read()['phase'], 'configuration-failed')
            with patch('network_labs.appliances.guest_firewall.apply') as apply:
                manager.recover()
            self.assertEqual(apply.call_args.args[1]['firewall'], spec['nodes'][0]['firewall'])
            manager.state = None; state = manager.read()
            self.assertEqual(state['phase'], 'running'); self.assertNotIn('pending_spec', state)

    def test_invalid_translation_is_refused_before_the_guest_is_touched(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            manager, spec = self.manager(root)
            policy = self.policy(spec); policy['nat'].append({'name': 'hide', 'in': 'eth0', 'out': 'eth1', 'type': 'masquerade'})
            with patch('network_labs.appliances.guest_firewall.apply') as apply, self.assertRaisesRegex(ValueError, 'outbound'):
                manager.configure_firewall('FW1', policy)
            apply.assert_not_called()


class GuestNatTests(unittest.TestCase):
    """Address translation in a firewall guest's nat table: wire format, exact readback, and kernels without NAT."""
    def node(self, nat=NAT_POLICY):
        spec = firewall_example('/kernel', '/disk'); spec['nodes'][0]['firewall']['nat'] = copy.deepcopy(nat)
        return validate(spec)['nodes'][0]

    def test_listing_reads_back_as_the_declared_translation_in_chain_order(self):
        node = self.node()
        self.assertEqual(guest_firewall.parse_nat(NAT_LISTING), guest_firewall.expected_nat(node['firewall']))
        self.assertEqual([r['type'] for r in guest_firewall.expected_nat(node['firewall'])], ['dnat', 'dnat', 'masquerade', 'snat'])
        self.assertEqual(guest_firewall.parse_nat(NAT_EMPTY), [])
        for wrong in (NAT_LISTING.replace('192.0.2.20:80', '192.0.2.20:81'), NAT_LISTING.replace('-o eth1 -j MASQUERADE', '-o eth0 -j MASQUERADE'),
                      NAT_LISTING.replace('-A POSTROUTING -s 192.0.2.30/32 -o eth1 -j SNAT --to-source 198.51.100.1\n', '')):
            self.assertNotEqual(guest_firewall.parse_nat(wrong), guest_firewall.expected_nat(node['firewall']))
        for unreadable in (NAT_LISTING.replace('-P OUTPUT ACCEPT', '-P OUTPUT DROP'), NAT_EMPTY + '-A OUTPUT -j DNAT --to-destination 192.0.2.1\n',
                           NAT_EMPTY + '-A POSTROUTING -j DNAT --to-destination 192.0.2.1\n', NAT_EMPTY + '-A PREROUTING -j REDIRECT --to-ports 80\n', ''):
            with self.subTest(unreadable=unreadable), self.assertRaises(ValueError): guest_firewall.parse_nat(unreadable)

    def test_wire_format_and_rejections(self):
        from network_labs.appliances.guest_control import _firewall_command
        expected = ['FW_NAT dnat eth1 - icmp - 198.51.100.1/32 - 192.0.2.20 -', 'FW_NAT dnat eth1 - tcp - 198.51.100.1/32 8080 192.0.2.20 80',
                    'FW_NAT masquerade - eth1 any 192.0.2.0/24 - - - -', 'FW_NAT snat - eth1 any 192.0.2.30/32 - - 198.51.100.1 -']
        self.assertEqual([_firewall_command('firewall-nat-rule', None, r) for r in guest_firewall.expected_nat(self.node()['firewall'])], expected)
        for rule in ({'type': 'masquerade'}, {'type': 'dnat', 'out': 'eth1', 'to': '192.0.2.1'}, {'type': 'masquerade', 'out': 'eth1', 'to': '192.0.2.1'},
                     {'type': 'snat', 'out': 'eth1'}, {'type': 'dnat', 'in': 'eth1', 'to': '192.0.2.1', 'to_port': 80},
                     {'type': 'dnat', 'in': 'eth1', 'to': '192.0.2.1', 'dport': 80}, {'type': 'redirect', 'in': 'eth1'},
                     {'type': 'dnat', 'in': 'eth9', 'to': '192.0.2.1'}, {'type': 'masquerade', 'out': 'eth1', 'comment': '; id'}):
            with self.subTest(rule=rule), self.assertRaises(ValueError): _firewall_command('firewall-nat-rule', None, rule)

    def test_apply_installs_translation_while_closed_and_reads_it_back(self):
        node = self.node(); calls = []
        filter_listing = '\n'.join(['-P FORWARD DROP', '-A FORWARD -m conntrack --ctstate INVALID -j DROP',
                                     '-A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT',
                                     '-A FORWARD -s 192.0.2.0/24 -i eth0 -o eth1 -p icmp -j ACCEPT']) + '\n'
        def fake(socket, operation, **arguments):
            calls.append(operation)
            return {'exit_code': 0, 'output': NAT_LISTING if operation == 'firewall-nat-list' else filter_listing}
        with patch.object(guest_firewall, 'request', side_effect=fake): guest_firewall.apply('/socket', node)
        flush = calls.index('firewall-nat-flush')
        self.assertEqual(calls[flush + 1:flush + 5], ['firewall-nat-rule'] * 4)
        self.assertEqual(calls[flush + 5], 'firewall-policy')  # The declared default comes only after NAT is in place.

    def test_kernel_without_nat_table_is_fine_without_translation_and_reported_with_it(self):
        missing = {'exit_code': 3, 'output': "iptables v1.8.10 (legacy): can't initialize iptables table `nat': Table does not exist"}
        old_agent = {'exit_code': 2, 'output': 'unsupported operation'}
        filter_ok = {'exit_code': 0, 'output': LISTING}
        plain = GuestFirewallTests.node(GuestFirewallTests())
        for absent in (missing, old_agent):
            fake = lambda socket, operation, **k: absent if operation.startswith('firewall-nat') else filter_ok
            with self.subTest(absent=absent['output'][:20]), patch.object(guest_firewall, 'request', side_effect=fake):
                guest_firewall.apply('/socket', plain)  # No NAT declared: a guest without the table is acceptable.
                self.assertIsNone(guest_firewall.observe_nat('/socket'))
            with patch.object(guest_firewall, 'request', side_effect=fake), self.assertRaisesRegex(ValueError, 'NAT table'):
                guest_firewall.apply('/socket', self.node())
        stray = lambda socket, operation, **k: {'exit_code': 0, 'output': NAT_LISTING} if operation == 'firewall-nat-list' else filter_ok
        with patch.object(guest_firewall, 'request', side_effect=stray), self.assertRaisesRegex(ValueError, 'NAT rules differ'):
            guest_firewall.check('/socket', plain)


class GuestSessionTests(unittest.TestCase):
    """sessions on a firewall guest: its own conntrack table, read over vsock."""
    def test_sessions_come_from_the_guest_table_and_clearing_is_refused(self):
        import tempfile
        from network_labs.appliances.runtime import RuntimeFailure
        table = ('ipv4     2 icmp     1 29 src=192.0.2.20 dst=198.51.100.20 type=8 code=0 id=7 src=198.51.100.20 dst=192.0.2.20 type=0 code=0 id=7 mark=0 use=1\n'
                 'ipv6     10 udp      17 20 src=fe80::1 dst=ff02::1 sport=546 dport=547 [UNREPLIED] src=ff02::1 dst=fe80::1 sport=547 dport=546 mark=0 use=1\n')
        with tempfile.TemporaryDirectory() as root:
            manager, spec = LiveGuestFirewallTests.manager(self, root)
            with patch('network_labs.appliances.guest_control.request', return_value={'exit_code': 0, 'output': table}) as request:
                result = manager.sessions('FW1')
            self.assertEqual(request.call_args.args, (manager.directory / 'FW1' / 'guest.vsock', 'firewall-sessions'))
            self.assertEqual(result['output'].count('\n'), 1); self.assertIn('src=192.0.2.20', result['output'])
            self.assertTrue(result['summary'].startswith('1 IPv4'))
            with self.assertRaisesRegex(ValueError, 'not available'): manager.sessions('FW1', clear=True)
            with patch('network_labs.appliances.guest_control.request', return_value={'exit_code': 1, 'output': 'no conntrack listing in this guest kernel'}), \
                 self.assertRaisesRegex(RuntimeFailure, 'no conntrack listing'):
                manager.sessions('FW1')
