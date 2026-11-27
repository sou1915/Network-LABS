"""Live vendor 'show' commands: observation parsing, vendor layouts, the GUI bridge action and the workbench."""
import os
import unittest
from unittest.mock import patch

from network_labs.appliances import ui_bridge, vendor_show
from network_labs.appliances.microvm import router_chain_example, switch_vlan_example
from network_labs.appliances.spec import validate

KERNEL, DISK = '/assets/vmlinux', '/assets/guest.ext4'
ADDRESSES = ('1: lo: <LOOPBACK,UP,LOWER_UP>\n    inet 127.0.0.1/8 scope host lo\n'
             '2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 192.0.2.1/24 scope global eth0\n'
             '3: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP>\n    inet 203.0.113.1/30 scope global eth1\n')
ROUTES = ('192.0.2.0/24 dev eth0 scope link  src 192.0.2.1\n198.51.100.0/24 via 203.0.113.2 dev eth1\n'
          '203.0.113.0/30 dev eth1 scope link  src 203.0.113.1\n')
VLANS = 'br0 1 pvid untagged\neth0 10 pvid untagged\neth1 10 pvid untagged\neth2 20 pvid untagged\neth3 1 pvid untagged\neth3 10\neth3 20\n'


def router(model):
    lab = router_chain_example(KERNEL, DISK)
    lab['nodes'][0]['model'] = model
    lab = validate(lab)
    return lab, lab['nodes'][0]


def observed(node, replies=None):
    replies = replies or {'addresses': ADDRESSES, 'routes': ROUTES}
    return vendor_show.observe_guest(lambda operation: replies[operation], node)


class ObservationTest(unittest.TestCase):
    def test_guest_replies_become_ports_and_routes(self):
        _, node = router('cisco-isr4331')
        observation = observed(node)
        self.assertEqual([(i['port'], i['up'], i['addresses']) for i in observation['interfaces']],
                         [('eth0', True, ['192.0.2.1/24']), ('eth1', True, ['203.0.113.1/30'])])
        self.assertIn({'network': '198.51.100.0/24', 'gateway': '203.0.113.2', 'port': 'eth1'}, observation['routes'])

    def test_container_ip_json_is_read_the_same_way(self):
        _, node = router('cisco-isr4331')
        address = {'family': 'inet', 'local': '192.0.2.1', 'prefixlen': 24}
        data = {'addresses': [{'ifname': 'eth0', 'flags': ['UP'], 'addr_info': [address]}],
                'routes': [{'dst': 'default', 'gateway': '192.0.2.254', 'dev': 'eth0'}]}
        observation = vendor_show.observe_container(data, node)
        self.assertEqual(observation['interfaces'][1], {'port': 'eth1', 'up': False, 'addresses': []})
        self.assertEqual(observation['routes'], [{'network': '0.0.0.0/0', 'gateway': '192.0.2.254', 'port': 'eth0'}])


class FormatTest(unittest.TestCase):
    def test_ios_route_and_abbreviations(self):
        _, node = router('cisco-isr4331')
        text = vendor_show.show(node, observed(node), 'sh ip ro')
        self.assertIn('S        198.51.100.0/24 [1/0] via 203.0.113.2, GigabitEthernet0/0/1', text)
        self.assertIn('C        192.0.2.0/24 is directly connected, GigabitEthernet0/0/0', text)
        self.assertIn('Gateway of last resort is not set', text)
        brief = vendor_show.show(node, observed(node), 'show ip interface brief')
        self.assertRegex(brief, r'GigabitEthernet0/0/1\s+203\.0\.113\.1\s+YES manual up\s+up')

    def test_fortios_junos_routeros_layouts(self):
        expectations = {'juniper-mx204': ('show route', '198.51.100.0/24    *[Static/5]'),
                        'mikrotik-ccr': ('/ip route print', 'A S  198.51.100.0/24'),
                        'mikrotik-chr': ('/ip address print', '192.0.2.1/24'),
                        'juniper-vsrx': ('show interfaces terse', 'ge-0/0/1.0')}
        for model, (command, expected) in expectations.items():
            with self.subTest(model=model):
                lab = router_chain_example(KERNEL, DISK)
                lab['nodes'][0]['model'] = model
                if model == 'juniper-vsrx':
                    lab['nodes'][0].update(role='firewall', firewall={'default': 'drop', 'stateful': True, 'rules': [], 'nat': []})
                node = validate(lab)['nodes'][0]
                self.assertIn(expected, vendor_show.show(node, observed(node), command))

    def test_eos_vrp_panos_layouts(self):
        expectations = {'arista-7280r': ('sh ip ro', ' S        198.51.100.0/24 [1/0] via 203.0.113.2, Ethernet2'),
                        'huawei-ar6120': ('dis ip routing-table', '198.51.100.0/24     Static  60   0     RD    203.0.113.2     GE0/0/1'),
                        'palo-alto': ('show routing route', '198.51.100.0/24     203.0.113.2      10      A S    ethernet1/2')}
        for model, (command, expected) in expectations.items():
            with self.subTest(model=model):
                lab = router_chain_example(KERNEL, DISK)
                lab['nodes'][0]['model'] = model
                if model == 'palo-alto':
                    lab['nodes'][0].update(role='firewall', firewall={'default': 'drop', 'stateful': True, 'rules': [], 'nat': []})
                node = validate(lab)['nodes'][0]
                self.assertIn(expected, vendor_show.show(node, observed(node), command))

    def test_vlan_brief_lists_access_ports_and_trunks(self):
        lab = switch_vlan_example(KERNEL, DISK)
        lab['nodes'][0]['model'] = 'cisco-9200l'
        node = validate(lab)['nodes'][0]
        replies = {'addresses': '', 'routes': '', 'bridge-vlans': VLANS}
        text = vendor_show.show(node, observed(node, replies), 'show vlan brief')
        self.assertRegex(text, r'10\s+VLAN0010\s+active\s+Gi1/0/1, Gi1/0/2\n')  # as IOS writes them
        self.assertNotIn('Gi1/0/4', text)  # the trunk: listed by show interfaces trunk, not here
        self.assertIn('1002 fddi-default                     act/unsup', text)

    def test_unknown_commands_list_the_supported_ones(self):
        _, node = router('cisco-isr4331')
        with self.assertRaisesRegex(ValueError, 'show ip route'):
            vendor_show.show(node, observed(node), 'show running-config')
        with self.assertRaisesRegex(ValueError, 'switch'):
            vendor_show.show(node, observed(node), 'show vlan brief')


def replies(pattern):
    ok = {'ok': True, 'ttl': 62, 'time_ms': 0.612}
    lost = {'ok': False, 'ttl': None, 'time_ms': None}
    return {'destination': '198.51.100.20', 'replies': [dict(ok if c == '!' else lost, sequence=i) for i, c in enumerate(pattern)]}


class PingTest(unittest.TestCase):
    def test_each_vendor_ping_syntax(self):
        cases = {'cisco-isr4331': 'ping 198.51.100.20', 'arista-7280r': 'ping 198.51.100.20', 'huawei-ar6120': 'ping 198.51.100.20',
                 'juniper-mx204': 'ping 198.51.100.20 count 5', 'fortigate': 'execute ping 198.51.100.20',
                 'mikrotik-ccr': '/ping address=198.51.100.20', 'palo-alto': 'ping host 198.51.100.20'}
        for model, command in cases.items():
            with self.subTest(model=model):
                self.assertEqual(vendor_show.ping_destination({'model': model}, command), '198.51.100.20')
        self.assertIsNone(vendor_show.ping_destination({'model': 'fortigate'}, 'ping 198.51.100.20'))
        self.assertIsNone(vendor_show.ping_destination({'model': 'cisco-isr4331'}, 'show ip route'))
        with self.assertRaises(ValueError):
            vendor_show.ping_destination({'model': 'cisco-isr4331'}, 'ping 198.51.100.300')

    def test_echo_reply_reads_busybox_and_iputils(self):
        self.assertEqual(vendor_show.echo_reply(0, '64 bytes from 198.51.100.20: seq=0 ttl=62 time=0.612 ms'),
                         {'ok': True, 'ttl': 62, 'time_ms': 0.612})
        self.assertEqual(vendor_show.echo_reply(0, '64 bytes from 198.51.100.20: icmp_seq=1 ttl=63 time=0.051 ms')['ttl'], 63)
        self.assertFalse(vendor_show.echo_reply(1, '1 packets transmitted, 0 packets received')['ok'])

    def test_vendor_layouts(self):
        ios = vendor_show.ping_text({'model': 'cisco-isr4331'}, replies('!!!!.'))
        self.assertIn('!!!!.', ios)
        self.assertIn('Success rate is 80 percent (4/5)', ios)
        self.assertIn('Success rate is 0 percent (0/5)', vendor_show.ping_text({'model': 'cisco-isr4331'}, replies('.....')))
        self.assertIn('20.00% packet loss', vendor_show.ping_text({'model': 'huawei-ar6120'}, replies('!!!!.')))
        self.assertIn('sent=5 received=4 packet-loss=20%', vendor_show.ping_text({'model': 'mikrotik-ccr'}, replies('!!!!.')))
        self.assertIn('Request timeout for icmp_seq 4', vendor_show.ping_text({'model': 'juniper-mx204'}, replies('!!!!.')))


class BridgeTest(unittest.TestCase):
    def test_ping_needs_a_node_and_an_ipv4_destination(self):
        envelope = {'id': '0' * 32, 'owner_uid': os.geteuid(), 'action': 'ping', 'target': 'lab', 'lab': 'lab', 'node': 'R1',
                    'destination': '198.51.100.20'}
        self.assertEqual(ui_bridge.validate_request(envelope)['destination'], '198.51.100.20')
        for wrong in ('VM3', None, '198.51.100.300'):
            with self.assertRaises(ValueError):
                ui_bridge.validate_request(dict(envelope, destination=wrong))

    def test_show_needs_a_node(self):
        envelope = {'id': '0' * 32, 'owner_uid': os.geteuid(), 'action': 'show', 'target': 'lab', 'lab': 'lab', 'node': 'R1',
                    'destination': None}
        self.assertEqual(ui_bridge.validate_request(envelope)['action'], 'show')
        with self.assertRaises(ValueError):
            ui_bridge.validate_request(dict(envelope, node=None))


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class WorkbenchShowTest(unittest.TestCase):
    def test_show_asks_the_running_lab_once_then_formats_locally(self):
        import tkinter as tk
        from network_labs.__main__ import App
        root = tk.Tk()
        try:
            window = App(root).open_native_lab()
            lab, node = router('cisco-isr4331')
            window.load_spec(lab)
            window.view_lab = lab['name']
            window.choose_node('R1')
            window.load_config(force=True)
            self.assertFalse(window.run_vendor_show())
            self.assertIn('Démarrer', window.vendor_message.get())
            window.states = {'R1': {'status': 'running'}}
            with patch.object(window, 'launch', return_value=True) as launch:
                window.vendor_command.set('show ip route')
                self.assertTrue(window.run_vendor_show())
                launch.assert_called_once_with('show')
            request = {'action': 'show', 'lab': lab['name'], 'node': 'R1'}
            window.apply_response({'ok': True, 'action': 'show', 'lab': lab['name'], 'topology': ui_bridge.public_topology(lab),
                                   'data': observed(node)}, request)
            self.assertIn('R1# show ip route', window.output.get('1.0', 'end'))
            window.states = {'R1': {'status': 'running'}}
            with patch.object(window, 'launch', side_effect=AssertionError('observed again')):
                window.vendor_command.set('sh ip int br')
                self.assertTrue(window.run_vendor_show())
            self.assertIn('GigabitEthernet0/0/0', window.output.get('1.0', 'end'))
            with patch.object(window, 'launch', return_value=True) as launch:
                window.vendor_command.set('ping 198.51.100.20')
                self.assertTrue(window.run_vendor_show())
                launch.assert_called_once_with('ping')
            self.assertEqual(window.vendor_ping_destination, '198.51.100.20')
            request = {'action': 'ping', 'lab': lab['name'], 'node': 'R1'}
            window.apply_response({'ok': True, 'action': 'ping', 'lab': lab['name'], 'topology': ui_bridge.public_topology(lab),
                                   'data': replies('!!!!!')}, request)
            self.assertIn('R1# ping 198.51.100.20', window.output.get('1.0', 'end'))
            self.assertIn('Success rate is 100 percent (5/5)', window.output.get('1.0', 'end'))
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
