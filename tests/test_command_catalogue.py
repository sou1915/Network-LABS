"""The command catalogue lists only what works: every example goes through the terminal's own parser."""
import unittest

from network_labs.appliances import command_catalogue as catalogue
from network_labs.appliances import vendor_config, vendor_show
from network_labs.appliances.microvm import firewall_nat_example, router_chain_example, switch_vlan_example
from network_labs.appliances.spec import validate

MODELS = {('ios', 'router'): 'cisco-isr4331', ('ios', 'switch'): 'cisco-2960', ('ios', 'firewall'): 'cisco-asa',
          ('eos', 'router'): 'arista-7280r', ('eos', 'switch'): 'arista-7050', ('vrp', 'router'): 'huawei-ar6120',
          ('vrp', 'switch'): 'huawei-s5700', ('junos', 'router'): 'juniper-mx204', ('junos', 'switch'): 'juniper-ex',
          ('junos', 'firewall'): 'juniper-srx', ('panos', 'firewall'): 'palo-alto', ('fortios', 'firewall'): 'fortigate',
          ('routeros', 'router'): 'mikrotik-ccr', ('routeros', 'switch'): 'mikrotik-crs'}
BASES = {'router': (router_chain_example, 'R1'), 'switch': (switch_vlan_example, 'SW1'), 'firewall': (firewall_nat_example, 'FW1')}
ENTER = {'ios': 'configure terminal', 'eos': 'configure terminal', 'vrp': 'system-view', 'junos': 'configure', 'panos': 'configure'}
EXEC_MODES = ('exec', 'user', 'operational')


def lab(syntax, role):
    build, name = BASES[role]
    spec = build('/k', '/d')
    node = next(n for n in spec['nodes'] if n['name'] == name)
    node['model'] = MODELS[(syntax, role)]
    if role != 'switch':
        node['interfaces']['eth2'] = '10.2.0.1/24'  # a third port, for the subinterface examples
        node['guest_network'] = {'addresses': [], 'routes': []}  # OSPF refuses static routes beside it
    return validate(spec), name


class CatalogueTest(unittest.TestCase):
    def test_every_configuration_example_is_accepted_by_the_vendor_parser(self):
        checked = 0
        for (syntax, role) in MODELS:
            spec, name = lab(syntax, role)
            node = next(n for n in spec['nodes'] if n['name'] == name)
            for entry in catalogue.entries(node):
                if entry['mode'] in EXEC_MODES:
                    continue
                with self.subTest(syntax=syntax, role=role, syntax_line=entry['syntax']):
                    vendor_config.apply(spec, name, '\n'.join(entry['example']))
                    checked += 1
        self.assertGreater(checked, 150)

    def test_every_show_and_ping_is_one_the_terminal_answers(self):
        self.assertEqual(catalogue.check_known_shows(), [])
        for (syntax, role) in MODELS:
            spec, name = lab(syntax, role)
            node = next(n for n in spec['nodes'] if n['name'] == name)
            for entry in catalogue.entries(node):
                if entry['mode'] in EXEC_MODES and 'ping' in entry['syntax']:
                    with self.subTest(syntax=syntax, line=entry['example'][0]):
                        self.assertEqual(vendor_show.ping_destination(node, entry['example'][0]), entry['example'][0].split()[-1])

    def test_examples_use_the_nodes_own_port_names_and_roles_filter_entries(self):
        spec, name = lab('junos', 'router')
        router = next(n for n in spec['nodes'] if n['name'] == name)
        address = next(e for e in catalogue.entries(router) if e['syntax'].startswith('set interfaces'))
        self.assertEqual(address['example'], ['set interfaces xe-0/0/0 unit 0 family inet address 192.0.2.1/24'])
        self.assertIn('BGP', catalogue.topics(router))
        spec, name = lab('ios', 'switch')
        switch = next(n for n in spec['nodes'] if n['name'] == name)
        self.assertIn('VLAN', catalogue.topics(switch))
        self.assertNotIn('BGP', catalogue.topics(switch))
        host = {'name': 'VM1', 'role': 'host', 'interfaces': {'eth0': '192.0.2.10/24'}}
        self.assertEqual(catalogue.syntax_of(host), 'shell')
        self.assertIn('ip route', [e['syntax'] for e in catalogue.entries(host)])

    def test_context_help_and_completion(self):
        spec, name = lab('ios', 'router')
        router = next(n for n in spec['nodes'] if n['name'] == name)
        self.assertEqual(catalogue.context('ios', 'router bgp 65001'), 'config-router')
        self.assertEqual(catalogue.context('ios', 'interface gi0/0/0.10'), 'config-subif')
        found = [e['syntax'] for e in catalogue.help_for(router, 'config-router', 'neighbor')]
        self.assertIn('neighbor A.B.C.D remote-as AS', found)
        self.assertIn('show ip bgp summary', [e['syntax'] for e in catalogue.help_for(router, 'exec', 'show ip')])
        self.assertEqual(catalogue.completions(router, 'exec', 'show ip b'), ['bgp'])
        self.assertIn('route', catalogue.completions(router, 'exec', 'show ip '))
        self.assertEqual(catalogue.search(router, 'bgp voisin')[0]['topic'], 'BGP')


if __name__ == '__main__':
    unittest.main()


class AbbreviationTest(unittest.TestCase):
    def test_ios_abbreviations_and_port_name_forms_as_typed_in_packet_tracer(self):
        spec, name = lab('ios', 'router')
        router = next(n for n in spec['nodes'] if n['name'] == name)
        expand = lambda line: catalogue.expand(router, line)
        self.assertEqual(expand('int g0/0/0'), 'interface g0/0/0')
        self.assertEqual(expand('ip add 192.0.2.1 255.255.255.0'), 'ip address 192.0.2.1 255.255.255.0')
        self.assertEqual(expand('no shut'), 'no shutdown')
        self.assertEqual(expand('router os 1'), 'router ospf 1')
        self.assertEqual(expand('nei 203.0.113.2 remote-as 65002'), 'neighbor 203.0.113.2 remote-as 65002')
        self.assertEqual(expand('ip ro 0.0.0.0 0.0.0.0 203.0.113.2'), 'ip route 0.0.0.0 0.0.0.0 203.0.113.2')
        self.assertEqual(expand('i 1'), 'i 1')  # ambiguous: left as typed, the parser answers
        for typed in ('g0/0/1', 'gi0/0/1', 'GigabitEthernet0/0/1', 'gig0/0/1', 'eth1'):
            with self.subTest(typed=typed):
                self.assertEqual(vendor_config._port(router, typed), 'eth1')
        with self.assertRaises(ValueError):
            vendor_config._port(router, 'fa0/0/1')
        spec, name = lab('ios', 'switch')
        switch = next(n for n in spec['nodes'] if n['name'] == name)
        self.assertEqual(catalogue.expand(switch, 'sw mo acc'), 'switchport mode access')
        self.assertEqual(catalogue.expand(switch, 'sw acc vl 20'), 'switchport access vlan 20')
        self.assertEqual(vendor_config._port(switch, 'FastEthernet0/2'), 'eth1')
