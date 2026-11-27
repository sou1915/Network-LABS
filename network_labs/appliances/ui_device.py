"""The workbench's device configuration form: its fields, ports, web management and header. A mixin of ui.ApplianceWindow."""
import tkinter as tk
from tkinter import ttk
from ..layout import ScrollPanel
from . import topology_edit
from .soft_widgets import SoftCard, SoftPanel
from .reference_theme import PANEL, TEXT, MUTED
from .native_models import port_names
from .ui_bridge import public_topology


class DeviceForm:
    def open_device_config(self,name):
        self.dragging=None
        self.choose_node(name)
        self.device_tabs.select(self.config_panel)
        return 'break'

    def build_config_form(self,parent):
        self.device_heading=tk.StringVar(value='Équipement · GUI')
        webbar=tk.Frame(parent,bg=PANEL)
        webbar.pack(fill='x',pady=3)
        ttk.Button(webbar,text='↗ Gestion web',command=self.open_web_management,style='Native.TButton').pack(side='right',padx=5)
        # Device header: role-coloured band with the device drawing, name, model and status (see draw_device_header).
        self.device_header=tk.Canvas(parent,height=86,bg=PANEL,highlightthickness=0,bd=0)
        self.device_header.pack(fill='x',padx=4,pady=(2,4))
        self.device_header.bind('<Configure>',lambda event:self.draw_device_header())
        self.device_header_node=None
        action_footer=tk.Frame(parent,bg=PANEL)
        action_footer.pack(side='bottom',fill='x')
        tk.Frame(action_footer,bg=PANEL,width=96).pack(side='left',fill='y')
        self.config_actions=tk.Frame(action_footer,bg=PANEL,padx=8,pady=6)
        self.config_actions.pack(side='left',fill='x',expand=True)
        shell=tk.Frame(parent,bg='#f6f8fb')
        shell.pack(fill='both',expand=True)
        rail_card=SoftPanel(shell,PANEL,face='#253440')
        rail_card.configure(width=100)
        rail_card.pack(side='left',fill='y')
        rail=rail_card.inner
        self.config_scroll=ScrollPanel(shell,PANEL)
        self.config_scroll.canvas.configure(bd=0,relief='flat')
        self.config_scroll.scroll.configure(style='Native.Vertical.TScrollbar')
        self.config_scroll.pack(side='left',fill='both',expand=True)
        for title,fraction in [('Interfaces',0),('Détails',.3)]:
            ttk.Button(rail,text=title,command=lambda f=fraction:self.config_scroll.canvas.yview_moveto(f),
                       style='Native.Rail.TButton').pack(fill='x',pady=3)
        self.web_section_buttons=[]
        for section,title,roles in [('dashboard','Vue globale',('host','router','switch','firewall')),('firewall','Politiques',
                ('firewall',)),('nat','NAT / VIP',('firewall',)),('routing','Routage',('router','switch','firewall')),('switching',
                        'VLAN / ports',('switch',))]:
            button=ttk.Button(rail,text=title,command=lambda key=section:self.open_web_management(key),style='Native.Rail.TButton')
            self.web_section_buttons.append((button,roles))
        form=self.config_scroll.inner
        self.label(form,'Interfaces',TEXT,11,True).pack(anchor='w',padx=9,pady=(9,4))
        self.label(form,'Configuration du projet · brouillon',MUTED,7).pack(anchor='w',padx=9,pady=(0,6))
        ports_card=SoftCard(form,PANEL)
        ports_card.pack(fill='x',padx=7)
        self.port_table=ttk.Treeview(ports_card.inner,columns=('address','admin'),show='tree headings',height=3,style='Native.Treeview')
        for key,label,width in [('#0','Nom',96),('address','Adresse IPv4',96),('admin','Admin',58)]:  # fits the panel's default width
            self.port_table.heading(key,text=label)
            self.port_table.column(key,width=width,minwidth=35)
        self.port_table.tag_configure('enabled',foreground='#168942')
        self.port_table.tag_configure('disabled',foreground='#bb3646')
        self.port_table.pack(fill='x')
        self.port_table.bind('<<TreeviewSelect>>',self.config_table_selected)
        detail_card=SoftCard(form,PANEL,face='#edf2f7',border='#edf2f7')
        detail_card.pack(fill='x',padx=7,pady=(10,5))
        detail=detail_card.inner
        self.label(detail,'Détails de l’interface',TEXT,8,True).pack(anchor='w',padx=7,pady=5)
        fields=tk.Frame(form,bg=PANEL)
        fields.pack(fill='x',padx=9)
        fields.columnconfigure(1,weight=1)
        self.config_vars={key:tk.StringVar() for key in ('name','port','address','gateway')}
        self.config_fields={}
        self.config_labels={}
        for row,(key,title) in enumerate([('name','Nom système'),('port','Interface'),('address','IPv4 / CIDR'),('gateway','Passerelle')]):
            caption=self.label(fields,title,MUTED,8)
            caption.grid(row=row,column=0,sticky='w',padx=(0,7),pady=3)
            self.config_labels[key]=caption
            field=ttk.Combobox(fields,textvariable=self.config_vars[key],state='readonly',style='Native.TCombobox',width=15,
                    font=(self.font,9)) if key=='port' else ttk.Entry(fields,textvariable=self.config_vars[key],style='Native.TEntry',
                                                                      width=15,font=(self.font,9))
            field.grid(row=row,column=1,sticky='ew',pady=3)
            self.config_fields[key]=field
        self.config_fields['port'].bind('<<ComboboxSelected>>',self.config_port_selected)
        self.config_enabled=tk.BooleanVar(value=True)
        self.config_admin=ttk.Checkbutton(form,text='Interface activée',variable=self.config_enabled,style='Native.TCheckbutton')
        self.config_admin.pack(anchor='w',padx=9,pady=5)
        self.config_admin_hint=tk.Label(form,text='Arrêter un port : « shutdown » dans le terminal de l’équipement.',bg=PANEL,fg=MUTED,
                                        font=(self.font,8),anchor='w',justify='left',wraplength=260)
        self.config_admin_hint.bind('<Configure>',lambda event:self.config_admin_hint.configure(wraplength=max(120,event.width-4)))
        self.config_admin_anchor=tk.Frame(form,bg=PANEL,height=1)
        self.config_admin_anchor.pack(fill='x')
        self.config_apply=ttk.Button(self.config_actions,text='Appliquer au brouillon',command=self.apply_config,
                                     style='Native.Primary.TButton')
        self.config_apply.pack(side='left',fill='x',expand=True,padx=(0,5))
        ttk.Button(self.config_actions,text='Recharger',command=lambda:self.load_config(force=True),
                   style='Native.TButton').pack(side='right')
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
        if not selected:
            return
        from ..web_portal import WebPortal
        from .web_management import NativeDeviceAPI
        if self.web_portal is None:
            self.web_portal=WebPortal(self,api=NativeDeviceAPI(self),native=True)
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
        if not selected:
            return
        key=(self.view_lab,selected[0])
        if not force and self.config_key==key:
            return
        self.config_key=key
        self.config_baseline=None
        try:
            spec=self.manifest()
            if public_topology(spec)!=self.graph:
                raise ValueError('Valider le JSON avant de charger le formulaire.')
            node=next(n for n in spec['nodes'] if n['name']==selected[0])
            self.config_baseline=spec
            for button,roles in self.web_section_buttons:
                button.pack_forget()
                if node['role'] in roles:
                    button.pack(fill='x',pady=2)
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
            self.config_vars['name'].set(node['name'])
            self.config_vars['gateway'].set(node.get('gateway',''))
            ports=list(node['interfaces'])
            self.config_fields['port'].configure(values=[self.port_choice(p,node) for p in ports])
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
            self.config_message.set(str(error))
            self.config_apply.state(['disabled'])

    def draw_device_header(self):
        """Paint the GUI tab's device band: gradient, drawing, name, brand · model and chips."""
        self.device_header.delete('all')
        if self.device_header_node:
            self.paint_device_header(self.device_header,*self.device_header_node)

    def paint_device_header(self,canvas,spec,node):
        """A device band on CANVAS (the Aperçu and GUI tabs): gradient, drawing, name, brand · model and chips."""
        return self.paint_studio_header(canvas,spec,node)

    def config_port_selected(self,event=None):
        if self.config_baseline is None:
            return
        node=next(n for n in self.config_baseline['nodes'] if n['name']==self.config_key[1])
        port=self.config_port()
        self.config_vars['address'].set(node['interfaces'].get(port,''))
        self.config_enabled.set(port not in node.get('shutdown',[]))
        if self.port_table.exists(port) and self.port_table.selection()!=(port,):
            self.port_table.selection_set(port)
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
            old=self.config_key[1]
            values={k:v.get().strip() for k,v in self.config_vars.items()}
            result=topology_edit.configure_node(current,old,new_name=values['name'],port=self.config_port(),address=values['address'],
                                                gateway=values['gateway'],enabled=self.config_enabled.get())
            if old!=values['name'] and old in self.positions:
                self.positions[values['name']]=self.positions.pop(old)
            self.config_key=None
            self.commit_edit(result)
            self.choose_node(values['name'])
            self.load_config(force=True)
            self.config_message.set('Brouillon appliqué. Enregistrer puis arrêter / démarrer pour activer les changements.')
            return True
        except (ValueError,TypeError,KeyError) as error:
            self.config_message.set(str(error))
            return False
