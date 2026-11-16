import unittest
from network_labs.engine import Lab,Node,demo
from network_labs.cli import Session

def commands(lab,node,*lines):
    session=Session(lab,node)
    for line in lines:
        result=session.execute(line)
        if result.startswith('%'):
            raise AssertionError((line,result))
    return session

def dhcp_lab():
    lab=demo()
    commands(lab,'R1','en','conf t','ip dhcp excluded-address 192.168.10.1 192.168.10.20','ip dhcp pool USERS','network 192.168.10.0 255.255.255.0','default-router 192.168.10.1','dns-server 1.1.1.1 8.8.8.8','lease 0 1','end')
    return lab

class ServiceTests(unittest.TestCase):
    def test_dtp_auto_auto_access_desirable_auto_trunk(self):
        lab=Lab()
        for name in ('A','B'):
            lab.add(Node(name,'Switch'))
        link=lab.connect('A','B','trunk',[10,20])
        a=commands(lab,'A','en','conf t','int gi0/1','switchport mode dynamic auto')
        b=commands(lab,'B','en','conf t','int gi0/1','switchport mode dynamic auto')
        self.assertEqual(lab.operational_mode(link,'A'),'access')
        self.assertIsNone(lab.path('A','B',20))
        a.execute('switchport mode dynamic desirable')
        self.assertEqual(lab.operational_mode(link,'A'),'trunk')
        self.assertEqual(lab.operational_mode(link,'B'),'trunk')
        self.assertEqual(lab.path('A','B',20),['A','B'])
        a.execute('switchport mode trunk'); a.execute('switchport nonegotiate')
        self.assertEqual(lab.operational_mode(link,'B'),'access')
        self.assertIsNone(lab.path('A','B',20))
        self.assertTrue(b.execute('switchport nonegotiate').startswith('%'))
        b.execute('switchport mode trunk')
        self.assertEqual(lab.path('A','B',20),['A','B'])

    def test_dhcp_exclusions_dns_renew_and_release(self):
        lab=dhcp_lab(); pc=Session(lab,'PC1')
        self.assertIn('DHCP ACK',pc.execute('ip dhcp'))
        self.assertEqual(lab.nodes['PC1'].address,'192.168.10.21/24')
        self.assertEqual(lab.nodes['PC1'].dns,['1.1.1.1','8.8.8.8'])
        self.assertTrue(lab.ping('PC1','192.168.10.1')[0])
        pc.execute('ipconfig /renew')
        self.assertEqual(lab.nodes['PC1'].address,'192.168.10.21/24')
        pc.execute('ip release')
        self.assertEqual(lab.nodes['PC1'].address,'')
        self.assertNotIn('PC1',lab.leases)

    def test_snooping_rejects_untrusted_server_and_records_binding(self):
        lab=dhcp_lab()
        switch=commands(lab,'SW1','en','conf t','ip dhcp snooping','ip dhcp snooping vlan 10')
        pc=Session(lab,'PC1')
        before=lab.nodes['PC1'].address
        self.assertIn('non trusted',pc.execute('ip dhcp'))
        self.assertEqual(lab.nodes['PC1'].address,before)
        self.assertEqual(lab.leases,{})
        switch.execute('int gi0/3'); switch.execute('ip dhcp snooping trust')
        self.assertIn('DHCP ACK',pc.execute('ip dhcp'))
        self.assertIn('192.168.10.21',switch.execute('do show ip dhcp snooping binding'))

    def test_dai_requires_binding_and_rejects_spoofed_ip(self):
        lab=dhcp_lab()
        switch=commands(lab,'SW1','en','conf t','ip dhcp snooping','ip dhcp snooping vlan 10','ip arp inspection vlan 10','int gi0/3','ip dhcp snooping trust','ip arp inspection trust')
        self.assertFalse(lab.ping('PC1','192.168.10.1')[0])
        pc=Session(lab,'PC1'); pc.execute('ip dhcp')
        self.assertTrue(lab.ping('PC1','192.168.10.1')[0])
        pc.execute('ip address 192.168.10.99/24')
        ok,trace=lab.ping('PC1','192.168.10.1')
        self.assertFalse(ok); self.assertIn('ARP Inspection',trace[-1])
        self.assertIn('dropped: 2',switch.execute('do show ip arp inspection statistics'))

    def test_source_guard_and_expired_binding(self):
        lab=dhcp_lab(); lab.clock=lambda:1000
        commands(lab,'SW1','en','conf t','ip dhcp snooping','ip dhcp snooping vlan 10','int gi0/3','ip dhcp snooping trust','int gi0/1','ip verify source')
        self.assertFalse(lab.ping('PC1','192.168.10.1')[0])
        Session(lab,'PC1').execute('ip dhcp')
        self.assertTrue(lab.ping('PC1','192.168.10.1')[0])
        lab.clock=lambda:5000
        self.assertFalse(lab.ping('PC1','192.168.10.1')[0])

    def test_dhcp_pool_state_serializes_runtime_bindings_do_not(self):
        lab=dhcp_lab()
        Session(lab,'PC1').execute('ip dhcp')
        restored=Lab.loads(lab.dumps())
        self.assertEqual(restored.nodes['R1'].dhcp_pools,lab.nodes['R1'].dhcp_pools)
        self.assertEqual(restored.leases,{})
        self.assertIn('DHCP ACK',Session(restored,'PC1').execute('ip dhcp'))

    def test_no_service_dhcp_and_different_vlan_timeout(self):
        lab=dhcp_lab()
        self.assertTrue(Session(lab,'PC2').execute('ip dhcp').startswith('%'))
        commands(lab,'R1','en','conf t','no service dhcp')
        self.assertTrue(Session(lab,'PC1').execute('ip dhcp').startswith('%'))

    def test_pool_exhaustion_is_atomic(self):
        lab=dhcp_lab()
        commands(lab,'R1','en','conf t','ip dhcp excluded-address 192.168.10.1 192.168.10.254')
        before=lab.nodes['PC1'].address
        self.assertTrue(Session(lab,'PC1').execute('ip dhcp').startswith('%'))
        self.assertEqual(lab.nodes['PC1'].address,before)
        self.assertEqual(lab.leases,{})
