"""ipconfig and arp -a on a PC (Windows style, as Packet Tracer's PCs), show arp on a router and show mac address-table on a
switch, built from what the guest agent reads (« ip addr », « ip route », « ip neigh », the bridge's learned MACs)."""
import unittest

from network_labs.appliances import ios_exec, pc_commands
from tests.test_ios_nat import lab
from tests.test_native_microvm_switch_live import lab as switch_lab

ADDRESSES = """1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue qlen 1000
    inet 127.0.0.1/8 scope host lo
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast qlen 1000
    link/ether 22:d6:a6:88:cf:db brd ff:ff:ff:ff:ff:ff
    inet 192.168.1.10/24 scope global eth0
"""
ROUTES = 'default via 192.168.1.1 dev eth0\n192.168.1.0/24 dev eth0 scope link  src 192.168.1.10\n'
NEIGHBORS = ('192.168.1.1 dev eth0 lladdr 7a:38:59:37:93:55 ref 1 used 0/0/0 probes 4 REACHABLE\n'
             '192.168.1.99 dev eth0  used 0/0/0 probes 6 FAILED\n')


class Console:
    """What ios_exec reads from a console: the node and the guest's replies."""
    def __init__(self, node, replies):
        self.node, self.replies = (lambda: node), replies

    def query(self, operation):
        return self.replies[operation]


class PcTest(unittest.TestCase):
    def test_ipconfig_as_windows_prints_it(self):
        self.assertEqual(pc_commands.ipconfig('PC1', ADDRESSES, ROUTES).splitlines()[-4:],
                         ['   Connection-specific DNS Suffix. . :', '   IPv4 Address. . . . . . . . . . . : 192.168.1.10',
                          '   Subnet Mask . . . . . . . . . . . : 255.255.255.0',
                          '   Default Gateway . . . . . . . . . : 192.168.1.1'])
        full = pc_commands.ipconfig('PC1', ADDRESSES, ROUTES, ['eth0'], full=True)
        self.assertIn('   Physical Address. . . . . . . . . : 22-D6-A6-88-CF-DB', full)
        self.assertIn('   DHCP Enabled. . . . . . . . . . . : Yes', full)
        self.assertIn('   Host Name . . . . . . . . . . . . : PC1', full)

    def test_arp_lists_resolved_neighbours_only(self):
        self.assertEqual(pc_commands.arp(NEIGHBORS, ADDRESSES).splitlines(),
                         ['', 'Interface: 192.168.1.10 --- 0x2', '  Internet Address      Physical Address      Type',
                          '  192.168.1.1           7A-38-59-37-93-55     dynamic'])
        self.assertEqual(pc_commands.arp('', ADDRESSES), 'No ARP Entries Found.')


class IosTablesTest(unittest.TestCase):
    def test_show_arp_has_own_addresses_and_neighbours(self):
        router = next(n for n in lab()['nodes'] if n['name'] == 'R1')
        addresses = ADDRESSES.replace('inet 192.168.1.10/24', 'inet 192.168.1.1/24')
        text = ios_exec.arp(Console(router, {'addresses': addresses, 'neighbors': NEIGHBORS.replace('192.168.1.1 ', '192.168.1.10 ')}))
        self.assertEqual(text.splitlines(), [
            'Protocol  Address          Age (min)  Hardware Addr   Type   Interface',
            'Internet  192.168.1.1             -   22d6.a688.cfdb  ARPA   GigabitEthernet0/0/0',
            'Internet  192.168.1.10            0   7a38.5937.9355  ARPA   GigabitEthernet0/0/0'])

    def test_mac_address_table_from_the_bridge(self):
        switch = next(n for n in switch_lab('/k', '/d')['nodes'] if n['name'] == 'SW1')
        switch.update(vlans=[1, 10], switchports={'eth0': {'mode': 'access', 'vlan': 1}, 'eth1': {'mode': 'access', 'vlan': 10},
                                                   'eth2': {'mode': 'access', 'vlan': 10}})
        # As seen on real KVM: the same MAC learned without VLAN (before filtering) and in VLAN 1 (before Fa0/2 moved).
        learned = ('eth0 1a:de:c7:b4:72:eb 1\neth0 1a:de:c7:b4:72:eb 0\neth0 1a:de:c7:b4:72:eb 1\n'
                   'eth1 7a:38:59:37:93:55 1\neth1 7a:38:59:37:93:55 10\n')
        text = ios_exec.mac_table(Console(switch, {'bridge-fdb': learned}))
        self.assertIn('   1    1ade.c7b4.72eb    DYNAMIC     Fa0/1\n  10    7a38.5937.9355    DYNAMIC     Fa0/2\n', text)
        self.assertTrue(text.endswith('Total Mac Addresses for this criterion: 2'))
        plain = next(n for n in switch_lab('/k', '/d')['nodes'] if n['name'] == 'SW1')  # no VLANs: all in VLAN 1
        self.assertIn('   1    1ade.c7b4.72eb    DYNAMIC     Fa0/1', ios_exec.mac_table(Console(plain,
                {'bridge-fdb': 'eth0 1a:de:c7:b4:72:eb 0\n'})))


if __name__ == '__main__':
    unittest.main()
