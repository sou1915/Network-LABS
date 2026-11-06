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
    def __init__(self,app):
        self.app=app;self.path=None;self.pending=None;self.poll_id=None;self.closed=False;self.last_response=None
        self.window=tk.Toplevel(app.root);self.window.title('Network LABS · LAN natif')
        self.window.geometry('1080x740');fit_dialog(self.window,1080,740)
        self.window.columnconfigure(0,weight=1);self.window.rowconfigure(1,weight=1)
        self.note=tk.StringVar(value='Ouvrir un projet natif ou créer un LAN pour commencer.')
        ttk.Label(self.window,textvariable=self.note,padding=10,wraplength=1000).grid(row=0,column=0,sticky='ew')
        self.tabs=ttk.Notebook(self.window);self.tabs.grid(row=1,column=0,sticky='nsew',padx=10)
        self.topology_tab=ttk.Frame(self.tabs);self.editor_tab=ttk.Frame(self.tabs)
        diagnostics=ttk.Frame(self.tabs);self.output_tab=ttk.Frame(self.tabs)
        for frame,title in ((self.topology_tab,'Topologie native'),(self.editor_tab,'Configuration JSON'),(diagnostics,'Dépendances'),(self.output_tab,'Observations / plan')):
            self.tabs.add(frame,text=title)
        self.topology_tab.columnconfigure(0,weight=1);self.topology_tab.rowconfigure(1,weight=1)
        self.observation=tk.StringVar(value='Aucun état runtime observé.')
        ttk.Label(self.topology_tab,textvariable=self.observation,padding=8).grid(row=0,column=0,sticky='ew')
        split=ttk.Panedwindow(self.topology_tab,orient='horizontal');split.grid(row=1,column=0,sticky='nsew')
        diagram=ttk.Frame(split);details=ttk.Frame(split);split.add(diagram,weight=3);split.add(details,weight=2)
        diagram.columnconfigure(0,weight=1);diagram.rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(diagram,background='#f1f5f9',highlightthickness=0)
        self.canvas.grid(row=0,column=0,sticky='nsew')
        for orient,row,col in (('vertical',0,1),('horizontal',1,0)):
            scrollbar=ttk.Scrollbar(diagram,orient=orient,command=self.canvas.yview if orient=='vertical' else self.canvas.xview)
            scrollbar.grid(row=row,column=col,sticky='ns' if orient=='vertical' else 'ew')
            self.canvas.configure(**({'yscrollcommand':scrollbar.set} if orient=='vertical' else {'xscrollcommand':scrollbar.set}))
        self.nodes=ttk.Treeview(details,columns=('runtime','state','memory'),show='tree headings',height=11,selectmode='browse')
        for key,label,width in (('#0','Nœud',85),('runtime','Runtime',75),('state','Dernier état',120),('memory','RAM OCI',75)):
            self.nodes.heading(key,text=label);self.nodes.column(key,width=width,minwidth=50)
        self.nodes.pack(fill='both',expand=True);self.nodes.bind('<<TreeviewSelect>>',self.select_node)
        controls=ttk.Frame(details,padding=6);controls.pack(fill='x')
        self.inspect_button=ttk.Button(controls,text='Inspecter',command=lambda:self.launch('inspect'));self.inspect_button.pack(side='left')
        self.destination=tk.StringVar();self.targets=ttk.Combobox(controls,textvariable=self.destination,state='readonly',width=12);self.targets.pack(side='left',padx=4)
        self.verify_button=ttk.Button(controls,text='Tester liaison',command=lambda:self.launch('verify'));self.verify_button.pack(side='left')
        ttk.Label(details,text='Liens déclarés ; vert = processus OCI observé en marche.\nLe test de liaison utilise le réseau réel.',wraplength=360,padding=8).pack(fill='x')
        self.editor=self.text_area(self.editor_tab);self.output=self.text_area(self.output_tab);self.output.configure(state='disabled')
        self.table=ttk.Treeview(diagnostics,columns=('runtime','implementation','detected','scope'),show='headings')
        for key,title,width in [('runtime','Runtime',110),('implementation','Implémentation',110),('detected','Détecté',90),('scope','Périmètre',600)]:
            self.table.heading(key,text=title);self.table.column(key,width=width)
        self.table.pack(fill='both',expand=True)
        ttk.Button(diagnostics,text='Actualiser les dépendances',command=self.refresh).pack(anchor='w',padx=8,pady=6)
        bar=ttk.Frame(self.window,padding=8);bar.grid(row=2,column=0,sticky='ew');self.buttons=[]
        for title,callback in [('Nouveau LAN',self.new),('Ouvrir',self.open),('Enregistrer',self.save),('Valider / plan',self.preview),
                               ('Démarrer',lambda:self.launch('start')),('Actualiser l’état',lambda:self.launch('status')),('Arrêter',lambda:self.launch('stop'))]:
            button=ttk.Button(bar,text=title,command=callback);button.pack(side='left',padx=3);self.buttons.append(button)
        ttk.Label(self.window,text='sudo uniquement dans le terminal ; la GUI reste sans privilèges. Fermer cette fenêtre ne stoppe pas un lab.',padding=8,wraplength=1000).grid(row=3,column=0,sticky='ew')
        self.window.protocol('WM_DELETE_WINDOW',self.close);self.window.bind('<Destroy>',self.destroyed,add='+')
        self.load_spec(example(Path.home()/'network-labs-rootfs'));self.refresh()

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
        self.canvas.delete('all');self.nodes.delete(*self.nodes.get_children())
        columns=max(3,math.ceil(math.sqrt(len(graph['nodes']))));positions={}
        for index,node in enumerate(graph['nodes']):positions[node['name']]=(110+(index%columns)*190,80+(index//columns)*125)
        for a,b in graph['links']:
            x,y=positions[a[0]];xx,yy=positions[b[0]]
            self.canvas.create_line(x,y,xx,yy,fill='#64748b',width=2,tags=('link',))
            self.canvas.create_text((x+xx)/2,(y+yy)/2-12,text=a[1],fill='#475569')
            self.canvas.create_text((x+xx)/2,(y+yy)/2+12,text=b[1],fill='#475569')
        for node in graph['nodes']:
            name=node['name'];x,y=positions[name];observed=self.states.get(name,{})
            state=observed.get('status','non observé');memory=observed.get('memory')
            color='#dcfce7' if state=='running' else '#e2e8f0'
            tags=('node','node:'+name)
            self.node_shapes[name]=self.canvas.create_rectangle(x-70,y-30,x+70,y+30,fill=color,outline='#334155',width=2,tags=tags)
            self.canvas.create_text(x,y,text=name+'\n'+node['role']+' · '+node['runtime'],tags=tags)
            self.canvas.tag_bind('node:'+name,'<Button-1>',lambda event,n=name:self.choose_node(n))
            self.nodes.insert('','end',iid=name,text=name,values=(node['runtime'],state,'—' if memory is None else f'{memory/1048576:.1f} MiB'))
        self.canvas.configure(scrollregion=(0,0,columns*190+30,max(220,math.ceil(len(graph['nodes'])/columns)*125+40)))
        hosts=[n['name'] for n in graph['nodes'] if n['runtime']=='oci' and n['role']=='host']
        self.targets.configure(values=hosts);self.destination.set(destination if destination in hosts else hosts[-1] if hosts else '')
        if graph['nodes']:self.choose_node(previous if previous in positions else graph['nodes'][0]['name'])

    def choose_node(self,name):self.nodes.selection_set(name);self.nodes.see(name);self.select_node()
    def select_node(self,event=None):
        selected=self.nodes.selection();node=next((n for n in self.graph['nodes'] if selected and n['name']==selected[0]),None)
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
        self.show_output(report);self.tabs.select(self.output_tab);return True

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
            self.draw(self.graph);self.show_output(response);return
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
        self.tabs.select(self.output_tab if action in ('inspect','verify') else self.topology_tab)

    def destroyed(self,event):
        if event.widget is self.window:
            self.closed=True
            if self.poll_id:
                try:self.window.after_cancel(self.poll_id)
                except tk.TclError:pass
            if self.pending:self.pending['directory'].cleanup();self.pending=None

    def close(self):self.window.destroy()
