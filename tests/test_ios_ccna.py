"""The CCNA / Packet Tracer command set on a Cisco device: typed in its CLI (here on the project, lab stopped)."""
import unittest

from network_labs.appliances import guest_console, ios_store, topology_edit
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.network_model import Model
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project


def project():
    spec = blank_project()
    spec = topology_edit.add_microvm_node(spec, name='R1', role='router', kernel='/k', disk='/d', ports=2, model='cisco-isr4331',
                                          addresses='192.168.1.1/24,192.168.2.1/24')
    spec = topology_edit.add_microvm_node(spec, name='R2', role='router', kernel='/k', disk='/d', ports=2, model='cisco-isr4331',
                                          addresses='192.168.2.2/24,10.0.0.1/24')
    spec['nodes'][-1]['guest_network'] = {'addresses': [], 'routes': [{'network': '192.168.1.0/24', 'gateway': '192.168.2.1'}]}
    spec = topology_edit.add_microvm_node(spec, name='SW1', role='switch', kernel='/k', disk='/d', ports=4, model='cisco-2960')
    spec = topology_edit.add_microvm_node(spec, name='PC1', role='host', kernel='/k', disk='/d', ports=1, addresses='192.168.1.10/24')
    spec['nodes'][-1]['gateway'] = '192.168.1.1'
    for a, b in ((('R1', 'eth1'), ('R2', 'eth0')), (('PC1', 'eth0'), ('SW1', 'eth0')), (('SW1', 'eth1'), ('R1', 'eth0'))):
        spec = topology_edit.connect(spec, a, b)
    return validate(spec)


class CcnaTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': project()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def console(self, node):
        return guest_console.Console('mon-lab', node, lambda name: self.lab)

    def run_lines(self, console, *lines):
        return [console.line(line) for line in lines]

    def node(self, name):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == name)

    def test_basic_device_security_as_in_the_ccna(self):
        r1 = self.console('R1')
        self.run_lines(r1, 'en', 'conf t', 'hostname R-CENTRE', 'enable secret class', 'service password-encryption',
                       'no ip domain-lookup', 'banner motd #Acces reserve#', 'line con 0', 'password cisco', 'login',
                       'logging synchronous', 'exit', 'line vty 0 4', 'transport input ssh', 'login local', 'exit',
                       'username admin privilege 15 secret cisco123', 'ip domain-name lab.local', 'crypto key generate rsa modulus 1024',
                       'ip ssh version 2', 'end')
        self.assertEqual(r1.prompt(), 'R-CENTRE#')
        running = r1.line('show running-config')
        for expected in ('hostname R-CENTRE', 'service password-encryption', 'enable secret 5 $1$', 'no ip domain-lookup',
                         'banner motd ^CAcces reserve^C', 'line con 0\n password 7 02050D480809\n login\n logging synchronous',
                         'line vty 0 4\n transport input ssh\n login local', 'ip ssh version 2'):
            self.assertIn(expected, running)
        self.assertNotIn('no service password-encryption', running)
        self.assertEqual(r1.line('show running-config | include password'), 'service password-encryption\n password 7 02050D480809')
        self.assertEqual(r1.line('sh run | section line con'), 'line con 0\n password 7 02050D480809\n login\n logging synchronous')
        self.assertTrue(r1.line('sh run | begin line vty').startswith('line vty 0 4'))
        fresh = self.console('R1')  # a new console session: banner, then the console password, then enable's secret
        self.assertEqual(fresh.greeting(), 'Acces reserve\n\nUser Access Verification\n')
        self.assertEqual(fresh.prompt(), 'Password: ')
        self.assertEqual(fresh.line('wrong'), '')
        self.assertEqual(fresh.line('cisco'), '')
        self.assertEqual(fresh.prompt(), 'R-CENTRE>')
        fresh.line('enable')
        self.assertEqual(fresh.prompt(), 'Password: ')
        for _ in range(2):
            self.assertEqual(fresh.line('nope'), '')
        self.assertEqual(fresh.line('nope'), '% Bad secrets')
        fresh.line('enable')
        fresh.line('class')
        self.assertEqual(fresh.prompt(), 'R-CENTRE#')

    def test_save_startup_cdp_version_history_and_rip_stored(self):
        r1 = self.console('R1')
        self.run_lines(r1, 'en')
        self.assertEqual(r1.line('show startup-config'), 'startup-config is not present')
        self.assertEqual(r1.line('wr'), 'Building configuration...\n[OK]')
        self.assertIn('interface GigabitEthernet0/0/0', r1.line('show startup-config'))
        cdp = r1.line('show cdp neighbors')
        self.assertRegex(cdp, r'R2\s+Gig 0/0/1\s+160\s+R\s+ISR4331\s+Gig 0/0/0')
        self.assertRegex(cdp, r'SW1\s+Gig 0/0/0\s+160\s+S\s+')
        self.assertNotIn('PC1', cdp)  # a PC does not speak CDP
        self.assertIn('2 Gigabit Ethernet interfaces', r1.line('show version'))
        self.assertIn('  show version', r1.line('show history'))
        self.run_lines(r1, 'conf t', 'router rip', 'version 2', 'network 192.168.1.0', 'no auto-summary', 'end')
        self.assertIn('router rip\n version 2\n network 192.168.1.0\n no auto-summary', r1.line('show run'))
        self.assertIn('Routing Protocol is "rip"', r1.line('show ip protocols'))
        self.assertIn('Description: vers R2', self.run_lines(r1, 'conf t', 'int g0/0/1', 'description vers R2', 'end',
                                                             'show interfaces g0/0/1')[-1])

    def test_numbered_acl_filters_for_real_and_interface_range_on_a_switch(self):
        self.assertTrue(Model(self.box['spec']).ping('PC1', '192.168.2.2')[0])
        r1 = self.console('R1')
        self.run_lines(r1, 'en', 'conf t', 'access-list 1 deny host 192.168.1.10', 'access-list 1 permit any',
                       'int g0/0/0', 'ip access-group 1 in', 'end')
        self.assertIn('access-list 1 deny host 192.168.1.10\naccess-list 1 permit any', r1.line('show run'))
        self.assertFalse(Model(self.box['spec']).ping('PC1', '192.168.2.2')[0])  # the list really drops PC1
        sw = self.console('SW1')
        self.run_lines(sw, 'en', 'conf t', 'interface range fa0/1 - 3', 'switchport mode access', 'switchport access vlan 10',
                       'spanning-tree portfast', 'end')
        self.assertEqual(sw.prompt(), 'SW1#')
        node = self.node('SW1')
        self.assertEqual([node['switchports'][p]['vlan'] for p in ('eth0', 'eth1', 'eth2')], [10, 10, 10])
        self.assertEqual(ios_store.config(node)['interfaces']['eth2'], ['spanning-tree portfast'])
        self.assertIn('(config-if-range)#', (sw.line('conf t'), sw.line('int range fa0/1 - 2'), sw.prompt())[2])

    def test_pat_overload_lets_a_private_lan_reach_a_network_that_has_no_route_back(self):
        spec = self.box['spec']
        r2 = next(n for n in spec['nodes'] if n['name'] == 'R2')
        r2['guest_network'] = {'addresses': [], 'routes': []}  # R2 knows nothing of 192.168.1.0/24
        self.box['spec'] = validate(spec)
        r1 = self.console('R1')
        self.run_lines(r1, 'en', 'conf t', 'ip route 0.0.0.0 0.0.0.0 192.168.2.2', 'end')
        self.assertFalse(Model(self.box['spec']).ping('PC1', '10.0.0.1')[0])  # the reply has no way back
        self.run_lines(r1, 'conf t', 'access-list 1 permit 192.168.1.0 0.0.0.255',
                       'ip nat inside source list 1 interface g0/0/1 overload', 'end')
        self.assertFalse(Model(self.box['spec']).ping('PC1', '10.0.0.1')[0])  # no inside/outside ports: IOS does not translate
        self.run_lines(r1, 'conf t', 'int g0/0/0', 'ip nat inside', 'int g0/0/1', 'ip nat outside', 'end')
        from network_labs.appliances.acl import policy
        self.assertEqual(policy(self.node('R1'))['nat'], [{'name': 'nat-1-1', 'type': 'masquerade', 'out': 'eth1', 'protocol': 'any',
                                                          'source': '192.168.1.0/24'}])
        ok, why = Model(self.box['spec']).ping('PC1', '10.0.0.1')
        self.assertTrue(ok, why)  # PC1 leaves as 192.168.2.1, R2 answers it
        self.assertIn('Dynamic mappings: 1 (overload)', r1.line('show ip nat statistics'))
        self.assertTrue(r1.line('show ip nat translations').startswith('Pro  Inside global'))


if __name__ == '__main__':
    unittest.main()
