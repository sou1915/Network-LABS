"""IOS extended access lists on router micro-VMs: schema, IOS commands, the guest chain they compile to, the model."""
import copy
import unittest

from network_labs.appliances import acl, guest_firewall, missions, vendor_show
from network_labs.appliances.network_model import Model
from network_labs.appliances.spec import validate
from network_labs.appliances.vendor_config import apply, render

FIX = ('ip access-list extended INVITES\n deny icmp 192.0.2.0 0.0.0.255 host 203.0.113.10\n permit ip any any\n'
       'interface gi0/0\n ip access-group INVITES in')


def lab():
    return missions.BY_ID['acl-invites']['build']('/k', '/d')


class AclTest(unittest.TestCase):
    def test_ios_commands_round_trip_and_sequence_numbers(self):
        fixed = apply(lab(), 'R1', FIX)
        router = fixed['nodes'][0]
        self.assertEqual(router['acl_ports'], {'eth0': 'INVITES'})
        self.assertEqual(apply(fixed, 'R1', render(fixed, 'R1')), fixed)
        replaced = apply(fixed, 'R1', 'ip access-list extended INVITES\n 10 deny icmp any host 203.0.113.10')['nodes'][0]
        self.assertEqual(replaced['acls']['INVITES'][0]['source'], '0.0.0.0/0')
        removed = apply(fixed, 'R1', 'ip access-list extended INVITES\n no 10')['nodes'][0]
        self.assertEqual([e['action'] for e in removed['acls']['INVITES']], ['permit'])
        gone = apply(fixed, 'R1', 'no ip access-list extended INVITES')['nodes'][0]
        self.assertEqual((gone['acls'], gone['acl_ports']), ({}, {}))
        for text, message in (('interface gi0/0\n ip access-group INVITES out', 'sortante'),
                              ('ip access-list extended X\n permit ip 10.0.0.0 0.255.0.255 any', 'contigu'),
                              ('ip access-list extended X\n 30 permit ip any any', 'prochaine'),
                              ('interface gi0/0\n ip access-group ABSENT in', 'existing access list')):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                apply(lab(), 'R1', text)

    def test_first_match_implicit_deny_protocol_and_port(self):
        node = validate({'version': 1, 'name': 'x', 'nodes': [dict(lab()['nodes'][0], acls={'L': [
            {'action': 'permit', 'protocol': 'tcp', 'destination': '10.0.0.0/8', 'dport': 443},
            {'action': 'deny', 'protocol': 'icmp', 'source': '192.0.2.0/24'},
            {'action': 'permit', 'protocol': 'icmp'}]}, acl_ports={'eth1': 'L'})], 'links': []})['nodes'][0]
        packet = {'source': '192.0.2.5', 'destination': '10.1.1.1'}
        self.assertEqual(acl.evaluate(node, 'eth1', dict(packet, protocol='tcp', dport=443)), 'permit')
        self.assertEqual(acl.evaluate(node, 'eth1', dict(packet, protocol='tcp', dport=22)), 'deny')  # implicit deny
        self.assertEqual(acl.evaluate(node, 'eth1', dict(packet, protocol='icmp')), 'deny')
        self.assertEqual(acl.evaluate(node, 'eth1', dict(packet, source='198.51.100.1', protocol='icmp')), 'permit')
        self.assertEqual(acl.evaluate(node, 'eth0', dict(packet, protocol='icmp')), 'permit')  # no list on that port
        chain = guest_firewall.expected(acl.policy(node))
        self.assertEqual(chain['default'], 'accept')
        self.assertEqual(chain['rules'][1:], [
            {'in': 'eth1', 'protocol': 'tcp', 'destination': '10.0.0.0/8', 'dport': 443, 'action': 'accept'},
            {'in': 'eth1', 'protocol': 'icmp', 'source': '192.0.2.0/24', 'action': 'drop'},
            {'in': 'eth1', 'protocol': 'icmp', 'action': 'accept'},
            {'in': 'eth1', 'action': 'drop'}])

    def test_only_micro_vm_routers_take_lists(self):
        host = copy.deepcopy(lab())
        host['nodes'][1]['acls'] = {'L': []}
        with self.assertRaisesRegex(ValueError, 'micro-VM routers'):
            validate(host)

    def test_model_mission_and_show(self):
        broken, fixed = lab(), apply(lab(), 'R1', FIX)
        self.assertTrue(Model(broken).ping('Invite', '203.0.113.10')[0])
        ok, why = Model(fixed).ping('Invite', '203.0.113.10')
        self.assertFalse(ok)
        self.assertIn('l’ACL INVITES de gi0/0 refuse le paquet', why)
        self.assertTrue(Model(fixed).ping('Invite', '100.64.0.10')[0])
        self.assertTrue(Model(fixed).ping('Personnel', '203.0.113.10')[0])
        graded = missions.grade(fixed, 'acl-invites')
        self.assertTrue(all(r['status'] == 'ok' for r in graded['results'] if r['kind'] == 'configuration'))
        text = vendor_show.show(fixed['nodes'][0], {'interfaces': [], 'routes': [], 'vlans': None, 'ospf': None}, 'sh access-lists')
        self.assertIn('Extended IP access list INVITES    (in : gi0/0)', text)
        self.assertIn('10 deny icmp 192.0.2.0 0.0.0.255 host 203.0.113.10', text)


if __name__ == '__main__':
    unittest.main()
