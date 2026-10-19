"""Editor for transparent LAN ICMP policies."""
import tkinter as tk
from tkinter import ttk,messagebox
from .layout import fit_dialog,ScrollPanel
from .cli import Session

class FirewallEditor:
    def __init__(self,app,node):
        self.app,self.node=app,node
        self.window=win=tk.Toplevel(app.root);win.title('Firewall LAN · '+node);win.configure(bg='#111d2e')
        fit_dialog(win,880,610)
        self.panel=ScrollPanel(win,'#111d2e');self.panel.pack(fill='both',expand=True)
        win=self.panel.inner
        ttk.Label(win,text='Filtrage transparent ICMP · console de simulation · ordre croissant des IDs',padding=12).pack(fill='x')
        policy=ttk.Frame(win,padding=12);policy.pack(fill='x')
        n=app.lab.nodes[node]
        self.mode=tk.StringVar(value=n.firewall_mode);self.default=tk.StringVar(value=n.firewall_default)
        for caption,value,options in [('Mode',self.mode,['stateful','stateless']),('Défaut',self.default,['deny','allow'])]:
            ttk.Label(policy,text=caption).pack(side='left',padx=5)
            ttk.Combobox(policy,textvariable=value,values=options,state='readonly',width=13).pack(side='left')
        ttk.Button(policy,text='Appliquer la politique',command=self.policy_apply).pack(side='right')
        self.table=ttk.Treeview(win,columns=('id','action','source','target'),show='headings',height=6)
        for key,title,width in [('id','Ordre / ID',75),('action','Action',75),('source','Source IPv4 / CIDR',270),('target','Destination IPv4 / CIDR',270)]:
            self.table.heading(key,text=title);self.table.column(key,width=width)
        self.table.pack(fill='both',expand=True,padx=12,pady=8)
        ttk.Label(win,text='Nouvelle règle : ID · action · source CIDR ou any · destination CIDR ou any',padding=10).pack(fill='x')
        fields=ttk.Frame(win,padding=12);fields.pack(fill='x')
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
        ttk.Label(win,text='Sessions : dernier test ICMP uniquement. Pas de TCP/UDP, NAT, VPN, IPS/antivirus ou inspection web.',padding=12,wraplength=780).pack(fill='x')
        self.refresh()

    def execute(self,line):
        result=Session(self.app.lab,self.node).execute(line)
        if result.startswith('%'):
            messagebox.showerror('Politique firewall',result,parent=self.window);return False
        self.app.changed('Politique firewall mise à jour');self.refresh();return True

    def policy_apply(self):
        self.execute('firewall mode '+self.mode.get())
        self.execute('firewall default '+self.default.get())

    def add(self):
        self.execute(f'firewall rule {self.number.get().strip()} {self.action.get()} {self.source.get().strip()} {self.target.get().strip()}')

    def remove(self):
        if self.table.selection():
            self.execute('firewall rule delete '+self.table.selection()[0])

    def refresh(self):
        self.table.delete(*self.table.get_children())
        for r in sorted(self.app.lab.nodes[self.node].firewall_rules,key=lambda r:r['id']):
            self.table.insert('', 'end',iid=str(r['id']),values=(r['id'],r['action'],r['source'],r['target']))
        counts=self.app.lab.firewall_counters.get(self.node,{'allow':0,'deny':0})
        self.report.set(f'Tests ICMP : autorisés {counts["allow"]} · refusés {counts["deny"]}. Compteurs pédagogiques, pas des compteurs de paquets réels.')
