"""The simulation mode window, as Packet Tracer's: choose a source and a destination, then step (or play) through every
frame of the ping. Each step moves envelopes along the cables of the drawing (amber ARP, magenta ICMP, a red cross
where a packet is dropped); the event list shows each frame (step, last device, at device, type) and the selected
frame's headers and what the device does with it. Computed by the network model (packet_sim), on the project: the
same path as « ping », a lab running or not.
"""
import tkinter as tk
from tkinter import ttk

from . import packet_sim

COLOURS = {'ARP': '#e8a317', 'ICMP': '#c2187a', 'DROP': '#d64541'}
FRAMES = 18  # animation frames per step
FRAME_MS = 28


class SimulationWindow:
    def __init__(self, workbench, font='DejaVu Sans'):
        self.workbench, self.font = workbench, font
        self.events, self.steps, self.position, self.playing = [], [], 0, False
        self.window = tk.Toplevel(workbench.window)
        self.window.title('Simulation')
        self.window.geometry('760x560')
        self.window.minsize(560, 380)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        tk.Label(self.window, text='SIMULATION   ·   chaque trame du ping, câble par câble (calculée par le modèle du projet)',
                 bg='#e9e9e9', fg='#222', font=(font, 9, 'bold'), anchor='w', padx=8).pack(fill='x')
        form = tk.Frame(self.window, padx=8, pady=6)
        form.pack(fill='x')
        names = [n['name'] for n in workbench.graph['nodes'] if n['role'] in ('host', 'router', 'firewall', 'switch')]
        tk.Label(form, text='Source', font=(font, 9)).pack(side='left')
        self.source = ttk.Combobox(form, values=names, width=10, state='readonly')
        self.source.pack(side='left', padx=(4, 10))
        if names:
            self.source.set(next((n for n in names if n.upper().startswith('PC')), names[0]))
        tk.Label(form, text='Destination (adresse IP)', font=(font, 9)).pack(side='left')
        self.destination = ttk.Entry(form, width=16)
        self.destination.pack(side='left', padx=(4, 10))
        ttk.Button(form, text='✉ Ajouter le ping', command=self.load).pack(side='left')
        controls = tk.Frame(self.window, padx=8)
        controls.pack(fill='x')
        self.back = ttk.Button(controls, text='◀ Retour', command=self.step_back)
        self.forward = ttk.Button(controls, text='Capture / Avancer ▶', command=self.step_forward)
        self.play = ttk.Button(controls, text='▶▶ Lecture', command=self.toggle_play)
        self.reset = ttk.Button(controls, text='⟲ Réinitialiser', command=self.restart)
        for button in (self.back, self.forward, self.play, self.reset):
            button.pack(side='left', padx=(0, 6), pady=4)
        self.status = tk.StringVar(value='Choisir la source et l’adresse de destination, puis « Ajouter le ping ».')
        tk.Label(controls, textvariable=self.status, font=(font, 9), fg='#444', anchor='w').pack(side='left', fill='x', padx=6)
        body = ttk.PanedWindow(self.window, orient='vertical')
        body.pack(fill='both', expand=True, padx=8, pady=(2, 8))
        table = tk.Frame(body)
        self.list = ttk.Treeview(table, columns=('step', 'last', 'at', 'type'), show='headings', height=9, selectmode='browse')
        for column, title, width in (('step', 'Pas', 50), ('last', 'Depuis', 150), ('at', 'Vers', 150), ('type', 'Type', 180)):
            self.list.heading(column, text=title)
            self.list.column(column, width=width, anchor='w')
        for kind, colour in COLOURS.items():
            self.list.tag_configure(kind, foreground=colour)
        self.list.tag_configure('future', foreground='#9a9a9a')
        scroll = ttk.Scrollbar(table, command=self.list.yview)
        self.list.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.list.pack(fill='both', expand=True)
        self.list.bind('<<TreeviewSelect>>', lambda _: self.show_details())
        body.add(table, weight=3)
        self.details = tk.Text(body, height=8, font=('DejaVu Sans Mono', 9), wrap='word', relief='flat', bg='#fafafa', padx=6, pady=4)
        self.details.tag_configure('title', font=('DejaVu Sans', 9, 'bold'))
        body.add(self.details, weight=2)
        self.update_buttons()

    # ---- the ping ----

    def load(self, source=None, destination=None):
        if source:
            self.source.set(source)
        if destination:
            self.destination.delete(0, 'end')
            self.destination.insert(0, destination)
        try:
            spec = self.workbench.editing_spec()
            result = packet_sim.simulate(spec, self.source.get(), self.destination.get().strip())
        except ValueError as error:
            self.status.set('Impossible : ' + str(error))
            return
        self.events = result['events']
        self.steps = sorted({e['step'] for e in self.events})
        self.position = 0
        self.outcome = result
        self.list.delete(*self.list.get_children())
        for index, event in enumerate(self.events):
            kind = event['kind']
            text = 'ARP' if kind == 'ARP' else 'ICMP' if kind == 'ICMP' else '✗ abandonné'
            self.list.insert('', 'end', iid=str(index), values=(event['step'], event['from'], event['to'],
                                                                  f'{text} · {event["what"]}'), tags=('future',))
        self.status.set(f'{len(self.steps)} pas · Capture / Avancer pour suivre la première trame.')
        self.clear_envelopes()
        self.update_buttons()

    def restart(self):
        self.playing = False
        self.position = 0
        self.clear_envelopes()
        for item in self.list.get_children():
            self.list.item(item, tags=('future',))
        self.update_buttons()

    # ---- stepping ----

    def step_forward(self):
        if self.position >= len(self.steps):
            return self.finish()
        self.position += 1
        self.mark()
        self.animate(self.current(), 0)
        self.update_buttons()

    def step_back(self):
        if self.position == 0:
            return
        self.position -= 1
        self.mark()
        self.clear_envelopes()
        if self.position:
            self.draw_envelopes(self.current(), 1.0)
        self.update_buttons()

    def toggle_play(self):
        self.playing = not self.playing
        self.play.configure(text='⏸ Pause' if self.playing else '▶▶ Lecture')
        if self.playing:
            self.tick()

    def tick(self):
        if not self.playing or not self.window.winfo_exists():
            return
        if self.position >= len(self.steps):
            self.playing = False
            self.play.configure(text='▶▶ Lecture')
            return self.finish()
        self.step_forward()
        self.window.after(FRAMES * FRAME_MS + 450, self.tick)

    def current(self):
        step = self.steps[self.position - 1]
        return [e for e in self.events if e['step'] == step]

    def finish(self):
        result = getattr(self, 'outcome', None)
        if result is not None:
            self.status.set('Ping réussi : la réponse est revenue à ' + self.source.get() + '.' if result['ok']
                            else 'Échec : ' + str(result['why']))

    def mark(self):
        """Steps done in their colour, the current one selected, those to come grey."""
        shown = None
        for index, event in enumerate(self.events):
            done = self.steps.index(event['step']) < self.position
            self.list.item(str(index), tags=(event['kind'],) if done else ('future',))
            if done and event['step'] == self.steps[self.position - 1] and shown is None:
                shown = str(index)
        if shown:
            self.list.selection_set(shown)
            self.list.see(shown)
        current = self.current() if self.position else []
        if current:
            event = current[0]
            self.status.set(f'Pas {self.position}/{len(self.steps)} · {event["what"]} · '
                            + (f'{len(current)} trames en même temps' if len(current) > 1 else f'{event["from"]} → {event["to"]}'))

    def show_details(self):
        selected = self.list.selection()
        self.details.delete('1.0', 'end')
        if not selected:
            return
        event = self.events[int(selected[0])]
        what = event['what']
        self.details.insert('end', f'{what[:1].upper() + what[1:]} · {event["from"]} → {event["to"]}\n', 'title')
        for layer, text in event['layers'].items():
            self.details.insert('end', f'{layer:<9}', 'title')
            self.details.insert('end', f' {text}\n')
        self.details.insert('end', '\nÀ l’arrivée : ', 'title')
        self.details.insert('end', event['arrival'] + '\n')

    def update_buttons(self):
        loaded = bool(self.steps)
        self.back.state(['!disabled'] if loaded and self.position else ['disabled'])
        self.forward.state(['!disabled'] if loaded and self.position < len(self.steps) else ['disabled'])
        self.play.state(['!disabled'] if loaded else ['disabled'])
        self.reset.state(['!disabled'] if loaded and self.position else ['disabled'])

    # ---- envelopes on the drawing ----

    def route_points(self, event):
        """The cable's drawn points from the event's sender to its receiver (canvas coordinates)."""
        workbench = self.workbench
        for index, (a, b) in enumerate(workbench.graph['links']):
            ends = (tuple(a), tuple(b))
            wanted = ((event['from'], event['from_port']), (event['to'], event['to_port']))
            if ends == wanted or ends == wanted[::-1]:
                coords = workbench.canvas.coords(workbench.link_shapes[index])
                points = list(zip(coords[::2], coords[1::2]))
                return points if ends == wanted else points[::-1]
        if event['kind'] == 'DROP':
            x, y = workbench.drawn_positions[event['to']]
            zoom = getattr(workbench, 'zoom', 1.)
            return [(x * zoom, y * zoom)]
        return None

    @staticmethod
    def along(points, fraction):
        if len(points) == 1:
            return points[0]
        lengths = [((x2 - x1) ** 2 + (y2 - y1) ** 2) ** .5 for (x1, y1), (x2, y2) in zip(points, points[1:])]
        goal, walked = sum(lengths) * fraction, 0.
        for (x1, y1), (x2, y2), length in zip(points, points[1:], lengths):
            if walked + length >= goal and length:
                part = (goal - walked) / length
                return x1 + (x2 - x1) * part, y1 + (y2 - y1) * part
            walked += length
        return points[-1]

    def clear_envelopes(self):
        self.workbench.canvas.delete('sim-envelope')

    def draw_envelopes(self, events, fraction):
        canvas = self.workbench.canvas
        self.clear_envelopes()
        for event in events:
            points = self.route_points(event)
            if not points:
                continue
            x, y = self.along(points, fraction)
            colour = COLOURS[event['kind']]
            if event['kind'] == 'DROP':
                canvas.create_line(x - 9, y - 9, x + 9, y + 9, fill=colour, width=4, tags=('sim-envelope',))
                canvas.create_line(x - 9, y + 9, x + 9, y - 9, fill=colour, width=4, tags=('sim-envelope',))
                continue
            canvas.create_rectangle(x - 10, y - 7, x + 10, y + 7, fill=colour, outline='white', width=1.5, tags=('sim-envelope',))
            canvas.create_line(x - 10, y - 7, x, y + 1, x + 10, y - 7, fill='white', width=1.5, tags=('sim-envelope',))
        canvas.tag_raise('sim-envelope')

    def animate(self, events, frame):
        if not self.window.winfo_exists() or not self.position or events != self.current():
            return
        self.draw_envelopes(events, frame / FRAMES)
        if frame < FRAMES:
            self.window.after(FRAME_MS, self.animate, events, frame + 1)

    def close(self):
        self.playing = False
        self.clear_envelopes()
        self.window.destroy()
