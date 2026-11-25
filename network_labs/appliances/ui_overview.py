"""The device panel's first tab, « Aperçu »: the selected device at a glance, as Packet Tracer's device window opens on
it. Its picture, brand, model and state on a band; each port with its address and the device at the other end of the
cable; the actions a user reaches for (terminal, web management, a simulated ping, the command catalogue). The lab's
devices follow with their runtime state, and the connectivity test of container hosts when the lab has some."""
import tkinter as tk
from tkinter import ttk

from .design import STUDIO

STATES = {'running': 'en marche', 'stopped': 'arrêté', 'exited': 'arrêté', 'failed': 'en échec'}  # the window's language
from .reference_theme import BG, BLUE, MUTED, PANEL, TEXT


class DeviceOverview:
    def build_overview(self, details):
        """Build the tab. Keeps the attributes the rest of the workbench drives: nodes, selected_title, selected_details,
        inspect_button, destination, targets, verify_button, note."""
        self.overview_header = tk.Canvas(details, height=86, bg=PANEL, highlightthickness=0, bd=0)
        self.overview_header.pack(fill='x', padx=8, pady=(8, 4))
        self.overview_header.bind('<Configure>', lambda event: self.draw_overview_header())
        self.overview_node = None
        self.selected_title, self.selected_details = tk.StringVar(), tk.StringVar()
        summary = tk.Label(details, textvariable=self.selected_details, bg=PANEL, fg=MUTED, font=(self.font, 8), justify='left',
                           anchor='w', wraplength=360)
        summary.pack(fill='x', padx=14, pady=(0, 4))
        summary.bind('<Configure>', lambda event: summary.configure(wraplength=max(160, event.width - 4)))
        actions = tk.Frame(details, bg=PANEL)
        actions.pack(fill='x', padx=10, pady=(2, 6))
        actions.columnconfigure((0, 1), weight=1, uniform='actions')
        self.overview_actions = {}
        for index, (key, text, command) in enumerate((
                ('cli', '⌨  Terminal', lambda: self.overview_selected() and self.open_cli(self.overview_selected())),
                ('web', '↗  Gestion web', lambda: self.open_web_management('dashboard')),
                ('sim', '✉  Simuler un ping', lambda: self.open_simulation(source=self.overview_selected())),
                ('book', '📖  Commandes', self.open_catalogue))):
            button = ttk.Button(actions, text=text, command=command,
                                style='Native.Primary.TButton' if key == 'cli' else 'Native.TButton')
            button.grid(row=index // 2, column=index % 2, sticky='ew', padx=3, pady=3)
            self.overview_actions[key] = button
        self.overview_ports_title = self.label(details, 'Interfaces', TEXT, 9, True)
        self.overview_ports_title.pack(anchor='w', padx=14, pady=(6, 2))
        self.overview_ports = ttk.Treeview(details, columns=('address', 'peer', 'state'), show='tree headings', height=4,
                                           selectmode='none', style='Native.Treeview')
        for key, title, width in (('#0', 'Port', 92), ('address', 'Adresse', 110), ('peer', 'Câble vers', 118), ('state', 'État', 62)):
            self.overview_ports.heading(key, text=title, anchor='w')
            self.overview_ports.column(key, width=width, minwidth=40, stretch=key != 'state', anchor='w')
        self.overview_ports.tag_configure('cabled', foreground=TEXT)
        self.overview_ports.tag_configure('free', foreground=MUTED)
        self.overview_ports.tag_configure('down', foreground='#bb3646')
        self.overview_ports.pack(fill='x', padx=10)
        self.nodes_title = self.label(details, 'Équipements du lab', TEXT, 9, True)
        self.nodes_title.pack(anchor='w', padx=14, pady=(10, 2))
        self.nodes = ttk.Treeview(details, columns=('runtime', 'state', 'memory'), displaycolumns=('state', 'memory'),
                                  show='tree headings', height=3, selectmode='browse', style='Native.Treeview')
        for key, label, width in (('#0', 'Équipement', 90), ('runtime', 'Runtime', 65), ('state', 'État', 115), ('memory', 'RAM', 70)):
            self.nodes.heading(key, text=label, anchor='w')
            self.nodes.column(key, width=width, minwidth=45, stretch=True)
        self.nodes.pack(fill='x', padx=10)
        self.nodes.bind('<<TreeviewSelect>>', self.select_node)
        # The container (OCI) hosts' link test and inspection: shown when the lab has container hosts.
        self.oci_controls = controls = tk.Frame(details, bg=PANEL, padx=12, pady=6)
        self.inspect_button = ttk.Button(controls, text='Inspecter le réseau', command=lambda: self.launch('inspect'),
                                         style='Native.TButton')
        self.inspect_button.pack(fill='x')
        self.label(controls, 'TEST DE CONNECTIVITÉ', MUTED, 9, True).pack(anchor='w', pady=(8, 4))
        self.destination = tk.StringVar()
        self.targets = ttk.Combobox(controls, textvariable=self.destination, state='readonly', style='Native.TCombobox',
                                    font=(self.font, 9))
        self.targets.pack(fill='x', pady=4)
        self.verify_button = ttk.Button(controls, text='Tester la liaison', command=lambda: self.launch('verify'),
                                        style='Native.Primary.TButton')
        self.verify_button.pack(fill='x', pady=4)
        self.note = tk.StringVar(value='')
        self.note_label = tk.Label(details, textvariable=self.note, bg=PANEL, fg=BLUE, font=(self.font, 8), justify='left',
                                   anchor='nw', wraplength=360)
        self.note_label.pack(fill='x', padx=14, pady=6)
        self.note_label.bind('<Configure>', lambda event: self.note_label.configure(wraplength=max(160, event.width - 4)))
        self.overview_hint = self.label(details, 'Double-clic sur un équipement : son terminal · clic droit sur un câble : le retirer',
                                        MUTED, 7)
        self.overview_hint.configure(justify='center')
        self.overview_hint.pack(side='bottom', fill='x', padx=12, pady=6)
        self.overview_hint.bind('<Configure>', lambda event: self.overview_hint.configure(wraplength=max(160, event.width - 4)))

    def overview_selected(self):
        selected = self.nodes.selection()
        return selected[0] if selected else None

    def refresh_overview(self, node):
        """Fill the tab for NODE (a topology node), or show the empty state."""
        self.overview_ports.delete(*self.overview_ports.get_children())
        for button in self.overview_actions.values():
            button.state(['disabled'] if node is None else ['!disabled'])
        for widget in (self.overview_ports_title, self.overview_ports):  # no device: no port table to show
            if node is None:
                widget.pack_forget()
            elif not widget.winfo_ismapped():
                widget.pack(anchor='w', padx=14, pady=(6, 2), before=self.nodes_title) if widget is self.overview_ports_title \
                    else widget.pack(fill='x', padx=10, before=self.nodes_title)
        if node is None:
            self.overview_node = None
            where = 'le dock sous le schéma' if STUDIO else 'la bibliothèque'
            self.selected_details.set(f'Ajouter un équipement depuis {where} (clic ou glisser), puis le sélectionner.')
            self.draw_overview_header()
            return
        try:
            spec = self.manifest()
            configured = next(n for n in spec['nodes'] if n['name'] == node['name'])
        except (ValueError, KeyError, TypeError, StopIteration):
            spec, configured = None, node
        self.overview_node = (spec, configured) if spec else None
        guest = node['runtime'] == 'firecracker'
        self.overview_actions['book'].state(['!disabled'] if guest else ['disabled'])
        self.overview_actions['web'].state(['!disabled'] if spec else ['disabled'])
        from .native_models import port_label
        peers = {}
        for a, b in self.graph['links']:
            peers[tuple(a)] = b
            peers[tuple(b)] = a
        nodes = {n['name']: n for n in self.graph['nodes']}
        shut = set(configured.get('shutdown') or [])
        dhcp = set(configured.get('dhcp_clients') or [])
        for port, address in configured.get('interfaces', {}).items():
            peer = peers.get((node['name'], port))
            shown_peer = f'{peer[0]} · {port_label(nodes[peer[0]], peer[1])}' if peer and peer[0] in nodes else '—'
            state = 'arrêté' if port in shut else 'câblé' if peer else 'libre'
            value = 'DHCP' if port in dhcp else address.split('/')[0] + ('/' + address.split('/')[1] if '/' in address else '') \
                if address else '—'
            self.overview_ports.insert('', 'end', text=port_label(configured, port), values=(value, shown_peer, state),
                                       tags=('down' if port in shut else 'cabled' if peer else 'free',))
        for name, sub in (configured.get('subinterfaces') or {}).items():
            self.overview_ports.insert('', 'end', text='  ' + port_label(configured, sub['parent']) + '.' + str(sub.get('vlan', '')),
                                       values=(sub.get('address') or '—', f"VLAN {sub.get('vlan', '?')}", '802.1Q'), tags=('cabled',))
        for name, svi in (configured.get('svis') or {}).items():
            self.overview_ports.insert('', 'end', text='Vlan' + name[4:], values=(svi.get('address') or '—', 'SVI', ''),
                                       tags=('down' if name in shut else 'cabled',))
        rows = len(self.overview_ports.get_children())
        self.overview_ports.configure(height=max(2, min(6, rows)))  # more ports: the wheel scrolls (a 2960 has 16)
        status = self.states.get(node['name'], {}).get('status', 'non observé')
        cabled = sum(1 for port in configured.get('interfaces', {}) if (node['name'], port) in peers)
        lines = [f"{len(configured.get('interfaces', {}))} ports · {cabled} câblé{'s' if cabled > 1 else ''} · "
                 f"{'micro-VM' if guest else 'conteneur OCI'} · état : {STATES.get(status, status)}"]
        if configured.get('gateway'):
            lines.append('Passerelle : ' + configured['gateway'])
        self.selected_details.set('\n'.join(lines))
        self.draw_overview_header()

    def draw_overview_header(self):
        canvas = self.overview_header
        if self.overview_node is None:
            canvas.delete('all')
            width = max(200, canvas.winfo_width())
            from .soft_widgets import rounded_box
            fill, border = ('#132131', '#1d2b38') if STUDIO else ('#eef3f9', '#dde6f0')
            rounded_box(canvas, 2, 4, width - 2, 82, r=14, fill=fill, outline=border)
            canvas.create_text(width / 2, 34, text='Aucun équipement sélectionné', fill=TEXT, font=(self.font, 11, 'bold'))
            canvas.create_text(width / 2, 56, text='Cliquer sur un équipement du schéma', fill=MUTED, font=(self.font, 8))
            return
        self.paint_device_header(canvas, *self.overview_node)

    def show_oci_controls(self, shown):
        if shown and not self.oci_controls.winfo_ismapped():
            self.oci_controls.pack(fill='x', before=self.note_label)
        elif not shown and self.oci_controls.winfo_ismapped():
            self.oci_controls.pack_forget()


__all__ = ['DeviceOverview', 'BG']
