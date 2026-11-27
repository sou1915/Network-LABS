"""A stopped lab's CLI: the same terminal, on the project (configuration saved in it; show and ping from the model)."""
import unittest

from network_labs.appliances import guest_console, topology_edit
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project


def project():
    spec = blank_project()
    spec = topology_edit.add_microvm_node(spec, name='R1', role='router', kernel='/k', disk='/d', ports=2, model='cisco-isr4331')
    for name in ('PC1', 'PC2'):
        spec = topology_edit.add_microvm_node(spec, name=name, role='host', kernel='/k', disk='/d', ports=1)
    spec = topology_edit.connect(spec, ('PC1', 'eth0'), ('R1', 'eth0'))
    spec = topology_edit.connect(spec, ('PC2', 'eth0'), ('R1', 'eth1'))
    next(n for n in spec['nodes'] if n['name'] == 'R1')['shutdown'] = ['eth0', 'eth1']
    return validate(spec)


class DraftLabTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': project()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def type(self, node, *lines):
        console = guest_console.Console('mon-lab', node, lambda name: self.lab)
        return [console.line(line) for line in lines]

    def node(self, name):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == name)

    def test_typed_configuration_goes_into_the_project_and_the_model_answers(self):
        replies = self.type('R1', 'en', 'sh ip int br', 'conf t', 'int g0/0/0', 'ip add 192.168.1.1 255.255.255.0', 'no shut',
                            'int g0/0/1', 'ip add 192.168.2.1 255.255.255.0', 'no shut', 'end', 'sh ip route')
        self.assertRegex(replies[1], r'GigabitEthernet0/0/0\s+unassigned\s+YES unset\s+administratively down down')
        self.assertIn('%LINK-5-CHANGED', replies[5])
        self.assertEqual((self.node('R1')['interfaces'], self.node('R1')['shutdown']),
                         ({'eth0': '192.168.1.1/24', 'eth1': '192.168.2.1/24'}, []))
        self.assertIn('C        192.168.2.0/24 is directly connected, GigabitEthernet0/0/1', replies[-1])
        self.assertEqual(self.type('PC1', 'ip addr add 192.168.1.10/24 dev eth0', 'ip route add default via 192.168.1.1'), ['', ''])
        self.assertIn('inet 192.168.1.10/24', self.type('PC1', 'ip addr')[0])
        unreachable = self.type('PC2', 'ip addr add 192.168.2.10/24 dev eth0', 'ping 192.168.1.10')[-1]
        self.assertIn('0 packets received', unreachable)  # PC2 has no gateway yet: the model says so
        self.assertIn('4 packets received', self.type('PC2', 'ip route add default via 192.168.2.1', 'ping 192.168.1.10')[-1])
        self.assertIn('!!!!!', self.type('R1', 'en', 'ping 192.168.2.10')[-1])
        self.assertIn('interface GigabitEthernet0/0/0\n ip address 192.168.1.1 255.255.255.0', self.type('R1', 'en', 'sh run')[-1])

    def test_a_switch_takes_vlans_and_shutdown_typed_on_its_ports(self):
        spec = blank_project()
        spec = topology_edit.add_microvm_node(spec, name='SW1', role='switch', kernel='/k', disk='/d', ports=2, model='cisco-2960')
        for index, name in enumerate(('PC1', 'PC2')):
            spec = topology_edit.add_microvm_node(spec, name=name, role='host', kernel='/k', disk='/d', ports=1,
                                                  addresses=f'10.0.0.{index + 1}/24')
            spec = topology_edit.connect(spec, (name, 'eth0'), ('SW1', f'eth{index}'))
        self.box['spec'] = validate(spec)
        self.assertIn('4 packets received', self.type('PC1', 'ping 10.0.0.2')[-1])
        console = guest_console.Console('mon-lab', 'SW1', lambda name: self.lab)
        for line in ('en', 'conf t', 'vlan 10'):
            console.line(line)
        self.assertEqual(console.prompt(), 'SW1(config-vlan)#')
        replies = [console.line(line) for line in ('name STAFF', 'int fa0/2', 'sw mo acc', 'sw acc vl 10', 'end', 'sh vlan br', 'sh run')]
        self.assertEqual(self.node('SW1')['switchports']['eth1'], {'mode': 'access', 'vlan': 10})
        self.assertRegex(replies[-2], r'1    default\s+active    Fa0/1\n10   STAFF\s+active    Fa0/2\n')
        self.assertIn('vlan 10\n name STAFF\n!', replies[-1])
        self.assertIn('0 packets received', self.type('PC1', 'ping 10.0.0.2')[-1])
        self.type('SW1', 'en', 'conf t', 'int fa0/2', 'switchport access vlan 1', 'int fa0/1', 'shut', 'end')
        self.assertEqual(self.node('SW1')['shutdown'], ['eth0'])
        self.assertRegex(self.type('SW1', 'en', 'sh int status')[-1], r'Fa0/1\s+disabled\s+1\s+auto\s+auto 10/100BaseTX')
        self.assertIn('0 packets received', self.type('PC1', 'ping 10.0.0.2')[-1])
        self.type('SW1', 'en', 'conf t', 'int fa0/1', 'no shutdown', 'end')
        self.assertIn('4 packets received', self.type('PC1', 'ping 10.0.0.2')[-1])


if __name__ == '__main__':
    unittest.main()
