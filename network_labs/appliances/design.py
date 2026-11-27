"""The workbench's look: black and white. The studio's layout (an icon rail, a top bar with the lab's mode and its start
button, devices as tiles and a device dock under the canvas) in a white window, with black devices, black cables and
greys.

The workbench's modules were written for a light window, and the studio's chrome for a dark one, and they set many
colours by hand. install() turns every colour Tk receives into black, white or a grey (tone()): widget options, text
tags, canvas items and ttk styles. Colours written for the dark window are read the other way round (its dark panels turn
white, its light text dark); light tints become the grey of the same lightness; strong colours turn black."""

# The window's colours. BG: behind everything; PANEL: cards and panels; SIDEBAR: the side column; LINE: borders;
# FIELD: entries; HOVER / SELECTED: rows and buttons under the pointer or chosen.
COLOURS = dict(BG='#ffffff', PANEL='#ffffff', SIDEBAR='#ffffff', TEXT='#111111', MUTED='#6b6b6b', BLUE='#111111',
               GREEN='#111111', RED='#111111', TITLE='#000000', LINE='#e2e2e2', FIELD='#ffffff', HOVER='#f2f2f2',
               SELECTED='#e8e8e8', CARD='#ffffff', CARD_LINE='#dddddd', HOVER_LINE='#111111')
# The dark window the studio's chrome was written for: its colours tell tone() which ones to read the other way round.
DARK = dict(BG='#0c131b', PANEL='#0f1922', SIDEBAR='#0a1017', TEXT='#dbe7f3', MUTED='#7f95ab', BLUE='#3b82f6', GREEN='#22c55e',
            RED='#ef4444', TITLE='#eef5fb', LINE='#1d2b38', FIELD='#0c141d', HOVER='#16273a', SELECTED='#1e3a5f',
            CARD='#121e2a', CARD_LINE='#213347', HOVER_LINE='#2f5f99')

# The topology canvas. Links, captions and the boxes behind VLANs and firewall zones; the VLAN boxes take turns.
CANVAS_DARK = dict(background='#0c131b', grid='#1b2a39', hint='#7f95ab', link='#3b82f6', link_hover='#93c5fd', link_end='#3b82f6',
                   light_ring='#0c131b', caption='#93c5fd', name='#eef5fb', detail='#7f95ab', address='#7fb2e8',
                   zone=('#171329', '#3d2f66', '#c4b5fd'), selection='#60a5fa', chip=('#132131', '#23415f', '#93c5fd'),
                   vlans=(('#0f1d2c', '#23415f', '#93c5fd'), ('#0e1f19', '#1f4d33', '#86efac'), ('#1f1b10', '#5a4a1c', '#fcd34d')))
CANVAS = dict(background='#ffffff', grid='#ececec', hint='#8a8a8a', link='#111111', link_hover='#555555', link_end='#111111',
                   light_ring='#ffffff', caption='#222222', name='#111111', detail='#6b6b6b', address='#333333',
                   zone=('#fafafa', '#bdbdbd', '#333333'), selection='#111111', chip=('#ffffff', '#cccccc', '#333333'),
                   vlans=(('#f7f7f7', '#c4c4c4', '#222222'), ('#fbfbfb', '#adadad', '#222222'), ('#f3f3f3', '#d4d4d4', '#222222')))

# Light colours set by hand in the workbench's modules and the dark ones the studio gave them: backgrounds, then inks.
# Only the dark side counts now: tone() reads those colours as written for a dark window.
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


# Colours the studio's own code writes for its dark window (tiles, chips, its buttons and pills), beyond the tables above.
STUDIO_LITERALS = {'#0f2347', '#0f766e', '#13243a', '#14b8a6', '#15803d', '#16a34a', '#1a2836', '#1d4ed8', '#2563eb',
                   '#2a3d52', '#2f4b68', '#334155', '#4a1c20', '#5b2a2e', '#64748b', '#6d28d9', '#7f2d33', '#8b5cf6',
                   '#9fb3c8', '#b91c1c', '#c2410c', '#dbeafe', '#f97316', '#fca5a5'}


def _flat(values):
    for value in values:
        if isinstance(value, str):
            yield value.lower()
        elif isinstance(value, (tuple, list)):
            yield from _flat(value)


# Every colour made for the dark window: read the other way round (dark backgrounds turn white).
FOR_DARK = (set(_flat(DARK.values())) | set(_flat(CANVAS_DARK.values())) | set(_flat(SURFACES.values())) | set(_flat(INKS.values()))
            | STUDIO_LITERALS)
NAMED = {'white': '#ffffff', 'black': '#000000'}
# The light design's dark side menu (the GUI tab's section list) and its pale text: white and black here.
MONO_FIXED = {'#253440': '#f4f4f4', '#edf4fa': '#111111'}


def _rgb(colour):
    text = NAMED.get(colour.lower(), colour.lower())
    if len(text) == 4 and text.startswith('#'):
        text = '#' + ''.join(ch * 2 for ch in text[1:])
    if len(text) != 7 or not text.startswith('#'):
        return None
    try:
        return tuple(int(text[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except ValueError:
        return None


def _grey(value):
    return '#' + f'{max(0, min(255, round(value))):02x}' * 3


def tone(colour, role):
    """COLOUR as the black and white design shows it. ROLE: 'surface' (backgrounds, filled shapes), 'ink' (text) or 'line'
    (borders, cables). Greys stay as they are. Strong colours (blue buttons, green or red lights, tiles) turn black.
    Colours made for the studio's dark window are read the other way round: its dark panels turn white, its light text
    dark. The light design's pale tints become the grey of the same lightness."""
    rgb = _rgb(colour) if isinstance(colour, str) else None
    if rgb is None:
        return colour
    if colour.lower() in MONO_FIXED:
        return MONO_FIXED[colour.lower()]
    high, low = max(rgb), min(rgb)
    if high - low < .012:
        return colour
    light, saturation = .299 * rgb[0] + .587 * rgb[1] + .114 * rgb[2], (high - low) / high
    if NAMED.get(colour.lower(), colour.lower()) in FOR_DARK:
        if saturation > .45 and .25 <= light < .8:
            return '#111111'
        if role == 'ink' or light >= .5:
            return _grey((1 - light) * 200)
        return _grey(255 - max(0, light - .07) * 110) if role == 'surface' else _grey(255 - light * 170)
    if saturation > .45 and light < .75:
        return '#111111'
    return _grey(light * 255 * (.8 if role == 'ink' else 1))


def surface(colour):
    """COLOUR as a background."""
    return tone(colour, 'surface')


def ink(colour):
    """COLOUR as text."""
    return tone(colour, 'ink')


SHAPE_OPTIONS = {'fill', 'outline', 'activefill', 'activeoutline', 'disabledfill', 'disabledoutline'}


def convert(options, item=None):
    """A widget's Tk options (('-background', '#ffffff', ...)) with their colours turned black and white. A canvas item's
    fill and outline follow too (ITEM: its type, so a text's fill is read as ink and a line's as a line)."""
    options = list(options)
    for index in range(0, len(options) - 1, 2):
        key = str(options[index]).lstrip('-').lower()
        if key in SURFACE_OPTIONS:
            options[index + 1] = surface(options[index + 1])
        elif key in INK_OPTIONS:
            options[index + 1] = ink(options[index + 1])
        elif item and key in SHAPE_OPTIONS:
            role = 'ink' if item == 'text' else 'line' if item == 'line' or 'outline' in key else 'surface'
            options[index + 1] = tone(options[index + 1], role)
    return tuple(options)


STYLE_ROLES = {'background': 'surface', 'fieldbackground': 'surface', 'selectbackground': 'surface', 'troughcolor': 'surface',
               'foreground': 'ink', 'selectforeground': 'ink', 'insertcolor': 'ink', 'arrowcolor': 'ink',
               'bordercolor': 'line', 'lightcolor': 'line', 'darkcolor': 'line', 'focuscolor': 'line'}


def _install_items(tk, ttk):
    """Canvas items and ttk styles are converted too (the studio's code sets them by hand for a dark window)."""
    if getattr(tk.Canvas, '_mono_create', None):
        return
    create, itemconfigure = tk.Canvas._create, tk.Canvas.itemconfigure

    def _create(self, kind, args, kw):
        self._mono_item = kind
        try:
            return create(self, kind, args, kw)
        finally:
            self._mono_item = None

    def item_configure(self, tag, cnf=None, **kw):
        try:
            self._mono_item = self.type(tag) if cnf or kw else None
        except tk.TclError:
            self._mono_item = None
        try:
            return itemconfigure(self, tag, cnf, **kw)
        finally:
            self._mono_item = None
    tk.Canvas._mono_create = create
    tk.Canvas._create, tk.Canvas.itemconfigure, tk.Canvas.itemconfig = _create, item_configure, item_configure
    configure, style_map = ttk.Style.configure, ttk.Style.map

    def style_configure(self, style, query_opt=None, **kw):
        return configure(self, style, query_opt, **{k: tone(v, STYLE_ROLES[k]) if k in STYLE_ROLES else v for k, v in kw.items()})

    def style_mapping(self, style, query_opt=None, **kw):
        kw = {k: [(*spec[:-1], tone(spec[-1], STYLE_ROLES[k])) for spec in v] if k in STYLE_ROLES and isinstance(v, (list, tuple)) else v
              for k, v in kw.items()}
        return style_map(self, style, query_opt, **kw)
    ttk.Style.configure, ttk.Style.map = style_configure, style_mapping
    tag_configure = ttk.Treeview.tag_configure

    def row_tag(self, tagname, option=None, **kw):
        kw = {k: tone(v, 'ink' if k == 'foreground' else 'surface') if k in ('foreground', 'background') else v for k, v in kw.items()}
        return tag_configure(self, tagname, option, **kw)
    ttk.Treeview.tag_configure = row_tag  # a list's coloured rows (enabled ports in green, errors in red)


def install(root):
    """Every colour a module gives a Tk widget (at creation or in a later configure, text tags included) goes through
    convert(), and the colours nobody sets (a Text's page, a Label's grey) default to the window's."""
    import tkinter as tk
    from tkinter import ttk
    _install_items(tk, ttk)
    if not getattr(tk.Misc, '_studio_options', None):
        original = tk.Misc._options

        def options(self, cnf, kw=None):
            return convert(original(self, cnf, kw), getattr(self, '_mono_item', None))
        tk.Misc._studio_options = original
        tk.Misc._options = options
    colours = COLOURS
    for key, value in (('*Background', colours['PANEL']), ('*Foreground', colours['TEXT']), ('*activeBackground', colours['HOVER']),
                       ('*activeForeground', colours['TEXT']), ('*highlightBackground', colours['PANEL']),
                       ('*highlightColor', colours['BLUE']), ('*selectBackground', colours['SELECTED']),
                       ('*selectForeground', colours['TEXT']), ('*insertBackground', colours['TEXT']), ('*troughColor', colours['BG']),
                       ('*disabledForeground', '#9a9a9a'), ('*Text.Background', colours['FIELD']),
                       ('*Entry.Background', colours['FIELD']), ('*Listbox.Background', colours['FIELD'])):
        root.option_add(key, value)
