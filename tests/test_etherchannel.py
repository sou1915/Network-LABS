"""EtherChannel on switch micro-VMs, typed as on IOS: « channel-group 1 mode active » on SW1's two ports to SW2 and
« mode passive » on SW2's make Port-channel 1, the guests' 802.3ad bond1, one spanning tree port (both cables forward);
« show etherchannel summary » says Po1(SU) with its ports (P). A bundle forms only once both switches have it, with one
active end."""
import unittest
from unittest.mock import patch

from network_labs.appliances import etherchannel, guest_console, topology_edit
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project

SW1 = ['en', 'conf t', 'int range fa0/1 - 2', 'channel-group 1 mode active', 'exit', 'int po1', 'switchport mode trunk', 'end']
SW2 = ['en', 'conf t', 'int range fa0/1 - 2', 'channel-group 1 mode passive', 'exit', 'int po1', 'switchport mode trunk', 'end']

BONDING = '''== bond1
Ethernet Channel Bonding Driver: v5.10.223

Bonding Mode: IEEE 802.3ad Dynamic link aggregation
MII Status: up

802.3ad info
LACP rate: fast
Active Aggregator Info:
	Aggregator ID: 1
	Number of ports: 2
	Actor Key: 15
	Partner Key: 15
	Partner Mac Address: 02:cc:d4:f6:12:00

Slave Interface: eth0
MII Status: up
Speed: 1000 Mbps
Duplex: full
Aggregator ID: 1

Slave Interface: eth1
MII Status: up
Speed: 1000 Mbps
Duplex: full
Aggregator ID: 1
'''


def lab(kernel='/k', disk='/d'):
    """SW1 and SW2 (2960s) joined by Fa0/1 and Fa0/2; PC1 on SW1 Fa0/3, PC2 on SW2 Fa0/3, one LAN."""
    spec = blank_project('etherchannel')
    for name in ('SW1', 'SW2'):
        spec = topology_edit.add_microvm_node(spec, name=name, role='switch', kernel=kernel, disk=disk, ports=4, model='cisco-2960')
    for name, address in (('PC1', '192.168.1.10/24'), ('PC2', '192.168.1.20/24')):
        spec = topology_edit.add_microvm_node(spec, name=name, role='host', kernel=kernel, disk=disk, ports=1, addresses=address)
    spec = topology_edit.connect(spec, ('SW1', 'eth0'), ('SW2', 'eth0'))
    spec = topology_edit.connect(spec, ('SW1', 'eth1'), ('SW2', 'eth1'))
    spec = topology_edit.connect(spec, ('PC1', 'eth0'), ('SW1', 'eth2'))
    return validate(topology_edit.connect(spec, ('PC2', 'eth0'), ('SW2', 'eth2')))


def ports_of(text):
    """{'Po1(SU)': ['Fa0/1(P)', …]} from « show etherchannel summary »."""
    rows = text.split('-' * 47, 1)[1].splitlines()[1:]
    return {row.split()[1]: row.split()[3:] for row in rows if row.strip()}


class EtherChannelTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': lab()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def type(self, name, lines):
        console = guest_console.Console('etherchannel', name, lambda _: self.lab)
        return [console.line(line) for line in lines]

    def node(self, name):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == name)

    def test_the_bundle_forms_once_both_switches_have_it(self):
        self.type('SW1', SW1)
        self.assertEqual(ports_of(self.type('SW1', ['en', 'sh etherchannel summary'])[-1]), {'Po1(SD)': ['Fa0/1(I)', 'Fa0/2(I)']})
        self.type('SW2', SW2)
        for name in ('SW1', 'SW2'):
            self.assertEqual(ports_of(self.type(name, ['en', 'sh etherchannel summary'])[-1]), {'Po1(SU)': ['Fa0/1(P)', 'Fa0/2(P)']})
        self.assertEqual(self.node('SW1')['port_channels'], {'bond1': {'members': ['eth0', 'eth1'], 'mode': 'active', 'min_links': 1}})
        self.assertEqual(self.node('SW1')['switchports']['bond1']['mode'], 'trunk')
        self.assertNotIn('eth0', self.node('SW1')['switchports'])  # the members follow the bundle
        self.assertIn('4 packets received', self.type('PC1', ['ping 192.168.1.20'])[0])

    def test_one_spanning_tree_port_and_nothing_blocked(self):
        self.type('SW1', SW1)
        self.type('SW2', SW2)
        from network_labs.appliances.guest_stp import blocked_ports
        self.assertEqual(blocked_ports(self.box['spec']), set())  # the two cables are one link: no loop to break
        shown = self.type('SW1', ['en', 'sh spanning-tree'])[-1]
        self.assertRegex(shown, r'Po1 +(Root|Desg) FWD 12 ')  # IOS's cost of two FastEthernet ports bundled
        self.assertNotRegex(shown, r'Fa0/[12] ')

    def test_passive_on_both_ends_never_forms(self):
        self.type('SW1', [line.replace('active', 'passive') for line in SW1])
        self.type('SW2', SW2)
        self.assertEqual(etherchannel.partners(self.box['spec']), {})
        self.assertIn('Po1(SD)', self.type('SW2', ['en', 'sh etherchannel summary'])[-1])

    def test_member_lines_configure_the_bundle_and_the_running_config_shows_both(self):
        self.type('SW1', SW1 + ['en', 'conf t', 'vlan 10', 'int fa0/2', 'switchport trunk allowed vlan 1,10', 'end'])
        self.assertEqual(self.node('SW1')['switchports']['bond1']['allowed'], [1, 10])
        config = self.type('SW1', ['en', 'sh run'])[-1]
        self.assertIn('interface Port-channel1\n switchport mode trunk', config)
        self.assertIn('interface FastEthernet0/2\n switchport mode trunk', config)
        self.assertIn(' switchport trunk allowed vlan 1,10\n channel-group 1 mode active', config)

    def test_leaving_and_removing_the_bundle(self):
        self.type('SW1', SW1 + ['en', 'conf t', 'int fa0/2', 'no channel-group', 'end'])
        self.assertEqual(self.node('SW1')['port_channels']['bond1']['members'], ['eth0'])
        self.assertEqual(self.node('SW1')['switchports']['eth1']['mode'], 'trunk')  # it keeps the bundle's settings
        self.type('SW1', ['en', 'conf t', 'no interface port-channel 1', 'end'])
        self.assertEqual(self.node('SW1')['port_channels'], {})
        self.assertEqual(self.node('SW1')['switchports']['eth0']['mode'], 'trunk')

    def test_ios_refusals(self):
        replies = self.type('SW1', ['en', 'conf t', 'int fa0/1', 'channel-group 1 mode on', 'channel-group 1 mode active',
                                    'int fa0/2', 'channel-group 1 mode passive', 'end'])
        self.assertIn('LACP', replies[3])
        self.assertIn('même mode', replies[6])


class EtherChannelGuestTest(unittest.TestCase):
    def node(self, name='SW1'):
        box = {'spec': lab()}
        draft = DraftLab(lambda: box['spec'], lambda spec: box.update(spec=validate(spec)))
        for switch, lines in (('SW1', SW1), ('SW2', SW2)):
            console = guest_console.Console('etherchannel', switch, lambda _: draft)
            for line in lines:
                console.line(line)
        return next(n for n in box['spec']['nodes'] if n['name'] == name)

    def test_boot_builds_the_bond_before_the_bridge(self):
        from network_labs.appliances import guest_startup
        node = self.node()
        calls = []

        def fake(socket, operation, **kw):
            calls.append((operation, kw.get('interface'), kw.get('state')))
            return {'forwarding': '0\n'}.get(operation, '')
        with patch.object(guest_startup, 'query', side_effect=fake), patch.object(guest_startup, 'check_switch'):
            guest_startup.apply('/socket', node)
        start = calls.index(('bond-add', 'bond1', None))
        self.assertEqual(calls[start:start + 5], [('bond-add', 'bond1', None), ('link', 'eth0', 'down'), ('bond-slave', 'bond1', 'eth0'),
                                                  ('link', 'eth1', 'down'), ('bond-slave', 'bond1', 'eth1')])
        added = [c[1] for c in calls if c[0] == 'bridge-add']
        self.assertEqual(added, ['eth2', 'eth3', 'bond1'])  # the members are the bond's, not the bridge's
        self.assertIn(('bridge-stp-port', 'bond1', None), calls)
        self.assertIn(('link', 'eth0', 'up'), calls[calls.index(('bridge-add', 'bond1', None)):])

    def test_the_guest_bonds_say_which_members_are_bundled(self):
        self.assertEqual(etherchannel.parse_bonds(BONDING), {'bond1': {'up': True, 'bundled': {'eth0', 'eth1'}}})
        alone = BONDING.replace('Partner Mac Address: 02:cc:d4:f6:12:00', 'Partner Mac Address: 00:00:00:00:00:00')
        self.assertEqual(etherchannel.parse_bonds(alone)['bond1']['bundled'], set())  # no LACP partner: individual
        node = self.node()
        shown = etherchannel.summary({'nodes': [node], 'links': []}, node, etherchannel.parse_bonds(BONDING))
        self.assertEqual(ports_of(shown), {'Po1(SU)': ['Fa0/1(P)', 'Fa0/2(P)']})


if __name__ == '__main__':
    unittest.main()
