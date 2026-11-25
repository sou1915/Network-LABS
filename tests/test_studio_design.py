"""The « Studio » design and its black and white variant « mono »: how they are chosen and saved, the dark and the
black and white colour mappings, the tiles, and the workbench built under each (in a separate process, since the design
is read once, when the modules load)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from network_labs.appliances import design, design_choice, studio_art

ROOT = Path(__file__).resolve().parents[1]


class DesignChoiceTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.settings = Path(self.folder.name) / 'ui.json'
        patcher = mock.patch.object(design_choice, 'SETTINGS', self.settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        environment = mock.patch.dict(os.environ, {}, clear=False)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop('NETWORK_LABS_DESIGN', None)

    def test_nothing_asked_means_no_choice(self):
        self.assertIsNone(design.chosen())

    def test_saved_choice_is_read_and_the_environment_wins(self):
        design.save_choice('studio')
        self.assertEqual(json.loads(self.settings.read_text())['design'], 'studio')
        os.environ.pop('NETWORK_LABS_DESIGN')
        self.assertEqual(design.chosen(), 'studio')
        os.environ['NETWORK_LABS_DESIGN'] = 'classic'
        self.assertEqual(design.chosen(), 'classic')

    def test_saving_keeps_other_settings_and_refuses_unknown_designs(self):
        self.settings.write_text(json.dumps({'other': 1, 'design': 'classic'}))
        design.save_choice('studio')
        self.assertEqual(json.loads(self.settings.read_text()), {'other': 1, 'design': 'studio'})
        with self.assertRaises(ValueError):
            design.save_choice('neon')

    def test_the_black_and_white_design_can_be_chosen(self):
        design.save_choice('mono')
        self.assertEqual(design.chosen(), 'mono')
        self.assertIn('mono', design_choice.DESIGNS)

    def test_a_damaged_or_unknown_setting_is_ignored(self):
        self.settings.write_text('{not json')
        self.assertIsNone(design.chosen())
        self.settings.write_text(json.dumps({'design': 'neon'}))
        self.assertIsNone(design.chosen())


class ColourMappingTest(unittest.TestCase):
    def test_studio_turns_light_backgrounds_and_dark_inks_around(self):
        with mock.patch.object(design, 'STUDIO', True):
            options = design.convert(('-background', '#FFFFFF', '-foreground', '#172c43', '-padx', 4, '-fill', '#ffffff'))
        self.assertEqual(options, ('-background', '#0f1922', '-foreground', '#dbe7f3', '-padx', 4, '-fill', '#ffffff'))

    def test_classic_leaves_every_colour_alone(self):
        with mock.patch.object(design, 'STUDIO', False):
            self.assertEqual(design.convert(('-bg', '#ffffff', '-fg', '#172c43')), ('-bg', '#ffffff', '-fg', '#172c43'))

    def test_dark_values_are_not_light_keys(self):
        # A colour converted once must stay as it is when Tk is given it again (configure after creation).
        self.assertFalse(set(design.SURFACES.values()) & set(design.SURFACES))
        self.assertFalse(set(design.INKS.values()) & set(design.INKS))


class MonoToneTest(unittest.TestCase):
    """Under mono every colour becomes black, white or a grey; the studio's colours, made for a dark window, turn around."""
    def test_greys_stay_and_strong_colours_turn_black(self):
        for grey in ('#ffffff', '#111111', '#e8e8e8', 'white'):
            self.assertEqual(design.tone(grey, 'surface'), grey)
        for strong in ('#2563eb', '#22c55e', '#ef4444', '#087fe9', '#f97316'):
            self.assertEqual(design.tone(strong, 'surface'), '#111111')

    def test_the_dark_window_turns_white_and_its_light_text_dark(self):
        self.assertEqual(design.tone(design.DARK['BG'], 'surface'), '#ffffff')
        self.assertGreater(int(design.tone(design.DARK['PANEL'], 'surface')[1:3], 16), 0xf0)
        self.assertLess(int(design.tone(design.DARK['TEXT'], 'ink')[1:3], 16), 0x30)

    def test_light_tints_keep_their_lightness_without_colour(self):
        tinted = design.tone('#e4f0ff', 'surface')
        self.assertEqual(len({tinted[1:3], tinted[3:5], tinted[5:7]}), 1)
        self.assertGreater(int(tinted[1:3], 16), 0xe0)
        self.assertEqual(design.tone('#8a98aa', 'ink')[1:3], design.tone('#8a98aa', 'ink')[3:5])  # a pale text stays pale grey

    def test_canvas_items_follow_under_mono_only(self):
        with mock.patch.object(design, 'MONO', True), mock.patch.object(design, 'STUDIO', True):
            converted = design.convert(('-fill', '#3b82f6', '-outline', '#23364a', '-width', 2), item='rectangle')
            text = design.convert(('-fill', '#dbe7f3'), item='text')
        self.assertEqual(converted[1], '#111111')
        self.assertEqual(converted[3], design.tone('#23364a', 'line'))
        self.assertLess(int(text[1][1:3], 16), 0x30)
        with mock.patch.object(design, 'MONO', False):
            self.assertEqual(design.convert(('-fill', '#3b82f6'), item='rectangle'), ('-fill', '#3b82f6'))

    def test_the_palettes_are_black_white_and_grey(self):
        def grey(colour):
            return colour[1:3] == colour[3:5] == colour[5:7]
        self.assertTrue(all(grey(c) for c in design.MONO_COLOURS.values()))
        self.assertTrue(all(grey(c) for c in design._flat(design.CANVAS_MONO.values())))


class TileTest(unittest.TestCase):
    def test_server_tiles_for_server_models_dmz_hosts_and_srv_names(self):
        models = {'srv': {'presentation': 'server'}, 'pc': {'presentation': 'host'}}
        self.assertEqual(studio_art.kind_of({'name': 'A', 'role': 'host', 'model': 'srv'}, models=models), 'server')
        self.assertEqual(studio_art.kind_of({'name': 'B', 'role': 'host', 'model': 'pc'}, dmz={'B'}, models=models), 'server')
        self.assertEqual(studio_art.kind_of({'name': 'srv2', 'role': 'host'}), 'server')
        self.assertEqual(studio_art.kind_of({'name': 'PC1', 'role': 'host', 'model': 'pc'}, models=models), 'host')
        self.assertEqual(studio_art.kind_of({'name': 'R1', 'role': 'router'}), 'router')

    def test_every_role_has_its_colours(self):
        self.assertEqual(set(studio_art.ROLE_COLOURS), {'router', 'switch', 'firewall', 'host', 'server'})


STUDIO_WORKBENCH = r'''
import json, tkinter as tk
from types import SimpleNamespace
from network_labs.appliances import design
from network_labs.appliances.spec import example
from network_labs.appliances.ui import ApplianceWindow
root = tk.Tk()
root.geometry('1400x880')
window = ApplianceWindow(SimpleNamespace(root=root, pause=lambda: None), embedded=True)
window.load_spec(example('/tmp/rootfs'))
root.update()
report = {'design': design.DESIGN, 'panes': len(window.content.panes())}
report['library_hidden'] = len(window.content.master.panes()) == 1
report['rail'] = sorted(window.rail_buttons)
report['tiles'] = len(window.canvas.find_withtag('glow')) > 0
report['canvas'] = window.canvas.cget('background')
names = [n['name'] for n in window.graph['nodes']]
window.draw(window.graph, {name: {'status': 'running'} for name in names})
report['chip'] = window.studio_chip.cget('text')
report['button'] = (window.start_button.cget('text'), str(window.start_button.cget('style')))
window.draw(window.graph, {})
report['button_stopped'] = window.start_button.cget('text')
window.toggle_log()
report['log_panes'] = len(window.content.panes())
window.choose_mode('live')
root.update()
report['dock_in_live'] = window.device_dock.winfo_ismapped()
window.choose_mode('design')
root.update()
report['dock_in_design'] = window.device_dock.winfo_ismapped()
report['log_after_design'] = window.log_shown
window.show_dock_category('Switches')
report['switch_cards'] = len(window.dock_strip.find_withtag('card0-face'))
window.dock_search.set('zzz-nothing')
report['search_empty'] = len(window.dock_strip.find_withtag('card0'))
window.dock_search.set('')
window.tool_mode.set('cable')
report['tool_bar'] = window.tool_bar.winfo_ismapped()
window.tabs.select(window.missions_tab)
root.update()
report['page'] = window.studio_page.get()
report['missions_active'] = window.rail_buttons['missions'].active
report['panel_colour'] = window.device_panel.cget('background')
print('REPORT ' + json.dumps(report))
root.destroy()
'''


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class StudioWorkbenchTest(unittest.TestCase):
    def test_the_workbench_under_the_studio_design(self):
        environment = dict(os.environ, NETWORK_LABS_DESIGN='studio', PYTHONPATH=str(ROOT))
        result = subprocess.run([sys.executable, '-c', STUDIO_WORKBENCH], cwd=ROOT, env=environment, capture_output=True, text=True,
                                timeout=120)
        line = next((l for l in result.stdout.splitlines() if l.startswith('REPORT ')), None)
        self.assertIsNotNone(line, result.stderr[-3000:])
        report = json.loads(line[7:])
        self.assertEqual(report['design'], 'studio')
        self.assertEqual(report['panes'], 1)  # the log is hidden until asked
        self.assertTrue(report['library_hidden'])  # the device dock replaces the library
        self.assertEqual(report['rail'], ['editor', 'missions', 'tools', 'topology'])
        self.assertTrue(report['tiles'])
        self.assertEqual(report['canvas'], design.CANVAS_DARK['background'])
        self.assertTrue(report['chip'].startswith('●  En marche'))
        self.assertEqual(report['button'], ['■  Arrêter le lab', 'Studio.Stop.TButton'])
        self.assertEqual(report['button_stopped'], '▶  Démarrer le lab')
        self.assertEqual(report['log_panes'], 2)
        self.assertFalse(report['dock_in_live'])
        self.assertTrue(report['dock_in_design'])
        self.assertFalse(report['log_after_design'])
        self.assertEqual(report['switch_cards'], 1)
        self.assertEqual(report['search_empty'], 0)
        self.assertTrue(report['tool_bar'])
        self.assertEqual(report['page'], '/  Scénarios')
        self.assertTrue(report['missions_active'])
        self.assertEqual(report['panel_colour'], design.DARK['PANEL'])  # a hand-set white panel, turned dark


MONO_WORKBENCH = r'''
import json, tkinter as tk
from types import SimpleNamespace
from network_labs.appliances import design
from network_labs.appliances.spec import example
from network_labs.appliances.ui import ApplianceWindow
root = tk.Tk()
root.geometry('1400x880')
window = ApplianceWindow(SimpleNamespace(root=root, pause=lambda: None), embedded=True)
window.load_spec(example('/tmp/rootfs'))
names = [n['name'] for n in window.graph['nodes']]
window.draw(window.graph, {name: {'status': 'running'} for name in names})
root.update()
canvas = window.canvas
colours = set()
for item in canvas.find_all():
    for option in ('fill', 'outline'):
        try:
            value = canvas.itemcget(item, option)
        except tk.TclError:
            continue
        if value.startswith('#'):
            colours.add(value.lower())
report = {'design': design.DESIGN, 'canvas': canvas.cget('background'), 'panel': window.device_panel.cget('background'),
          'colours': sorted(colours), 'rail': sorted(window.rail_buttons)}
print('REPORT ' + json.dumps(report))
root.destroy()
'''


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class MonoWorkbenchTest(unittest.TestCase):
    def test_the_workbench_in_black_and_white(self):
        environment = dict(os.environ, NETWORK_LABS_DESIGN='mono', PYTHONPATH=str(ROOT))
        result = subprocess.run([sys.executable, '-c', MONO_WORKBENCH], cwd=ROOT, env=environment, capture_output=True, text=True,
                                timeout=120)
        line = next((l for l in result.stdout.splitlines() if l.startswith('REPORT ')), None)
        self.assertIsNotNone(line, result.stderr[-3000:])
        report = json.loads(line[7:])
        self.assertEqual(report['design'], 'mono')
        self.assertEqual(report['rail'], ['editor', 'missions', 'tools', 'topology'])  # the studio's layout
        self.assertEqual(report['canvas'], '#ffffff')
        self.assertEqual(report['panel'], '#ffffff')
        self.assertIn('#111111', report['colours'])  # black tiles and cables
        self.assertTrue(all(c[1:3] == c[3:5] == c[5:7] for c in report['colours']), report['colours'])  # nothing but greys


if __name__ == '__main__':
    unittest.main()
