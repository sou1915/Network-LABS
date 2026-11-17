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
