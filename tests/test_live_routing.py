"""Live routing changes on running micro-VMs: only what differs changes, other edits are refused, failures roll back."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from network_labs.appliances import guest_startup, missions, runtime
from network_labs.appliances.microvm import ospf_example, router_chain_example
from network_labs.appliances.spec import validate


class ChangeRoutingTest(unittest.TestCase):
    def run_change(self, old, new, readback=None):
        calls = []
        def query(socket, operation, **fields):
            calls.append((operation, fields))
            return ''
        with mock.patch.object(guest_startup, 'query', query), \
                mock.patch.object(guest_startup, 'start_ospf', lambda socket, node: calls.append(('start-ospf', node['name']))), \
                mock.patch.object(guest_startup, 'observe',
                                  lambda socket, node: readback or node.get('guest_network') or {'addresses': [], 'routes': []}):
            guest_startup.change_routing('/unused', old, new)
        return calls

    def test_only_the_differing_routes_change(self):
        lab = router_chain_example('/k', '/d')
        old = lab['nodes'][0]
        new = copy.deepcopy(old)
        new['guest_network']['routes'] = [{'network': '198.51.100.0/24', 'gateway': '203.0.113.2'},
                                          {'network': '10.9.0.0/16', 'gateway': '203.0.113.2'}]
        self.assertEqual(self.run_change(old, new),
                         [('route-add', {'network': '10.9.0.0/16', 'gateway': '203.0.113.2', 'interface': 'eth1'})])
        self.assertEqual(self.run_change(new, old),
                         [('route-delete', {'network': '10.9.0.0/16', 'gateway': '203.0.113.2', 'interface': 'eth1'})])

    def test_ospf_restarts_only_when_it_changed(self):
        lab = ospf_example('/k', '/d')
        r1 = lab['nodes'][0]
        without = dict(copy.deepcopy(r1), ospf=None)
        self.assertEqual(self.run_change(without, r1), [('start-ospf', 'R1')])
        self.assertEqual(self.run_change(r1, without), [('ospf-stop', {})])
        self.assertEqual(self.run_change(r1, r1), [])
        with self.assertRaisesRegex(ValueError, 'readback'):
            self.run_change(r1, r1, readback={'addresses': [], 'routes': [{'network': '10.0.0.0/8', 'gateway': '1.1.1.1'}]})


    def test_an_address_typed_on_a_running_router_replaces_the_old_one_between_the_routes(self):
        lab = router_chain_example('/k', '/d')
        old = lab['nodes'][0]
        new = copy.deepcopy(old)
        new['interfaces']['eth1'] = '203.0.113.5/30'
        new['guest_network']['routes'] = [{'network': '198.51.100.0/24', 'gateway': '203.0.113.6'}]
        self.assertEqual(self.run_change(old, new), [
            ('route-delete', {'network': '198.51.100.0/24', 'gateway': '203.0.113.2', 'interface': 'eth1'}),
            ('address-delete', {'interface': 'eth1', 'cidr': '203.0.113.1/30'}),
            ('address-add', {'interface': 'eth1', 'cidr': '203.0.113.5/30'}),
            ('route-add', {'network': '198.51.100.0/24', 'gateway': '203.0.113.6', 'interface': 'eth1'})])
        fresh = copy.deepcopy(old)
        fresh['interfaces']['eth0'] = ''  # a new, unconfigured port: only the address is added
        self.assertEqual(self.run_change(fresh, old), [('address-add', {'interface': 'eth0', 'cidr': '192.0.2.1/24'})])


    def test_static_nat_typed_live_adds_the_public_address_then_removes_it(self):
        from network_labs.appliances import guest_console
        from network_labs.appliances.draft_lab import DraftLab
        from tests.test_ios_nat import MARKS, STATIC, lab
        box = {'spec': lab()}
        draft = DraftLab(lambda: box['spec'], lambda spec: box.update(spec=validate(spec)))
        console = guest_console.Console('ios-static-nat', 'R1', lambda name: draft)
        router = lambda: copy.deepcopy(next(n for n in box['spec']['nodes'] if n['name'] == 'R1'))
        for line in ['en', *MARKS]:
            console.line(line)
        before = router()
        for line in STATIC:
            console.line(line)
        after = router()
        with mock.patch('network_labs.appliances.guest_firewall.apply', lambda socket, node: None):
            calls = self.run_change(before, after)
            self.assertIn(('address-add', {'interface': 'eth1', 'cidr': '203.0.113.10/32'}), calls)
            self.assertIn(('address-delete', {'interface': 'eth1', 'cidr': '203.0.113.10/32'}), self.run_change(after, before))


class ChangeSwitchTest(unittest.TestCase):
    def run_change(self, old, new):
        calls = []
        def query(socket, operation, **fields):
            calls.append((operation, fields))
            return ''
        with mock.patch.object(guest_startup, 'query', query), mock.patch.object(guest_startup, 'check_switch',
                                                                                lambda socket, node: calls.append(('check',))):
            guest_startup.change_switch('/unused', old, new)
        return calls

    def switch(self, **ports):
        node = {'name': 'SW1', 'role': 'switch', 'interfaces': {f'eth{i}': '' for i in range(4)}, 'vlans': [1],
                'switchports': {f'eth{i}': {'mode': 'access', 'vlan': 1} for i in range(4)}, 'shutdown': []}
        for port, value in ports.items():
            node['switchports'][port] = value
            node['vlans'] = sorted(set(node['vlans']) | {value.get('vlan') or value.get('native_vlan')}
                                   | set(value.get('allowed', []) if value.get('allowed') != 'all' else []))
        return node

    def test_a_first_vlan_turns_filtering_on_and_moves_the_port_untagged_last(self):
        plain = self.switch()
        access = self.switch(eth0={'mode': 'access', 'vlan': 10})
        self.assertEqual(self.run_change(plain, access), [
            ('bridge-vlan-filtering', {}), ('bridge-vlan-delete', {'interface': 'eth0', 'vlan': 1}),
            ('bridge-vlan-add', {'interface': 'eth0', 'vlan': 10, 'state': 'pvid'}), ('check',)])
        trunk = self.switch(eth0={'mode': 'access', 'vlan': 10}, eth3={'mode': 'trunk', 'native_vlan': 1, 'allowed': [1, 10]})
        self.assertEqual(self.run_change(access, trunk), [
            ('bridge-vlan-add', {'interface': 'eth3', 'vlan': 10, 'state': 'tagged'}), ('check',)])
        shut = dict(trunk, shutdown=['eth2'])
        self.assertEqual(self.run_change(trunk, shut), [('link', {'interface': 'eth2', 'state': 'down'}), ('check',)])


class ConfigureRoutingTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        for name, value in (('STATE_ROOT', Path(self.folder.name) / 'state'), ('CONFIG_ROOT', Path(self.folder.name) / 'config')):
            patcher = mock.patch.object(runtime, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.lab = missions.mission('route-manquante')['build']('/k', '/d')
        self.manager = runtime.Manager(self.lab['name'])
        self.manager.directory.mkdir(parents=True)
        self.manager.state = {'phase': 'running', 'spec': self.lab, 'revision': 0}
        self.manager.save()

    def fixed(self):
        node = copy.deepcopy(self.lab['nodes'][0])
        node['guest_network'] = {'addresses': [], 'routes': [{'network': '198.51.100.0/24', 'gateway': '203.0.113.2'}]}
        return node

    def test_the_running_lab_takes_the_new_routes(self):
        with mock.patch('network_labs.appliances.guest_startup.change_routing') as change:
            with self.manager.locked():
                self.manager.state = None
                result = self.manager.configure_routing('R1', self.fixed())
        self.assertEqual(result['revision'], 1)
        change.assert_called_once()
        state = runtime.Manager(self.lab['name']).read()
        self.assertEqual((state['phase'], state['spec']['nodes'][0]['guest_network']['routes'][0]['gateway']), ('running', '203.0.113.2'))

    def test_other_changes_are_refused_and_failures_roll_back(self):
        moved = self.fixed()
        moved['memory_mib'] = 192  # the machine itself still needs a restart
        with self.manager.locked():
            self.manager.state = None
            with self.assertRaisesRegex(ValueError, 'restart'):
                self.manager.configure_routing('R1', moved)
        attempts = []
        def change(socket, old, new):
            attempts.append((old.get('guest_network'), new.get('guest_network')))
            if len(attempts) == 1:
                raise ValueError('guest refused')
        with mock.patch('network_labs.appliances.guest_startup.change_routing', change):
            with self.manager.locked():
                self.manager.state = None
                with self.assertRaisesRegex(runtime.RuntimeFailure, 'rolled back'):
                    self.manager.configure_routing('R1', self.fixed())
        self.assertEqual(len(attempts), 2)  # the change, then the way back
        state = runtime.Manager(self.lab['name']).read()
        self.assertEqual((state['phase'], state.get('revision')), ('running', 0))
        self.assertNotIn('pending_spec', state)


class BridgeTest(unittest.TestCase):
    def test_routing_requests_carry_a_snapshot_and_a_node(self):
        from network_labs.appliances.ui_bridge import validate_request
        envelope = {'id': '0' * 32, 'owner_uid': os.geteuid(), 'action': 'routing', 'target': '/tmp/manifest.json', 'lab': 'lab',
                    'node': 'R1', 'destination': None}
        self.assertEqual(validate_request(envelope)['action'], 'routing')
        with self.assertRaises(ValueError):
            validate_request(dict(envelope, target='lab'))
        with self.assertRaises(ValueError):
            validate_request(dict(envelope, node=None))


if __name__ == '__main__':
    unittest.main()
