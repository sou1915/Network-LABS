"""Which look the workbench wears, and the colours of each.

Two designs: « classic » (light, the original workbench) and « studio » (dark, an icon rail, a top bar with the lab's
mode and its start button, devices as coloured tiles and a device dock under the canvas). The choice is read once, at
import, from the NETWORK_LABS_DESIGN environment variable (classic when unset). The launcher sets it from --design, else
~/.config/network-labs/ui.json ({"design": "studio"}), else studio. Changing it restarts the application
(ui_studio.switch_design).

The workbench's modules were written for the light design and set many colours by hand. Under studio, install() maps
those light colours to their dark counterparts as Tk receives them, so each panel follows without a dark copy of its
code; canvas drawings choose their colours themselves (CANVAS here, studio_art for the devices)."""
from .design_choice import DESIGNS, SETTINGS, asked, chosen, save_choice  # noqa: F401 (re-exported)

# Only the environment counts here: the application's launcher (__main__.main) puts the saved choice there, so code
# that builds the workbench without it (the tests) gets classic whatever this computer saved.
DESIGN = asked() or 'classic'
STUDIO = DESIGN == 'studio'

# The window's colours. BG: behind everything; PANEL: cards and panels; SIDEBAR: the side column; LINE: borders;
# FIELD: entries; HOVER / SELECTED: rows and buttons under the pointer or chosen.
CLASSIC = dict(BG='#f1f4f9', PANEL='#ffffff', SIDEBAR='#eef3f9', TEXT='#172c43', MUTED='#66788f', BLUE='#007ce5', GREEN='#24c52c',
               RED='#df1723', TITLE='#243746', LINE='#e1e9f3', FIELD='#ffffff', HOVER='#edf5ff', SELECTED='#e4f0ff',
               CARD='#ffffff', CARD_LINE='#e1e9f3', HOVER_LINE='#b7d6fa')
DARK = dict(BG='#0c131b', PANEL='#0f1922', SIDEBAR='#0a1017', TEXT='#dbe7f3', MUTED='#7f95ab', BLUE='#3b82f6', GREEN='#22c55e',
            RED='#ef4444', TITLE='#eef5fb', LINE='#1d2b38', FIELD='#0c141d', HOVER='#16273a', SELECTED='#1e3a5f',
            CARD='#121e2a', CARD_LINE='#213347', HOVER_LINE='#2f5f99')
COLOURS = DARK if STUDIO else CLASSIC

# The topology canvas. Links, captions and the boxes behind VLANs and firewall zones; the VLAN boxes take turns.
CANVAS_CLASSIC = dict(background='#ffffff', grid='#e8eef7', hint='#66788f', link='#3886b9', link_hover='#007ce5', link_end='#4f83b3',
                      light_ring='#ffffff', caption='#315b7d', name='#172c43', detail='#66788f', address='#315b7d',
                      zone=('#f2ecff', '#cbb9ec', '#705493'), selection='#007ce5', chip=None,
                      vlans=(('#e8f4ff', '#8fc0ed', '#0064c7'), ('#e9f8ed', '#9ed4ad', '#14884b'), ('#fff7dd', '#ead08b', '#ba7a04')))
CANVAS_DARK = dict(background='#0c131b', grid='#1b2a39', hint='#7f95ab', link='#3b82f6', link_hover='#93c5fd', link_end='#3b82f6',
                   light_ring='#0c131b', caption='#93c5fd', name='#eef5fb', detail='#7f95ab', address='#7fb2e8',
                   zone=('#171329', '#3d2f66', '#c4b5fd'), selection='#60a5fa', chip=('#132131', '#23415f', '#93c5fd'),
                   vlans=(('#0f1d2c', '#23415f', '#93c5fd'), ('#0e1f19', '#1f4d33', '#86efac'), ('#1f1b10', '#5a4a1c', '#fcd34d')))
CANVAS = CANVAS_DARK if STUDIO else CANVAS_CLASSIC

# Light colours set by hand in the workbench's modules and what they become under studio: backgrounds, then inks.
SURFACES = {
    '#ffffff': '#0f1922', '#f1f4f9': '#0c131b', '#eef3f9': '#0a1017', '#f1f5fb': '#0f1922', '#f3f6fa': '#132131',
    '#f6f8fb': '#111c27', '#f7f9fc': '#111c27', '#f9fbfe': '#132131', '#e8eef5': '#16273a', '#e8eef7': '#1b2a39',
    '#eef4fb': '#132131', '#e6edf4': '#16273a', '#edf2f7': '#132131', '#edf1f7': '#132131', '#f0f4f8': '#111c27',
    '#e4f0ff': '#1e3a5f', '#eaf3ff': '#1e3a5f', '#edf5ff': '#16273a', '#ddecff': '#1e3a5f', '#e1ebfb': '#1e3a5f',
    '#e8f4ff': '#0f1d2c', '#e9f8ed': '#0e1f19', '#e3f6ea': '#0e2418', '#fff7dd': '#1f1b10', '#fff8ef': '#1f1b10',
    '#f2ecff': '#171329', '#f2f0ff': '#171329', '#efe9fb': '#1b1630', '#fff5f5': '#2a1416', '#ffe9e9': '#3a1a1d',
    '#dfe7f0': '#1d2b38', '#dfe7ef': '#1d2b38', '#e1e9f3': '#1d2b38', '#dde6f0': '#1d2b38', '#d3dde8': '#1d2b38',
    '#d7e3f4': '#1d2b38', '#d7e3f0': '#1d2b38', '#d8e6f2': '#1d2b38', '#dae4ef': '#23364a', '#e0e8f2': '#23364a',
    '#c4d4e6': '#24384d', '#8fc0ed': '#23415f', '#9ed4ad': '#1f4d33', '#ead08b': '#5a4a1c', '#cbb9ec': '#3d2f66',
    '#d9d2f5': '#3d2f66', '#f1dfc6': '#4a3a22', '#b9d9fc': '#2f5f99', '#9cc9ff': '#2f5f99', '#b7d6fa': '#2f5f99',
    '#e8edf4': '#132131', '#dce6f4': '#1a2c40', '#d9d9d9': '#0f1922', 'white': '#0f1922', '#e3f0ff': '#1e3a5f',
    '#253440': '#111c27',
}
INKS = {
    '#172c43': '#dbe7f3', '#243746': '#dbe7f3', '#000000': '#dbe7f3', '#66788f': '#7f95ab', '#8a98aa': '#5d7288',
    '#8b9cae': '#5d7288', '#9aa8b8': '#5d7288', '#7f93aa': '#7f95ab', '#71859d': '#5d7288', '#007ce5': '#60a5fa',
    '#0064c7': '#60a5fa', '#1f5f9c': '#93c5fd', '#315b7d': '#93c5fd', '#34536f': '#93c5fd', '#14884b': '#4ade80',
    '#168942': '#4ade80', '#157a3e': '#4ade80', '#159746': '#4ade80', '#21a35a': '#4ade80', '#ba7a04': '#fbbf24',
    '#b7791f': '#fbbf24', '#bb3646': '#f87171', '#b42323': '#f87171', '#df1723': '#f87171', '#b00020': '#f87171',
    '#5b3aa6': '#c4b5fd', '#705493': '#c4b5fd', '#3d2c7a': '#c4b5fd',
}
SURFACE_OPTIONS = {'background', 'bg', 'activebackground', 'highlightbackground', 'selectbackground', 'troughcolor',
                   'readonlybackground', 'disabledbackground'}
INK_OPTIONS = {'foreground', 'fg', 'activeforeground', 'disabledforeground', 'insertbackground', 'highlightcolor',
               'selectforeground'}


def surface(colour):
    """COLOUR as a background under the active design."""
    return SURFACES.get(colour.lower(), colour) if STUDIO and isinstance(colour, str) else colour


def ink(colour):
    """COLOUR as text under the active design."""
    return INKS.get(colour.lower(), colour) if STUDIO and isinstance(colour, str) else colour


def convert(options):
    """A widget's Tk options (('-background', '#ffffff', ...)) with their light colours turned dark."""
    options = list(options)
    for index in range(0, len(options) - 1, 2):
        key = str(options[index]).lstrip('-').lower()
        if key in SURFACE_OPTIONS:
            options[index + 1] = surface(options[index + 1])
        elif key in INK_OPTIONS:
            options[index + 1] = ink(options[index + 1])
    return tuple(options)


def install(root):
    """Under studio: every colour a module gives a Tk widget (at creation or in a later configure, text tags included)
    goes through convert(), and the colours nobody sets (a Text's white page, a Label's grey) default to dark ones."""
    import tkinter as tk
    if not STUDIO:
        return
    if not getattr(tk.Misc, '_studio_options', None):
        original = tk.Misc._options

        def options(self, cnf, kw=None):
            return convert(original(self, cnf, kw))
        tk.Misc._studio_options = original
        tk.Misc._options = options
    colours = COLOURS
    for key, value in (('*Background', colours['PANEL']), ('*Foreground', colours['TEXT']), ('*activeBackground', colours['HOVER']),
                       ('*activeForeground', colours['TEXT']), ('*highlightBackground', colours['PANEL']),
                       ('*highlightColor', colours['BLUE']), ('*selectBackground', colours['SELECTED']),
                       ('*selectForeground', colours['TEXT']), ('*insertBackground', colours['TEXT']), ('*troughColor', colours['BG']),
                       ('*disabledForeground', '#5d7288'), ('*Text.Background', colours['FIELD']),
                       ('*Entry.Background', colours['FIELD']), ('*Listbox.Background', colours['FIELD'])):
        root.option_add(key, value)
