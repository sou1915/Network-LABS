"""OSPF on micro-VM routers: the guest agent's BIRD configuration, the typed wire, vendor CLIs, show commands and readback."""
import copy
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from network_labs.appliances import ospf, vendor_show
from network_labs.appliances.guest_control import ospf_fields, request
from network_labs.appliances.guest_startup import learned
from network_labs.appliances.microvm import ospf_example
from network_labs.appliances.spec import validate
from network_labs.appliances.vendor_config import apply, render

ADDRESSES = ('1: lo: <LOOPBACK,UP,LOWER_UP>\n    inet 127.0.0.1/8 scope host lo\n'
             '2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 192.0.2.1/24 scope global eth0\n'
             '3: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 203.0.113.1/30 scope global eth1\n')
# As the guest's BusyBox prints them (recorded beside a real BIRD 2): no protocol, BIRD's metric 32.
ROUTES = ('192.0.2.0/24 dev eth0 scope link  src 192.0.2.1 \n192.0.2.0/24 dev eth0 scope link  metric 32 \n'
          '198.51.100.0/24 via 203.0.113.2 dev eth1  metric 32 \n203.0.113.0/30 dev eth1 scope link  src 203.0.113.1 \n'
          '203.0.113.0/30 dev eth1 scope link  metric 32 \n')
NEIGHBORS = ('BIRD 2.14 ready.\nAccess restricted\nospf4:\nRouter ID   \tPri\t     State     \tDTime\tInterface  Router IP\n'
             '2.2.2.2     \t  1\tFull/PtP  \t 3.996\teth1       203.0.113.2\n')
BIRD_ROUTES = ('BIRD 2.14 ready.\nAccess restricted\nTable master4:\n'
               '198.51.100.0/24      unicast [ospf4 10:02:12.730] * I (150/20) [2.2.2.2]\n\tvia 203.0.113.2 on eth1\n'
               '192.0.2.0/24         unicast [ospf4 10:02:05.730] * I (150/10) [1.1.1.1]\n\tdev eth0\n')
SOLUTION = 'router ospf 1\n network 192.0.2.0 0.0.0.255 area 0\n network 203.0.113.0 0.0.0.3 area 0\n passive-interface gi0/0/0'


def lab():
    return ospf_example('/k', '/d')


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

    def test_agent_writes_the_same_bird_configuration_as_the_lab(self):
        for node in lab()['nodes'][:3]:
            with self.subTest(node=node['name']):
                self.assertEqual(self.invoke('NL1 OSPF_RENDER ' + ospf_fields(ospf.guest_process(node))), (0, ospf.config(node)))
        broadcast = copy.deepcopy(lab())
        broadcast['nodes'][1]['ospf']['interfaces']['eth0'].update(network_type='broadcast', priority=5)
        node = validate(broadcast)['nodes'][1]
        self.assertIn('priority 5; wait 4;', ospf.config(node))
        self.assertEqual(self.invoke('NL1 OSPF_RENDER ' + ospf_fields(ospf.guest_process(node)))[1], ospf.config(node))

    @unittest.skipUnless(shutil.which('bird'), 'BIRD 2 parses the configuration')
    def test_bird_accepts_the_rendered_configuration(self):
        code, text = self.invoke('NL1 OSPF_RENDER 1.1.1.1 1 4 eth0:10:y:p:1,eth1:20:n:b:5')
        self.assertEqual(code, 0)
        path = Path(self.temporary.name) / 'bird.conf'
        path.write_text(text)
        self.assertEqual(subprocess.run(['bird', '-p', '-c', str(path)], capture_output=True).returncode, 0)

    def test_malformed_processes_and_stdio_changes_are_refused(self):
        for fields in ('1.1.1.1 4 4 eth0:10:n:p:1', '1.1.1.1 1 4 eth16:10:n:p:1', '1.1.1.1 1 4 eth0:10:y:p:1', '1.1.1.1 1 4 eth0:0:n:p:1',
                       '1.1.1.1 1 4 eth0:10:n:p:2', '1.1.1.1 1 4 eth0:10:n:p:1,eth0:10:n:p:1', '1.1.1.1 1 4 eth0:10:n:p:1;id',
                       'x 1 4 eth0:10:n:p:1', '1.1.1.1 1 4 eth0:10:n:p:1,eth1:1:n:p:1,eth2:1:n:p:1,eth3:1:n:p:1,eth0:1:n:p:1'):
            with self.subTest(fields=fields):
                self.assertEqual(self.invoke('NL1 OSPF_RENDER ' + fields)[0], 2)
        for line in ('NL1 OSPF_START 1.1.1.1 1 4 eth0:10:n:p:1', 'NL1 OSPF_STOP', 'NL1 OSPF_SHOW everything'):
            with self.subTest(line=line):
                self.assertEqual(self.invoke(line)[0], 2)
        self.assertEqual(self.invoke('NL1 OSPF_SHOW config'), (1, 'ospf not running'))


class WireTest(unittest.TestCase):
    def test_typed_fields_and_refusals(self):
        node = lab()['nodes'][0]
        self.assertEqual(ospf_fields(ospf.guest_process(node)), '1.1.1.1 1 4 eth0:10:y:p:1,eth1:10:n:p:1')
        process = ospf.guest_process(node)
        for change in ({'hello': 4}, {'router_id': 'x'}, {'interfaces': []}, {'extra': 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ospf_fields(dict(process, **change))
        with self.assertRaises(ValueError):
            request('/nonexistent', 'ospf-show', state='everything')
        with self.assertRaises(ValueError):
            request('/nonexistent', 'ospf-start', ospf=process, interface='eth0')


class SpecTest(unittest.TestCase):
    def test_preflight_of_an_ospf_micro_vm_lab_needs_no_container_rootfs(self):
        from unittest.mock import patch
        from network_labs.appliances import runtime
        with tempfile.TemporaryDirectory() as folder:
            kernel, disk = Path(folder) / 'vmlinux', Path(folder) / 'disk.ext4'
            kernel.write_bytes(b'k')
            disk.write_bytes(b'd')
            spec = ospf_example(kernel, disk)
            report = {'host': {'linux': True}, 'runtimes': [{'id': 'firecracker', 'prerequisites_detected': True},
                                                            {'id': 'oci', 'prerequisites_detected': True}]}
            with patch.object(runtime, 'capabilities', return_value=report):
                runtime.Manager(spec['name']).preflight(spec)  # no KeyError on 'rootfs'

    def test_micro_vm_routers_run_ospf_without_static_routes(self):
        spec = lab()
        self.assertEqual([n['ospf']['router_id'] for n in spec['nodes'][:3]], ['1.1.1.1', '2.2.2.2', '3.3.3.3'])
        for change, message in ((lambda n: n.update(guest_network={'addresses': [], 'routes': [{'network': '10.0.0.0/8',
                                                                                                 'gateway': '203.0.113.2'}]}),
                                 'no static'),
                                (lambda n: n['ospf']['interfaces']['eth1'].update(hello=2), 'whole process')):
            broken = copy.deepcopy(spec)
            change(broken['nodes'][0])
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate(broken)
        host = copy.deepcopy(spec)
        host['nodes'][3]['ospf'] = {'router_id': '9.9.9.9', 'interfaces': {'eth0': {}}}
        with self.assertRaisesRegex(ValueError, 'role router'):
            validate(host)

    def test_guest_readback_skips_birds_routes_in_busybox_output(self):
        from unittest.mock import patch
        from network_labs.appliances import guest_startup
        node = lab()['nodes'][0]
        replies = {'addresses': ADDRESSES, 'routes': ROUTES, 'forwarding': '1\n', 'ospf-show': ospf.config(node),
                   'proxy-arps': ''.join(f'{port} 1\n' for port, address in node['interfaces'].items() if address)}
        with patch.object(guest_startup, 'query', lambda socket, operation, **fields: replies[operation]):
            self.assertEqual(guest_startup.observe('/unused', node), {'addresses': [], 'routes': []})
        replies['ospf-show'] = ospf.config(node).replace('cost 10', 'cost 11', 1)
        with patch.object(guest_startup, 'query', lambda socket, operation, **fields: replies[operation]):
            with self.assertRaisesRegex(ValueError, 'differs'):
                guest_startup.observe('/unused', node)

    def test_bird_routes_are_recognised_and_never_saved(self):
        self.assertTrue(learned('198.51.100.0/24 via 203.0.113.2 dev eth1 proto bird metric 32'.split()))
        self.assertTrue(learned('198.51.100.0/24 via 203.0.113.2 dev eth1 proto 12 metric 32'.split()))
        self.assertFalse(learned('198.51.100.0/24 via 203.0.113.2 dev eth1'.split()))
        # BusyBox (the guest's ip) never prints the protocol: BIRD's routes carry its kernel metric instead.
        self.assertTrue(learned('198.51.100.0/24 via 203.0.113.2 dev eth1  metric 32'.split()))
        self.assertTrue(learned('192.0.2.0/24 dev eth0 scope link  metric 32'.split()))
        self.assertFalse(learned('192.0.2.0/24 dev eth0 scope link  src 192.0.2.1'.split()))


class VendorTest(unittest.TestCase):
    def test_every_dialect_renders_and_reads_back_its_ospf(self):
        spec = lab()
        for name in ('R1', 'R2', 'R3'):
            with self.subTest(node=name):
                self.assertEqual(apply(spec, name, render(spec, name)), spec)
        self.assertIn(' network 203.0.113.0 0.0.0.3 area 0', render(spec, 'R1'))
        self.assertIn('set protocols ospf area 0.0.0.0 interface xe-0/0/0.0 interface-type p2p', render(spec, 'R2'))
        self.assertIn(' silent-interface GE0/0/1', render(spec, 'R3'))

    def test_student_entry_in_ios_junos_vrp_and_eos(self):
        bare = copy.deepcopy(lab())
        for node in bare['nodes'][:3]:
            node['ospf'] = None
        bare = validate(bare)
        r1 = apply(bare, 'R1', SOLUTION)['nodes'][0]['ospf']
        self.assertEqual((r1['router_id'], r1['interfaces']['eth0']['passive'], r1['networks']),
                         ('203.0.113.1', True, ['192.0.2.0/24', '203.0.113.0/30']))
        r2 = apply(bare, 'R2', 'set protocols ospf area 0.0.0.0 interface xe-0/0/0.0\n'
                               'set protocols ospf area 0 interface xe-0/0/1 metric 50\n'
                               'set routing-options router-id 2.2.2.2')['nodes'][1]['ospf']
        self.assertEqual((r2['router_id'], r2['interfaces']['eth1']['cost']), ('2.2.2.2', 50))
        r3 = apply(bare, 'R3', 'ospf 1 router-id 3.3.3.3\n area 0.0.0.0\n  network 203.0.113.4 0.0.0.3\ninterface GE0/0/0\n'
                               ' ospf cost 30')['nodes'][2]['ospf']
        self.assertEqual((r3['networks'], r3['interfaces']['eth0']['cost']), (['203.0.113.4/30'], 30))
        arista = copy.deepcopy(bare)
        arista['nodes'][0]['model'] = 'arista-7280r'
        arista = validate(arista)
        self.assertEqual(apply(arista, 'R1', 'router ospf 1\n network 203.0.113.0/30 area 0.0.0.0')['nodes'][0]['ospf']['networks'],
                         ['203.0.113.0/30'])
        for text, message in (('router ospf 1\n network 192.0.2.0 0.0.0.255 area 1', 'zone 0'),
                              ('router ospf 1\n network 10.0.0.0 0.0.0.255 area 0', 'aucun port'),
                              ('interface gi0/0/1\n ip ospf cost 5', 'sans processus')):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                apply(bare, 'R1', text)
        configured = apply(bare, 'R1', SOLUTION)
        self.assertIsNone(apply(configured, 'R1', 'no router ospf 1')['nodes'][0]['ospf'])


class ShowTest(unittest.TestCase):
    def observation(self, node):
        replies = {'addresses': ADDRESSES, 'routes': ROUTES, ('ospf-show', 'neighbors'): NEIGHBORS, ('ospf-show', 'routes'): BIRD_ROUTES}
        def query(operation, **fields):
            return replies[(operation, fields['state'])] if fields else replies[operation]
        return vendor_show.observe_guest(query, node)

    def test_learned_routes_neighbors_and_vendor_layouts(self):
        spec = lab()
        seen = self.observation(spec['nodes'][0])
        self.assertEqual([r for r in seen['routes'] if r.get('protocol')],
                         [{'network': '198.51.100.0/24', 'gateway': '203.0.113.2', 'port': 'eth1', 'protocol': 'ospf', 'metric': 20}])
        self.assertEqual(seen['ospf']['neighbors'][0]['state'], 'Full')
        self.assertIn('O        198.51.100.0/24 [110/20] via 203.0.113.2, GigabitEthernet0/0/1',
                      vendor_show.show(spec['nodes'][0], seen, 'show ip route'))
        self.assertIn('2.2.2.2           1   FULL/   -', vendor_show.show(spec['nodes'][0], seen, 'sh ip ospf nei'))
        self.assertIn('*[OSPF/10] metric 20', vendor_show.show(spec['nodes'][1], seen, 'show route'))
        self.assertIn('Full      2.2.2.2', vendor_show.show(spec['nodes'][1], seen, 'show ospf neighbor'))
        self.assertIn('198.51.100.0/24     OSPF    10   20', vendor_show.show(spec['nodes'][2], seen, 'display ip routing-table'))
        self.assertIn('2.2.2.2          Full', vendor_show.show(spec['nodes'][2], seen, 'display ospf peer brief'))
        from network_labs.appliances.device_view import live, summary
        page = live(spec, spec['nodes'][0], seen)
        self.assertTrue(page['conform'], page)  # an OSPF route is the protocol's result, not an écart
        self.assertEqual([r['state'] for r in page['routes']], ['ospf'])
        self.assertEqual((page['ospf']['complete'], page['ospf']['interfaces'][1]['neighbors']), (True, 1))
        self.assertTrue(summary(spec, spec['nodes'][0])['ospf'])
        bare = copy.deepcopy(spec)
        bare['nodes'][0]['ospf'] = None
        node = validate(bare)['nodes'][0]
        plain = vendor_show.observe_guest(lambda operation, **fields: {'addresses': ADDRESSES, 'routes': ''}[operation], node)
        with self.assertRaisesRegex(ValueError, 'OSPF n’est pas configuré'):
            vendor_show.show(node, plain, 'show ip ospf neighbor')



@unittest.skipUnless(importlib.util.find_spec('tkinter'), 'tkinter required for the workbench layout')
class LayoutTest(unittest.TestCase):
    def test_three_routers_in_a_row_are_staggered(self):
        from network_labs.appliances.ui_bridge import public_topology
        from network_labs.appliances.workspace_art import place_nodes
        positions = place_nodes(public_topology(lab()), {}, 780)
        self.assertEqual([positions[name][1] for name in ('R1', 'R2', 'R3')], [100, 210, 100])
        self.assertGreater(positions['R3'][0] - positions['R1'][0], 300)


class PanneTest(unittest.TestCase):
    def test_each_ospf_fault_is_repaired_from_its_vendor_cli(self):
        from network_labs.appliances import faults
        repairs = {'r1-off': ('R1', SOLUTION),
                   'r2-passive': ('R2', 'delete protocols ospf area 0.0.0.0 interface xe-0/0/1.0 passive'),
                   'r3-lan': ('R3', 'ospf 1\n area 0.0.0.0\n  network 198.51.100.0 0.0.0.255\n silent-interface GE0/0/1')}
        self.assertEqual(set(repairs), set(faults.FAULTS['ospf']))
        for fault, (node, text) in repairs.items():
            with self.subTest(fault=fault):
                original = faults.LABS['ospf']['build']('/k', '/d')
                broken = copy.deepcopy(original)
                faults.FAULTS['ospf'][fault][0][0](broken)
                panne = {'lab': 'ospf', 'fault': fault, 'original': original}
                repaired = apply(validate(broken), node, text)
                self.assertEqual(faults.grade(repaired, panne)['results'][0]['status'], 'ok', faults.grade(repaired, panne))


if __name__ == '__main__':
    unittest.main()
