"""IOS static NAT and NAT pools typed in a router's terminal: compiled into the guest NAT entries, the public addresses
the router holds on its outside port, and the network model's verdicts."""
import unittest

from network_labs.appliances import guest_console, ios_nat, topology_edit
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.network_model import Model
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project

MARKS = ['conf t', 'ip route 0.0.0.0 0.0.0.0 203.0.113.2', 'int g0/0/0', 'ip nat inside', 'int g0/0/1', 'ip nat outside', 'end']
STATIC = ['conf t', 'ip nat inside source static 192.168.1.10 203.0.113.10', 'end']
POOL = ['conf t', 'no ip nat inside source static 192.168.1.10 203.0.113.10',
        'ip nat pool PUBLIC 203.0.113.20 203.0.113.21 netmask 255.255.255.0',
        'access-list 2 permit 192.168.1.0 0.0.0.255', 'ip nat inside source list 2 pool PUBLIC', 'end']


def lab(kernel='/k', disk='/d'):
    """PC1 192.168.1.10 — R1 (Cisco) 203.0.113.1/24 — R2 203.0.113.2/24 — PC9 198.51.100.10. R2 knows no 192.168.1.0/24."""
    spec = blank_project('ios-static-nat')
    spec = topology_edit.add_microvm_node(spec, name='R1', role='router', kernel=kernel, disk=disk, ports=2, model='cisco-isr4331',
                                          addresses='192.168.1.1/24,203.0.113.1/24')
    spec = topology_edit.add_microvm_node(spec, name='R2', role='router', kernel=kernel, disk=disk, ports=2, model='cisco-isr4331',
                                          addresses='203.0.113.2/24,198.51.100.1/24')
    for name, address, gateway in (('PC1', '192.168.1.10/24', '192.168.1.1'), ('PC9', '198.51.100.10/24', '198.51.100.1')):
        spec = topology_edit.add_microvm_node(spec, name=name, role='host', kernel=kernel, disk=disk, ports=1, addresses=address)
        spec['nodes'][-1]['gateway'] = gateway
    spec = topology_edit.connect(spec, ('PC1', 'eth0'), ('R1', 'eth0'))
    spec = topology_edit.connect(spec, ('R1', 'eth1'), ('R2', 'eth0'))
    spec = topology_edit.connect(spec, ('R2', 'eth1'), ('PC9', 'eth0'))
    return validate(spec)


class IosNatTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': lab()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))
        self.r1 = guest_console.Console('ios-static-nat', 'R1', lambda name: self.lab)
        self.r1.line('en')

    def type(self, lines):
        return [self.r1.line(line) for line in lines]

    def r1_node(self):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == 'R1')

    def ping(self, source, destination):
        return Model(self.box['spec']).ping(source, destination)

    def test_static_nat_publishes_the_inside_host_and_translates_its_traffic(self):
        self.assertFalse(self.ping('PC9', '203.0.113.10')[0])  # nobody holds it yet
        self.type(STATIC)
        self.assertEqual(ios_nat.public_addresses(self.r1_node()), {})  # no inside / outside ports: IOS does nothing
        self.type(MARKS)
        node = self.r1_node()
        self.assertEqual(ios_nat.public_addresses(node), {'eth1': ['203.0.113.10/32']})
        self.assertEqual([(e['type'], e.get('in') or e.get('out'), e.get('destination') or e.get('source'), e['to'])
                          for e in ios_nat.entries(node)],
                         [('dnat', 'eth1', '203.0.113.10/32', '192.168.1.10'), ('snat', 'eth1', '192.168.1.10/32', '203.0.113.10')])
        ok, why = self.ping('PC9', '203.0.113.10')
        self.assertTrue(ok, why)  # reached by its public address, through R1
        ok, why = self.ping('PC1', '198.51.100.10')
        self.assertTrue(ok, why)  # R2 has no route to 192.168.1.0/24: PC1 leaves as 203.0.113.10
        self.assertRegex(self.r1.line('show ip nat translations'), r'\n---  203\.0\.113\.10\s+192\.168\.1\.10\s+---\s+---')
        self.assertIn('Total active translations: 1 (1 static, 0 dynamic; 0 extended)', self.r1.line('show ip nat statistics'))

    def test_a_pool_translates_to_its_addresses_with_or_without_overload(self):
        self.type(MARKS + STATIC + POOL)
        node = self.r1_node()
        self.assertEqual(ios_nat.public_addresses(node), {'eth1': ['203.0.113.20/32', '203.0.113.21/32']})
        self.assertEqual([(e['type'], e['to']) for e in ios_nat.entries(node)], [('snat', '203.0.113.20-203.0.113.21')])
        self.assertFalse(self.ping('PC9', '203.0.113.10')[0])  # the static entry is gone, its address with it
        ok, why = self.ping('PC1', '198.51.100.10')
        self.assertTrue(ok, why)
        self.type(['conf t', 'ip nat inside source list 2 pool PUBLIC overload', 'end'])
        self.assertEqual([(e['type'], e['to']) for e in ios_nat.entries(self.r1_node())], [('snat', '203.0.113.20')])
        self.assertIn('[Id: 1] access-list 2 pool PUBLIC overload', self.r1.line('show ip nat statistics'))
        self.assertIn('ip nat pool PUBLIC 203.0.113.20 203.0.113.21 netmask 255.255.255.0', self.r1.line('show run'))

    def test_the_guest_takes_a_source_nat_range_only_ascending(self):
        from network_labs.appliances.guest_control import nat_to
        self.assertEqual(nat_to('203.0.113.20-203.0.113.21', 'snat'), '203.0.113.20-203.0.113.21')
        for value, kind in (('203.0.113.21-203.0.113.20', 'snat'), ('203.0.113.20-203.0.113.21', 'dnat')):
            with self.assertRaisesRegex(ValueError, 'range'):
                nat_to(value, kind)

    def test_a_pool_beyond_the_lab_limit_is_not_used(self):
        self.type(MARKS + ['conf t', 'ip nat pool BIG 203.0.113.20 203.0.113.200 netmask 255.255.255.0',
                           'access-list 2 permit any', 'ip nat inside source list 2 pool BIG', 'end'])
        self.assertEqual((ios_nat.entries(self.r1_node()), ios_nat.public_addresses(self.r1_node())), ([], {}))


if __name__ == '__main__':
    unittest.main()
