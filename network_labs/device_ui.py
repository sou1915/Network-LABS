"""Device workspace: typed graphical forms and a live CLI share one engine."""
import tkinter as tk
from tkinter import ttk
from .layout import fit_dialog,ScrollPanel
from .profiles import PROFILES,profile_role
from .firewall import is_firewall
from .cli import Session
from .device_config import apply_device_commands,fingerprint

class DeviceWindow:
    def __init__(self,app,node):
        from .__main__ import Terminal
        self.app,self.node,self.lab=app,node,app.lab
        self.loading=True;self.dirty=False;self.closed=False;self.vars={}
        self.window=win=tk.Toplevel(app.root);win.title(node+' · Configuration GUI / CLI');win.configure(bg='#111d2e')
        fit_dialog(win,1060,720)
        win.protocol('WM_DELETE_WINDOW',self.close)
        win.bind('<Destroy>',self.destroyed)
        profile=PROFILES[self.n.profile]
        ttk.Label(win,text=f'{node} · {profile.brand} {profile.model} · {profile_role(profile)}',padding=10).pack(fill='x')
        self.status=tk.StringVar(value='GUI et CLI utilisent la même configuration. Appliquer pour enregistrer un formulaire.')
        footer=ttk.Frame(win,padding=8);footer.pack(side='bottom',fill='x')
        ttk.Button(footer,text='Actualiser les formulaires',command=self.reload).pack(side='right')
        status_label=ttk.Label(footer,textvariable=self.status,wraplength=620)
        status_label.pack(side='left',fill='x',expand=True)
        footer.bind('<Configure>',lambda e:status_label.configure(wraplength=max(180,e.width-240)))
        self.tabs=ttk.Notebook(win);self.tabs.pack(fill='both',expand=True,padx=8,pady=5)
        self.gui=ttk.Notebook(self.tabs);self.tabs.add(self.gui,text='GUI · Configuration')
        self.terminal=Terminal(app,node,parent=self.tabs);self.tabs.add(self.terminal.frame,text='CLI · Console')
        self.config=tk.Text(self.tabs,bg='#0a101c',fg='#d9e7f7',font=('DejaVu Sans Mono',10),wrap='word',state='disabled')
        self.tabs.add(self.config,text='Configuration / limites')
        general=self.page('Système')
        ttk.Label(general,text=profile.scope,wraplength=780).pack(fill='x',pady=8)
        self.field(general,'hostname','Nom système',self.n.hostname or node)
        self.action(general,'Appliquer le nom',lambda:self.apply(['hostname '+self.value('hostname')]))
        if self.n.kind=='PC':
            self.build_endpoint()
        else:
            self.build_ports()
            if self.n.kind=='Routeur':
                self.build_router();self.build_dhcp()
            elif not is_firewall(self.n):
                self.build_vlans();self.build_switching()
        if is_firewall(self.n):
            from .firewall_ui import FirewallEditor
            page=self.page('Politique firewall',scroll=False)
            self.firewall=FirewallEditor(app,node,parent=page,on_change=self.reload,can_apply=self.form_is_current)
            for var in (self.firewall.mode,self.firewall.default,self.firewall.number,self.firewall.action,self.firewall.source,self.firewall.target):var.trace_add('write',self.edited)
        if profile_role(profile)=='Serveur':
            page=self.page('DNS local')
            self.reload_dns=app.dns_editor(node,parent=page)
        self.tabs.bind('<<NotebookTabChanged>>',self.tab_changed)
        self.reload()

    @property
    def n(self):
        return self.app.lab.nodes[self.node]

    def page(self,title,scroll=True):
        if scroll:
            panel=ScrollPanel(self.gui,'#111d2e');self.gui.add(panel,text=title)
            panel.inner.configure(padx=16,pady=10);return panel.inner
        panel=tk.Frame(self.gui,bg='#111d2e');self.gui.add(panel,text=title);return panel

    def edited(self,*args):
        if not self.loading:
            self.dirty=True

    def field(self,parent,key,title,value='',choices=None,check=False):
        var=tk.BooleanVar(value=value) if check else tk.StringVar(value=value)
        self.vars[key]=var;var.trace_add('write',self.edited)
        row=ttk.Frame(parent,padding=(0,4));row.pack(fill='x')
        if check:
            ttk.Checkbutton(row,text=title,variable=var).pack(anchor='w')
        else:
            ttk.Label(row,text=title,width=25).pack(side='left')
            if choices is not None:
                widget=ttk.Combobox(row,textvariable=var,values=choices,state='readonly')
            else:
                widget=ttk.Entry(row,textvariable=var,show='•' if 'password' in key else '')
            widget.pack(side='left',fill='x',expand=True)
            return widget

    def value(self,key):
        value=str(self.vars[key].get()).strip()
        if '\n' in value or '\r' in value:
            raise ValueError('Un seul champ par ligne : '+key)
        return value

    def action(self,parent,title,callback):
        def run():
            try: callback()
            except ValueError as error:self.status.set(str(error))
        ttk.Button(parent,text=title,command=run).pack(anchor='w',pady=10)

    def form_is_current(self):
        if fingerprint(self.n)!=self.base:
            self.status.set('Configuration modifiée depuis ce formulaire. Actualiser avant d’appliquer.');return False
        return True

    def apply(self,commands):
        if not self.form_is_current():return False
        try:
            apply_device_commands(self.app.lab,self.node,commands)
        except ValueError as error:
            self.status.set(str(error));return False
        self.reload();self.app.changed('Configuration GUI appliquée : '+self.node)
        self.status.set('Configuration appliquée et visible dans la CLI.');return True

    def build_endpoint(self):
        page=self.page('Réseau IPv4')
        self.field(page,'address_mode','Configuration IPv4','static',['static','dhcp'])
        for key,title in [('address','Adresse IPv4 / CIDR'),('gateway','Passerelle'),('dns','DNS (séparés par espace)')]:self.field(page,key,title)
        self.field(page,'up','Interface eth0 activée',True,check=True)
        ttk.Label(page,text='En DHCP, adresse/passerelle/DNS proviennent du serveur. Les champs statiques sont ignorés.',wraplength=760).pack(fill='x',pady=8)
        self.action(page,'Appliquer la configuration réseau',self.apply_endpoint)
        self.test_target=tk.StringVar(value='192.168.10.1')
        ttk.Label(page,text='Tester une adresse ou un nom DNS').pack(anchor='w',pady=(14,3))
        ttk.Entry(page,textvariable=self.test_target).pack(fill='x')
        self.action(page,'Tester ping',self.test_ping)

    def apply_endpoint(self):
        commands=['ip link '+('up' if self.vars['up'].get() else 'down')]
        if self.value('address_mode')=='dhcp':
            if self.vars['up'].get():commands+=['ip dhcp']
            elif self.n.address_mode!='dhcp':raise ValueError('Activer eth0 pour obtenir une première configuration DHCP.')
        else:
            commands += ['ip address '+self.value('address') if self.value('address') else 'no ip address',
                         'ip gateway '+self.value('gateway') if self.value('gateway') else 'no ip gateway',
                         'ip dns '+self.value('dns') if self.value('dns') else 'no ip dns']
        return self.apply(commands)

    def test_ping(self):
        ok,trace=self.app.lab.ping(self.node,self.test_target.get().strip())
        self.app.animate_result(ok,trace[-1]);self.status.set(('✓ ' if ok else '✗ ')+ '\n'.join(trace))

    def build_vlans(self):
        page=self.page('VLANs')
        self.vlans=ttk.Treeview(page,columns=('id','name'),show='headings',height=7)
        self.vlans.heading('id',text='VLAN');self.vlans.heading('name',text='Nom');self.vlans.pack(fill='x')
        self.field(page,'vlan_id','VLAN ID','10');self.field(page,'vlan_name','Nom VLAN','USERS')
        self.action(page,'Créer / modifier le VLAN',lambda:self.apply(['vlan '+self.value('vlan_id'),'name '+self.value('vlan_name'),'exit']))
        self.action(page,'Supprimer le VLAN indiqué',lambda:self.apply(['no vlan '+self.value('vlan_id')]))

    def build_ports(self):
        page=self.page('Interfaces')
        self.port_box=self.field(page,'port','Interface',choices=list(self.n.ports))
        self.port_box.bind('<<ComboboxSelected>>',lambda e:self.load_port())
        self.field(page,'description','Description')
        self.field(page,'port_up','Interface activée',True,check=True)
        if self.n.kind=='Switch':
            self.field(page,'mode','Mode','access',['access','trunk','dynamic auto','dynamic desirable'])
            for key,title in [('access','VLAN access'),('native','VLAN natif'),('allowed','VLANs autorisés'),('cost','Coût STP')]:self.field(page,key,title)
            for key,title in [('portfast','PortFast'),('bpduguard','BPDU Guard'),('security','Port security'),('dhcp_trust','DHCP snooping trusted'),('arp_trust','DAI trusted'),('source_guard','IP Source Guard')]:self.field(page,key,title,False,check=True)
            self.field(page,'maximum','MACs autorisées maximum')
            self.field(page,'violation','Violation','shutdown',['shutdown','restrict','protect'])
            self.field(page,'auth_control','802.1X port-control','force-authorized',['force-authorized','force-unauthorized','auto'])
            self.field(page,'authenticator','PAE authenticator',False,check=True)
            self.field(page,'channel','EtherChannel ID (0 = aucun)')
            self.field(page,'channel_mode','Négociation EtherChannel','active',['active','passive','desirable','auto','on'])
        self.action(page,'Appliquer cette interface',self.apply_port)

    def load_port(self):
        key=self.vars['port'].get()
        if key not in self.n.ports:return
        p=self.n.ports[key];before=self.loading;self.loading=True
        values={'description':p.description,'port_up':not p.shutdown,'mode':p.mode,'access':str(p.access_vlan),'native':str(p.native_vlan),'allowed':Session.compact(p.allowed),'cost':str(p.cost),'portfast':p.portfast,'bpduguard':p.bpduguard,'security':p.security,'dhcp_trust':p.dhcp_trust,'arp_trust':p.arp_trust,'source_guard':p.source_guard,'maximum':str(p.maximum),'violation':p.violation,'auth_control':p.auth_control,'authenticator':p.authenticator,'channel':str(p.channel),'channel_mode':p.channel_mode or 'active'}
        for k,v in values.items():
            if k in self.vars:self.vars[k].set(v)
        self.loading=before

    def apply_port(self):
        commands=['interface '+self.value('port'),'description '+self.value('description') if self.value('description') else 'no description']
        if self.n.kind=='Switch':
            # Remove access-only controls before changing to a trunk, then validate the final selection.
            current=self.n.ports[self.value('port')]
            if current.mode!=self.value('mode'):
                commands+=['no switchport port-security','no ip verify source','no authentication port-control']
            commands+=['switchport mode '+self.value('mode'),'switchport access vlan '+self.value('access'),
                       'switchport trunk native vlan '+self.value('native'),'switchport trunk allowed vlan '+self.value('allowed'),
                       'spanning-tree cost '+self.value('cost')]
            for key,command in [('portfast','spanning-tree portfast'),('bpduguard','spanning-tree bpduguard enable'),('security','switchport port-security'),('dhcp_trust','ip dhcp snooping trust'),('arp_trust','ip arp inspection trust'),('source_guard','ip verify source'),('authenticator','dot1x pae authenticator')]:
                commands.append(('' if self.vars[key].get() else 'no ')+command)
            commands+=['switchport port-security maximum '+self.value('maximum'),'switchport port-security violation '+self.value('violation'),]
            if self.value('mode')=='access' and (current.mode!=self.value('mode') or current.auth_control!=self.value('auth_control')):commands.append('authentication port-control '+self.value('auth_control'))
            elif self.value('mode')!='access' and self.value('auth_control')!='force-authorized':raise ValueError('802.1X auto/force-unauthorized : mode access requis.')
            group=int(self.value('channel'))
            commands.append('no channel-group' if group==0 else 'channel-group '+str(group)+' mode '+self.value('channel_mode'))
        commands+=['no shutdown' if self.vars['port_up'].get() else 'shutdown','end']
        return self.apply(commands)

    def build_switching(self):
        page=self.page('Switching / sécurité')
        self.field(page,'stp_mode','Mode STP','rapid-pvst',['pvst','rapid-pvst','mst'])
        self.field(page,'stp_vlan','VLAN / instance MST','1');self.field(page,'priority','Priorité STP','32768')
        self.action(page,'Appliquer STP',lambda:self.apply(['spanning-tree mode '+self.value('stp_mode'),('spanning-tree mst ' if self.value('stp_mode')=='mst' else 'spanning-tree vlan ')+self.value('stp_vlan')+' priority '+self.value('priority')]))
        self.field(page,'mst_name','Nom de région MST','DEFAULT')
        self.field(page,'mst_revision','Révision MST','0')
        self.field(page,'mst_instance','Instance MST','1')
        self.field(page,'mst_vlans','VLANs de l’instance','10')
        self.vars['stp_vlan'].trace_add('write',lambda *args:self.load_priority() if not self.loading else None)
        self.vars['mst_instance'].trace_add('write',lambda *args:self.load_mapping() if not self.loading else None)
        self.action(page,'Appliquer région / mapping MST',lambda:self.apply(['spanning-tree mst configuration','name '+self.value('mst_name'),'revision '+self.value('mst_revision'),'instance '+self.value('mst_instance')+' vlan '+self.value('mst_vlans'),'exit']))
        self.field(page,'vtp_mode','Mode VTP v2','transparent',['server','client','transparent','off'])
        self.field(page,'vtp_domain','Domaine VTP');self.field(page,'vtp_password','Mot de passe VTP')
        self.action(page,'Appliquer VTP',self.apply_vtp)
        for key,title in [('snooping','DHCP snooping'),('igmp','IGMP snooping'),('aaa','AAA new-model'),('dot1x','802.1X global'),('radius','Méthode dot1x group radius')]:self.field(page,key,title,False,check=True)
        self.field(page,'snoop_vlans','VLANs DHCP snooping');self.field(page,'dai_vlans','VLANs DAI')
        self.action(page,'Appliquer les protections',self.apply_protection)

    def apply_vtp(self):
        return self.apply(['vtp version 2','vtp domain '+self.value('vtp_domain') if self.value('vtp_domain') else 'no vtp domain','vtp password '+self.value('vtp_password') if self.value('vtp_password') else 'no vtp password','vtp mode '+self.value('vtp_mode')])

    def apply_protection(self):
        commands=[]
        for key,command in [('snooping','ip dhcp snooping'),('igmp','ip igmp snooping'),('aaa','aaa new-model'),('dot1x','dot1x system-auth-control'),('radius','aaa authentication dot1x default group radius')]:commands.append(('' if self.vars[key].get() else 'no ')+command)
        if self.n.snooping_vlans:commands.append('no ip dhcp snooping vlan '+Session.compact(self.n.snooping_vlans))
        if self.n.dai_vlans:commands.append('no ip arp inspection vlan '+Session.compact(self.n.dai_vlans))
        if self.value('snoop_vlans'):commands.append('ip dhcp snooping vlan '+self.value('snoop_vlans'))
        if self.value('dai_vlans'):commands.append('ip arp inspection vlan '+self.value('dai_vlans'))
        return self.apply(commands)

    def build_router(self):
        page=self.page('802.1Q / IPv4')
        self.subs=ttk.Treeview(page,columns=('name','vlan','ip'),show='headings',height=6)
        for key,title in [('name','Interface'),('vlan','VLAN'),('ip','IPv4')]:self.subs.heading(key,text=title)
        self.subs.pack(fill='x')
        self.subs.bind('<<TreeviewSelect>>',self.select_subinterface)
        self.field(page,'subif','Sous-interface','gi0/0.10');self.field(page,'tag','VLAN 802.1Q','10');self.field(page,'subip','Adresse IPv4 / CIDR','192.168.10.1/24')
        self.action(page,'Créer / modifier la sous-interface',lambda:self.apply(['interface '+self.value('subif'),'encapsulation dot1Q '+self.value('tag'),'ip address '+self.value('subip'),'no shutdown','end']))
        self.action(page,'Supprimer la sous-interface',lambda:self.apply(['no interface '+self.value('subif')]))

    def build_dhcp(self):
        page=self.page('Serveur DHCP')
        self.field(page,'dhcp_service','Service DHCP activé',True,check=True)
        self.action(page,'Appliquer le service DHCP',lambda:self.apply(['service dhcp' if self.vars['dhcp_service'].get() else 'no service dhcp']))
        self.pool_box=self.field(page,'pool','Pool DHCP',choices=list(self.n.dhcp_pools))
        self.pool_box.configure(state='normal');self.pool_box.bind('<<ComboboxSelected>>',lambda e:self.load_pool())
        for key,title in [('network','Réseau / CIDR'),('pool_gateway','Passerelle distribuée'),('pool_dns','DNS distribués')]:self.field(page,key,title)
        for key,title in [('lease_days','Bail : jours'),('lease_hours','Bail : heures'),('lease_minutes','Bail : minutes')]:self.field(page,key,title,'0')
        self.action(page,'Créer / remplacer le pool',self.apply_pool)
        self.action(page,'Supprimer le pool',lambda:self.apply(['no ip dhcp pool '+self.value('pool')]))
        self.exclusions=ttk.Label(page,text='',wraplength=760);self.exclusions.pack(fill='x',pady=8)
        self.field(page,'excluded_first','Première IP exclue');self.field(page,'excluded_last','Dernière IP exclue')
        self.action(page,'Ajouter la plage exclue',lambda:self.apply(['ip dhcp excluded-address '+self.value('excluded_first')+' '+self.value('excluded_last')]))
        self.action(page,'Retirer la plage indiquée',lambda:self.apply(['no ip dhcp excluded-address '+self.value('excluded_first')+' '+self.value('excluded_last')]))

    def load_pool(self):
        pool=self.n.dhcp_pools.get(self.vars['pool'].get(),{})
        before=self.loading;self.loading=True
        for key,value in [('network',pool.get('network','')),('pool_gateway',pool.get('gateway','')),('pool_dns',' '.join(pool.get('dns',[])))]:self.vars[key].set(value)
        days,rem=divmod(pool.get('lease',86400),86400);hours,rem=divmod(rem,3600)
        for key,value in [('lease_days',days),('lease_hours',hours),('lease_minutes',rem//60)]:self.vars[key].set(str(value))
        self.loading=before

    def apply_pool(self):
        # Replace in the isolated candidate, so removing an old pool is rolled back on any error.
        name=self.value('pool')
        commands=['no ip dhcp pool '+name,'ip dhcp pool '+name,'network '+self.value('network')]
        if self.value('pool_gateway'):commands.append('default-router '+self.value('pool_gateway'))
        if self.value('pool_dns'):commands.append('dns-server '+self.value('pool_dns'))
        commands.append('lease '+self.value('lease_days')+' '+self.value('lease_hours')+' '+self.value('lease_minutes'))
        return self.apply(commands+['exit','end'])

    def select_subinterface(self,event=None):
        if self.closed:return
        selected=self.subs.selection()
        if not selected:return
        key=selected[0];p=self.n.ports.get(key)
        if p is None:return
        before=self.loading;self.loading=True
        self.vars['subif'].set(key);self.vars['tag'].set(str(p.sub_vlan));self.vars['subip'].set(p.address)
        self.loading=before

    def load_priority(self):
        before=self.loading;self.loading=True
        key=('mst:' if self.vars['stp_mode'].get()=='mst' else '')+self.vars['stp_vlan'].get()
        self.vars['priority'].set(str(self.n.priorities.get(key,32768)))
        self.loading=before

    def load_mapping(self):
        before=self.loading;self.loading=True
        try:instance=int(self.vars['mst_instance'].get())
        except ValueError:instance=-1
        values=sorted(int(v) for v,i in self.n.mst_map.items() if i==instance)
        self.vars['mst_vlans'].set(Session.compact(values) if values else '')
        self.loading=before

    def reload(self):
        self.loading=True
        n=self.n
        values={'hostname':n.hostname or n.name,'address':n.address,'gateway':n.gateway,'dns':' '.join(n.dns),'dhcp_service':n.dhcp_service,'address_mode':n.address_mode,'up':not n.ports.get('eth0',next(iter(n.ports.values()))).shutdown,'stp_mode':n.stp_mode,'mst_name':n.mst_name or 'DEFAULT','mst_revision':str(n.mst_revision),'vtp_mode':n.vtp_mode,'vtp_domain':n.vtp_domain,'vtp_password':n.vtp_password,'snooping':n.dhcp_snooping,'igmp':n.igmp_enabled,'aaa':n.aaa_enabled,'dot1x':n.dot1x_enabled,'radius':n.dot1x_radius,'snoop_vlans':Session.compact(n.snooping_vlans) if n.snooping_vlans else '','dai_vlans':Session.compact(n.dai_vlans) if n.dai_vlans else ''}
        for key,value in values.items():
            if key in self.vars:self.vars[key].set(value)
        if hasattr(self,'port_box'):
            self.port_box['values']=list(n.ports)
            if self.vars['port'].get() not in n.ports:self.vars['port'].set(next(iter(n.ports)))
            self.load_port()
        if hasattr(self,'vlans'):
            self.vlans.delete(*self.vlans.get_children())
            for v,name in sorted(n.vlans.items(),key=lambda item:int(item[0])):self.vlans.insert('', 'end',values=(v,name))
        if hasattr(self,'subs'):
            self.subs.delete(*self.subs.get_children())
            for key,p in n.ports.items():
                if p.sub_vlan:self.subs.insert('', 'end',iid=key,values=(key,p.sub_vlan,p.address))
            if self.vars['subif'].get() in self.subs.get_children():
                self.subs.selection_set(self.vars['subif'].get());self.select_subinterface()
        if hasattr(self,'pool_box'):
            self.pool_box['values']=list(n.dhcp_pools)
            if not self.vars['pool'].get():self.vars['pool'].set(next(iter(n.dhcp_pools),'LAN'))
            self.load_pool()
            self.exclusions.configure(text='Exclusions : '+('; '.join(a+' – '+b for a,b in n.dhcp_excluded) or 'aucune'))
        if 'priority' in self.vars:self.load_priority();self.load_mapping()
        if hasattr(self,'reload_dns'):self.reload_dns()
        if hasattr(self,'firewall'):
            self.firewall.mode.set(n.firewall_mode);self.firewall.default.set(n.firewall_default);self.firewall.refresh()
        self.base=fingerprint(n);self.dirty=False;self.loading=False
        self.terminal.refresh_prompt();self.update_config()
        self.status.set('Formulaires synchronisés avec la configuration courante.')

    def update_config(self):
        n=self.n;profile=PROFILES[n.profile]
        text=profile.scope+'\n\n'
        text+=Session(self.app.lab,self.node).execute('ipconfig') if n.kind=='PC' else Session(self.app.lab,self.node).running_config()
        self.config.configure(state='normal');self.config.delete('1.0','end');self.config.insert('1.0',text);self.config.configure(state='disabled')

    def external_changed(self):
        if self.closed:return
        if self.app.lab is not self.lab or self.node not in self.app.lab.nodes:
            self.close();return
        self.terminal.refresh_prompt()
        if fingerprint(self.n)!=self.base:
            if self.dirty:self.status.set('La CLI ou un autre panneau a modifié cet équipement. Actualiser avant d’appliquer vos champs.')
            else:self.reload()
        self.update_config()

    def tab_changed(self,event=None):
        if self.closed:return
        self.external_changed()
        if self.tabs.select()==str(self.terminal.frame):self.terminal.entry.focus_set();self.terminal.schedule_tail()

    def show_page(self,title):
        self.tabs.select(self.gui)
        for page in self.gui.tabs():
            if self.gui.tab(page,'text')==title:
                self.gui.select(page);break
        self.window.lift()

    def destroyed(self,event):
        if event.widget==self.window:
            self.closed=True
            windows=getattr(self.app,'device_windows',{})
            if windows.get(self.node) is self:windows.pop(self.node,None)

    def close(self):
        if self.closed:return
        self.closed=True
        getattr(self.app,'device_windows',{}).pop(self.node,None)
        self.window.destroy()
