"""Guided labs: each mission starts unsolved, its solution passes, and the policy evaluator follows iptables order."""
import os
import unittest

from network_labs.appliances import missions, vendor_config

SOLUTIONS = {
    'router-on-a-stick': ('R1', 'interface gi0/0/0.20\n encapsulation dot1Q 20'),
    'serveur-dhcp': ('R1', 'ip dhcp excluded-address 192.0.2.1 192.0.2.99\nip dhcp pool LAN\n network 192.0.2.0 255.255.255.0\n'
                           ' default-router 192.0.2.1'),
    'ospf-multi-constructeurs': ('R1', 'router ospf 1\n network 192.0.2.0 0.0.0.255 area 0\n network 203.0.113.0 0.0.0.3 area 0\n'
                                       ' passive-interface gi0/0/0'),
    'acl-invites': ('R1', 'ip access-list extended INVITES\n deny icmp 192.0.2.0 0.0.0.255 host 203.0.113.10\n'
                          ' permit ip any any\ninterface gi0/0\n ip access-group INVITES in'),
    'bgp-trois-operateurs': ('R1', 'router bgp 65001\n neighbor 203.0.113.2 remote-as 65002\n network 192.0.2.0 mask 255.255.255.0'),
    'route-manquante': ('R1', 'ip route 198.51.100.0 255.255.255.0 203.0.113.2'),
    'isoler-un-vlan': ('SW1', 'interface gi1/0/3\n switchport access vlan 20'),
    'publier-un-serveur': ('FW1', 'config firewall vip\n edit "srv"\n set extip 198.51.100.1\n set mappedip "192.0.2.20"\n'
                                  ' set extintf "port2"\n next\nend\nconfig firewall policy\n edit 2\n set name "srv-in"\n'
                                  ' set srcintf "port2"\n set dstintf "port1"\n set dstaddr "192.0.2.20/32"\n set service "ALL_ICMP"\n'
                                  ' set action accept\n next\nend'),
}


def setUpModule():
    # GUI tests record progress: keep it out of the real ~/.config.
    import tempfile
    from unittest import mock
    global _config, _env
    _config = tempfile.TemporaryDirectory()
    _env = mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': _config.name})
    _env.start()


def tearDownModule():
    _env.stop()
    _config.cleanup()


class MissionTest(unittest.TestCase):
    def test_every_mission_starts_unsolved_and_its_solution_passes_the_configuration_checks(self):
        self.assertEqual(set(SOLUTIONS), set(missions.BY_ID))
        for item in missions.MISSIONS:
            with self.subTest(mission=item['id']):
                lab = item['build']('/k', '/d')
                self.assertEqual(lab['name'], item['lab'])
                start = missions.grade(lab, item['id'])
                self.assertFalse(start['solved'])
                self.assertTrue(any(r['status'] == 'fail' for r in start['results']))
                node, text = SOLUTIONS[item['id']]
                solved = missions.grade(vendor_config.apply(lab, node, text), item['id'])
                self.assertTrue(all(r['status'] == 'ok' for r in solved['results'] if r['kind'] == 'configuration'), solved)
                self.assertTrue(all(r['status'] == 'pending' for r in solved['results'] if r['kind'] == 'réel'))
                real = {i: (True, 'ok') for i, c in enumerate(item['checks']) if c['kind'] in missions.REAL_KINDS}
                self.assertTrue(missions.grade(vendor_config.apply(lab, node, text), item['id'], real)['solved'])

    def test_policy_evaluation_order_dnat_and_default(self):
        lab = missions.BY_ID['publier-un-serveur']['build']('/k', '/d')
        node, text = SOLUTIONS['publier-un-serveur']
        firewall = next(n for n in vendor_config.apply(lab, node, text)['nodes'] if n['name'] == 'FW1')
        ping = {'in': 'eth1', 'source': '198.51.100.20', 'destination': '198.51.100.1', 'protocol': 'icmp'}
        self.assertEqual(missions.evaluate_policy(firewall, ping), 'accept')
        self.assertEqual(missions.evaluate_policy(firewall, dict(ping, protocol='tcp', dport=22)), 'drop')
        firewall['firewall']['rules'].insert(0, {'name': 'deny-first', 'in': 'eth1', 'action': 'drop', 'protocol': 'any'})
        self.assertEqual(missions.evaluate_policy(firewall, ping), 'drop')

    def test_unknown_mission(self):
        with self.assertRaises(ValueError):
            missions.mission('nope')


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class MissionTabTest(unittest.TestCase):
    def test_load_check_and_real_results(self):
        import tkinter as tk
        from unittest.mock import patch
        from network_labs.__main__ import App
        from network_labs.appliances.ui_bridge import public_topology, validate_request
        root = tk.Tk()
        try:
            window = App(root).open_native_lab()
            window.select_mission('route-manquante')
            self.assertFalse(window.load_mission())  # kernel and disk first
            window.mission_kernel.set('/k')
            window.mission_disk.set('/d')
            self.assertTrue(window.load_mission())
            self.assertEqual(window.manifest()['name'], 'mission-route-manquante')
            self.assertTrue(window.mission_score.get().startswith('0 / 3'))
            self.assertFalse(window.test_mission())  # the lab must run first
            window.commit_edit(vendor_config.apply(window.editing_spec(), *SOLUTIONS['route-manquante']))
            window.check_mission()
            self.assertTrue(window.mission_score.get().startswith('1 / 3'))
            spec = window.manifest()
            window.view_lab = spec['name']
            window.states = {n['name']: {'status': 'running'} for n in spec['nodes']}
            with patch.object(window, 'launch', return_value=True) as launch:
                self.assertTrue(window.test_mission())
                launch.assert_called_once_with('mission')
            window.apply_response({'ok': True, 'action': 'mission', 'lab': spec['name'], 'topology': public_topology(spec),
                                   'data': {'mission': 'route-manquante', 'results': [[1, True, '3/3'], [2, True, '3/3']]}},
                                  {'action': 'mission', 'lab': spec['name'], 'node': 'route-manquante'})
            self.assertIn('Mission réussie', window.mission_score.get())
            envelope = {'id': '0' * 32, 'owner_uid': os.geteuid(), 'action': 'mission', 'target': spec['name'], 'lab': spec['name'],
                        'node': 'route-manquante', 'destination': None}
            self.assertEqual(validate_request(envelope)['node'], 'route-manquante')
        finally:
            root.destroy()


class ProgressTest(unittest.TestCase):
    def test_best_score_solved_flag_hints_and_paths(self):
        import tempfile
        from unittest import mock
        from network_labs.appliances import progress
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': folder.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(progress.load(), {'missions': {}, 'paths': {}, 'seen': []})
        progress.record('route-manquante', 1, 3, hints=1)
        entry = progress.record('route-manquante', 3, 3, hints=2, solved=True)
        self.assertEqual((entry['best'], entry['solved'], entry['hints'], entry['tries']), (3, True, 2, 2))
        entry = progress.record('route-manquante', 1, 3, hints=0)  # a worse try keeps the best
        self.assertEqual((entry['best'], entry['solved'], entry['hints']), (3, True, 2))
        self.assertEqual(progress.record('route-manquante', 3, 3, hints=0, solved=True)['hints'], 0)
        progress.remember_paths('/k', '/d')
        self.assertEqual(progress.load()['paths'], {'kernel': '/k', 'disk': '/d'})
        self.assertEqual(oct(progress.path().stat().st_mode & 0o777), '0o600')
        progress.path().write_text('{broken')
        self.assertEqual(progress.load(), {'missions': {}, 'paths': {}, 'seen': []})
