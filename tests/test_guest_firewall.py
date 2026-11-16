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
        with self.assertRaisesRegex(ValueError, 'translation'): configure_section(spec, 'FW1', 'firewall', {'firewall': translated})
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

    def test_translation_is_still_refused_before_the_guest_is_touched(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            manager, spec = self.manager(root)
            policy = self.policy(spec); policy['nat'].append({'name': 'hide', 'out': 'eth1', 'type': 'masquerade'})
            with patch('network_labs.appliances.guest_firewall.apply') as apply, self.assertRaisesRegex(ValueError, 'translation'):
                manager.configure_firewall('FW1', policy)
            apply.assert_not_called()
