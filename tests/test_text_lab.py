import unittest
from pathlib import Path
from network_labs.engine import demo
from network_labs.__main__ import App
from network_labs.cli import Session
from network_labs.text_lab import parse_lab,export_lab,import_device_config,LabTextError

class TextLabTests(unittest.TestCase):
    def sample(self):
        return Path('examples/inter_vlan.lab.txt').read_text()

    def test_builds_working_topology(self):
        result=parse_lab(self.sample())
        self.assertEqual(len(result.lab.nodes),4)
        self.assertEqual(len(result.lab.links),3)
        self.assertTrue(result.lab.ping('PC1','192.168.20.10')[0])

    def test_failure_has_line_and_original_untouched(self):
        lab=demo(); before=lab.dumps()
        with self.assertRaises(LabTextError) as caught:
            import_device_config('interface gi0/1\nshutdown\nunsupported command',lab,'SW1')
        self.assertEqual(caught.exception.issues[0].line,3)
        self.assertEqual(before,lab.dumps())

    def test_structural_errors_precise(self):
        for text,line in [('[devices]\nA Switch\nA PC',3),('[devices]\nA Switch\n[links]\nA:gi0/1 MISSING:eth0',4),('[wrong]\nhello',1)]:
            with self.assertRaises(LabTextError) as caught:
                parse_lab(text)
            self.assertEqual(caught.exception.issues[0].line,line)

    def test_single_device_raw_cli_or_prompt_transcript(self):
        result=import_device_config('SW1# configure terminal\nSW1(config)# interface gi0/1\nSW1(config-if)# shutdown\nend',demo(),'SW1')
        self.assertTrue(result.lab.nodes['SW1'].ports['gi0/1'].shutdown)

    def test_roundtrip_all_integrated_labs(self):
        for factory in (demo,App.channel_demo,App.security_demo,App.vtp_demo,App.mst_demo):
            with self.subTest(factory=factory.__name__):
                lab=factory()
                if factory==App.security_demo:
                    Session(lab,'PC1').execute('ip dhcp'); Session(lab,'PC2').execute('ip dhcp')
                restored=parse_lab(export_lab(lab)).lab
                self.assertEqual(set(lab.nodes),set(restored.nodes))
                self.assertEqual(len(lab.links),len(restored.links))
                target=restored.nodes['PC2'].address.split('/')[0]
                if target:
                    self.assertTrue(restored.ping('PC1',target)[0])

    def test_unsupported_configuration_rejected_not_ignored(self):
        text=self.sample().replace('vlan 10','switchport voice vlan 10',1)
        with self.assertRaises(LabTextError) as caught:
            parse_lab(text)
        self.assertIn('SW1',str(caught.exception))

    def test_pc_dns_and_hostname_survive_export(self):
        lab=demo()
        Session(lab,'PC1').execute('hostname WORKSTATION')
        Session(lab,'PC1').execute('ip dns 1.1.1.1 8.8.8.8')
        restored=parse_lab(export_lab(lab)).lab
        self.assertEqual(restored.nodes['PC1'].dns,['1.1.1.1','8.8.8.8'])
        self.assertEqual(restored.nodes['PC1'].hostname,'WORKSTATION')
