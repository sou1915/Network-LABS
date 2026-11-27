"""Several DHCP pools on one router micro-VM: one « ip dhcp pool » per LAN or VLAN (router-on-a-stick subinterfaces), from
the IOS lines to the running-config, the network model's leases, the guest's udhcpd daemons at boot and live, and the
agent serving both pools for real between network namespaces."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances import microvm, network_model, vendor_config
from network_labs.appliances.dhcp import pools
from network_labs.appliances.spec import validate

POOLS = '''ip dhcp excluded-address 192.0.2.1 192.0.2.9
ip dhcp excluded-address 198.51.100.1 198.51.100.49
ip dhcp pool VLAN10
 network 192.0.2.0 255.255.255.0
 default-router 192.0.2.1
 dns-server 192.0.2.53
ip dhcp pool VLAN20
 network 198.51.100.0 255.255.255.0
 default-router 198.51.100.1
 lease 0 8
'''


def stick(folder):
    """Router-on-a-stick: R1 (a Cisco ISR) routes VLAN 10 and VLAN 20 on eth0.10 and eth0.20; VM1 and VM2 ask for leases."""
    (Path(folder) / 'k').write_bytes(b'k')
    (Path(folder) / 'r').write_bytes(b'r')
    spec = microvm.router_on_a_stick_example(Path(folder) / 'k', Path(folder) / 'r')
    for node in spec['nodes']:
        if node['name'] in ('VM1', 'VM2'):
            node.update(interfaces={'eth0': ''}, gateway='', dhcp_clients=['eth0'])
        if node['name'] == 'R1':
            node['model'] = 'cisco-isr4331'
    return validate(spec)


def router(spec):
    return next(n for n in spec['nodes'] if n['name'] == 'R1')


class PoolsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.spec = vendor_config.apply(stick(self.folder.name), 'R1', POOLS)

    def test_one_pool_per_vlan_from_the_ios_lines(self):
        r1 = router(self.spec)
        self.assertEqual([(p['name'], p['interface'], p['start'], p['end']) for p in pools(r1)],
                         [('VLAN10', 'eth0.10', '192.0.2.10', '192.0.2.254'), ('VLAN20', 'eth0.20', '198.51.100.50', '198.51.100.254')])
        self.assertEqual((r1['dhcp_server']['dns'], r1['dhcp_extra'][0]['lease_seconds']), (['192.0.2.53'], 28800))

    def test_running_config_prints_every_pool_and_reads_back_the_same(self):
        text = vendor_config.render(self.spec, 'R1')
        self.assertIn('ip dhcp excluded-address 192.0.2.1 192.0.2.9\nip dhcp excluded-address 198.51.100.1 198.51.100.49\n!\n'
                      'ip dhcp pool VLAN10\n network 192.0.2.0 255.255.255.0\n default-router 192.0.2.1\n dns-server 192.0.2.53\n'
                      ' lease 1 0 0\n!\nip dhcp pool VLAN20\n network 198.51.100.0 255.255.255.0\n default-router 198.51.100.1\n'
                      ' lease 0 8 0\n!', text)
        lines = [line for line in text.splitlines() if line.startswith(('ip dhcp', ' network', ' default-router', ' dns-server', ' lease'))]
        again = vendor_config.apply(stick(self.folder.name), 'R1', '\n'.join(lines))
        self.assertEqual(pools(router(again)), pools(router(self.spec)))

    def test_editing_and_removing_a_pool_by_name(self):
        edited = vendor_config.apply(self.spec, 'R1', 'ip dhcp pool VLAN20\n dns-server 198.51.100.53')
        self.assertEqual([p['dns'] for p in pools(router(edited))], [['192.0.2.53'], ['198.51.100.53']])
        self.assertEqual(pools(router(edited))[1]['start'], '198.51.100.50')  # no exclusion restated: the range stays
        removed = vendor_config.apply(self.spec, 'R1', 'no ip dhcp pool VLAN20')
        self.assertEqual([p['name'] for p in pools(router(removed))], ['VLAN10'])
        self.assertNotIn('dhcp_extra', router(removed))
        first = vendor_config.apply(self.spec, 'R1', 'no ip dhcp pool VLAN10')
        self.assertEqual(router(first)['dhcp_server']['name'], 'VLAN20')  # the other pool moves up

    def test_two_pools_for_one_lan_are_refused_a_new_name_replaces_an_old_pool(self):
        with self.assertRaisesRegex(ValueError, 'un pool par interface'):
            vendor_config.apply(self.spec, 'R1',
                                'ip dhcp pool A\n network 192.0.2.0 255.255.255.0\nip dhcp pool B\n network 192.0.2.0 255.255.255.0')
        renamed = vendor_config.apply(self.spec, 'R1', 'ip dhcp pool USERS\n network 198.51.100.0 255.255.255.0')
        self.assertEqual([p['name'] for p in pools(router(renamed))], ['VLAN10', 'USERS'])

    def test_each_vlan_host_gets_a_lease_from_its_own_pool(self):
        leases = network_model.Model(self.spec).leases
        self.assertEqual({name: (str(lease), str(gateway)) for (name, _), (lease, gateway) in leases.items()},
                         {'VM1': ('192.0.2.10/24', '192.0.2.1'), 'VM2': ('198.51.100.50/24', '198.51.100.1')})

    def test_validation(self):
        r1 = router(self.spec)
        for extra, message in (([r1['dhcp_extra'][0]] * 8, 'seven'), ([dict(r1['dhcp_server'], name='OTHER')], 'one pool per interface'),
                               ([dict(r1['dhcp_extra'][0], name='VLAN10')], 'own name')):
            spec = copy.deepcopy(self.spec)
            router(spec)['dhcp_extra'] = extra
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                validate(spec)
        spec = copy.deepcopy(self.spec)
        router(spec)['dhcp_server'] = None
        with self.assertRaisesRegex(ValueError, 'first pool in dhcp_server'):
            validate(spec)

    def test_boot_starts_one_server_per_pool_and_a_live_change_restarts_only_the_changed_one(self):
        from network_labs.appliances import guest_startup
        calls = []
        def fake(socket, operation, **kw):
            calls.append((operation, kw.get('interface'), kw.get('dhcp')))
            return {'forwarding': '1\n',
                    'dhcp-leases': 'Mac Address       IP Address      Host Name           Expires in\n'}.get(operation, '')
        with patch.object(guest_startup, 'query', side_effect=fake), \
                patch.object(guest_startup, 'observe', return_value={'addresses': [], 'routes': []}):
            guest_startup.apply('/socket', router(self.spec))
        served = [(c[1], c[2]['start'], c[2]['netmask']) for c in calls if c[0] == 'dhcp-serve']
        self.assertEqual(served, [('eth0.10', '192.0.2.10', 24), ('eth0.20', '198.51.100.50', 24)])
        self.assertEqual({c[1] for c in calls if c[0] == 'dhcp-leases'}, {'eth0.10', 'eth0.20'})
        calls.clear()
        edited = vendor_config.apply(self.spec, 'R1', 'ip dhcp pool VLAN20\n dns-server 198.51.100.53')
        with patch.object(guest_startup, 'query', side_effect=fake):
            guest_startup._dhcp_servers('/socket', router(self.spec), router(edited))
        self.assertEqual([c[:2] for c in calls if c[0] != 'dhcp-leases'], [('dhcp-stop', 'eth0.20'), ('dhcp-serve', 'eth0.20')])
        calls.clear()
        with patch.object(guest_startup, 'query', side_effect=fake):
            guest_startup._dhcp_servers('/socket', router(self.spec), router(vendor_config.apply(self.spec, 'R1',
                                                                                                 'no ip dhcp pool VLAN10')))
        self.assertEqual([c[:2] for c in calls], [('dhcp-stop', 'eth0.10')])
        from network_labs.appliances.guest_startup import LIVE_ROUTING
        self.assertTrue({'dhcp_server', 'dhcp_extra'} <= set(LIVE_ROUTING))

    def test_the_device_panel_lists_each_pool(self):
        from network_labs.appliances.device_view import features
        rows = [row['detail'] for row in features(router(self.spec)) if row['name'] == 'Serveur DHCP']
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].endswith('.10') and rows[1].endswith('.20'), rows)


@unittest.skipUnless(shutil.which('gcc') and shutil.which('ip') and os.geteuid() == 0 and Path('/bin/busybox').exists(),
                     'root, gcc, iproute2 and BusyBox required for the agent in network namespaces')
class AgentPoolsTest(unittest.TestCase):
    """The agent serves two pools on two router-on-a-stick interfaces (eth0.10, eth0.20), for real, and stops one live.

    Veth links carry the subinterface names here (a container kernel may lack 802.1Q); the VLAN tags themselves are proven
    by the real-KVM router-on-a-stick test."""

    @classmethod
    def setUpClass(cls):
        from network_labs.appliances.guest_control import _dhcp_command
        cls.folder = tempfile.TemporaryDirectory()
        root, agent = Path(cls.folder.name), Path('network_labs/appliances/guest/agent.c').resolve()
        (root / 'harness.c').write_text(f'#define main agent_main\n#include "{agent}"\n#undef main\nint main(int argc, char **argv) {{\n'
                                        '    int pipes[2]; if (argc != 2 || pipe(pipes)) return 2;\n'
                                        '    dprintf(pipes[1], "%s\\n", argv[1]); close(pipes[1]); serve(pipes[0], 1, 1); return 0;\n}\n')
        subprocess.run(['gcc', '-Wall', '-Wno-unused-function', '-o', str(root / 'h'), str(root / 'harness.c')], check=True)
        (root / 'bound.sh').write_text(f'#!/bin/sh\n[ "$1" = bound ] && echo "$interface $ip $router $dns" >> {root}/bound\nexit 0\n')
        (root / 'bound.sh').chmod(0o755)
        cls.root, tag = root, str(os.getpid())
        cls.spaces = (f'nlr{tag}', f'nlc{tag}')
        commands = [['ip', 'netns', 'add', cls.spaces[0]], ['ip', 'netns', 'add', cls.spaces[1]]]
        for vid, address in (('10', '192.0.2.1/24'), ('20', '198.51.100.1/24')):
            port = 'eth0.' + vid
            commands += [['ip', 'link', 'add', port, 'netns', cls.spaces[0], 'type', 'veth', 'peer', 'name', port, 'netns', cls.spaces[1]],
                         ['ip', '-n', cls.spaces[0], 'addr', 'add', address, 'dev', port],
                         ['ip', '-n', cls.spaces[0], 'link', 'set', port, 'up'], ['ip', '-n', cls.spaces[1], 'link', 'set', port, 'up']]
        try:
            for command in commands:
                subprocess.run(command, check=True, capture_output=True)
        except subprocess.CalledProcessError as error:
            cls.tearDownClass()
            raise unittest.SkipTest(f'network namespaces unavailable: {error.stderr.decode(errors="replace").strip()}')
        cls.serve = {port: _dhcp_command('dhcp-serve', port, pool) for port, pool in (
            ('eth0.10', {'start': '192.0.2.10', 'end': '192.0.2.20', 'netmask': 24, 'router': '192.0.2.1', 'lease_seconds': 3600,
                         'dns': ['192.0.2.53']}),
            ('eth0.20', {'start': '198.51.100.50', 'end': '198.51.100.60', 'netmask': 24, 'router': '198.51.100.1', 'lease_seconds': 600,
                         'dns': []}))}

    @classmethod
    def tearDownClass(cls):
        for port in ('eth0.10', 'eth0.20'):
            subprocess.run(['ip', 'netns', 'exec', cls.spaces[0], str(cls.root / 'h'), 'NL1 DHCP_STOP ' + port], capture_output=True)
            for suffix in ('conf', 'leases', 'pid'):
                Path(f'/run/udhcpd.{port}.{suffix}').unlink(missing_ok=True)
        for space in cls.spaces:
            subprocess.run(['ip', 'netns', 'del', space], capture_output=True)
        cls.folder.cleanup()

    def ask(self, request):
        out = subprocess.run(['ip', 'netns', 'exec', self.spaces[0], str(self.root / 'h'), 'NL1 ' + request], capture_output=True,
                             timeout=10).stdout
        header, _, body = out.partition(b'\n')
        return int(header.split()[1]), body.decode()

    def lease(self, port):
        subprocess.run(['ip', 'netns', 'exec', self.spaces[1], 'busybox', 'udhcpc', '-i', port, '-n', '-q', '-t', '5', '-T', '1',
                        '-s', str(self.root / 'bound.sh')], capture_output=True, timeout=30)
        bound = (self.root / 'bound').read_text().splitlines() if (self.root / 'bound').exists() else []
        return next((line.split() for line in reversed(bound) if line.startswith(port + ' ')), None)

    def test_two_pools_lease_and_one_stops_and_restarts_live(self):
        for port in ('eth0.10', 'eth0.20'):
            self.assertEqual(self.ask(self.serve[port]), (0, ''))
        time.sleep(.5)
        vlan10, vlan20 = self.lease('eth0.10'), self.lease('eth0.20')
        self.assertTrue(vlan10[1].startswith('192.0.2.') and vlan10[2:] == ['192.0.2.1', '192.0.2.53'], vlan10)
        self.assertTrue(vlan20[1].startswith('198.51.100.') and vlan20[2:] == ['198.51.100.1'], vlan20)
        self.assertIn(vlan20[1], self.ask('DHCP_LEASES eth0.20')[1])
        self.assertEqual(self.ask('DHCP_STOP eth0.20'), (0, ''))
        self.assertEqual(self.ask('DHCP_LEASES eth0.20'), (1, 'dhcp server not running'))
        self.assertEqual(self.ask('DHCP_STOP eth0.20'), (0, ''))  # stopping a stopped pool is fine
        self.assertIn(vlan10[1], self.ask('DHCP_LEASES eth0.10')[1])  # the other pool keeps serving
        self.assertEqual(self.ask(self.serve['eth0.20']), (0, ''))
        time.sleep(.5)
        self.assertIn(vlan20[1], self.ask('DHCP_LEASES eth0.20')[1])  # restarted, it keeps its bindings, as IOS does


if __name__ == '__main__':
    unittest.main()
