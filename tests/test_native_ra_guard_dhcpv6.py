"""Explicit local IA_NA/RA/guard pairing; broader coexistence stays rejected."""
import copy
import unittest
from network_labs.appliances.examples import ra_guard_dhcpv6_lab
from network_labs.appliances.ra_guard import render
from network_labs.appliances.slaac import server_config, client_settings
from network_labs.appliances.spec import validate


class RAGuardDHCPv6Tests(unittest.TestCase):
    def test_local_pair_keeps_dhcp_address_and_ra_gateway_separate(self):
        spec = ra_guard_dhcpv6_lab('/rootfs'); self.assertEqual(validate(spec), spec)
        client, server = spec['nodes'][:2]; switch = spec['nodes'][5]
        self.assertEqual(client['dhcpv6_clients'], ['eth0']); self.assertEqual(client['slaac'], [])
        self.assertEqual(client['ipv6'], {}); self.assertEqual(client['ipv6_routes'], [])
        self.assertEqual(client_settings(client)['autoconf'], 0)
        self.assertEqual(client_settings(client)['accept_ra'], 1)
        self.assertIn('dhcp-range=2001:db8:10::100,2001:db8:10::10f,64,120s', server_config(server))
        text = render(switch)
        self.assertIn('tcp, udp, ipv6-icmp', text)
        self.assertNotIn('udp sport', text); self.assertNotIn('udp dport', text)
        self.assertEqual(switch['ra_guard']['trusted'], ['eth1'])

    def test_client_and_server_must_be_directly_paired_to_untrusted_and_trusted_ports(self):
        original = ra_guard_dhcpv6_lab('/rootfs')
        changes = [lambda s: s['nodes'][5]['ra_guard'].update(trusted=[]),
                   lambda s: s['nodes'][5]['ra_guard'].update(trusted=['eth0', 'eth1']),
                   lambda s: s['nodes'][1].update(dhcpv6_server=None),
                   lambda s: s['nodes'][0].update(dhcpv6_clients=[]),
                   lambda s: s['nodes'][1].update(router_advertisements=['eth0', 'eth1']),
                   lambda s: s['nodes'][4].update(ipv6={}, ipv6_routes=[], dhcpv6_clients=['eth0']),
                   lambda s: s['nodes'][4].update(ipv6={}, ipv6_routes=[], slaac=['eth0']),
                   lambda s: s['links'].pop(-2),
                   lambda s: s.update(links=None),
                   lambda s: s['links'][0][1].__setitem__(1, [])]
        for index, change in enumerate(changes):
            spec = copy.deepcopy(original); change(spec)
            with self.subTest(case=index), self.assertRaises(ValueError): validate(spec)
        swapped = copy.deepcopy(original); swapped['links'] = [link[::-1] for link in swapped['links']]
        self.assertEqual(validate(swapped), swapped)
