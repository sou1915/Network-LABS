"""The « Studio » design's frame around the workbench (design.py). On the left an icon rail (pages, simulation, the log,
the settings); on top the project's name, the mode (Concevoir · Simuler · Lab en direct) and one large button that
starts or stops the lab; under the canvas a dock of devices to click or drag in, by category; floating tools on the
canvas (select, cable, delete, zoom). The classic widgets are still built (the workbench drives them); this frame
hides the ones it replaces."""
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk

from . import design, studio_art
from .design import CANVAS, COLOURS
from .soft_widgets import rounded_box

PANEL, SIDEBAR, LINE, TEXT, MUTED = COLOURS['PANEL'], COLOURS['SIDEBAR'], COLOURS['LINE'], COLOURS['TEXT'], COLOURS['MUTED']
PAGES = (('Topologie', 'topology'), ('Équipements · JSON', 'editor'), ('Scénarios', 'missions'), ('Outils', 'tools'))


class Tip:
    """One small label beside the pointer that names what a rail or tool button does."""
    def __init__(self, root, font):
        self.root, self.font, self.window, self.pending = root, font, None, None

    def later(self, widget, text, x, y):
        self.cancel()
        self.pending = widget.after(380, lambda: self.show(text, x, y))

    def show(self, text, x, y):
        self.hide()
        self.window = tk.Toplevel(self.root, bg='#23364a')
        self.window.wm_overrideredirect(True)
        tk.Label(self.window, text=text, bg='#1a2c40', fg=TEXT, font=(self.font, 9), padx=9, pady=4).pack(padx=1, pady=1)
        self.window.geometry(f'+{int(x)}+{int(y)}')

    def cancel(self):
        if self.pending is not None:
            self.root.after_cancel(self.pending)
            self.pending = None
        self.hide()

    def hide(self):
        if self.window is not None:
            self.window.destroy()
            self.window = None


class IconButton(tk.Canvas):
    """A square button drawn on a canvas: a line icon, a soft square under the pointer, a blue one when active."""
    def __init__(self, parent, icon, command, *, tip=None, tips=None, size=44, background=SIDEBAR):
        super().__init__(parent, width=size, height=size, bg=background, highlightthickness=0, bd=0, cursor='hand2')
        self.icon, self.command, self.size, self.active, self.hovered, self.enabled = icon, command, size, False, False, True
        self.bind('<Enter>', lambda event: self.hover(True, tip, tips))
        self.bind('<Leave>', lambda event: self.hover(False, tip, tips))
        self.bind('<ButtonRelease-1>', self.released)
        self.paint()

    def hover(self, inside, tip, tips):
        self.hovered = inside
        self.paint()
        if tips is not None and tip:
            if inside:
                tips.later(self, tip, self.winfo_rootx() + self.size + 8, self.winfo_rooty() + self.size / 2 - 13)
            else:
                tips.cancel()

    def released(self, event):
        if self.enabled and 0 <= event.x < self.size and 0 <= event.y < self.size:
            self.command()

    def set_active(self, active):
        self.active = active
        self.paint()

    def paint(self):
        self.delete('all')
        size = self.size
        if self.active:
            rounded_box(self, 4, 4, size - 4, size - 4, r=11, fill='#13243a', outline='#2563eb')
        elif self.hovered and self.enabled:
            rounded_box(self, 4, 4, size - 4, size - 4, r=11, fill='#16273a', outline='')
        colour = '#60a5fa' if self.active else TEXT if self.hovered and self.enabled else MUTED
        studio_art.icon(self, self.icon, size / 2, size / 2, size * .48, colour)


class Choice(tk.Canvas):
    """Choices in a row, drawn on a canvas: a segmented control (one frame, the chosen part in blue) or separate pills."""
    def __init__(self, parent, items, command, *, font, background=PANEL, pills=False, height=34, size=10):
        super().__init__(parent, height=height, bg=background, highlightthickness=0, bd=0)
        self.items, self.command, self.pills, self.height = list(items), command, pills, height
        self.font = tkfont.Font(root=self, family=font, size=size, weight='bold' if not pills else 'normal')
        self.current, self.hovered = (self.items[0][0] if self.items else None), None
        self.bind('<Motion>', self.motion)
        self.bind('<Leave>', lambda event: self.motion(None))
        self.bind('<ButtonRelease-1>', self.released)
        self.spans = []
        self.paint()

    def set(self, key):
        self.current = key
        self.paint()

    def set_items(self, items):
        self.items = list(items)
        self.paint()

    def key_at(self, x):
        return next((key for key, left, right in self.spans if left <= x <= right), None)

    def motion(self, event):
        key = None if event is None else self.key_at(event.x)
        if key != self.hovered:
            self.hovered = key
            self.configure(cursor='hand2' if key else '')
            self.paint()

    def released(self, event):
        key = self.key_at(event.x)
        if key is not None:
            self.command(key)

    def paint(self):
        self.delete('all')
        self.spans, gap, pad = [], 8 if self.pills else 2, 16 if self.pills else 20
        widths = [self.font.measure(label) + 2 * pad for key, label in self.items]
        total = sum(widths) + gap * max(0, len(widths) - 1) + (0 if self.pills else 8)
        self.configure(width=total)
        h = self.height
        if not self.pills:
            rounded_box(self, 1, 1, total - 1, h - 1, r=10, fill='#111c27', outline=LINE)
        x = 0 if self.pills else 4
        for (key, label), width in zip(self.items, widths):
            chosen, hovered = key == self.current, key == self.hovered
            if self.pills:
                fill, border = ('#1e3a5f', '#2f5f99') if chosen else ('#16273a', '#2a3d52') if hovered else ('#132131', LINE)
                rounded_box(self, x, 3, x + width, h - 3, r=(h - 6) / 2, fill=fill, outline=border)
                ink = '#dbeafe' if chosen else TEXT if hovered else '#9fb3c8'
            else:
                if chosen:
                    rounded_box(self, x, 4, x + width, h - 4, r=8, fill='#2563eb', outline='')
                elif hovered:
                    rounded_box(self, x, 4, x + width, h - 4, r=8, fill='#16273a', outline='')
                ink = '#ffffff' if chosen else TEXT if hovered else '#9fb3c8'
            self.create_text(x + width / 2, h / 2, text=label, fill=ink, font=self.font)
            self.spans.append((key, x, x + width))
            x += width + gap


class StudioChrome:
    """Mixed into ApplianceWindow: builds the studio frame once the classic widgets exist (build_studio)."""

    def build_studio(self):
        window = self.window
        self.tips = Tip(self.root, self.font)
        self.studio_running = False
        body = None
        for widget in window.grid_slaves():
            row = int(widget.grid_info()['row'])
            if row in (0, 1, 2):
                widget.grid_remove()  # the classic header, toolbar and page tabs
            elif row == 3:
                body = widget
        window.columnconfigure(0, weight=0)
        window.columnconfigure(1, weight=1)
        self.build_rail().grid(row=0, column=0, rowspan=4, sticky='ns')
        self.build_top_bar().grid(row=0, column=1, sticky='ew')
        body.grid_configure(column=1, padx=0, pady=0)
        body.forget(body.panes()[0])  # the library: the device dock replaces it
        self.content.forget(self.lower)  # the log: on demand, from the rail or « Lab en direct »
        self.log_shown = False
        self.runtime_label.master.grid_remove()  # the classic legend: the top bar shows the lab's state
        self.device_dock = self.build_device_dock(self.topology_tab)
        self.device_dock.grid(row=2, column=0, sticky='ew')
        self.device_tabs.pack_configure(pady=(10, 0), padx=(4, 6))
        diagram = self.canvas.master
        for widget in diagram.place_slaves():
            widget.place_forget()  # the classic zoom bar
        card = diagram.master  # the canvas runs edge to edge: no rounded card around it
        card.face = card.edge = CANVAS['background']
        for widget in (self.canvas, diagram, card):
            widget.configure(bg=CANVAS['background'])
        card.arrange()
        self.build_canvas_tools(diagram)
        self.tabs.bind('<<NotebookTabChanged>>', self.studio_page_changed, add='+')
        self.studio_page_changed()

    # The rail -----------------------------------------------------------------------------------------------------
    def build_rail(self):
        rail = tk.Frame(self.window, bg=SIDEBAR, width=64)
        tk.Frame(rail, bg=LINE, width=1).pack(side='right', fill='y')
        column = tk.Frame(rail, bg=SIDEBAR)
        column.pack(side='left', fill='both', expand=True)
        mark = tk.Canvas(column, width=63, height=62, bg=SIDEBAR, highlightthickness=0, bd=0)
        studio_art.logo(mark, 31.5, 30, 36, self.font)
        mark.pack()
        self.rail_buttons = {}
        frames = {'topology': self.topology_tab, 'editor': self.editor_tab, 'missions': self.missions_tab, 'tools': self.tools_tab}
        for (title, key), icon in zip(PAGES, ('topology', 'code', 'flag', 'sliders')):
            button = IconButton(column, icon, lambda frame=frames[key]: self.tabs.select(frame), tip=title, tips=self.tips)
            button.pack(pady=3)
            self.rail_buttons[key] = button
        tk.Frame(column, bg=LINE, height=1, width=30).pack(pady=10)
        IconButton(column, 'mail', self.open_simulation, tip='Simulation de paquets', tips=self.tips).pack(pady=3)
        self.log_button = IconButton(column, 'list', self.toggle_log, tip='Journal : événements et diagnostic', tips=self.tips)
        self.log_button.pack(pady=3)
        self.settings_button = IconButton(column, 'gear', self.studio_menu, tip='Projet, réglages et design', tips=self.tips)
        self.settings_button.pack(side='bottom', pady=14)
        return rail

    def studio_page_changed(self, event=None):
        if self.closed:
            return
        current = self.tabs.select()
        frames = {'topology': self.topology_tab, 'editor': self.editor_tab, 'missions': self.missions_tab, 'tools': self.tools_tab}
        page = next((key for key, frame in frames.items() if str(frame) == current), 'topology')
        for key, button in self.rail_buttons.items():
            button.set_active(key == page)
        self.studio_page.set('/  ' + next(title for title, key in PAGES if key == page))

    def studio_menu(self):
        """The rail's settings: the project's files, advanced editing and the design."""
        menu = tk.Menu(self.window, tearoff=False)
        for label, command in (('Nouveau LAN', self.new), ('Campus entreprise', self.new_campus),
                               ('LAN sécurité access', lambda: self.new_campus(security=True)), (None, None),
                               ('Ouvrir…', self.open), ('Enregistrer', self.save), ('Enregistrer sous…', lambda: self.save(ask=True)),
                               (None, None),
                               ('Ajouter (options avancées)…', self.add_device_dialog), ('Valider / plan', self.preview),
                               ('Actualiser l’état du lab', lambda: self.launch('status'))):
            if label is None:
                menu.add_separator()
            else:
                menu.add_command(label=label, command=command)
        menu.add_separator()
        designs = tk.Menu(menu, tearoff=False)
        chosen = tk.StringVar(value=design.DESIGN)
        designs.add_radiobutton(label='Noir & blanc', variable=chosen, value='mono', command=lambda: self.switch_design('mono'))
        designs.add_radiobutton(label='Studio · sombre', variable=chosen, value='studio', command=lambda: self.switch_design('studio'))
        designs.add_radiobutton(label='Classique · clair', variable=chosen, value='classic',
                                command=lambda: self.switch_design('classic'))
        menu.add_cascade(label='Design', menu=designs)
        menu.chosen_design = chosen  # kept alive with the menu
        x, y = self.settings_button.winfo_rootx() + 52, self.settings_button.winfo_rooty() - 250
        try:
            menu.tk_popup(x, max(0, y))
        finally:
            menu.grab_release()
        return menu

    # The top bar --------------------------------------------------------------------------------------------------
    def build_top_bar(self):
        bar = tk.Frame(self.window, bg=PANEL, height=58)
        tk.Frame(bar, bg=LINE, height=1).pack(side='bottom', fill='x')
        inner = tk.Frame(bar, bg=PANEL)
        inner.pack(fill='both', expand=True, padx=(20, 14), pady=10)
        tk.Label(inner, textvariable=self.project_title, bg=PANEL, fg=COLOURS['TITLE'], font=(self.font, 12, 'bold')).pack(side='left')
        self.studio_page = tk.StringVar(value='/  Topologie')
        tk.Label(inner, textvariable=self.studio_page, bg=PANEL, fg=MUTED, font=(self.font, 10)).pack(side='left', padx=(14, 0))
        style = ttk.Style(self.root)
        for name, element in (('Studio.Start.TButton', 'Soft.start'), ('Studio.Stop.TButton', 'Soft.stop')):
            style.layout(name, [(element, {'sticky': 'nswe', 'children': [('Button.padding', {'sticky': 'nswe', 'children': [
                ('Button.label', {'sticky': 'nswe'})]})]})])
            style.configure(name, background=PANEL, font=(self.font, 10, 'bold'), padding=(18, 8), borderwidth=0,
                            foreground='white' if 'Start' in name else '#fca5a5')
            style.map(name, foreground=[('disabled', '#5d7288')])
        self.start_button = ttk.Button(inner, text='▶  Démarrer le lab', style='Studio.Start.TButton', command=self.studio_start_stop)
        self.start_button.pack(side='right')
        self.buttons.append(self.start_button)
        state = IconButton(inner, 'refresh', lambda: self.launch('status'), tip='Actualiser l’état du lab', tips=self.tips,
                           size=38, background=PANEL)
        state.pack(side='right', padx=(0, 8))
        self.studio_chip = tk.Label(inner, text='○ Lab arrêté', bg='#132131', fg=MUTED, font=(self.font, 9, 'bold'), padx=12, pady=5)
        self.studio_chip.pack(side='right', padx=(0, 10))
        self.modes = Choice(inner, (('design', 'Concevoir'), ('simulate', 'Simuler'), ('live', 'Lab en direct')), self.choose_mode,
                            font=self.font, height=36)
        self.modes.place(relx=.5, rely=.5, anchor='center')
        return bar

    def choose_mode(self, mode):
        """Concevoir: the canvas and the device dock. Simuler: the packet simulation window. Lab en direct: the canvas
        with the lab's log (events and diagnostics) in place of the dock."""
        if mode == 'simulate':
            self.open_simulation()
            return
        self.modes.set(mode)
        self.tabs.select(self.topology_tab)
        live = mode == 'live'
        if live:
            self.device_dock.grid_remove()
            self.set_edit_mode(None)
        else:
            self.device_dock.grid()
        self.toggle_log(live)

    def studio_start_stop(self):
        self.launch('stop' if self.studio_running else 'start')

    def studio_lab_state(self, guests, total):
        """The top bar after each drawing: the lab's state on the chip, start or stop on the large button."""
        from .platform_support import model_mode
        self.studio_running = bool(guests)
        plural = 's' if total > 1 else ''
        if guests:
            self.studio_chip.configure(text=f'●  En marche · {guests}/{total}', bg='#0e2418', fg='#4ade80')
        elif model_mode():
            self.studio_chip.configure(text='◇  Mode modèle', bg='#1b1630', fg='#c4b5fd')
        else:
            self.studio_chip.configure(text=f'○  Arrêté · {total} équipement{plural}', bg='#132131', fg=MUTED)
        self.start_button.configure(text='■  Arrêter le lab' if guests else '▶  Démarrer le lab',
                                    style='Studio.Stop.TButton' if guests else 'Studio.Start.TButton')

    def toggle_log(self, shown=None):
        shown = not self.log_shown if shown is None else shown
        if shown and not self.log_shown:
            self.content.add(self.lower, weight=1)
            self.window.after_idle(self.fit_reference_layout)
        elif not shown and self.log_shown:
            self.content.forget(self.lower)
        self.log_shown = shown
        self.log_button.set_active(shown)
        if getattr(self, 'graph', None) and not getattr(self, 'view_moved', False):
            self.window.after(60, self.fit_view)  # the canvas changed height: the whole lab in view again

    # The device dock ----------------------------------------------------------------------------------------------
    def dock_catalog(self):
        from .native_models import grouped, short_name
        generic = {'Routeurs': [('router', None, 'Routeur Linux', 'Routage · 802.1Q')],
                   'Switches': [('switch', None, 'Switch Linux', 'VLAN · ports')],
                   'Pare-feu': [('firewall', None, 'Pare-feu Linux', 'nftables')],
                   'Postes clients': [('host', None, 'Poste Linux', 'Micro-VM')],
                   'Serveurs et stockage': [('server', None, 'Serveur Linux', 'Ethernet')]}
        names = {'Postes clients': 'Postes', 'Serveurs et stockage': 'Serveurs'}
        catalog = []
        for category, models in grouped():
            entries = list(generic.get(category, []))
            for model in models:
                kind = 'server' if model['presentation'] == 'server' else model['role']
                entries.append((kind, model['id'], short_name(model), model['brand']))
            if entries:
                catalog.append((names.get(category, category), entries))
        return catalog

    def build_device_dock(self, parent):
        dock = tk.Frame(parent, bg=PANEL)
        tk.Frame(dock, bg=LINE, height=1).pack(fill='x')
        head = tk.Frame(dock, bg=PANEL)
        head.pack(fill='x', padx=16, pady=(10, 4))
        self.dock_entries = self.dock_catalog()
        self.dock_categories = Choice(head, [(name, name) for name, entries in self.dock_entries], self.show_dock_category,
                                      font=self.font, pills=True, height=32, size=9)
        self.dock_categories.pack(side='left')
        self.dock_search = tk.StringVar()
        search = ttk.Entry(head, textvariable=self.dock_search, style='Native.TEntry', width=24, font=(self.font, 9))
        search.pack(side='right')
        hint = tk.Label(search, text='Rechercher un modèle', bg=COLOURS['FIELD'], fg='#5d7288', font=(self.font, 9))
        hint.place(x=7, rely=.5, anchor='w')
        hint.bind('<Button-1>', lambda event: search.focus_set())
        search.bind('<FocusIn>', lambda event: hint.place_forget())
        search.bind('<FocusOut>', lambda event: self.dock_search.get() or hint.place(x=7, rely=.5, anchor='w'))
        self.dock_search.trace_add('write', lambda *args: self.dock_searched(search, hint))
        for icon, step in (('right', 1), ('left', -1)):
            IconButton(head, icon, lambda s=step: self.dock_strip.xview_scroll(s, 'pages'), size=32, background=PANEL,
                       tip='Modèles suivants' if step > 0 else 'Modèles précédents', tips=self.tips).pack(side='right', padx=(0, 2))
        self.dock_strip = strip = tk.Canvas(dock, bg=PANEL, height=78, highlightthickness=0, bd=0)
        strip.pack(fill='x', padx=12, pady=(4, 12))
        for sequence, step in (('<Button-4>', -3), ('<Button-5>', 3)):
            strip.bind(sequence, lambda event, s=step: strip.xview_scroll(s, 'units'))
        strip.bind('<MouseWheel>', lambda event: strip.xview_scroll(-3 if event.delta > 0 else 3, 'units'))
        self.show_dock_category(self.dock_entries[0][0] if self.dock_entries else None)
        return dock

    def dock_searched(self, search, hint):
        if self.dock_search.get():
            hint.place_forget()
        elif self.root.focus_get() is not search:
            hint.place(x=7, rely=.5, anchor='w')
        self.show_dock_category(None)

    def show_dock_category(self, category):
        """The dock's cards: one category, or every model matching the search."""
        query = self.dock_search.get().strip().casefold()
        if query:
            entries = [entry for name, items in self.dock_entries for entry in items
                       if query in ' '.join([name, entry[0], entry[1] or '', entry[2], entry[3]]).casefold()]
            self.dock_categories.set(None)
        else:
            category = category or self.dock_categories.current or self.dock_entries[0][0]
            self.dock_categories.set(category)
            entries = next((items for name, items in self.dock_entries if name == category), [])
        strip = self.dock_strip
        strip.delete('all')
        width, height, gap = 184, 66, 10
        title_font, detail_font = (self.font, 9, 'bold'), (self.font, 8)
        measure = tkfont.Font(root=strip, family=self.font, size=9, weight='bold')
        for index, (kind, model, title, detail) in enumerate(entries):
            x, tag = 4 + index * (width + gap), f'card{index}'
            rounded_box(strip, x, 4, x + width, 4 + height, r=12, fill=COLOURS['CARD'], outline=COLOURS['CARD_LINE'],
                        tags=(tag, tag + '-face'))
            studio_art.tile(strip, kind, x + 30, 4 + height / 2 - 1, 34, tags=(tag,))
            shown = title
            while measure.measure(shown) > width - 70 and len(shown) > 4:
                shown = shown.rstrip('…')[:-1] + '…'
            strip.create_text(x + 58, 4 + height / 2 - 9, text=shown, anchor='w', fill=TEXT, font=title_font, tags=(tag,))
            strip.create_text(x + 58, 4 + height / 2 + 10, text=detail[:22], anchor='w', fill=MUTED, font=detail_font, tags=(tag,))
            strip.tag_bind(tag, '<Enter>', lambda event, t=tag: self.dock_hover(t, True))
            strip.tag_bind(tag, '<Leave>', lambda event, t=tag: self.dock_hover(t, False))
            strip.tag_bind(tag, '<B1-Motion>', lambda event: strip.configure(cursor='plus'))
            strip.tag_bind(tag, '<ButtonRelease-1>', lambda event, k=kind, m=model: self.dock_released(event, k, m))
            strip.tag_bind(tag, '<Button-3>', lambda event, k=kind, m=model: self.add_device_dialog(k, model=m))
        if not entries:
            strip.create_text(8, 39, text='Aucun modèle ne correspond à la recherche.', anchor='w', fill=MUTED, font=(self.font, 9))
        strip.configure(scrollregion=(0, 0, 8 + len(entries) * (width + gap), height + 8))
        strip.xview_moveto(0)

    def dock_hover(self, tag, inside):
        self.dock_strip.itemconfigure(tag + '-face', fill=COLOURS['HOVER'] if inside else COLOURS['CARD'],
                                      outline=COLOURS['HOVER_LINE'] if inside else COLOURS['CARD_LINE'])
        self.dock_strip.configure(cursor='hand2' if inside else '')

    def dock_released(self, event, kind, model):
        """A card released: dropped on the canvas, the device goes there; a click adds it in view (ui_quick)."""
        self.dock_strip.configure(cursor='hand2')
        self.tile_released(event, kind, model)

    # The canvas tools ---------------------------------------------------------------------------------------------
    TOOLS = (('select', 'pointer', 'Sélection · Échap'), ('cable', 'cable', 'Connecter un câble : deux clics'),
             ('delete', 'trash', 'Supprimer la sélection'), None, ('out', 'minus', 'Zoom arrière'), ('zoom', None, 'Zoom'),
             ('in', 'plus', 'Zoom avant'), ('fit', 'fit', 'Tout afficher'))

    def build_canvas_tools(self, diagram):
        self.tool_bar = bar = tk.Canvas(diagram, height=44, bg=CANVAS['background'], highlightthickness=0, bd=0)
        bar.place(x=16, rely=1., y=-26, anchor='sw')
        self.tool_hover = None
        bar.bind('<Motion>', self.tools_motion)
        bar.bind('<Leave>', lambda event: self.tools_motion(None))
        bar.bind('<ButtonRelease-1>', self.tools_released)
        self.tool_mode.trace_add('write', lambda *args: self.paint_tools())
        self.zoom_label.trace_add('write', lambda *args: self.paint_tools())
        self.paint_tools()

    def tool_spans(self):
        spans, x = [], 6
        for item in self.TOOLS:
            if item is None:
                spans.append((None, x + 4, x + 5))
                x += 9
                continue
            width = 50 if item[0] == 'zoom' else 34
            spans.append((item, x, x + width))
            x += width + 2
        return spans, x + 4

    def paint_tools(self):
        bar = self.tool_bar
        bar.delete('all')
        spans, total = self.tool_spans()
        bar.configure(width=total)
        rounded_box(bar, 1, 1, total - 1, 43, r=12, fill=PANEL, outline=COLOURS['CARD_LINE'])
        for item, left, right in spans:
            if item is None:
                bar.create_line(left, 12, left, 32, fill=LINE, width=1)
                continue
            key, icon, tip = item
            if key == 'zoom':
                bar.create_text((left + right) / 2, 22, text=self.zoom_label.get(), fill=MUTED, font=(self.font, 8))
                continue
            chosen = key == self.tool_mode.get()
            if chosen:
                rounded_box(bar, left, 6, right, 38, r=9, fill='#1e3a5f', outline='')
            elif key == self.tool_hover:
                rounded_box(bar, left, 6, right, 38, r=9, fill='#16273a', outline='')
            colour = '#60a5fa' if chosen else TEXT if key == self.tool_hover else '#9fb3c8'
            studio_art.icon(bar, icon, (left + right) / 2, 22, 18, colour)

    def tool_at(self, x):
        spans, total = self.tool_spans()
        return next((item for item, left, right in spans if item and item[1] and left <= x <= right), None)

    def tools_motion(self, event):
        item = None if event is None else self.tool_at(event.x)
        key = item[0] if item else None
        if key != self.tool_hover:
            self.tool_hover = key
            self.tool_bar.configure(cursor='hand2' if key else '')
            self.paint_tools()
            if item:
                self.tips.later(self.tool_bar, item[2], event.x_root + 6, self.tool_bar.winfo_rooty() - 32)
            else:
                self.tips.cancel()

    def tools_released(self, event):
        item = self.tool_at(event.x)
        if item is None:
            return
        actions = {'select': lambda: self.set_edit_mode(None), 'cable': lambda: self.set_edit_mode('cable'),
                   'delete': self.delete_selected, 'out': lambda: self.set_zoom(self.zoom / 1.15),
                   'in': lambda: self.set_zoom(self.zoom * 1.15), 'fit': self.reset_view}
        actions[item[0]]()

    # The device band (Aperçu and GUI tabs) ------------------------------------------------------------------------
    def paint_studio_header(self, canvas, spec, node):
        """The selected device on a dark band: its tile, name, brand · model, and chips (state, ports, runtime, CLI)."""
        from .device_view import summary
        canvas.delete('all')
        canvas.configure(bg=PANEL)
        info = summary(spec, node)
        width = max(200, canvas.winfo_width())
        status = self.states.get(node['name'], {}).get('status')
        studio_art.tile(canvas, info['art'].split('-')[0], 36, 38, 48, status if status in ('running', 'stopped') else 'unknown')
        canvas.create_text(78, 20, text=node['name'], anchor='w', fill=COLOURS['TITLE'], font=(self.font, 14, 'bold'))
        line = (f"{info['brand']} · {info['title'].split(' · ')[-1]} — {info['role_name']}" if node.get('model')
                else f"Nœud Linux générique — {info['role_name']}")
        canvas.create_text(78, 41, text=line, anchor='w', fill=MUTED, font=(self.font, 9))
        running = status == 'running'
        chips = [('● En marche' if running else '○ Non observé'), f"{len(info['ports'])} ports",
                 'Micro-VM' if node['runtime'] == 'firecracker' else 'OCI'] + ([info['cli']] if info['cli'] else [])
        x = 78
        for chip in chips:
            item = canvas.create_text(x + 9, 66, text=chip, anchor='w', fill='#4ade80' if chip.startswith('●') else TEXT,
                                      font=(self.font, 8))
            left, top, right, bottom = canvas.bbox(item)
            if right + 9 > width - 6:
                canvas.delete(item)  # chips that do not fit the panel are left out rather than cut
                break
            canvas.tag_lower(rounded_box(canvas, left - 8, top - 3, right + 8, bottom + 3, r=9, fill='#132131', outline='#23364a'), item)
            x = right + 14

    # Switching design -------------------------------------------------------------------------------------------
    def switch_design(self, chosen):
        """Save the choice, then start the application again on the project as it is (saved first)."""
        if chosen == design.DESIGN:
            return
        name = {'mono': 'noir & blanc', 'studio': 'Studio (sombre)'}.get(chosen, 'classique (clair)')
        if self.pending:
            messagebox.showinfo('Design', 'Attendre la fin de l’opération en cours, puis changer de design.', parent=self.window)
            return
        if not messagebox.askokcancel('Design', f'Passer au design {name} ?\n\nLe projet est enregistré, puis le logiciel redémarre '
                                      'et le rouvre.', parent=self.window):
            return
        if not self.save():
            return
        design.save_choice(chosen)
        package = Path(__file__).resolve().parents[2]
        environment = dict(os.environ, NETWORK_LABS_DESIGN=chosen)
        environment['PYTHONPATH'] = os.pathsep.join(filter(None, [str(package), environment.get('PYTHONPATH')]))
        arguments = [sys.executable, '-m', 'network_labs', '--open', str(self.path)]
        self.root.destroy()
        os.execve(sys.executable, arguments, environment)


__all__ = ['StudioChrome', 'IconButton', 'Choice', 'Tip']
