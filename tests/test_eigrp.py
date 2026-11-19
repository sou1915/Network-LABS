"""EIGRP typed as on IOS (router eigrp, network with or without wildcard, eigrp router-id): the process given to FRR's
eigrpd, the routes the model computes (D, IOS metrics on GigabitEthernet), show ip eigrp neighbors, FRR's outputs read."""
import unittest

from network_labs.appliances import eigrp, guest_console
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.guest_control import request
from network_labs.appliances.network_model import Model
from network_labs.appliances.spec import validate

from tests.test_rip import chain

TYPED = {'R1': ['en', 'conf t', 'router eigrp 10', 'network 192.168.1.0 0.0.0.255', 'network 10.0.12.0 0.0.0.3', 'no auto-summary', 'end'],
         'R2': ['en', 'conf t', 'router eigrp 10', 'network 10.0.0.0', 'end'],
         'R3': ['en', 'conf t', 'router eigrp 10', 'network 10.0.23.0 0.0.0.3', 'network 192.168.3.0', 'end']}
# Captured from FRR 8.4's eigrpd (three routers in network namespaces).
TOPOLOGY = """
EIGRP Topology Table for AS(10)/ID(1.1.1.1)

Codes: P - Passive, A - Active, U - Update, Q - Query, R - Reply
       r - reply Status, s - sia Status

P  10.0.12.0/30, 1 successors, FD is 28160, serno: 0 
       via Connected, eth1
P  192.168.3.0/24, 1 successors, FD is 33280, serno: 0 
       via 10.0.12.2 (33280/30720), eth1
"""
NEIGHBORS = """
EIGRP neighbors for AS(10)

H   Address           Interface            Hold   Uptime   SRTT   RTO   Q     Seq  
                                           (sec)           (ms)        Cnt    Num   
0   10.0.12.2         eth1                 11     0        0      2    0      3
"""


class EigrpTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': chain()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def type(self, name, lines):
        console = guest_console.Console('rip-lab', name, lambda _: self.lab)
        return [console.line(line) for line in lines]

    def node(self, name):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == name)

    def test_the_process_frr_runs(self):
        for name, lines in TYPED.items():
            self.type(name, lines)
        r1, r2 = eigrp.process(self.node('R1')), eigrp.process(self.node('R2'))
        self.assertEqual((r1['asn'], r1['router_id'], r1['networks']), (10, '192.168.1.1', ['10.0.12.0/30', '192.168.1.0/24']))
        self.assertEqual(r2['networks'], ['10.0.0.0/8'])  # classful, as IOS reads « network 10.0.0.0 »
        self.assertEqual(eigrp.fields(r1), '10 192.168.1.1 10.0.12.0/30,192.168.1.0/24 -')
        self.assertEqual(eigrp.config(r1), 'frr defaults traditional\nrouter eigrp 10\n eigrp router-id 192.168.1.1\n'
                                           ' network 10.0.12.0/30\n network 192.168.1.0/24\n')

    def test_routes_metrics_neighbours_and_reachability(self):
        self.assertIn('0 packets received', self.type('PC1', ['ping 192.168.3.10'])[0])
        for name, lines in TYPED.items():
            self.type(name, lines)
        table = self.type('R1', ['en', 'sh ip route'])[-1]
        self.assertIn('D        10.0.23.0/30 [90/3072] via 10.0.12.2, GigabitEthernet0/0/1', table)
        self.assertIn('D        192.168.3.0/24 [90/3328] via 10.0.12.2, GigabitEthernet0/0/1', table)
        self.assertRegex(self.type('R1', ['en', 'sh ip eigrp neighbors'])[-1], r'\n0   10\.0\.12\.2\s+Gi0/0/1\s+13 ')
        self.assertIn('Routing Protocol is "eigrp 10"', self.type('R1', ['en', 'sh ip protocols'])[-1])
        self.assertNotIn('C ', self.type('R1', ['en', 'sh ip ro eigrp'])[-1].split('\n\n', 2)[-1])
        ok, why = Model(self.box['spec']).ping('PC1', '192.168.3.10')
        self.assertTrue(ok, why)

    def test_frr_outputs_and_ios_metrics(self):
        self.assertEqual(eigrp.parse_topology(TOPOLOGY), {'10.0.12.0/30': 28160, '192.168.3.0/24': 33280})
        self.assertEqual(eigrp.parse_neighbors(NEIGHBORS)[0]['address'], '10.0.12.2')
        self.assertEqual((eigrp.ios_metric(33280), eigrp.ios_metric(28160, gigabit=False)), (3328, 28160))

    def test_one_dynamic_protocol_per_router_and_the_guest_request(self):
        self.type('R1', ['en', 'conf t', 'router rip', 'network 10.0.0.0', 'end'])
        reply = self.type('R1', ['en', 'conf t', 'router eigrp 10', 'network 10.0.0.0', 'end'])
        self.assertIn('un protocole dynamique', ' '.join(reply))
        with self.assertRaisesRegex(ValueError, 'config, neighbors or topology'):
            request('/nonexistent', 'eigrp-show', state='routes')


if __name__ == '__main__':
    unittest.main()
