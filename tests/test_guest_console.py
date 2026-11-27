"""The node terminal of a running micro-VM: vendor prompts and modes, show, ping, live configuration, the host shell."""
import contextlib
import copy
import unittest
from unittest import mock

from network_labs.appliances import guest_console, missions
from network_labs.appliances.spec import validate

ADDRESSES = ('1: lo: <LOOPBACK,UP,LOWER_UP>\n    inet 127.0.0.1/8 scope host lo\n'
             '2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 192.0.2.1/24 scope global eth0\n'
             '3: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 203.0.113.1/30 scope global eth1\n')


class FakeManager:
    """A running lab: its spec, a guest that answers, and the live changes asked of it."""
    def __init__(self, spec):
        self.spec, self.changes, self.state, self.directory = spec, [], None, mock.MagicMock()

    def __call__(self, lab):
        return self

    @contextlib.contextmanager
    def locked(self):
        yield self

    def read(self):
        return {'spec': self.spec}

    def observe_node(self, name):
        return {'interfaces': [{'port': 'eth0', 'up': True, 'addresses': ['192.0.2.1/24']},
                               {'port': 'eth1', 'up': True, 'addresses': ['203.0.113.1/30']}],
                'routes': [], 'vlans': None, 'ospf': None, 'bgp': None}

    def ping_node(self, name, destination, count=5):
        return {'node': name, 'destination': destination,
                'replies': [{'ok': True, 'ttl': 63, 'time_ms': 0.4, 'sequence': i} for i in range(count)]}

    def configure_routing(self, name, node):
        from network_labs.appliances.guest_startup import LIVE_ROUTING
        current = next(n for n in self.spec['nodes'] if n['name'] == name)
        if {k: v for k, v in node.items() if k not in LIVE_ROUTING} != {k: v for k, v in current.items() if k not in LIVE_ROUTING}:
            # as the real configure_routing does
            raise ValueError('Only static routes, the gateway and OSPF change on a running lab; restart it for the rest.')
        self.changes.append(('routing', name, copy.deepcopy(node)))
        self.spec = validate(dict(self.spec, nodes=[node if n['name'] == name else n for n in self.spec['nodes']]))
        return {'configured': name}

    def configure_firewall(self, name, policy):
        self.changes.append(('firewall', name, policy))


def lab(models=None):
    spec = missions.BY_ID['route-manquante']['build']('/k', '/d')
    for name, model in (models or {}).items():
        next(n for n in spec['nodes'] if n['name'] == name)['model'] = model
    return validate(spec)


class ConsoleTest(unittest.TestCase):
    def console(self, spec, node='R1'):
        manager = FakeManager(spec)
        return guest_console.Console(spec['name'], node, manager), manager

    def test_ios_modes_show_ping_and_live_configuration(self):
        console, manager = self.console(lab())
        self.assertEqual(console.prompt(), 'R1>')
        self.assertIn("% Invalid input detected at '^' marker.", console.line('conf t'))  # not from user EXEC, as on IOS
        console.line('enable')
        self.assertEqual(console.prompt(), 'R1#')
        self.assertIn('GigabitEthernet0/0/0', console.line('show ip interface brief'))
        self.assertIn('!!!!!', console.line('ping 198.51.100.20'))
        running = console.line('show running-config')
        self.assertTrue(running.startswith('Building configuration...'))
        self.assertIn('interface GigabitEthernet0/0/0', running)
        self.assertNotIn('Network LABS', running)
        self.assertEqual(console.line('configure terminal'), 'Enter configuration commands, one per line.  End with CNTL/Z.')
        self.assertEqual(console.prompt(), 'R1(config)#')
        self.assertEqual(console.line('ip route 198.51.100.0 255.255.255.0 203.0.113.2'), '')
        kind, name, node = manager.changes[0]  # applied at once, as each IOS line is
        self.assertEqual((kind, name, node['guest_network']['routes']),
                         ('routing', 'R1', [{'network': '198.51.100.0/24', 'gateway': '203.0.113.2'}]))
        self.assertEqual(console.line('end'), '%SYS-5-CONFIG_I: Configured from console by console')
        self.assertEqual(console.prompt(), 'R1#')
        console.line('conf t')
        console.line('int g0/0/0')
        self.assertEqual(console.line('ip add 192.0.2.9 255.255.255.0'), '')
        self.assertEqual(manager.changes[-1][2]['interfaces']['eth0'], '192.0.2.9/24')
        self.assertIn('%LINK-5-CHANGED: Interface GigabitEthernet0/0/0, changed state to administratively down',
                      console.line('shutdown'))
        self.assertEqual(manager.changes[-1][2]['shutdown'], ['eth0'])
        reply = console.line('no shut')
        self.assertIn('%LINEPROTO-5-UPDOWN: Line protocol on Interface GigabitEthernet0/0/0, changed state to up', reply)
        self.assertEqual(manager.changes[-1][2]['shutdown'], [])
        self.assertEqual(console.line('ip adress 1.1.1.1 255.0.0.0').splitlines()[-1], "% Invalid input detected at '^' marker.")
        self.assertEqual(console.line('ip address 192.0.2.9'), '% Incomplete command.')
        self.assertTrue(console.line('i 1').startswith('% Ambiguous command'))
        self.assertEqual(console.line('hostname R9'), '')  # the prompt follows, as on IOS (the lab keeps its node name)
        self.assertEqual(console.prompt(), 'R9(config)#')  # a global command leaves the interface, as on IOS
        self.assertEqual(console.line('end'), '%SYS-5-CONFIG_I: Configured from console by console')
        self.assertEqual(console.line('wr'), 'Building configuration...\n[OK]')
        self.assertIn('% Unknown command', console.line('pign 1.1.1.1'))
        console.line('disable')
        self.assertEqual(console.prompt(), 'R9>')
        with self.assertRaises(EOFError):
            console.line('exit')

    def test_junos_commit_and_vrp_return_apply_live(self):
        console, manager = self.console(lab(), 'R2')  # Juniper MX204 in this mission
        self.assertEqual(console.prompt(), 'admin@R2> ')
        console.line('configure')
        self.assertEqual(console.prompt(), 'admin@R2# ')
        console.line('set routing-options static route 10.9.0.0/16 next-hop 203.0.113.1')
        self.assertIn('Appliqué', console.line('commit'))
        self.assertEqual(console.prompt(), 'admin@R2# ')  # Junos stays in configuration after commit
        console.line('set routing-options static route 10.8.0.0/16 next-hop 203.0.113.1')
        self.assertIn('abandonnées', console.line('exit'))
        self.assertEqual(len(manager.changes), 1)
        vrp, other = self.console(lab({'R1': 'huawei-ar6120'}))
        self.assertEqual(vrp.prompt(), '<R1> ')
        vrp.line('system-view')
        self.assertEqual(vrp.prompt(), '[R1] ')
        vrp.line('ip route-static 198.51.100.0 255.255.255.0 203.0.113.2')
        self.assertIn('Appliqué', vrp.line('return'))
        self.assertEqual(vrp.prompt(), '<R1> ')
        self.assertEqual(other.changes[0][2]['guest_network']['routes'][0]['gateway'], '203.0.113.2')

    def test_host_shell_uses_the_guest_and_its_ping(self):
        console, _ = self.console(lab(), 'VM2')
        self.assertEqual(console.prompt(), 'root@VM2:~# ')
        self.assertIn('4 packets transmitted, 4 packets received, 0% packet loss', console.line('ping 198.51.100.20'))
        with mock.patch.object(guest_console.Console, 'query', return_value=ADDRESSES):
            self.assertIn('inet 192.0.2.1/24', console.line('ip a'))
        with self.assertRaisesRegex(ValueError, 'non disponible'):
            console.line('rm -rf /')

    def test_run_loop_reports_errors_and_closes_on_exit(self):
        spec = lab()
        typed = iter(['enable', 'show nonsense', 'exit'])
        written = []
        code = guest_console.run(spec['name'], 'R1', read=lambda prompt: next(typed), write=written.append,
                                 manager_factory=FakeManager(spec))
        self.assertEqual(code, 0)
        self.assertTrue(written[0].startswith('Terminal de R1'))
        self.assertTrue(any("% Invalid input detected at '^' marker." in line for line in written))


if __name__ == '__main__':
    unittest.main()


class CatalogueHelpTest(unittest.TestCase):
    def console(self, models=None, node='R1'):
        spec = lab(models)
        return guest_console.Console(spec['name'], node, FakeManager(spec))

    def test_ios_sub_mode_prompts_and_context_help(self):
        console = self.console()
        top = console.line('?')
        self.assertIn('enable', top)
        self.assertIn('show', top)
        console.line('enable')
        console.line('configure terminal')
        console.line('interface gi0/0/1')
        self.assertEqual(console.prompt(), 'R1(config-if)#')
        reply = console.line('ip ?')  # IOS: the next words, with what they do
        self.assertIn('address', reply)
        self.assertNotIn('route', reply)  # the sub-mode's own commands
        self.assertIn('A.B.C.D', console.line('ip address ?'))
        self.assertIn('<cr>', console.line('ip address 203.0.113.1 255.255.255.252 ?'))
        self.assertEqual(console.line('ip add?'), 'address')
        console.line('exit')
        self.assertEqual(console.prompt(), 'R1(config)#')
        console.line('interface gi0/0/0')
        console.line('ip route 10.99.0.0 255.255.0.0 203.0.113.2')  # a global command leaves the sub-mode, as on IOS
        self.assertEqual(console.prompt(), 'R1(config)#')
        self.assertEqual(console.line('exit'), '%SYS-5-CONFIG_I: Configured from console by console')  # exit from config
        self.assertEqual(console.prompt(), 'R1#')
        self.assertIn('ip access-group INVITES in', console.line('help acl'))
        self.assertEqual(console.complete('show ip b'), ['bgp'])

    def test_vrp_views_and_quit_one_level_up(self):
        console = self.console({'R1': 'huawei-ar6120'})
        self.assertEqual(console.prompt(), '<R1> ')
        console.line('system-view')
        console.line('interface GE0/0/1')
        self.assertEqual(console.prompt(), '[R1-GE0/0/1] ')
        console.line('quit')
        self.assertEqual(console.prompt(), '[R1] ')
        console.line('undo ip route-static 198.51.100.0 255.255.255.0')
        console.line('ospf 1 router-id 1.1.1.1')
        console.line('area 0')
        self.assertEqual(console.prompt(), '[R1-ospf-1-area-0.0.0.0] ')
        self.assertIn('network A.B.C.D JOKER', console.line('?'))
        console.line('quit')
        self.assertEqual(console.prompt(), '[R1-ospf-1] ')

    def test_unknown_topic_lists_the_topics(self):
        self.assertIn('Interfaces', self.console().line('help pizza'))


class HostShellAddressingTest(unittest.TestCase):
    def test_a_pc_gets_its_address_and_gateway_from_its_terminal(self):
        spec = lab()
        host = next(n for n in spec['nodes'] if n['role'] == 'host')
        cidr = host['interfaces']['eth0']
        network = cidr.rsplit('.', 1)[0]
        manager = FakeManager(spec)
        console = guest_console.Console(spec['name'], host['name'], manager)
        self.assertIn('ip addr del', console.line('?'))
        with self.assertRaisesRegex(ValueError, 'ip addr del'):
            console.line(f'ip addr add {network}.77/24 dev eth0')  # one address per port: remove the old one first
        self.assertEqual(console.line(f'ip addr del {cidr} dev eth0'), '')  # silent when it works, as on Linux
        self.assertEqual(manager.changes[-1][2]['interfaces']['eth0'], '')
        self.assertEqual(console.line(f'ip addr add {network}.77/24 dev eth0'), '')
        self.assertEqual(manager.changes[-1][2]['interfaces']['eth0'], f'{network}.77/24')
        import ipaddress
        lan = ipaddress.IPv4Interface(f'{network}.77/24').network
        gateway = next(a.split('/')[0] for n in spec['nodes'] if n['role'] == 'router' for a in n['interfaces'].values()
                       if a and ipaddress.IPv4Interface(a).network == lan)
        self.assertEqual(console.line(f'ip route add default via {gateway}'), '')
        self.assertEqual(manager.changes[-1][2]['gateway'], gateway)
