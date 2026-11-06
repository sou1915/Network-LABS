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
from .workspace_art import draw_device,access_vlans,place_nodes,networks
from .ui_bridge import SOURCE,client_args,private_json,public_topology,read_result,validate_request,validate_topology


def launch_terminal(command):
    terminal=shutil.which('x-terminal-emulator') or shutil.which('xterm')
    if not terminal or not shutil.which('sudo'):
        raise ValueError('Installer un terminal x-terminal-emulator/xterm et sudo pour le contrôle natif.')
    return subprocess.Popen([terminal,'-e',*command],cwd=SOURCE)


class ApplianceWindow:
    def __init__(self,app,*,embedded=False):
        self.app=app;self.path=None;self.pending=None;self.poll_id=None;self.closed=False;self.last_response=None
        # Use the established desktop's theme and device artwork. Native state
        # stays separate from the pedagogical Session/model behind that desktop.
        from ..__main__ import App
        self.root=app.root;self.embedded=embedded;self.previous_widgets=[]
        App.style(self)
        style=ttk.Style(self.root)
        style.configure('Native.TButton',padding=(8,5),font=('DejaVu Sans',9),background='#f5f7fa',borderwidth=0)
        style.map('Native.TButton',background=[('active','#e5edf7')])
        style.configure('Native.TNotebook',background='#f1f4f8',borderwidth=0)
        style.configure('Native.TNotebook.Tab',padding=(10,5),font=('DejaVu Sans',9))
        style.map('Native.TNotebook.Tab',background=[('selected','#ffffff')],foreground=[('selected',BLUE)])
        style.configure('Native.Treeview',rowheight=23,font=('DejaVu Sans',9))
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
        self.window.columnconfigure(0,weight=1);self.window.rowconfigure(2,weight=1)
        self.config_key=None;self.config_baseline=None;self.positions={};self.edit_mode=None;self.cable_source=None;self.dragging=None
        self.buttons=[]
        header=tk.Frame(self.window,bg='#223344',padx=8,pady=4);header.grid(row=0,column=0,sticky='ew')
        self.label(header,'◉  Network LABS','#ffffff',10,True).pack(side='left')
        self.project_title=tk.StringVar(value='Projet LAN')
        tk.Label(header,textvariable=self.project_title,bg='#223344',fg='#d6e2ee',font=('DejaVu Sans',9)).pack(side='left',padx=18)
        for title,commands in [('Fichier',[('Nouveau LAN',self.new),('Ouvrir',self.open),('Enregistrer',self.save)]),
                               ('Édition',[('Ajouter un équipement',self.add_device_dialog),('Connecter un câble',lambda:self.set_edit_mode('cable')),('Supprimer',self.delete_selected)]),
                               ('Affichage',[('Topologie',lambda:self.tabs.select(self.topology_tab)),('Configuration du projet',lambda:self.tabs.select(self.editor_tab)),('Configuration du dispositif',lambda:self.device_tabs.select(self.config_panel))]),
                               ('Outils',[('Valider / plan',self.preview),('Actualiser l’état',lambda:self.launch('status'))])]:
            menu_button=tk.Menubutton(header,text=title,bg='#223344',fg='white',activebackground='#334b60',activeforeground='white',font=('DejaVu Sans',9),padx=9)
            menu=tk.Menu(menu_button,tearoff=False)
            for label,callback in commands:menu.add_command(label=label,command=callback)
            menu_button.configure(menu=menu);menu_button.pack(side='left')
        if self.embedded:ttk.Button(header,text='Retour au projet pédagogique',command=self.close,style='Native.TButton').pack(side='right')
        toolbar=tk.Frame(self.window,bg='#f5f7fa',padx=8,pady=4);toolbar.grid(row=1,column=0,sticky='ew',pady=(0,2))
        for title,callback in [('↖ Sélection',lambda:self.set_edit_mode(None)),('+ Ajouter un équipement',self.add_device_dialog),('⌁ Connecter un câble',lambda:self.set_edit_mode('cable')),('Supprimer',self.delete_selected)]:
            button=ttk.Button(toolbar,text=title,command=callback,style='Native.TButton');button.pack(side='left',padx=2);self.buttons.append(button)
        for title,action in [('▶ Démarrer','start'),('↻ État','status'),('■ Arrêter','stop')]:
            button=ttk.Button(toolbar,text=title,command=lambda a=action:self.launch(a),style='Native.TButton');button.pack(side='left',padx=3);self.buttons.append(button)
        button=ttk.Button(toolbar,text='▣ Enregistrer',command=self.save,style='Native.TButton');button.pack(side='left',padx=3);self.buttons.append(button)

        body=ttk.Panedwindow(self.window,orient='vertical');body.grid(row=2,column=0,sticky='nsew',padx=6)
        workspace=ttk.Panedwindow(body,orient='horizontal');body.add(workspace,weight=3)
        lower=ttk.Panedwindow(body,orient='horizontal');body.add(lower,weight=1)
        self.dock=ttk.Notebook(lower,height=155,style='Native.TNotebook');lower.add(self.dock,weight=3)
        self.activity_book=ttk.Notebook(lower,height=155,style='Native.TNotebook');lower.add(self.activity_book,weight=2)
        activity=ttk.Frame(self.activity_book);self.activity_book.add(activity,text='Événements natifs')
        self.activity=ttk.Treeview(activity,columns=('time','action','result'),show='headings',height=5,style='Native.Treeview')
        for key,title,width in [('time','Heure',75),('action','Opération',85),('result','Résultat observé',280)]:
            self.activity.heading(key,text=title);self.activity.column(key,width=width,minwidth=60)
        self.activity.tag_configure('failed',foreground=RED);self.activity.tag_configure('passed',foreground=TEAL)
        self.activity.pack(fill='both',expand=True)
        ttk.Label(activity,text='Opérations natives reçues · aucune capture de paquets en direct',padding=4).pack(fill='x')
        library=tk.Frame(workspace,bg=PANEL,width=185);library.pack_propagate(False);workspace.add(library,weight=0)
        self.label(library,'Bibliothèque',TEXT,10,True).pack(anchor='w',padx=10,pady=10)
        self.search=tk.StringVar();search=ttk.Entry(library,textvariable=self.search);search.pack(fill='x',padx=8,pady=(0,8))
        self.search.trace_add('write',self.filter_library)
        self.build_library_palette(library)
        self.library=ttk.Treeview(library,show='tree',selectmode='browse',height=4,style='Native.Treeview');self.library.pack(fill='both',expand=True,padx=8)
        self.library.bind('<<TreeviewSelect>>',self.library_selected)
        self.label(library,'Équipements déclarés',MUTED,9).pack(padx=8,pady=10)
        self.tabs=ttk.Notebook(workspace,style='Native.TNotebook');workspace.add(self.tabs,weight=1)
        self.topology_tab=tk.Frame(self.tabs,bg=BG);self.editor_tab=ttk.Frame(self.tabs)
        diagnostics=ttk.Frame(self.tabs);self.output_tab=ttk.Frame(self.dock);self.dock.add(self.output_tab,text='Diagnostic réseau · lecture seule')
        self.raw_tab=ttk.Frame(self.dock);self.dock.add(self.raw_tab,text='Détails JSON')
        for frame,title in ((self.topology_tab,'Topologie'),(self.editor_tab,'Équipements / JSON'),(diagnostics,'Outils')):
            self.tabs.add(frame,text=title)
        self.topology_tab.columnconfigure(0,weight=1);self.topology_tab.rowconfigure(1,weight=1)
        titlebar=tk.Frame(self.topology_tab,bg=PANEL,padx=10,pady=6);titlebar.grid(row=0,column=0,sticky='ew')
        self.label(titlebar,'Espace réseau',TEXT,9,True).pack(side='left')
        self.observation=tk.StringVar(value='Aucun état runtime observé.')
        tk.Label(titlebar,textvariable=self.observation,bg=PANEL,fg=MUTED,font=('DejaVu Sans',8),anchor='e').pack(side='right')
        diagram=ttk.Frame(self.topology_tab);diagram.grid(row=1,column=0,sticky='nsew')
        diagram.columnconfigure(0,weight=1);diagram.rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(diagram,background='#fcfdff',highlightthickness=0)
        self.canvas.grid(row=0,column=0,sticky='nsew');self.canvas.bind('<Configure>',self.resize_graph)
        self.canvas.bind('<B1-Motion>',self.drag_node);self.canvas.bind('<ButtonRelease-1>',self.drop_node)
        self.canvas.bind('<Escape>',lambda event:self.set_edit_mode(None))
        for orient,row,col in (('vertical',0,1),('horizontal',1,0)):
            scrollbar=ttk.Scrollbar(diagram,orient=orient,command=self.canvas.yview if orient=='vertical' else self.canvas.xview)
            scrollbar.grid(row=row,column=col,sticky='ns' if orient=='vertical' else 'ew')
            self.canvas.configure(**({'yscrollcommand':scrollbar.set} if orient=='vertical' else {'xscrollcommand':scrollbar.set}))
        legend=tk.Frame(self.topology_tab,bg=PANEL,padx=10,pady=8);legend.grid(row=2,column=0,sticky='ew')
        self.label(legend,'● OCI en marche',TEAL,9).pack(side='left',padx=5)
        self.label(legend,'● Non observé / arrêté',MUTED,9).pack(side='left',padx=5)
        self.label(legend,'VLAN / adresses : configuration',MUTED,8).pack(side='right')
        device=tk.Frame(workspace,bg=PANEL,width=300);device.pack_propagate(False);workspace.add(device,weight=0)
        self.device_tabs=ttk.Notebook(device,style='Native.TNotebook');self.device_tabs.pack(fill='both',expand=True)
        details=tk.Frame(self.device_tabs,bg=PANEL);self.device_tabs.add(details,text='État / test')
        self.config_panel=ScrollPanel(self.device_tabs,PANEL);self.device_tabs.add(self.config_panel,text='Configuration')
        self.build_config_form(self.config_panel.inner)
        self.label(details,'Équipement · réseau natif',TEXT,11,True).pack(anchor='w',padx=14,pady=8)
        self.selected_title=tk.StringVar();self.selected_details=tk.StringVar()
        tk.Label(details,textvariable=self.selected_title,bg=PANEL,fg=TEXT,font=('DejaVu Sans',13,'bold'),anchor='w').pack(fill='x',padx=14)
        tk.Label(details,textvariable=self.selected_details,bg=PANEL,fg=MUTED,justify='left',anchor='w',wraplength=265).pack(fill='x',padx=14,pady=4)
        self.nodes=ttk.Treeview(details,columns=('runtime','state','memory'),displaycolumns=('state','memory'),show='tree headings',height=3,selectmode='browse')
        for key,label,width in (('#0','Nœud',65),('runtime','Runtime',65),('state','État OCI',115),('memory','RAM',70)):
            self.nodes.heading(key,text=label);self.nodes.column(key,width=width,minwidth=45,stretch=True)
        self.nodes.pack(fill='x',padx=8);self.nodes.bind('<<TreeviewSelect>>',self.select_node)
        controls=tk.Frame(details,bg=PANEL,padx=12,pady=6);controls.pack(fill='x')
        self.inspect_button=ttk.Button(controls,text='Inspecter le réseau',command=lambda:self.launch('inspect'));self.inspect_button.pack(fill='x')
        self.label(controls,'TEST DE CONNECTIVITÉ',MUTED,9,True).pack(anchor='w',pady=(8,4))
        self.destination=tk.StringVar();self.targets=ttk.Combobox(controls,textvariable=self.destination,state='readonly');self.targets.pack(fill='x',pady=4)
        self.verify_button=ttk.Button(controls,text='Tester la liaison',command=lambda:self.launch('verify'));self.verify_button.pack(fill='x',pady=4)
        self.note=tk.StringVar(value='Ouvrir un projet natif ou créer un LAN pour commencer.')
        tk.Label(details,textvariable=self.note,bg=PANEL,fg=TEAL,justify='left',anchor='nw',wraplength=265).pack(fill='x',padx=14,pady=4)
        self.label(details,'Vert = processus OCI observé.\nTester pour vérifier la connectivité.',MUTED,9).pack(side='bottom',padx=12,pady=6)
        self.editor=self.text_area(self.editor_tab);self.output=self.text_area(self.output_tab);self.output.configure(state='disabled',background='#0d131b',foreground='#dce6f0',insertbackground='white')
        self.raw_output=self.text_area(self.raw_tab);self.raw_output.configure(state='disabled')
        validate_button=ttk.Button(self.editor_tab,text='Valider / plan',command=self.preview);validate_button.grid(row=2,column=0,sticky='e',pady=4);self.buttons.append(validate_button)
        self.table=ttk.Treeview(diagnostics,columns=('runtime','implementation','detected','scope'),show='headings')
        for key,title,width in [('runtime','Runtime',100),('implementation','Implémentation',100),('detected','Détecté',80),('scope','Périmètre',360)]:
            self.table.heading(key,text=title);self.table.column(key,width=width)
        self.table.pack(fill='both',expand=True)
        ttk.Button(diagnostics,text='Actualiser les dépendances',command=self.refresh).pack(anchor='w',padx=8,pady=6)
        footer=tk.Frame(self.window,bg=PANEL,padx=14,pady=7);footer.grid(row=3,column=0,sticky='ew',pady=(6,0))
        self.counts=tk.StringVar();self.label(footer,'Sélection · état natif observé sur demande',MUTED,9).pack(side='left')
        tk.Label(footer,textvariable=self.counts,bg=PANEL,fg=TEAL,font=('DejaVu Sans',9)).pack(side='right')
        self.window.bind('<Destroy>',self.destroyed,add='+')
        self.load_spec(example(Path.home()/'network-labs-rootfs'));self.refresh()

    @staticmethod
    def label(parent,text,color=TEXT,size=10,bold=False):
        return tk.Label(parent,text=text,bg=parent.cget('bg'),fg=color,justify='left',font=('DejaVu Sans',size,'bold' if bold else 'normal'))

    def build_library_palette(self,parent):
        for role,category,title in [('router','Routeurs','Routeur Linux'),('switch','Switches','Switch Linux'),('host','Postes clients','Poste Linux')]:
            self.label(parent,category,TEXT,8,True).pack(anchor='w',padx=10,pady=(5,2))
            tile=tk.Frame(parent,bg='#f2f5f9',cursor='hand2');tile.pack(fill='x',padx=7,pady=(0,2))
            icon=tk.Canvas(tile,width=67,height=43,bg='#f2f5f9',highlightthickness=0);icon.pack(side='left')
            draw_device(icon,role,33,22,scale=.52)
            caption=tk.Frame(tile,bg='#f2f5f9');caption.pack(side='left',fill='x')
            self.label(caption,title,TEXT,8).pack(anchor='w')
            self.label(caption,'OCI · ajouter',MUTED,7).pack(anchor='w')
            def bind(widget,r=role):
                widget.bind('<Button-1>',lambda event:self.add_device_dialog(r))
                for child in widget.winfo_children():bind(child,r)
            bind(tile)
        self.label(parent,'Dans ce projet',MUTED,8,True).pack(anchor='w',padx=10,pady=(9,3))

    def record_event(self,action,result):
        tag='failed' if 'failed' in result or 'blocked' in result else 'passed' if 'passed' in result else ''
        self.activity.insert('','end',values=(time.strftime('%H:%M:%S'),action,result),tags=(tag,))
        children=self.activity.get_children()
        if len(children)>200:self.activity.delete(*children[:-200])
        self.activity.see(self.activity.get_children()[-1])

    def filter_library(self,*args):
        if not hasattr(self,'graph'):return
        query=self.search.get().strip().casefold()
        for node in self.graph['nodes']:
            name=node['name']
            if not query or query in (name+' '+node['role']+' '+node['runtime']).casefold():self.library.reattach(name,'','end')
            else:self.library.detach(name)

    def library_selected(self,event=None):
        selected=self.library.selection()
        if selected and self.nodes.selection()!=selected:self.choose_node(selected[0])

    def resize_graph(self,event=None):
        if hasattr(self,'graph'):self.draw(self.graph,self.states)

    def text_area(self,parent):
        parent.rowconfigure(0,weight=1);parent.columnconfigure(0,weight=1)
        text=tk.Text(parent,wrap='none',font=('DejaVu Sans Mono',10),undo=True)
        vertical=ttk.Scrollbar(parent,command=text.yview);horizontal=ttk.Scrollbar(parent,orient='horizontal',command=text.xview)
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
        if isinstance(value,dict) and isinstance(value.get('directions'),list):
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
        self.config_key=None;self.positions={};self.draw(public_topology(spec));self.observation.set('Topologie déclarée · état runtime à actualiser.')

    def draw(self,graph,states=None):
        validate_topology(graph)
        selected=self.nodes.selection();previous=selected[0] if selected else None;destination=self.destination.get()
        self.graph=graph;self.view_lab=graph['name'];self.states=states or {};self.node_shapes={}
        from ..__main__ import App,roundrect
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
        for xx in range(12,int(width),22):
            for yy in range(12,int(height),22):self.canvas.create_oval(xx,yy,xx+1,yy+1,fill='#e8eef5',outline='',tags=('grid',))
        palette=[('#eff7ff','#abc9ed','#2865a8'),('#f0faf3','#b2dabc','#2c7545'),('#fff9e9','#e8d89c','#996c15')]
        self.vlan_members=members;captions=[]
        for index,vid in enumerate(sorted(set(members.values()))):
            names=[n for n in members if members[n]==vid];points=[positions[n] for n in names]
            x1=min(x for x,y in points)-77;x2=max(x for x,y in points)+77
            y1=min(y for x,y in points)-76;y2=max(y for x,y in points)+80
            bg,border,ink=palette[index%len(palette)]
            roundrect(self.canvas,x1,y1,x2,y2,r=10,fill=bg,outline=border,dash=(3,2),tags=('vlan-group',))
            captions.append((x1,y1,x2,bg,ink,vid,networks(graph,names,spec,vid)))
        for index,(a,b) in enumerate(graph['links']):
            x,y=positions[a[0]];xx,yy=positions[b[0]]
            if abs(y-yy)<5:
                sign=1 if xx>x else -1;ax=x+sign*55;ay=y;bx=xx-sign*55;by=yy;points=(ax,ay,bx,by)
            else:
                sign=1 if yy>y else -1;ax=x;ay=y+sign*25;bx=xx;by=yy-sign*25
                graph_nodes={n['name']:n for n in graph['nodes']}
                if graph_nodes[a[0]]['role']!='host':ax+=(int(a[1][3:])%8-3.5)*7
                if graph_nodes[b[0]]['role']!='host':bx+=(int(b[1][3:])%8-3.5)*7
                mid=min(ay,by)+19+(index%4)*10
                points=(ax,ay,ax,mid,bx,mid,bx,by)
            self.canvas.create_line(*points,fill='#5180ae',width=1.5,tags=('link','link:'+str(index)))
            self.canvas.tag_bind('link:'+str(index),'<Button-3>',lambda event,aa=a,bb=b:self.remove_cable(aa,bb))
            for px,py,port in ((ax,ay,a[1]),(bx,by,b[1])):
                self.canvas.create_oval(px-2,py-2,px+2,py+2,fill='#4f83b3',outline='')
                self.canvas.create_text(px+6,py-8,text=port,fill=MUTED,font=('DejaVu Sans',7),anchor='w')
            policies=[config.get(end[0],{}).get('switchports',{}).get(end[1],{}) for end in (a,b)]
            if all(p.get('mode')=='trunk' for p in policies):
                lx=(ax+bx)/2;ly=(ay+by)/2-11
                self.canvas.create_rectangle(lx-48,ly-9,lx+48,ly+9,fill='white',outline='#d9e4ef')
                self.canvas.create_text(lx,ly,text='Trunk · 802.1Q',fill='#3a6085',font=('DejaVu Sans',8))
        for x1,y1,x2,bg,ink,vid,subnets in captions:
            self.canvas.create_rectangle(x1+3,y1+3,x2-3,y1+41,fill=bg,outline='')
            self.canvas.create_text((x1+x2)/2,y1+14,text=f'VLAN {vid}',fill=ink,font=('DejaVu Sans',9,'bold'),tags=('vlan-label',))
            self.canvas.create_text((x1+x2)/2,y1+30,text=subnets,fill=MUTED,font=('DejaVu Sans',8))
        for node in graph['nodes']:
            name=node['name'];x,y=positions[name];observed=self.states.get(name,{})
            state=observed.get('status','non observé');memory=observed.get('memory')
            color=TEAL if state=='running' else MUTED;tags=('node','node:'+name)
            self.node_shapes[name]=self.canvas.create_rectangle(x-64,y-34 if node['role']=='host' else y-43,x+64,y+66 if node['role']=='host' else y+43,fill='',outline='',width=1,tags=tags)
            draw_device(self.canvas,node['role'],x,y,tags=tags)
            if node['role']=='host':
                self.canvas.create_text(x,y+42,text=name,fill=TEXT,font=('DejaVu Sans',9,'bold'),tags=tags)
                ips=[v.split('/')[0] for v in node['interfaces'].values() if v]
                self.canvas.create_text(x,y+57,text=', '.join(ips) or 'Linux · OCI',fill=MUTED,font=('DejaVu Sans',8),tags=tags)
            else:
                self.canvas.create_text(x,y-48,text=name,fill=TEXT,font=('DejaVu Sans',9,'bold'),tags=tags)
                self.canvas.create_text(x,y-34,text={'switch':'Switch Linux','router':'Routeur Linux','firewall':'Pare-feu Linux'}.get(node['role'],'Linux'),fill=MUTED,font=('DejaVu Sans',8),tags=tags)
            self.canvas.create_oval(x+53,y+16,x+60,y+23,fill=color,outline='#ffffff',tags=tags)
            self.canvas.tag_bind('node:'+name,'<Button-1>',lambda event,n=name:self.node_pressed(event,n))
            self.nodes.insert('','end',iid=name,text=name,values=(node['runtime'],state,'—' if memory is None else f'{memory/1048576:.1f} MiB'))
            self.library.insert('','end',iid=name,text=name)
        self.filter_library();self.project_title.set(graph['name'])
        self.counts.set(f"{len(graph['nodes'])} équipements  /  {len(graph['links'])} liens  /  {graph['name']}")
        self.canvas.configure(scrollregion=(0,0,max(width,max(x for x,y in positions.values())+90),max(height,max(y for x,y in positions.values())+90)))
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

    def build_config_form(self,parent):
        self.label(parent,'Configuration du projet',TEXT,11,True).pack(anchor='w',padx=10,pady=(12,4))
        self.label(parent,'Brouillon · appliquer après arrêt / démarrage',MUTED,8).pack(anchor='w',padx=10,pady=(0,8))
        self.config_vars={key:tk.StringVar() for key in ('name','port','address','gateway')};self.config_fields={}
        for key,title in [('name','Nom de l’équipement'),('port','Interface physique'),('address','IPv4 / CIDR (vide = aucune)'),('gateway','Passerelle IPv4 (vide = aucune)')]:
            self.label(parent,title,MUTED,9).pack(anchor='w',padx=10,pady=(6,3))
            field=ttk.Combobox(parent,textvariable=self.config_vars[key],state='readonly') if key=='port' else ttk.Entry(parent,textvariable=self.config_vars[key])
            field.pack(fill='x',padx=10);self.config_fields[key]=field
        self.config_fields['port'].bind('<<ComboboxSelected>>',self.config_port_selected)
        self.config_enabled=tk.BooleanVar(value=True)
        self.config_admin=ttk.Checkbutton(parent,text='Interface activée',variable=self.config_enabled);self.config_admin.pack(anchor='w',padx=10,pady=8)
        self.config_apply=ttk.Button(parent,text='Appliquer au brouillon',command=self.apply_config);self.config_apply.pack(fill='x',padx=10,pady=3)
        ttk.Button(parent,text='Recharger le formulaire',command=lambda:self.load_config(force=True)).pack(fill='x',padx=10,pady=3)
        self.config_message=tk.StringVar()
        tk.Label(parent,textvariable=self.config_message,bg=PANEL,fg=MUTED,justify='left',wraplength=255,anchor='w').pack(fill='x',padx=10,pady=8)

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
        self.edit_mode=mode;self.cable_source=None;self.dragging=None
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
        self.choose_node(name);self.canvas.focus_set()
        if self.pending:return
        if self.edit_mode=='cable':
            if self.cable_source is None:self.cable_source=name;self.note.set('Choisir le deuxième équipement après '+name+'.')
            elif self.cable_source!=name:
                first=self.cable_source;self.cable_source=None;self.connect_dialog(first,name)
            return
        self.dragging=(name,self.canvas.canvasx(event.x),self.canvas.canvasy(event.y))

    def drag_node(self,event):
        if self.pending or not self.dragging:return
        name,x,y=self.dragging;xx=self.canvas.canvasx(event.x);yy=self.canvas.canvasy(event.y)
        self.canvas.move('node:'+name,xx-x,yy-y);self.dragging=(name,xx,yy)

    def drop_node(self,event):
        if not self.dragging:return
        name,_,_=self.dragging;self.dragging=None
        box=self.canvas.coords(self.node_shapes[name])
        offset=16 if next(n for n in self.graph['nodes'] if n['name']==name)['role']=='host' else 0
        self.positions[name]=(max(85,(min(box[::2])+max(box[::2]))/2),max(70,(min(box[1::2])+max(box[1::2]))/2-offset))
        self.draw(self.graph,self.states)

    def add_device_dialog(self,role='host'):
        try:spec=self.editing_spec()
        except (ValueError,TypeError,KeyError) as error:self.error(error);return
        win=tk.Toplevel(self.window);win.title('Ajouter un équipement Linux natif');win.transient(self.window.winfo_toplevel())
        form=ttk.Frame(win,padding=14);form.pack(fill='both',expand=True)
        values={}
        rootfs=next((n['rootfs'] for n in spec['nodes'] if n['runtime']=='oci'),'')
        prefix={'host':'PC','switch':'SW','router':'R'}[role];used={n['name'] for n in spec['nodes']}
        suggested=next(prefix+str(i) for i in range(1,258) if prefix+str(i) not in used)
        for row,(key,title,initial) in enumerate([('name','Nom',suggested),('role','Rôle',role),('rootfs','Rootfs Linux',rootfs),('ports','Nombre de ports',{'host':'1','switch':'8','router':'3'}[role]),('address','IPv4 eth0 / CIDR (facultatif)','')]):
            ttk.Label(form,text=title).grid(row=row,column=0,sticky='w',pady=5)
            value=tk.StringVar(value=initial);values[key]=value
            field=ttk.Combobox(form,textvariable=value,values=('host','switch','router'),state='readonly') if key=='role' else ttk.Entry(form,textvariable=value,width=38)
            field.grid(row=row,column=1,sticky='ew',padx=8)
        def browse():
            path=filedialog.askdirectory(parent=win,title='Rootfs Linux')
            if path:values['rootfs'].set(path)
        ttk.Button(form,text='Parcourir…',command=browse).grid(row=2,column=2)
        ttk.Label(form,text='OCI / Linux générique. Aucun firmware constructeur.').grid(row=5,column=0,columnspan=3,pady=8)
        def apply():
            try:
                current=self.editing_spec()
                result=topology_edit.add_node(current,**{k:v.get().strip() for k,v in values.items() if k!='ports'},ports=int(values['ports'].get()))
                self.commit_edit(result);self.choose_node(values['name'].get().strip());win.destroy()
            except (ValueError,TypeError,KeyError) as error:self.error(error)
        ttk.Button(form,text='Ajouter au brouillon',command=apply).grid(row=6,column=1,sticky='e')
        ttk.Button(form,text='Annuler',command=win.destroy).grid(row=6,column=0)

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
            ttk.Combobox(form,textvariable=var,values=available,state='readonly').grid(row=row,column=1,padx=8)
        def apply():
            try:
                draft=self.editing_spec()
                for name,port in additions.items():draft=topology_edit.add_port(draft,name,port)
                self.commit_edit(topology_edit.connect(draft,(first,ports[0].get()),(second,ports[1].get())));win.destroy()
            except (ValueError,TypeError,KeyError) as error:self.error(error)
        ttk.Button(form,text='Connecter au brouillon',command=apply).grid(row=2,column=1,pady=8)
        ttk.Button(form,text='Annuler',command=win.destroy).grid(row=2,column=0)

    def delete_selected(self):
        selected=self.nodes.selection()
        if not selected:return
        try:self.commit_edit(topology_edit.remove_node(self.editing_spec(),selected[0]))
        except (ValueError,TypeError,KeyError) as error:self.error(error)

    def remove_cable(self,a,b):
        try:self.commit_edit(topology_edit.disconnect(self.editing_spec(),a,b))
        except (ValueError,TypeError,KeyError) as error:self.error(error)

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
        self.poll_id=None
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
            if self.poll_id:
                try:self.window.after_cancel(self.poll_id)
                except tk.TclError:pass
            if self.pending:self.pending['directory'].cleanup();self.pending=None
            if self.embedded and self.root.winfo_exists():
                self.root.bind('<Control-s>',self.previous_save)
                for widget,options in self.previous_widgets:
                    if widget.winfo_exists():widget.pack(**options)

    def close(self):self.window.destroy()
