import unittest
from network_labs.engine import Lab,Node
from network_labs.cli import Session
from network_labs.text_lab import parse_lab,export_lab

class FirewallTests(unittest.TestCase):
    def setUp(self):
        self.lab=Lab()
        for node in (Node('PC1','PC',address='10.0.0.1/24'),Node('PC2','PC',address='10.0.0.2/24'),Node('FW','Switch',profile='fw-stateful')):
            self.lab.add(node)
        self.lab.connect('PC1','FW',b_port='gi0/1')
        self.lab.connect('PC2','FW',b_port='gi0/2')
        self.cli=Session(self.lab,'FW')
    def command(self,line):
        result=self.cli.execute(line)
        self.assertFalse(result.startswith('%'),result)
    def test_default_deny_and_stateful_return(self):
        self.assertFalse(self.lab.ping('PC1','10.0.0.2')[0])
        self.command('firewall rule 10 allow 10.0.0.1/32 10.0.0.2/32')
        self.assertTrue(self.lab.ping('PC1','10.0.0.2')[0])
        self.assertIn('session retour',str(self.lab.firewall_log))
        self.assertFalse(self.lab.ping('PC2','10.0.0.1')[0])
    def test_stateless_requires_explicit_return(self):
        self.command('firewall mode stateless')
        self.command('firewall rule 10 allow 10.0.0.1/32 10.0.0.2/32')
        self.assertFalse(self.lab.ping('PC1','10.0.0.2')[0])
        self.command('firewall rule 20 allow 10.0.0.2/32 10.0.0.1/32')
        self.assertTrue(self.lab.ping('PC1','10.0.0.2')[0])
    def test_rule_order_replace_delete_and_counters(self):
        self.command('firewall default allow')
        self.command('firewall rule 20 allow any any')
        self.command('firewall rule 10 deny 10.0.0.0/24 any')
        self.assertFalse(self.lab.ping('PC1','10.0.0.2')[0])
        self.command('firewall rule 10 allow any any')
        self.assertTrue(self.lab.ping('PC1','10.0.0.2')[0])
        self.assertEqual(len(self.cli.n.firewall_rules),2)
        self.command('firewall rule delete 10')
        self.assertEqual(len(self.cli.n.firewall_rules),1)
        self.assertIn('deny',self.cli.execute('show firewall counters'))
    def test_invalid_policy_atomic(self):
        before=self.lab.dumps()
        for command in ['firewall rule 0 allow any any','firewall rule 1 allow bad any','firewall default trust','firewall rule 1 accept any any','firewall rule delete 100']:
            self.assertTrue(self.cli.execute(command).startswith('%'))
            self.assertEqual(before,self.lab.dumps())
    def test_vlan_and_shutdown_still_apply(self):
        self.command('firewall default allow')
        self.cli.n.ports['gi0/1'].shutdown=True
        self.assertFalse(self.lab.ping('PC1','10.0.0.2')[0])
        self.cli.n.ports['gi0/1'].shutdown=False
        self.cli.n.ports['gi0/2'].access_vlan=20
        self.assertFalse(self.lab.ping('PC1','10.0.0.2')[0])
    def test_persistence_without_sessions_or_counters(self):
        self.command('firewall rule 10 allow any any')
        self.assertTrue(self.lab.ping('PC1','10.0.0.2')[0])
        for restored in (Lab.loads(self.lab.dumps()),parse_lab(export_lab(self.lab)).lab):
            self.assertFalse(restored.firewall_sessions)
            self.assertFalse(restored.firewall_counters)
            self.assertTrue(restored.ping('PC1','10.0.0.2')[0])
