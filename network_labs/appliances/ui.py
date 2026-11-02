"""Native lab workbench. Desktop stays unprivileged; sudo runs in a terminal."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..layout import fit_dialog
from .catalog import capabilities
from .runtime import plan
from .spec import example, validate


class ApplianceWindow:
    def __init__(self, app):
        self.app = app
        self.path = None
        self.window = tk.Toplevel(app.root)
        self.window.title('Network LABS · Micro-nodes natifs (expérimental)')
        self.window.geometry('960x680')
        fit_dialog(self.window, 960, 680)
        self.window.columnconfigure(0, weight=1); self.window.rowconfigure(1, weight=1)
        ttk.Label(self.window, text='Micro-nodes Linux / microVMs · laboratoire distinct du canvas pédagogique',
                  padding=12).grid(row=0, column=0, sticky='ew')
        tabs = ttk.Notebook(self.window); tabs.grid(row=1, column=0, sticky='nsew', padx=12)
        diagnostics = ttk.Frame(tabs); editor = ttk.Frame(tabs); output = ttk.Frame(tabs)
        tabs.add(diagnostics, text='Runtimes et dépendances'); tabs.add(editor, text='Manifest du lab'); tabs.add(output, text='Validation / plan')
        self.table = ttk.Treeview(diagnostics, columns=('runtime', 'implementation', 'detected', 'scope'), show='headings', height=10)
        for key, title, width in [('runtime', 'Technologie', 130), ('implementation', 'Implémentation', 110),
                                  ('detected', 'Prérequis détectés', 125), ('scope', 'Périmètre', 530)]:
            self.table.heading(key, text=title); self.table.column(key, width=width, minwidth=80, stretch=key == 'scope')
        self.table.pack(fill='both', expand=True)
        horizontal = ttk.Scrollbar(diagnostics, orient='horizontal', command=self.table.xview)
        self.table.configure(xscrollcommand=horizontal.set); horizontal.pack(fill='x')
        ttk.Label(diagnostics, text='Détection ≠ démarrage vérifié. Research = aucun adaptateur exécutable.\n'
                  'OCI : commandes Linux réelles. Firecracker : kernel/disque fournis, console fichier, sans agent exec.\n'
                  'Wasm conserve son propre réseau ; aucun pont Wasm ↔ Linux n’est annoncé.', wraplength=850, padding=12).pack(fill='x')
        ttk.Button(diagnostics, text='Actualiser le diagnostic', command=self.refresh).pack(anchor='w', padx=12, pady=8)
        self.editor = self.text_area(editor)
        self.output = self.text_area(output); self.output.configure(state='disabled')
        self.editor.insert('1.0', json.dumps(example(Path.home() / 'network-labs-rootfs'), indent=2))
        bar = ttk.Frame(self.window, padding=10); bar.grid(row=2, column=0, sticky='ew')
        for text, action in [('Ouvrir', self.open), ('Enregistrer', self.save), ('Valider / plan', self.preview),
                             ('Démarrer', lambda: self.launch('start')), ('État', lambda: self.launch('status')),
                             ('Arrêter', lambda: self.launch('stop'))]:
            ttk.Button(bar, text=text, command=action).pack(side='left', padx=3)
        ttk.Label(self.window, text='Démarrage / arrêt : terminal externe avec sudo ; la GUI reste sans privilèges. '
                  'Voir docs/HYBRID_APPLIANCES.md pour préparer le rootfs.', wraplength=880, padding=12).grid(row=3, column=0, sticky='ew')
        self.tabs = tabs; self.refresh()

    def text_area(self, parent):
        parent.rowconfigure(0, weight=1); parent.columnconfigure(0, weight=1)
        text = tk.Text(parent, wrap='none', font=('DejaVu Sans Mono', 10), undo=True)
        scrollbar = ttk.Scrollbar(parent, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.grid(row=0, column=0, sticky='nsew'); scrollbar.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(parent, orient='horizontal', command=text.xview)
        text.configure(xscrollcommand=horizontal.set); horizontal.grid(row=1, column=0, sticky='ew')
        return text

    def refresh(self):
        self.table.delete(*self.table.get_children())
        for runtime in capabilities()['runtimes']:
            self.table.insert('', 'end', values=(runtime['id'], runtime['implementation'],
                              'oui' if runtime['prerequisites_detected'] else 'non', runtime['scope']))

    def manifest(self):
        return validate(json.loads(self.editor.get('1.0', 'end-1c')))

    def error(self, error):
        messagebox.showerror('Micro-nodes natifs', str(error), parent=self.window)

    def preview(self):
        try:
            report = plan(self.manifest())
        except (ValueError, TypeError, KeyError) as error:
            self.error(error); return False
        self.output.configure(state='normal'); self.output.delete('1.0', 'end')
        self.output.insert('1.0', json.dumps(report, ensure_ascii=False, indent=2)); self.output.configure(state='disabled')
        self.tabs.select(2); return True

    def open(self):
        path = filedialog.askopenfilename(parent=self.window, filetypes=[('Native lab JSON', '*.json')])
        if path:
            try:
                content = Path(path).read_text(encoding='utf-8')
                validate(json.loads(content))
            except (OSError, ValueError, TypeError, KeyError) as error:
                self.error(error); return
            self.path = Path(path); self.editor.delete('1.0', 'end'); self.editor.insert('1.0', content)
            self.tabs.select(1)

    def save(self):
        try:
            spec = self.manifest()
            path = self.path or filedialog.asksaveasfilename(parent=self.window, defaultextension='.json', filetypes=[('Native lab JSON', '*.json')])
            if not path:
                return False
            self.path = Path(path).resolve(); self.path.write_text(json.dumps(spec, indent=2), encoding='utf-8')
            return True
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.error(error); return False

    def launch(self, action):
        try:
            if action == 'start':
                if not self.save():
                    return
                target = str(self.path)
            else:
                target = self.manifest()['name']
            terminal = shutil.which('x-terminal-emulator') or shutil.which('xterm')
            if not terminal:
                raise ValueError('Installer un terminal x-terminal-emulator/xterm, ou utiliser les commandes du guide.')
            if not shutil.which('sudo'):
                raise ValueError('sudo absent ; utiliser la CLI depuis un terminal administrateur.')
            # Pass argv without shell parsing. The unprivileged wrapper keeps results visible.
            source = Path(__file__).resolve().parents[2]
            code = 'import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("network_labs.appliances",run_name="__main__")'
            wrapper = 'import subprocess,sys;r=subprocess.run(sys.argv[1:]);input("Entrée pour fermer…");sys.exit(r.returncode)'
            subprocess.Popen([terminal, '-e', sys.executable, '-c', wrapper, 'sudo',
                              sys.executable, '-c', code, str(source), action, target], cwd=source)
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.error(error)
