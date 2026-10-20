import unittest
from network_labs.__main__ import App
from network_labs.cli import Session
from network_labs.engine import Lab
from network_labs.text_lab import parse_lab,export_lab

class TransportTests(unittest.TestCase):
    def setUp(self):self.lab=App.firewall_demo();self.fw=Session(self.lab,'FW1')
    def command(self,line):self.assertFalse(self.fw.execute(line).startswith('%'),line)
    def test_tcp_policy_port_and_stateful_return(self):
        self.command('firewall rule 20 allow tcp 192.168.10.10/32 192.168.10.20/32 445')
        ok,trace=self.lab.probe('PC1','192.168.10.20','tcp',445)
        self.assertTrue(ok,trace);self.assertIn('session retour',str(self.lab.firewall_log))
        self.assertFalse(self.lab.probe('NAS1','192.168.10.10','tcp',445)[0])
        self.assertFalse(self.lab.probe('PC1','192.168.10.20','tcp',443)[0])
        self.assertFalse(self.lab.probe('PC1','192.168.10.20','udp',445)[0])
    def test_stateless_requires_reverse_rule(self):
        self.command('firewall mode stateless');self.command('firewall rule 20 allow tcp 192.168.10.10/32 192.168.10.20/32 445')
        self.assertFalse(self.lab.probe('PC1','192.168.10.20','tcp',445)[0])
        self.command('firewall rule 30 allow tcp 192.168.10.20/32 192.168.10.10/32 445')
        self.assertTrue(self.lab.probe('PC1','192.168.10.20','tcp',445)[0])
    def test_closed_service_and_persistence(self):
        self.command('firewall rule 20 allow tcp any any any')
        Session(self.lab,'NAS1').execute('unlisten tcp 445')
        ok,trace=self.lab.probe('PC1','192.168.10.20','tcp',445)
        self.assertFalse(ok);self.assertIn('aucun service',str(trace))
        for lab in (Lab.loads(self.lab.dumps()),parse_lab(export_lab(self.lab)).lab):
            self.assertEqual(lab.nodes['NAS1'].services,{})
            self.assertFalse(lab.probe('PC1','192.168.10.20','tcp',445)[0])
    def test_dns_now_checks_udp53(self):
        self.lab.nodes['NAS1'].profile='server-linux';self.lab.nodes['NAS1'].dns_service=True
        self.lab.nodes['NAS1'].dns_records={'files.lan':'192.168.10.20'};self.lab.nodes['PC1'].dns=['192.168.10.20']
        self.assertTrue(self.lab.ping('PC1','192.168.10.20')[0])
        self.assertFalse(self.lab.ping('PC1','files.lan')[0])
        self.command('firewall rule 5 allow udp 192.168.10.10/32 192.168.10.20/32 53')
        self.assertTrue(self.lab.ping('PC1','files.lan')[0])
    def test_service_cli_validation_and_probe(self):
        cli=Session(self.lab,'NAS1');before=self.lab.dumps()
        for command in ['listen tcp 0 bad','listen udp 65536 bad','listen http 80 bad']:
            self.assertTrue(cli.execute(command).startswith('%'));self.assertEqual(before,self.lab.dumps())
        cli.execute('listen tcp 443 HTTPS');self.command('firewall rule 5 allow tcp any any 443')
        self.assertTrue(Session(self.lab,'PC1').execute('probe tcp 192.168.10.20 443').startswith('SUCCESS'))
        self.assertIn('TCP/443',self.fw.execute('show firewall sessions'))
    def test_link_shutdown_still_blocks_service(self):
        self.command('firewall rule 5 allow tcp any any 445')
        self.lab.nodes['NAS1'].ports['eth0'].shutdown=True
        self.assertFalse(self.lab.probe('PC1','192.168.10.20','tcp',445)[0])
    def test_service_lab_named_port_probes(self):
        lab=App.service_demo()
        self.assertTrue(lab.probe('PC1','nas.lan','tcp',445)[0])
        self.assertTrue(lab.probe('PC1','printer.lan','tcp',9100)[0])
        ok,trace=lab.probe('PC1','camera.lan','tcp',554)
        self.assertFalse(ok);self.assertIn('règle 40',str(trace))
        self.assertFalse(lab.ping('PC1','nas.lan')[0])
        restored=parse_lab(export_lab(lab)).lab
        self.assertTrue(restored.probe('PC1','nas.lan','tcp',445)[0])
