"""Quick editing, Packet Tracer style: a click (or a drag) on the library adds a device, two clicks lay a cable.

A new device is a micro-VM with the kernel and disk that « setup » prepared, its model's ports and no address yet:
the student configures it in its terminal once the lab runs (addresses, routes, protocols apply live). The full
form stays one right-click away (« options avancées »), and Ctrl-click on the second device picks the cable's ports.
"""
from pathlib import Path

from . import topology_edit
from .native_models import default_ports, port_names

PREFIXES = {'host': 'PC', 'server': 'SRV', 'switch': 'SW', 'router': 'R', 'firewall': 'FW'}
GENERIC_PORTS = {'host': 1, 'server': 1, 'switch': 4, 'router': 2, 'firewall': 2}


def projects_dir():
    from .setup import data_dir
    return data_dir() / 'projects'


def blank_project(name='mon-lab'):
    """An empty project: a blank canvas, as at the start of Packet Tracer."""
    return {'version': 2, 'name': name, 'nodes': [], 'links': []}


def unused_name(spec, kind):
    used = {n['name'] for n in spec['nodes']}
    prefix = PREFIXES[kind]
    return next(prefix + str(i) for i in range(1, 258) if prefix + str(i) not in used)


class QuickEditing:
    def microvm_paths(self):
        """The kernel and disk « setup » prepared, or None (then the student is offered to prepare the computer)."""
        from . import progress
        saved = progress.load()['paths']
        if saved.get('kernel') and saved.get('disk'):
            return saved['kernel'], saved['disk']
        current = next((n for n in self.manifest()['nodes'] if n['runtime'] == 'firecracker'), None)
        return (current['kernel'], current['disk']) if current else None

    def quick_add(self, kind, model=None, at=None):
        """Add a device with sensible defaults, without a form; AT is a canvas point (x, y) or None."""
        if self.pending:
            return None
        try:
            spec = self.editing_spec()
            paths = self.microvm_paths()
            if paths is None:
                from tkinter import messagebox
                if messagebox.askyesno('Préparer cet ordinateur', 'Les micro-VM ne sont pas encore prêtes sur cet ordinateur '
                                       '(Firecracker, noyau, disque). Préparer maintenant ?', parent=self.window):
                    self.prepare_computer()
                return None
            role = 'host' if kind == 'server' else kind
            ports = default_ports(model, 'firecracker') if model else GENERIC_PORTS[kind]
            name = unused_name(spec, kind)
            result = topology_edit.add_microvm_node(spec, name=name, role=role, kernel=paths[0], disk=paths[1], ports=ports,
                                                    addresses='', model=model)
            if at is not None:
                self.positions[name] = (at[0] / self.zoom, at[1] / self.zoom)
            self.commit_edit(result)
            self.choose_node(name)
            self.note.set(f'{name} ajouté. Câbler avec « Connecter un câble », puis ▶ Démarrer ; configurer ensuite '
                          f'{name} dans son terminal (double-clic), comme sur l’équipement réel.')
            return name
        except (ValueError, TypeError, KeyError) as error:
            self.error(error)
            return None

    def add_menu(self):
        """The toolbar's « Ajouter » : a short menu of device kinds, added at once (the full form last)."""
        import tkinter as tk
        menu = tk.Menu(self.window, tearoff=False)
        for label, kind in (('Routeur', 'router'), ('Switch', 'switch'), ('Pare-feu', 'firewall'), ('PC', 'host'),
                            ('Serveur', 'server')):
            menu.add_command(label=label, command=lambda k=kind: self.quick_add(k))
        menu.add_separator()
        menu.add_command(label='Options avancées…', command=self.add_device_dialog)
        menu.add_command(label='Modèles constructeur : cliquer ou glisser dans la bibliothèque', state='disabled')
        try:
            menu.tk_popup(self.window.winfo_pointerx(), self.window.winfo_pointery())
        finally:
            menu.grab_release()
        return menu

    def tile_released(self, event, kind, model):
        """A library tile released: on the canvas, the device goes where it was dropped; elsewhere, in view."""
        target = self.window.winfo_containing(event.x_root, event.y_root)
        at = None
        if target is self.canvas:
            at = (self.canvas.canvasx(event.x_root - self.canvas.winfo_rootx()),
                  self.canvas.canvasy(event.y_root - self.canvas.winfo_rooty()))
        return self.quick_add(kind, model, at)

    def auto_connect(self, first, second):
        """A cable between the first free port of each device (a new port when one has none left and can take one)."""
        try:
            spec = self.editing_spec()
            ends = []
            for name in (first, second):
                free = topology_edit.free_ports(spec, name)
                if not free:
                    port = topology_edit.next_port(spec, name)
                    spec = topology_edit.add_port(spec, name, port)
                    free = [port]
                ends.append((name, free[0]))
            result = topology_edit.connect(spec, *ends)
            self.commit_edit(result)
            shown = {name: port_names(next(n for n in result['nodes'] if n['name'] == name)) for name in (first, second)}
            self.note.set('Câble ' + ' ↔ '.join(f'{name} {shown[name].get(port, port)}' for name, port in ends) +
                          '. Un autre câble : choisir deux équipements · Échap pour sélectionner.')
            return ends
        except (ValueError, TypeError, KeyError) as error:
            self.error(error)
            return None

    def project_file(self, spec):
        """Where a project that was never saved goes: the projects folder, by its name (no file dialog)."""
        folder = projects_dir()
        folder.mkdir(parents=True, exist_ok=True)
        return Path(folder) / (spec['name'] + '.json')

    def device_double_click(self, name):
        """As in Packet Tracer: a running device opens its terminal; otherwise its configuration panel."""
        self.dragging = None
        self.choose_node(name)
        if self.states.get(name, {}).get('status') == 'running':
            self.open_console()
        else:
            self.device_tabs.select(self.config_panel)
            self.note.set(f'{name} n’est pas démarré : ▶ Démarrer, puis double-clic pour ouvrir son terminal.')
        return 'break'
