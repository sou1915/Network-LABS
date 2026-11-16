import unittest
from network_labs.__main__ import App
from network_labs.engine import Lab,Node
from network_labs.cli import Session
from network_labs.text_lab import parse_lab,export_lab,import_device_config
from network_labs.profiles import PROFILES,profile_role

class LANTests(unittest.TestCase):
    def setUp(self):
        self.lab=App.lan_demo()
    def test_all_lan_endpoints_reachable(self):
        for target in ['printer.lan','nas.lan','camera.lan','phone.lan','sensor.lan']:
            ok,trace=self.lab.ping('PC1',target)
            self.assertTrue(ok,(target,trace))
        self.assertEqual(self.lab.nodes['PC1'].dns,['192.168.10.2'])
    def test_lookup_case_trailing_dot_and_explicit_server(self):
        cli=Session(self.lab,'PC1')
        self.assertIn('192.168.10.20',cli.execute('nslookup PRINTER.LAN.'))
        cli.n.dns=[]
        self.assertIn('192.168.10.30',cli.execute('nslookup nas.lan 192.168.10.2'))
        self.assertTrue(cli.execute('nslookup nas.lan').startswith('%'))
    def test_dns_down_and_vlan_isolation(self):
        self.lab.nodes['SRV1'].ports['eth0'].shutdown=True
        self.assertFalse(self.lab.ping('PC1','printer.lan')[0])
        self.assertTrue(self.lab.ping('PC1','192.168.10.20')[0])
        self.lab.nodes['SRV1'].ports['eth0'].shutdown=False
        self.lab.nodes['SW1'].ports['fa0/2'].access_vlan=20
        self.assertFalse(self.lab.ping('PC1','printer.lan')[0])
    def test_nxdomain_no_false_success_or_old_playback(self):
        self.lab.ping('PC1','printer.lan')
        ok,trace=self.lab.ping('PC1','missing.lan')
        self.assertFalse(ok);self.assertIn('NXDOMAIN',str(trace));self.assertEqual(self.lab.last_paths,[])
    def test_service_disable_and_records_validation_atomic(self):
        cli=Session(self.lab,'SRV1')
        before=self.lab.dumps()
        for command in ['dns record bad..name 1.1.1.1','dns record x.lan invalid','dns record x.lan 1.1.1.1 extra']:
            self.assertTrue(cli.execute(command).startswith('%'))
            self.assertEqual(before,self.lab.dumps())
        cli.execute('no service dns')
        self.assertFalse(self.lab.ping('PC1','printer.lan')[0])
        cli.execute('service dns');cli.execute('no dns record printer.lan')
        self.assertFalse(self.lab.ping('PC1','printer.lan')[0])
    def test_roles_console_and_dns_restricted_to_server(self):
        cli=Session(self.lab,'PRN1')
        self.assertIn('[LAN]>',cli.prompt)
        self.assertIn('Imprimante',cli.execute('show device'))
        self.assertTrue(cli.execute('service dns').startswith('%'))
        self.assertIn('dns record',Session(self.lab,'SRV1').execute('help'))
    def test_serialization_and_text_roundtrip(self):
        for restored in (Lab.loads(self.lab.dumps()),parse_lab(export_lab(self.lab)).lab):
            self.assertEqual(restored.nodes['NAS1'].profile,'synology-ds224')
            self.assertEqual(restored.nodes['SRV1'].dns_records['printer.lan'],'192.168.10.20')
            self.assertTrue(restored.ping('PC1','printer.lan')[0])
    def test_import_server_config_is_atomic(self):
        before=self.lab.dumps()
        with self.assertRaises(ValueError):
            import_device_config('dns record a.lan 1.1.1.1\ndns record b.lan wrong',self.lab,'SRV1')
        self.assertEqual(before,self.lab.dumps())
    def test_all_creatable_profiles_construct(self):
        for p in PROFILES.values():
            if p.creatable:
                node=Node('Device',p.kind,profile=p.id)
                self.assertTrue(node.ports)
                self.assertTrue(profile_role(p))
