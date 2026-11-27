"""The command catalogue window: every command the selected node's terminal accepts, searchable, with examples.

The terminal stays where commands are typed; this window helps find them. Examples use the node's own port names
and addresses, and « Copier l’exemple » puts the lines on the clipboard, ready to paste into the node's terminal.
"""
import tkinter as tk
from tkinter import ttk

from . import command_catalogue
from .reference_theme import BG, BLUE, MUTED, PANEL, TEXT
from .vendor_config import TITLES

ALL_TOPICS = 'Tous les sujets'


class CatalogueWindow:
    def __init__(self, parent, node, font='DejaVu Sans'):
        self.node, self.font = node, font
        self.syntax = command_catalogue.syntax_of(node)
        self.window = tk.Toplevel(parent)
        title = TITLES.get(self.syntax, 'shell BusyBox')
        self.window.title(f'Catalogue de commandes · {node["name"]} ({title})')
        self.window.configure(bg=BG)
        self.window.geometry('980x640')
        self.window.minsize(720, 460)
        top = tk.Frame(self.window, bg=BG)
        top.pack(fill='x', padx=14, pady=(12, 6))
        tk.Label(top, text=f'{node["name"]} · {title}', bg=BG, fg=TEXT, font=(font, 13, 'bold')).pack(anchor='w')
        tk.Label(top, text='Les commandes que le terminal du nœud accepte, vérifiées par les tests. Taper les commandes dans le '
                 'terminal ; « ? » et « help SUJET » y donnent la même aide, Tab complète les mots.', bg=BG, fg=MUTED,
                 font=(font, 9), justify='left', wraplength=900).pack(anchor='w', pady=(2, 8))
        filters = tk.Frame(top, bg=BG)
        filters.pack(fill='x')
        tk.Label(filters, text='Rechercher', bg=BG, fg=MUTED, font=(font, 9)).pack(side='left')
        self.query = tk.StringVar()
        entry = ttk.Entry(filters, textvariable=self.query, width=34)
        entry.pack(side='left', padx=(6, 14))
        tk.Label(filters, text='Sujet', bg=BG, fg=MUTED, font=(font, 9)).pack(side='left')
        self.topic = tk.StringVar(value=ALL_TOPICS)
        self.topics = ttk.Combobox(filters, textvariable=self.topic, state='readonly', width=22,
                                   values=[ALL_TOPICS] + command_catalogue.topics(node))
        self.topics.pack(side='left', padx=6)
        self.count = tk.StringVar()
        tk.Label(filters, textvariable=self.count, bg=BG, fg=MUTED, font=(font, 9)).pack(side='right')

        body = ttk.PanedWindow(self.window, orient='vertical')
        body.pack(fill='both', expand=True, padx=14, pady=6)
        table = tk.Frame(body, bg=PANEL)
        self.table = ttk.Treeview(table, columns=('mode', 'syntax', 'help'), show='tree headings', selectmode='browse')
        self.table.heading('#0', text='Sujet')
        self.table.heading('mode', text='Mode')
        self.table.heading('syntax', text='Commande')
        self.table.heading('help', text='Rôle')
        self.table.column('#0', width=130, stretch=False)
        self.table.column('mode', width=120, stretch=False)
        self.table.column('syntax', width=360)
        self.table.column('help', width=330)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        body.add(table, weight=3)
        detail = tk.Frame(body, bg=BG)
        self.heading = tk.StringVar(value='Choisir une commande pour voir son exemple.')
        tk.Label(detail, textvariable=self.heading, bg=BG, fg=TEXT, font=(font, 10, 'bold'), anchor='w',
                 justify='left', wraplength=900).pack(fill='x', pady=(6, 2))
        self.where = tk.StringVar()
        tk.Label(detail, textvariable=self.where, bg=BG, fg=MUTED, font=(font, 9), anchor='w', justify='left',
                 wraplength=900).pack(fill='x')
        self.example = tk.Text(detail, height=7, bg='#0b1220', fg='#d7e3f4', insertbackground='#d7e3f4',
                               font=('DejaVu Sans Mono', 10), relief='flat', padx=10, pady=8)
        self.example.pack(fill='both', expand=True, pady=6)
        buttons = tk.Frame(detail, bg=BG)
        buttons.pack(fill='x')
        self.copy_button = ttk.Button(buttons, text='Copier l’exemple', command=self.copy)
        self.copy_button.pack(side='left')
        self.copied = tk.StringVar()
        tk.Label(buttons, textvariable=self.copied, bg=BG, fg=BLUE, font=(font, 9)).pack(side='left', padx=10)
        body.add(detail, weight=2)

        self.rows = {}
        self.query.trace_add('write', lambda *_: self.fill())
        self.topics.bind('<<ComboboxSelected>>', lambda _: self.fill())
        self.table.bind('<<TreeviewSelect>>', lambda _: self.show())
        self.table.bind('<Double-1>', lambda _: self.copy())
        self.fill()
        entry.focus_set()

    def fill(self):
        topic = None if self.topic.get() == ALL_TOPICS else self.topic.get()
        found = command_catalogue.search(self.node, self.query.get(), topic=topic)
        self.table.delete(*self.table.get_children())
        self.rows = {}
        for index, entry in enumerate(found):
            item = self.table.insert('', 'end', text=entry['topic'], values=(entry['mode'], entry['syntax'], entry['help']))
            self.rows[item] = entry
            if index == 0:
                self.table.selection_set(item)
        self.count.set(f'{len(found)} commande' + ('s' if len(found) > 1 else ''))
        if not found:
            self.heading.set('Aucune commande ne correspond.')
            self.where.set('')
            self._example('')

    def selected(self):
        chosen = self.table.selection()
        return self.rows.get(chosen[0]) if chosen else None

    def show(self):
        entry = self.selected()
        if entry is None:
            return
        self.heading.set(f'{entry["syntax"]} — {entry["help"]}')
        modes = command_catalogue.MODES.get(self.syntax, {})
        self.where.set(f'Mode {entry["mode"]} : {modes.get(entry["mode"], "")}')
        self._example('\n'.join(entry['example']))
        self.copied.set('')

    def _example(self, text):
        self.example.configure(state='normal')
        self.example.delete('1.0', 'end')
        self.example.insert('1.0', text)
        self.example.configure(state='disabled')

    def copy(self):
        entry = self.selected()
        if entry is None:
            return ''
        text = '\n'.join(entry['example'])
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.copied.set('Copié : coller dans le terminal du nœud (mode ' + entry['mode'] + ').')
        return text
