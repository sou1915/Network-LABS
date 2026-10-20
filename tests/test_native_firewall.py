"""Policy validation, safe rendering, drift and transaction failure checks."""
import copy
import unittest
from unittest.mock import patch

from network_labs.appliances.examples import firewall_lab
from network_labs.appliances.firewall import fingerprint, render
from network_labs.appliances.runtime import Manager, RuntimeFailure
from network_labs.appliances.spec import validate


class FirewallTests(unittest.TestCase):
    def test_validation_and_render(self):
        spec = firewall_lab('/tmp/rootfs')
        policy = spec['nodes'][1]['firewall']
        text = render(policy, replace=True)
        self.assertTrue(text.startswith('delete table ip network_labs\n'))
        self.assertIn('ct state established,related counter accept', text)
        self.assertIn('dnat to 10.42.0.10:80', text)
        self.assertIn('counter masquerade', text)
        self.assertNotIn('flush ruleset', text)
        self.assertEqual(validate(spec), spec)

    def test_invalid_policies_rejected(self):
        changes = [lambda p: p.update(default='allow'), lambda p: p.update(stateful=1),
                   lambda p: p['rules'][0].update(dport=0),
                   lambda p: p['rules'][0].update(protocol='icmp'),
                   lambda p: p['rules'][0].update(source='::/0'),
                   lambda p: p['rules'][0].update(out='eth99'),
                   lambda p: p['rules'][0].update(name='bad"; flush ruleset'),
                   lambda p: p['rules'].append(copy.deepcopy(p['rules'][0])),
                   lambda p: p['nat'][1].pop('destination'),
                   lambda p: p['nat'][1].update(out='eth0'),
                   lambda p: p['nat'][0].update(type='snat', to='198.51.100.99'),
                   lambda p: p['nat'][0].update(to='198.51.100.1'),
                   lambda p: p.update(unknown=True)]
        for change in changes:
            spec = firewall_lab('/tmp/rootfs')
            change(spec['nodes'][1]['firewall'])
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(spec)
        for change in (lambda n: n.update(role='router'), lambda n: n.update(startup=[['/bin/true']])):
            spec = firewall_lab('/tmp/rootfs'); change(spec['nodes'][1])
            with self.assertRaises(ValueError):
                validate(spec)

    def test_fingerprint_ignores_traffic_but_detects_policy_and_extra_tables(self):
        base = {'nftables': [{'metainfo': {'version': '1'}}, {'table': {'family': 'ip', 'name': 'network_labs', 'handle': 1}},
                              {'rule': {'expr': [{'counter': {'packets': 1, 'bytes': 10}}, {'drop': None}], 'handle': 2}}]}
        traffic = copy.deepcopy(base)
        traffic['nftables'][2]['rule']['expr'][0]['counter']['bytes'] = 999
        traffic['nftables'][2]['rule']['handle'] = 77
        self.assertEqual(fingerprint(base), fingerprint(traffic))
        traffic['nftables'][2]['rule']['expr'][1] = {'accept': None}
        self.assertNotEqual(fingerprint(base), fingerprint(traffic))
        traffic = copy.deepcopy(base); traffic['nftables'].append({'table': {'name': 'extra', 'family': 'ip'}})
        self.assertNotEqual(fingerprint(base), fingerprint(traffic))

    def test_update_validates_before_apply_and_rolls_back(self):
        manager = Manager('firewall-lan')
        spec = firewall_lab('/tmp/rootfs')
        manager.state = {'spec': spec, 'phase': 'running', 'revision': 0}
        invalid = copy.deepcopy(spec['nodes'][1]['firewall']); invalid['default'] = 'oops'
        with patch.object(manager, 'save'), patch('network_labs.appliances.firewall.apply') as apply:
            with self.assertRaises(ValueError):
                manager.configure_firewall('FW1', invalid)
            apply.assert_not_called()
            policy = copy.deepcopy(spec['nodes'][1]['firewall']); policy['stateful'] = False
            apply.side_effect = [RuntimeFailure('apply failed'), 'restored']
            with self.assertRaisesRegex(RuntimeFailure, 'rolled back'):
                manager.configure_firewall('FW1', policy)
            self.assertEqual(manager.state['spec'], spec)
            self.assertEqual(manager.state['phase'], 'running')
            self.assertNotIn('pending_spec', manager.state)
            apply.side_effect = [RuntimeFailure('apply failed'), RuntimeFailure('rollback failed')]
            with self.assertRaisesRegex(RuntimeFailure, 'rollback failed'):
                manager.configure_firewall('FW1', policy)
            self.assertEqual(manager.state['phase'], 'configuration-failed')
            self.assertIn('pending_spec', manager.state)
        with patch.object(manager, 'save'), patch('network_labs.appliances.firewall.apply', return_value='recovered'), patch('network_labs.appliances.lan.configure'):
            manager.recover()
        self.assertEqual(manager.state['phase'], 'running')
        self.assertEqual(manager.state['firewall_fingerprints']['FW1'], 'recovered')
