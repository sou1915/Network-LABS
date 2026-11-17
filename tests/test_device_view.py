"""Device pages: the device summary, the portal's device images and script, and the GUI tab header."""
import json
import os
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from network_labs.appliances import device_view
from network_labs.appliances.microvm import firewall_nat_example, router_on_a_stick_example, switch_vlan_example
from network_labs.appliances.spec import validate

KERNEL, DISK = '/assets/vmlinux', '/assets/guest.ext4'


def modelled(lab, name, model):
    next(n for n in lab['nodes'] if n['name'] == name)['model'] = model
    lab = validate(lab)
    return lab, next(n for n in lab['nodes'] if n['name'] == name)


class SummaryTest(unittest.TestCase):
    def test_firewall_ports_neighbours_and_spare_model_ports(self):
        lab, node = modelled(firewall_nat_example(KERNEL, DISK), 'FW1', 'fortigate')
        info = device_view.summary(lab, node)
        self.assertEqual((info['brand'], info['cli'], info['art']), ('Fortinet', 'FortiOS', 'firewall'))
        self.assertEqual([(p['name'], p['peer']) for p in info['ports']], [('port1', 'VM2 · eth0'), ('port2', 'VM3 · eth0')])
        self.assertEqual(info['spare'][:2], ['port3', 'port4'])

    def test_switch_access_and_trunk_ports(self):
        lab, node = modelled(switch_vlan_example(KERNEL, DISK), 'SW1', 'cisco-9200l')
        ports = {p['name']: p for p in device_view.summary(lab, node)['ports']}
        self.assertEqual(ports['gi1/0/1']['detail'], 'VLAN 10')
        self.assertTrue(ports['gi1/0/4']['trunk'])
        self.assertEqual(ports['gi1/0/4']['detail'], 'Trunk 10,20')

    def test_router_on_a_stick_lists_subinterfaces_and_connected_networks(self):
        lab, node = modelled(router_on_a_stick_example(KERNEL, DISK), 'R1', 'cisco-isr4331')
        info = device_view.summary(lab, node)
        self.assertEqual(info['ports'][0]['detail'], '802.1Q ×2')
        self.assertEqual({s['name'] for s in info['subinterfaces']}, {'gi0/0/0.10', 'gi0/0/0.20'})
        self.assertEqual({c['port'] for c in info['connected']}, {'gi0/0/0.10', 'gi0/0/0.20'})

    def test_generic_node(self):
        lab = firewall_nat_example(KERNEL, DISK)
        info = device_view.summary(lab, lab['nodes'][0])
        self.assertEqual((info['brand'], info['cli'], info['spare']), ('Linux', None, []))


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class PortalAndHeaderTest(unittest.TestCase):
    def test_device_pages_assets_and_header(self):
        import tkinter as tk
        import webbrowser
        from network_labs.__main__ import App
        from network_labs.web_portal import WebPortal
        from network_labs.appliances.web_management import NativeDeviceAPI
        root = tk.Tk()
        try:
            with patch.object(webbrowser, 'open', return_value=True):
                window = App(root).open_native_lab()
                lab, _ = modelled(firewall_nat_example(KERNEL, DISK), 'FW1', 'fortigate')
                window.load_spec(lab)
                window.choose_node('FW1')
                window.load_config(force=True)
                root.update()
                texts = [window.device_header.itemcget(i, 'text') for i in window.device_header.find_all()
                         if window.device_header.type(i) == 'text']
                self.assertIn('FW1', texts)
                self.assertTrue(any('Fortinet' in t for t in texts))
                portal = WebPortal(window, api=NativeDeviceAPI(window), native=True)
                try:
                    with urllib.request.urlopen(portal.origin + '/devices/firewall@175.png') as response:
                        self.assertEqual(response.headers['Content-Type'], 'image/png')
                    with urllib.request.urlopen(portal.origin + '/native_device_view.js') as response:
                        self.assertIn(b'Face avant', response.read())
                    for bad in ('/devices/..%2Fui.py', '/devices/router.png', '/devices/router@100.png/../x'):
                        with self.assertRaises(urllib.error.HTTPError):
                            urllib.request.urlopen(portal.origin + bad)
                    state = NativeDeviceAPI(window).dispatch('state', {'node': 'FW1'})
                    self.assertEqual(state['device']['port_names'], {'eth0': 'port1', 'eth1': 'port2'})
                    json.dumps(state)
                finally:
                    portal.close()
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()


SESSIONS = ('ipv4     2 icmp     1 27 src=192.0.2.20 dst=198.51.100.20 type=8 code=0 id=41 src=198.51.100.20 dst=192.0.2.20 type=0 '
            'code=0 id=41 mark=0 use=2\n'
            'ipv4     2 tcp      6 431996 ESTABLISHED src=192.0.2.20 dst=198.51.100.20 sport=51514 dport=443 src=198.51.100.20 '
            'dst=198.51.100.1 sport=443 dport=51514 [ASSURED] mark=0 use=1\n'
            'udp      17 21 src=192.0.2.20 dst=198.51.100.20 sport=40021 dport=53 [UNREPLIED] src=198.51.100.20 dst=198.51.100.1 '
            'sport=53 dport=40021 mark=0 use=1\n')
ADDRESSES = ('1: lo: <LOOPBACK,UP>\n    inet 127.0.0.1/8 scope host lo\n2: eth0: <BROADCAST,UP>\n    inet 192.0.2.1/24 scope global eth0\n'
             '3: eth1: <BROADCAST,UP>\n    inet 203.0.113.1/30 scope global eth1\n')


class LiveViewTest(unittest.TestCase):
    def test_sessions_keep_the_original_direction(self):
        from network_labs.appliances.vendor_show import parse_sessions
        sessions = parse_sessions(SESSIONS)
        self.assertEqual([(s['protocol'], s['source'], s['destination'], s['port']) for s in sessions],
                         [('icmp', '192.0.2.20', '198.51.100.20', ''), ('tcp', '192.0.2.20', '198.51.100.20', '443'),
                          ('udp', '192.0.2.20', '198.51.100.20', '53')])
        self.assertEqual(sessions[1]['state'], 'ESTABLISHED')
        self.assertFalse(sessions[2]['replied'])

    def test_missing_route_and_extra_vlan_are_reported(self):
        from network_labs.appliances.microvm import router_chain_example
        from network_labs.appliances.vendor_show import observe_guest
        lab = router_chain_example(KERNEL, DISK)
        router = lab['nodes'][0]
        observed = observe_guest(lambda op: {'addresses': ADDRESSES, 'routes': '192.0.2.0/24 dev eth0 scope link\n'
                                             '10.9.0.0/16 via 203.0.113.2 dev eth1\n'}[op], router)
        view = device_view.live(lab, router, observed)
        self.assertTrue(all(i['ok'] for i in view['interfaces']))
        self.assertEqual({(r['network'], r['state']) for r in view['routes']},
                         {('198.51.100.0/24', 'absente'), ('10.9.0.0/16', 'non déclarée')})
        self.assertFalse(view['conform'])
        lab, switch = modelled(switch_vlan_example(KERNEL, DISK), 'SW1', 'cisco-9200l')
        listing = 'eth0 10 pvid untagged\neth1 10 pvid untagged\neth2 20 pvid untagged\neth3 1 pvid untagged\neth3 10\neth3 20\neth0 30\n'
        observed = observe_guest(lambda op: {'addresses': '', 'routes': '', 'bridge-vlans': listing}[op], switch)
        states = {(v['port'], v['vlan'], v['state']) for v in device_view.live(lab, switch, observed)['vlans']}
        self.assertIn(('gi1/0/1', 30, 'non déclarée'), states)
        self.assertIn(('gi1/0/4', 20, 'ok'), states)


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class ObserveActionTest(unittest.TestCase):
    def test_observe_needs_a_running_node_then_launches_one_show(self):
        import tkinter as tk
        from network_labs.__main__ import App
        from network_labs.appliances.web_management import NativeDeviceAPI
        from network_labs.appliances.ui_bridge import public_topology
        from network_labs.appliances.vendor_show import observe_guest
        root = tk.Tk()
        try:
            window = App(root).open_native_lab()
            lab, node = modelled(firewall_nat_example(KERNEL, DISK), 'FW1', 'fortigate')
            window.load_spec(lab)
            api = NativeDeviceAPI(window)
            with self.assertRaisesRegex(ValueError, 'Démarrer'):
                api.dispatch('observe', {'node': 'FW1'})
            window.view_lab = lab['name']
            window.states = {'FW1': {'status': 'running'}}
            with patch.object(window, 'launch', return_value=True) as launch:
                api.dispatch('observe', {'node': 'FW1'})
                launch.assert_called_once_with('show')
            self.assertIsNone(api.dispatch('state', {'node': 'FW1'})['live'])
            data = observe_guest(lambda op: {'addresses': ADDRESSES.replace('203.0.113.1/30', '198.51.100.1/24'), 'routes': ''}[op], node)
            data['sessions'] = []
            window.apply_response({'ok': True, 'action': 'show', 'lab': lab['name'], 'topology': public_topology(lab), 'data': data},
                                  {'action': 'show', 'lab': lab['name'], 'node': 'FW1'})
            live = api.dispatch('state', {'node': 'FW1'})['live']
            self.assertTrue(live['conform'])
            self.assertEqual(live['sessions'], [])
            self.assertIn('Relevé de FW1', window.output.get('1.0', 'end'))
        finally:
            root.destroy()
