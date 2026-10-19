import unittest
from network_labs.engine import Lab,Node,switching_demo
from network_labs.cli import Session
from test_services import commands

class Layer2Tests(unittest.TestCase):
    def pair(self):
        lab=Lab()
        for n in ('A','B'):
            lab.add(Node(n,'Switch'))
        lab.connect('A','B','trunk',[1,10,20])
        return lab

    def test_vtp_propagation_names_delete_and_client_rejection(self):
        lab=self.pair()
        a=commands(lab,'A','en','conf t','vtp domain LAB','vtp mode server')
        b=commands(lab,'B','en','conf t','vtp domain LAB','vtp mode client')
        a.execute('vlan 30'); a.execute('name USERS')
        self.assertEqual(lab.nodes['B'].vlans['30'],'USERS')
        self.assertEqual(lab.nodes['A'].vtp_revision,lab.nodes['B'].vtp_revision)
        self.assertTrue(b.execute('vlan 50').startswith('%'))
        a.execute('exit'); a.execute('no vlan 30')
        self.assertNotIn('30',lab.nodes['B'].vlans)

    def test_vtp_password_and_trunk_isolation(self):
        lab=self.pair()
        a=commands(lab,'A','en','conf t','vtp domain LAB','vtp password secret','vtp mode server')
        b=commands(lab,'B','en','conf t','vtp domain LAB','vtp mode client')
        a.execute('vlan 30')
        self.assertNotIn('30',lab.nodes['B'].vlans)
        b.execute('vtp password secret')
        self.assertIn('30',lab.nodes['B'].vlans)
        commands(lab,'B','en','conf t','int gi0/1','shutdown')
        a.execute('vlan 40')
        self.assertNotIn('40',lab.nodes['B'].vlans)
        commands(lab,'B','en','conf t','int gi0/1','no shutdown')
        self.assertIn('40',lab.nodes['B'].vlans)

    def test_vtp_transparent_forwards_without_changing_local_database(self):
        lab=self.pair(); lab.add(Node('C','Switch'))
        lab.connect('B','C','trunk',[1])
        a=commands(lab,'A','en','conf t','vtp domain LAB','vtp mode server')
        commands(lab,'C','en','conf t','vtp domain LAB','vtp mode client')
        a.execute('vlan 77')
        self.assertNotIn('77',lab.nodes['B'].vlans)
        self.assertIn('77',lab.nodes['C'].vlans)

    def mst_lab(self):
        lab=switching_demo()
        for n in ('SW1','SW2','SW3'):
            commands(lab,n,'en','conf t','spanning-tree mst configuration','name CAMPUS','revision 1','instance 1 vlan 10','instance 2 vlan 20','exit','spanning-tree mode mst')
        return lab

    def test_mst_distinct_instance_roots_and_blocking(self):
        lab=self.mst_lab()
        commands(lab,'SW1','en','conf t','spanning-tree mst 1 priority 0')
        commands(lab,'SW3','en','conf t','spanning-tree mst 2 priority 0')
        for v,root in [(10,'SW1'),(20,'SW3')]:
            state=lab.stp(v)
            self.assertEqual({n['root'] for n in state.values()},{root})
            self.assertEqual(sum(status=='BLK' for n in state.values() for _,status in n['ports'].values()),1)
        self.assertTrue(lab.ping('PC1','192.168.20.10')[0])

    def test_mst_same_instance_shared_tree_and_pending_commit(self):
        lab=self.mst_lab()
        for n in ('SW1','SW2','SW3'):
            cli=commands(lab,n,'en','conf t','spanning-tree mst configuration','instance 1 vlan 20')
            self.assertEqual(lab.nodes[n].mst_map['20'],2)
            self.assertIn('Instance 1',cli.execute('show pending'))
            cli.execute('exit')
        self.assertEqual(lab.stp(10),lab.stp(20))
        self.assertTrue(lab.ping('PC1','192.168.20.10')[0])

    def test_mst_boundary_is_explicitly_unsupported(self):
        lab=self.mst_lab()
        lab.nodes['SW3'].mst_revision=2
        self.assertTrue(all(lab.boundary_reason(l) for l in lab.links if 'SW3' in (l.a,l.b)))
        self.assertIsNone(lab.path('SW1','SW3',10))
        self.assertIn('Region CAMPUS',commands(lab,'SW1','en').execute('show spanning-tree mst 1'))

    def test_mst_vtp_persist_configuration(self):
        lab=self.mst_lab()
        commands(lab,'SW1','en','conf t','vtp domain LAB','vtp mode server')
        restored=Lab.loads(lab.dumps())
        self.assertEqual(lab.stp(10),restored.stp(10))
        self.assertEqual(restored.nodes['SW1'].vtp_domain,'LAB')
