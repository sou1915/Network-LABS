"""Soft native theme with a privately registered, licensed Inter font."""
import ctypes
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import font as tkfont,ttk
from .soft_widgets import surface

BG='#f1f4f9'
PANEL='#ffffff'
SIDEBAR='#eef3f9'
TEXT='#172c43'
MUTED='#66788f'
BLUE='#007ce5'
GREEN='#24c52c'
RED='#df1723'
TITLE='#243746'
FONT='DejaVu Sans'


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
    s.configure('Native.TButton',background=BG,foreground=TEXT,font=(font,9),padding=(9,5),borderwidth=0)
    s.map('Native.TButton',foreground=[('disabled','#8a98aa')])
    s.configure('Native.Toolbutton',background=BG,foreground=TEXT,font=(font,9),padding=(9,5),borderwidth=0)
    s.map('Native.Toolbutton',foreground=[('selected',BLUE),('disabled','#8a98aa')])
    s.configure('Native.Primary.TButton',background=PANEL,foreground='white',font=(font,9,'bold'),padding=(9,5),borderwidth=0)
    s.map('Native.Primary.TButton',foreground=[('disabled','#71859d')])
    s.configure('Native.TNotebook',background=BG,borderwidth=0,lightcolor='#e4ebf3',darkcolor='#e4ebf3',bordercolor='#e4ebf3')
    s.configure('Native.TNotebook.Tab',padding=(10,5),font=(font,9),background=BG)
    s.map('Native.TNotebook.Tab',background=[('selected',PANEL)],foreground=[('selected',BLUE)])
    if not hasattr(root,'_native_soft_images'):
        images={}
        def element(name,normal,hover,pressed,disabled,selected=None):
            for key,(face,border) in dict(normal=normal,hover=hover,pressed=pressed,disabled=disabled,selected=selected or hover).items():images[name,key]=surface(root,face,border)
            s.element_create(name,'image',images[name,'normal'],('disabled',images[name,'disabled']),('pressed',images[name,'pressed']),('selected',images[name,'selected']),('active',images[name,'hover']),('focus',images[name,'hover']),border=8,padding=0,sticky='nswe')
        element('Soft.button',('#f9fbfe','#e0e8f2'),('#eaf3ff','#b9d9fc'),('#ddecff','#9fc8f9'),('#f0f4f8','#e1e8f0'),('#e4f0ff','#9cc9ff'))
        element('Soft.primary',('#087fe9','#087fe9'),('#168df4','#168df4'),('#0067ce','#0067ce'),('#e1ebf7','#e1ebf7'))
        element('Soft.entry',('#ffffff','#dae4ef'),('#ffffff','#8bbcf5'),('#ffffff','#7fb5f1'),('#f3f6fa','#e3eaf2'))
        blank=tk.PhotoImage(master=root,width=1,height=2);blank.put(BG,to=(0,0,1,2))
        active=tk.PhotoImage(master=root,width=1,height=2);active.put(BLUE,to=(0,0,1,2))
        images['tabline']=(blank,active)
        s.element_create('Soft.tabline','image',blank,('selected',active),sticky='ew')
        root._native_soft_images=images
    for name,element in [('Native.TButton','Soft.button'),('Native.Toolbutton','Soft.button'),('Native.Primary.TButton','Soft.primary')]:
        s.layout(name,[(element,{'sticky':'nswe','children':[('Button.padding',{'sticky':'nswe','children':[('Button.label',{'sticky':'nswe'})]})]})])
    s.layout('Native.TNotebook.Tab',[('Notebook.padding',{'sticky':'nswe','children':[('Notebook.label',{'sticky':'nswe'})]}),('Soft.tabline',{'side':'bottom','sticky':'ew'})])
    s.layout('Native.Hidden.TNotebook.Tab',[]);s.configure('Native.Hidden.TNotebook',background=PANEL,borderwidth=0)
    s.configure('Native.Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT,font=(font,9),rowheight=23,borderwidth=0)
    s.configure('Native.Treeview.Heading',background='#f3f6fa',foreground=TEXT,font=(font,8,'bold'),padding=5,relief='flat')
    s.map('Native.Treeview',background=[('selected','#e4f0ff')],foreground=[('selected',TEXT)])
    s.configure('Native.TEntry',background=PANEL,fieldbackground=PANEL,foreground=TEXT,font=(font,9),padding=5)
    s.layout('Native.TEntry',[('Soft.entry',{'sticky':'nswe','children':[('Entry.padding',{'sticky':'nswe','children':[('Entry.textarea',{'sticky':'nswe'})]})]})])
    s.configure('Native.TCombobox',background=PANEL,fieldbackground=PANEL,foreground=TEXT,font=(font,9),padding=5,arrowsize=11)
    s.map('Native.TCombobox',fieldbackground=[('readonly',PANEL)],foreground=[('readonly',TEXT)])
    s.layout('Native.TCombobox',[('Soft.entry',{'sticky':'nswe','children':[('Combobox.downarrow',{'side':'right','sticky':'ns'}),('Combobox.padding',{'sticky':'nswe','children':[('Combobox.textarea',{'sticky':'nswe'})]})]})])
    s.configure('Native.TCheckbutton',background=PANEL,foreground=TEXT,font=(font,9))
    return font
