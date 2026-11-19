"""IOS DHCP relay typed in the routers' terminals: R2 serves 192.168.10.0/24, a LAN on none of its ports, and R1's
« ip helper-address » relays PC1's requests to it; the pool is served on the port the relayed requests arrive by."""
import unittest

from network_labs.appliances import guest_console, ios_relay, topology_edit
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.guest_startup import relay_command
from network_labs.appliances.network_model import Model
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project

POOL = ['en', 'conf t', 'ip dhcp excluded-address 192.168.10.1 192.168.10.9', 'ip dhcp pool LAN10', 'network 192.168.10.0 255.255.255.0',
        'default-router 192.168.10.1', 'exit', 'ip route 192.168.10.0 255.255.255.0 10.0.12.1', 'end']
HELPER = ['en', 'conf t', 'int g0/0/0', 'ip helper-address 10.0.12.2', 'end']


def lab(kernel='/k', disk='/d'):
    """PC1 (DHCP client) — R1 192.168.10.1 | 10.0.12.1 — R2 10.0.12.2 (its LAN 192.168.20.1 on its first port)."""
    spec = blank_project('ios-relay')
    spec = topology_edit.add_microvm_node(spec, name='R1', role='router', kernel=kernel, disk=disk, ports=2, model='cisco-isr4331',
                                          addresses='192.168.10.1/24,10.0.12.1/30')
    spec = topology_edit.add_microvm_node(spec, name='R2', role='router', kernel=kernel, disk=disk, ports=2, model='cisco-isr4331',
                                          addresses='192.168.20.1/24,10.0.12.2/30')
    spec = topology_edit.add_microvm_node(spec, name='PC1', role='host', kernel=kernel, disk=disk, ports=1, addresses='dhcp')
    spec = topology_edit.connect(spec, ('PC1', 'eth0'), ('R1', 'eth0'))
    return validate(topology_edit.connect(spec, ('R1', 'eth1'), ('R2', 'eth1')))


class IosRelayTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': lab()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def type(self, name, lines):
        console = guest_console.Console('ios-relay', name, lambda _: self.lab)
        return [console.line(line) for line in lines]

    def node(self, name):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == name)

    def test_a_relayed_pool_gives_the_remote_client_its_address(self):
        self.type('R2', POOL[:-2] + ['end'])  # the pool before any route: served on a port for now
        self.type('R2', ['en', 'conf t', POOL[-2], 'end'])
        server = self.node('R2')['dhcp_server']
        self.assertEqual({k: server[k] for k in ('interface', 'network', 'start', 'router')},
                         {'interface': 'eth1', 'network': '192.168.10.0/24', 'start': '192.168.10.10', 'router': '192.168.10.1'})
        self.assertIn('ip dhcp pool LAN10\n network 192.168.10.0 255.255.255.0', self.type('R2', ['en', 'sh run'])[-1])
        self.assertEqual(Model(self.box['spec']).leases, {})  # no relay yet: PC1's broadcasts stay on its LAN
        self.type('R1', HELPER)
        relay = ios_relay.process(self.node('R1'))
        self.assertEqual(relay, {'server': '10.0.12.2', 'clients': ['eth0']})
        self.assertEqual(relay_command(relay), 'network-labs-agent --dhcp-relay 10.0.12.2 eth0')
        lease, router = Model(self.box['spec']).leases[('PC1', 'eth0')]
        self.assertEqual((str(lease), str(router)), ('192.168.10.10/24', '192.168.10.1'))
        self.assertIn('inet 192.168.10.10/24', self.type('PC1', ['ip addr'])[0])
        self.assertIn('4 packets received', self.type('PC1', ['ping 10.0.12.2'])[0])
        self.assertRegex(self.type('R2', ['en', 'sh ip dhcp binding'])[-1], r'\n192\.168\.10\.10\s+\(projet\).*GigabitEthernet0/0/1$')
        self.assertIn('interface GigabitEthernet0/0/0\n ip address 192.168.10.1 255.255.255.0\n ip helper-address 10.0.12.2',
                      self.type('R1', ['en', 'sh run'])[-1])

    def test_without_the_route_back_the_server_cannot_answer(self):
        self.type('R2', POOL[:-2] + ['end'])
        self.type('R1', HELPER)
        self.assertEqual(Model(self.box['spec']).leases, {})

    def test_one_server_per_router(self):
        self.type('R1', HELPER)
        reply = self.type('R1', ['en', 'conf t', 'int g0/0/1', 'ip helper-address 10.9.9.9', 'end'])
        self.assertIn('une seule adresse de serveur DHCP', ' '.join(reply))


if __name__ == '__main__':
    unittest.main()
