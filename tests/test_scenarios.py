"""Generated troubleshooting scenarios and the network model they rely on."""
import collections
import copy
import json
import os
import unittest

from network_labs.appliances import microvm, missions, scenarios
from network_labs.appliances.network_model import Model
from network_labs.appliances.spec import validate

K, D = '/k', '/d'


class ModelTest(unittest.TestCase):
    def test_model_agrees_with_the_labs_tested_on_real_guests(self):
        cases = [(microvm.router_chain_example, [('VM2', '198.51.100.20', True), ('VM3', '192.0.2.20', True)]),
                 (microvm.switch_vlan_example, [('VM1', '192.0.2.12', True), ('VM1', '192.0.2.14', True), ('VM1', '192.0.2.13', False)]),
                 (microvm.router_on_a_stick_example, [('VM1', '198.51.100.10', True), ('VM2', '192.0.2.10', True)]),
                 (microvm.ospf_example, [('VM2', '198.51.100.20', True), ('VM3', '192.0.2.20', True)]),
                 (microvm.firewall_nat_example, [('VM2', '198.51.100.20', True), ('VM3', '198.51.100.1', True)]),
                 (microvm.dhcp_example, [('VM2', '198.51.100.20', True)])]
        for build, probes in cases:
            model = Model(build(K, D))
            for source, destination, expected in probes:
                with self.subTest(lab=build.__name__, source=source, destination=destination):
                    self.assertEqual(model.ping(source, destination)[0], expected, model.ping(source, destination))

    def test_every_mission_starts_broken_in_the_model(self):
        for item in missions.MISSIONS:
            lab = item['build'](K, D)
            reach = [c for c in item['checks'] if c['kind'] == 'reach']
            model = Model(lab)
            with self.subTest(mission=item['id']):
                self.assertTrue(any(model.ping(c['source'], c['destination'])[0] != c['expect'] for c in reach))

    def test_where_a_packet_stops(self):
        lab = microvm.router_chain_example(K, D)
        lab['nodes'][0].pop('guest_network')
        ok, why = Model(validate(lab)).ping('VM2', '198.51.100.20')
        self.assertFalse(ok)
        self.assertIn('R1 n’a aucune route vers 198.51.100.20', why)
        loop = microvm.router_chain_example(K, D)
        loop['nodes'][1]['guest_network']['routes'].append({'network': '198.51.100.20/32', 'gateway': '203.0.113.1'})
        loop['nodes'][0]['guest_network']['routes'] = [{'network': '198.51.100.0/24', 'gateway': '203.0.113.2'}]
        self.assertIn('boucle de routage entre R1 et R2', Model(validate(loop)).ping('VM2', '198.51.100.20')[1])


class ScenarioTest(unittest.TestCase):
    def test_more_than_a_thousand_distinct_scenarios_each_with_an_observable_fault(self):
        self.assertGreaterEqual(scenarios.COUNT, 1000)
        families, faults, seen = collections.Counter(), collections.Counter(), set()
        for number in range(1, scenarios.COUNT + 1):
            item = scenarios.scenario(number)
            families[item['family']] += 1
            faults[item['fault']['kind']] += 1
            seen.add(json.dumps([item['spec']['nodes'], item['spec']['links']], sort_keys=True))
            budget = item['spec']['budget_mib'] - item['spec']['reserve_mib']
            self.assertLessEqual(sum(n['memory_mib'] for n in item['spec']['nodes']), budget)
        self.assertEqual(len(seen), scenarios.COUNT)
        self.assertEqual(set(families), set(scenarios.FAMILIES))
        self.assertTrue(all(count >= scenarios.COUNT // 5 for count in families.values()), families)
        self.assertEqual(set(faults), set(scenarios.FAULTS), faults)

    def test_grade_help_and_the_privileged_mission(self):
        for number in (1, 2, 3, 4, 427, 1200):
            item = scenarios.scenario(number)
            with self.subTest(number=number):
                self.assertEqual(item, scenarios.scenario(number))  # a number always gives the same lab
                self.assertEqual(scenarios.grade(item['spec'], item)['results'][0]['status'], 'fail')
                repaired = scenarios.grade(item['original'], item)
                self.assertEqual(repaired['results'][0]['status'], 'ok')
                real = {i: (True, 'ok') for i in range(len(item['probes']))}
                self.assertTrue(scenarios.grade(item['original'], item, real)['solved'])
                steps = [scenarios.help_step(item['spec'], item, step) for step in range(1, scenarios.HELP_STEPS + 1)]
                self.assertIn(item['fault']['node'], steps[2])
                self.assertTrue(steps[4].startswith('Solution : '))
                self.assertEqual(missions.mission(item['id'])['checks'], scenarios.mission_for(number)['checks'])
        with self.assertRaises(ValueError):
            scenarios.scenario(scenarios.COUNT + 1)

    def test_a_different_correct_fix_also_passes(self):
        """Grading is by behaviour: a missing static route can come back with an equivalent route."""
        number = next(n for n in range(1, 400) if scenarios.scenario(n)['fault']['kind'] == 'route-missing')
        item = scenarios.scenario(number)
        node = next(n for n in item['spec']['nodes'] if n['name'] == item['fault']['node'])
        before = next(n for n in item['original']['nodes'] if n['name'] == node['name'])
        fixed = copy.deepcopy(item['spec'])
        target = next(n for n in fixed['nodes'] if n['name'] == node['name'])
        target['guest_network']['routes'] = sorted(before['guest_network']['routes'], key=lambda r: r['network'], reverse=True)
        self.assertEqual(scenarios.grade(fixed, item)['results'][0]['status'], 'ok')


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class WorkbenchTest(unittest.TestCase):
    def test_load_help_and_grade_a_scenario(self):
        import tkinter as tk
        from network_labs.__main__ import App
        from test_missions import setUpModule, tearDownModule  # noqa: F401
        setUpModule()
        root = tk.Tk()
        try:
            window = App(root).open_native_lab()
            window.tabs.select(window.missions_tab)
            window.mission_kernel.set('/k')
            window.mission_disk.set('/d')
            window.select_scenario(4)
            self.assertTrue(window.load_mission())
            self.assertEqual(window.manifest()['name'], 'scenario-0004')
            self.assertIn('ne joint plus', window.mission_story.get())
            for _ in range(2):
                window.mission_hint()
            self.assertIn('Aide 2', window.mission_help.get())
            self.assertEqual(window.mission_help_button.cget('text'), 'Un peu d’aide (2/5)')
            window.commit_edit(window.scenario['original'])
            self.assertEqual(window.show_mission_results()['results'][0]['status'], 'ok')
        finally:
            root.destroy()
            tearDownModule()
