"""The workbench's topology editing: the edit mode, moving devices, adding devices and cables. A mixin of ui.ApplianceWindow."""
import json
import tkinter as tk
from tkinter import filedialog, ttk
from .spec import validate
from . import topology_edit
from .ui_bridge import public_topology


class TopologyEditing:
    def set_edit_mode(self,mode):
        if self.pending:
            return
        self.edit_mode=mode
        self.panning=False
        self.tool_mode.set('cable' if mode=='cable' else 'select')
        self.cable_source=None
        self.dragging=None
        self.canvas.configure(cursor='crosshair' if mode=='cable' else '')
        cable='Câbler : cliquer deux équipements (Ctrl+clic sur le second pour choisir les ports).'
        self.note.set(cable if mode=='cable' else 'Sélectionner ou déplacer un équipement · clic droit sur un câble pour le retirer.')

    def editing_spec(self):
        if self.pending:
            raise ValueError('Attendre la fin de l’opération native.')
        spec=self.manifest()
        if public_topology(spec)!=self.graph:
            raise ValueError('Le brouillon JSON diffère du dessin. Valider / plan avant une édition graphique.')
        return spec

    def commit_edit(self,spec):
        spec=validate(spec)
        self.editor.delete('1.0','end')
        self.editor.insert('1.0',json.dumps(spec,indent=2))
        self.draw(public_topology(spec))
        self.observation.set('Brouillon modifié · état runtime non observé.')
        self.note.set('Brouillon uniquement : enregistrer, puis arrêter / redémarrer pour appliquer. Aucun réseau actif modifié.')
        self.tabs.select(self.topology_tab)

    def node_pressed(self,event,name):
        if getattr(event,'state',0)&1:
            return self.begin_pan(event)
        self.choose_node(name)
        self.canvas.focus_set()
        if self.pending:
            return
        if self.edit_mode=='cable':
            if self.cable_source is None:
                self.cable_source=name
                self.note.set('Choisir le deuxième équipement après '+name+'.')
            elif self.cable_source!=name:
                # Ctrl-click chooses the ports; a plain click takes the first free ones.
                first,self.cable_source=self.cable_source,None
                if getattr(event,'state',0)&4:
                    self.connect_dialog(first,name)
                else:
                    self.auto_connect(first,name)
            return
        self.drag_moved=False
        self.dragging=(name,self.canvas.canvasx(event.x),self.canvas.canvasy(event.y))

    def drag_node(self,event):
        if self.panning:
            return self.pan_motion(event)
        if self.pending or not self.dragging:
            return
        name,x,y=self.dragging
        xx=self.canvas.canvasx(event.x)
        yy=self.canvas.canvasy(event.y)
        if abs(xx-x)+abs(yy-y)>1:
            self.drag_moved=True
        self.canvas.move('node:'+name,xx-x,yy-y)
        self.dragging=(name,xx,yy)

    def drop_node(self,event):
        if self.panning:
            return self.end_pan(event)
        if not self.dragging:
            return
        name,_,_=self.dragging
        self.dragging=None
        if not self.drag_moved:
            return
        box=self.canvas.coords(self.node_shapes[name])
        # Box centre minus the device origin: (-40+68)/2 for hosts, (-68+40)/2 for chassis (the tiles' boxes in draw()).
        offset=14 if next(n for n in self.graph['nodes'] if n['name']==name)['role']=='host' else -14
        self.positions[name]=(max(50,(min(box[::2])+max(box[::2]))/(2*self.zoom)),max(60,
                                                                                      (min(box[1::2])+max(box[1::2]))/(2*self.zoom)-offset))
        self.draw(self.graph,self.states)

    def add_device_dialog(self,role='host',model=None):
        server=role=='server'
        if server:
            role='host'
        try:
            spec=self.editing_spec()
        except (ValueError,TypeError,KeyError) as error:
            self.error(error)
            return
        win=tk.Toplevel(self.window)
        win.title('Ajouter un équipement Linux natif')
        win.transient(self.window.winfo_toplevel())
        form=ttk.Frame(win,padding=14)
        form.pack(fill='both',expand=True)
        values={}
        rootfs=next((n['rootfs'] for n in spec['nodes'] if n['runtime']=='oci'),'')
        vm=next((n for n in spec['nodes'] if n['runtime']=='firecracker'),{})
        prefix='SRV' if server else {'host':'PC','switch':'SW','router':'R','firewall':'FW'}[role]
        used={n['name'] for n in spec['nodes']}
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
            value=tk.StringVar(value=initial)
            values[key]=value
            if key in choices:
                field=ttk.Combobox(form,textvariable=value,values=choices[key],state='readonly',
                                   style='Native.TCombobox',font=(self.font,9))
            else:
                field=ttk.Entry(form,textvariable=value,width=38,style='Native.TEntry',font=(self.font,9))
            field.grid(row=row,column=1,sticky='ew',padx=8)
        def browse():
            path=filedialog.askdirectory(parent=win,title='Rootfs Linux')
            if path:
                values['rootfs'].set(path)
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
            spec=self.editing_spec()
            choices=[topology_edit.free_ports(spec,name) for name in (first,second)]
            additions={}
            for index,name in enumerate((first,second)):
                if not choices[index]:
                    additions[name]=topology_edit.next_port(spec,name)
                    choices[index]=[additions[name]]
        except (ValueError,TypeError,KeyError) as error:
            self.error(error)
            return
        win=tk.Toplevel(self.window)
        win.title('Connecter un câble')
        win.transient(self.window.winfo_toplevel())
        form=ttk.Frame(win,padding=14)
        form.pack()
        ports=[]
        for row,(name,available) in enumerate(zip((first,second),choices)):
            ttk.Label(form,text=name+(' · nouveau port' if name in additions else '')).grid(row=row,column=0,pady=6)
            var=tk.StringVar(value=available[0])
            ports.append(var)
            ttk.Combobox(form,textvariable=var,values=available,state='readonly',style='Native.TCombobox',font=(self.font,9)).grid(row=row,
                    column=1,padx=8)
        def apply():
            try:
                draft=self.editing_spec()
                for name,port in additions.items():
                    draft=topology_edit.add_port(draft,name,port)
                self.commit_edit(topology_edit.connect(draft,(first,ports[0].get()),(second,ports[1].get())))
                win.destroy()
            except (ValueError,TypeError,KeyError) as error:self.error(error)
        ttk.Button(form,text='Connecter au brouillon',command=apply,style='Native.Primary.TButton').grid(row=2,column=1,pady=8)
        ttk.Button(form,text='Annuler',command=win.destroy,style='Native.TButton').grid(row=2,column=0)

    def delete_selected(self):
        selected=self.nodes.selection()
        if not selected:
            return
        try:
            self.commit_edit(topology_edit.remove_node(self.editing_spec(),selected[0]))
        except (ValueError,TypeError,KeyError) as error:self.error(error)

    def remove_cable(self,a,b):
        try:
            self.commit_edit(topology_edit.disconnect(self.editing_spec(),a,b))
        except (ValueError,TypeError,KeyError) as error:self.error(error)
