"""Soft native theme with a privately registered, licensed Inter font."""
import ctypes
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import font as tkfont,ttk
from .soft_widgets import surface

from .design import COLOURS,STUDIO

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
ELEMENTS_CLASSIC={
    'button':(('#f9fbfe','#e0e8f2'),('#eaf3ff','#b9d9fc'),('#ddecff','#9fc8f9'),('#f0f4f8','#e1e8f0'),('#e4f0ff','#9cc9ff')),
    'primary':(('#087fe9','#087fe9'),('#168df4','#168df4'),('#0067ce','#0067ce'),('#e1ebf7','#e1ebf7'),None),
    'rail':(('#253440','#253440'),('#364f64','#364f64'),('#3c5d79','#3c5d79'),('#253440','#253440'),None),
    'start':(('#1f9d55','#1f9d55'),('#24b062','#24b062'),('#178245','#178245'),('#e1ebf7','#e1ebf7'),None),
    'stop':(('#fff5f5','#f0c9c9'),('#ffe9e9','#e7a8a8'),('#ffdcdc','#df9090'),('#f0f4f8','#e1e8f0'),None),
    'entry':(('#ffffff','#dae4ef'),('#ffffff','#8bbcf5'),('#ffffff','#7fb5f1'),('#f3f6fa','#e3eaf2'),None),
}
ELEMENTS_STUDIO={
    'button':(('#132131','#23364a'),('#1a2c40','#2f4b68'),('#1e3a5f','#3b82f6'),('#0f1922','#1a2836'),('#1e3a5f','#3b82f6')),
    'primary':(('#2563eb','#2563eb'),('#3b82f6','#3b82f6'),('#1d4ed8','#1d4ed8'),('#1a2836','#1a2836'),None),
    'rail':(('#16273a','#16273a'),('#1e3a5f','#1e3a5f'),('#2563eb','#2563eb'),('#111c27','#111c27'),('#1d4ed8','#1d4ed8')),
    'start':(('#16a34a','#16a34a'),('#22c55e','#22c55e'),('#15803d','#15803d'),('#1a2836','#1a2836'),None),
    'stop':(('#2a1416','#5b2a2e'),('#3a1a1d','#7f2d33'),('#4a1c20','#b91c1c'),('#0f1922','#1a2836'),None),
    'entry':(('#0c141d','#23364a'),('#0c141d','#3b82f6'),('#0c141d','#60a5fa'),('#0f1922','#1a2836'),None),
}
ELEMENTS=ELEMENTS_STUDIO if STUDIO else ELEMENTS_CLASSIC


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
    # Every menu of the application (Fichier, Édition, « + Ajouter »…): white, the theme's font, a soft blue highlight.
    menu_colours=(('#121e2a','#1e3a5f','#5d7288') if STUDIO else ('#ffffff','#e4f0ff','#8a98aa'))
    for key,value in (('background',menu_colours[0]),('foreground',TEXT),('activeBackground',menu_colours[1]),('activeForeground',TEXT),
                      ('disabledForeground',menu_colours[2]),('relief','solid'),('borderWidth',1),('activeBorderWidth',0),
                      ('font',(font,9)),('selectColor',BLUE)):
        root.option_add('*Menu.'+key,value)
    s.configure('Native.TButton',background=BG,foreground=TEXT,font=(font,9),padding=(9,5),borderwidth=0)
    s.map('Native.TButton',foreground=[('disabled','#8a98aa')])
    s.configure('Native.Toolbutton',background=BG,foreground=TEXT,font=(font,9),padding=(9,5),borderwidth=0)
    s.map('Native.Toolbutton',foreground=[('selected',BLUE),('disabled','#8a98aa')])
    s.configure('Native.Primary.TButton',background=PANEL,foreground='white',font=(font,9,'bold'),padding=(9,5),borderwidth=0)
    s.map('Native.Primary.TButton',foreground=[('disabled','#71859d')])
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
    s.configure('Native.Stop.TButton',background=BG,foreground='#fca5a5' if STUDIO else '#b42323',font=(font,9),padding=(10,5),
                borderwidth=0)
    s.map('Native.Stop.TButton',foreground=[('disabled','#5d7288' if STUDIO else '#8a98aa')])
    s.layout('Native.TNotebook.Tab',[('Soft.button',{'sticky':'nswe','children':[('Notebook.padding',{'sticky':'nswe','children':[('Notebook.label',{'sticky':'nswe'})]})]})])
    s.layout('Native.Hidden.TNotebook.Tab',[]);s.configure('Native.Hidden.TNotebook',background=BG,borderwidth=0,lightcolor=BG,darkcolor=BG,bordercolor=BG)
    s.configure('Native.Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT,font=(font,9),rowheight=23,borderwidth=0)
    s.layout('Native.Treeview',[('Treeview.treearea',{'sticky':'nswe'})])
    s.configure('Native.Treeview.Heading',background='#132131' if STUDIO else '#f3f6fa',foreground=MUTED if STUDIO else TEXT,
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
            shade='#24384d' if STUDIO else '#c4d4e6'
            thumb=surface(root,shade,shade,radius=6,size=12)
            root._native_soft_images['thumb',orient]=thumb
            s.element_create('Soft.'+orient+'.Scrollbar.thumb','image',thumb,border=5,sticky='nswe',width=10 if orient=='Vertical' else 24,height=24 if orient=='Vertical' else 10)
        s.configure('Native.'+orient+'.TScrollbar',background=BG,troughcolor=PANEL,arrowsize=10,borderwidth=0,troughborderwidth=0,bordercolor=PANEL,lightcolor=PANEL,darkcolor=PANEL)
        s.layout('Native.'+orient+'.TScrollbar',[(orient+'.Scrollbar.trough',{'sticky':'nswe','children':[('Soft.'+orient+'.Scrollbar.thumb',{'sticky':'nswe','expand':1})]})])
    if STUDIO:
        dark_base(root,s,font)
    return font


def dark_base(root,s,font):
    """Under studio, the plain ttk styles too (dialogs and panels that do not use the Native ones), and the lists of the
    comboboxes: dark, with the theme's font."""
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
