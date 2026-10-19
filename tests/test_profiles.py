import unittest
from network_labs.engine import Lab,Node
from network_labs.cli import Session
from network_labs.text_lab import parse_lab,export_lab

class ProfilesTest(unittest.TestCase):
    def test_windows_static(self):
        lab=Lab(); lab.add(Node('PC1','PC',profile='windows-11'))
        cli=Session(lab,'PC1')
        self.assertIn('C:',cli.prompt)
        result=cli.execute('netsh interface ipv4 set address name="Ethernet" source=static address=10.0.0.2 mask=255.255.255.0 gateway=10.0.0.1')
        self.assertEqual(result,'Ok.')
        self.assertEqual(cli.n.address,'10.0.0.2/24')
    def test_linux_roundtrip(self):
        lab=parse_lab('[devices]\nPC1 linux-ubuntu\n[config PC1]\nsudo ip addr add 10.0.0.2/24 dev eth0\nsudo ip route add default via 10.0.0.1').lab
        cli=Session(lab,'PC1')
        self.assertIn('10.0.0.1',cli.execute('ip route'))
        restored=parse_lab(export_lab(lab)).lab
        self.assertEqual(restored.nodes['PC1'].profile,'linux-ubuntu')
        self.assertEqual(Lab.loads(lab.dumps()).nodes['PC1'].profile,'linux-ubuntu')
    def test_reference_rejected(self):
        with self.assertRaises(ValueError):
            Node('SW','Switch',profile='juniper-ex')
    def test_linux_interface_and_dns(self):
        from network_labs.engine import demo
        lab=demo(); lab.nodes['PC1'].profile='linux-debian'
        cli=Session(lab,'PC1')
        self.assertIn('resolvectl',cli.execute('help'))
        self.assertTrue(lab.ping('PC1','192.168.20.10')[0])
        self.assertEqual(cli.execute('sudo ip link set dev eth0 down'),'')
        self.assertIn('DOWN',cli.execute('ip link show'))
        self.assertFalse(lab.ping('PC1','192.168.20.10')[0])
        restored=parse_lab(export_lab(lab)).lab
        self.assertTrue(restored.nodes['PC1'].ports['eth0'].shutdown)
        cli.execute('sudo ip link set dev eth0 up')
        self.assertTrue(lab.ping('PC1','192.168.20.10')[0])
        cli.execute('sudo resolvectl dns eth0 1.1.1.1 8.8.8.8')
        self.assertEqual(cli.n.dns,['1.1.1.1','8.8.8.8'])
        before=lab.dumps()
        self.assertTrue(cli.execute('sudo resolvectl dns eth0 1.1.1.1 invalid').startswith('%'))
        self.assertEqual(before,lab.dumps())
    def test_netsh_validation_atomic(self):
        lab=Lab(); lab.add(Node('PC','PC',profile='windows-11'))
        cli=Session(lab,'PC')
        before=lab.dumps()
        for command in ['netsh interface ipv4 set address name=Ethernet source=static',
                        'netsh interface ipv4 set address name=Ethernet source=static address=10.0.0.2 mask=255.255.255.0 gateway=bad',
                        'netsh interface ipv4 set address name=Ethernet source=dhcp nonsense=yes',
                        'netsh interface ipv4 set dnsservers name=Ethernet source=static address=bad']:
            self.assertTrue(cli.execute(command).startswith('%'),command)
            self.assertEqual(before,lab.dumps())
        self.assertEqual(cli.execute('netsh interface ipv4 set dnsservers name=Ethernet source=static address=1.1.1.1'),'Ok.')
        self.assertEqual(cli.n.dns,['1.1.1.1'])
        self.assertIn('netsh',cli.execute('help'))
    def test_model_ports_and_roundtrip(self):
        for profile,first,count in [('cisco-2960','fa0/1',26),('cisco-9200l','gi1/0/1',28)]:
            lab=Lab(); lab.add(Node('SW','Switch',profile=profile)); lab.add(Node('PC','PC'))
            link=lab.connect('PC','SW',b_port=first)
            self.assertEqual(link.b_port,first)
            self.assertEqual(len(lab.nodes['SW'].ports),count)
            cli=Session(lab,'SW')
            for command in ['enable','configure terminal','vlan 10','exit',f'interface range {first} - 4','switchport access vlan 10']:
                self.assertFalse(cli.execute(command).startswith('%'),command)
            restored=parse_lab(export_lab(lab)).lab
            self.assertEqual(restored.nodes['SW'].profile,profile)
            self.assertEqual(restored.nodes['SW'].ports[first].access_vlan,10)
    def test_static_transition_clears_dhcp_binding(self):
        from network_labs.__main__ import App
        lab=App.security_demo(); cli=Session(lab,'PC1')
        self.assertFalse(cli.execute('ip dhcp').startswith('%'))
        self.assertIn('PC1',lab.leases)
        self.assertTrue(any(record['client']=='PC1' for table in lab.bindings.values() for record in table.values()))
        cli.execute('ip address 192.168.10.100/24')
        self.assertNotIn('PC1',lab.leases)
        self.assertFalse(any(record['client']=='PC1' for table in lab.bindings.values() for record in table.values()))
        self.assertEqual(cli.n.address_mode,'static')
