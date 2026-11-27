"""Soft native theme with a privately registered, licensed Inter font."""
import ctypes
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import font as tkfont,ttk
from .soft_widgets import surface

from .design import COLOURS

# The active design's colours (design.py): light for « classic », dark for « studio ».
BG=COLOURS['BG']
PANEL=COLOURS['PANEL']
SIDEBAR=COLOURS['SIDEBAR']
TEXT=COLOURS['TEXT']
MUTED=COLOURS['MUTED']
BLUE=COLOURS['BLUE']
GREEN=COLOURS['GREEN']
RED=COLOURS['RED']
TITLE=COLOURS['TITLE']
LINE=COLOURS['LINE']
FONT='DejaVu Sans'

# The rounded ttk surfaces, as (face, border) for normal, hover, pressed, disabled and selected.
# Black and white: white buttons with a grey edge (black under the pointer), black filled ones for the main actions.
ELEMENTS={
    'button':(('#ffffff','#d4d4d4'),('#f5f5f5','#111111'),('#e8e8e8','#111111'),('#ffffff','#ebebeb'),('#eeeeee','#111111')),
    'primary':(('#111111','#111111'),('#333333','#333333'),('#000000','#000000'),('#e6e6e6','#e6e6e6'),None),
    'rail':(('#ffffff','#ffffff'),('#f2f2f2','#f2f2f2'),('#e6e6e6','#e6e6e6'),('#ffffff','#ffffff'),('#111111','#111111')),
    'start':(('#111111','#111111'),('#333333','#333333'),('#000000','#000000'),('#e6e6e6','#e6e6e6'),None),
    'stop':(('#ffffff','#111111'),('#f2f2f2','#111111'),('#e6e6e6','#111111'),('#ffffff','#e6e6e6'),None),
    'entry':(('#ffffff','#cfcfcf'),('#ffffff','#111111'),('#ffffff','#111111'),('#f7f7f7','#e6e6e6'),None),
}


def choose_font(root):
    # Fontconfig application fonts are private to this process, not installed
    # into the user's desktop or system font directories.
    if sys.platform.startswith('linux'):
        try:
            fc=ctypes.CDLL('libfontconfig.so.1')
            fc.FcConfigGetCurrent.argtypes=[];fc.FcConfigGetCurrent.restype=ctypes.c_void_p
            fc.FcConfigAppFontAddFile.argtypes=[ctypes.c_void_p,ctypes.c_char_p];fc.FcConfigAppFontAddFile.restype=ctypes.c_int
            config=fc.FcConfigGetCurrent()
            if config:fc.FcConfigAppFontAddFile(config,os.fsencode(Path(__file__).with_name('assets')/'InterVariable.ttf'))
        except (OSError,AttributeError):pass
    families={name.casefold():name for name in tkfont.families(root)}
    for requested in ('Inter Variable','Inter','Noto Sans','Segoe UI','SF Pro Text','DejaVu Sans','Helvetica'):
        candidate=families.get(requested.casefold(),requested)
        actual=tkfont.Font(root=root,family=candidate,size=10).actual('family')
        if requested.startswith('Inter') and actual.casefold().replace(' ','').startswith('inter'):return actual
        if actual.casefold() in (requested.casefold(),candidate.casefold()):return actual
    return tkfont.nametofont('TkDefaultFont',root).actual('family')


def apply(root):
    font=choose_font(root);s=ttk.Style(root)
    # Every menu of the application (Fichier, Édition, « + Ajouter »…): white, the theme's font, a light grey highlight.
    menu_colours=('#ffffff','#eeeeee','#9a9a9a')
    for key,value in (('background',menu_colours[0]),('foreground',TEXT),('activeBackground',menu_colours[1]),('activeForeground',TEXT),
                      ('disabledForeground',menu_colours[2]),('relief','solid'),('borderWidth',1),('activeBorderWidth',0),
                      ('font',(font,9)),('selectColor',BLUE)):
        root.option_add('*Menu.'+key,value)
    # Disabled text: the menus' grey.
    off=menu_colours[2]
    s.configure('Native.TButton',background=BG,foreground=TEXT,font=(font,9),padding=(9,5),borderwidth=0)
    s.map('Native.TButton',foreground=[('disabled',off)])
    s.configure('Native.Toolbutton',background=BG,foreground=TEXT,font=(font,9),padding=(9,5),borderwidth=0)
    s.map('Native.Toolbutton',foreground=[('selected',BLUE),('disabled',off)])
    s.configure('Native.Primary.TButton',background=PANEL,foreground='white',font=(font,9,'bold'),padding=(9,5),borderwidth=0)
    s.map('Native.Primary.TButton',foreground=[('disabled','#5d7288')])
    s.configure('Native.TNotebook',background=BG,borderwidth=0,lightcolor=BG,darkcolor=BG,bordercolor=BG)
    s.configure('Native.TNotebook.Tab',padding=(10,5),font=(font,9),background=BG)
    s.map('Native.TNotebook.Tab',background=[('selected',PANEL)],foreground=[('selected',BLUE)])
    if not hasattr(root,'_native_soft_images'):
        images={}
        def element(name,normal,hover,pressed,disabled,selected=None):
            for key,(face,border) in dict(normal=normal,hover=hover,pressed=pressed,disabled=disabled,selected=selected or hover).items():images[name,key]=surface(root,face,border)
            s.element_create(name,'image',images[name,'normal'],('disabled',images[name,'disabled']),('pressed',images[name,'pressed']),('selected',images[name,'selected']),('active',images[name,'hover']),('focus',images[name,'hover']),border=8,padding=0,sticky='nswe')
        for key,states in ELEMENTS.items():
            element('Soft.'+key,*states)
        blank=tk.PhotoImage(master=root,width=1,height=2);blank.put(BG,to=(0,0,1,2))
        active=tk.PhotoImage(master=root,width=1,height=2);active.put(BLUE,to=(0,0,1,2))
        images['tabline']=(blank,active)
        s.element_create('Soft.tabline','image',blank,('selected',active),sticky='ew')
        root._native_soft_images=images
    for name,element in [('Native.Rail.TButton','Soft.rail'),('Native.TButton','Soft.button'),('Native.Toolbutton','Soft.button'),('Native.Primary.TButton','Soft.primary'),
                         ('Native.Start.TButton','Soft.start'),('Native.Stop.TButton','Soft.stop')]:
        s.layout(name,[(element,{'sticky':'nswe','children':[('Button.padding',{'sticky':'nswe','children':[('Button.label',{'sticky':'nswe'})]})]})])
    s.configure('Native.Rail.TButton',background=ELEMENTS['rail'][0][0],foreground='#edf4fa',font=(font,8),padding=(4,8),anchor='w')
    s.configure('Native.Start.TButton',background=BG,foreground='white',font=(font,9,'bold'),padding=(11,5),borderwidth=0)
    s.map('Native.Start.TButton',foreground=[('disabled','#71859d')])
    s.configure('Native.Stop.TButton',background=BG,foreground='#fca5a5',font=(font,9),padding=(10,5),
                borderwidth=0)
    s.map('Native.Stop.TButton',foreground=[('disabled','#5d7288')])
    s.layout('Native.TNotebook.Tab',[('Soft.button',{'sticky':'nswe','children':[('Notebook.padding',{'sticky':'nswe','children':[('Notebook.label',{'sticky':'nswe'})]})]})])
    s.layout('Native.Hidden.TNotebook.Tab',[]);s.configure('Native.Hidden.TNotebook',background=BG,borderwidth=0,lightcolor=BG,darkcolor=BG,bordercolor=BG)
    s.configure('Native.Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT,font=(font,9),rowheight=23,borderwidth=0)
    s.layout('Native.Treeview',[('Treeview.treearea',{'sticky':'nswe'})])
    s.configure('Native.Treeview.Heading',background='#132131',foreground=MUTED,
                font=(font,8,'bold'),padding=5,relief='flat')
    s.map('Native.Treeview',background=[('selected',COLOURS['SELECTED'])],foreground=[('selected',TEXT)])
    s.configure('Native.TEntry',background=PANEL,fieldbackground=COLOURS['FIELD'],foreground=TEXT,insertcolor=TEXT,font=(font,9),
                padding=5)
    s.layout('Native.TEntry',[('Soft.entry',{'sticky':'nswe','children':[('Entry.padding',{'sticky':'nswe','children':[('Entry.textarea',{'sticky':'nswe'})]})]})])
    s.configure('Native.TCombobox',background=PANEL,fieldbackground=COLOURS['FIELD'],foreground=TEXT,font=(font,9),padding=5,
                arrowsize=11,arrowcolor=MUTED)
    s.map('Native.TCombobox',fieldbackground=[('readonly',COLOURS['FIELD'])],foreground=[('readonly',TEXT)])
    s.layout('Native.TCombobox',[('Soft.entry',{'sticky':'nswe','children':[('Combobox.downarrow',{'side':'right','sticky':'ns'}),('Combobox.padding',{'sticky':'nswe','children':[('Combobox.textarea',{'sticky':'nswe'})]})]})])
    s.configure('Native.TCheckbutton',background=PANEL,foreground=TEXT,font=(font,9))
    for orient in ('Vertical','Horizontal'):
        if 'Soft.'+orient+'.Scrollbar.thumb' not in s.element_names():
            shade='#c8c8c8'
            thumb=surface(root,shade,shade,radius=6,size=12)
            root._native_soft_images['thumb',orient]=thumb
            s.element_create('Soft.'+orient+'.Scrollbar.thumb','image',thumb,border=5,sticky='nswe',width=10 if orient=='Vertical' else 24,height=24 if orient=='Vertical' else 10)
        s.configure('Native.'+orient+'.TScrollbar',background=BG,troughcolor=PANEL,arrowsize=10,borderwidth=0,troughborderwidth=0,bordercolor=PANEL,lightcolor=PANEL,darkcolor=PANEL)
        s.layout('Native.'+orient+'.TScrollbar',[(orient+'.Scrollbar.trough',{'sticky':'nswe','children':[('Soft.'+orient+'.Scrollbar.thumb',{'sticky':'nswe','expand':1})]})])
    base_styles(root,s,font)
    return font


def base_styles(root,s,font):
    """The plain ttk styles too (dialogs and panels that do not use the Native ones), and the lists of the comboboxes, with
    the theme's font; their colours come out black and white (design.tone)."""
    field=COLOURS['FIELD']
    s.configure('.',background=PANEL,foreground=TEXT,fieldbackground=field,bordercolor=LINE,lightcolor=PANEL,darkcolor=PANEL,
                troughcolor=BG,selectbackground=COLOURS['SELECTED'],selectforeground=TEXT,insertcolor=TEXT)
    s.map('.',background=[('disabled',PANEL)],foreground=[('disabled','#5d7288')])
    s.configure('TButton',background='#132131',foreground=TEXT,bordercolor='#23364a',lightcolor='#132131',darkcolor='#132131')
    s.map('TButton',background=[('active','#1a2c40'),('pressed','#1e3a5f')],foreground=[('disabled','#5d7288')])
    s.configure('Accent.TButton',background='#2563eb',foreground='white')
    s.map('Accent.TButton',background=[('active','#3b82f6')])
    s.configure('TEntry',fieldbackground=field,foreground=TEXT,insertcolor=TEXT,bordercolor='#23364a')
    s.configure('TCombobox',fieldbackground=field,foreground=TEXT,arrowcolor=MUTED,bordercolor='#23364a')
    s.map('TCombobox',fieldbackground=[('readonly',field)],foreground=[('readonly',TEXT)])
    s.configure('TNotebook',background=BG)
    s.configure('TNotebook.Tab',background=PANEL,foreground=MUTED)
    s.map('TNotebook.Tab',background=[('selected','#132131')],foreground=[('selected',TEXT)])
    s.configure('Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT)
    s.configure('Treeview.Heading',background='#132131',foreground=MUTED)
    s.map('Treeview',background=[('selected',COLOURS['SELECTED'])])
    s.configure('TPanedwindow',background=BG)
    s.configure('Sash',sashthickness=4,gripcount=0,background=BG,lightcolor=BG,bordercolor=BG)
    for kind in ('TCheckbutton','TRadiobutton'):
        s.configure(kind,background=PANEL,foreground=TEXT,indicatorbackground=field,indicatorforeground=TEXT)
        s.map(kind,background=[('active',PANEL)])
    s.configure('TLabel',background=PANEL,foreground=TEXT)
    s.configure('TFrame',background=PANEL)
    for key,value in (('background',field),('foreground',TEXT),('selectBackground',COLOURS['SELECTED']),('selectForeground',TEXT),
                      ('font',(font,9))):
        root.option_add('*TCombobox*Listbox.'+key,value)
    root.configure(bg=BG)
