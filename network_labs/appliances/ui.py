"""Native topology and lifecycle workbench; sudo stays in an external terminal."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog,ttk
import uuid
import os
from ..layout import fit_dialog,ScrollPanel
from ..theme import BG,PANEL,CARD,LINE,TEXT,MUTED,TEAL,BLUE,RED
from .catalog import capabilities
from .runtime import plan
from .spec import example,validate
from . import topology_edit
from .campus import campus_example
from . import reference_theme
from .soft_widgets import SoftCard,SoftPanel,rounded_box
from .reference_theme import BG,PANEL,SIDEBAR,TEXT,MUTED,BLUE,GREEN as TEAL,RED
from .native_models import port_label,port_names
from .workspace_art import port_offset,draw_device,access_vlans,auto_layout,layout_bounds,networks,firewall_hosts,link_caption,draw_port_labels
from .workspace_art import vlan_groups
from .missions_ui import MissionsPanel
from .ui_quick import QuickEditing,blank_project
from .ui_overview import DeviceOverview
from .ui_bridge import SOURCE,client_args,private_json,public_topology,read_result,validate_request,validate_topology


def launch_terminal(command):
    terminal=shutil.which('x-terminal-emulator') or shutil.which('xterm')
    if not terminal or not shutil.which('sudo'):
        raise ValueError('Installer un terminal x-terminal-emulator/xterm et sudo pour le contrôle natif.')
    # Plain xterm needs -u8 for the accents of the French messages; x-terminal-emulator already speaks UTF-8.
    options=['-u8'] if Path(terminal).name=='xterm' else []
    environment=dict(os.environ)
    if 'utf' not in (environment.get('LC_ALL') or environment.get('LC_CTYPE') or environment.get('LANG') or '').lower().replace('-',''):
        environment['LC_ALL']='C.UTF-8'  # without a UTF-8 locale xterm shows the accents as Ã©
    return subprocess.Popen([terminal,*options,'-e',*command],cwd=SOURCE,env=environment)


class ApplianceWindow(MissionsPanel,QuickEditing,DeviceOverview):
    def __init__(self,app,*,embedded=False):
        self.app=app;self.path=None;self.pending=None;self.poll_id=None;self.closed=False;self.last_response=None;self.web_portal=None
        # Use the established desktop's theme and device artwork. Native state
        # stays separate from the pedagogical Session/model behind that desktop.
        from ..__main__ import App
        self.root=app.root;self.embedded=embedded;self.previous_widgets=[]
        App.style(self)
        self.font=reference_theme.apply(self.root)
        if self.embedded:
            app.pause()
            for widget in app.root.pack_slaves():
                self.previous_widgets.append((widget,widget.pack_info()));widget.pack_forget()
            self.window=tk.Frame(app.root,bg=BG);self.window.pack(fill='both',expand=True)
            self.previous_save=app.root.bind('<Control-s>')
            app.root.bind('<Control-s>',lambda event:self.save())
        else:
            self.window=tk.Toplevel(app.root);self.window.title('Network LABS · LAN natif')
            fit_dialog(self.window,1280,800);self.window.configure(bg=BG)
            self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.columnconfigure(0,weight=1);self.window.rowconfigure(3,weight=1)
        self.layout_id=None;self.config_key=None;self.config_baseline=None;self.positions={};self.zoom=1.;self.panning=False;self.drag_moved=False;self.edit_mode=None;self.cable_source=None;self.dragging=None
        self.tool_mode=tk.StringVar(value='select');self.buttons=[]
        header_card=SoftCard(self.window,BG,face='#223344',border='#223344');header_card.grid(row=0,column=0,sticky='ew',padx=4,pady=(3,1));header=header_card.inner
        self.label(header,'◉  Network LABS','#ffffff',9,True).pack(side='left')
        self.project_title=tk.StringVar(value='Projet LAN')
        tk.Label(header,textvariable=self.project_title,bg='#223344',fg='#d6e2ee',font=(self.font,8)).pack(side='left',padx=18)
        files=[('Nouveau LAN',self.new),('Campus entreprise',self.new_campus),('LAN sécurité access',lambda:self.new_campus(security=True)),
               ('Ouvrir',self.open),('Enregistrer',self.save),('Enregistrer sous…',lambda:self.save(ask=True))]
        edits=[('Ajouter un équipement',self.add_menu),('Ajouter (options avancées)…',self.add_device_dialog),
               ('Connecter un câble',lambda:self.set_edit_mode('cable')),('Supprimer',self.delete_selected)]
        for title,commands in [('Fichier',files),
                               ('Édition',edits),
                               ('Affichage',[('Topologie',lambda:self.tabs.select(self.topology_tab)),('Configuration du projet',lambda:self.tabs.select(self.editor_tab)),('Configuration du dispositif',lambda:self.device_tabs.select(self.config_panel))]),
                               ('Outils',[('Valider / plan',self.preview),('Actualiser l’état',lambda:self.launch('status'))])]:
            menu_button=tk.Menubutton(header,text=title,bg='#223344',fg='white',activebackground='#334b60',activeforeground='white',font=(self.font,8),padx=8)
            menu=tk.Menu(menu_button,tearoff=False)
            for label,callback in commands:menu.add_command(label=label,command=callback)
            menu_button.configure(menu=menu);menu_button.pack(side='left')
        # The workbench is the whole application now: no « Retour » to the old simulator, which is gone.
        toolbar=tk.Frame(self.window,bg='#f1f5fb',padx=7,pady=2);toolbar.grid(row=1,column=0,sticky='ew',pady=(0,2))
        tools=[('↖ Sélection',lambda:self.set_edit_mode(None)),('+ Ajouter un équipement',self.add_menu),
               ('⌁ Connecter un câble',lambda:self.set_edit_mode('cable')),('Supprimer',self.delete_selected)]
        separator=lambda:tk.Frame(toolbar,bg='#d3dde8',width=1,height=24).pack(side='left',padx=7,pady=3)  # between groups
        for title,callback in tools:
            if title.startswith('↖') or title.startswith('⌁'):
                button=ttk.Radiobutton(toolbar,text=title,command=callback,variable=self.tool_mode,value='select' if title.startswith('↖') else 'cable',style='Native.Toolbutton')
            else:button=ttk.Button(toolbar,text=title,command=callback,style='Native.TButton')
            button.pack(side='left',padx=2);self.buttons.append(button)
        separator()
        for title,action,style in [('▶ Démarrer','start','Native.Start.TButton'),('■ Arrêter','stop','Native.Stop.TButton'),
                                   ('↻ État','status','Native.TButton')]:
            button=ttk.Button(toolbar,text=title,command=lambda a=action:self.launch(a),style=style);button.pack(side='left',padx=3);self.buttons.append(button)
        separator()
        button=ttk.Button(toolbar,text='▣ Enregistrer',command=self.save,style='Native.TButton');button.pack(side='left',padx=3);self.buttons.append(button)
        button=ttk.Button(toolbar,text='✉ Simulation',command=self.open_simulation,style='Native.TButton')
        button.pack(side='left',padx=3)
        self.buttons.append(button)
        # The lab's state at a glance, at the end of the toolbar (draw() keeps it up to date).
        self.lab_chip=tk.Label(toolbar,text='○ Lab arrêté',bg='#e8eef5',fg=MUTED,font=(self.font,8,'bold'),padx=10,pady=3)
        self.lab_chip.pack(side='right',padx=6)

        nav=tk.Frame(self.window,bg=BG,height=24);nav.grid(row=2,column=0,sticky='ew')
        self.nav_items={};self.nav_current='Topologie'
        pages=[('Topologie',lambda:self.tabs.select(self.topology_tab)),('Équipements',lambda:self.tabs.select(self.editor_tab)),
               ('Scénarios',lambda:self.tabs.select(self.missions_tab)),('Outils',lambda:self.tabs.select(self.tools_tab))]
        for label,callback in pages:
            item=tk.Frame(nav,bg=BG);item.pack(side='left')
            button=tk.Button(item,text=label,command=callback,font=(self.font,8),bg=BG,fg=BLUE if label=='Topologie' else TEXT,relief='flat',borderwidth=0,highlightthickness=0,padx=12,pady=4,activebackground='white',activeforeground=BLUE);button.pack()
            line=tk.Frame(item,bg=BLUE if label=='Topologie' else BG,height=2);line.pack(fill='x')
            self.nav_items[label]=(button,line)
        body=ttk.Panedwindow(self.window,orient='horizontal');body.grid(row=3,column=0,sticky='nsew',padx=4)
        library_card=SoftPanel(body,BG,SIDEBAR);library_card.configure(width=218);body.add(library_card,weight=0);library=library_card.inner
        content=self.content=ttk.Panedwindow(body,orient='vertical');body.add(content,weight=1)
        workspace=self.workspace=ttk.Panedwindow(content,orient='horizontal')
        content.add(workspace,weight=3)
        lower=self.lower=ttk.Panedwindow(content,orient='horizontal');content.add(lower,weight=1)
        self.dock=ttk.Notebook(lower,height=155,style='Native.TNotebook');lower.add(self.dock,weight=3)
        self.activity_book=ttk.Notebook(lower,height=155,style='Native.TNotebook');lower.add(self.activity_book,weight=2)
        activity_card=SoftPanel(self.activity_book,BG);self.activity_book.add(activity_card,text='Événements');activity=activity_card.inner
        self.activity=ttk.Treeview(activity,columns=('time','action','result'),show='headings',height=5,style='Native.Treeview')
        for key,title,width in [('time','Heure',75),('action','Opération',85),('result','Résultat observé',280)]:
            self.activity.heading(key,text=title);self.activity.column(key,width=width,minwidth=60)
        self.activity.tag_configure('failed',foreground=RED);self.activity.tag_configure('passed',foreground=TEAL)
        self.activity.tag_configure('empty',foreground=MUTED)
        self.activity.insert('','end',iid='empty',values=('—','—','Démarrage, terminaux, tests : l’historique du lab.'),
                             tags=('empty',))
        self.activity.pack(fill='both',expand=True)
        self.label(library,'Bibliothèque',TEXT,9,True).pack(anchor='w',padx=9,pady=8)
        self.search=tk.StringVar();search=ttk.Entry(library,textvariable=self.search,style='Native.TEntry',font=(self.font,9));search.pack(fill='x',padx=8,pady=(0,8))
        self.search_hint=tk.Label(search,text='Rechercher un équipement',bg=PANEL,fg=MUTED,font=(self.font,8))
        self.search_hint.place(x=5,rely=.5,anchor='w');self.search_hint.bind('<Button-1>',lambda event:search.focus_set())
        search.bind('<FocusIn>',lambda event:self.search_hint.place_forget())
        search.bind('<FocusOut>',lambda event:self.refresh_search_hint())
        self.search_entry=search
        self.search.trace_add('write',self.filter_library)
        self.build_library_palette(library)
        self.project_list=tk.Frame(library,bg=SIDEBAR)
        self.project_list_open=False
        self.project_toggle=ttk.Button(library,text='▸ Équipements du projet',command=self.toggle_project_list,style='Native.TButton');self.project_toggle.pack(fill='x',padx=7,pady=8)
        self.library=ttk.Treeview(self.project_list,show='tree',selectmode='browse',height=4,style='Native.Treeview');self.library.pack(fill='both',expand=True,side='left')
        project_scroll=ttk.Scrollbar(self.project_list,style='Native.Vertical.TScrollbar',command=self.library.yview);project_scroll.pack(side='right',fill='y');self.library.configure(yscrollcommand=project_scroll.set)
        self.library.bind('<<TreeviewSelect>>',self.library_selected)
        self.tabs=ttk.Notebook(workspace,style='Native.Hidden.TNotebook');workspace.add(self.tabs,weight=1)
        self.topology_tab=tk.Frame(self.tabs,bg=BG);self.editor_tab=ttk.Frame(self.tabs)
        diagnostics=self.tools_tab=ttk.Frame(self.tabs);self.output_tab=ttk.Frame(self.dock);self.dock.add(self.output_tab,text='Diagnostic réseau · lecture seule')
        self.missions_tab=tk.Frame(self.tabs,bg=BG)
        self.raw_tab=ttk.Frame(self.dock);self.dock.add(self.raw_tab,text='Détails JSON')
        for frame,title in ((self.topology_tab,'Topologie'),(self.editor_tab,'Équipements / JSON'),(diagnostics,'Outils'),
                            (self.missions_tab,'Scénarios')):
            self.tabs.add(frame,text=title)
        self.build_missions(self.missions_tab)
        self.tabs.bind('<<NotebookTabChanged>>',self.sync_navigation)
        self.topology_tab.columnconfigure(0,weight=1);self.topology_tab.rowconfigure(1,weight=1)
        self.observation=tk.StringVar(value='Aucun état runtime observé.')
        diagram_card=SoftPanel(self.topology_tab,BG);diagram_card.grid(row=1,column=0,sticky='nsew');diagram=diagram_card.inner
        diagram.columnconfigure(0,weight=1);diagram.rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(diagram,background='#ffffff',highlightthickness=0,bd=0,relief='flat')
        self.canvas.grid(row=0,column=0,sticky='nsew');self.canvas.bind('<Configure>',self.resize_graph)
        self.canvas.bind('<B1-Motion>',self.drag_node);self.canvas.bind('<ButtonRelease-1>',self.drop_node)
        self.canvas.bind('<Escape>',lambda event:self.set_edit_mode(None))
        self.canvas.bind('<MouseWheel>',self.wheel_zoom)
        self.canvas.bind('<Button-4>',lambda event:self.wheel_zoom(event,1))
        self.canvas.bind('<Button-5>',lambda event:self.wheel_zoom(event,-1))
        self.canvas.bind('<Button-2>',self.begin_pan);self.canvas.bind('<B2-Motion>',self.pan_motion);self.canvas.bind('<ButtonRelease-2>',self.end_pan)
        self.canvas.bind('<Shift-Button-1>',self.begin_pan);self.canvas.bind('<Shift-B1-Motion>',self.pan_motion)
        self.canvas.bind('<Button-1>',lambda event:self.canvas.focus_set())
        self.canvas.bind('<plus>',lambda event:self.set_zoom(self.zoom*1.15))
        self.canvas.bind('<minus>',lambda event:self.set_zoom(self.zoom/1.15))
        self.canvas.bind('<Key-0>',lambda event:self.reset_view())
        for orient,row,col in (('vertical',0,1),('horizontal',1,0)):
            scrollbar=ttk.Scrollbar(diagram,orient=orient,style='Native.'+orient.title()+'.TScrollbar',command=self.canvas.yview if orient=='vertical' else self.canvas.xview)
            scrollbar.grid(row=row,column=col,sticky='ns' if orient=='vertical' else 'ew')
            self.canvas.configure(**({'yscrollcommand':scrollbar.set} if orient=='vertical' else {'xscrollcommand':scrollbar.set}))
        viewbar=tk.Frame(diagram,bg=PANEL,padx=3,pady=3);viewbar.place(x=10,y=8,anchor='nw')
        self.zoom_label=tk.StringVar(value='100 %')
        for text,callback in [('−',lambda:self.set_zoom(self.zoom/1.15)),('+',lambda:self.set_zoom(self.zoom*1.15)),('Centrer',self.reset_view)]:
            ttk.Button(viewbar,text=text,command=callback,style='Native.TButton',width=2 if text!='Centrer' else 7).pack(side='left',padx=1)
        tk.Label(viewbar,textvariable=self.zoom_label,bg=PANEL,fg=MUTED,font=(self.font,8),padx=4).pack(side='left')
        legend=tk.Frame(self.topology_tab,bg=PANEL,padx=8,pady=3);legend.grid(row=2,column=0,sticky='ew')
        self.runtime_hint=tk.StringVar(value='État non observé');self.runtime_label=tk.Label(legend,textvariable=self.runtime_hint,bg=PANEL,fg=MUTED,font=(self.font,8));self.runtime_label.pack(side='left',padx=5)
        self.label(legend,'VLAN / adresses : configuration',MUTED,8).pack(side='right')
        device=self.device_panel=tk.Frame(workspace,bg=PANEL,width=430)
        device.pack_propagate(False)
        workspace.add(device,weight=0)
        self.device_tabs=ttk.Notebook(device,style='Native.TNotebook');self.device_tabs.pack(fill='both',expand=True)
        details_card=SoftPanel(self.device_tabs,BG);self.device_tabs.add(details_card,text='Aperçu');details=details_card.inner
        self.config_panel=SoftPanel(self.device_tabs,BG);self.device_tabs.add(self.config_panel,text='GUI')
        self.build_config_form(self.config_panel.inner)
        self.console_panel=SoftPanel(self.device_tabs,BG)
        self.device_tabs.add(self.console_panel,text='CLI')
        self.build_vendor_console(self.console_panel.inner)
        self.linux_console_title=self.label(self.console_panel.inner,'Console Linux native',TEXT,11,True)
        self.linux_console_title.pack(anchor='w',padx=14,pady=16)
        tk.Label(self.console_panel.inner,text='Ouvrir un terminal sur le nœud sélectionné, lab démarré. Micro-VM : invite du '
                 'constructeur (show, ping, configuration appliquée au nœud en marche) ou shell du poste (ping, ip addr, ip route). '
                 'Nœud OCI : shell Linux.\n\nAuthentification sudo une fois, dans le terminal. Taper exit pour fermer.\n\n'
                 'Les commandes modifient le lab actif ; elles ne réécrivent pas le brouillon.',bg=BG,fg=MUTED,font=(self.font,9),
                 justify='left',wraplength=275).pack(fill='x',padx=14,pady=8)
        self.console_button=ttk.Button(self.console_panel.inner,text='Ouvrir la console Linux',command=self.open_console,style='Native.Primary.TButton');self.console_button.pack(fill='x',padx=14,pady=12)
        # The commands this node's terminal accepts, with examples: available before the lab runs, to prepare.
        self.catalogue_button=ttk.Button(self.console_panel.inner,text='📖 Catalogue de commandes',command=self.open_catalogue,
                                         style='Native.TButton')
        self.catalogue_button.pack(fill='x',padx=14,pady=(0,12))
        self.catalogue_window=None

        self.capture_panel=SoftPanel(self.device_tabs,BG);self.device_tabs.add(self.capture_panel,text='PCAP')
        self.capture_scroll=ScrollPanel(self.capture_panel.inner,PANEL);self.capture_scroll.canvas.configure(bd=0,relief='flat');self.capture_scroll.scroll.configure(style='Native.Vertical.TScrollbar');self.capture_scroll.pack(fill='both',expand=True)
        capture_form=self.capture_scroll.inner
        self.label(capture_form,'Capture réseau native',TEXT,11,True).pack(anchor='w',padx=14,pady=12)
        self.label(capture_form,'Interface du nœud sélectionné',MUTED,9).pack(anchor='w',padx=14)
        self.capture_interface=tk.StringVar();self.capture_ports=ttk.Combobox(capture_form,textvariable=self.capture_interface,state='readonly',style='Native.TCombobox');self.capture_ports.pack(fill='x',padx=14,pady=4)
        self.capture_seconds=tk.StringVar(value='10');self.capture_packets=tk.StringVar(value='1000');self.capture_filter=tk.StringVar(value='')
        for label,variable in [('Durée maximale · 1 à 60 secondes',self.capture_seconds),('Limite de paquets · budget 16 Mio',self.capture_packets),('Filtre BPF · vide = tout le trafic visible',self.capture_filter)]:
            self.label(capture_form,label,MUTED,9).pack(anchor='w',padx=14,pady=(8,0))
            ttk.Entry(capture_form,textvariable=variable,style='Native.TEntry').pack(fill='x',padx=14,pady=4)
        self.capture_button=ttk.Button(capture_form,text='Enregistrer une capture PCAP…',command=self.open_capture,style='Native.Primary.TButton');self.capture_button.pack(fill='x',padx=14,pady=12)
        self.build_trace_form(capture_form)
        tk.Label(capture_form,text='Choisir un nouveau fichier. La capture se déroule dans le namespace du nœud, sans interface hôte.\n\nAuthentification, progression et résultat dans le terminal. Vous pouvez générer du trafic depuis le logiciel pendant la capture.\n\nSnapshot : 2048 octets par paquet. Un fichier vide ne prouve pas une absence de trafic.',bg=BG,fg=MUTED,font=(self.font,9),justify='left',wraplength=275).pack(fill='x',padx=14,pady=6)

        self.build_overview(details)  # the selected device at a glance (ui_overview)
        self.editor=self.text_area(self.editor_tab);self.output=self.text_area(self.output_tab);self.output.configure(state='disabled',background='#0b0f15',foreground='#edf1f7',insertbackground='white');self.output.master.configure(bg='#0b0f15');self.output.master.master.face='#0b0f15'
        self.output.tag_configure('empty',foreground='#7f93aa',font=(self.font,9))
        self.raw_output=self.text_area(self.raw_tab);self.raw_output.configure(state='disabled')
        validate_button=ttk.Button(self.editor_tab,text='Valider / plan',command=self.preview,style='Native.TButton');validate_button.grid(row=2,column=0,sticky='e',pady=4);self.buttons.append(validate_button)
        self.table=ttk.Treeview(diagnostics,columns=('runtime','implementation','detected','scope'),show='headings',style='Native.Treeview')
        for key,title,width in [('runtime','Runtime',100),('implementation','Implémentation',100),('detected','Détecté',80),('scope','Périmètre',360)]:
            self.table.heading(key,text=title);self.table.column(key,width=width)
        self.table.pack(fill='both',expand=True)
        ttk.Button(diagnostics,text='Actualiser les dépendances',command=self.refresh,style='Native.TButton').pack(anchor='w',padx=8,pady=6)
        footer=tk.Frame(self.window,bg=PANEL,padx=10,pady=3);footer.grid_forget()
        self.counts=tk.StringVar();self.label(footer,'Sélection · état natif observé sur demande',MUTED,9).pack(side='left')
        tk.Label(footer,textvariable=self.counts,bg=PANEL,fg=TEAL,font=(self.font,8)).pack(side='right')
        self.window.bind('<Destroy>',self.destroyed,add='+')
        self.window.bind('<Configure>',self.schedule_reference_layout,add='+')
        self.content.bind('<Configure>',self.schedule_reference_layout,add='+')
        # A blank canvas, as in Packet Tracer: devices come from the library (click or drag), cables from two clicks.
        self.load_spec(blank_project())
        self.refresh()
        self.schedule_reference_layout()

    def schedule_reference_layout(self,event=None):
        if self.closed or (event is not None and event.widget not in (self.window,self.content)):return
        if self.layout_id is not None:self.window.after_cancel(self.layout_id)
        self.layout_id=self.window.after_idle(self.fit_reference_layout)

    def fit_reference_layout(self):
        self.layout_id=None
        if not self.closed and self.content.winfo_height()>350:
            self.content.sashpos(0,max(250,self.content.winfo_height()-160))
            self.lower.sashpos(0,int(self.content.winfo_width()*.55))
            # The device panel holds a section rail and a form: give it about 30% of the width (420-560 px)
            # so port names, addresses and action buttons are not cut off.
            width=self.workspace.winfo_width()
            if width>900:
                self.workspace.sashpos(len(self.workspace.panes())-2,width-max(420,min(560,int(width*.3))))
            # Node positions depend on the canvas width: lay the topology out again for the fitted canvas, and
            # put the view back at the origin unless the user has zoomed or panned it.
            if getattr(self,'graph',None) and not self.pending:
                self.window.after_idle(self.refit_topology)

    def refit_topology(self):
        if self.closed or not getattr(self,'graph',None):
            return
        self.draw(self.graph,self.states)
        if self.zoom==1. and not getattr(self,'view_moved',False):
            self.view_origin(0,0)

    def sync_navigation(self,event=None):
        if self.closed:return
        current=self.tabs.select()
        frames=[('Topologie',self.topology_tab),('Équipements',self.editor_tab),('Outils',self.tools_tab),('Scénarios',self.missions_tab)]
        self.nav_current=next((name for name,frame in frames if str(frame)==current),'Topologie')
        for name,(button,line) in self.nav_items.items():
            button.configure(fg=BLUE if name==self.nav_current else TEXT)
            line.configure(bg=BLUE if name==self.nav_current else BG)

    def refresh_search_hint(self):
        if self.search.get() or self.root.focus_get() is self.search_entry:self.search_hint.place_forget()
        else:self.search_hint.place(x=5,rely=.5,anchor='w')

    def label(self,parent,text,color=TEXT,size=10,bold=False):
        return tk.Label(parent,text=text,bg=parent.cget('bg'),fg=color,justify='left',font=(self.font,size,'bold' if bold else 'normal'))

    def build_library_palette(self,parent):
        from .native_models import grouped,short_name
        generic={'Routeurs':[('router',None,'Routeur Linux','Routage / 802.1Q','blue')],
                 'Switches':[('switch',None,'Switch Linux','VLAN / ports','blue')],
                 'Pare-feu':[('firewall',None,'Pare-feu Linux','Politique nftables','blue')],
                 'Postes clients':[('host',None,'Poste Linux','Thème bleu','blue'),('host',None,'Poste Linux','Thème rouge','red')],
                 'Serveurs et stockage':[('server',None,'Serveur Linux','Réseau Ethernet','blue')],'Périphériques':[]}
        catalog=[]
        for category,models in grouped():
            entries=list(generic.get(category,[]))
            for model in models:
                kind='server' if model['presentation']=='server' else model['role']
                entries.append((kind,model['id'],model['brand'],short_name(model),'blue'))
            catalog.append((category,entries))
        scroll=ScrollPanel(parent,SIDEBAR)
        scroll.canvas.configure(bd=0,relief='flat')
        scroll.scroll.configure(style='Native.Vertical.TScrollbar')
        scroll.pack(fill='both',expand=True)
        self.library_scroll=scroll
        container=scroll.inner
        self.palette_groups=[]
        for category,entries in catalog:
            group=tk.Frame(container,bg=SIDEBAR);group.pack(fill='x');tiles=[]
            self.palette_groups.append((group,tiles))
            self.label(group,category,TEXT,8,True).pack(anchor='w',padx=9,pady=(7,2))
            for kind,model,title,subtitle,variant in entries:
                tile=SoftCard(group,SIDEBAR);tile.pack(fill='x',padx=7,pady=3)
                icon=tk.Canvas(tile.inner,width=62,height=38,bg=PANEL,highlightthickness=0)
                icon.pack(side='left',padx=(0,4))
                draw_device(icon,kind,31,19,scale=.5,variant=variant)
                caption=tk.Frame(tile.inner,bg=PANEL)
                caption.pack(side='left',fill='x',expand=True)
                # Left-anchored and trimmed: an overflowing label would otherwise lose its first letters.
                for text,colour,size,limit in ((title,TEXT,9,13),(subtitle,MUTED,7,16)):
                    shown=text if len(text)<=limit else text[:limit-1]+'…'
                    self.label(caption,shown,colour,size).configure(anchor='w')
                    caption.winfo_children()[-1].pack(fill='x')
                def bind(widget,r=kind,m=model,card=tile):
                    # Click or drag onto the canvas: the device is added at once; right-click: the full form.
                    widget.bind('<ButtonRelease-1>',lambda event:self.tile_released(event,r,m))
                    widget.bind('<Button-3>',lambda event:self.add_device_dialog(r,model=m))
                    widget.bind('<Enter>',lambda event:card.hover(True))
                    widget.bind('<Leave>',lambda event:card.hover(False))
                    for child in widget.winfo_children():
                        bind(child,r,m,card)
                bind(tile)
                tiles.append((tile,(category+' '+title+' '+subtitle+' '+kind+' '+(model or '')).casefold()))

    def toggle_project_list(self):
        self.project_list_open=not self.project_list_open
        if self.project_list_open:self.project_list.pack(fill='both',expand=True,padx=7)
        else:self.project_list.pack_forget()
        self.project_toggle.configure(text=('▾' if self.project_list_open else '▸')+' Équipements du projet')

    def model_mode_refusal(self,action):
        """On Windows, macOS, or a Linux without KVM for a micro-VM lab: say once why the lab cannot start and what still
        works (the CLIs, ping and simulation on the model), instead of failing in a terminal. True when refused."""
        from .platform_support import MODEL_MODE,blocker
        try:
            spec=self.manifest() if action=='start' else None
        except (ValueError,TypeError,KeyError):
            spec=None
        why=blocker(spec)
        if why is None:
            return False
        self.note.set('Mode modèle : CLI, ping et ✉ Simulation fonctionnent ; démarrer les micro-VM demande Linux avec KVM.')
        messagebox.showinfo('Mode modèle',MODEL_MODE.format(why=why),parent=self.window)
        return True

    def record_event(self,action,result):
        tag='failed' if 'failed' in result or 'blocked' in result else 'passed' if 'passed' in result else ''
        if self.activity.exists('empty'):self.activity.delete('empty')
        self.activity.insert('','end',values=(time.strftime('%H:%M:%S'),action,result),tags=(tag,))
        children=self.activity.get_children()
        if len(children)>200:self.activity.delete(*children[:-200])
        self.activity.see(self.activity.get_children()[-1])

    def filter_library(self,*args):
        if not hasattr(self,'graph'):return
        self.refresh_search_hint()
        query=self.search.get().strip().casefold()
        for node in self.graph['nodes']:
            name=node['name']
            if not query or query in (name+' '+node['role']+' '+node['runtime']).casefold():self.library.reattach(name,'','end')
            else:self.library.detach(name)
        for group,tiles in self.palette_groups:
            group.pack_forget()
            for tile,words in tiles:tile.pack_forget()
            matches=[tile for tile,words in tiles if not query or query in words]
            if matches:
                group.pack(fill='x')
                for tile in matches:tile.pack(fill='x',padx=7,pady=1)
        if query and self.library.get_children() and not self.project_list_open:self.toggle_project_list()

    def library_selected(self,event=None):
        selected=self.library.selection()
        if selected and self.nodes.selection()!=selected:self.choose_node(selected[0])

    def resize_graph(self,event=None):
        if hasattr(self,'graph'):self.draw(self.graph,self.states)

    def text_area(self,parent):
        parent.rowconfigure(0,weight=1);parent.columnconfigure(0,weight=1)
        card=SoftPanel(parent,BG);card.grid(row=0,column=0,sticky='nsew');area=card.inner
        area.rowconfigure(0,weight=1);area.columnconfigure(0,weight=1)
        text=tk.Text(area,wrap='none',font=('DejaVu Sans Mono',9),undo=True,bd=0,highlightthickness=0)
        vertical=ttk.Scrollbar(area,command=text.yview,style='Native.Vertical.TScrollbar');horizontal=ttk.Scrollbar(area,orient='horizontal',command=text.xview,style='Native.Horizontal.TScrollbar')
        text.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        text.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        return text

    def refresh(self):
        self.table.delete(*self.table.get_children())
        for runtime in capabilities()['runtimes']:
            self.table.insert('','end',values=(runtime['id'],runtime['implementation'],'oui' if runtime['prerequisites_detected'] else 'non',runtime['scope']))

    def manifest(self):return validate(json.loads(self.editor.get('1.0','end-1c')))
    def error(self,error):messagebox.showerror('LAN natif',str(error),parent=self.window)

    def show_output(self,value):
        raw=json.dumps(value,ensure_ascii=False,indent=2);display=raw
        self.dock.tab(self.output_tab,text='Diagnostic réseau · lecture seule')
        if isinstance(value,dict) and isinstance(value.get('directions'),list):
            if value['directions']:
                first=value['directions'][0]
                self.dock.tab(self.output_tab,text='ICMP · '+str(first.get('source',''))[:18]+' ↔ '+str(first.get('destination',''))[:18])
            lines=['TEST ICMP · résultat : '+str(value.get('status','unknown')),'']
            for direction in value['directions']:
                lines.append(str(direction.get('source',''))+' → '+str(direction.get('destination','')))
                if direction.get('command'):lines.append('$ '+' '.join(direction['command']))
                lines.append(direction.get('stdout') or direction.get('error') or direction.get('status','unknown'))
                lines.append('')
            display='\n'.join(lines)
        for target,text in ((self.output,display),(self.raw_output,raw)):
            target.configure(state='normal');target.delete('1.0','end');target.insert('1.0',text);target.configure(state='disabled')

    def load_spec(self,spec,path=None):
        spec=validate(spec);self.path=Path(path) if path else None
        # Output and observations of the previous lab do not describe this one.
        self.vendor_observation=None
        self.write_output('',{},'Diagnostic réseau · lecture seule')
        self.editor.delete('1.0','end');self.editor.insert('1.0',json.dumps(spec,indent=2))
        self.config_key=None
        self.positions={name:tuple(point) for name,point in (spec.get('layout') or {}).items()}  # as last saved
        self.zoom=1.
        self.view_moved=False
        self.draw(public_topology(spec))
        self.fit_view()
        self.observation.set('Topologie déclarée · état runtime à actualiser.')

    def draw(self,graph,states=None):
        validate_topology(graph)
        selected=self.nodes.selection();previous=selected[0] if selected else None;destination=self.destination.get()
        self.graph=graph;self.view_lab=graph['name'];self.states=states or {};self.node_shapes={};self.link_shapes={}
        self.canvas.delete('all');self.nodes.delete(*self.nodes.get_children());self.library.delete(*[n['name'] for n in getattr(self,'library_graph',{}).get('nodes',[]) if self.library.exists(n['name'])]);self.library_graph=graph
        width=max(600,self.canvas.winfo_width());height=max(360,self.canvas.winfo_height())
        spec=None;members={}
        try:
            candidate=self.manifest()
            if public_topology(candidate)==graph:spec=candidate;members=access_vlans(graph,spec)
        except (ValueError,TypeError,KeyError):pass
        config={n['name']:n for n in spec['nodes']} if spec else {}
        positions=auto_layout(graph,members,width)
        positions.update({name:point for name,point in self.positions.items() if name in positions})
        self.drawn_positions=positions
        for xx in range(-142,int(width/max(.65,self.zoom))+160,22):
            for yy in range(-142,int(height/max(.65,self.zoom))+160,22):self.canvas.create_oval(xx,yy,xx+1,yy+1,fill='#e8eef7',outline='',tags=('grid',))
        if not graph['nodes']:
            # A blank project says how to begin, as an empty Packet Tracer workspace invites a first device.
            self.canvas.create_text(width/2,height/2-24,text='Cliquer ou glisser un équipement depuis la bibliothèque',
                                    fill=MUTED,font=(self.font,13,'bold'),tags=('hint',))
            self.canvas.create_text(width/2,height/2+6,text='puis « Connecter un câble » : deux clics · ▶ Démarrer · double-clic : '
                                    'le terminal de l’équipement',fill=MUTED,font=(self.font,10),tags=('hint',))
        palette=[('#e8f4ff','#8fc0ed','#0064c7'),('#e9f8ed','#9ed4ad','#14884b'),('#fff7dd','#ead08b','#ba7a04')]
        self.vlan_members=members;captions=[]
        groups=vlan_groups(graph,members)
        for index,(vid,names) in enumerate(groups):
            points=[positions[n] for n in names]
            spread=max(x for x,y in points)-min(x for x,y in points)+104
            # Laid-out sites (tree layout or moved by hand): a box hugs its hosts and never covers a neighbour's.
            span=spread
            middle=(min(x for x,y in points)+max(x for x,y in points))/2
            x1=middle-span/2;x2=middle+span/2
            # Keep the group inside the canvas, clear of the vertical scrollbar.
            right=width-24
            if x2>right:
                x1,x2=x1-(x2-right),right
            if x1<8:
                x2,x1=x2+(8-x1),8
            y1=min(y for x,y in points)-82;y2=max(y for x,y in points)+64
            bg,border,ink=palette[index%len(palette)]
            rounded_box(self.canvas,x1,y1,x2,y2,r=16,fill=bg,outline=border,dash=(3,2),tags=('vlan-group',))
            captions.append((x1,y1,x2,bg,ink,vid,networks(graph,names,spec,vid)))
        dmz=firewall_hosts(graph)
        for name in dmz:
            xx,yy=positions[name]
            rounded_box(self.canvas,xx-58,yy-56,xx+58,yy+62,r=14,fill='#f2ecff',outline='#cbb9ec',dash=(3,2),tags=('firewall-zone',))
            zone=self.canvas.create_text(xx-50,yy-46,text='Zone pare-feu',anchor='w',fill='#705493',font=(self.font,7,'bold'),
                                         tags=('zone-label',))
            bx1,by1,bx2,by2=self.canvas.bbox(zone)  # on a card of its own: the firewall's cable passes behind it
            self.canvas.tag_lower(rounded_box(self.canvas,bx1-3,by1-1,bx2+3,by2+1,r=5,fill='#f2ecff',outline='',tags=('zone-label',)),zone)
        graph_nodes={n['name']:n for n in graph['nodes']};port_labels=[]
        blocked=set()
        try:
            from .guest_stp import blocked_ports
            if spec:
                blocked=blocked_ports(spec)  # amber link lights: the ports spanning tree blocks
        except (ValueError,KeyError,TypeError):pass
        shut={(n['name'],port) for n in (spec or {}).get('nodes',[]) for port in n.get('shutdown') or []}
        try:
            from .port_guard import model as guarded
            if spec:  # red too: a port that port security or BPDU guard err-disables
                shut|={end for end,state in guarded(spec).items() if state['state']=='err-disabled'}
        except (ValueError,KeyError,TypeError):pass
        parallel={}  # several cables between the same two devices (a redundant link): drawn side by side
        for a,b in graph['links']:
            parallel.setdefault(frozenset((a[0],b[0])),[]).append((a,b))
        router_links={}
        for a,b in graph['links']:
            if graph_nodes[a[0]]['role']==graph_nodes[b[0]]['role']=='router':
                router_links[a[0]]=router_links.get(a[0],0)+1
                router_links[b[0]]=router_links.get(b[0],0)+1
        for index,(a,b) in enumerate(graph['links']):
            x,y=positions[a[0]];xx,yy=positions[b[0]]
            # Staggered routers (different rows, apart sideways): an L from one to the other's side.
            side=(abs(y-yy)>=45 and abs(x-xx)>=120 and graph_nodes[a[0]]['role']==graph_nodes[b[0]]['role']=='router'
                  and max(router_links.get(a[0],0),router_links.get(b[0],0))<=2)  # a chain, not a hub with its branches
            if abs(y-yy)<45:
                group=parallel[frozenset((a[0],b[0]))]
                shift=(group.index((a,b))-(len(group)-1)/2)*12
                sign=1 if xx>x else -1
                ax,ay,bx,by=x+sign*55,y+shift,xx-sign*55,yy+shift
                points=(ax,ay,bx,by)
            elif side:
                # An L: down from the upper device's port, then into the lower device's side, clear of its title.
                if y<yy:
                    ax,ay=x+port_offset(graph_nodes[a[0]],a[1]),y+25
                    bx,by=xx-(62 if xx>x else -62),yy
                    points,mid=(ax,ay,ax,by,bx,by),ax
                else:
                    bx,by=xx+port_offset(graph_nodes[b[0]],b[1]),yy+25
                    ax,ay=x-(62 if x>xx else -62),y
                    points,mid=(ax,ay,bx,ay,bx,by),bx
            else:
                sign=1 if yy>y else -1;ax=x;ay=y+sign*25;bx=xx;by=yy-sign*25
                # Ports leave the chassis spread across its width, so cables and their captions stay apart.
                if graph_nodes[a[0]]['role']!='host':
                    ax+=port_offset(graph_nodes[a[0]],a[1])
                if graph_nodes[b[0]]['role']!='host':
                    bx+=port_offset(graph_nodes[b[0]],b[1])
                mid=min(ay,by)+8+(index%3)*8
                points=(ax,ay,ax,mid,bx,mid,bx,by)
            self.link_shapes[index]=self.canvas.create_line(*points,fill='#3886b9',width=1.5,joinstyle='round',capstyle='round',
                                                            tags=('link','link:'+str(index)))
            self.canvas.tag_bind('link:'+str(index),'<Button-3>',lambda event,aa=a,bb=b:self.remove_cable(aa,bb))
            for endpoint,peer,px,py in ((a,b,ax,ay),(b,a,bx,by)):
                light=tuple(endpoint)
                if light in blocked or light in shut:  # amber: blocked by spanning tree; red: shutdown
                    colour='#e8a317' if light in blocked else '#d64541'
                    self.canvas.create_oval(px-4,py-4,px+4,py+4,fill=colour,outline='#ffffff',tags=('port-light',))
                else:
                    self.canvas.create_oval(px-2,py-2,px+2,py+2,fill='#4f83b3',outline='')
                nx,ny=positions[endpoint[0]];other_y=positions[peer[0]][1]
                ordinal=list(graph_nodes[endpoint[0]]['interfaces']).index(endpoint[1])
                tx,ty,anchor=px+5,py-8,'w'
                if side and abs(py-ny)<5:
                    outward=1 if px>nx else -1  # entering the lower device's side
                    tx,ty,anchor=px+outward*4,py-9,'w' if outward>0 else 'e'
                elif side:
                    tx,ty,anchor=px+5,py+8,'w'
                elif graph_nodes[endpoint[0]]['role']!='host':
                    if other_y<ny-45:tx,ty,anchor=nx-56,ny-19,'e'
                    else:tx,ty=px+5,ny+30+(ordinal%4)*10
                shown=port_label(graph_nodes[endpoint[0]],endpoint[1])
                port_labels.append(dict(x=tx,y=ty,text=shown,anchor=anchor,tag='link:'+str(index)))
            caption=link_caption(a,b,config)
            if caption:
                if abs(y-yy)<45:
                    self.canvas.create_text((ax+bx)/2,(ay+by)/2-12,text=caption,fill='#315b7d',font=(self.font,7))
                elif side:
                    lower=xx if y<yy else x  # the caption faces the lower device, away from the upper one's other cables
                    self.canvas.create_text(mid+(6 if lower>mid else -6),(min(ay,by)+max(ay,by))/2+6,text=caption,
                                            anchor='w' if lower>mid else 'e',fill='#315b7d',font=(self.font,7))
                elif abs(ax-bx)<40:
                    # A cable going almost straight down: label its vertical run, clear of both devices.
                    self.canvas.create_text(bx+6,(mid+by)/2,text=caption,anchor='w',fill='#315b7d',font=(self.font,7))
                else:
                    # On the lower device's own vertical run: the upper device's port labels keep their room.
                    lower_x,lower_y=(bx,by) if by>ay else (ax,ay)
                    self.canvas.create_text(lower_x+6,(mid+lower_y)/2,text=caption,anchor='w',fill='#315b7d',font=(self.font,7))
        for x1,y1,x2,bg,ink,vid,subnets in captions:
            rounded_box(self.canvas,x1+3,y1+3,x2-3,y1+41,r=9,fill=bg,outline='')
            self.canvas.create_text((x1+x2)/2,y1+14,text=f'VLAN {vid}',fill=ink,font=(self.font,8,'bold'),tags=('vlan-label',))
            self.canvas.create_text((x1+x2)/2,y1+30,text=subnets,fill=MUTED,font=(self.font,7))
        for node in graph['nodes']:
            name=node['name'];x,y=positions[name];observed=self.states.get(name,{})
            state=observed.get('status','non observé');memory=observed.get('memory')
            color='#21c632' if state=='running' else '#8b9cae';tags=('node','node:'+name)
            # The selection box encloses the device and its title (and, for hosts, the captions below).
            host=node['role']=='host'
            box=(x-44,y-34,x+44,y+66) if host else (x-64,y-58,x+64,y+30)
            self.node_shapes[name]=rounded_box(self.canvas,*box,fill='',outline='',width=1,tags=tags)
            from .native_models import MODELS,label as model_label
            presentation=MODELS[node['model']]['presentation'] if node.get('model') in MODELS else None
            kind='server' if presentation=='server' or name in dmz or name.upper().startswith('SRV') else node['role']
            host_index=[n['name'] for n in graph['nodes'] if n['role']=='host'].index(name) if node['role']=='host' else 0
            draw_device(self.canvas,kind,x,y,scale=1,tags=tags,variant='red' if host_index%2 else 'blue',zoom=self.zoom)
            if node['role']=='host':
                self.canvas.create_text(x,y+40,text=name,fill=TEXT,font=(self.font,9,'bold'),tags=tags)
                ips=[v.split('/')[0] for v in node['interfaces'].values() if v]
                # Under a host: its address (what a lab is about); the model only while it has none.
                caption=', '.join(ips) if ips else (MODELS[node['model']]['model'][:20] if node.get('model') in MODELS
                                                    else 'Linux · micro-VM' if node.get('runtime')=='firecracker' else 'Linux · OCI')
                if node.get('dhcp_clients') and not ips:
                    caption='DHCP'
                self.canvas.create_text(x,y+54,text=caption,fill='#315b7d' if ips else MUTED,font=(self.font,8),tags=tags)
            else:
                self.canvas.create_text(x,y-48,text=name,fill=TEXT,font=(self.font,9,'bold'),tags=tags)
                subtitle=model_label(node,short=True)
                subtitle=subtitle if len(subtitle)<=30 else subtitle[:29]+'…'
                self.canvas.create_text(x,y-34,text=subtitle,fill=MUTED,font=(self.font,8),tags=tags)
            self.canvas.create_oval(x+36,y+14,x+43,y+21,fill=color,outline='#ffffff',tags=tags)
            self.canvas.tag_bind('node:'+name,'<Button-1>',lambda event,n=name:self.node_pressed(event,n))
            self.canvas.tag_bind('node:'+name,'<Double-Button-1>',lambda event,n=name:self.device_double_click(n))
            self.canvas.tag_bind('node:'+name,'<Enter>',lambda event,n=name:self.hover_node(n,True))
            self.canvas.tag_bind('node:'+name,'<Leave>',lambda event,n=name:self.hover_node(n,False))
            self.nodes.insert('','end',iid=name,text=name,values=(node['runtime'],state,'—' if memory is None else f'{memory/1048576:.1f} MiB'))
            self.library.insert('','end',iid=name,text=name)
        obstacles=[self.canvas.bbox(item) for item in self.canvas.find_all() if self.canvas.type(item)=='text']
        for node in graph['nodes']:
            x,y=positions[node['name']];host=node['role']=='host'
            obstacles.append((x-32 if host else x-50,y-29,x+32 if host else x+50,y+24))
        draw_port_labels(self.canvas,port_labels,obstacles,(self.font,7),MUTED)
        self.canvas.tag_raise('zone-label')
        self.canvas.tag_raise('port-light')  # above the devices' artwork, as a port's link light
        for index,(a,b) in enumerate(graph['links']):
            self.canvas.tag_bind('link:'+str(index),'<Button-3>',lambda event,aa=a,bb=b:self.remove_cable(aa,bb))
        running=sum(n['runtime']=='oci' and self.states.get(n['name'],{}).get('status')=='running' for n in graph['nodes'])
        stopped=bool(self.states) and all(self.states.get(n['name'],{}).get('status')=='stopped' for n in graph['nodes'])
        from .platform_support import model_mode
        self.runtime_hint.set(f'● Relevé : {running} processus OCI en marche' if running else '● Arrêt confirmé' if stopped
                              else '◇ Mode modèle : CLI, ping et simulation' if model_mode() else '○ État non observé')
        self.runtime_label.configure(fg='#159746' if running else MUTED)
        guests=sum(self.states.get(n['name'],{}).get('status')=='running' for n in graph['nodes'])
        if guests:
            self.lab_chip.configure(text=f'● Lab en marche · {guests} équipement{"s" if guests>1 else ""}',bg='#e3f6ea',fg='#157a3e')
        elif model_mode():
            self.lab_chip.configure(text='◇ Mode modèle',bg='#efe9fb',fg='#5b3aa6')
        else:
            self.lab_chip.configure(text='○ Lab arrêté · '+str(len(graph['nodes']))+' équipement'+('s' if len(graph['nodes'])>1 else ''),
                                    bg='#e8eef5',fg=MUTED)
        self.filter_library();self.project_title.set(graph['name'])
        self.counts.set(f"{len(graph['nodes'])} équipements  /  {len(graph['links'])} liens  /  {graph['name']}")
        if self.zoom!=1.:
            for item in self.canvas.find_all():
                if self.canvas.type(item)=='text':
                    font=self.canvas.tk.splitlist(self.canvas.itemcget(item,'font'))
                    self.canvas.itemconfigure(item,font=(font[0],max(6,round(int(font[1])*self.zoom)),*font[2:]))
            self.canvas.scale('all',0,0,self.zoom,self.zoom)
        right=max((x for x,y in positions.values()),default=0)
        bottom=max((y for x,y in positions.values()),default=0)
        self.canvas.configure(scrollregion=(-100,-100,max(width,(right+90)*self.zoom)+100,max(height,(bottom+90)*self.zoom)+100))
        self.zoom_label.set(f'{round(self.zoom*100)} %')
        hosts=[n['name'] for n in graph['nodes'] if n['runtime']=='oci' and n['role']=='host']
        self.targets.configure(values=hosts);self.destination.set(destination if destination in hosts else hosts[-1] if hosts else '')
        self.show_oci_controls(bool(hosts))
        if graph['nodes']:self.choose_node(previous if previous in positions else graph['nodes'][0]['name'])
        else:self.refresh_overview(None)

    def choose_node(self,name):self.nodes.selection_set(name);self.nodes.see(name);self.select_node()
    def select_node(self,event=None):
        selected=self.nodes.selection();node=next((n for n in self.graph['nodes'] if selected and n['name']==selected[0]),None)
        if node:
            name=node['name']
            self.selected_title.set(name)
            if self.library.selection()!=(name,):self.library.selection_set(name)
            for key,shape in self.node_shapes.items():self.canvas.itemconfigure(shape,outline=BLUE if key==name else '',width=2 if key==name else 1)
        self.inspect_button.state(['!disabled'] if node and node['runtime']=='oci' and not self.pending else ['disabled'])
        running=node and self.states.get(node['name'],{}).get('status')=='running' and not self.pending
        # A micro-VM's terminal is its node console (typed requests to the agent, no shell); an OCI node's is a Linux shell.
        self.console_button.state(['!disabled'] if running else ['disabled'])
        guest=bool(node) and node['runtime']=='firecracker'
        self.linux_console_title.configure(text='Terminal du nœud' if guest else 'Console Linux native')
        self.console_button.configure(text=f'Ouvrir le terminal de {node["name"]}' if guest else 'Ouvrir la console Linux')
        self.catalogue_button.state(['!disabled'] if guest else ['disabled'])
        self.capture_button.state(['!disabled'] if running else ['disabled'])
        capture_ports=list(node['interfaces']) if node else []
        if node and node['runtime']=='oci':
            try:configured=next(n for n in self.manifest()['nodes'] if n['name']==node['name'])
            except (ValueError,KeyError,StopIteration):configured={}
            capture_ports+=list(configured.get('port_channels',{}))+list(configured.get('svis',{}))+[p for p,sub in configured.get('subinterfaces',{}).items() if sub.get('vlan') is not None]
            capture_ports+=['lo']+(['br0'] if node['role']=='switch' else [])
        self.capture_ports.configure(values=list(dict.fromkeys(capture_ports)))
        if self.capture_interface.get() not in capture_ports:self.capture_interface.set(capture_ports[0] if capture_ports else '')

        self.verify_button.state(['!disabled'] if node and node['runtime']=='oci' and node['role']=='host' and not self.pending else ['disabled'])
        self.refresh_overview(node)
        if node:self.load_config()
        self.config_apply.state(['!disabled'] if node and not self.pending and self.config_baseline is not None else ['disabled'])

    def set_zoom(self,value,x=None,y=None):
        value=max(.65,min(1.75,value))
        if abs(value-self.zoom)<.001:return
        x=self.canvas.winfo_width()/2 if x is None else x;y=self.canvas.winfo_height()/2 if y is None else y
        logical_x=self.canvas.canvasx(x)/self.zoom;logical_y=self.canvas.canvasy(y)/self.zoom
        self.dragging=None;self.panning=False;self.zoom=value;self.draw(self.graph,self.states)
        self.view_origin(logical_x*self.zoom-x,logical_y*self.zoom-y)

    def wheel_zoom(self,event,direction=None):
        direction=direction if direction is not None else (1 if event.delta>0 else -1)
        self.set_zoom(self.zoom*(1.12 if direction>0 else 1/1.12),event.x,event.y)
        return 'break'

    def reset_view(self):
        self.dragging=None
        self.panning=False
        self.zoom=1.
        self.view_moved=False
        self.draw(self.graph,self.states)
        self.fit_view()

    def fit_view(self):
        """Zoom out (never below 65 %) until every device shows, then centre the drawing in the canvas."""
        bounds=layout_bounds(self.graph,getattr(self,'drawn_positions',{})) if getattr(self,'graph',None) else None
        self.canvas.update_idletasks()
        width,height=max(300,self.canvas.winfo_width()-16),max(200,self.canvas.winfo_height()-16)
        if bounds is None:
            return self.view_origin(0,0)
        x1,y1,x2,y2=bounds
        wanted=max(.65,min(1.,width/max(1,x2-x1),height/max(1,y2-y1)))
        if abs(wanted-self.zoom)>.001:
            self.zoom=wanted;self.draw(self.graph,self.states)
        z=self.zoom
        self.view_origin(((x1+x2)/2)*z-width/2,max(y1*z-8,((y1+y2)/2)*z-height/2))
        self.zoom_label.set(f'{round(self.zoom*100)} %')

    def view_origin(self,x,y):
        region=tuple(float(v) for v in self.canvas.cget('scrollregion').split())
        self.canvas.xview_moveto((x-region[0])/max(1,region[2]-region[0]))
        self.canvas.yview_moveto((y-region[1])/max(1,region[3]-region[1]))

    def begin_pan(self,event):
        self.view_moved=True
        self.dragging=None;self.panning=True;self.canvas.focus_set();self.canvas.configure(cursor='fleur')
        self.canvas.scan_mark(event.x,event.y);return 'break'

    def pan_motion(self,event):
        if self.panning:self.canvas.scan_dragto(event.x,event.y,gain=1)
        return 'break'

    def end_pan(self,event=None):
        self.panning=False;self.canvas.configure(cursor='crosshair' if self.edit_mode=='cable' else '')
        return 'break'

    def open_device_config(self,name):
        self.dragging=None;self.choose_node(name);self.device_tabs.select(self.config_panel)
        return 'break'

    def hover_node(self,name,active):
        if name not in self.node_shapes:return
        selected=self.nodes.selection()
        self.canvas.itemconfigure(self.node_shapes[name],outline=BLUE if active or name in selected else '',width=2)
        for index,link in enumerate(self.graph['links']):
            if any(end[0]==name for end in link) and index in self.link_shapes:
                self.canvas.itemconfigure(self.link_shapes[index],fill=BLUE if active else '#3886b9',width=2.3 if active else 1.5)
        if not self.panning:self.canvas.configure(cursor='crosshair' if self.edit_mode=='cable' else 'hand2' if active else '')

    def build_config_form(self,parent):
        self.device_heading=tk.StringVar(value='Équipement · GUI')
        webbar=tk.Frame(parent,bg=PANEL);webbar.pack(fill='x',pady=3)
        ttk.Button(webbar,text='↗ Gestion web',command=self.open_web_management,style='Native.TButton').pack(side='right',padx=5)
        # Device header: role-coloured band with the device drawing, name, model and status (see draw_device_header).
        self.device_header=tk.Canvas(parent,height=86,bg=PANEL,highlightthickness=0,bd=0)
        self.device_header.pack(fill='x',padx=4,pady=(2,4))
        self.device_header.bind('<Configure>',lambda event:self.draw_device_header())
        self.device_header_node=None
        action_footer=tk.Frame(parent,bg=PANEL);action_footer.pack(side='bottom',fill='x')
        tk.Frame(action_footer,bg=PANEL,width=96).pack(side='left',fill='y')
        self.config_actions=tk.Frame(action_footer,bg=PANEL,padx=8,pady=6);self.config_actions.pack(side='left',fill='x',expand=True)
        shell=tk.Frame(parent,bg='#f6f8fb');shell.pack(fill='both',expand=True)
        rail_card=SoftPanel(shell,PANEL,face='#253440');rail_card.configure(width=100);rail_card.pack(side='left',fill='y');rail=rail_card.inner
        self.config_scroll=ScrollPanel(shell,PANEL);self.config_scroll.canvas.configure(bd=0,relief='flat');self.config_scroll.scroll.configure(style='Native.Vertical.TScrollbar');self.config_scroll.pack(side='left',fill='both',expand=True)
        for title,fraction in [('Interfaces',0),('Détails',.3)]:
            ttk.Button(rail,text=title,command=lambda f=fraction:self.config_scroll.canvas.yview_moveto(f),style='Native.Rail.TButton').pack(fill='x',pady=3)
        self.web_section_buttons=[]
        for section,title,roles in [('dashboard','Vue globale',('host','router','switch','firewall')),('firewall','Politiques',('firewall',)),('nat','NAT / VIP',('firewall',)),('routing','Routage',('router','switch','firewall')),('switching','VLAN / ports',('switch',))]:
            button=ttk.Button(rail,text=title,command=lambda key=section:self.open_web_management(key),style='Native.Rail.TButton')
            self.web_section_buttons.append((button,roles))
        form=self.config_scroll.inner
        self.label(form,'Interfaces',TEXT,11,True).pack(anchor='w',padx=9,pady=(9,4))
        self.label(form,'Configuration du projet · brouillon',MUTED,7).pack(anchor='w',padx=9,pady=(0,6))
        ports_card=SoftCard(form,PANEL);ports_card.pack(fill='x',padx=7)
        self.port_table=ttk.Treeview(ports_card.inner,columns=('address','admin'),show='tree headings',height=3,style='Native.Treeview')
        for key,label,width in [('#0','Nom',116),('address','Adresse IPv4',112),('admin','Admin',54)]:
            self.port_table.heading(key,text=label);self.port_table.column(key,width=width,minwidth=35)
        self.port_table.tag_configure('enabled',foreground='#168942');self.port_table.tag_configure('disabled',foreground='#bb3646')
        self.port_table.pack(fill='x');self.port_table.bind('<<TreeviewSelect>>',self.config_table_selected)
        detail_card=SoftCard(form,PANEL,face='#edf2f7',border='#edf2f7');detail_card.pack(fill='x',padx=7,pady=(10,5));detail=detail_card.inner
        self.label(detail,'Détails de l’interface',TEXT,8,True).pack(anchor='w',padx=7,pady=5)
        fields=tk.Frame(form,bg=PANEL);fields.pack(fill='x',padx=9)
        fields.columnconfigure(1,weight=1)
        self.config_vars={key:tk.StringVar() for key in ('name','port','address','gateway')};self.config_fields={}
        self.config_labels={}
        for row,(key,title) in enumerate([('name','Nom système'),('port','Interface'),('address','IPv4 / CIDR'),('gateway','Passerelle')]):
            caption=self.label(fields,title,MUTED,8)
            caption.grid(row=row,column=0,sticky='w',padx=(0,7),pady=3)
            self.config_labels[key]=caption
            field=ttk.Combobox(fields,textvariable=self.config_vars[key],state='readonly',style='Native.TCombobox',width=15,font=(self.font,9)) if key=='port' else ttk.Entry(fields,textvariable=self.config_vars[key],style='Native.TEntry',width=15,font=(self.font,9))
            field.grid(row=row,column=1,sticky='ew',pady=3);self.config_fields[key]=field
        self.config_fields['port'].bind('<<ComboboxSelected>>',self.config_port_selected)
        self.config_enabled=tk.BooleanVar(value=True)
        self.config_admin=ttk.Checkbutton(form,text='Interface activée',variable=self.config_enabled,style='Native.TCheckbutton');self.config_admin.pack(anchor='w',padx=9,pady=5)
        self.config_admin_hint=tk.Label(form,text='Arrêter un port : « shutdown » dans le terminal de l’équipement.',bg=PANEL,fg=MUTED,
                                        font=(self.font,8),anchor='w',justify='left',wraplength=260)
        self.config_admin_hint.bind('<Configure>',lambda event:self.config_admin_hint.configure(wraplength=max(120,event.width-4)))
        self.config_admin_anchor=tk.Frame(form,bg=PANEL,height=1);self.config_admin_anchor.pack(fill='x')
        self.config_apply=ttk.Button(self.config_actions,text='Appliquer au brouillon',command=self.apply_config,style='Native.Primary.TButton');self.config_apply.pack(side='left',fill='x',expand=True,padx=(0,5))
        ttk.Button(self.config_actions,text='Recharger',command=lambda:self.load_config(force=True),style='Native.TButton').pack(side='right')
        self.firewall_live=ttk.Button(form,text='Appliquer le pare-feu au lab actif',command=lambda:self.launch('firewall'),
                                      style='Native.TButton')
        self.firewall_live.pack(fill='x',padx=9,pady=(2,5))
        self.firewall_live.state(['disabled'])
        self.config_message=tk.StringVar()
        message=self.config_message_label=tk.Label(form,textvariable=self.config_message,bg=PANEL,fg=MUTED,
                                                   font=(self.font,7),justify='left',wraplength=300,anchor='w')
        message.pack(fill='x',padx=9,pady=7)
        # Wrap to the form's real width, which follows the device panel.
        message.bind('<Configure>',lambda event:message.configure(wraplength=max(120,event.width-4)))

    def open_web_management(self,page='interfaces'):
        selected=self.nodes.selection()
        if not selected:return
        from ..web_portal import WebPortal
        from .web_management import NativeDeviceAPI
        if self.web_portal is None:self.web_portal=WebPortal(self,api=NativeDeviceAPI(self),native=True)
        self.web_portal.open(selected[0],page=page)

    def config_table_selected(self,event=None):
        selected=self.port_table.selection()
        # A subinterface row stands for its parent port: the form edits physical ports only.
        port=(self.port_table.parent(selected[0]) or selected[0]) if selected else None
        if port and port!=self.config_port():
            self.config_vars['port'].set(self.port_choice(port))
            self.config_port_selected()

    def load_config(self,force=False):
        selected=self.nodes.selection()
        if not selected:return
        key=(self.view_lab,selected[0])
        if not force and self.config_key==key:return
        self.config_key=key;self.config_baseline=None
        try:
            spec=self.manifest()
            if public_topology(spec)!=self.graph:raise ValueError('Valider le JSON avant de charger le formulaire.')
            node=next(n for n in spec['nodes'] if n['name']==selected[0]);self.config_baseline=spec
            for button,roles in self.web_section_buttons:
                button.pack_forget()
                if node['role'] in roles:button.pack(fill='x',pady=2)
            from .native_models import label as model_label
            self.device_heading.set(node['name']+' · '+model_label(node))
            self.device_header_node=(spec,node)
            self.draw_device_header()
            self.load_vendor_console(spec,node)
            self.port_table.delete(*self.port_table.get_children())
            self.port_table.configure(height=max(1,min(4,len(node['interfaces'])+len(node.get('subinterfaces',{})))))
            for port,address in node['interfaces'].items():
                enabled=port not in node.get('shutdown',[])
                shown=port_names(node)[port]
                text=port if shown==port else f'{shown} ({port})'
                row=(address or '—','Activé' if enabled else 'Arrêté')
                self.port_table.insert('','end',iid=port,text=text,values=row,tags=('enabled' if enabled else 'disabled',))
                # 802.1Q subinterfaces (router-on-a-stick) are listed under their port; they are edited in Gestion web.
                for name,sub in node.get('subinterfaces',{}).items():
                    if sub.get('parent')==port:
                        row=(sub.get('address') or '—','VLAN '+str(sub.get('vlan')))
                        self.port_table.insert(port,'end',iid=name,text=name,values=row,tags=('enabled',))
                self.port_table.item(port,open=True)
            self.config_vars['name'].set(node['name']);self.config_vars['gateway'].set(node.get('gateway',''))
            ports=list(node['interfaces']);self.config_fields['port'].configure(values=[self.port_choice(p,node) for p in ports])
            self.config_vars['port'].set(self.port_choice(ports[0],node) if ports else '')
            self.config_port_selected()
            self.config_fields['name'].configure(state='normal')
            self.config_fields['gateway'].configure(state='normal' if node['role']!='switch' else 'disabled')
            # A switch has no address or gateway on its ports: the rows are hidden rather than shown disabled.
            for key in ('address','gateway'):
                for widget in (self.config_labels[key],self.config_fields[key]):
                    widget.grid_remove() if node['role']=='switch' else widget.grid()
            self.config_message.set('Modifier un port puis appliquer. Le réseau actif reste inchangé.')
            self.config_apply.state(['!disabled'] if ports and not self.pending else ['disabled'])
            # A firewall policy can also be applied to the running lab: atomically on containers, rebuilt closed on micro-VMs.
            if node['role']=='firewall':
                self.firewall_live.pack(fill='x',padx=9,pady=(2,5),before=self.config_message_label)
            else:
                self.firewall_live.pack_forget()
            self.firewall_live.state(['!disabled'] if node['role']=='firewall' and node['name'] in self.states and not self.pending
                                     else ['disabled'])
        except (ValueError,TypeError,KeyError,StopIteration) as error:
            self.config_message.set(str(error));self.config_apply.state(['disabled'])

    HEADER_THEMES={'router':('#0d2638','#1f5a85'),'switch':('#123049','#2b6f9f'),'firewall':('#2a0f12','#8a2b1f'),
                   'host':('#16263a','#34536f')}

    def draw_device_header(self):
        """Paint the GUI tab's device band: gradient, drawing, name, brand · model and chips."""
        self.device_header.delete('all')
        if self.device_header_node:
            self.paint_device_header(self.device_header,*self.device_header_node)

    def paint_device_header(self,canvas,spec,node):
        """A device band on CANVAS (the Aperçu and GUI tabs): gradient, drawing, name, brand · model and chips."""
        canvas.delete('all')
        from .device_view import summary
        from .workspace_art import _mix,device_image
        info=summary(spec,node)
        width=max(200,canvas.winfo_width())
        start,end=self.HEADER_THEMES.get(node['role'],self.HEADER_THEMES['host'])
        steps=48
        for i in range(steps):
            canvas.create_rectangle(i*width/steps,0,(i+1)*width/steps+1,86,fill=_mix(start,end,i/(steps-1)),outline='')
        role=info['art'].split('-')[0]
        image=device_image(canvas,role,info['art'].split('-')[1] if '-' in info['art'] else 'blue',.8)
        if image is not None:
            canvas.create_image(58,43,image=image)
        canvas.create_text(118,24,text=node['name'],anchor='w',fill='white',font=(self.font,14,'bold'))
        line=(f"{info['brand']} · {info['title'].split(' · ')[-1]} — {info['role_name']}" if node.get('model')
              else f"Nœud Linux générique — {info['role_name']}")
        canvas.create_text(118,45,text=line,anchor='w',
                           fill='#d8e6f2',font=(self.font,9))
        running=self.states.get(node['name'],{}).get('status')=='running'
        chips=[('● En marche' if running else '○ Non observé'),f"{len(info['ports'])} ports",
               'Micro-VM' if node['runtime']=='firecracker' else 'OCI']+([info['cli']] if info['cli'] else [])
        x=118
        for chip in chips:
            item=canvas.create_text(x+8,67,text=chip,anchor='w',fill='#3ddc84' if chip.startswith('●') else 'white',font=(self.font,8))
            left,top,right,bottom=canvas.bbox(item)
            if right+8>width-6:
                canvas.delete(item)  # chips that do not fit the panel are left out rather than cut
                break
            canvas.tag_lower(rounded_box(canvas,left-7,top-3,right+7,bottom+3,r=9,fill=_mix(start,'#ffffff',.18),outline=''),item)
            x=right+14

    def build_trace_form(self,parent):
        """Follow one real ping across the lab: every link is recorded, then the packet is replayed on the topology."""
        self.label(parent,'Suivre un paquet',TEXT,11,True).pack(anchor='w',padx=14,pady=(18,4))
        self.label(parent,'Depuis le nœud sélectionné, vers l’adresse IPv4',MUTED,9).pack(anchor='w',padx=14)
        self.trace_destination=tk.StringVar()
        ttk.Entry(parent,textvariable=self.trace_destination,style='Native.TEntry').pack(fill='x',padx=14,pady=4)
        self.trace_button=ttk.Button(parent,text='Envoyer un ping et le suivre',command=self.trace_packet,style='Native.TButton')
        self.trace_button.pack(fill='x',padx=14,pady=(4,2))
        note=('Chaque câble est enregistré pendant un ping réel ; l’animation rejoue ce que chaque fil a porté '
              '(adresses, étiquette VLAN, NAT). Authentification sudo dans le terminal.')
        tk.Label(parent,text=note,bg=BG,fg=MUTED,font=(self.font,8),justify='left',wraplength=275).pack(fill='x',padx=14,pady=(2,10))
        self.trace_after=None

    def trace_packet(self):
        selected=self.nodes.selection()
        node=next((n for n in self.graph['nodes'] if selected and n['name']==selected[0]),None)
        try:
            import ipaddress
            ipaddress.IPv4Address(self.trace_destination.get().strip())
            if not node or self.states.get(node['name'],{}).get('status')!='running':
                raise ValueError('Démarrer le lab, actualiser son état et sélectionner le nœud source.')
            if self.manifest()['name']!=self.view_lab:
                raise ValueError('Le projet et le laboratoire observé diffèrent.')
        except (ValueError,TypeError,KeyError) as error:
            self.error(error)
            return False
        return self.launch('trace')

    def trace_steps(self,data):
        """Each recorded crossing with the direction it went: the walk starts at the source node."""
        steps,current,previous=[],data['source'],{}
        for hop in data['hops']:
            a,b=hop['endpoints']
            if a[0]==current:
                start,end=a,b
            elif b[0]==current:
                start,end=b,a
            else:
                start,end=a,b
            seen=previous.get(hop['type'])
            nat=seen and (seen['source'],seen['destination'])!=(hop['source'],hop['destination'])
            steps.append(dict(hop,start=start,end=end,nat=bool(nat)))
            previous[hop['type']]=hop
            current=end[0]
        return steps

    def animate_trace(self,data):
        if self.trace_after is not None:
            try:
                self.window.after_cancel(self.trace_after)
            except tk.TclError:
                pass
        self.canvas.delete('trace')
        steps=self.trace_steps(data)
        lines=[f"Ping {data['source']} → {data['destination']} : {'réponse reçue' if data['answered'] else 'pas de réponse'}",'',
               f"{'#':>2}  {'t (ms)':>7}  {'Type':<8} {'VLAN':<5} {'Câble':<24} Sur le fil"]
        for number,step in enumerate(steps,1):
            cable=f"{step['start'][0]}:{step['start'][1]} → {step['end'][0]}:{step['end'][1]}"
            wire=f"{step['source']} → {step['destination']}"+(' (NAT)' if step['nat'] else '')
            kind='requête' if step['type']=='request' else 'réponse'
            lines.append(f"{number:>2}  {step['time_ms']:>7}  {kind:<8} {str(step['vlan'] or '—'):<5} {cable:<24} {wire}")
        if not steps:
            lines.append('Aucun câble n’a porté ce ping : vérifier la source, la destination et les routes.')
        self.write_output('\n'.join(lines),data,'Trajet du paquet')
        self.dock.select(self.output_tab)
        frames=22

        def frame(index,tick):
            self.canvas.delete('trace')
            if index>=len(steps):
                self.trace_after=None
                return
            step=steps[index]
            shape=self.link_shapes.get(step['link'])
            if shape is None:
                return frame(index+1,0)
            points=self.canvas.coords(shape)
            pairs=list(zip(points[0::2],points[1::2]))
            a=step['endpoints'][0]
            if step['start']!=a:
                pairs.reverse()
            lengths=[((x2-x1)**2+(y2-y1)**2)**.5 for (x1,y1),(x2,y2) in zip(pairs,pairs[1:])]
            target=sum(lengths)*tick/frames
            x,y=pairs[0]
            for ((x1,y1),(x2,y2)),length in zip(zip(pairs,pairs[1:]),lengths):
                if target<=length and length:
                    x,y=x1+(x2-x1)*target/length,y1+(y2-y1)*target/length
                    break
                target-=length
                x,y=x2,y2
            colour='#ff8a1f' if step['type']=='request' else '#21c66b'
            self.canvas.create_oval(x-11,y-11,x+11,y+11,fill='',outline=colour,width=2,tags=('trace',))
            self.canvas.create_oval(x-6,y-6,x+6,y+6,fill=colour,outline='white',width=2,tags=('trace',))
            text=f"{'requête' if step['type']=='request' else 'réponse'} · {step['source']} → {step['destination']}"
            text+=(f" · VLAN {step['vlan']}" if step['vlan'] else '')+(' · NAT' if step['nat'] else '')
            label=self.canvas.create_text(x+14,y-14,text=text,anchor='w',fill='#13324b',font=(self.font,8,'bold'),tags=('trace',))
            box=self.canvas.bbox(label)
            backing=self.canvas.create_rectangle(box[0]-5,box[1]-3,box[2]+5,box[3]+3,fill='white',outline=colour,tags=('trace',))
            self.canvas.tag_lower(backing,label)
            following=(index,tick+1) if tick<frames else (index+1,0)
            self.trace_after=self.window.after(35,lambda:frame(*following))

        frame(0,0)

    def build_vendor_console(self,parent):
        """Vendor-syntax configuration (IOS, FortiOS, Junos, RouterOS) of the selected node's lab draft."""
        frame=self.vendor_frame=tk.Frame(parent,bg=BG)
        self.vendor_title=tk.StringVar()
        title=self.label(frame,'',TEXT,11,True)
        title.configure(textvariable=self.vendor_title)
        title.pack(fill='x',padx=14,pady=(14,2))
        title.configure(anchor='w')
        title.bind('<Configure>',lambda event:title.configure(wraplength=max(120,event.width-4)))
        self.vendor_hint=tk.StringVar()
        hint=tk.Label(frame,textvariable=self.vendor_hint,bg=BG,fg=MUTED,font=(self.font,8),justify='left',anchor='w')
        hint.pack(fill='x',padx=14)
        hint.bind('<Configure>',lambda event:hint.configure(wraplength=max(120,event.width-4)))
        box=tk.Frame(frame,bg='#0d1520')
        box.pack(fill='both',expand=True,padx=14,pady=8)
        self.vendor_text=tk.Text(box,wrap='none',font=('DejaVu Sans Mono',8),height=13,bg='#0d1520',fg='#d7e3f0',
                                 insertbackground='#d7e3f0',bd=0,highlightthickness=0,padx=8,pady=6,undo=True)
        scroll=ttk.Scrollbar(box,orient='vertical',command=self.vendor_text.yview,style='Native.Vertical.TScrollbar')
        across=ttk.Scrollbar(box,orient='horizontal',command=self.vendor_text.xview)
        self.vendor_text.configure(yscrollcommand=scroll.set,xscrollcommand=across.set)
        across.pack(side='bottom',fill='x')
        scroll.pack(side='right',fill='y')
        self.vendor_text.pack(side='left',fill='both',expand=True)
        actions=tk.Frame(frame,bg=BG)
        actions.pack(fill='x',padx=14)
        self.vendor_show=ttk.Button(actions,text='Afficher la configuration',command=self.show_vendor_config,style='Native.TButton')
        self.vendor_show.pack(side='left',fill='x',expand=True,padx=(0,5))
        self.vendor_apply=ttk.Button(actions,text='Appliquer au brouillon',command=self.apply_vendor_config,
                                     style='Native.Primary.TButton')
        self.vendor_apply.pack(side='right',fill='x',expand=True)
        self.vendor_live=ttk.Button(frame,text='⚡ Appliquer au lab en marche',
                                    command=self.apply_routing_live,style='Native.TButton')
        self.vendor_live.pack(fill='x',padx=14,pady=(5,0))
        live=tk.Frame(frame,bg=BG)
        live.pack(fill='x',padx=14,pady=(8,0))
        self.vendor_command=tk.StringVar()
        self.vendor_commands=ttk.Combobox(live,textvariable=self.vendor_command,style='Native.TCombobox',font=('DejaVu Sans Mono',9))
        self.vendor_commands.pack(side='left',fill='x',expand=True,padx=(0,5))
        self.vendor_commands.bind('<Return>',lambda event:self.run_vendor_show())
        self.vendor_run=ttk.Button(live,text='Exécuter',command=self.run_vendor_show,style='Native.TButton')
        self.vendor_run.pack(side='left')
        self.vendor_refresh=ttk.Button(live,text='Relire',command=lambda:self.run_vendor_show(refresh=True),
                                       style='Native.TButton')
        self.vendor_refresh.pack(side='right',padx=(5,0))
        self.vendor_observation=None
        self.vendor_pending_command=None
        self.vendor_ping_destination=None
        self.vendor_ping_command=''
        self.vendor_message=tk.StringVar()
        message=tk.Label(frame,textvariable=self.vendor_message,bg=BG,fg=MUTED,font=(self.font,8),justify='left',anchor='w')
        message.pack(fill='x',padx=14,pady=6)
        message.bind('<Configure>',lambda event:message.configure(wraplength=max(120,event.width-4)))
        self.vendor_node=None

    def load_vendor_console(self,spec,node):
        from . import vendor_config
        from .native_models import label as model_label
        syntax=vendor_config.dialect(node)
        if syntax is None:
            self.vendor_node=None
            self.vendor_frame.pack_forget()
            return
        self.vendor_frame.pack(fill='both',expand=True,before=self.linux_console_title)
        self.vendor_node=node['name']
        from .vendor_show import COMMANDS
        self.vendor_commands.configure(values=COMMANDS[syntax])
        if self.vendor_command.get() not in COMMANDS[syntax]:
            self.vendor_command.set(COMMANDS[syntax][0])
        self.vendor_title.set(f'{vendor_config.TITLES[syntax]} · {model_label(node,short=True)}')
        self.vendor_hint.set(vendor_config.HINTS[syntax]+' Les commandes écrivent dans le brouillon du lab, '
                             'validé comme le formulaire ; le nœud exécute Linux, pas le système du constructeur.')
        self.show_vendor_config(spec)
        from .vendor_show import PING_HELP
        self.vendor_message.set('Configuration du brouillon. Lab actif : commandes show et '+PING_HELP[syntax]+'.')

    def show_vendor_config(self,spec=None):
        from . import vendor_config
        try:
            text=vendor_config.render(spec or self.editing_spec(),self.vendor_node)
        except (ValueError,TypeError,KeyError) as error:
            self.vendor_message.set(str(error))
            return
        self.vendor_text.delete('1.0','end')
        self.vendor_text.insert('1.0',text)
        self.vendor_message.set('Configuration du brouillon. Modifier ou taper des commandes, puis appliquer.')

    def apply_routing_live(self):
        """Apply the draft (vendor commands or forms) first, then send the saved node's static routes, gateway and OSPF
        to the running micro-VM: no restart. Other changes still need one; the bridge refuses them."""
        name=self.vendor_node
        node=next((n for n in self.editing_spec()['nodes'] if n['name']==name),None)
        running=self.view_lab==self.manifest()['name'] and self.states.get(name,{}).get('status')=='running'
        if node is None or node['runtime']!='firecracker' or node['role']=='switch' or not running:
            self.vendor_message.set('À chaud : un poste, routeur ou pare-feu micro-VM d’un lab démarré. '
                                    'Sinon, enregistrer puis redémarrer.')
            return False
        if self.vendor_text.get('1.0','end').strip() and not self.apply_vendor_config():
            return False
        self.nodes.selection_set(name)
        self.vendor_message.set('Application à chaud : confirmer avec sudo dans le terminal.')
        return self.launch('routing')

    def apply_vendor_config(self):
        from . import vendor_config
        name=self.vendor_node
        try:
            result=vendor_config.apply(self.editing_spec(),name,self.vendor_text.get('1.0','end'))
        except (ValueError,TypeError,KeyError) as error:
            self.vendor_message.set(str(error))
            return False
        self.config_key=None
        self.commit_edit(result)
        self.choose_node(name)
        self.load_config(force=True)
        self.device_tabs.select(self.console_panel)
        self.vendor_message.set('Brouillon appliqué. Enregistrer puis arrêter / démarrer pour activer les changements.')
        return True

    def run_vendor_show(self,refresh=False):
        """Print the running node's state in its vendor's format; observe it first when no observation is held."""
        from .vendor_show import show
        name=self.vendor_node
        if not name:
            return False
        if self.states.get(name,{}).get('status')!='running':
            self.vendor_message.set('Démarrer le lab et actualiser l’état : les commandes show lisent le nœud actif.')
            return False
        from .vendor_show import ping_destination
        try:
            node=next(n for n in self.manifest()['nodes'] if n['name']==name)
            target=ping_destination(node,self.vendor_command.get())
        except (ValueError,TypeError,KeyError,StopIteration) as error:
            self.vendor_message.set(str(error))
            return False
        if target:
            # Each ping is a new, sudo-confirmed request: echo requests leave the running node.
            self.vendor_ping_destination=target
            self.vendor_ping_command=self.vendor_command.get().strip()
            return self.launch('ping')
        held=self.vendor_observation
        if refresh or not held or held['key']!=(self.view_lab,name):
            self.vendor_pending_command=self.vendor_command.get()
            return self.launch('show')
        try:
            node=next(n for n in self.manifest()['nodes'] if n['name']==name)
            text=show(node,held['data'],self.vendor_command.get())
        except (ValueError,TypeError,KeyError,StopIteration) as error:
            self.vendor_message.set(str(error))
            return False
        from .vendor_show import PROMPTS
        from .vendor_config import dialect
        prompt=PROMPTS[dialect(node)].format(name)
        header=f'{prompt} {self.vendor_command.get().strip()}'
        note=f'(état Linux observé à {held["time"]} ; « Relire » interroge à nouveau le nœud)'
        self.write_output(header+'\n'+text+'\n\n'+note,held['data'],'CLI · '+name)
        self.vendor_message.set('Sortie dans « Diagnostic réseau ». Les valeurs viennent du nœud Linux actif.')
        self.dock.select(self.output_tab)
        return True

    EMPTY_OUTPUT=('  Aucun relevé pour l’instant.\n\n'
                  '  Les sorties des commandes lancées depuis l’application (état, inspection, show d’un équipement)\n'
                  '  s’affichent ici. Pour taper des commandes : double-clic sur un équipement.')

    def write_output(self,display,raw,title):
        self.dock.tab(self.output_tab,text=title)
        raw=json.dumps(raw,ensure_ascii=False,indent=2)
        for target,text in ((self.output,display),(self.raw_output,raw)):
            target.configure(state='normal')
            target.delete('1.0','end')
            target.insert('1.0',text)
            if target is self.output and not display:
                target.insert('1.0',self.EMPTY_OUTPUT,('empty',))  # an empty terminal says what will come in it
            target.configure(state='disabled')

    def config_port_selected(self,event=None):
        if self.config_baseline is None:return
        node=next(n for n in self.config_baseline['nodes'] if n['name']==self.config_key[1])
        port=self.config_port()
        self.config_vars['address'].set(node['interfaces'].get(port,''));self.config_enabled.set(port not in node.get('shutdown',[]))
        if self.port_table.exists(port) and self.port_table.selection()!=(port,):self.port_table.selection_set(port)
        editable=node['role']!='switch' and port not in node.get('dhcp_clients',[])
        self.config_fields['address'].configure(state='normal' if editable else 'disabled')
        # A micro-VM's port is shut from its terminal (« shutdown »), as on the device: no checkbox for it here.
        guest=node['runtime']=='firecracker'
        if guest:
            self.config_admin.pack_forget()
            self.config_admin_hint.pack(anchor='w',padx=9,pady=5,before=self.config_admin_anchor)
        else:
            self.config_admin_hint.pack_forget()
            self.config_admin.pack(anchor='w',padx=9,pady=5,before=self.config_admin_anchor)

    def port_choice(self,port,node=None):
        """How the GUI tab's port picker shows PORT: the vendor's name, with the Linux one in brackets."""
        if node is None:
            node=next(n for n in self.config_baseline['nodes'] if n['name']==self.config_key[1])
        shown=port_names(node).get(port,port)
        return port if shown==port else f'{shown} ({port})'

    def config_port(self):
        """The Linux port the picker shows (« port1 (eth0) » → eth0)."""
        text=self.config_vars['port'].get()
        return text[text.rindex('(')+1:-1] if text.endswith(')') and '(' in text else text

    def apply_config(self):
        try:
            current=self.editing_spec()
            if self.config_baseline is None or current!=self.config_baseline:
                raise ValueError('Le projet a changé. Recharger le formulaire avant d’appliquer.')
            old=self.config_key[1];values={k:v.get().strip() for k,v in self.config_vars.items()}
            result=topology_edit.configure_node(current,old,new_name=values['name'],port=self.config_port(),address=values['address'],gateway=values['gateway'],enabled=self.config_enabled.get())
            if old!=values['name'] and old in self.positions:self.positions[values['name']]=self.positions.pop(old)
            self.config_key=None;self.commit_edit(result);self.choose_node(values['name']);self.load_config(force=True)
            self.config_message.set('Brouillon appliqué. Enregistrer puis arrêter / démarrer pour activer les changements.')
            return True
        except (ValueError,TypeError,KeyError) as error:
            self.config_message.set(str(error));return False

    def set_edit_mode(self,mode):
        if self.pending:return
        self.edit_mode=mode;self.panning=False;self.tool_mode.set('cable' if mode=='cable' else 'select');self.cable_source=None;self.dragging=None
        self.canvas.configure(cursor='crosshair' if mode=='cable' else '')
        cable='Câbler : cliquer deux équipements (Ctrl+clic sur le second pour choisir les ports).'
        self.note.set(cable if mode=='cable' else 'Sélectionner ou déplacer un équipement · clic droit sur un câble pour le retirer.')

    def editing_spec(self):
        if self.pending:raise ValueError('Attendre la fin de l’opération native.')
        spec=self.manifest()
        if public_topology(spec)!=self.graph:
            raise ValueError('Le brouillon JSON diffère du dessin. Valider / plan avant une édition graphique.')
        return spec

    def commit_edit(self,spec):
        spec=validate(spec)
        self.editor.delete('1.0','end');self.editor.insert('1.0',json.dumps(spec,indent=2))
        self.draw(public_topology(spec));self.observation.set('Brouillon modifié · état runtime non observé.')
        self.note.set('Brouillon uniquement : enregistrer, puis arrêter / redémarrer pour appliquer. Aucun réseau actif modifié.')
        self.tabs.select(self.topology_tab)

    def node_pressed(self,event,name):
        if getattr(event,'state',0)&1:return self.begin_pan(event)
        self.choose_node(name);self.canvas.focus_set()
        if self.pending:return
        if self.edit_mode=='cable':
            if self.cable_source is None:self.cable_source=name;self.note.set('Choisir le deuxième équipement après '+name+'.')
            elif self.cable_source!=name:
                # Ctrl-click chooses the ports; a plain click takes the first free ones.
                first,self.cable_source=self.cable_source,None
                if getattr(event,'state',0)&4:
                    self.connect_dialog(first,name)
                else:
                    self.auto_connect(first,name)
            return
        self.drag_moved=False;self.dragging=(name,self.canvas.canvasx(event.x),self.canvas.canvasy(event.y))

    def drag_node(self,event):
        if self.panning:return self.pan_motion(event)
        if self.pending or not self.dragging:return
        name,x,y=self.dragging;xx=self.canvas.canvasx(event.x);yy=self.canvas.canvasy(event.y)
        if abs(xx-x)+abs(yy-y)>1:self.drag_moved=True
        self.canvas.move('node:'+name,xx-x,yy-y);self.dragging=(name,xx,yy)

    def drop_node(self,event):
        if self.panning:return self.end_pan(event)
        if not self.dragging:return
        name,_,_=self.dragging;self.dragging=None
        if not self.drag_moved:return
        box=self.canvas.coords(self.node_shapes[name])
        # Box centre minus the device origin: (-34+66)/2 for hosts, (-58+30)/2 for chassis.
        offset=16 if next(n for n in self.graph['nodes'] if n['name']==name)['role']=='host' else -14
        self.positions[name]=(max(50,(min(box[::2])+max(box[::2]))/(2*self.zoom)),max(60,(min(box[1::2])+max(box[1::2]))/(2*self.zoom)-offset))
        self.draw(self.graph,self.states)

    def add_device_dialog(self,role='host',model=None):
        server=role=='server'
        if server:role='host'
        try:spec=self.editing_spec()
        except (ValueError,TypeError,KeyError) as error:self.error(error);return
        win=tk.Toplevel(self.window);win.title('Ajouter un équipement Linux natif');win.transient(self.window.winfo_toplevel())
        form=ttk.Frame(win,padding=14);form.pack(fill='both',expand=True)
        values={}
        rootfs=next((n['rootfs'] for n in spec['nodes'] if n['runtime']=='oci'),'')
        vm=next((n for n in spec['nodes'] if n['runtime']=='firecracker'),{})
        prefix='SRV' if server else {'host':'PC','switch':'SW','router':'R','firewall':'FW'}[role];used={n['name'] for n in spec['nodes']}
        suggested=next(prefix+str(i) for i in range(1,258) if prefix+str(i) not in used)
        default_ports={'host':'1','switch':'8','router':'3','firewall':'2'}[role]
        runtime_default='firecracker' if vm and not rootfs else 'oci'
        if model:
            from .native_models import default_ports as model_ports,model_info
            default_ports=str(model_ports(model,runtime_default))
        rows=[('name','Nom',suggested),('role','Rôle',role),('rootfs','Rootfs Linux',rootfs),
              ('ports','Nombre de ports',default_ports),('address','IPv4 eth0 / CIDR (facultatif)',''),
              ('runtime','Exécution',runtime_default),
              ('kernel','Noyau micro-VM',vm.get('kernel','')),('disk','Disque micro-VM',vm.get('disk',''))]
        choices={'role':('host','switch','router','firewall'),'runtime':('oci','firecracker')}
        for row,(key,title,initial) in enumerate(rows):
            ttk.Label(form,text=title).grid(row=row,column=0,sticky='w',pady=5)
            value=tk.StringVar(value=initial);values[key]=value
            if key in choices:
                field=ttk.Combobox(form,textvariable=value,values=choices[key],state='readonly',
                                   style='Native.TCombobox',font=(self.font,9))
            else:
                field=ttk.Entry(form,textvariable=value,width=38,style='Native.TEntry',font=(self.font,9))
            field.grid(row=row,column=1,sticky='ew',padx=8)
        def browse():
            path=filedialog.askdirectory(parent=win,title='Rootfs Linux')
            if path:values['rootfs'].set(path)
        ttk.Button(form,text='Parcourir…',command=browse,style='Native.TButton').grid(row=2,column=2)
        hint=('Linux natif · pare-feu : trafic transitant bloqué par défaut.\n'
              'Micro-VM : 1 à 4 ports, une IPv4/préfixe par port séparées par des virgules, ou « dhcp ».')
        if model:
            info=model_info(model)
            win.title('Ajouter · '+info['brand']+' '+info['model'])
            hint=(f"Modèle {info['brand']} · {info['model']} : nom, ports ({', '.join(info['ports'][:3])}…) et présentation.\n"
                  'Le nœud exécute Linux (conteneur ou micro-VM) ; ce n’est pas le système du constructeur.\n'+hint)
        ttk.Label(form,text=hint).grid(row=8,column=0,columnspan=3,pady=8)
        def apply():
            try:
                current=self.editing_spec()
                field=lambda key:values[key].get().strip()
                if field('runtime')=='firecracker':
                    result=topology_edit.add_microvm_node(current,name=field('name'),role=field('role'),kernel=field('kernel'),
                                                          disk=field('disk'),ports=int(field('ports')),addresses=field('address'),
                                                          model=model if field('role')==role else None)
                else:
                    firewall={'default':'drop','stateful':True,'rules':[]} if field('role')=='firewall' else None
                    result=topology_edit.add_node(current,name=field('name'),role=field('role'),rootfs=field('rootfs'),
                                                  address=field('address'),ports=int(field('ports')),firewall=firewall,
                                                  model=model if field('role')==role else None)
                self.commit_edit(result)
                self.choose_node(field('name'))
                win.destroy()
            except (ValueError,TypeError,KeyError) as error:self.error(error)
        ttk.Button(form,text='Ajouter au brouillon',command=apply,style='Native.Primary.TButton').grid(row=9,column=1,sticky='e')
        ttk.Button(form,text='Annuler',command=win.destroy,style='Native.TButton').grid(row=9,column=0)

    def connect_dialog(self,first,second):
        try:
            spec=self.editing_spec();choices=[topology_edit.free_ports(spec,name) for name in (first,second)]
            additions={}
            for index,name in enumerate((first,second)):
                if not choices[index]:
                    additions[name]=topology_edit.next_port(spec,name);choices[index]=[additions[name]]
        except (ValueError,TypeError,KeyError) as error:self.error(error);return
        win=tk.Toplevel(self.window);win.title('Connecter un câble');win.transient(self.window.winfo_toplevel());form=ttk.Frame(win,padding=14);form.pack()
        ports=[]
        for row,(name,available) in enumerate(zip((first,second),choices)):
            ttk.Label(form,text=name+(' · nouveau port' if name in additions else '')).grid(row=row,column=0,pady=6)
            var=tk.StringVar(value=available[0]);ports.append(var)
            ttk.Combobox(form,textvariable=var,values=available,state='readonly',style='Native.TCombobox',font=(self.font,9)).grid(row=row,column=1,padx=8)
        def apply():
            try:
                draft=self.editing_spec()
                for name,port in additions.items():draft=topology_edit.add_port(draft,name,port)
                self.commit_edit(topology_edit.connect(draft,(first,ports[0].get()),(second,ports[1].get())));win.destroy()
            except (ValueError,TypeError,KeyError) as error:self.error(error)
        ttk.Button(form,text='Connecter au brouillon',command=apply,style='Native.Primary.TButton').grid(row=2,column=1,pady=8)
        ttk.Button(form,text='Annuler',command=win.destroy,style='Native.TButton').grid(row=2,column=0)

    def delete_selected(self):
        selected=self.nodes.selection()
        if not selected:return
        try:self.commit_edit(topology_edit.remove_node(self.editing_spec(),selected[0]))
        except (ValueError,TypeError,KeyError) as error:self.error(error)

    def remove_cable(self,a,b):
        try:self.commit_edit(topology_edit.disconnect(self.editing_spec(),a,b))
        except (ValueError,TypeError,KeyError) as error:self.error(error)

    def new_campus(self,security=False):
        if self.pending:return False
        rootfs=filedialog.askdirectory(parent=self.window,title='Rootfs Linux du laboratoire')
        if not rootfs:return False
        name=simpledialog.askstring('LAN sécurité access' if security else 'Campus entreprise','Nom du projet :',initialvalue='Access-security' if security else 'Campus-entreprise',parent=self.window)
        if not name:return False
        from .access_security import access_security_example
        try:self.load_spec((access_security_example if security else campus_example)(rootfs,name));self.tabs.select(self.topology_tab);return True
        except (ValueError,TypeError,KeyError) as error:self.error(error);return False

    def new(self):
        """A new, empty project (no question asked): devices come from the library."""
        if self.pending:return False
        used={p.stem for p in self.project_file(blank_project()).parent.glob('*.json')}
        name=next(n for n in ['mon-lab']+[f'mon-lab-{i}' for i in range(2,1000)] if n not in used)
        self.load_spec(blank_project(name))
        self.tabs.select(self.topology_tab)
        self.note.set('Nouveau projet vide : cliquer ou glisser un équipement depuis la bibliothèque.')
        return True

    def preview(self):
        if self.pending:return False
        try:spec=self.manifest();report=plan(spec)
        except (ValueError,TypeError,KeyError) as error:self.error(error);return False
        self.draw(public_topology(spec));self.observation.set('Topologie déclarée · état runtime à actualiser.')
        self.show_output(report);self.dock.select(self.output_tab);return True

    def open(self):
        if self.pending:return False
        path=filedialog.askopenfilename(parent=self.window,filetypes=[('Native lab JSON','*.json')])
        if path:
            try:self.load_spec(json.loads(Path(path).read_text()),path);self.tabs.select(self.topology_tab)
            except (OSError,ValueError,TypeError,KeyError) as error:self.error(error)

    def save(self,ask=False):
        """Save the project: in its file, or (never saved) in the projects folder by its name, without a dialog."""
        if self.pending:return False
        try:
            spec=self.manifest()
            if ask:
                path=filedialog.asksaveasfilename(parent=self.window,defaultextension='.json',filetypes=[('Native lab JSON','*.json')])
            else:
                path=self.path or self.project_file(spec)
            if not path:return False
            self.path=Path(path).resolve()
            drawn=getattr(self,'drawn_positions',{})  # the workbench drawing comes back as it was left
            spec['layout']={name:[round(x,1),round(y,1)] for name,(x,y) in drawn.items() if name in {n['name'] for n in spec['nodes']}}
            private_json(self.path,spec)
            self.project_title.set(spec['name']+' · '+self.path.name)
            return True
        except (OSError,ValueError,TypeError,KeyError) as error:self.error(error);return False

    def busy(self,enabled):
        for button in self.buttons:button.state(['disabled'] if enabled else ['!disabled'])
        self.editor.configure(state='disabled' if enabled else 'normal');self.select_node()

    def open_capture(self):
        if self.pending:return False
        try:
            selected=self.nodes.selection()
            node=next((n for n in self.graph['nodes'] if selected and n['name']==selected[0]),None)
            if not node or self.states.get(node['name'],{}).get('status')!='running':
                raise ValueError('Démarrer le nœud puis actualiser son état avant la capture.')
            if self.manifest()['name']!=self.view_lab:raise ValueError('Le projet et le laboratoire observé diffèrent.')
            interface=self.capture_interface.get()
            if interface not in self.capture_ports.cget('values'):raise ValueError('Choisir une interface du nœud.')
            seconds=int(self.capture_seconds.get());packets=int(self.capture_packets.get());expression=self.capture_filter.get()
            from .capture import limits
            limits(seconds,packets,2048,expression)
            output=filedialog.asksaveasfilename(parent=self.window,defaultextension='.pcap',filetypes=[('Capture PCAP','*.pcap')],title='Nouveau fichier PCAP (sans écrasement)')
            if not output:return False
            from .ui_capture import terminal_args
            launch_terminal(terminal_args(self.view_lab,node['name'],interface,output,seconds,packets,expression))
            self.last_response=None
            self.note.set('Capture demandée pour '+node['name']+'/'+interface+' ; résultat dans le terminal.')
            self.record_event('capture','Terminal demandé : '+node['name']+'/'+interface)
            return True
        except (OSError,ValueError,TypeError,KeyError) as error:
            self.error(error);return False

    def open_console(self):
        if self.pending:return False
        try:
            selected=self.nodes.selection()
            node=next((n for n in self.graph['nodes'] if selected and n['name']==selected[0]),None)
            if not node or self.states.get(node['name'],{}).get('status')!='running':
                raise ValueError('Démarrer le lab puis actualiser son état avant le terminal du nœud.')
            if self.manifest()['name']!=self.view_lab:raise ValueError('Le projet et le laboratoire observé diffèrent.')
            from .ui_console import terminal_args
            from . import console_server
            if node['runtime']=='firecracker' and console_server.available(self.view_lab):
                return bool(self.open_cli(node['name']))  # the CLI inside the workbench, no other password
            # Otherwise: a micro-VM's node terminal or an OCI node's Linux shell, in a terminal emulator with sudo.
            launch_terminal(terminal_args(self.view_lab,node['name'],'guest' if node['runtime']=='firecracker' else 'oci'))
            self.last_response=None
            self.note.set('Terminal demandé pour '+node['name']+' ; connexion à confirmer dans le terminal.')
            self.record_event('console','Terminal demandé : '+node['name'])
            return True
        except (OSError,ValueError,TypeError,KeyError) as error:
            self.error(error);return False

    def open_catalogue(self):
        """The command catalogue of the selected micro-VM, for its vendor and role, with its own ports in the examples."""
        try:
            selected=self.nodes.selection()
            node=next((n for n in self.manifest()['nodes'] if selected and n['name']==selected[0]),None)
            if not node or node['runtime']!='firecracker':
                raise ValueError('Choisir un nœud micro-VM pour voir ses commandes.')
            from .ui_catalogue import CatalogueWindow
            if self.catalogue_window is not None and self.catalogue_window.window.winfo_exists():
                self.catalogue_window.window.destroy()
            self.catalogue_window=CatalogueWindow(self.window,node,self.font)
            return self.catalogue_window
        except (ValueError,KeyError,TypeError) as error:
            self.error(error)
            return None

    def launch(self,action):
        if self.pending:return False
        if self.model_mode_refusal(action):
            return False
        directory=None
        try:
            if action in ('start','firewall','routing'):
                if not self.save():
                    return False
                spec=self.manifest()
                lab=spec['name'] if action=='start' else self.view_lab
                if action in ('firewall','routing') and spec['name']!=lab:
                    raise ValueError('Le projet et le laboratoire observé diffèrent.')
            else:
                lab=self.view_lab
            directory=tempfile.TemporaryDirectory(prefix='network-labs-gui-')
            target=lab
            # Both carry a private snapshot of the saved project: start the lab from it, or take the node's policy from it.
            if action in ('start','firewall','routing'):
                target=str(Path(directory.name)/'manifest.json')
                private_json(target,spec)
            selected=self.nodes.selection()
            node=selected[0] if selected and action in ('inspect','verify','firewall','routing','show','ping','trace') else None
            if action=='mission':
                node=self.mission_current  # the bridge's node field carries the mission id
            destination={'verify':self.destination.get(),'ping':getattr(self,'vendor_ping_destination',None),
                         'trace':self.trace_destination.get().strip() if hasattr(self,'trace_destination') else None}.get(action)
            if action=='mission' and self.is_scenario() and self.scenario and (self.mission_current.startswith('gen-')
                                                                               or self.scenario.get('key')):
                from .missions import encode_probes
                from .scenarios import checks_for
                destination=encode_probes(checks_for(self.scenario))  # pings of a scenario only this machine knows
            request=validate_request({'id':uuid.uuid4().hex,'owner_uid':os.geteuid(),'action':action,'target':target,'lab':lab,'node':node,
                                      'destination':destination})
            path=Path(directory.name)/'request.json';private_json(path,request)
            process=launch_terminal(client_args(path))
            self.last_response=None
            self.pending={'request':request,'directory':directory,'process':process,'began':time.monotonic()}
            self.busy(True);self.note.set(f'{action} · {lab} : confirmer dans le terminal…')
            self.poll_id=self.window.after(100,self.poll_result);return True
        except (OSError,ValueError,TypeError,KeyError) as error:
            if directory:directory.cleanup()
            self.error(error);return False

    def poll_result(self):
        poll_id=self.poll_id;self.poll_id=None
        if poll_id is not None:
            try:self.window.after_cancel(poll_id)
            except tk.TclError:pass
        if self.closed or not self.pending:return
        pending=self.pending;path=Path(pending['directory'].name)/'result.json'
        if not path.exists() and time.monotonic()-pending['began']<300:
            self.poll_id=self.window.after(100,self.poll_result);return
        try:
            response=read_result(path,pending['request']) if path.exists() else {'ok':False,'error':'Aucun résultat reçu ; actualiser l’état. Le lab peut rester actif.'}
            self.apply_response(response,pending['request'])
        except (OSError,ValueError,TypeError,KeyError) as error:
            self.last_response={'ok':False,'uncertain':True,'error':str(error)}
            self.note.set('Résultat non confirmé : '+str(error));self.observation.set('État précédent non confirmé ; actualiser.')
            self.draw(self.graph);self.show_output(self.last_response)
        finally:
            pending['directory'].cleanup();self.pending=None;self.busy(False)

    def apply_response(self,response,request):
        if not response['ok']:
            self.last_response=response
            self.note.set(response.get('error','Opération non confirmée.'));self.observation.set('État à vérifier ; aucune réussite déduite.')
            self.draw(self.graph);self.show_output(response);self.record_event(request['action'],self.note.get());return
        if response.get('lab')!=request['lab'] or response.get('action')!=request['action'] or response['topology']['name']!=request['lab']:
            raise ValueError('Le résultat ne correspond pas au lab demandé.')
        self.last_response=response
        action=request['action'];data=response['data'];graph=response['topology']
        if action=='inspect':
            from .web_observations import revision
            self.web_inspection_revision=revision(self.manifest())
            self.web_inspection_time=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        states=self.states if self.view_lab==request['lab'] else {}
        if action in ('start','stop'):
            self.vendor_observation=None  # a new or stopped lab invalidates what was observed
        if action in ('start','status','consoles'):
            from .ui_bridge import observed_states
            states=observed_states(data)
            self.observation.set(f"{data['name']} · {data['phase']} · état observé à {time.strftime('%H:%M:%S')}")
            if response.get('consoles'):
                self.note.set('Lab démarré · double-clic sur un équipement : son terminal, dans l’atelier, sans autre mot de passe.')
        elif action=='stop':
            if data.get('stopped')!=request['lab']:raise ValueError('Arrêt non confirmé.')
            states={n['name']:{'status':'stopped'} for n in graph['nodes']};self.observation.set(request['lab']+' · arrêt confirmé')
        self.draw(graph,states)
        if action=='trace':
            self.draw(graph,states)
            self.tabs.select(self.topology_tab)
            self.animate_trace(data)
            self.record_event('trace',f"{data['source']} → {data['destination']} : {len(data['hops'])} passages enregistrés")
            return
        if action=='mission':
            self.mission_real={index:(ok,detail) for index,ok,detail in data['results']}
            self.record_mission(self.show_mission_results())
            self.write_output('Mission '+data['mission']+' : pings réels envoyés depuis les micro-VM.',data,'Mission')
            self.draw(graph,states)
            self.record_event('mission',self.mission_score.get())
            self.tabs.select(self.missions_tab)
            return
        if action=='ping':
            from .vendor_show import PROMPTS,ping_text
            from .vendor_config import dialect
            node=next(n for n in self.manifest()['nodes'] if n['name']==request['node'])
            prompt=PROMPTS[dialect(node)].format(node['name'])
            text=f'{prompt} {self.vendor_ping_command}\n'+ping_text(node,data)+'\n\n(échos ICMP réels envoyés par le nœud Linux)'
            self.choose_node(request['node'])
            self.write_output(text,data,'CLI · '+node['name'])
            self.vendor_message.set('Ping exécuté sur le nœud actif.')
        elif action=='show':
            self.vendor_observation={'key':(request['lab'],request['node']),'data':data,'time':time.strftime('%H:%M:%S')}
            self.choose_node(request['node'])
            if self.vendor_pending_command:
                self.vendor_command.set(self.vendor_pending_command)
                self.vendor_pending_command=None
                self.run_vendor_show()
            else:
                # A relevé requested from the device page: shown there; the dock keeps the raw observation.
                self.write_output('Relevé de '+request['node']+' : voir la page de l’équipement (Gestion web).',data,
                                  'Relevé · '+request['node'])
        else:
            self.show_output(data)
        self.note.set(('Test réseau : '+data['status']) if action=='verify' else action+' · '+request['lab']+' : terminé')
        self.dock.select(self.output_tab);self.tabs.select(self.topology_tab)
        self.record_event(action,self.note.get())

    def destroyed(self,event):
        if event.widget is self.window:
            self.closed=True
            if self.web_portal is not None:self.web_portal.close();self.web_portal=None
            if self.layout_id is not None:
                try:self.window.after_cancel(self.layout_id)
                except tk.TclError:pass
                self.layout_id=None
            if self.poll_id:
                try:self.window.after_cancel(self.poll_id)
                except tk.TclError:pass
            if self.pending:self.pending['directory'].cleanup();self.pending=None
            if self.embedded and self.root.winfo_exists():
                self.root.bind('<Control-s>',self.previous_save)
                for widget,options in self.previous_widgets:
                    if widget.winfo_exists():widget.pack(**options)

    def close(self):self.window.destroy()
