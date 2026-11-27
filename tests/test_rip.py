"""RIP from the IOS lines of a router: the process the guest runs, the model's routes, show ip route, BIRD's own check."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from network_labs.appliances import guest_console, rip, topology_edit
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.guest_control import rip_fields
from network_labs.appliances.network_model import Model
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project


def chain():
    """PC1 — R1 — R2 — R3 — PC3, no static route anywhere."""
    spec = blank_project('rip-lab')
    for name, addresses in (('R1', '192.168.1.1/24,10.0.12.1/30'), ('R2', '10.0.12.2/30,10.0.23.1/30'),
                            ('R3', '10.0.23.2/30,192.168.3.1/24')):
        spec = topology_edit.add_microvm_node(spec, name=name, role='router', kernel='/k', disk='/d', ports=2, model='cisco-isr4331',
                                              addresses=addresses)
    for name, address, gateway in (('PC1', '192.168.1.10/24', '192.168.1.1'), ('PC3', '192.168.3.10/24', '192.168.3.1')):
        spec = topology_edit.add_microvm_node(spec, name=name, role='host', kernel='/k', disk='/d', ports=1, addresses=address)
        spec['nodes'][-1]['gateway'] = gateway
    for a, b in ((('PC1', 'eth0'), ('R1', 'eth0')), (('R1', 'eth1'), ('R2', 'eth0')), (('R2', 'eth1'), ('R3', 'eth0')),
                 (('R3', 'eth1'), ('PC3', 'eth0'))):
        spec = topology_edit.connect(spec, a, b)
    return validate(spec)


TYPED = {'R1': ['en', 'conf t', 'router rip', 'version 2', 'network 192.168.1.0', 'network 10.0.0.0', 'no auto-summary',
                'passive-interface g0/0/0', 'end'],
         'R2': ['en', 'conf t', 'router rip', 'version 2', 'network 10.0.0.0', 'no auto-summary', 'end'],
         'R3': ['en', 'conf t', 'router rip', 'version 2', 'network 10.0.0.0', 'network 192.168.3.0', 'no auto-summary', 'end']}


class RipTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': chain()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def configure(self, *names):
        for name in names:
            console = guest_console.Console('rip-lab', name, lambda _: self.lab)
            for line in TYPED[name]:
                self.assertFalse(console.line(line).startswith('% '), line)

    def node(self, name):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == name)

    def test_typed_rip_gives_the_process_the_model_routes_and_show_ip_route(self):
        self.assertFalse(Model(self.box['spec']).ping('PC1', '192.168.3.10')[0])
        self.configure('R1', 'R2')
        self.assertFalse(Model(self.box['spec']).ping('PC1', '192.168.3.10')[0])  # R3 does not run RIP yet
        self.configure('R3')
        self.assertEqual(rip.process(self.node('R1')), {'router_id': '192.168.1.1', 'version': 2, 'interfaces': [
            {'port': 'eth0', 'passive': True}, {'port': 'eth1', 'passive': False}]})
        ok, why = Model(self.box['spec']).ping('PC1', '192.168.3.10')
        self.assertTrue(ok, why)
        table = guest_console.Console('rip-lab', 'R1', lambda _: self.lab).line('show ip route')
        self.assertIn('R        192.168.3.0/24 [120/2] via 10.0.12.2, GigabitEthernet0/0/1', table)
        self.assertIn('R        10.0.23.0/30 [120/1] via 10.0.12.2, GigabitEthernet0/0/1', table)
        self.assertIn('Passive Interface(s):\n    GigabitEthernet0/0/0',
                      guest_console.Console('rip-lab', 'R1', lambda _: self.lab).line('show ip protocols'))

    def test_a_passive_link_carries_no_updates_and_rip_refuses_ospf_beside_it(self):
        self.configure('R1', 'R2', 'R3')
        console = guest_console.Console('rip-lab', 'R2', lambda _: self.lab)
        for line in ('en', 'conf t', 'router rip', 'passive-interface g0/0/1', 'end'):
            console.line(line)
        self.assertFalse(Model(self.box['spec']).ping('PC1', '192.168.3.10')[0])  # R2 no longer tells R3 about R1's LAN
        r1 = guest_console.Console('rip-lab', 'R1', lambda _: self.lab)
        replies = [r1.line(line) for line in ('en', 'conf t', 'router ospf 1', 'network 10.0.12.0 0.0.0.3 area 0', 'end')]
        self.assertIn('RIP et OSPF', replies[-1])  # said at end, as the block never became valid
        self.assertIsNone(self.node('R1').get('ospf'))


class RipMetricTest(unittest.TestCase):
    def test_bird_metrics_become_ios_hop_counts(self):
        from network_labs.appliances.vendor_show import parse_rip_metrics
        text = ('Table master4:\n10.0.23.0/30         unicast [rip4 22:41:02.113] * (120/2)\n'
                '\tvia 10.0.12.2 on eth1\n192.168.3.0/24       unicast [rip4 22:41:07.204] * (120/3)\n\tvia 10.0.12.2 on eth1\n')
        self.assertEqual(parse_rip_metrics(text), {'10.0.23.0/30': 1, '192.168.3.0/24': 2})  # as the model and IOS count

@unittest.skipUnless(shutil.which('gcc') and shutil.which('bird'), 'gcc and BIRD required')
class RipAgentTest(unittest.TestCase):
    def test_the_agent_renders_a_rip_configuration_bird_accepts_and_refuses_bad_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'agent'
            subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', '-o', str(binary), 'network_labs/appliances/guest/agent.c'], check=True)

            def invoke(line):
                out = subprocess.run([str(binary), '--stdio'], input=(line + '\n').encode(), capture_output=True, timeout=7).stdout
                header, _, body = out.partition(b'\n')
                return int(header.split()[1]), body.decode()
            fields = rip_fields({'router_id': '192.168.1.1', 'version': 2,
                                 'interfaces': [{'port': 'eth0', 'passive': True}, {'port': 'eth1', 'passive': False}]})
            code, config = invoke('NL1 RIP_RENDER ' + fields)
            self.assertEqual(code, 0)
            self.assertIn('interface "eth0" { version 2; mode multicast; update time 5; timeout time 30; garbage time 20; passive yes; };',
                          config)
            path = Path(folder) / 'bird.conf'
            path.write_text(config)
            checked = subprocess.run(['bird', '-p', '-c', str(path)], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            for bad in ('192.168.1.1 3 eth0:a', '192.168.1.1 2 eth16:a', '192.168.1.1 2 eth0:a,eth0:p', '1.1.1 2 eth0:a',
                        '192.168.1.1 2 eth0:x', '192.168.1.1 2 eth0:a extra'):
                with self.subTest(fields=bad):
                    self.assertEqual(invoke('NL1 RIP_RENDER ' + bad)[0], 2)


if __name__ == '__main__':
    unittest.main()
