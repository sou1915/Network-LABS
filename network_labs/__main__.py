"""Network LABS desktop: the micro-VM workbench (Firecracker micro-VMs and OCI containers, missions, scenarios)."""
import argparse
import os
import tkinter as tk
from tkinter import ttk

from .layout import initial_geometry
from .theme import BG, PANEL, CARD, LINE, TEXT, MUTED, TEAL, BLUE

FONT = ('DejaVu Sans', 10)


class App:
    """The desktop window that hosts the workbench (appliances.ui.ApplianceWindow), with the base ttk styles it uses."""

    def __init__(self, root):
        self.root = root
        self.native_lab_window = None
        root.title('Network LABS')
        width, height, x, y = initial_geometry(root.winfo_screenwidth(), root.winfo_screenheight())
        root.geometry(f'{width}x{height}+{x}+{y}')
        root.configure(bg=BG)

    def style(self):
        s = ttk.Style(self.root)
        s.theme_use('clam')
        s.configure('.', background=PANEL, foreground=TEXT, font=FONT)
        s.configure('TButton', background='#e8edf4', foreground=TEXT, padding=(10, 8), borderwidth=0)
        s.map('TButton', background=[('active', '#dce6f4')], foreground=[('disabled', MUTED)])
        s.configure('Small.TButton', padding=(7, 7), width=0)
        s.configure('Accent.TButton', background=BLUE, foreground='white')
        s.map('Accent.TButton', background=[('active', '#174fbb')])
        s.configure('TEntry', fieldbackground=BG, foreground=TEXT, insertcolor=TEAL, padding=6, bordercolor=LINE)
        s.configure('TCombobox', fieldbackground=BG, foreground=TEXT, padding=5, arrowcolor=TEAL)
        s.map('TCombobox', fieldbackground=[('readonly', BG)], foreground=[('readonly', TEXT)])
        self.root.option_add('*TCombobox*Listbox.background', PANEL)
        self.root.option_add('*TCombobox*Listbox.foreground', TEXT)
        s.configure('TNotebook', background=BG, borderwidth=0)
        s.configure('TNotebook.Tab', background=PANEL, padding=(15, 9), foreground=MUTED)
        s.map('TNotebook.Tab', background=[('selected', CARD)], foreground=[('selected', TEAL)])
        s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=26, borderwidth=0)
        s.configure('Treeview.Heading', background=CARD, foreground=MUTED, font=('DejaVu Sans', 9, 'bold'), padding=7, relief='flat')
        s.map('Treeview', background=[('selected', '#e1ebfb')], foreground=[('selected', TEXT)])
        s.configure('TPanedwindow', background=BG)
        s.configure('TScale', background=PANEL, troughcolor=BG)

    def pause(self):
        """Nothing runs behind the workbench any more (the old pedagogical simulator is gone)."""

    def open_native_lab(self):
        from .appliances.ui import ApplianceWindow
        previous = self.native_lab_window
        if previous is not None and previous.window.winfo_exists():
            previous.window.lift()
            return previous
        self.native_lab_window = ApplianceWindow(self, embedded=True)
        return self.native_lab_window


def main(arguments=None):
    parser = argparse.ArgumentParser(description='Network LABS desktop: micro-VM workbench, missions and scenarios')
    parser.add_argument('--native-lab', action='store_true', help='Accepted for compatibility: the workbench always opens.')
    parser.add_argument('--open', metavar='PROJET', help='Open this project file (JSON) at start.')
    parser.add_argument('--design', choices=('studio', 'classic'), help='The look of the workbench for this run.')
    options = parser.parse_args(arguments)
    # The design is chosen before the workbench's modules load: --design, else the saved choice, else Studio (the dark
    # design) for the application. Code that builds the workbench without main(), as the tests do, keeps classic.
    if options.design:
        os.environ['NETWORK_LABS_DESIGN'] = options.design
    elif not os.environ.get('NETWORK_LABS_DESIGN'):
        from .appliances.design_choice import chosen  # not design.py: it would fix the design before this choice
        os.environ['NETWORK_LABS_DESIGN'] = chosen() or 'studio'
    root = tk.Tk()
    window = App(root).open_native_lab()
    if options.open:
        open_project(window, options.open)
    root.mainloop()


def open_project(window, path):
    """Load PATH in WINDOW, as « Ouvrir » does; a file that cannot be read leaves the blank project and says why."""
    import json
    from tkinter import messagebox
    try:
        with open(path, encoding='utf-8') as handle:
            window.load_spec(json.load(handle), path)
    except (OSError, ValueError, TypeError, KeyError) as error:
        messagebox.showerror('Network LABS', f'Projet non ouvert : {path}\n{error}', parent=window.window)


if __name__ == '__main__':
    main()
