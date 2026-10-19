"""Interactive desktop topology editor and simplified reachability playback."""
import tkinter as tk
from tkinter import ttk, messagebox
from ipaddress import IPv4Interface, IPv4Address
from .basic_ui import App as BasicApp
from .engine import Node

BG, PANEL, INK, MUTED = '#0b1220', '#131f32', '#e2ecfb', '#8199b8'
ACCENT = '#38d9bc'

class App(BasicApp):
    def __init__(self, root):
        from .engine import demo
        self.root, self.lab = root, demo()
        self.selected = self.link_selected = None
        self.mode, self.anchor = 'select', None
        self.timer = None
        self.hops, self.index, self.progress = [], 0, 0
        self.running, self.result = False, None
        root.title('Network LABS • Studio réseau')
        root.geometry('1320x880')
        root.minsize(1100, 760)
        root.configure(bg=BG)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', background=PANEL, foreground=INK, font=('DejaVu Sans', 10))
        style.configure('TButton', padding=(12, 9), background='#223650', borderwidth=0)
        style.map('TButton', background=[('active', '#305375')])
        style.configure('TEntry', fieldbackground='#0d1727', foreground=INK, insertcolor=INK)
        style.configure('TCombobox', fieldbackground='#0d1727', foreground=INK)
        style.configure('TScale', background=PANEL, troughcolor=BG)
        header = tk.Frame(root, bg=PANEL, padx=20, pady=12)
        header.pack(fill='x')
        tk.Label(header, text='◈  NETWORK LABS', bg=PANEL, fg=ACCENT, font=('DejaVu Sans', 17, 'bold')).pack(side='left')
        tk.Label(header, text='  /  Studio de simulation', bg=PANEL, fg=MUTED).pack(side='left')
        for title, callback in [('Sauvegarder', self.save), ('Ouvrir', self.load), ('Démo', self.reset)]:
            ttk.Button(header, text=title, command=lambda c=callback: self.mutate(c)).pack(side='right', padx=4)
        body = tk.Frame(root, bg=BG)
        body.pack(fill='both', expand=True, padx=12, pady=12)
        sidebar = tk.Frame(body, bg=PANEL, width=160, padx=12, pady=16)
        sidebar.pack(side='left', fill='y', padx=(0, 10))
        self.label(sidebar, 'ÉQUIPEMENTS', MUTED)
        for kind, symbol in [('PC', '▣'), ('Switch', '▤'), ('Routeur', '◉')]:
            ttk.Button(sidebar, text=f'{symbol}  {kind}', command=lambda k=kind: self.add(k)).pack(fill='x', pady=6)
        self.label(sidebar, 'OUTILS', MUTED, pady=18)
        ttk.Button(sidebar, text='↖  Sélection', command=lambda: self.set_mode('select')).pack(fill='x', pady=5)
        ttk.Button(sidebar, text='⌁  Câbler', command=lambda: self.set_mode('cable')).pack(fill='x', pady=5)
        ttk.Button(sidebar, text='Supprimer', command=self.delete).pack(fill='x', pady=5)
        self.label(sidebar, 'Câble : cliquer sur\ndeux équipements.\n\nLien : cliquer pour\nmodifier ses VLAN.\n\nÉquipement : glisser\npour déplacer.', MUTED, pady=20)
        right = tk.Frame(body, bg=PANEL, width=275, padx=16, pady=12)
        right.pack(side='right', fill='y', padx=(10, 0))
        self.label(right, 'INSPECTEUR', MUTED)
        self.inspector = tk.Frame(right, bg=PANEL)
        self.inspector.pack(fill='x', pady=12)
        self.label(right, 'TEST DE CONNECTIVITÉ', MUTED, pady=12)
        self.source = tk.StringVar(value='PC1')
        self.destination = tk.StringVar(value='192.168.20.10')
        self.label(right, 'PC source')
        self.source_box = ttk.Combobox(right, textvariable=self.source, state='readonly', width=25)
        self.source_box.pack(fill='x', pady=4)
        self.label(right, 'Adresse IPv4 destination')
        ttk.Entry(right, textvariable=self.destination).pack(fill='x', pady=4)
        ttk.Button(right, text='▶  Lancer le ping simulé', command=self.ping).pack(fill='x', pady=10)
        self.status = tk.StringVar(value='Prêt • Démo inter-VLAN')
        tk.Label(right, textvariable=self.status, bg=PANEL, fg=ACCENT, wraplength=240, justify='left').pack(fill='x', pady=12)
        self.label(right, 'Lecture du chemin calculé.\nARP et trames non simulés.', MUTED, pady=8)
        center = tk.Frame(body, bg=BG)
        center.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(center, bg=BG, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Button-1>', self.select)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<Configure>', lambda e: self.draw())
        controls = tk.Frame(center, bg=PANEL, padx=8, pady=8)
        controls.pack(fill='x', pady=(8, 0))
        for title, callback in [('▶ Lecture', self.play), ('Ⅱ Pause', self.pause), ('⏭ Étape', self.step), ('↺ Rejouer', self.replay)]:
            ttk.Button(controls, text=title, command=callback).pack(side='left', padx=3)
        self.speed = tk.DoubleVar(value=1)
        ttk.Scale(controls, from_=0.3, to=3, variable=self.speed, length=95).pack(side='right')
        tk.Label(controls, text='Vitesse', bg=PANEL, fg=MUTED).pack(side='right', padx=6)
        self.events = ttk.Treeview(center, columns=('phase','chemin'), show='headings', height=4)
        self.events.heading('phase', text='Phase')
        self.events.heading('chemin', text='Chemin / diagnostic')
        self.events.column('phase', width=85, stretch=False)
        self.events.column('chemin', width=400)
        self.events.pack(fill='x', pady=(8, 0))
        self.output = tk.Text(root, height=3, bg=PANEL, fg=MUTED, relief='flat', padx=16, pady=8)
        self.output.pack(fill='x')
        self.log('Glisser les équipements. Cliquer sur un lien pour changer les VLAN. Lancer un ping pour visualiser l’aller et le retour.')
        self.inspect()
        self.draw()

    def label(self, parent, text, color=INK, pady=3):
        widget = tk.Label(parent, text=text, bg=PANEL, fg=color, justify='left', anchor='w')
        widget.pack(fill='x', pady=pady)
        return widget

    def set_mode(self, mode):
        self.mode, self.anchor = mode, None
        self.status.set('Câbler : choisir deux équipements' if mode == 'cable' else 'Sélection / déplacement')

    def mutate(self, callback):
        self.clear_simulation()
        callback()
        self.link_selected = None
        self.inspect()
        self.draw()

    def clear_simulation(self):
        self.pause()
        self.hops, self.index, self.progress, self.result = [], 0, 0, None
        if hasattr(self, 'events'):
            self.events.delete(*self.events.get_children())
        self.status.set('Topologie modifiée • relancer le test')

    def draw(self):
        c = self.canvas
        c.delete('all')
        for x in range(20, c.winfo_width(), 28):
            for y in range(20, c.winfo_height(), 28):
                c.create_oval(x,y,x+1,y+1, fill='#24334a', outline='')
        for i,l in enumerate(self.lab.links):
            a,b = self.lab.nodes[l.a],self.lab.nodes[l.b]
            active = bool(self.hops and self.index < len(self.hops) and {l.a,l.b} == set(self.hops[self.index][:2]))
            color = ACCENT if active else '#ffce66' if self.link_selected == i else '#42617d'
            tags = ('link', str(i))
            c.create_line(a.x,a.y,b.x,b.y,fill=color,width=4,tags=tags)
            c.create_text((a.x+b.x)/2,(a.y+b.y)/2-17,text=f'{l.mode.upper()} · ' + ','.join(map(str,l.vlans)), fill='#a5bbd4',font=('DejaVu Sans',9),tags=tags)
        for n in self.lab.nodes.values():
            color = {'PC':'#225780','Switch':'#126d66','Routeur':'#644b98'}[n.kind]
            tags = ('node',n.name)
            c.create_rectangle(n.x-54,n.y-35,n.x+54,n.y+35,fill=color,outline=ACCENT if n.name==self.selected else '#527497',width=2,tags=tags)
            c.create_text(n.x,n.y-8,text={'PC':'▣','Switch':'▤','Routeur':'◉'}[n.kind],fill='white',font=('DejaVu Sans',23),tags=tags)
            c.create_text(n.x,n.y+21,text=n.name,fill='white',font=('DejaVu Sans',10,'bold'),tags=tags)
            c.create_text(n.x,n.y+50,text=n.address or n.kind,fill=MUTED,tags=tags)
        if self.hops and self.index < len(self.hops):
            a,b,phase = self.hops[self.index]
            a,b = self.lab.nodes[a],self.lab.nodes[b]
            x,y = a.x+(b.x-a.x)*self.progress,a.y+(b.y-a.y)*self.progress
            color = '#f9cf65' if phase=='Aller' else ACCENT
            c.create_rectangle(x-10,y-7,x+10,y+7,fill=color,outline='white',width=2)
            c.create_text(x,y-23,text=phase,fill=color)

    def select(self,event):
        items=self.canvas.find_withtag('current')
        tags=self.canvas.gettags(items[0]) if items else ()
        if tags and tags[0]=='node':
            name=tags[1]
            if self.mode=='cable':
                if self.anchor is None:
                    self.anchor=name
                    self.status.set(f'{name} → choisir la destination')
                else:
                    a,self.anchor=self.anchor,None
                    mode=self.ask('Câble','Mode : access ou trunk','access')
                    if mode:
                        vlans=self.ask('VLAN','VLAN autorisés, séparés par virgule','10')
                        if vlans:
                            try:
                                self.lab.connect(a,name,mode,[int(v) for v in vlans.split(',')])
                                self.clear_simulation()
                            except ValueError as e:
                                messagebox.showerror('Câble',str(e))
                self.draw()
                return
            self.selected,self.link_selected=name,None
            if self.lab.nodes[name].kind=='PC':
                self.source.set(name)
        elif tags and tags[0]=='link':
            self.selected,self.link_selected=None,int(tags[1])
        else:
            self.selected,self.link_selected=None,None
        self.inspect()
        self.draw()

    def drag(self,event):
        if self.mode=='select' and self.selected:
            n=self.lab.nodes[self.selected]
            n.x,n.y=max(60,min(self.canvas.winfo_width()-60,event.x)),max(40,min(self.canvas.winfo_height()-65,event.y))
            self.draw()

    def add(self,kind):
        self.clear_simulation()
        i=1
        while f'{kind}{i}' in self.lab.nodes:
            i+=1
        name=f'{kind}{i}'
        self.lab.add(Node(name,kind,150+20*(i%5),100+90*(i%4)))
        self.selected,self.link_selected=name,None
        self.inspect()
        self.draw()

    def inspect(self):
        self.source_box['values']=[n.name for n in self.lab.nodes.values() if n.kind=='PC']
        if self.source.get() not in self.source_box['values']:
            self.source.set('')
        for child in self.inspector.winfo_children():
            child.destroy()
        self.fields={}
        if self.selected not in self.lab.nodes and self.link_selected is None:
            self.label(self.inspector,'Sélectionner un équipement\nou un lien.',MUTED)
            return
        if self.link_selected is not None:
            l=self.lab.links[self.link_selected]
            self.label(self.inspector,f'{l.a} ↔ {l.b}',ACCENT)
            values=[('Mode',l.mode),('VLAN',','.join(map(str,l.vlans)))]
        else:
            n=self.lab.nodes[self.selected]
            self.label(self.inspector,f'{n.name} / {n.kind}',ACCENT)
            values=([('IPv4/CIDR',n.address),('Passerelle',n.gateway)] if n.kind=='PC' else [('Sous-interfaces',','.join(f'{v}={ip}' for v,ip in n.interfaces.items()))] if n.kind=='Routeur' else [])
        for title,value in values:
            self.label(self.inspector,title)
            var=tk.StringVar(value=value)
            ttk.Entry(self.inspector,textvariable=var,width=25).pack(fill='x',pady=4)
            self.fields[title]=var
        if values:
            ttk.Button(self.inspector,text='Appliquer',command=self.apply).pack(fill='x',pady=10)
        else:
            self.label(self.inspector,'Cliquer sur un câble pour\nconfigurer son mode / VLAN.',MUTED)

    def apply(self):
        try:
            f={k:v.get().strip() for k,v in self.fields.items()}
            if self.link_selected is not None:
                i=self.link_selected
                l=self.lab.links[i]
                # Validate on a separate lab to keep changes atomic.
                from .engine import Lab
                copy=Lab.loads(self.lab.dumps())
                copy.links.pop(i)
                copy.connect(l.a,l.b,f['Mode'],[int(v) for v in f['VLAN'].split(',')])
                updated=copy.links[-1]
                self.lab.links[i]=updated
            else:
                n=self.lab.nodes[self.selected]
                if n.kind=='PC':
                    IPv4Interface(f['IPv4/CIDR'])
                    if f['Passerelle']:
                        IPv4Address(f['Passerelle'])
                    n.address,n.gateway=f['IPv4/CIDR'],f['Passerelle']
                else:
                    interfaces={}
                    for entry in f['Sous-interfaces'].split(',') if f['Sous-interfaces'] else []:
                        v,ip=entry.strip().split('=')
                        if not 1<=int(v)<=4094:
                            raise ValueError('VLAN invalide')
                        IPv4Interface(ip)
                        interfaces[str(int(v))]=ip
                    n.interfaces=interfaces
            self.clear_simulation()
            self.draw()
            self.status.set('Configuration appliquée')
        except (ValueError,KeyError) as e:
            messagebox.showerror('Configuration invalide',str(e))

    def delete(self):
        if self.selected is None and self.link_selected is None:
            return
        self.clear_simulation()
        if self.link_selected is not None:
            self.lab.links.pop(self.link_selected)
        elif self.selected:
            self.lab.links=[l for l in self.lab.links if self.selected not in (l.a,l.b)]
            del self.lab.nodes[self.selected]
        self.selected=self.link_selected=None
        self.inspect()
        self.draw()

    def ping(self):
        self.clear_simulation()
        ok,trace=self.lab.ping(self.source.get(),self.destination.get())
        self.result=ok
        for i,path in enumerate(self.lab.last_paths):
            phase='Aller' if i==0 else 'Retour'
            self.events.insert('', 'end', values=(phase,' → '.join(path)))
            self.hops.extend((a,b,phase) for a,b in zip(path,path[1:]))
        if not ok:
            self.events.insert('', 'end',values=('Échec',trace[-1]))
        self.log('\n'.join(trace))
        if self.hops:
            self.play()
        else:
            self.status.set(('Réussite' if ok else 'Échec')+' : '+trace[-1])
        self.draw()

    def pause(self):
        self.running=False
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer=None

    def play(self):
        if self.running or self.index>=len(self.hops):
            return
        self.running=True
        self.tick()

    def tick(self):
        self.timer=None
        if not self.running:
            return
        self.progress=min(1,self.progress+0.025*self.speed.get())
        a,b,phase=self.hops[self.index]
        self.status.set(f'{phase} · {a} → {b} · {self.index+1}/{len(self.hops)}')
        self.draw()
        if self.progress>=1:
            self.index+=1
            self.progress=0
        if self.index>=len(self.hops):
            self.finish()
        else:
            self.timer=self.root.after(25,self.tick)

    def finish(self):
        self.pause()
        self.status.set('✓ Aller / retour accessibles' if self.result else '✗ Connectivité interrompue • voir diagnostic')
        self.draw()

    def step(self):
        self.pause()
        if self.index<len(self.hops):
            a,b,phase=self.hops[self.index]
            self.log(f'{phase} : {a} → {b}')
            self.index+=1
            self.progress=0
            self.status.set(f'Étape : {b} atteint')
            if self.index==len(self.hops):
                self.finish()
            self.draw()

    def replay(self):
        self.pause()
        self.index,self.progress=0,0
        self.play()

if __name__=='__main__':
    root=tk.Tk()
    App(root)
    root.mainloop()
