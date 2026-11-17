"""Troubleshooting mode: every fault breaks its lab, is invisible until repaired, and the working lab grades clean."""
import copy
import os
import unittest

from network_labs.appliances import faults, missions
from network_labs.appliances.spec import validate


class FaultTest(unittest.TestCase):
    def test_every_fault_is_valid_detected_and_absent_from_the_working_lab(self):
        for lab, table in faults.FAULTS.items():
            original = faults.LABS[lab]['build']('/k', '/d')
            for fault, ((apply, _), symptom, answer) in table.items():
                with self.subTest(lab=lab, fault=fault):
                    broken = copy.deepcopy(original)
                    apply(broken)
                    broken = validate(broken)
                    panne = {'lab': lab, 'fault': fault, 'original': original}
                    graded = faults.grade(broken, panne)
                    self.assertEqual(graded['results'][0]['status'], 'fail')
                    self.assertIn('pas encore', graded['results'][0]['detail'])  # no spoiler before the repair
                    self.assertEqual(faults.grade(original, panne)['results'][0]['status'], 'ok')
                    self.assertTrue(symptom and answer)

    def test_create_is_reproducible_with_a_seed_and_names_its_lab(self):
        first = faults.create('routeurs', '/k', '/d', seed=2)
        self.assertEqual((first['fault'], first['spec']['name']), ('r1-route', 'panne-routeurs'))
        self.assertEqual(faults.create('routeurs', '/k', '/d', seed=2)['spec'], first['spec'])
        with self.assertRaises(ValueError):
            faults.create('nope', '/k', '/d')

    def test_real_results_complete_the_grade(self):
        panne = faults.create('pare-feu', '/k', '/d', seed=0)
        real = {index: (True, '3/3 réponses') for index in range(len(faults.LABS['pare-feu']['probes']))}
        self.assertTrue(faults.grade(panne['original'], panne, real)['solved'])
        self.assertFalse(faults.grade(panne['spec'], panne, real)['solved'])
        self.assertEqual(missions.mission('panne-pare-feu')['checks'], faults.LABS['pare-feu']['probes'])


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class PanneTabTest(unittest.TestCase):
    def test_panne_flow(self):
        import tkinter as tk
        from unittest.mock import patch
        from network_labs.__main__ import App
        from network_labs.appliances import vendor_config
        root = tk.Tk()
        try:
            window = App(root).open_native_lab()
            window.mission_kernel.set('/k')
            window.mission_disk.set('/d')
            window.select_mission('panne-routeurs')
            create = faults.create
            with patch('network_labs.appliances.faults.create', lambda lab, k, d, seed=None: create(lab, k, d, seed=2)):
                self.assertTrue(window.load_mission())
            self.assertEqual(window.panne['fault'], 'r1-route')
            self.assertIn('Le site A ne joint plus le site B', window.mission_story.get())
            self.assertTrue(window.mission_score.get().startswith('0 / 3'))
            window.mission_hint()
            window.mission_hint()
            self.assertIn('Solution', window.mission_status.get())
            window.commit_edit(vendor_config.apply(window.editing_spec(), 'R1', 'ip route 198.51.100.0 255.255.255.0 203.0.113.2'))
            window.check_mission()
            self.assertTrue(window.mission_score.get().startswith('1 / 3'))
        finally:
            root.destroy()
