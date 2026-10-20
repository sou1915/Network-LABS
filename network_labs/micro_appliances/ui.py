"""Optional, separate three-appliance lab; no changes to the normal topology."""
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from .runtime import make_lab,ApplianceFault
from .experiment import echo_ping,memory_sample
from .packets import describe
from ..layout import fit_dialog
from ..theme import PANEL,TEXT,MUTED,BLUE,TEAL,RED

class MicroLabWindow:
    def __init__(self,app,snapshot=None):
        self.app=app;self.fabric=snapshot if snapshot is not None else make_lab();self.owns_fabric=snapshot is None;self.closed=False;self.link_up=True
        self.window=win=tk.Toplevel(app.root);win.title('Network LABS · Lab micro-appliances expérimental')
        win.configure(bg=PANEL);fit_dialog(win,1100,760);win.protocol('WM_DELETE_WINDOW',self.close)
        win.bind('<Destroy>',self.destroyed)
        ttk.Label(win,text='Lab micro-appliances · PC1 — SW1 — PC2' if self.owns_fabric else 'Capture Wasm · topologie du projet',font=('DejaVu Sans',14,'bold'),padding=12).pack(fill='x')
        caption=ttk.Label(win,text='Exécution Wasm indépendante · ARP / ICMP / TCP · lab séparé du projet courant · aucun OS invité' if self.owns_fabric else 'Instantané du dernier test du projet · ports physiques conservés · nouvelles instances par test · aucun OS invité',padding=(12,0,12,10),wraplength=900);caption.pack(fill='x')
        caption.bind('<Configure>',lambda e:caption.configure(wraplength=max(150,e.width-30)))
        actions=ttk.Frame(win,padding=(12,4));actions.pack(fill='x')
        controls=[('Ping PC1 → PC2',self.ping),('TCP echo / 8080',self.tcp),('Réinitialiser',self.reset)] if self.owns_fabric else []
        for title,action in controls+[('Exporter PCAP',self.export)]:
            ttk.Button(actions,text=title,command=action).pack(side='left',padx=(0,6))
        if self.owns_fabric:
            self.link_button=ttk.Button(actions,text='Déconnecter PC2',command=self.toggle_link);self.link_button.pack(side='right')
        self.status=tk.StringVar(value='Prêt. Chaque équipement dispose de sa mémoire et de son état réseau propres.' if self.owns_fabric else 'Capture figée. Modifier les équipements et relancer un test dans le projet pour produire une nouvelle capture.')
        status=ttk.Label(win,textvariable=self.status,padding=12,wraplength=1000);status.pack(fill='x')
        status.bind('<Configure>',lambda e:status.configure(wraplength=max(120,e.width-30)))
        self.nodes=ttk.Treeview(win,columns=('role','address','memory','rx','tx','mac'),show='tree headings',height=min(6,len(self.fabric.stats()['nodes'])))
        self.nodes.heading('#0',text='Instance');self.nodes.column('#0',width=110,stretch=False)
        for key,title,width in [('role','Rôle',100),('address','IPv4',130),('memory','Mémoire linéaire',140),('rx','RX trames',100),('tx','TX trames',100),('mac','MAC apprises',110)]:
            self.nodes.heading(key,text=title);self.nodes.column(key,width=width)
        self.nodes.pack(fill='x',padx=12,pady=8)
        self.resources=tk.StringVar()
        resource_label=ttk.Label(win,textvariable=self.resources,padding=(12,0,12,8),wraplength=980);resource_label.pack(fill='x')
        resource_label.bind('<Configure>',lambda e:resource_label.configure(wraplength=max(150,e.width-30)))
        split=ttk.Panedwindow(win,orient='vertical');split.pack(fill='both',expand=True,padx=12,pady=(0,12))
        frame=ttk.Frame(split);split.add(frame,weight=2)
        self.trace=ttk.Treeview(frame,columns=('time','path','protocol','description'),show='headings',height=8)
        for key,title,width in [('time','Temps virtuel',120),('path','Liaison',140),('protocol','Protocole',90),('description','Ce qui a été observé',550)]:
            self.trace.heading(key,text=title);self.trace.column(key,width=width,stretch=key=='description')
        sb=ttk.Scrollbar(frame,command=self.trace.yview);self.trace.configure(yscrollcommand=sb.set);sb.pack(side='right',fill='y');self.trace.pack(fill='both',expand=True)
        self.trace.bind('<<TreeviewSelect>>',self.inspect)
        self.detail=tk.Text(split,height=5,bg='#f4f7fa',fg=TEXT,wrap='word',font=('DejaVu Sans Mono',10),padx=10,pady=10,state='disabled');split.add(self.detail,weight=1)
        self.update()

    def update(self):
        self.nodes.delete(*self.nodes.get_children())
        for row in self.fabric.stats()['nodes']:
            self.nodes.insert('', 'end',text=row['name'],values=(row['role'],row['address'] if row['role']!='switch' else '—',str(row['linear_memory_bytes']//1024)+' Kio',row['rx_frames'],row['tx_frames'],row['learned_macs'] if row['learned_macs'] is not None else '—'))
        self.trace.delete(*self.trace.get_children())
        for index,frame in enumerate(self.fabric.frames):
            packet=describe(frame)
            self.trace.insert('', 'end',iid=str(index),values=(str(frame.time_ms)+' ms',frame.source+' → '+frame.destination,packet['protocol'],packet.get('explanation','Trame Ethernet')))
        memory=memory_sample();rss=memory.get('rss_bytes')
        self.resources.set(('RSS du processus entier (GUI incluse) : '+f'{rss/1048576:.1f} Mio. ' if rss else '')+'La mémoire linéaire ci-dessus est une capacité allouée, distincte de la RAM totale du runtime. Horloge virtuelle contrôlée.')
        if self.fabric.frames:
            index=str(len(self.fabric.frames)-1);self.trace.selection_set(index);self.trace.see(index);self.inspect()

    def ping(self):
        try:
            result=echo_ping(self.fabric,'PC1','10.0.0.2')
            self.status.set('ICMP : réponse reçue avec la charge utile attendue.' if result['ok'] else 'ICMP : aucune réponse reçue avant le délai virtuel. Vérifier la liaison de PC2.')
        except (ValueError,ApplianceFault) as error:self.status.set(str(error))
        self.update()

    def tcp(self):
        try:
            client=self.fabric.nodes['PC1'];payload=b'Hello from the micro-appliance lab'
            if client.reply()==payload:
                self.status.set('Échange TCP déjà terminé. Réinitialiser pour observer une nouvelle connexion.');return
            client.connect('10.0.0.2',8080,payload)
            ok=self.fabric.run_until(lambda:client.reply()==payload)
            self.status.set('TCP : handshake et échange de données aller-retour réussis.' if ok else 'TCP : aucun écho reçu avant le délai virtuel. Vérifier la liaison de PC2.')
        except (ValueError,ApplianceFault) as error:self.status.set(str(error))
        self.update()

    def toggle_link(self):
        self.link_up=not self.link_up;self.fabric.set_link_enabled('PC2',0,self.link_up)
        self.link_button.configure(text='Déconnecter PC2' if self.link_up else 'Reconnecter PC2')
        self.status.set('Liaison de PC2 '+('connectée.' if self.link_up else 'déconnectée. Les nouvelles trames ne sont plus livrées.'))

    def reset(self):
        self.fabric.close();self.fabric=make_lab();self.link_up=True
        self.link_button.configure(text='Déconnecter PC2');self.status.set('Nouvelles instances créées : états et tables remis à zéro.')
        self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.configure(state='disabled');self.update()

    def inspect(self,event=None):
        selection=self.trace.selection()
        if not selection:return
        frame=self.fabric.frames[int(selection[0])];packet=describe(frame)
        text=packet.get('explanation',packet['protocol'])+'\n'+frame.source+':'+str(frame.source_port)+' → '+frame.destination+':'+str(frame.destination_port)
        if not self.owns_fabric:
            text+='\nPorts du projet : '+self.fabric.port_names[frame.source][frame.source_port]+' → '+self.fabric.port_names[frame.destination][frame.destination_port]
        text+='\nEthernet : '+packet.get('source_mac','')+' → '+packet.get('destination_mac','')
        if 'checksum_ok' in packet:text+='\nChecksum transport : '+('valide' if packet['checksum_ok'] else 'invalide')
        if packet.get('payload'):text+='\nCharge utile (hex) : '+packet['payload']
        self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.insert('end',text);self.detail.configure(state='disabled')

    def export(self):
        path=filedialog.asksaveasfilename(parent=self.window,defaultextension='.pcap',filetypes=[('Capture Ethernet','*.pcap')])
        if path:
            try:self.fabric.write_pcap(path);self.status.set('Capture PCAP exportée : observations des ports connectés, temps virtuels.')
            except OSError as error:messagebox.showerror('Export PCAP',str(error),parent=self.window)

    def close(self):
        if self.closed:return
        self.closed=True
        if self.owns_fabric:self.fabric.close()
        self.window.destroy()

    def destroyed(self,event):
        if event.widget==self.window and not self.closed:
            self.closed=True
            if self.owns_fabric:self.fabric.close()
