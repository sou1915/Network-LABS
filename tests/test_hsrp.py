"""HSRP on router micro-VMs, typed as on IOS: R1 and R2 share the LAN 192.168.1.0/24 (group 1, virtual address .1) and
the server LAN 10.0.0.0/24 (group 2, version 2, virtual address .1); R1 is preferred on the LAN, R2 on the server side.
The lines make the agent's --hsrp arguments; a stopped lab elects as the routers would, so the PC reaches the server
through the virtual addresses, and the backup takes over when the active router's port is shut."""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console, hsrp, topology_edit
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project

R1 = ['en', 'conf t', 'int g0/0/0', 'ip address 192.168.1.2 255.255.255.0', 'no shut', 'standby 1 ip 192.168.1.1',
      'standby 1 priority 110', 'standby 1 preempt', 'int g0/0/1', 'ip address 10.0.0.2 255.255.255.0', 'no shut',
      'standby version 2', 'standby 2 ip 10.0.0.1', 'end']
R2 = ['en', 'conf t', 'int g0/0/0', 'ip address 192.168.1.3 255.255.255.0', 'no shut', 'standby 1 ip 192.168.1.1',
      'int g0/0/1', 'ip address 10.0.0.3 255.255.255.0', 'no shut', 'standby version 2', 'standby 2 ip 10.0.0.1',
      'standby 2 priority 110', 'standby 2 preempt', 'end']


def lab(kernel='/k', disk='/d'):
    spec = blank_project('hsrp')
    for name in ('SW1', 'SW2'):
        spec = topology_edit.add_microvm_node(spec, name=name, role='switch', kernel=kernel, disk=disk, ports=4, model='cisco-2960')
    for name in ('R1', 'R2'):
        spec = topology_edit.add_microvm_node(spec, name=name, role='router', kernel=kernel, disk=disk, ports=2, model='cisco-isr4331')
    spec = topology_edit.add_microvm_node(spec, name='PC1', role='host', kernel=kernel, disk=disk, ports=1, addresses='192.168.1.10/24')
    spec = topology_edit.add_microvm_node(spec, name='SRV', role='host', kernel=kernel, disk=disk, ports=1, addresses='10.0.0.10/24')
    for name, gateway in (('PC1', '192.168.1.1'), ('SRV', '10.0.0.1')):
        next(n for n in spec['nodes'] if n['name'] == name)['gateway'] = gateway
    for a, b in ((('R1', 'eth0'), ('SW1', 'eth0')), (('R2', 'eth0'), ('SW1', 'eth1')), (('PC1', 'eth0'), ('SW1', 'eth2')),
                 (('R1', 'eth1'), ('SW2', 'eth0')), (('R2', 'eth1'), ('SW2', 'eth1')), (('SRV', 'eth0'), ('SW2', 'eth2'))):
        spec = topology_edit.connect(spec, a, b)
    return validate(spec)


def configured(kernel='/k', disk='/d'):
    box = {'spec': lab(kernel, disk)}
    draft = DraftLab(lambda: box['spec'], lambda spec: box.update(spec=validate(spec)))
    for name, lines in (('R1', R1), ('R2', R2)):
        console = guest_console.Console('hsrp', name, lambda _: draft)
        for line in lines:
            reply = console.line(line)
            assert '%' not in reply or 'CONFIG_I' in reply or 'LINK' in reply or 'LINEPROTO' in reply, (line, reply)
    return box


class HsrpTest(unittest.TestCase):
    def setUp(self):
        self.box = configured()
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def type(self, name, lines):
        console = guest_console.Console('hsrp', name, lambda _: self.lab)
        return [console.line(line) for line in lines]

    def node(self, name):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == name)

    def test_typed_lines_make_the_groups_and_the_agent_arguments(self):
        r1 = self.node('R1')
        self.assertEqual(r1['cli_config']['interfaces']['eth1'], ['standby version 2', 'standby 2 ip 10.0.0.1'])
        self.assertEqual(hsrp.arguments(r1), ['eth0/1/1/192.168.1.1/110/y/3/10/636973636f', 'eth1/2/2/10.0.0.1/100/n/3/10/636973636f'])
        self.assertEqual(hsrp.virtual_mac(1, 1), '0000.0c07.ac01')
        self.assertEqual(hsrp.virtual_mac(2, 2), '0000.0c9f.f002')
        self.assertIn(' standby 1 priority 110\n standby 1 preempt', self.type('R1', ['en', 'show running-config'])[-1])

    def test_a_stopped_lab_elects_and_the_pc_reaches_the_server_through_the_virtual_addresses(self):
        brief = self.type('R1', ['en', 'show standby brief'])[-1]
        self.assertRegex(brief, r'Gi0/0/0 +1 +110 P Active +local +192\.168\.1\.3 +192\.168\.1\.1')
        self.assertRegex(brief, r'Gi0/0/1 +2 +100   Standby 10\.0\.0\.3 +local +10\.0\.0\.1')
        self.assertIn('4 packets received', self.type('PC1', ['ping 10.0.0.10'])[0])
        self.assertIn('4 packets received', self.type('PC1', ['ping 192.168.1.1'])[0])  # the virtual address answers
        detail = self.type('R2', ['en', 'show standby'])[-1]
        self.assertIn('GigabitEthernet0/0/0 - Group 1\n  State is Standby', detail)
        self.assertIn('Active router is 192.168.1.2, priority 110', detail)
        self.assertIn('GigabitEthernet0/0/1 - Group 2 (version 2)\n  State is Active', detail)
        self.assertIn('Active virtual MAC address is 0000.0c9f.f002 (MAC In Use)', detail)

    def test_the_backup_takes_over_when_the_active_port_is_shut(self):
        self.type('R1', ['en', 'conf t', 'int g0/0/0', 'shutdown', 'end'])
        self.assertRegex(self.type('R2', ['en', 'show standby brief'])[-1], r'Gi0/0/0 +1 +100   Active +local +unknown +192\.168\.1\.1')
        self.assertIn('State is Init (interface down)', self.type('R1', ['en', 'show standby'])[-1])
        self.assertIn('4 packets received', self.type('PC1', ['ping 10.0.0.10'])[0])

    def test_ios_checks(self):
        replies = self.type('R2', ['en', 'conf t', 'int g0/0/0', 'standby 3 ip 10.9.9.1', 'standby 3 ip 192.168.1.3',
                                   'standby 3 priority 256', 'standby 300 ip 192.168.1.5', 'standby 3 timers 5 5',
                                   'standby 3 authentication md5 key-string x', 'standby 3 authentication LAB12345',
                                   'standby 3 ip 192.168.1.4', 'stan 3 pri 90', 'no standby 3 priority', 'no standby 3', 'end'])
        self.assertIn('address is not within a subnet on this interface', replies[3])
        self.assertIn("own address", replies[4])
        self.assertIn('de 0 à 255', replies[5])
        self.assertIn('de 0 à 255 en version 1', replies[6])
        self.assertIn('hold de hello+1', replies[7])
        self.assertIn('texte seulement', replies[8])
        self.assertEqual(replies[9:13], ['', '', '', ''])
        self.assertEqual([l for l in self.node('R2')['cli_config']['interfaces']['eth0'] if 'standby 3' in l], [])
        self.assertNotIn('%', ''.join(r for r in replies[9:] if 'CONFIG_I' not in r))

    def test_a_group_above_255_needs_version_2(self):
        replies = self.type('R2', ['en', 'conf t', 'int g0/0/1', 'standby 4000 ip 10.0.0.5', 'no standby version', 'end'])
        self.assertEqual(replies[3], '')
        self.assertIn('version 2', replies[4])
        self.assertIn('eth1/4000/2/10.0.0.5/100/n/3/10/636973636f', hsrp.arguments(self.node('R2')))


SHOW = '''now 1200.0
== eth0.1
interface eth0
group 1
version 1
vip 192.168.1.1
vdev hsrp2-1
macvlan 1
state active
priority 110
preempt y
hello 3
hold 10
auth 636973636f000000
changes 4
since 1080.5
active local 110 0.0
standby 192.168.1.3 100 1208.2
next 1201.5
'''


class GuestHsrpTest(unittest.TestCase):
    def node(self, name='R1'):
        return next(n for n in configured()['spec']['nodes'] if n['name'] == name)

    def test_the_guest_state_reads_as_ios_shows_it(self):
        states = hsrp.parse(SHOW)
        self.assertEqual(states[('eth0', 1)]['state'], 'active')
        text = hsrp.show(self.node(), states)
        self.assertIn('  State is Active\n    4 state changes, last state change 00:01:59', text)
        self.assertIn('    Next hello sent in 1.500 secs', text)
        self.assertIn('  Standby router is 192.168.1.3, priority 100 (expires in 8.200 sec)', text)
        self.assertIn('Active virtual MAC address is 0000.0c07.ac01 (MAC In Use)', text)

    def test_boot_starts_the_speaker_and_a_change_hands_it_over(self):
        from network_labs.appliances import guest_startup
        node = self.node()
        calls = []
        record = lambda s, o, **k: calls.append((o, k.get('hsrp'))) or {'forwarding': '1\n'}.get(o, '')
        with patch.object(guest_startup, 'query', side_effect=record), patch.object(guest_startup, 'observe', return_value={}), \
                patch.object(guest_startup, 'expected_profile', return_value={}):
            guest_startup.apply('/socket', node)
        self.assertIn(('hsrp-start', hsrp.arguments(node)), calls)
        changed = copy.deepcopy(node)
        changed['cli_config']['interfaces']['eth0'] = [l for l in changed['cli_config']['interfaces']['eth0'] if 'preempt' not in l]
        calls.clear()
        with patch.object(guest_startup, 'query', side_effect=record), patch.object(guest_startup, 'observe', return_value={}), \
                patch.object(guest_startup, 'expected_profile', return_value={}):
            guest_startup.change_routing('/socket', node, changed)
        self.assertIn(('hsrp-start', ['eth0/1/1/192.168.1.1/110/n/3/10/636973636f', 'eth1/2/2/10.0.0.1/100/n/3/10/636973636f']), calls)

    def test_the_readback_accepts_the_virtual_mac_device(self):
        from network_labs.appliances import guest_startup
        node = self.node()
        text = ('2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 192.168.1.2/24 scope global eth0\n'
                '    inet 192.168.1.1/32 scope global eth0\n'  # a guest kernel without macvlan: on the port itself
                '3: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 10.0.0.2/24 scope global eth1\n'
                '4: hsrp2-1@eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 192.168.1.1/32 scope global hsrp2-1\n')
        routes = '192.168.1.0/24 dev eth0 scope link src 192.168.1.2\n10.0.0.0/24 dev eth1 scope link src 10.0.0.2\n'
        replies = {'addresses': text, 'routes': routes, 'forwarding': '1\n', 'proxy-arps': 'eth0 1\neth1 1\n'}
        with patch.object(guest_startup, 'query', side_effect=lambda s, o, **k: replies[o]):
            profile = guest_startup.observe('/socket', node)
        self.assertEqual(profile, {'addresses': [], 'routes': []})  # nothing to save: no extra address, no route

    def test_guest_requests_are_checked(self):
        from network_labs.appliances.guest_control import request
        for bad in (['eth16/1/1/192.168.1.1/100/n/3/10/63'], ['eth0/1/3/192.168.1.1/100/n/3/10/63'], [], 'eth0/1/1/1.1.1.1/1/n/3/10/63'):
            with self.subTest(groups=bad), self.assertRaises(ValueError):
                request('/nowhere', 'hsrp-start', hsrp=bad)
        with self.assertRaises(ValueError):
            request('/nowhere', 'hsrp-show', hsrp=['eth0/1/1/192.168.1.1/100/n/3/10/63'])


class AgentHsrpParseTest(unittest.TestCase):
    """The agent checks each group again, and parsing one keeps HSRP_START's own split of the request."""

    def run_harness(self, body):
        agent = Path('network_labs/appliances/guest/agent.c').resolve()
        harness = f'#define main agent_main\n#include "{agent}"\n#undef main\nint main(void) {{ {body} return 0; }}\n'
        with tempfile.TemporaryDirectory() as folder:
            source, binary = Path(folder) / 'harness.c', Path(folder) / 'harness'
            source.write_text(harness)
            subprocess.run(['gcc', '-Wall', '-Wno-unused-function', '-o', str(binary), str(source)], check=True)
            return subprocess.run([str(binary)], capture_output=True, text=True, check=True).stdout.split()

    def test_groups_are_checked_and_the_split_kept(self):
        good = 'eth0/1/1/192.168.1.1/110/y/3/10/636973636f eth0.10/4095/2/10.0.0.1/0/n/1/4/6c6162'
        bad = ['eth0/256/1/192.168.1.1/100/n/3/10/63', 'eth0/1/1/192.168.1.1/100/n/5/5/63', 'eth0/1/1/192.168.1.1/256/n/3/10/63',
               'br0/1/1/192.168.1.1/100/n/3/10/63', 'eth0/1/1/192.168.1.1/100/n/3/10/6', 'eth0/1/1/192.168.1.1/100/n/3/10/63/x']
        body = (f'char line[] = "{good}"; struct hsrp h; int count = 0;\n'
                '  for (char *item = strtok(line, " "); item; item = strtok(NULL, " ")) count += hsrp_parse(item, &h);\n'
                '  printf("%d %02x%02x%02x %d\\n", count, h.vmac[3], h.vmac[4], h.vmac[5], h.priority);\n'
                + ''.join(f'  printf("%d\\n", hsrp_parse("{b}", &h));\n' for b in bad))
        self.assertEqual(self.run_harness(body), ['2', '9fffff', '0'] + ['0'] * len(bad))


if __name__ == '__main__':
    unittest.main()
