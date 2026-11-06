"""Native-only palette and typography sampled from the supplied GUI reference."""
import tkinter as tk
from tkinter import ttk

BG='#f1f4f9'
PANEL='#ffffff'
SIDEBAR='#eef3f9'
TEXT='#172c43'
MUTED='#66788f'
BLUE='#007ce5'
GREEN='#24c52c'
RED='#df1723'
TITLE='#243746'
FONT='Liberation Sans'


def apply(root):
    s=ttk.Style(root)
    s.configure('Native.TButton',background=BG,foreground=TEXT,font=(FONT,8),padding=(7,4),borderwidth=0)
    s.map('Native.TButton',background=[('active','#e0efff')])
    s.configure('Native.Primary.TButton',background=BLUE,foreground='white',font=(FONT,8,'bold'),padding=(7,4),borderwidth=0)
    s.map('Native.Primary.TButton',background=[('active','#0067c4')])
    s.configure('Native.TNotebook',background=BG,borderwidth=0,lightcolor='#d9e2ee',darkcolor='#d9e2ee',bordercolor='#d9e2ee')
    s.configure('Native.TNotebook.Tab',padding=(10,5),font=(FONT,8),background=BG)
    s.map('Native.TNotebook.Tab',background=[('selected',PANEL)],foreground=[('selected',BLUE)])
    # Remove the old raised tab silhouette. Keep an actual selected blue line.
    if not hasattr(root,'_native_reference_images'):
        blank=tk.PhotoImage(master=root,width=1,height=2);blank.put(BG,to=(0,0,1,2))
        active=tk.PhotoImage(master=root,width=1,height=2);active.put(BLUE,to=(0,0,1,2))
        root._native_reference_images=(blank,active)
        s.element_create('Reference.tabline','image',blank,('selected',active),sticky='ew')
    s.layout('Native.TNotebook.Tab',[('Notebook.padding',{'sticky':'nswe','children':[('Notebook.label',{'sticky':'nswe'})]}),('Reference.tabline',{'side':'bottom','sticky':'ew'})])
    s.layout('Native.Hidden.TNotebook.Tab',[])
    s.configure('Native.Hidden.TNotebook',background=PANEL,borderwidth=0)
    s.configure('Native.Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT,font=(FONT,8),rowheight=21,borderwidth=0)
    s.configure('Native.Treeview.Heading',background='#f0f4f8',foreground=TEXT,font=(FONT,8,'bold'),padding=5,relief='flat')
    s.map('Native.Treeview',background=[('selected','#ddecff')],foreground=[('selected',TEXT)])
    s.configure('Native.TEntry',fieldbackground=PANEL,foreground=TEXT,font=(FONT,8),padding=4,bordercolor='#d6e0eb',lightcolor='#d6e0eb',darkcolor='#d6e0eb')
    s.configure('Native.TCombobox',fieldbackground=PANEL,foreground=TEXT,font=(FONT,8),padding=4)
    s.map('Native.TCombobox',fieldbackground=[('readonly',PANEL)],foreground=[('readonly',TEXT)])
    s.configure('Native.TCheckbutton',background=PANEL,foreground=TEXT,font=(FONT,8))
