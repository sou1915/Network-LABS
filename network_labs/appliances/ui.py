"""Native topology and lifecycle workbench; sudo stays in an external terminal."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import uuid
import os
from ..layout import fit_dialog,ScrollPanel
from .catalog import capabilities
from .spec import validate
from . import reference_theme
from .soft_widgets import SoftCard, SoftPanel
from .reference_theme import BG,PANEL,SIDEBAR,TEXT,MUTED,BLUE,GREEN as TEAL,RED
from .missions_ui import MissionsPanel
from .ui_quick import QuickEditing,blank_project
from .ui_overview import DeviceOverview
from .ui_studio import StudioChrome
from . import design
from .ui_canvas import TopologyCanvas
from .ui_device import DeviceForm
from .ui_vendor import VendorConsole
from .ui_trace import PacketTrace
from .ui_editing import TopologyEditing
from .ui_library import LibraryPalette
from .ui_project import ProjectFiles
from .ui_bridge import SOURCE, client_args, private_json, read_result, validate_request


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


class ApplianceWindow(TopologyCanvas,DeviceForm,VendorConsole,PacketTrace,TopologyEditing,LibraryPalette,ProjectFiles,MissionsPanel,
                      QuickEditing,DeviceOverview,StudioChrome):
    def __init__(self,app,*,embedded=False):
        self.app=app;self.path=None;self.pending=None;self.poll_id=None;self.closed=False;self.last_response=None;self.web_portal=None
        # Use the established desktop's theme and device artwork. Native state
        # stays separate from the pedagogical Session/model behind that desktop.
        from ..__main__ import App
        self.root=app.root
        self.embedded=embedded
        self.previous_widgets=[]
        design.install(self.root)  # studio: the panels' hand-set light colours turn dark; mono: every colour to black and white
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
                               ('Affichage',[('Topologie',lambda:self.tabs.select(self.topology_tab)),
                                             ('Configuration du projet',lambda:self.tabs.select(self.editor_tab)),
                                             ('Configuration du dispositif',lambda:self.device_tabs.select(self.config_panel))]),
                               ('Outils',[('Valider / plan',self.preview),('Actualiser l’état',lambda:self.launch('status'))])]:
            menu_button=tk.Menubutton(header,text=title,bg='#223344',fg='white',activebackground='#334b60',activeforeground='white',font=(self.font,8),padx=8)
            menu=tk.Menu(menu_button,tearoff=False)
            for label,callback in commands:menu.add_command(label=label,command=callback)
            menu_button.configure(menu=menu)
            menu_button.pack(side='left')
        # The workbench is the whole application now: no « Retour » to the old simulator, which is gone.
        toolbar=tk.Frame(self.window,bg='#f1f5fb',padx=7,pady=2)
        toolbar.grid(row=1,column=0,sticky='ew',pady=(0,2))
        tools=[('↖ Sélection',lambda:self.set_edit_mode(None)),('+ Ajouter un équipement',self.add_menu),
               ('⌁ Connecter un câble',lambda:self.set_edit_mode('cable')),('Supprimer',self.delete_selected)]
        separator=lambda:tk.Frame(toolbar,bg='#d3dde8',width=1,height=24).pack(side='left',padx=7,pady=3)  # between groups
        for title,callback in tools:
            if title.startswith('↖') or title.startswith('⌁'):
                button=ttk.Radiobutton(toolbar,text=title,command=callback,variable=self.tool_mode,
                                       value='select' if title.startswith('↖') else 'cable',style='Native.Toolbutton')
            else:button=ttk.Button(toolbar,text=title,command=callback,style='Native.TButton')
            button.pack(side='left',padx=2)
            self.buttons.append(button)
        separator()
        for title,action,style in [('▶ Démarrer','start','Native.Start.TButton'),('■ Arrêter','stop','Native.Stop.TButton'),
                                   ('↻ État','status','Native.TButton')]:
            button=ttk.Button(toolbar,text=title,command=lambda a=action:self.launch(a),style=style)
            button.pack(side='left',padx=3)
            self.buttons.append(button)
        separator()
        button=ttk.Button(toolbar,text='▣ Enregistrer',command=self.save,style='Native.TButton')
        button.pack(side='left',padx=3)
        self.buttons.append(button)
        button=ttk.Button(toolbar,text='✉ Simulation',command=self.open_simulation,style='Native.TButton')
        button.pack(side='left',padx=3)
        self.buttons.append(button)
        # The lab's state at a glance, at the end of the toolbar (draw() keeps it up to date).
        self.lab_chip=tk.Label(toolbar,text='○ Lab arrêté',bg='#e8eef5',fg=MUTED,font=(self.font,8,'bold'),padx=10,pady=3)
        self.lab_chip.pack(side='right',padx=6)

        nav=tk.Frame(self.window,bg=BG,height=24)
        nav.grid(row=2,column=0,sticky='ew')
        self.nav_items={}
        self.nav_current='Topologie'
        pages=[('Topologie',lambda:self.tabs.select(self.topology_tab)),('Équipements',lambda:self.tabs.select(self.editor_tab)),
               ('Scénarios',lambda:self.tabs.select(self.missions_tab)),('Outils',lambda:self.tabs.select(self.tools_tab))]
        for label,callback in pages:
            item=tk.Frame(nav,bg=BG)
            item.pack(side='left')
            button=tk.Button(item,text=label,command=callback,font=(self.font,8),bg=BG,fg=BLUE if label=='Topologie' else TEXT,
                             relief='flat',borderwidth=0,highlightthickness=0,padx=12,pady=4,activebackground='white',activeforeground=BLUE)
            button.pack()
            line=tk.Frame(item,bg=BLUE if label=='Topologie' else BG,height=2)
            line.pack(fill='x')
            self.nav_items[label]=(button,line)
        body=self.body=ttk.Panedwindow(self.window,orient='horizontal')
        body.grid(row=3,column=0,sticky='nsew',padx=4)
        library_card=SoftPanel(body,BG,SIDEBAR)
        library_card.configure(width=218)
        body.add(library_card,weight=0)
        library=library_card.inner
        content=self.content=ttk.Panedwindow(body,orient='vertical')
        body.add(content,weight=1)
        workspace=self.workspace=ttk.Panedwindow(content,orient='horizontal')
        content.add(workspace,weight=3)
        lower=self.lower=ttk.Panedwindow(content,orient='horizontal')
        content.add(lower,weight=1)
        self.dock=ttk.Notebook(lower,height=155,style='Native.TNotebook')
        lower.add(self.dock,weight=3)
        self.activity_book=ttk.Notebook(lower,height=155,style='Native.TNotebook')
        lower.add(self.activity_book,weight=2)
        activity_card=SoftPanel(self.activity_book,BG)
        self.activity_book.add(activity_card,text='Événements')
        activity=activity_card.inner
        self.activity=ttk.Treeview(activity,columns=('time','action','result'),show='headings',height=5,style='Native.Treeview')
        for key,title,width in [('time','Heure',75),('action','Opération',85),('result','Résultat observé',280)]:
            self.activity.heading(key,text=title)
            self.activity.column(key,width=width,minwidth=60)
        self.activity.tag_configure('failed',foreground=RED)
        self.activity.tag_configure('passed',foreground=TEAL)
        self.activity.tag_configure('empty',foreground=MUTED)
        self.activity.insert('','end',iid='empty',values=('—','—','Démarrage, terminaux, tests : l’historique du lab.'),
                             tags=('empty',))
        self.activity.pack(fill='both',expand=True)
        self.label(library,'Bibliothèque',TEXT,9,True).pack(anchor='w',padx=9,pady=8)
        self.search=tk.StringVar()
        search=ttk.Entry(library,textvariable=self.search,style='Native.TEntry',font=(self.font,9))
        search.pack(fill='x',padx=8,pady=(0,8))
        self.search_hint=tk.Label(search,text='Rechercher un équipement',bg=PANEL,fg=MUTED,font=(self.font,8))
        self.search_hint.place(x=5,rely=.5,anchor='w')
        self.search_hint.bind('<Button-1>',lambda event:search.focus_set())
        search.bind('<FocusIn>',lambda event:self.search_hint.place_forget())
        search.bind('<FocusOut>',lambda event:self.refresh_search_hint())
        self.search_entry=search
        self.search.trace_add('write',self.filter_library)
        self.build_library_palette(library)
        self.project_list=tk.Frame(library,bg=SIDEBAR)
        self.project_list_open=False
        self.project_toggle=ttk.Button(library,text='▸ Équipements du projet',command=self.toggle_project_list,style='Native.TButton')
        self.project_toggle.pack(fill='x',padx=7,pady=8)
        self.library=ttk.Treeview(self.project_list,show='tree',selectmode='browse',height=4,style='Native.Treeview')
        self.library.pack(fill='both',expand=True,side='left')
        project_scroll=ttk.Scrollbar(self.project_list,style='Native.Vertical.TScrollbar',command=self.library.yview)
        project_scroll.pack(side='right',fill='y')
        self.library.configure(yscrollcommand=project_scroll.set)
        self.library.bind('<<TreeviewSelect>>',self.library_selected)
        self.tabs=ttk.Notebook(workspace,style='Native.Hidden.TNotebook')
        workspace.add(self.tabs,weight=1)
        self.topology_tab=tk.Frame(self.tabs,bg=BG)
        self.editor_tab=ttk.Frame(self.tabs)
        diagnostics=self.tools_tab=ttk.Frame(self.tabs)
        self.output_tab=ttk.Frame(self.dock)
        self.dock.add(self.output_tab,text='Diagnostic réseau · lecture seule')
        self.missions_tab=tk.Frame(self.tabs,bg=BG)
        self.raw_tab=ttk.Frame(self.dock)
        self.dock.add(self.raw_tab,text='Détails JSON')
        for frame,title in ((self.topology_tab,'Topologie'),(self.editor_tab,'Équipements / JSON'),(diagnostics,'Outils'),
                            (self.missions_tab,'Scénarios')):
            self.tabs.add(frame,text=title)
        self.build_missions(self.missions_tab)
        self.tabs.bind('<<NotebookTabChanged>>',self.sync_navigation)
        self.topology_tab.columnconfigure(0,weight=1)
        self.topology_tab.rowconfigure(1,weight=1)
        self.observation=tk.StringVar(value='Aucun état runtime observé.')
        diagram_card=SoftPanel(self.topology_tab,BG)
        diagram_card.grid(row=1,column=0,sticky='nsew')
        diagram=diagram_card.inner
        diagram.columnconfigure(0,weight=1)
        diagram.rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(diagram,background='#ffffff',highlightthickness=0,bd=0,relief='flat')
        self.canvas.grid(row=0,column=0,sticky='nsew')
        self.canvas.bind('<Configure>',self.resize_graph)
        self.canvas.bind('<B1-Motion>',self.drag_node)
        self.canvas.bind('<ButtonRelease-1>',self.drop_node)
        self.canvas.bind('<Escape>',lambda event:self.set_edit_mode(None))
        self.canvas.bind('<MouseWheel>',self.wheel_zoom)
        self.canvas.bind('<Button-4>',lambda event:self.wheel_zoom(event,1))
        self.canvas.bind('<Button-5>',lambda event:self.wheel_zoom(event,-1))
        self.canvas.bind('<Button-2>',self.begin_pan)
        self.canvas.bind('<B2-Motion>',self.pan_motion)
        self.canvas.bind('<ButtonRelease-2>',self.end_pan)
        self.canvas.bind('<Shift-Button-1>',self.begin_pan)
        self.canvas.bind('<Shift-B1-Motion>',self.pan_motion)
        self.canvas.bind('<Button-1>',lambda event:self.canvas.focus_set())
        self.canvas.bind('<plus>',lambda event:self.set_zoom(self.zoom*1.15))
        self.canvas.bind('<minus>',lambda event:self.set_zoom(self.zoom/1.15))
        self.canvas.bind('<Key-0>',lambda event:self.reset_view())
        for orient,row,col in (('vertical',0,1),('horizontal',1,0)):
            scrollbar=ttk.Scrollbar(diagram,orient=orient,style='Native.'+orient.title()+'.TScrollbar',
                                    command=self.canvas.yview if orient=='vertical' else self.canvas.xview)
            scrollbar.grid(row=row,column=col,sticky='ns' if orient=='vertical' else 'ew')
            self.canvas.configure(**({'yscrollcommand':scrollbar.set} if orient=='vertical' else {'xscrollcommand':scrollbar.set}))
        viewbar=tk.Frame(diagram,bg=PANEL,padx=3,pady=3)
        viewbar.place(x=10,y=8,anchor='nw')
        self.zoom_label=tk.StringVar(value='100 %')
        for text,callback in [('−',lambda:self.set_zoom(self.zoom/1.15)),('+',lambda:self.set_zoom(self.zoom*1.15)),('Centrer',
                                                                                                                     self.reset_view)]:
            ttk.Button(viewbar,text=text,command=callback,style='Native.TButton',width=2 if text!='Centrer' else 7).pack(side='left',padx=1)
        tk.Label(viewbar,textvariable=self.zoom_label,bg=PANEL,fg=MUTED,font=(self.font,8),padx=4).pack(side='left')
        legend=tk.Frame(self.topology_tab,bg=PANEL,padx=8,pady=3)
        legend.grid(row=2,column=0,sticky='ew')
        self.runtime_hint=tk.StringVar(value='État non observé')
        self.runtime_label=tk.Label(legend,textvariable=self.runtime_hint,bg=PANEL,fg=MUTED,font=(self.font,8))
        self.runtime_label.pack(side='left',padx=5)
        self.label(legend,'VLAN / adresses : configuration',MUTED,8).pack(side='right')
        # The device panel takes the full height on the right: the results log opens under the topology only, never over
        # the device's controls.
        device=self.device_panel=tk.Frame(body,bg=PANEL,width=430)
        device.pack_propagate(False)
        body.add(device,weight=0)
        self.device_tabs=ttk.Notebook(device,style='Native.TNotebook')
        self.device_tabs.pack(fill='both',expand=True)
        details_card=SoftPanel(self.device_tabs,BG)
        self.device_tabs.add(details_card,text='Aperçu')
        details=details_card.inner
        self.config_panel=SoftPanel(self.device_tabs,BG)
        self.device_tabs.add(self.config_panel,text='GUI')
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
        self.console_button=ttk.Button(self.console_panel.inner,text='Ouvrir la console Linux',command=self.open_console,
                                       style='Native.Primary.TButton')
        self.console_button.pack(fill='x',padx=14,pady=12)
        # The commands this node's terminal accepts, with examples: available before the lab runs, to prepare.
        self.catalogue_button=ttk.Button(self.console_panel.inner,text='📖 Catalogue de commandes',command=self.open_catalogue,
                                         style='Native.TButton')
        self.catalogue_button.pack(fill='x',padx=14,pady=(0,12))
        self.catalogue_window=None

        self.capture_panel=SoftPanel(self.device_tabs,BG)
        self.device_tabs.add(self.capture_panel,text='PCAP')
        self.capture_scroll=ScrollPanel(self.capture_panel.inner,PANEL)
        self.capture_scroll.canvas.configure(bd=0,relief='flat')
        self.capture_scroll.scroll.configure(style='Native.Vertical.TScrollbar')
        self.capture_scroll.pack(fill='both',expand=True)
        capture_form=self.capture_scroll.inner
        self.label(capture_form,'Capture réseau native',TEXT,11,True).pack(anchor='w',padx=14,pady=12)
        self.label(capture_form,'Interface du nœud sélectionné',MUTED,9).pack(anchor='w',padx=14)
        self.capture_interface=tk.StringVar()
        self.capture_ports=ttk.Combobox(capture_form,textvariable=self.capture_interface,state='readonly',style='Native.TCombobox')
        self.capture_ports.pack(fill='x',padx=14,pady=4)
        self.capture_seconds=tk.StringVar(value='10')
        self.capture_packets=tk.StringVar(value='1000')
        self.capture_filter=tk.StringVar(value='')
        for label,variable in [('Durée maximale · 1 à 60 secondes',self.capture_seconds),('Limite de paquets · budget 16 Mio',
                self.capture_packets),('Filtre BPF · vide = tout le trafic visible',self.capture_filter)]:
            self.label(capture_form,label,MUTED,9).pack(anchor='w',padx=14,pady=(8,0))
            ttk.Entry(capture_form,textvariable=variable,style='Native.TEntry').pack(fill='x',padx=14,pady=4)
        self.capture_button=ttk.Button(capture_form,text='Enregistrer une capture PCAP…',command=self.open_capture,
                                       style='Native.Primary.TButton')
        self.capture_button.pack(fill='x',padx=14,pady=12)
        self.build_trace_form(capture_form)
        tk.Label(capture_form,
                text='Choisir un nouveau fichier. La capture se déroule dans le namespace du nœud, sans interface '
                     'hôte.\n\nAuthentification, progression et résultat dans le terminal. Vous pouvez générer du trafic depuis le '
                     'logiciel pendant la capture.\n\nSnapshot : 2048 octets par paquet. Un fichier vide ne prouve pas une absence '
                     'de trafic.',bg=BG,fg=MUTED,font=(self.font,9),justify='left',wraplength=275).pack(fill='x',padx=14,pady=6)

        self.build_overview(details)  # the selected device at a glance (ui_overview)
        self.editor=self.text_area(self.editor_tab)
        self.output=self.text_area(self.output_tab)
        self.output.configure(state='disabled',background='#0b0f15',foreground='#edf1f7',insertbackground='white')
        self.output.master.configure(bg='#0b0f15')
        self.output.master.master.face='#0b0f15'
        self.output.tag_configure('empty',foreground='#7f93aa',font=(self.font,9))
        self.raw_output=self.text_area(self.raw_tab)
        self.raw_output.configure(state='disabled')
        validate_button=ttk.Button(self.editor_tab,text='Valider / plan',command=self.preview,style='Native.TButton')
        validate_button.grid(row=2,column=0,sticky='e',pady=4)
        self.buttons.append(validate_button)
        self.table=ttk.Treeview(diagnostics,columns=('runtime','implementation','detected','scope'),show='headings',style='Native.Treeview')
        for key,title,width in [('runtime','Runtime',100),('implementation','Implémentation',100),('detected','Détecté',80),('scope',
                'Périmètre',360)]:
            self.table.heading(key,text=title)
            self.table.column(key,width=width)
        self.table.pack(fill='both',expand=True)
        ttk.Button(diagnostics,text='Actualiser les dépendances',command=self.refresh,style='Native.TButton').pack(anchor='w',padx=8,pady=6)
        footer=tk.Frame(self.window,bg=PANEL,padx=10,pady=3)
        footer.grid_forget()
        self.counts=tk.StringVar()
        self.label(footer,'Sélection · état natif observé sur demande',MUTED,9).pack(side='left')
        tk.Label(footer,textvariable=self.counts,bg=PANEL,fg=TEAL,font=(self.font,8)).pack(side='right')
        self.window.bind('<Destroy>',self.destroyed,add='+')
        self.window.bind('<Configure>',self.schedule_reference_layout,add='+')
        self.content.bind('<Configure>',self.schedule_reference_layout,add='+')
        self.build_studio()  # the rail, top bar, device dock and canvas tools (ui_studio)
        # A blank canvas, as in Packet Tracer: devices come from the library (click or drag), cables from two clicks.
        self.load_spec(blank_project())
        self.refresh()
        self.schedule_reference_layout()

    def schedule_reference_layout(self,event=None):
        if self.closed or (event is not None and event.widget not in (self.window,self.content)):
            return
        if self.layout_id is not None:
            self.window.after_cancel(self.layout_id)
        self.layout_id=self.window.after_idle(self.fit_reference_layout)

    def fit_reference_layout(self):
        self.layout_id=None
        if not self.closed and self.content.winfo_height()>350:
            if len(self.content.panes())>1:  # the log stays hidden until asked
                self.content.sashpos(0,max(250,self.content.winfo_height()-210))
                self.lower.sashpos(0,int(self.content.winfo_width()*.55))
            # The device panel holds a section rail and a form: give it about 30% of the width (420-560 px)
            # so port names, addresses and action buttons are not cut off.
            width=self.body.winfo_width()
            if width>900:
                index=len(self.body.panes())-2
                target=width-max(420,min(560,int(width*.3)))
                if abs(self.body.sashpos(index)-target)>2:  # moving it resizes the content pane, which lays out again
                    self.body.sashpos(index,target)
            # Node positions depend on the canvas width: lay the topology out again for the fitted canvas, and
            # put the view back at the origin unless the user has zoomed or panned it.
            if getattr(self,'graph',None) and not self.pending:
                self.window.after_idle(self.refit_topology)

    def sync_navigation(self,event=None):
        if self.closed:
            return
        current=self.tabs.select()
        frames=[('Topologie',self.topology_tab),('Équipements',self.editor_tab),('Outils',self.tools_tab),('Scénarios',self.missions_tab)]
        self.nav_current=next((name for name,frame in frames if str(frame)==current),'Topologie')
        for name,(button,line) in self.nav_items.items():
            button.configure(fg=BLUE if name==self.nav_current else TEXT)
            line.configure(bg=BLUE if name==self.nav_current else BG)

    def refresh_search_hint(self):
        if self.search.get() or self.root.focus_get() is self.search_entry:
            self.search_hint.place_forget()
        else:self.search_hint.place(x=5,rely=.5,anchor='w')

    def label(self,parent,text,color=TEXT,size=10,bold=False):
        return tk.Label(parent,text=text,bg=parent.cget('bg'),fg=color,justify='left',font=(self.font,size,'bold' if bold else 'normal'))

    def text_area(self,parent):
        parent.rowconfigure(0,weight=1)
        parent.columnconfigure(0,weight=1)
        card=SoftPanel(parent,BG)
        card.grid(row=0,column=0,sticky='nsew')
        area=card.inner
        area.rowconfigure(0,weight=1)
        area.columnconfigure(0,weight=1)
        text=tk.Text(area,wrap='none',font=('DejaVu Sans Mono',9),undo=True,bd=0,highlightthickness=0)
        vertical=ttk.Scrollbar(area,command=text.yview,style='Native.Vertical.TScrollbar')
        horizontal=ttk.Scrollbar(area,orient='horizontal',command=text.xview,style='Native.Horizontal.TScrollbar')
        text.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        text.grid(row=0,column=0,sticky='nsew')
        vertical.grid(row=0,column=1,sticky='ns')
        horizontal.grid(row=1,column=0,sticky='ew')
        return text

    def refresh(self):
        self.table.delete(*self.table.get_children())
        for runtime in capabilities()['runtimes']:
            self.table.insert('','end',values=(runtime['id'],runtime['implementation'],
                                               'oui' if runtime['prerequisites_detected'] else 'non',runtime['scope']))

    def manifest(self):
        return validate(json.loads(self.editor.get('1.0','end-1c')))

    def error(self,error):
        messagebox.showerror('LAN natif',str(error),parent=self.window)

    def show_output(self,value):
        if getattr(self,'log_shown',None) is False:
            self.toggle_log(True)  # an operation's result: the log opens on it
        raw=json.dumps(value,ensure_ascii=False,indent=2)
        display=raw
        self.dock.tab(self.output_tab,text='Diagnostic réseau · lecture seule')
        if isinstance(value,dict) and isinstance(value.get('directions'),list):
            if value['directions']:
                first=value['directions'][0]
                self.dock.tab(self.output_tab,text='ICMP · '+str(first.get('source',''))[:18]+' ↔ '+str(first.get('destination',''))[:18])
            lines=['TEST ICMP · résultat : '+str(value.get('status','unknown')),'']
            for direction in value['directions']:
                lines.append(str(direction.get('source',''))+' → '+str(direction.get('destination','')))
                if direction.get('command'):
                    lines.append('$ '+' '.join(direction['command']))
                lines.append(direction.get('stdout') or direction.get('error') or direction.get('status','unknown'))
                lines.append('')
            display='\n'.join(lines)
        for target,text in ((self.output,display),(self.raw_output,raw)):
            target.configure(state='normal')
            target.delete('1.0','end')
            target.insert('1.0',text)
            target.configure(state='disabled')

    def open_capture(self):
        if self.pending:
            return False
        try:
            selected=self.nodes.selection()
            node=next((n for n in self.graph['nodes'] if selected and n['name']==selected[0]),None)
            if not node or self.states.get(node['name'],{}).get('status')!='running':
                raise ValueError('Démarrer le nœud puis actualiser son état avant la capture.')
            if self.manifest()['name']!=self.view_lab:
                raise ValueError('Le projet et le laboratoire observé diffèrent.')
            interface=self.capture_interface.get()
            if interface not in self.capture_ports.cget('values'):
                raise ValueError('Choisir une interface du nœud.')
            seconds=int(self.capture_seconds.get())
            packets=int(self.capture_packets.get())
            expression=self.capture_filter.get()
            from .capture import limits
            limits(seconds,packets,2048,expression)
            output=filedialog.asksaveasfilename(parent=self.window,defaultextension='.pcap',filetypes=[('Capture PCAP','*.pcap')],title='Nouveau fichier PCAP (sans écrasement)')
            if not output:
                return False
            from .ui_capture import terminal_args
            launch_terminal(terminal_args(self.view_lab,node['name'],interface,output,seconds,packets,expression))
            self.last_response=None
            self.note.set('Capture demandée pour '+node['name']+'/'+interface+' ; résultat dans le terminal.')
            self.record_event('capture','Terminal demandé : '+node['name']+'/'+interface)
            return True
        except (OSError,ValueError,TypeError,KeyError) as error:
            self.error(error)
            return False

    def open_console(self):
        if self.pending:
            return False
        try:
            selected=self.nodes.selection()
            node=next((n for n in self.graph['nodes'] if selected and n['name']==selected[0]),None)
            if not node or self.states.get(node['name'],{}).get('status')!='running':
                raise ValueError('Démarrer le lab puis actualiser son état avant le terminal du nœud.')
            if self.manifest()['name']!=self.view_lab:
                raise ValueError('Le projet et le laboratoire observé diffèrent.')
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
            self.error(error)
            return False

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
        if self.pending:
            return False
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
            response=read_result(path,pending['request']) if path.exists() else {'ok':False,
                    'error':'Aucun résultat reçu ; actualiser l’état. Le lab peut rester actif.'}
            self.apply_response(response,pending['request'])
        except (OSError,ValueError,TypeError,KeyError) as error:
            self.last_response={'ok':False,'uncertain':True,'error':str(error)}
            self.note.set('Résultat non confirmé : '+str(error))
            self.observation.set('État précédent non confirmé ; actualiser.')
            self.draw(self.graph)
            self.show_output(self.last_response)
        finally:
            pending['directory'].cleanup()
            self.pending=None
            self.busy(False)

    def apply_response(self,response,request):
        if not response['ok']:
            self.last_response=response
            self.note.set(response.get('error','Opération non confirmée.'))
            self.observation.set('État à vérifier ; aucune réussite déduite.')
            self.draw(self.graph)
            self.show_output(response)
            self.record_event(request['action'],self.note.get())
            return
        if response.get('lab')!=request['lab'] or response.get('action')!=request['action'] or response['topology']['name']!=request['lab']:
            raise ValueError('Le résultat ne correspond pas au lab demandé.')
        self.last_response=response
        action=request['action']
        data=response['data']
        graph=response['topology']
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
            if data.get('stopped')!=request['lab']:
                raise ValueError('Arrêt non confirmé.')
            states={n['name']:{'status':'stopped'} for n in graph['nodes']}
            self.observation.set(request['lab']+' · arrêt confirmé')
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
