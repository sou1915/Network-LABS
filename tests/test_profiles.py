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
