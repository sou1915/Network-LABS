"""Spanning tree on switch micro-VMs: a second cable between two Catalysts closes a loop and turns classic STP on (lab
timers, IOS port costs); « spanning-tree vlan 1 root primary », « spanning-tree cost » and « port-priority » typed in the
switch's CLI set the guest bridge's numbers; « show spanning-tree » shows the tree (computed from the cables while the lab
is stopped, read from the guest bridge's sysfs while it runs)."""
import copy
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console, guest_stp, topology_edit
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.runtime import guest_mac
from network_labs.appliances.spanning_tree import LAB_TIMERS
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project


def lab(kernel='/k', disk='/d', loop=True):
    """SW1 and SW2 (2960s) joined by Fa0/1 and Fa0/2 (a loop); PC1 on SW1 Fa0/3, PC2 on SW2 Fa0/3, one LAN."""
    spec = blank_project('stp')
    for name in ('SW1', 'SW2'):
        spec = topology_edit.add_microvm_node(spec, name=name, role='switch', kernel=kernel, disk=disk, ports=4, model='cisco-2960')
    for name, address in (('PC1', '192.168.1.10/24'), ('PC2', '192.168.1.20/24')):
        spec = topology_edit.add_microvm_node(spec, name=name, role='host', kernel=kernel, disk=disk, ports=1, addresses=address)
    spec = topology_edit.connect(spec, ('SW1', 'eth0'), ('SW2', 'eth0'))
    if loop:
        spec = topology_edit.connect(spec, ('SW1', 'eth1'), ('SW2', 'eth1'))
    spec = topology_edit.connect(spec, ('PC1', 'eth0'), ('SW1', 'eth2'))
    return validate(topology_edit.connect(spec, ('PC2', 'eth0'), ('SW2', 'eth2')))


def ports(text):
    """{port label: (role, state)} from « show spanning-tree »."""
    rows = text.split('-' * 19, 1)[1].splitlines()[1:]
    return {row.split()[0]: tuple(row.split()[1:3]) for row in rows}


# What BRIDGE_STP_SHOW prints on SW2 once the tree has converged with SW1 as the root (sysfs: centiseconds, port
# priorities /16).
LISTING = '''bridge stp_state 1
bridge bridge_id 8000.02ccd4f61200
bridge root_id 6000.02e4be7c1600
bridge root_port 1
bridge root_path_cost 19
bridge priority 32768
bridge hello_time 200
bridge max_age 600
bridge forward_delay 400
eth0 port_no 0x1
eth0 state 3
eth0 path_cost 19
eth0 priority 8
eth1 port_no 0x2
eth1 state 4
eth1 path_cost 19
eth1 priority 8
eth2 port_no 0x3
eth2 state 3
eth2 path_cost 19
eth2 priority 8
eth3 port_no 0x4
eth3 state 0
eth3 path_cost 19
eth3 priority 8
'''


class GuestStpTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': lab()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def type(self, name, lines):
        console = guest_console.Console('stp', name, lambda _: self.lab)
        return [console.line(line) for line in lines]

    def node(self, name):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == name)

    def test_the_cable_that_closes_a_loop_turns_stp_on_with_ios_costs(self):
        self.assertEqual((lab(loop=False)['nodes'][0].get('spanning_tree') or {}).get('mode', 'off'), 'off')
        policy = self.node('SW1')['spanning_tree']
        self.assertEqual({k: policy[k] for k in ('mode', 'priority', *LAB_TIMERS)}, {'mode': 'stp', 'priority': 32768, **LAB_TIMERS})
        self.assertEqual({p: s['cost'] for p, s in policy['ports'].items()}, {f'eth{i}': 19 for i in range(4)})  # FastEthernet

    def test_a_stopped_lab_shows_the_port_that_will_block(self):
        root = min(('SW1', 'SW2'), key=lambda n: guest_mac(n, 'eth0'))  # equal priorities: the lowest bridge MAC
        other = 'SW2' if root == 'SW1' else 'SW1'
        shown = self.type(other, ['en', 'show spanning-tree'])[-1]
        self.assertEqual(ports(shown), {'Fa0/1': ('Root', 'FWD'), 'Fa0/2': ('Altn', 'BLK'), 'Fa0/3': ('Desg', 'FWD')})
        self.assertIn('Address     ' + guest_stp.bridge_mac(self.node(root)), shown.split('Bridge ID')[0])
        self.assertIn('Cost        19\n             Port        1(FastEthernet0/1)', shown)
        shown = self.type(root, ['en', 'sh span'])[-1]
        self.assertIn('This bridge is the root', shown)
        self.assertEqual(set(ports(shown).values()), {('Desg', 'FWD')})
        self.assertIn('4 packets received', self.type('PC1', ['ping 192.168.1.20'])[0])

    def test_root_primary_moves_the_root_and_the_blocked_port(self):
        root = min(('SW1', 'SW2'), key=lambda n: guest_mac(n, 'eth0'))
        other = 'SW2' if root == 'SW1' else 'SW1'
        self.type(other, ['en', 'conf t', 'spanning-tree vlan 1 root primary', 'end'])
        self.assertEqual(self.node(other)['spanning_tree']['priority'], 24576)
        self.assertIn('spanning-tree vlan 1 priority 24576', self.type(other, ['en', 'sh run'])[-1])  # what IOS's macro writes
        shown = self.type(other, ['en', 'sh spanning-tree'])[-1]
        self.assertIn('Priority    24577  (priority 24576 sys-id-ext 1)', shown)
        self.assertIn('This bridge is the root', shown)
        self.assertEqual(ports(self.type(root, ['en', 'sh spanning-tree'])[-1])['Fa0/2'], ('Altn', 'BLK'))
        self.type(other, ['en', 'conf t', 'no spanning-tree vlan 1 priority', 'end'])
        self.assertEqual(self.node(other)['spanning_tree']['priority'], 32768)
        self.assertNotIn('spanning-tree vlan', self.type(other, ['en', 'sh run'])[-1])

    def test_port_cost_and_priority_choose_the_root_port(self):
        root = min(('SW1', 'SW2'), key=lambda n: guest_mac(n, 'eth0'))
        other = 'SW2' if root == 'SW1' else 'SW1'
        self.type(other, ['en', 'conf t', 'int fa0/1', 'spanning-tree cost 100', 'end'])  # Fa0/2 is now cheaper to the root
        self.assertEqual(ports(self.type(other, ['en', 'sh spanning-tree'])[-1]),
                         {'Fa0/1': ('Altn', 'BLK'), 'Fa0/2': ('Root', 'FWD'), 'Fa0/3': ('Desg', 'FWD')})
        self.type(other, ['en', 'conf t', 'int fa0/1', 'no spanning-tree cost', 'end'])
        self.assertEqual(self.node(other)['spanning_tree']['ports']['eth0']['cost'], 19)
        # The root's port priority decides between two equal cables: SW2 takes the cable on the root's lower port ID.
        self.type(root, ['en', 'conf t', 'int fa0/2', 'spanning-tree port-priority 64', 'end'])
        self.assertEqual(self.node(root)['spanning_tree']['ports']['eth1']['priority'], 64)
        self.assertEqual(ports(self.type(other, ['en', 'sh spanning-tree'])[-1])['Fa0/2'], ('Root', 'FWD'))
        self.assertIn(' spanning-tree port-priority 64', self.type(root, ['en', 'sh run'])[-1])

    def test_ios_refusals(self):
        replies = self.type('SW1', ['en', 'conf t', 'spanning-tree vlan 1 priority 1000', 'spanning-tree vlan 10 priority 4096',
                                    'int fa0/1', 'spanning-tree port-priority 100', 'end'])
        self.assertIn('% Bridge Priority must be in increments of 4096.', replies[2])
        self.assertIn('un seul arbre 802.1D', replies[3])
        self.assertIn('% Port Priority in increments of 16 is required', replies[5])
        self.assertEqual(self.node('SW1')['spanning_tree']['priority'], 32768)
        self.assertIn('does not exist', self.type('SW1', ['en', 'show spanning-tree vlan 10'])[-1])

    def test_stp_typed_on_a_loop_free_switch_alone(self):
        self.box['spec'] = lab(loop=False)
        self.type('SW1', ['en', 'conf t', 'spanning-tree vlan 1 priority 4096', 'end'])
        self.assertEqual((self.node('SW1')['spanning_tree']['mode'], self.node('SW2')['spanning_tree']['mode']), ('stp', 'off'))
        self.assertEqual(self.type('SW2', ['en', 'show spanning-tree'])[-1], 'No spanning tree instance exists.')
        broken = copy.deepcopy(self.box['spec'])  # a loop needs it on every switch
        broken['links'].append([['SW1', 'eth1'], ['SW2', 'eth1']])
        with self.assertRaises(ValueError):
            validate(broken)

    def test_the_running_bridge_is_read_from_sysfs(self):
        node = self.node('SW2')
        from network_labs.appliances.guest_startup import parse_stp
        shown = guest_stp.render(node, guest_stp.from_guest(parse_stp(LISTING), node))
        self.assertIn('Root ID    Priority    24577\n             Address     02e4.be7c.1600\n             Cost        19\n'
                      '             Port        1(FastEthernet0/1)', shown)
        self.assertIn('Bridge ID  Priority    32769  (priority 32768 sys-id-ext 1)\n             Address     02cc.d4f6.1200', shown)
        self.assertEqual(ports(shown), {'Fa0/1': ('Root', 'FWD'), 'Fa0/2': ('Altn', 'BLK'), 'Fa0/3': ('Desg', 'FWD')})
        self.assertIn('Fa0/2               Altn BLK 19        128.2    P2p', shown)


class GuestStpStartupTest(unittest.TestCase):
    def test_the_switch_boots_with_its_ports_down_until_stp_is_set(self):
        from network_labs.appliances import guest_startup
        node = lab()['nodes'][0]
        calls = []

        def fake(socket, operation, **kw):
            calls.append((operation, kw.get('interface'), kw.get('state'), kw.get('stp')))
            return {'forwarding': '0\n', 'bridge-ports': 'eth0\neth1\neth2\neth3\n'}.get(operation, '')
        with patch.object(guest_startup, 'query', side_effect=fake), patch.object(guest_startup, 'check_switch'):
            guest_startup.apply('/socket', node)
        names = [c[0] for c in calls]
        first_up = next(i for i, c in enumerate(calls) if c[0] == 'link' and c[2] == 'up')
        self.assertLess(names.index('bridge-stp'), first_up)  # no frame crosses a port before the bridge runs STP
        self.assertTrue(all(c[2] == 'down' for c in calls[:first_up] if c[0] == 'link'))
        self.assertEqual(calls[names.index('bridge-stp')][3], {'priority': 32768, **LAB_TIMERS})
        self.assertEqual([c[1:4:2] for c in calls if c[0] == 'bridge-stp-port'],
                         [(f'eth{i}', {'cost': 19, 'priority': 128}) for i in range(4)])

    def test_the_readback_names_a_priority_that_differs(self):
        from network_labs.appliances import guest_startup
        node = lab()['nodes'][0]
        node['spanning_tree']['priority'] = 4096
        with patch.object(guest_startup, 'stp_listing', return_value=guest_startup.parse_stp(LISTING)):
            with self.assertRaises(ValueError) as caught:
                with patch.object(guest_startup, 'query', side_effect=self._switch_replies(node)):
                    guest_startup.check_switch('/socket', node)
        self.assertIn('priority', str(caught.exception))

    @staticmethod
    def _switch_replies(node):
        text = ''.join(f'{i + 2}: eth{i}: <BROADCAST,UP,LOWER_UP>\n' for i in range(4)) + '6: br0: <BROADCAST,UP,LOWER_UP>\n'
        replies = {'bridge-ports': 'eth0\neth1\neth2\neth3\n', 'addresses': text, 'forwarding': '0\n'}
        return lambda socket, operation, **kw: replies[operation]

    def test_guest_macs_are_fixed_and_the_bridge_takes_eth0s(self):
        self.assertEqual(guest_mac('SW1', 'eth0'), guest_mac('SW1', 'eth0'))
        self.assertNotEqual(guest_mac('SW1', 'eth0')[:-3], guest_mac('SW2', 'eth0')[:-3])
        node = lab()['nodes'][0]
        self.assertEqual(guest_stp.bridge_mac(node).replace('.', ''), guest_mac('SW1', 'eth0').replace(':', ''))


if __name__ == '__main__':
    unittest.main()
