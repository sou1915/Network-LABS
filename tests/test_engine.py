import unittest
from network_labs.engine import Lab, demo

class ReachabilityTests(unittest.TestCase):
    def test_inter_vlan_roundtrip(self):
        self.assertTrue(demo().ping('PC1', '192.168.20.10')[0])

    def test_missing_trunk_vlan(self):
        lab = demo()
        lab.links[-1].vlans = [10]
        self.assertFalse(lab.ping('PC1', '192.168.20.10')[0])

    def test_return_gateway_required(self):
        lab = demo()
        lab.nodes['PC2'].gateway = '192.168.20.254'
        self.assertFalse(lab.ping('PC1', '192.168.20.10')[0])

    def test_same_subnet_different_vlan(self):
        lab = demo()
        lab.nodes['PC2'].address = '192.168.10.20/24'
        self.assertFalse(lab.ping('PC1', '192.168.10.20')[0])

    def test_same_vlan_direct(self):
        lab = demo()
        lab.links[1].vlans = [10]
        lab.nodes['PC2'].address = '192.168.10.20/24'
        self.assertTrue(lab.ping('PC1', '192.168.10.20')[0])

    def test_save_roundtrip(self):
        lab = Lab.loads(demo().dumps())
        self.assertTrue(lab.ping('PC1', '192.168.20.10')[0])

    def test_playback_paths_and_reset(self):
        lab = demo()
        lab.ping('PC1', '192.168.20.10')
        self.assertEqual(lab.last_paths, [
            ['PC1', 'SW1', 'R1', 'SW1', 'PC2'],
            ['PC2', 'SW1', 'R1', 'SW1', 'PC1']])
        lab.ping('PC1', 'invalid')
        self.assertEqual(lab.last_paths, [])

    def test_invalid_vlan(self):
        lab = Lab.loads(demo().dumps())
        with self.assertRaises(ValueError):
            lab.connect('PC1', 'R1', vlans=[4095])

if __name__ == '__main__':
    unittest.main()
