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
        self.assertIn('S        198.51.100.0/24 [1/0] via 203.0.113.2, gi0/0/1', text)
        self.assertIn('C        192.0.2.0/24 is directly connected, gi0/0/0', text)
        self.assertIn('Gateway of last resort is not set', text)
        brief = vendor_show.show(node, observed(node), 'show ip interface brief')
        self.assertRegex(brief, r'gi0/0/1\s+203\.0\.113\.1\s+YES manual up\s+up')

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
        self.assertRegex(text, r'10\s+VLAN0010\s+active\s+gi1/0/1, gi1/0/2')
        self.assertIn('Trunks (802.1Q) : gi1/0/4', text)

    def test_unknown_commands_list_the_supported_ones(self):
        _, node = router('cisco-isr4331')
        with self.assertRaisesRegex(ValueError, 'show ip route'):
            vendor_show.show(node, observed(node), 'show running-config')
        with self.assertRaisesRegex(ValueError, 'switch'):
            vendor_show.show(node, observed(node), 'show vlan brief')


class BridgeTest(unittest.TestCase):
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
            self.assertIn('gi0/0/0', window.output.get('1.0', 'end'))
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
