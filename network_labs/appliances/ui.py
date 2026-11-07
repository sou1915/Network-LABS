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
from .workspace_art import draw_device,access_vlans,place_nodes,networks,firewall_hosts,link_caption,draw_port_labels
from .ui_bridge import SOURCE,client_args,private_json,public_topology,read_result,validate_request,validate_topology


def launch_terminal(command):
    terminal=shutil.which('x-terminal-emulator') or shutil.which('xterm')
    if not terminal or not shutil.which('sudo'):
        raise ValueError('Installer un terminal x-terminal-emulator/xterm et sudo pour le contrôle natif.')
    return subprocess.Popen([terminal,'-e',*command],cwd=SOURCE)


class ApplianceWindow:
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
        for title,commands in [('Fichier',[('Nouveau LAN',self.new),('Campus entreprise',self.new_campus),('LAN sécurité access',lambda:self.new_campus(security=True)),('Ouvrir',self.open),('Enregistrer',self.save)]),
                               ('Édition',[('Ajouter un équipement',self.add_device_dialog),('Connecter un câble',lambda:self.set_edit_mode('cable')),('Supprimer',self.delete_selected)]),
                               ('Affichage',[('Topologie',lambda:self.tabs.select(self.topology_tab)),('Configuration du projet',lambda:self.tabs.select(self.editor_tab)),('Configuration du dispositif',lambda:self.device_tabs.select(self.config_panel))]),
                               ('Outils',[('Valider / plan',self.preview),('Actualiser l’état',lambda:self.launch('status'))])]:
            menu_button=tk.Menubutton(header,text=title,bg='#223344',fg='white',activebackground='#334b60',activeforeground='white',font=(self.font,8),padx=8)
            menu=tk.Menu(menu_button,tearoff=False)
            for label,callback in commands:menu.add_command(label=label,command=callback)
            menu_button.configure(menu=menu);menu_button.pack(side='left')
        if self.embedded:ttk.Button(header,text='Retour',command=self.close,style='Native.TButton').pack(side='right')
        toolbar=tk.Frame(self.window,bg='#f1f5fb',padx=7,pady=2);toolbar.grid(row=1,column=0,sticky='ew',pady=(0,2))
        for title,callback in [('↖ Sélection',lambda:self.set_edit_mode(None)),('+ Ajouter un équipement',self.add_device_dialog),('⌁ Connecter un câble',lambda:self.set_edit_mode('cable')),('Supprimer',self.delete_selected)]:
            if title.startswith('↖') or title.startswith('⌁'):
                button=ttk.Radiobutton(toolbar,text=title,command=callback,variable=self.tool_mode,value='select' if title.startswith('↖') else 'cable',style='Native.Toolbutton')
            else:button=ttk.Button(toolbar,text=title,command=callback,style='Native.TButton')
            button.pack(side='left',padx=2);self.buttons.append(button)
        for title,action in [('▶ Démarrer','start'),('↻ État','status'),('■ Arrêter','stop')]:
            button=ttk.Button(toolbar,text=title,command=lambda a=action:self.launch(a),style='Native.TButton');button.pack(side='left',padx=3);self.buttons.append(button)
        button=ttk.Button(toolbar,text='▣ Enregistrer',command=self.save,style='Native.TButton');button.pack(side='left',padx=3);self.buttons.append(button)

        nav=tk.Frame(self.window,bg=BG,height=24);nav.grid(row=2,column=0,sticky='ew')
        self.nav_items={};self.nav_current='Topologie'
        for label,callback in [('Topologie',lambda:self.tabs.select(self.topology_tab)),('Équipements',lambda:self.tabs.select(self.editor_tab)),('Scénarios',self.new_campus),('Outils',lambda:self.tabs.select(self.tools_tab))]:
            item=tk.Frame(nav,bg=BG);item.pack(side='left')
            button=tk.Button(item,text=label,command=callback,font=(self.font,8),bg=BG,fg=BLUE if label=='Topologie' else TEXT,relief='flat',borderwidth=0,highlightthickness=0,padx=12,pady=4,activebackground='white',activeforeground=BLUE);button.pack()
            line=tk.Frame(item,bg=BLUE if label=='Topologie' else BG,height=2);line.pack(fill='x')
            self.nav_items[label]=(button,line)
        body=ttk.Panedwindow(self.window,orient='horizontal');body.grid(row=3,column=0,sticky='nsew',padx=4)
        library_card=SoftPanel(body,BG,SIDEBAR);library_card.configure(width=196);body.add(library_card,weight=0);library=library_card.inner
        content=self.content=ttk.Panedwindow(body,orient='vertical');body.add(content,weight=1)
        workspace=ttk.Panedwindow(content,orient='horizontal');content.add(workspace,weight=3)
        lower=self.lower=ttk.Panedwindow(content,orient='horizontal');content.add(lower,weight=1)
        self.dock=ttk.Notebook(lower,height=155,style='Native.TNotebook');lower.add(self.dock,weight=3)
        self.activity_book=ttk.Notebook(lower,height=155,style='Native.TNotebook');lower.add(self.activity_book,weight=2)
        activity_card=SoftPanel(self.activity_book,BG);self.activity_book.add(activity_card,text='Événements');activity=activity_card.inner
        self.activity=ttk.Treeview(activity,columns=('time','action','result'),show='headings',height=5,style='Native.Treeview')
        for key,title,width in [('time','Heure',75),('action','Opération',85),('result','Résultat observé',280)]:
            self.activity.heading(key,text=title);self.activity.column(key,width=width,minwidth=60)
        self.activity.tag_configure('failed',foreground=RED);self.activity.tag_configure('passed',foreground=TEAL)
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
        self.raw_tab=ttk.Frame(self.dock);self.dock.add(self.raw_tab,text='Détails JSON')
        for frame,title in ((self.topology_tab,'Topologie'),(self.editor_tab,'Équipements / JSON'),(diagnostics,'Outils')):
            self.tabs.add(frame,text=title)
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
        device=tk.Frame(workspace,bg=PANEL,width=354);device.pack_propagate(False);workspace.add(device,weight=0)
        self.device_tabs=ttk.Notebook(device,style='Native.TNotebook');self.device_tabs.pack(fill='both',expand=True)
        details_card=SoftPanel(self.device_tabs,BG);self.device_tabs.add(details_card,text='État / test');details=details_card.inner
        self.config_panel=SoftPanel(self.device_tabs,BG);self.device_tabs.add(self.config_panel,text='GUI')
        self.build_config_form(self.config_panel.inner)
        self.label(details,'État de l’équipement',TEXT,9,True).pack(anchor='w',padx=14,pady=8)
        self.selected_title=tk.StringVar();self.selected_details=tk.StringVar()
        tk.Label(details,textvariable=self.selected_title,bg=PANEL,fg=TEXT,font=(self.font,10,'bold'),anchor='w').pack(fill='x',padx=14)
        tk.Label(details,textvariable=self.selected_details,bg=PANEL,fg=MUTED,justify='left',anchor='w',wraplength=265).pack(fill='x',padx=14,pady=4)
        self.nodes=ttk.Treeview(details,columns=('runtime','state','memory'),displaycolumns=('state','memory'),show='tree headings',height=3,selectmode='browse',style='Native.Treeview')
        for key,label,width in (('#0','Nœud',65),('runtime','Runtime',65),('state','État OCI',115),('memory','RAM',70)):
            self.nodes.heading(key,text=label);self.nodes.column(key,width=width,minwidth=45,stretch=True)
        self.nodes.pack(fill='x',padx=8);self.nodes.bind('<<TreeviewSelect>>',self.select_node)
        controls=tk.Frame(details,bg=PANEL,padx=12,pady=6);controls.pack(fill='x')
        self.inspect_button=ttk.Button(controls,text='Inspecter le réseau',command=lambda:self.launch('inspect'),style='Native.TButton');self.inspect_button.pack(fill='x')
        self.label(controls,'TEST DE CONNECTIVITÉ',MUTED,9,True).pack(anchor='w',pady=(8,4))
        self.destination=tk.StringVar();self.targets=ttk.Combobox(controls,textvariable=self.destination,state='readonly',style='Native.TCombobox',font=(self.font,9));self.targets.pack(fill='x',pady=4)
        self.verify_button=ttk.Button(controls,text='Tester la liaison',command=lambda:self.launch('verify'),style='Native.Primary.TButton');self.verify_button.pack(fill='x',pady=4)
        self.note=tk.StringVar(value='Ouvrir un projet natif ou créer un LAN pour commencer.')
        tk.Label(details,textvariable=self.note,bg=PANEL,fg=BLUE,font=(self.font,8),justify='left',anchor='nw',wraplength=265).pack(fill='x',padx=14,pady=4)
        self.label(details,'Vert : processus actif. Tester le réseau.',MUTED,7).pack(side='bottom',padx=12,pady=6)
        self.editor=self.text_area(self.editor_tab);self.output=self.text_area(self.output_tab);self.output.configure(state='disabled',background='#0b0f15',foreground='#edf1f7',insertbackground='white');self.output.master.configure(bg='#0b0f15');self.output.master.master.face='#0b0f15'
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
        self.load_spec(campus_example(Path.home()/'network-labs-rootfs'));self.refresh();self.schedule_reference_layout()

    def schedule_reference_layout(self,event=None):
        if self.closed or (event is not None and event.widget not in (self.window,self.content)):return
        if self.layout_id is not None:self.window.after_cancel(self.layout_id)
        self.layout_id=self.window.after_idle(self.fit_reference_layout)

    def fit_reference_layout(self):
        self.layout_id=None
        if not self.closed and self.content.winfo_height()>350:
            self.content.sashpos(0,max(250,self.content.winfo_height()-184))
            self.lower.sashpos(0,int(self.content.winfo_width()*.55))

    def sync_navigation(self,event=None):
        if self.closed:return
        current=self.tabs.select()
        self.nav_current=next((name for name,frame in [('Topologie',self.topology_tab),('Équipements',self.editor_tab),('Outils',self.tools_tab)] if str(frame)==current),'Topologie')
        for name,(button,line) in self.nav_items.items():
            button.configure(fg=BLUE if name==self.nav_current else TEXT)
            line.configure(bg=BLUE if name==self.nav_current else BG)

    def refresh_search_hint(self):
        if self.search.get() or self.root.focus_get() is self.search_entry:self.search_hint.place_forget()
        else:self.search_hint.place(x=5,rely=.5,anchor='w')

    def label(self,parent,text,color=TEXT,size=10,bold=False):
        return tk.Label(parent,text=text,bg=parent.cget('bg'),fg=color,justify='left',font=(self.font,size,'bold' if bold else 'normal'))

    def build_library_palette(self,parent):
        catalog=[('Routeurs',[('router','Routeur Linux','Routage / 802.1Q','blue')]),
                 ('Switches',[('switch','Switch Linux','VLAN / ports','blue')]),
                 ('Pare-feu',[('firewall','Pare-feu Linux','Politique nftables','blue')]),
                 ('Postes clients',[('host','Poste Linux','Thème bleu','blue'),('host','Poste Linux','Thème rouge','red')]),
                 ('Serveurs',[('server','Serveur Linux','Réseau Ethernet','blue')])]
        container=tk.Frame(parent,bg=SIDEBAR);container.pack(fill='x')
        self.palette_groups=[]
        for category,entries in catalog:
            group=tk.Frame(container,bg=SIDEBAR);group.pack(fill='x');tiles=[]
            self.palette_groups.append((group,tiles))
            self.label(group,category,TEXT,8,True).pack(anchor='w',padx=9,pady=(7,2))
            for kind,title,subtitle,variant in entries:
                tile=SoftCard(group,SIDEBAR);tile.pack(fill='x',padx=7,pady=3)
                icon=tk.Canvas(tile.inner,width=60,height=32,bg=PANEL,highlightthickness=0);icon.pack(side='left')
                draw_device(icon,kind,31,17,scale=.46,variant=variant)
                caption=tk.Frame(tile.inner,bg=PANEL);caption.pack(side='left',fill='x')
                self.label(caption,title,TEXT,9).pack(anchor='w');self.label(caption,subtitle,MUTED,7).pack(anchor='w')
                def bind(widget,r=kind,card=tile):
                    widget.bind('<Button-1>',lambda event:self.add_device_dialog(r))
                    widget.bind('<Enter>',lambda event:card.hover(True))
                    widget.bind('<Leave>',lambda event:card.hover(False))
                    for child in widget.winfo_children():bind(child,r,card)
                bind(tile);tiles.append((tile,(category+' '+title+' '+subtitle+' '+kind).casefold()))

    def toggle_project_list(self):
        self.project_list_open=not self.project_list_open
        if self.project_list_open:self.project_list.pack(fill='both',expand=True,padx=7)
        else:self.project_list.pack_forget()
        self.project_toggle.configure(text=('▾' if self.project_list_open else '▸')+' Équipements du projet')

    def record_event(self,action,result):
        tag='failed' if 'failed' in result or 'blocked' in result else 'passed' if 'passed' in result else ''
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
        self.editor.delete('1.0','end');self.editor.insert('1.0',json.dumps(spec,indent=2))
        self.config_key=None;self.positions={};self.zoom=1.;self.draw(public_topology(spec));self.view_origin(0,0);self.observation.set('Topologie déclarée · état runtime à actualiser.')

    def draw(self,graph,states=None):
        validate_topology(graph)
        selected=self.nodes.selection();previous=selected[0] if selected else None;destination=self.destination.get()
        self.graph=graph;self.view_lab=graph['name'];self.states=states or {};self.node_shapes={};self.link_shapes={}
        from ..__main__ import App
        self.canvas.delete('all');self.nodes.delete(*self.nodes.get_children());self.library.delete(*[n['name'] for n in getattr(self,'library_graph',{}).get('nodes',[]) if self.library.exists(n['name'])]);self.library_graph=graph
        width=max(600,self.canvas.winfo_width());height=max(360,self.canvas.winfo_height())
        spec=None;members={}
        try:
            candidate=self.manifest()
            if public_topology(candidate)==graph:spec=candidate;members=access_vlans(graph,spec)
        except (ValueError,TypeError,KeyError):pass
        config={n['name']:n for n in spec['nodes']} if spec else {}
        positions=place_nodes(graph,members,width)
        positions.update({name:point for name,point in self.positions.items() if name in positions})
        self.drawn_positions=positions
        for xx in range(-142,int(width/max(.65,self.zoom))+160,22):
            for yy in range(-142,int(height/max(.65,self.zoom))+160,22):self.canvas.create_oval(xx,yy,xx+1,yy+1,fill='#e8eef7',outline='',tags=('grid',))
        palette=[('#e8f4ff','#8fc0ed','#0064c7'),('#e9f8ed','#9ed4ad','#14884b'),('#fff7dd','#ead08b','#ba7a04')]
        self.vlan_members=members;captions=[]
        for index,vid in enumerate(sorted(set(members.values()))):
            names=[n for n in members if members[n]==vid];points=[positions[n] for n in names]
            span=max(max(x for x,y in points)-min(x for x,y in points)+104,width/max(1,len(set(members.values())))-18)
            middle=(min(x for x,y in points)+max(x for x,y in points))/2
            x1=middle-span/2;x2=middle+span/2
            y1=min(y for x,y in points)-82;y2=max(y for x,y in points)+64
            bg,border,ink=palette[index%len(palette)]
            rounded_box(self.canvas,x1,y1,x2,y2,r=16,fill=bg,outline=border,dash=(3,2),tags=('vlan-group',))
            captions.append((x1,y1,x2,bg,ink,vid,networks(graph,names,spec,vid)))
        dmz=firewall_hosts(graph)
        for name in dmz:
            xx,yy=positions[name]
            rounded_box(self.canvas,xx-43,yy-52,xx+43,yy+76,r=14,fill='#f2ecff',outline='#cbb9ec',dash=(3,2),tags=('firewall-zone',))
            self.canvas.create_text(xx,yy-40,text='Segment pare-feu',fill='#705493',font=(self.font,7,'bold'))
        graph_nodes={n['name']:n for n in graph['nodes']};port_labels=[]
        for index,(a,b) in enumerate(graph['links']):
            x,y=positions[a[0]];xx,yy=positions[b[0]]
            if abs(y-yy)<45:
                sign=1 if xx>x else -1;ax=x+sign*55;ay=y;bx=xx-sign*55;by=yy;points=(ax,ay,bx,by)
            else:
                sign=1 if yy>y else -1;ax=x;ay=y+sign*25;bx=xx;by=yy-sign*25
                if graph_nodes[a[0]]['role']!='host':ax+=(list(graph_nodes[a[0]]['interfaces']).index(a[1])%8-3.5)*7
                if graph_nodes[b[0]]['role']!='host':bx+=(list(graph_nodes[b[0]]['interfaces']).index(b[1])%8-3.5)*7
                mid=min(ay,by)+8+(index%3)*8
                points=(ax,ay,ax,mid,bx,mid,bx,by)
            self.link_shapes[index]=self.canvas.create_line(*points,fill='#3886b9',width=1.5,joinstyle='round',capstyle='round',tags=('link','link:'+str(index)))
            self.canvas.tag_bind('link:'+str(index),'<Button-3>',lambda event,aa=a,bb=b:self.remove_cable(aa,bb))
            for endpoint,peer,px,py in ((a,b,ax,ay),(b,a,bx,by)):
                self.canvas.create_oval(px-2,py-2,px+2,py+2,fill='#4f83b3',outline='')
                nx,ny=positions[endpoint[0]];other_y=positions[peer[0]][1]
                ordinal=list(graph_nodes[endpoint[0]]['interfaces']).index(endpoint[1])
                tx,ty,anchor=px+5,py-8,'w'
                if graph_nodes[endpoint[0]]['role']!='host':
                    if other_y<ny-45:tx,ty,anchor=nx-56,ny-19,'e'
                    else:tx,ty=px+5,ny+30+(ordinal%4)*10
                port_labels.append(dict(x=tx,y=ty,text=endpoint[1],anchor=anchor,tag='link:'+str(index)))
            caption=link_caption(a,b,config)
            if caption:
                lx=(ax+bx)/2;ly=((ay+by)/2 if abs(y-yy)<45 else mid)-12
                self.canvas.create_text(lx,ly,text=caption,fill='#315b7d',font=(self.font,7))
        for x1,y1,x2,bg,ink,vid,subnets in captions:
            rounded_box(self.canvas,x1+3,y1+3,x2-3,y1+41,r=9,fill=bg,outline='')
            self.canvas.create_text((x1+x2)/2,y1+14,text=f'VLAN {vid}',fill=ink,font=(self.font,8,'bold'),tags=('vlan-label',))
            self.canvas.create_text((x1+x2)/2,y1+30,text=subnets,fill=MUTED,font=(self.font,7))
        for node in graph['nodes']:
            name=node['name'];x,y=positions[name];observed=self.states.get(name,{})
            state=observed.get('status','non observé');memory=observed.get('memory')
            color='#21c632' if state=='running' else '#8b9cae';tags=('node','node:'+name)
            self.node_shapes[name]=rounded_box(self.canvas,x-44 if node['role']=='host' else x-58,y-34 if node['role']=='host' else y-43,x+44 if node['role']=='host' else x+58,y+66 if node['role']=='host' else y+43,fill='',outline='',width=1,tags=tags)
            kind='server' if name in dmz or name.upper().startswith('SRV') else node['role']
            host_index=[n['name'] for n in graph['nodes'] if n['role']=='host'].index(name) if node['role']=='host' else 0
            draw_device(self.canvas,kind,x,y,scale=.85 if node['role']=='host' else .9,tags=tags,variant='red' if host_index%2 else 'blue')
            if node['role']=='host':
                self.canvas.create_text(x,y+36,text=name,fill=TEXT,font=(self.font,9,'bold'),tags=tags)
                ips=[v.split('/')[0] for v in node['interfaces'].values() if v]
                self.canvas.create_text(x,y+49,text=', '.join(ips) or 'Linux · OCI',fill=MUTED,font=(self.font,8),tags=tags)
            else:
                self.canvas.create_text(x,y-48,text=name,fill=TEXT,font=(self.font,9,'bold'),tags=tags)
                self.canvas.create_text(x,y-34,text={'switch':'Switch Linux','router':'Routeur Linux','firewall':'Pare-feu Linux'}.get(node['role'],'Linux'),fill=MUTED,font=(self.font,8),tags=tags)
            self.canvas.create_oval(x+36,y+14,x+43,y+21,fill=color,outline='#ffffff',tags=tags)
            self.canvas.tag_bind('node:'+name,'<Button-1>',lambda event,n=name:self.node_pressed(event,n))
            self.canvas.tag_bind('node:'+name,'<Double-Button-1>',lambda event,n=name:self.open_device_config(n))
            self.canvas.tag_bind('node:'+name,'<Enter>',lambda event,n=name:self.hover_node(n,True))
            self.canvas.tag_bind('node:'+name,'<Leave>',lambda event,n=name:self.hover_node(n,False))
            self.nodes.insert('','end',iid=name,text=name,values=(node['runtime'],state,'—' if memory is None else f'{memory/1048576:.1f} MiB'))
            self.library.insert('','end',iid=name,text=name)
        obstacles=[self.canvas.bbox(item) for item in self.canvas.find_all() if self.canvas.type(item)=='text']
        for node in graph['nodes']:
            x,y=positions[node['name']];host=node['role']=='host'
            obstacles.append((x-32 if host else x-50,y-29,x+32 if host else x+50,y+24))
        draw_port_labels(self.canvas,port_labels,obstacles,(self.font,7),MUTED)
        for index,(a,b) in enumerate(graph['links']):
            self.canvas.tag_bind('link:'+str(index),'<Button-3>',lambda event,aa=a,bb=b:self.remove_cable(aa,bb))
        running=sum(n['runtime']=='oci' and self.states.get(n['name'],{}).get('status')=='running' for n in graph['nodes'])
        stopped=bool(self.states) and all(self.states.get(n['name'],{}).get('status')=='stopped' for n in graph['nodes'])
        self.runtime_hint.set(f'● Relevé : {running} processus OCI en marche' if running else '● Arrêt confirmé' if stopped else '○ État non observé')
        self.runtime_label.configure(fg='#159746' if running else MUTED)
        self.filter_library();self.project_title.set(graph['name'])
        self.counts.set(f"{len(graph['nodes'])} équipements  /  {len(graph['links'])} liens  /  {graph['name']}")
        if self.zoom!=1.:
            for item in self.canvas.find_all():
                if self.canvas.type(item)=='text':
                    font=self.canvas.tk.splitlist(self.canvas.itemcget(item,'font'))
                    self.canvas.itemconfigure(item,font=(font[0],max(6,round(int(font[1])*self.zoom)),*font[2:]))
            self.canvas.scale('all',0,0,self.zoom,self.zoom)
        self.canvas.configure(scrollregion=(-100,-100,max(width,(max(x for x,y in positions.values())+90)*self.zoom)+100,max(height,(max(y for x,y in positions.values())+90)*self.zoom)+100))
        self.zoom_label.set(f'{round(self.zoom*100)} %')
        hosts=[n['name'] for n in graph['nodes'] if n['runtime']=='oci' and n['role']=='host']
        self.targets.configure(values=hosts);self.destination.set(destination if destination in hosts else hosts[-1] if hosts else '')
        if graph['nodes']:self.choose_node(previous if previous in positions else graph['nodes'][0]['name'])

    def choose_node(self,name):self.nodes.selection_set(name);self.nodes.see(name);self.select_node()
    def select_node(self,event=None):
        selected=self.nodes.selection();node=next((n for n in self.graph['nodes'] if selected and n['name']==selected[0]),None)
        if node:
            name=node['name'];state=self.states.get(name,{}).get('status','non observé')
            self.selected_title.set(name);self.selected_details.set(node['role']+' · '+node['runtime']+'\nÉtat : '+state+'\nInterfaces : '+', '.join(node['interfaces']))
            if self.library.selection()!=(name,):self.library.selection_set(name)
            for key,shape in self.node_shapes.items():self.canvas.itemconfigure(shape,outline=BLUE if key==name else '',width=2 if key==name else 1)
        self.inspect_button.state(['!disabled'] if node and node['runtime']=='oci' and not self.pending else ['disabled'])
        self.verify_button.state(['!disabled'] if node and node['runtime']=='oci' and node['role']=='host' and not self.pending else ['disabled'])
        if node:self.load_config()
        self.config_apply.state(['!disabled'] if node and node['runtime']=='oci' and not self.pending and self.config_baseline is not None else ['disabled'])

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
        self.dragging=None;self.panning=False;self.zoom=1.;self.draw(self.graph,self.states)
        self.view_origin(0,0)

    def view_origin(self,x,y):
        region=tuple(float(v) for v in self.canvas.cget('scrollregion').split())
        self.canvas.xview_moveto((x-region[0])/max(1,region[2]-region[0]))
        self.canvas.yview_moveto((y-region[1])/max(1,region[3]-region[1]))

    def begin_pan(self,event):
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
        tk.Label(parent,textvariable=self.device_heading,bg='#f5f8fc',fg=TEXT,font=(self.font,9,'bold'),anchor='w',padx=9,pady=5).pack(fill='x')
        brand_card=SoftCard(parent,PANEL,face='#df1723',border='#df1723');brand_card.pack(fill='x',pady=3);brand=brand_card.inner
        tk.Label(brand,text='NETWORK LABS',bg='#df1723',fg='white',font=(self.font,12,'bold'),padx=9,pady=6).pack(side='left')
        tk.Label(brand,text='Linux · GUI',bg='#df1723',fg='white',font=(self.font,8),padx=6).pack(side='right')
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
        for key,label,width in [('#0','Nom',45),('address','Adresse IPv4',130),('admin','Admin',48)]:
            self.port_table.heading(key,text=label);self.port_table.column(key,width=width,minwidth=35)
        self.port_table.tag_configure('enabled',foreground='#168942');self.port_table.tag_configure('disabled',foreground='#bb3646')
        self.port_table.pack(fill='x');self.port_table.bind('<<TreeviewSelect>>',self.config_table_selected)
        detail_card=SoftCard(form,PANEL,face='#edf2f7',border='#edf2f7');detail_card.pack(fill='x',padx=7,pady=(10,5));detail=detail_card.inner
        self.label(detail,'Détails de l’interface',TEXT,8,True).pack(anchor='w',padx=7,pady=5)
        fields=tk.Frame(form,bg=PANEL);fields.pack(fill='x',padx=9)
        fields.columnconfigure(1,weight=1)
        self.config_vars={key:tk.StringVar() for key in ('name','port','address','gateway')};self.config_fields={}
        for row,(key,title) in enumerate([('name','Nom système'),('port','Interface'),('address','IPv4 / CIDR'),('gateway','Passerelle')]):
            self.label(fields,title,MUTED,8).grid(row=row,column=0,sticky='w',padx=(0,7),pady=3)
            field=ttk.Combobox(fields,textvariable=self.config_vars[key],state='readonly',style='Native.TCombobox',width=15,font=(self.font,9)) if key=='port' else ttk.Entry(fields,textvariable=self.config_vars[key],style='Native.TEntry',width=15,font=(self.font,9))
            field.grid(row=row,column=1,sticky='ew',pady=3);self.config_fields[key]=field
        self.config_fields['port'].bind('<<ComboboxSelected>>',self.config_port_selected)
        self.config_enabled=tk.BooleanVar(value=True)
        self.config_admin=ttk.Checkbutton(form,text='Interface activée',variable=self.config_enabled,style='Native.TCheckbutton');self.config_admin.pack(anchor='w',padx=9,pady=5)
        self.config_apply=ttk.Button(self.config_actions,text='Appliquer au brouillon',command=self.apply_config,style='Native.Primary.TButton');self.config_apply.pack(side='left',fill='x',expand=True,padx=(0,5))
        ttk.Button(self.config_actions,text='Recharger',command=lambda:self.load_config(force=True),style='Native.TButton').pack(side='right')
        self.config_message=tk.StringVar()
        tk.Label(form,textvariable=self.config_message,bg=PANEL,fg=MUTED,font=(self.font,7),justify='left',wraplength=230,anchor='w').pack(fill='x',padx=9,pady=7)

    def open_web_management(self,page='interfaces'):
        selected=self.nodes.selection()
        if not selected:return
        from ..web_portal import WebPortal
        from .web_management import NativeDeviceAPI
        if self.web_portal is None:self.web_portal=WebPortal(self,api=NativeDeviceAPI(self),native=True)
        self.web_portal.open(selected[0],page=page)

    def config_table_selected(self,event=None):
        selected=self.port_table.selection()
        if selected and selected[0]!=self.config_vars['port'].get():
            self.config_vars['port'].set(selected[0]);self.config_port_selected()

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
            self.device_heading.set(node['name']+' · '+{'host':'Linux','switch':'Switch Linux','router':'Routeur Linux','firewall':'Pare-feu Linux'}[node['role']])
            self.port_table.delete(*self.port_table.get_children())
            self.port_table.configure(height=max(1,min(3,len(node['interfaces']))))
            for port,address in node['interfaces'].items():
                enabled=port not in node.get('shutdown',[])
                self.port_table.insert('','end',iid=port,text=port,values=(address or '—','Activé' if enabled else 'Arrêté'),tags=('enabled' if enabled else 'disabled',))
            self.config_vars['name'].set(node['name']);self.config_vars['gateway'].set(node.get('gateway',''))
            ports=list(node['interfaces']);self.config_fields['port'].configure(values=ports)
            self.config_vars['port'].set(ports[0] if ports else '')
            self.config_port_selected()
            self.config_fields['name'].configure(state='normal' if node['runtime']=='oci' else 'disabled')
            self.config_fields['gateway'].configure(state='normal' if node['runtime']=='oci' and node['role']!='switch' else 'disabled')
            self.config_message.set('Modifier un port puis appliquer. Le réseau actif reste inchangé.' if node['runtime']=='oci' else 'MicroVM : configuration JSON uniquement.')
            self.config_apply.state(['!disabled'] if ports and node['runtime']=='oci' and not self.pending else ['disabled'])
        except (ValueError,TypeError,KeyError,StopIteration) as error:
            self.config_message.set(str(error));self.config_apply.state(['disabled'])

    def config_port_selected(self,event=None):
        if self.config_baseline is None:return
        node=next(n for n in self.config_baseline['nodes'] if n['name']==self.config_key[1])
        port=self.config_vars['port'].get()
        self.config_vars['address'].set(node['interfaces'].get(port,''));self.config_enabled.set(port not in node.get('shutdown',[]))
        if self.port_table.exists(port) and self.port_table.selection()!=(port,):self.port_table.selection_set(port)
        editable=node['runtime']=='oci' and node['role']!='switch' and port not in node.get('dhcp_clients',[])
        self.config_fields['address'].configure(state='normal' if editable else 'disabled')
        self.config_admin.state(['!disabled'] if node['runtime']=='oci' else ['disabled'])

    def apply_config(self):
        try:
            current=self.editing_spec()
            if self.config_baseline is None or current!=self.config_baseline:
                raise ValueError('Le projet a changé. Recharger le formulaire avant d’appliquer.')
            old=self.config_key[1];values={k:v.get().strip() for k,v in self.config_vars.items()}
            result=topology_edit.configure_node(current,old,new_name=values['name'],port=values['port'],address=values['address'],gateway=values['gateway'],enabled=self.config_enabled.get())
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
        self.note.set('Câbler : choisir deux équipements, puis leurs ports libres.' if mode=='cable' else 'Sélectionner ou déplacer un équipement · clic droit sur un câble pour le retirer.')

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
                first=self.cable_source;self.cable_source=None;self.connect_dialog(first,name)
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
        offset=16 if next(n for n in self.graph['nodes'] if n['name']==name)['role']=='host' else 0
        self.positions[name]=(max(50,(min(box[::2])+max(box[::2]))/(2*self.zoom)),max(60,(min(box[1::2])+max(box[1::2]))/(2*self.zoom)-offset))
        self.draw(self.graph,self.states)

    def add_device_dialog(self,role='host'):
        server=role=='server'
        if server:role='host'
        try:spec=self.editing_spec()
        except (ValueError,TypeError,KeyError) as error:self.error(error);return
        win=tk.Toplevel(self.window);win.title('Ajouter un équipement Linux natif');win.transient(self.window.winfo_toplevel())
        form=ttk.Frame(win,padding=14);form.pack(fill='both',expand=True)
        values={}
        rootfs=next((n['rootfs'] for n in spec['nodes'] if n['runtime']=='oci'),'')
        prefix='SRV' if server else {'host':'PC','switch':'SW','router':'R','firewall':'FW'}[role];used={n['name'] for n in spec['nodes']}
        suggested=next(prefix+str(i) for i in range(1,258) if prefix+str(i) not in used)
        for row,(key,title,initial) in enumerate([('name','Nom',suggested),('role','Rôle',role),('rootfs','Rootfs Linux',rootfs),('ports','Nombre de ports',{'host':'1','switch':'8','router':'3','firewall':'2'}[role]),('address','IPv4 eth0 / CIDR (facultatif)','')]):
            ttk.Label(form,text=title).grid(row=row,column=0,sticky='w',pady=5)
            value=tk.StringVar(value=initial);values[key]=value
            field=ttk.Combobox(form,textvariable=value,values=('host','switch','router','firewall'),state='readonly',style='Native.TCombobox',font=(self.font,9)) if key=='role' else ttk.Entry(form,textvariable=value,width=38,style='Native.TEntry',font=(self.font,9))
            field.grid(row=row,column=1,sticky='ew',padx=8)
        def browse():
            path=filedialog.askdirectory(parent=win,title='Rootfs Linux')
            if path:values['rootfs'].set(path)
        ttk.Button(form,text='Parcourir…',command=browse,style='Native.TButton').grid(row=2,column=2)
        ttk.Label(form,text='Linux natif · pare-feu : trafic transitant bloqué par défaut.').grid(row=5,column=0,columnspan=3,pady=8)
        def apply():
            try:
                current=self.editing_spec()
                result=topology_edit.add_node(current,**{k:v.get().strip() for k,v in values.items() if k!='ports'},ports=int(values['ports'].get()),firewall={'default':'drop','stateful':True,'rules':[]} if values['role'].get()=='firewall' else None)
                self.commit_edit(result);self.choose_node(values['name'].get().strip());win.destroy()
            except (ValueError,TypeError,KeyError) as error:self.error(error)
        ttk.Button(form,text='Ajouter au brouillon',command=apply,style='Native.Primary.TButton').grid(row=6,column=1,sticky='e')
        ttk.Button(form,text='Annuler',command=win.destroy,style='Native.TButton').grid(row=6,column=0)

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
        if self.pending:return False
        rootfs=filedialog.askdirectory(parent=self.window,title='Rootfs BusyBox natif')
        if not rootfs:return
        name=simpledialog.askstring('Nouveau LAN','Nom du lab :',initialvalue='micro-lan',parent=self.window)
        if not name:return
        try:spec=example(rootfs);spec['name']=name;self.load_spec(spec);self.tabs.select(self.topology_tab)
        except (ValueError,TypeError,KeyError) as error:self.error(error)

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

    def save(self):
        if self.pending:return False
        try:
            spec=self.manifest();path=self.path or filedialog.asksaveasfilename(parent=self.window,defaultextension='.json',filetypes=[('Native lab JSON','*.json')])
            if not path:return False
            self.path=Path(path).resolve();private_json(self.path,spec);return True
        except (OSError,ValueError,TypeError,KeyError) as error:self.error(error);return False

    def busy(self,enabled):
        for button in self.buttons:button.state(['disabled'] if enabled else ['!disabled'])
        self.editor.configure(state='disabled' if enabled else 'normal');self.select_node()

    def launch(self,action):
        if self.pending:return False
        directory=None
        try:
            if action=='start':
                if not self.save():return False
                spec=self.manifest();lab=spec['name']
            else:lab=self.view_lab
            directory=tempfile.TemporaryDirectory(prefix='network-labs-gui-')
            target=lab
            if action=='start':target=str(Path(directory.name)/'manifest.json');private_json(target,spec)
            selected=self.nodes.selection();node=selected[0] if selected and action in ('inspect','verify') else None
            request=validate_request({'id':uuid.uuid4().hex,'owner_uid':os.geteuid(),'action':action,'target':target,'lab':lab,'node':node,
                                      'destination':self.destination.get() if action=='verify' else None})
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
        states=self.states if self.view_lab==request['lab'] else {}
        if action in ('start','status'):
            states={n['name']:{'status':(n.get('state') or {}).get('status','invité non vérifié'),'memory':n.get('memory_current_bytes')} for n in data['nodes']}
            self.observation.set(f"{data['name']} · {data['phase']} · état observé à {time.strftime('%H:%M:%S')}")
        elif action=='stop':
            if data.get('stopped')!=request['lab']:raise ValueError('Arrêt non confirmé.')
            states={n['name']:{'status':'stopped'} for n in graph['nodes']};self.observation.set(request['lab']+' · arrêt confirmé')
        self.draw(graph,states);self.show_output(data)
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
