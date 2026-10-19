import unittest
from network_labs.engine import Lab,Node
from network_labs.cli import Session

class AccessMulticastTests(unittest.TestCase):
    def setUp(self):
        self.lab=Lab()
        self.lab.add(Node('SW','Switch'))
        for i in range(1,4):
            self.lab.add(Node('PC'+str(i),'PC',address=f'10.0.0.{i}/24'))
            self.lab.connect('PC'+str(i),'SW')
    def test_auth_gate_credentials_logoff(self):
        cli=Session(self.lab,'SW')
        for command in ['enable','configure terminal','aaa new-model','aaa authentication dot1x default group radius','dot1x system-auth-control','interface gi0/1','authentication port-control auto','dot1x pae authenticator']:
            self.assertFalse(cli.execute(command).startswith('%'),command)
        self.assertFalse(self.lab.ping('PC1','10.0.0.2')[0])
        self.lab.radius_users['Alice']='Secret'
        pc=Session(self.lab,'PC1')
        self.assertTrue(pc.execute('dot1x login Alice wrong').startswith('%'))
        self.assertIn('Access-Accept',pc.execute('dot1x login Alice Secret'))
        self.assertTrue(self.lab.ping('PC1','10.0.0.2')[0])
        self.assertFalse(Lab.loads(self.lab.dumps()).auth_sessions)
        pc.execute('dot1x logoff')
        self.assertFalse(self.lab.ping('PC1','10.0.0.2')[0])
    def test_snooping_prunes_known_and_unknown_policy(self):
        self.lab.join_group('PC2','239.1.1.1')
        self.lab.multicast('PC1','239.1.1.1')
        self.assertEqual(self.lab.last_multicast,['PC2'])
        self.lab.nodes['SW'].igmp_enabled=False
        self.lab.multicast('PC1','239.1.1.1')
        self.assertEqual(set(self.lab.last_multicast),{'PC2','PC3'})
        self.lab.nodes['SW'].igmp_enabled=True
        self.lab.nodes['SW'].igmp_unknown='drop'
        self.lab.multicast('PC1','239.2.2.2')
        self.assertEqual(self.lab.last_multicast,[])
