"""Editor for transparent LAN ICMP policies."""
import tkinter as tk
from .theme import PANEL
from tkinter import ttk,messagebox
from .layout import fit_dialog,ScrollPanel
from .cli import Session
from .device_config import apply_device_commands

class FirewallEditor:
    def __init__(self,app,node,parent=None,on_change=None,can_apply=None):
        self.app,self.node=app,node
        self.on_change,self.can_apply=on_change,can_apply
        if parent is None:
            self.window=win=tk.Toplevel(app.root);win.title('Firewall LAN · '+node);win.configure(bg=PANEL)
            fit_dialog(win,880,610)
        else:
            self.window=win=parent
        self.panel=ScrollPanel(win,PANEL);self.panel.pack(fill='both',expand=True)
        win=self.panel.inner
        ttk.Label(win,text='Filtrage transparent ICMP / TCP / UDP · console de simulation · ordre croissant des IDs',padding=12).pack(fill='x')
        policy=ttk.Frame(win,padding=12);policy.pack(fill='x')
        n=app.lab.nodes[node]
        self.mode=tk.StringVar(value=n.firewall_mode);self.default=tk.StringVar(value=n.firewall_default)
        for caption,value,options in [('Mode',self.mode,['stateful','stateless']),('Défaut',self.default,['deny','allow'])]:
            ttk.Label(policy,text=caption).pack(side='left',padx=5)
            ttk.Combobox(policy,textvariable=value,values=options,state='readonly',width=13).pack(side='left')
        ttk.Button(policy,text='Appliquer la politique',command=self.policy_apply).pack(side='right')
        self.table=ttk.Treeview(win,columns=('id','action','protocol','source','target','port'),show='headings',height=6)
        for key,title,width in [('id','Ordre / ID',75),('action','Action',75),('protocol','Protocole',75),('source','Source IPv4 / CIDR',190),('target','Destination IPv4 / CIDR',190),('port','Port',65)]:
            self.table.heading(key,text=title);self.table.column(key,width=width)
        self.table.pack(fill='both',expand=True,padx=12,pady=8)
        ttk.Label(win,text='Nouvelle règle : ID · action · source CIDR ou any · destination CIDR ou any',padding=10).pack(fill='x')
        fields=ttk.Frame(win,padding=12);fields.pack(fill='x')
        protocol_row=ttk.Frame(win,padding=(12,0));protocol_row.pack(fill='x')
        self.protocol=tk.StringVar(value='icmp');self.port=tk.StringVar(value='any')
        ttk.Label(protocol_row,text='Protocole').pack(side='left',padx=4)
        ttk.Combobox(protocol_row,textvariable=self.protocol,values=['icmp','tcp','udp','any'],state='readonly',width=10).pack(side='left',padx=4)
        ttk.Label(protocol_row,text='Port service (any = tous)').pack(side='left',padx=4)
        ttk.Entry(protocol_row,textvariable=self.port,width=10).pack(side='left',padx=4)
        self.number=tk.StringVar(value='10');self.action=tk.StringVar(value='allow');self.source=tk.StringVar(value='any');self.target=tk.StringVar(value='any')
        ttk.Entry(fields,textvariable=self.number,width=7).pack(side='left',padx=4)
        ttk.Combobox(fields,textvariable=self.action,values=['allow','deny'],state='readonly',width=8).pack(side='left',padx=4)
        ttk.Entry(fields,textvariable=self.source,width=22).pack(side='left',padx=4,fill='x',expand=True)
        ttk.Entry(fields,textvariable=self.target,width=22).pack(side='left',padx=4,fill='x',expand=True)
        actions=ttk.Frame(win,padding=12);actions.pack(fill='x')
        ttk.Button(actions,text='Ajouter / remplacer cet ID',command=self.add).pack(side='left')
        ttk.Button(actions,text='Supprimer la sélection',command=self.remove).pack(side='right')
        self.report=tk.StringVar()
        ttk.Label(win,textvariable=self.report,padding=12,wraplength=780).pack(fill='x')
        ttk.Label(win,text='Sessions : transaction simulée courante. Pas de handshake TCP, application réelle, NAT, VPN, IPS ou inspection web.',padding=12,wraplength=780).pack(fill='x')
        self.refresh()

    def execute(self,line):
        if self.can_apply and not self.can_apply():return False
        result=Session(self.app.lab,self.node).execute(line)
        if result.startswith('%'):
            messagebox.showerror('Politique firewall',result,parent=self.window);return False
        if self.on_change:self.on_change()
        self.app.changed('Politique firewall mise à jour');self.refresh();return True

    def policy_apply(self):
        if self.can_apply and not self.can_apply():return False
        commands=['firewall mode '+self.mode.get(),'firewall default '+self.default.get()]
        try:
            apply_device_commands(self.app.lab,self.node,commands)
        except ValueError as error:
            messagebox.showerror('Politique firewall',str(error),parent=self.window);return False
        if self.on_change:self.on_change()
        self.app.changed('Politique firewall mise à jour');self.refresh();return True

    def add(self):
        self.execute(f'firewall rule {self.number.get().strip()} {self.action.get()} {self.protocol.get()} {self.source.get().strip()} {self.target.get().strip()} {self.port.get().strip() if self.protocol.get() in ('tcp','udp') else 'any'}')

    def remove(self):
        if self.table.selection():
            self.execute('firewall rule delete '+self.table.selection()[0])

    def refresh(self):
        self.table.delete(*self.table.get_children())
        for r in sorted(self.app.lab.nodes[self.node].firewall_rules,key=lambda r:r['id']):
            self.table.insert('', 'end',iid=str(r['id']),values=(r['id'],r['action'],r.get('protocol','icmp'),r['source'],r['target'],r.get('port',0) or 'any'))
        counts=self.app.lab.firewall_counters.get(self.node,{'allow':0,'deny':0})
        self.report.set(f'Transactions : autorisés {counts["allow"]} · refusés {counts["deny"]}. Compteurs pédagogiques, pas des compteurs de paquets réels.')
