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
from ..layout import fit_dialog
from ..theme import BG,PANEL,CARD,LINE,TEXT,MUTED,TEAL,BLUE,RED
from .catalog import capabilities
from .runtime import plan
from .spec import example,validate
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
        self.buttons=[]
        header=tk.Frame(self.window,bg='#223344',padx=14,pady=7);header.grid(row=0,column=0,sticky='ew')
        self.label(header,'Network LABS','#ffffff',13,True).pack(side='left')
        self.label(header,'Projet LAN natif','#cbd5e1').pack(side='left',padx=18)
        if self.embedded:ttk.Button(header,text='Retour au projet pédagogique',command=self.close).pack(side='left')
        for title,callback in [('Enregistrer',self.save),('Ouvrir',self.open),('Nouveau LAN',self.new)]:
            button=ttk.Button(header,text=title,command=callback,style='Accent.TButton' if title=='Enregistrer' else 'TButton')
            button.pack(side='right',padx=4);self.buttons.append(button)
        toolbar=tk.Frame(self.window,bg=PANEL,padx=12,pady=6);toolbar.grid(row=1,column=0,sticky='ew',pady=(0,6))
        self.label(toolbar,'Réseau réel · projet natif',TEAL,10,True).pack(side='left',padx=(0,18))
        for title,action in [('Démarrer','start'),('Actualiser l’état','status'),('Arrêter','stop')]:
            button=ttk.Button(toolbar,text=title,command=lambda a=action:self.launch(a));button.pack(side='left',padx=3);self.buttons.append(button)
        self.label(toolbar,'Observation sur demande',MUTED,9).pack(side='right')
        body=ttk.Panedwindow(self.window,orient='vertical');body.grid(row=2,column=0,sticky='nsew',padx=6)
        workspace=ttk.Panedwindow(body,orient='horizontal');body.add(workspace,weight=3)
        lower=ttk.Panedwindow(body,orient='horizontal');body.add(lower,weight=1)
        self.dock=ttk.Notebook(lower,height=155);lower.add(self.dock,weight=3)
        self.activity_book=ttk.Notebook(lower,height=155);lower.add(self.activity_book,weight=2)
        activity=ttk.Frame(self.activity_book);self.activity_book.add(activity,text='Événements des opérations')
        self.activity=ttk.Treeview(activity,columns=('time','action','result'),show='headings',height=5)
        for key,title,width in [('time','Heure',75),('action','Opération',85),('result','Résultat observé',280)]:
            self.activity.heading(key,text=title);self.activity.column(key,width=width,minwidth=60)
        self.activity.pack(fill='both',expand=True)
        ttk.Label(activity,text='Opérations natives reçues · aucune capture de paquets en direct',padding=4).pack(fill='x')
        library=tk.Frame(workspace,bg=PANEL,width=185);library.pack_propagate(False);workspace.add(library,weight=0)
        self.label(library,'Bibliothèque',TEXT,10,True).pack(anchor='w',padx=10,pady=10)
        self.search=tk.StringVar();search=ttk.Entry(library,textvariable=self.search);search.pack(fill='x',padx=8,pady=(0,8))
        self.search.trace_add('write',self.filter_library)
        self.library=ttk.Treeview(library,show='tree',selectmode='browse');self.library.pack(fill='both',expand=True,padx=8)
        self.library.bind('<<TreeviewSelect>>',self.library_selected)
        self.label(library,'Équipements déclarés',MUTED,9).pack(padx=8,pady=10)
        self.tabs=ttk.Notebook(workspace);workspace.add(self.tabs,weight=1)
        self.topology_tab=tk.Frame(self.tabs,bg=BG);self.editor_tab=ttk.Frame(self.tabs)
        diagnostics=ttk.Frame(self.tabs);self.output_tab=ttk.Frame(self.dock);self.dock.add(self.output_tab,text='Résultats natifs / inspection')
        for frame,title in ((self.topology_tab,'Topologie'),(self.editor_tab,'Configuration JSON'),(diagnostics,'Dépendances')):
            self.tabs.add(frame,text=title)
        self.topology_tab.columnconfigure(0,weight=1);self.topology_tab.rowconfigure(1,weight=1)
        titlebar=tk.Frame(self.topology_tab,bg=PANEL,padx=12,pady=12);titlebar.grid(row=0,column=0,sticky='ew')
        self.label(titlebar,'TOPOLOGIE',TEXT,10,True).pack(side='left')
        self.observation=tk.StringVar(value='Aucun état runtime observé.')
        tk.Label(titlebar,textvariable=self.observation,bg=PANEL,fg=MUTED,font=('DejaVu Sans',9),anchor='e').pack(side='right')
        diagram=ttk.Frame(self.topology_tab);diagram.grid(row=1,column=0,sticky='nsew')
        diagram.columnconfigure(0,weight=1);diagram.rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(diagram,background=BG,highlightthickness=0)
        self.canvas.grid(row=0,column=0,sticky='nsew');self.canvas.bind('<Configure>',self.resize_graph)
        for orient,row,col in (('vertical',0,1),('horizontal',1,0)):
            scrollbar=ttk.Scrollbar(diagram,orient=orient,command=self.canvas.yview if orient=='vertical' else self.canvas.xview)
            scrollbar.grid(row=row,column=col,sticky='ns' if orient=='vertical' else 'ew')
            self.canvas.configure(**({'yscrollcommand':scrollbar.set} if orient=='vertical' else {'xscrollcommand':scrollbar.set}))
        legend=tk.Frame(self.topology_tab,bg=PANEL,padx=10,pady=8);legend.grid(row=2,column=0,sticky='ew')
        self.label(legend,'● OCI en marche',TEAL,9).pack(side='left',padx=5)
        self.label(legend,'● Non observé / arrêté',MUTED,9).pack(side='left',padx=5)
        self.label(legend,'Traits : liens déclarés',MUTED,9).pack(side='right')
        details=tk.Frame(workspace,bg=PANEL,width=300);details.pack_propagate(False);workspace.add(details,weight=0)
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

    def record_event(self,action,result):
        self.activity.insert('','end',values=(time.strftime('%H:%M:%S'),action,result))
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
        self.output.configure(state='normal');self.output.delete('1.0','end');self.output.insert('1.0',json.dumps(value,ensure_ascii=False,indent=2));self.output.configure(state='disabled')

    def load_spec(self,spec,path=None):
        spec=validate(spec);self.path=Path(path) if path else None
        self.editor.delete('1.0','end');self.editor.insert('1.0',json.dumps(spec,indent=2))
        self.draw(public_topology(spec));self.observation.set('Topologie déclarée · état runtime à actualiser.')

    def draw(self,graph,states=None):
        validate_topology(graph)
        selected=self.nodes.selection();previous=selected[0] if selected else None;destination=self.destination.get()
        self.graph=graph;self.view_lab=graph['name'];self.states=states or {};self.node_shapes={}
        from ..__main__ import App,roundrect
        self.canvas.delete('all');self.nodes.delete(*self.nodes.get_children());self.library.delete(*[n['name'] for n in getattr(self,'library_graph',{}).get('nodes',[]) if self.library.exists(n['name'])]);self.library_graph=graph
        columns=max(3,math.ceil(math.sqrt(len(graph['nodes']))));positions={}
        width=max(650,self.canvas.winfo_width());height=max(400,self.canvas.winfo_height())
        rows=math.ceil(len(graph['nodes'])/columns);spacing=max(195,width/columns)
        for index,node in enumerate(graph['nodes']):positions[node['name']]=(spacing/2+(index%columns)*spacing,max(180,height/2-(rows-1)*85)+(index//columns)*170)
        for a,b in graph['links']:
            x,y=positions[a[0]];xx,yy=positions[b[0]]
            self.canvas.create_line(x,y,xx,yy,fill=MUTED,width=2,tags=('link',))
            for fraction,port in ((.35,a[1]),(.65,b[1])):
                lx=x+(xx-x)*fraction;ly=y+(yy-y)*fraction
                self.canvas.create_rectangle(lx-22,ly-27,lx+22,ly-9,fill=PANEL,outline=LINE)
                self.canvas.create_text(lx,ly-18,text=port,fill=MUTED,font=('DejaVu Sans',8))
        for node in graph['nodes']:
            name=node['name'];x,y=positions[name];observed=self.states.get(name,{})
            state=observed.get('status','non observé');memory=observed.get('memory')
            color=TEAL if state=='running' else MUTED;tags=('node','node:'+name)
            roundrect(self.canvas,x-69,y-48,x+73,y+52,r=9,fill='#dce4ef',outline='',tags=tags)
            self.node_shapes[name]=roundrect(self.canvas,x-72,y-51,x+70,y+49,r=9,fill=CARD,outline=LINE,width=1,tags=tags)
            kind={'host':'PC','switch':'Switch','router':'Router','firewall':'Firewall'}.get(node['role'],'Serveur')
            App.icon(self,kind,x,y-12,1,TEAL if kind=='Switch' else BLUE,tags)
            self.canvas.create_text(x,y+31,text=name,fill=TEXT,font=('DejaVu Sans',10,'bold'),tags=tags)
            self.canvas.create_oval(x+54,y-41,x+60,y-35,fill=color,outline='',tags=tags)
            self.canvas.create_text(x,y+66,text=node['role']+' · '+node['runtime'],fill=MUTED,font=('DejaVu Sans',9),tags=tags)
            self.canvas.tag_bind('node:'+name,'<Button-1>',lambda event,n=name:self.choose_node(n))
            self.nodes.insert('','end',iid=name,text=name,values=(node['runtime'],state,'—' if memory is None else f'{memory/1048576:.1f} MiB'))
            self.library.insert('','end',iid=name,text=name+' · '+node['role'])
        self.filter_library()
        self.counts.set(f"{len(graph['nodes'])} équipements  /  {len(graph['links'])} liens  /  {graph['name']}")
        self.canvas.configure(scrollregion=(0,0,max(width,columns*spacing),max(height,rows*170+180)))
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
            for key,shape in self.node_shapes.items():self.canvas.itemconfigure(shape,outline=BLUE if key==name else LINE,width=2 if key==name else 1)
        self.inspect_button.state(['!disabled'] if node and node['runtime']=='oci' and not self.pending else ['disabled'])
        self.verify_button.state(['!disabled'] if node and node['runtime']=='oci' and node['role']=='host' and not self.pending else ['disabled'])

    def new(self):
        rootfs=filedialog.askdirectory(parent=self.window,title='Rootfs BusyBox natif')
        if not rootfs:return
        name=simpledialog.askstring('Nouveau LAN','Nom du lab :',initialvalue='micro-lan',parent=self.window)
        if not name:return
        try:spec=example(rootfs);spec['name']=name;self.load_spec(spec);self.tabs.select(self.topology_tab)
        except (ValueError,TypeError,KeyError) as error:self.error(error)

    def preview(self):
        try:spec=self.manifest();report=plan(spec)
        except (ValueError,TypeError,KeyError) as error:self.error(error);return False
        self.draw(public_topology(spec));self.observation.set('Topologie déclarée · état runtime à actualiser.')
        self.show_output(report);self.dock.select(self.output_tab);return True

    def open(self):
        path=filedialog.askopenfilename(parent=self.window,filetypes=[('Native lab JSON','*.json')])
        if path:
            try:self.load_spec(json.loads(Path(path).read_text()),path);self.tabs.select(self.topology_tab)
            except (OSError,ValueError,TypeError,KeyError) as error:self.error(error)

    def save(self):
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
