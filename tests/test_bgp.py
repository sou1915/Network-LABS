"""eBGP on router micro-VMs with FRR: the agent's configuration, the typed wire, vendor CLIs, show commands, the model."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from network_labs.appliances import bgp, missions, vendor_show
from network_labs.appliances.guest_control import bgp_fields, request
from network_labs.appliances.guest_startup import learned
from network_labs.appliances.microvm import bgp_example
from network_labs.appliances.network_model import Model
from network_labs.appliances.spec import validate
from network_labs.appliances.vendor_config import apply, render

RECORDED = json.loads((Path(__file__).parent / 'data' / 'frr_bgp_r1.json').read_text())  # real FRR 8.4, R1 of a 2-AS session
ADDRESSES = ('1: lo: <LOOPBACK,UP,LOWER_UP>\n    inet 127.0.0.1/8 scope host lo\n'
             '2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 192.0.2.1/24 scope global eth0\n'
             '3: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 203.0.113.1/30 scope global eth1\n')
ROUTES = ('192.0.2.0/24 dev eth0 scope link  src 192.0.2.1 \n198.51.100.0/24 via 203.0.113.2 dev eth1  metric 20 \n'
          '203.0.113.0/30 dev eth1 scope link  src 203.0.113.1 \n')  # BusyBox, beside the FRR session above
FIX = 'router bgp 65001\n neighbor 203.0.113.2 remote-as 65002\n network 192.0.2.0 mask 255.255.255.0'


def lab():
    return bgp_example('/k', '/d')


@unittest.skipUnless(shutil.which('gcc'), 'gcc required for the actual guest agent')
class AgentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary = Path(cls.temporary.name) / 'agent'
        subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', '-o', str(cls.binary), 'network_labs/appliances/guest/agent.c'], check=True)

    def invoke(self, line):
        out = subprocess.run([str(self.binary), '--stdio'], input=(line + '\n').encode(), capture_output=True, timeout=7).stdout
        header, body = out.split(b'\n', 1)
        return int(header.split()[1]), body.decode()

    def test_agent_writes_the_same_frr_configuration_as_the_lab(self):
        for node in lab()['nodes'][:3]:
            with self.subTest(node=node['name']):
                self.assertEqual(self.invoke('NL1 BGP_RENDER ' + bgp_fields(bgp.guest_process(node))), (0, bgp.config(node)))

    def test_malformed_processes_and_stdio_changes_are_refused(self):
        for fields in ('0 1.1.1.1 10.0.0.1:2 -', '1 1.1.1.1 10.0.0.1:1 -', '1 x 10.0.0.1:2 -', '1 1.1.1.1 10.0.0.1:2 10.0.0.0/33',
                       '1 1.1.1.1 - -', '1 1.1.1.1 10.0.0.1:2;id -', '1 1.1.1.1 10.0.0.1:2,10.0.0.2:2,10.0.0.3:2,10.0.0.4:2,10.0.0.5:2 -'):
            with self.subTest(fields=fields):
                self.assertEqual(self.invoke('NL1 BGP_RENDER ' + fields)[0], 2)
        for line in ('NL1 BGP_START 65001 1.1.1.1 203.0.113.2:65002 -', 'NL1 BGP_STOP', 'NL1 BGP_SHOW everything'):
            with self.subTest(line=line):
                self.assertEqual(self.invoke(line)[0], 2)
        self.assertEqual(self.invoke('NL1 BGP_SHOW config'), (1, 'bgp not running'))


class SchemaTest(unittest.TestCase):
    def test_validation_and_wire(self):
        self.assertEqual(bgp_fields(bgp.guest_process(lab()['nodes'][1])), '65002 2.2.2.2 203.0.113.1:65001,203.0.113.6:65003 -')
        for change, message in ((lambda n: n['bgp']['neighbors'][0].update(remote_as=65001), 'eBGP'),
                                (lambda n: n['bgp']['neighbors'][0].update(address='10.9.9.9'), 'directly connected'),
                                (lambda n: n.update(ospf={'router_id': '1.1.1.1', 'interfaces': {'eth0': {}}}), 'OSPF and BGP')):
            broken = copy.deepcopy(lab())
            change(broken['nodes'][0])
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate(broken)
        with self.assertRaises(ValueError):
            request('/nonexistent', 'bgp-show', state='everything')

    def test_frr_routes_are_recognised_and_never_saved(self):
        self.assertTrue(learned('198.51.100.0/24 via 203.0.113.2 dev eth1  metric 20'.split()))
        self.assertTrue(learned('198.51.100.0/24 nhid 6 via 203.0.113.2 dev eth1 proto bgp metric 20'.split()))


class VendorTest(unittest.TestCase):
    def test_each_dialect_renders_and_reads_back_its_bgp(self):
        spec = lab()
        for name in ('R1', 'R2', 'R3'):
            with self.subTest(node=name):
                self.assertEqual(apply(spec, name, render(spec, name)), spec)
        self.assertIn(' network 192.0.2.0 mask 255.255.255.0', render(spec, 'R1'))
        self.assertIn('set protocols bgp group EBGP neighbor 203.0.113.6 peer-as 65003', render(spec, 'R2'))
        self.assertIn(' peer 203.0.113.5 as-number 65002', render(spec, 'R3'))

    def test_student_entry_classful_junos_policy_and_vrp(self):
        start = missions.BY_ID['bgp-trois-operateurs']['build']('/k', '/d')
        self.assertEqual(apply(start, 'R1', FIX)['nodes'][0]['bgp']['networks'], ['192.0.2.0/24'])
        self.assertEqual(apply(start, 'R1', 'router bgp 65001\n neighbor 203.0.113.2 remote-as 65002\n network 192.0.2.0')
                         ['nodes'][0]['bgp']['networks'], ['192.0.2.0/24'])  # classful, like IOS
        junos = apply(start, 'R2', 'set policy-options policy-statement OUT term a from route-filter 203.0.113.4/30 exact\n'
                                   'set policy-options policy-statement OUT term a then accept\n'
                                   'set protocols bgp group EBGP export OUT')['nodes'][1]['bgp']
        self.assertEqual(junos['networks'], ['203.0.113.4/30'])
        self.assertEqual({n['address'] for n in junos['neighbors']}, {'203.0.113.1', '203.0.113.6'})
        gone = apply(start, 'R3', 'undo bgp 65003')['nodes'][2]
        self.assertIsNone(gone['bgp'])
        with self.assertRaisesRegex(ValueError, 'declared twice'):  # one neighbour in two groups: refused, as Junos does
            apply(start, 'R2', 'set protocols bgp group CLIENTS neighbor 203.0.113.1 peer-as 65001')


class ShowAndModelTest(unittest.TestCase):
    def observation(self, node):
        replies = {'addresses': ADDRESSES, 'routes': ROUTES, ('bgp-show', 'summary'): json.dumps(RECORDED['summary']),
                   ('bgp-show', 'routes'): json.dumps(RECORDED['routes'])}

        def query(operation, **fields):
            return replies[(operation, fields['state'])] if fields else replies[operation]
        return vendor_show.observe_guest(query, node)

    def test_shows_from_real_frr_output(self):
        spec = lab()
        seen = self.observation(spec['nodes'][0])
        self.assertEqual(seen['bgp']['peers'][0]['state'], 'Established')
        self.assertIn('203.0.113.2     4        65002', vendor_show.show(spec['nodes'][0], seen, 'show ip bgp summary'))
        self.assertIn(' *>  198.51.100.0/24     203.0.113.2         65002 i', vendor_show.show(spec['nodes'][0], seen, 'sh ip bgp'))
        self.assertIn('B        198.51.100.0/24 [20/0] via 203.0.113.2, GigabitEthernet0/0/1',
                      vendor_show.show(spec['nodes'][0], seen, 'show ip route'))
        self.assertIn('*[BGP/170] AS path: 65002 I', vendor_show.show(spec['nodes'][1], seen, 'show route'))
        self.assertIn('Establ', vendor_show.show(spec['nodes'][1], seen, 'show bgp summary'))
        self.assertIn('Established', vendor_show.show(spec['nodes'][2], seen, 'display bgp peer'))

    def test_model_sessions_announcements_and_mistakes(self):
        self.assertTrue(Model(lab()).ping('VM2', '198.51.100.20')[0])
        start = missions.BY_ID['bgp-trois-operateurs']['build']('/k', '/d')
        self.assertFalse(Model(start).ping('VM2', '198.51.100.20')[0])
        self.assertTrue(Model(apply(start, 'R1', FIX)).ping('VM2', '198.51.100.20')[0])
        wrong_mask = apply(start, 'R1', FIX.replace('255.255.255.0', '255.255.0.0'))
        self.assertIn('R3 n’a aucune route vers 192.0.2.20', Model(wrong_mask).ping('VM2', '198.51.100.20')[1])
        wrong_as = apply(start, 'R1', FIX.replace('remote-as 65002', 'remote-as 65009'))
        self.assertIn('R1 n’a aucune route vers 198.51.100.20', Model(wrong_as).ping('VM2', '198.51.100.20')[1])


@unittest.skipUnless(all(Path(p).is_file() for p in ('/usr/lib/frr/zebra', '/usr/lib/frr/bgpd', '/usr/bin/vtysh'))
                     and shutil.which('busybox') and shutil.which('mke2fs'), 'FRR and image tools required')
class ImageTest(unittest.TestCase):
    def test_routing_image_carries_frr_and_its_accounts(self):
        from network_labs.appliances.guest_image import build
        with tempfile.TemporaryDirectory() as folder:
            disk = Path(folder) / 'g.ext4'
            build(shutil.which('busybox'), disk, size_mib=128, with_agent=True, with_routing=True)
            listing = subprocess.run(['debugfs', '-R', 'ls /usr/lib/frr', str(disk)], capture_output=True, text=True).stdout
            group = subprocess.run(['debugfs', '-R', 'cat /etc/group', str(disk)], capture_output=True, text=True).stdout
            vtysh = subprocess.run(['debugfs', '-R', 'cat /etc/frr/vtysh.conf', str(disk)], capture_output=True, text=True).stdout
        self.assertEqual(vtysh, 'username root nopassword\n')  # vtysh would otherwise need PAM, absent from the guest
        self.assertIn('bgpd', listing)
        self.assertIn('frrvty:x:85:root', group)


if __name__ == '__main__':
    unittest.main()
