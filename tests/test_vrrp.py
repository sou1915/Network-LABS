"""VRRP on router micro-VMs, typed as on IOS: R1 and R2 share the LAN 192.168.1.0/24 (group 1, virtual address .1, R1
priority 110) and the server LAN 10.0.0.0/24, where group 2's virtual address is R2's own (R2 owns it: priority 255).
The lines make the agent's --vrrp arguments; a stopped lab elects as the routers would, so the PC reaches the server
through the virtual addresses and the backup takes over when the master's port is shut. Two agents speak VRRP for real
between network namespaces: election, the PC on the virtual MAC, failover when the master resigns, preemption."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console, topology_edit, vrrp
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project

R1 = ['en', 'conf t', 'int g0/0/0', 'ip address 192.168.1.2 255.255.255.0', 'no shut', 'vrrp 1 ip 192.168.1.1', 'vrrp 1 priority 110',
      'vrrp 1 description LAN', 'int g0/0/1', 'ip address 10.0.0.2 255.255.255.0', 'no shut', 'vrrp 2 ip 10.0.0.3', 'end']
R2 = ['en', 'conf t', 'int g0/0/0', 'ip address 192.168.1.3 255.255.255.0', 'no shut', 'vrrp 1 ip 192.168.1.1',
      'int g0/0/1', 'ip address 10.0.0.3 255.255.255.0', 'no shut', 'vrrp 2 ip 10.0.0.3', 'end']


def lab():
    spec = blank_project('vrrp')
    for name in ('SW1', 'SW2'):
        spec = topology_edit.add_microvm_node(spec, name=name, role='switch', kernel='/k', disk='/d', ports=4, model='cisco-2960')
    for name in ('R1', 'R2'):
        spec = topology_edit.add_microvm_node(spec, name=name, role='router', kernel='/k', disk='/d', ports=2, model='cisco-isr4331')
    spec = topology_edit.add_microvm_node(spec, name='PC1', role='host', kernel='/k', disk='/d', ports=1, addresses='192.168.1.10/24')
    spec = topology_edit.add_microvm_node(spec, name='SRV', role='host', kernel='/k', disk='/d', ports=1, addresses='10.0.0.10/24')
    for name, gateway in (('PC1', '192.168.1.1'), ('SRV', '10.0.0.3')):
        next(n for n in spec['nodes'] if n['name'] == name)['gateway'] = gateway
    for a, b in ((('R1', 'eth0'), ('SW1', 'eth0')), (('R2', 'eth0'), ('SW1', 'eth1')), (('PC1', 'eth0'), ('SW1', 'eth2')),
                 (('R1', 'eth1'), ('SW2', 'eth0')), (('R2', 'eth1'), ('SW2', 'eth1')), (('SRV', 'eth0'), ('SW2', 'eth2'))):
        spec = topology_edit.connect(spec, a, b)
    return validate(spec)


def configured():
    box = {'spec': lab()}
    draft = DraftLab(lambda: box['spec'], lambda spec: box.update(spec=validate(spec)))
    for name, lines in (('R1', R1), ('R2', R2)):
        console = guest_console.Console('vrrp', name, lambda _: draft)
        for line in lines:
            reply = console.line(line)
            assert '%' not in reply or 'CONFIG_I' in reply or 'LINK' in reply or 'LINEPROTO' in reply, (line, reply)
    return box


SHOW = """now 500.0
== eth0.1
interface eth0
group 1
vip 192.168.1.1
vdev vrrp2-1
macvlan 1
state master
priority 110
preempt y
advert 1
auth -
changes 3
since 381.0
master local 110 1
down 0.0
next 500.6
"""


class VrrpTest(unittest.TestCase):
    def setUp(self):
        self.box = configured()
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def type(self, name, lines):
        console = guest_console.Console('vrrp', name, lambda _: self.lab)
        return [console.line(line) for line in lines]

    def node(self, name):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == name)

    def test_typed_lines_make_the_groups_and_the_agent_arguments(self):
        self.assertEqual(vrrp.arguments(self.node('R1')), ['eth0/1/192.168.1.1/110/y/1/-', 'eth1/2/10.0.0.3/100/y/1/-'])
        self.assertEqual(vrrp.arguments(self.node('R2')), ['eth0/1/192.168.1.1/100/y/1/-', 'eth1/2/10.0.0.3/255/y/1/-'])  # the owner
        config = self.type('R1', ['en', 'show running-config'])[-1]
        self.assertIn(' vrrp 1 description LAN\n vrrp 1 ip 192.168.1.1\n vrrp 1 priority 110', config)

    def test_a_stopped_lab_elects_and_the_pc_reaches_the_server_through_the_virtual_addresses(self):
        brief = self.type('R1', ['en', 'show vrrp brief'])[-1].splitlines()
        self.assertEqual(brief[0], 'Interface          Grp Pri Time  Own Pre State   Master addr     Group addr')
        self.assertRegex(brief[1], r'^Gi0/0/0 +1 +110 3570 +Y +Master +192\.168\.1\.2 +192\.168\.1\.1$')
        self.assertRegex(brief[2], r'^Gi0/0/1 +2 +100 3609 +Y +Backup +10\.0\.0\.3 +10\.0\.0\.3$')
        shown = self.type('R2', ['en', 'show vrrp'])[-1]
        self.assertIn('GigabitEthernet0/0/0 - Group 1\n  State is Backup\n  Virtual IP address is 192.168.1.1\n'
                      '  Virtual MAC address is 0000.5e00.0101', shown)
        self.assertIn('  Master Router is 192.168.1.2, priority is 110', shown)
        self.assertIn('  Priority is 255 (IP address owner)\n  Master Router is 10.0.0.3 (local), priority is 255', shown)
        self.assertIn(', 0% packet loss', self.type('PC1', ['ping 10.0.0.10'])[-1])  # PC1 → 192.168.1.1 (R1) → SRV, back by 10.0.0.3

    def test_the_backup_takes_over_when_the_master_port_is_shut(self):
        self.type('R1', ['en', 'conf t', 'int g0/0/0', 'shutdown', 'end'])
        brief = self.type('R2', ['en', 'show vrrp brief'])[-1]
        self.assertRegex(brief, r'Gi0/0/0 +1 +100 3609 +Y +Master +192\.168\.1\.3 +192\.168\.1\.1')
        self.assertIn(', 0% packet loss', self.type('PC1', ['ping 10.0.0.10'])[-1])

    def test_preempt_shutdown_and_removal(self):
        self.type('R2', ['en', 'conf t', 'int g0/0/0', 'no vrrp 1 preempt', 'vrrp 1 timers advertise 2', 'vrrp 1 authentication text LAB',
                         'int g0/0/1', 'vrrp 2 shutdown', 'end'])
        settings = vrrp.groups(self.node('R2'))
        self.assertEqual((settings['eth0'][1]['preempt'], settings['eth0'][1]['advertise'], settings['eth0'][1]['auth']), (False, 2, 'LAB'))
        self.assertEqual(vrrp.arguments(self.node('R2')), ['eth0/1/192.168.1.1/100/n/2/4c4142'])  # a shut group is not run
        self.assertIn(' no vrrp 1 preempt', self.type('R2', ['en', 'show running-config'])[-1])
        self.type('R2', ['en', 'conf t', 'int g0/0/0', 'vrrp 1 preempt', 'no vrrp 1', 'end'])
        self.assertNotIn('eth0', vrrp.groups(self.node('R2')))

    def test_ios_checks(self):
        replies = self.type('R1', ['en', 'conf t', 'int g0/0/0', 'vrrp 1 priority 255', 'vrrp 0 ip 192.168.1.1', 'vrrp 3 ip 10.9.9.9',
                                   'vrrp 1 authentication md5 key-string x', 'vrrp 1 timers advertise 0', 'vrrp 1 ip 192.168.1.1 secondary'])
        for reply in replies[3:]:
            self.assertTrue(reply.strip(), replies)
        self.assertIn('Address 10.9.9.9 is not in a subnet', replies[5])
        self.assertEqual(vrrp.arguments(self.node('R1'))[0], 'eth0/1/192.168.1.1/110/y/1/-')  # nothing refused was kept

    def test_the_guest_state_reads_as_ios_shows_it(self):
        states = vrrp.parse(SHOW)
        self.assertEqual(states[('eth0', 1)]['state'], 'master')
        text = vrrp.show(self.node('R1'), states)
        self.assertIn('GigabitEthernet0/0/0 - Group 1\n  LAN\n  State is Master', text)
        self.assertIn('  Master Router is 192.168.1.2 (local), priority is 110', text)
        self.assertIn('  Master Down interval is 3.570 sec', text)

    def test_boot_starts_the_speaker_and_a_change_hands_it_over(self):
        from network_labs.appliances import guest_startup
        node = self.node('R1')
        calls = []
        record = lambda s, o, **k: calls.append((o, k.get('vrrp'))) or {'forwarding': '1\n'}.get(o, '')
        with patch.object(guest_startup, 'query', side_effect=record), patch.object(guest_startup, 'observe', return_value={}), \
                patch.object(guest_startup, 'expected_profile', return_value={}):
            guest_startup.apply('/socket', node)
        self.assertIn(('vrrp-start', vrrp.arguments(node)), calls)
        changed = copy.deepcopy(node)
        changed['cli_config']['interfaces']['eth0'] = [l for l in changed['cli_config']['interfaces']['eth0'] if 'priority' not in l]
        calls.clear()
        with patch.object(guest_startup, 'query', side_effect=record), patch.object(guest_startup, 'observe', return_value={}), \
                patch.object(guest_startup, 'expected_profile', return_value={}):
            guest_startup.change_routing('/socket', node, changed)
        self.assertIn(('vrrp-start', ['eth0/1/192.168.1.1/100/y/1/-', 'eth1/2/10.0.0.3/100/y/1/-']), calls)

    def test_the_readback_accepts_the_virtual_mac_device(self):
        from network_labs.appliances import guest_startup
        node = self.node('R1')
        text = ('2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 192.168.1.2/24 scope global eth0\n'
                '3: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 10.0.0.2/24 scope global eth1\n'
                '4: vrrp2-1@eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 192.168.1.1/32 scope global vrrp2-1\n')
        routes = '192.168.1.0/24 dev eth0 scope link src 192.168.1.2\n10.0.0.0/24 dev eth1 scope link src 10.0.0.2\n'
        replies = {'addresses': text, 'routes': routes, 'forwarding': '1\n', 'proxy-arps': 'eth0 1\neth1 1\n'}
        with patch.object(guest_startup, 'query', side_effect=lambda s, o, **k: replies[o]):
            self.assertEqual(guest_startup.observe('/socket', node), {'addresses': [], 'routes': []})

    def test_guest_requests_are_checked(self):
        from network_labs.appliances.guest_control import request
        for bad in (['eth16/1/192.168.1.1/100/y/1/-'], ['eth0/1/192.168.1.1/100/x/1/-'], [], 'eth0/1/192.168.1.1/100/y/1/-'):
            with self.subTest(groups=bad), self.assertRaises(ValueError):
                request('/nowhere', 'vrrp-start', vrrp=bad)
        with self.assertRaises(ValueError):
            request('/nowhere', 'vrrp-show', vrrp=['eth0/1/192.168.1.1/100/y/1/-'])


@unittest.skipUnless(shutil.which('gcc') and shutil.which('ip') and os.geteuid() == 0 and Path('/bin/busybox').exists(),
                     'root, gcc, iproute2 and BusyBox required for the agent in network namespaces')
class AgentVrrpTest(unittest.TestCase):
    """Two routers' agents speak VRRP on a bridge with a PC: R1 (priority 120) master, R2 backup; the PC reaches the virtual
    address on the virtual MAC; R1 resigns and R2 takes over; R1 comes back and, preempting, is master again."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root, agent = Path(cls.folder.name), Path('network_labs/appliances/guest/agent.c').resolve()
        for side in ('r1', 'r2'):
            (root / side).mkdir()
            subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', f'-DVRRP_RUN="{root / side}"', '-o', str(root / ('agent_' + side)), str(agent)],
                           check=True)
        cls.root, tag = root, str(os.getpid())
        cls.spaces = {name: f'nlv{name}{tag}' for name in ('r1', 'r2', 'pc', 'sw')}
        commands = [['ip', 'netns', 'add', space] for space in cls.spaces.values()]
        commands += [['ip', '-n', cls.spaces['sw'], 'link', 'add', 'br0', 'type', 'bridge'], ['ip', '-n', cls.spaces['sw'], 'link', 'set', 'br0', 'up']]
        for name, address in (('r1', '10.9.0.2/24'), ('r2', '10.9.0.3/24'), ('pc', '10.9.0.10/24')):
            space, port = cls.spaces[name], f'p{name}'
            commands += [['ip', 'link', 'add', 'eth0', 'netns', space, 'type', 'veth', 'peer', 'name', port, 'netns', cls.spaces['sw']],
                         ['ip', '-n', cls.spaces['sw'], 'link', 'set', port, 'master', 'br0'], ['ip', '-n', cls.spaces['sw'], 'link', 'set', port, 'up'],
                         ['ip', '-n', space, 'addr', 'add', address, 'dev', 'eth0'], ['ip', '-n', space, 'link', 'set', 'eth0', 'up']]
        try:
            for command in commands:
                subprocess.run(command, check=True, capture_output=True)
        except subprocess.CalledProcessError as error:
            cls.tearDownClass()
            raise unittest.SkipTest(f'network namespaces unavailable: {error.stderr.decode(errors="replace").strip()}')
        cls.running = {}

    @classmethod
    def tearDownClass(cls):
        for process in getattr(cls, 'running', {}).values():
            process.terminate()
            process.wait(timeout=5)
        for space in cls.spaces.values():
            subprocess.run(['ip', 'netns', 'del', space], capture_output=True)
        cls.folder.cleanup()

    def start(self, name, priority):
        self.running[name] = subprocess.Popen(['ip', 'netns', 'exec', self.spaces[name], str(self.root / f'agent_{name}'), '--vrrp',
                                               f'eth0/1/10.9.0.1/{priority}/y/1/-'])

    def state(self, name):
        path = self.root / name / 'eth0.1'
        values = dict(line.split(' ', 1) for line in path.read_text().splitlines() if ' ' in line) if path.exists() else {}
        return values.get('state'), values.get('master', '').split(' ')[0]

    def wait(self, name, wanted, seconds=8):  # WANTED: (state, master), the master known once an advert is heard
        deadline = time.monotonic() + seconds
        while self.state(name) != wanted and time.monotonic() < deadline:
            time.sleep(.2)
        return self.state(name)

    def pc(self, *command):
        return subprocess.run(['ip', 'netns', 'exec', self.spaces['pc'], *command], capture_output=True, text=True, timeout=15).stdout

    def test_election_failover_and_preemption(self):
        self.start('r1', 120)
        self.start('r2', 100)
        self.assertEqual(self.wait('r1', ('master', 'local')), ('master', 'local'))
        self.assertEqual(self.wait('r2', ('backup', '10.9.0.2')), ('backup', '10.9.0.2'))
        time.sleep(1.5)
        self.assertEqual(self.state('r2'), ('backup', '10.9.0.2'))  # a single master: the adverts are heard
        self.assertIn(' 0% packet loss', self.pc('busybox', 'ping', '-c', '2', '-W', '1', '10.9.0.1'))
        self.assertIn('00:00:5e:00:01:01', self.pc('ip', 'neigh', 'show', '10.9.0.1'))  # the virtual MAC
        self.running.pop('r1').terminate()  # R1 resigns (an advert of priority 0)
        self.assertEqual(self.wait('r2', ('master', 'local'), 3), ('master', 'local'))
        self.assertIn(' 0% packet loss', self.pc('busybox', 'ping', '-c', '2', '-W', '1', '10.9.0.1'))
        self.start('r1', 120)  # back, with the higher priority: preemption makes it master again
        self.assertEqual(self.wait('r1', ('master', 'local')), ('master', 'local'))
        self.assertEqual(self.wait('r2', ('backup', '10.9.0.2')), ('backup', '10.9.0.2'))


if __name__ == '__main__':
    unittest.main()
