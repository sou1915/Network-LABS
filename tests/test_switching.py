import unittest
from network_labs.engine import Lab, Node, demo, switching_demo
from network_labs.cli import Session

class CLITests(unittest.TestCase):
    def setUp(self):
        self.lab=demo()
        self.cli=Session(self.lab,'SW1')

    def config(self,*lines):
        self.cli.execute('enable')
        self.cli.execute('conf t')
        for line in lines:
            result=self.cli.execute(line)
            self.assertFalse(result.startswith('%'),(line,result))

    def test_shutdown_breaks_ping_and_recovers(self):
        self.config('int gi0/1','shutdown')
        self.assertFalse(self.lab.ping('PC1','192.168.20.10')[0])
        self.cli.execute('no shutdown')
        self.assertTrue(self.lab.ping('PC1','192.168.20.10')[0])

    def test_allowed_vlan_breaks_ping(self):
        self.config('int gi0/3','switchport trunk allowed vlan 10')
        self.assertFalse(self.lab.ping('PC1','192.168.20.10')[0])
        self.cli.execute('switchport trunk allowed vlan add 20')
        self.assertTrue(self.lab.ping('PC1','192.168.20.10')[0])

    def test_range_and_vlan_name(self):
        self.config('vlan 30','name USERS','exit','int range gi0/4 - 6','switchport mode access','switchport access vlan 30')
        self.assertEqual(self.lab.nodes['SW1'].vlans['30'],'USERS')
        self.assertTrue(all(self.lab.nodes['SW1'].ports[f'gi0/{i}'].access_vlan==30 for i in range(4,7)))
        self.assertIn('USERS',self.cli.execute('do show vlan brief'))

    def test_unknown_command_does_not_mutate(self):
        self.config('int gi0/1')
        before=self.lab.dumps()
        self.assertTrue(self.cli.execute('switchport voice vlan 200').startswith('%'))
        self.assertEqual(before,self.lab.dumps())

    def test_root_bridge_and_loop_block(self):
        lab=switching_demo()
        session=Session(lab,'SW3')
        for line in ['en','conf t','spanning-tree vlan 10 priority 0']:
            session.execute(line)
        state=lab.stp(10)
        self.assertTrue(all(n['root']=='SW3' for n in state.values()))
        blocked=[p for n in state.values() for p in n['ports'].values() if p[1]=='BLK']
        self.assertEqual(len(blocked),1)
        self.assertTrue(lab.ping('PC1','192.168.20.10')[0])

    def test_lacp_passive_passive_suspends_then_active_recovers(self):
        lab=Lab()
        for name in ('A','B'):
            lab.add(Node(name,'Switch'))
        lab.connect('A','B','trunk',[10])
        lab.connect('A','B','trunk',[10])
        for name in ('A','B'):
            session=Session(lab,name)
            for line in ['en','conf t','int range gi0/1 - 2','channel-group 1 mode passive']:
                self.assertFalse(session.execute(line).startswith('%'))
        self.assertIsNone(lab.path('A','B',10))
        session=Session(lab,'A')
        for line in ['en','conf t','int range gi0/1 - 2','channel-group 1 mode active']:
            session.execute(line)
        self.assertEqual(lab.path('A','B',10),['A','B'])
        self.assertFalse(any(state=='BLK' for n in lab.stp(10).values() for _,state in n['ports'].values()))
        lab.nodes['A'].ports['gi0/1'].shutdown=True
        self.assertEqual(lab.path('A','B',10),['A','B'])

    def test_port_security_shutdown_recovery(self):
        self.config('int gi0/1','switchport port-security','switchport port-security mac-address 00:00:00:00:00:01')
        self.assertFalse(self.lab.ping('PC1','192.168.20.10')[0])
        self.assertTrue(self.lab.nodes['SW1'].ports['gi0/1'].errdisabled)
        self.cli.execute('shutdown')
        self.cli.execute('no shutdown')
        self.assertFalse(self.lab.nodes['SW1'].ports['gi0/1'].errdisabled)

    def test_gateway_ping_and_mac_learning(self):
        self.assertTrue(self.lab.ping('PC1','192.168.10.1')[0])
        self.assertIn(self.lab.nodes['PC1'].mac,self.cli.execute('show mac address-table'))

    def test_router_subinterface_config_and_shutdown(self):
        session=Session(self.lab,'R1')
        for line in ['en','conf t','int gi0/0.10','encapsulation dot1Q 10','ip address 192.168.10.1 255.255.255.0','shutdown']:
            self.assertFalse(session.execute(line).startswith('%'))
        self.assertFalse(self.lab.ping('PC1','192.168.20.10')[0])
        session.execute('no shutdown')
        self.assertTrue(self.lab.ping('PC1','192.168.20.10')[0])

    def test_v2_serialization_and_v1_migration(self):
        self.config('int gi0/1','description Test','shutdown')
        lab=Lab.loads(self.lab.dumps())
        self.assertTrue(lab.nodes['SW1'].ports['gi0/1'].shutdown)
        self.assertFalse(lab.ping('PC1','192.168.20.10')[0])
        import json
        data=json.loads(demo().dumps())
        data['version']=1
        for n in data['nodes']:
            for key in ('ports','vlans','hostname','priorities','startup','stp_mode'):
                n.pop(key,None)
        for link in data['links']:
            for key in ('a_port','b_port','enabled'):
                link.pop(key)
        self.assertTrue(Lab.loads(json.dumps(data)).ping('PC1','192.168.20.10')[0])

    def test_bpdu_guard_and_pc_commands(self):
        lab=switching_demo()
        session=Session(lab,'SW1')
        for command in ['en','conf t','int gi0/4','spanning-tree portfast','spanning-tree bpduguard enable']:
            session.execute(command)
        lab.stp(10)
        self.assertTrue(lab.nodes['SW1'].ports['gi0/4'].errdisabled)
        pc=Session(lab,'PC1')
        self.assertEqual(pc.execute('ip address 10.0.0.10/24'),'Adresse appliquée.')
        self.assertIn('10.0.0.10/24',pc.execute('ipconfig'))
        self.assertTrue(pc.execute('rm -rf /').startswith('%'))

    def test_native_mismatch_is_conservatively_blocked(self):
        self.config('int gi0/3','switchport trunk native vlan 99')
        self.assertFalse(self.lab.ping('PC1','192.168.20.10')[0])

    def test_sticky_survives_save_dynamic_does_not(self):
        self.config('int gi0/1','switchport port-security','switchport port-security mac-address sticky')
        self.assertTrue(self.lab.ping('PC1','192.168.10.1')[0])
        self.assertEqual(Lab.loads(self.lab.dumps()).nodes['SW1'].ports['gi0/1'].secure_macs,[self.lab.nodes['PC1'].mac])
        lab=demo(); session=Session(lab,'SW1')
        for cmd in ['en','conf t','int gi0/1','switchport port-security']:
            session.execute(cmd)
        lab.ping('PC1','192.168.10.1')
        self.assertIn(lab.nodes['PC1'].mac,session.execute('do show port-security interface gi0/1'))
        self.assertEqual(Lab.loads(lab.dumps()).nodes['SW1'].ports['gi0/1'].secure_macs,[])

    def test_restrict_drops_without_errdisable(self):
        self.config('int gi0/1','switchport port-security','switchport port-security mac-address 00:00:00:00:00:01','switchport port-security violation restrict')
        self.assertFalse(self.lab.ping('PC1','192.168.10.1')[0])
        p=self.lab.nodes['SW1'].ports['gi0/1']
        self.assertFalse(p.errdisabled)
        self.assertEqual(p.violations,1)
