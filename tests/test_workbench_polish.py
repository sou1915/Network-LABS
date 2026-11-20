"""The workbench's drawing and the device pages: every device gets its own place (cabled groups as trees, devices without
a cable in a row below, never on top of another), the drawing is saved with the project and comes back as it was left,
and a PC's desktop sets its IP configuration (DHCP, or a static address and gateway) in the project."""
import copy
import json
import unittest

from network_labs.appliances import topology_edit
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_bridge import public_topology
from network_labs.appliances.ui_quick import blank_project
from network_labs.appliances.web_management import NativeDeviceAPI
from network_labs.appliances.workspace_art import auto_layout, layout_bounds
from network_labs.web_portal import WebPortal


def agency():
    spec = blank_project('agence')
    add = lambda spec, **k: topology_edit.add_microvm_node(spec, kernel='/k', disk='/d', **k)
    spec = add(spec, name='FW1', role='firewall', ports=3, model='fortigate', addresses='203.0.113.2/30,192.168.10.1/24,10.0.50.1/24')
    spec = add(spec, name='R1', role='router', ports=2, model='cisco-isr4331', addresses='203.0.113.1/30,198.51.100.1/24')
    spec = add(spec, name='SW1', role='switch', ports=8, model='cisco-2960')
    for name, address in (('PC1', '192.168.10.10/24'), ('PC2', '192.168.10.11/24')):
        spec = add(spec, name=name, role='host', ports=1, model='windows-11', addresses=address)
    spec = add(spec, name='SRV1', role='host', ports=1, model='server-windows', addresses='10.0.50.10/24')
    for name, model in (('ASA', 'cisco-asa'), ('PFS', 'pfsense'), ('PAN', 'palo-alto')):  # added, not cabled yet
        spec = add(spec, name=name, role='firewall', ports=3, model=model)
    for a, b in ((('FW1', 'eth0'), ('R1', 'eth0')), (('FW1', 'eth1'), ('SW1', 'eth0')), (('PC1', 'eth0'), ('SW1', 'eth1')),
                 (('PC2', 'eth0'), ('SW1', 'eth2')), (('FW1', 'eth2'), ('SRV1', 'eth0'))):
        spec = topology_edit.connect(spec, a, b)
    return validate(spec)


class LayoutTest(unittest.TestCase):
    def test_every_device_has_its_own_place(self):
        graph = public_topology(agency())
        positions = auto_layout(graph, {}, 900)
        self.assertEqual(set(positions), {n['name'] for n in graph['nodes']})
        points = list(positions.values())
        for i, (x, y) in enumerate(points):  # no two devices closer than a device's width (the old layout stacked them)
            for xx, yy in points[i + 1:]:
                self.assertTrue(abs(x - xx) >= 110 or abs(y - yy) >= 110, (x, y, xx, yy))
        cabled_bottom = max(positions[n][1] for n in ('FW1', 'R1', 'SW1', 'PC1', 'PC2', 'SRV1'))
        self.assertTrue(all(positions[n][1] > cabled_bottom for n in ('ASA', 'PFS', 'PAN')))  # waiting below, in a row
        self.assertEqual(len({positions[n][1] for n in ('ASA', 'PFS', 'PAN')}), 1)
        self.assertLess(positions['FW1'][1], positions['SW1'][1])
        self.assertLess(positions['SW1'][1], positions['PC1'][1])  # a tree: firewall, its switch, the switch's PCs
        x1, y1, x2, y2 = layout_bounds(graph, positions)
        self.assertTrue(x1 < min(x for x, _ in points) and y2 > max(y for _, y in points))

    def test_the_layout_is_kept_in_the_project(self):
        spec = dict(agency(), layout={'FW1': [120, 90.25], 'GONE': [1, 1]})
        self.assertEqual(validate(spec)['layout'], {'FW1': [120.0, 90.2]})  # a device no longer in the lab is dropped
        for bad in ({'FW1': [1]}, {'FW1': ['a', 2]}, ['FW1']):
            with self.subTest(layout=bad), self.assertRaises(ValueError):
                validate(dict(agency(), layout=bad))


class FakeRoot:
    def after(self, delay, callback, *args):
        return None

    def after_cancel(self, job):
        pass


class Workbench:
    def __init__(self):
        self.root = FakeRoot()
        self.spec = agency()
        self.view_lab, self.states, self.pending, self.positions, self.config_key = self.spec['name'], {}, None, {}, None
        self.events, self.opened = [], []

    def manifest(self):
        return copy.deepcopy(self.spec)

    def editing_spec(self):
        return self.manifest()

    def commit_edit(self, spec):
        self.spec = validate(spec)

    def choose_node(self, name):
        self.selected = name

    def load_config(self, force=False):
        pass

    def record_event(self, *args):
        self.events.append(args)

    def open_cli(self, name):
        self.opened.append(name)


class DesktopTest(unittest.TestCase):
    def setUp(self):
        self.app = Workbench()
        self.api = NativeDeviceAPI(self.app)

    def ip(self, **values):
        revision = self.api.dispatch('state', {'node': 'PC1'})['revision']
        return self.api.dispatch('host_ip', dict({'node': 'PC1', 'revision': revision, 'port': 'eth0'}, **values))

    def pc(self):
        return next(n for n in self.app.spec['nodes'] if n['name'] == 'PC1')

    def test_state_carries_the_running_configuration_of_vendor_devices(self):
        # The product pages show the device's configuration in its own syntax; a PC has none.
        self.assertIsNone(self.api.dispatch('state', {'node': 'PC1'})['config_text'])

    def test_static_then_dhcp(self):
        state = self.ip(mode='static', address='192.168.10.50/24', gateway='192.168.10.1')
        self.assertEqual(state['node']['interfaces']['eth0'], '192.168.10.50/24')
        self.assertEqual(self.pc()['gateway'], '192.168.10.1')
        self.ip(mode='dhcp', address='', gateway='')
        self.assertEqual((self.pc()['interfaces']['eth0'], self.pc()['dhcp_clients'], self.pc().get('gateway')), ('', ['eth0'], None))
        self.ip(mode='static', address='192.168.10.51/24', gateway='')
        self.assertEqual(self.pc().get('dhcp_clients') or [], [])

    def test_checks(self):
        for address, gateway in (('192.168.10.50', ''), ('192.168.10.0/24', ''), ('192.168.10.50/24', '10.0.0.1'),
                                 ('192.168.10.50/24', '192.168.10.50'), ('nope/24', '')):
            with self.subTest(address=address, gateway=gateway), self.assertRaises(ValueError):
                self.ip(mode='static', address=address, gateway=gateway)
        with self.assertRaises(ValueError):
            self.api.dispatch('host_ip', {'node': 'SW1', 'revision': 'x', 'port': 'eth0', 'mode': 'dhcp', 'address': '', 'gateway': ''})

    def test_a_running_pc_gets_the_change_typed_in_its_console(self):
        from unittest.mock import patch
        self.ip(mode='static', address='192.168.10.50/24', gateway='192.168.10.1')
        self.app.states = {'PC1': {'status': 'running'}}
        typed = []
        reply = lambda lab, payload, timeout=6: typed.append(payload.get('text')) or {'ok': True, 'reply': '', 'prompt': '$ '}
        with patch('network_labs.appliances.console_server.request', side_effect=reply):
            state = self.ip(mode='static', address='192.168.10.60/24', gateway='192.168.10.254')
        self.assertEqual(state['ip_live'], 'appliqué')
        self.assertEqual([t for t in typed if t], ['ip route del default via 192.168.10.1', 'ip addr del 192.168.10.50/24 dev eth0',
                                                   'ip addr add 192.168.10.60/24 dev eth0', 'ip route add default via 192.168.10.254'])
        refused = lambda lab, payload, timeout=6: {'ok': True, 'reply': '% eth0 a déjà 1.2.3.4/24', 'prompt': '$ '}
        with patch('network_labs.appliances.console_server.request', side_effect=refused):
            self.assertIn('refusé', self.ip(mode='static', address='192.168.10.61/24', gateway='')['ip_live'])
        self.assertIsNone(Workbench().states.get('PC1'))

    def test_the_command_prompt_opens_the_device_terminal(self):
        self.assertEqual(self.api.dispatch('open_cli', {'node': 'PC1'}), {'opened': 'PC1'})
        self.assertEqual(self.app.opened, ['PC1'])

    def test_the_portal_serves_the_desktop_and_accepts_its_actions(self):
        portal = WebPortal(self.app, api=self.api, native=True)
        try:
            import http.client
            connection = http.client.HTTPConnection(portal.host)
            connection.request('GET', '/native_desktop.js', headers={'Host': portal.host})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b'Configuration IP', response.read())
            connection.request('GET', '/', headers={'Host': portal.host})
            page = connection.getresponse().read()
            self.assertIn(b'/native_desktop.js', page)
            self.assertIn(b'/native_vendor.js', page)  # the firewall vendors' faces (ASDM, pfSense, PAN-OS…)
            connection.request('GET', '/native_vendor.js', headers={'Host': portal.host})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            script = response.read()
            self.assertTrue(all(word in script for word in (b'Access Rules', b'Firewall Rules', b'Security Policy Rules')))
            self.assertIn(b'/native_simple.js', page)  # the « Simple » design, chosen per browser beside the vendor one
            connection.request('GET', '/native_simple.js', headers={'Host': portal.host})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            script = response.read()
            self.assertTrue(all(word in script for word in (b'network-labs-design', b'/api/host_ip', b"section: 'switching'")))
            self.assertIn(b'/native_studio.js', page)  # the dark « Studio » look, loaded before the page that uses it
            self.assertLess(page.index(b'/native_studio.js'), page.index(b'/native_simple.js'))
            connection.request('GET', '/native_studio.js', headers={'Host': portal.host})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            studio = response.read()
            self.assertTrue(all(word in studio for word in (b'window.nlStudio', b'.sd-app.st', b'body.stb')))
        finally:
            portal.close()


if __name__ == '__main__':
    unittest.main()
