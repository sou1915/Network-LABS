import tkinter as tk
from tkinter import ttk, simpledialog, filedialog, messagebox
from .engine import Lab, Node, demo

class App:
    def __init__(self, root):
        self.root, self.lab, self.selected = root, demo(), None
        root.title('Network LABS • Prototype Linux')
        root.geometry('1100x760')
        bar = ttk.Frame(root, padding=8)
        bar.pack(fill='x')
        for kind in ('PC', 'Switch', 'Routeur'):
            ttk.Button(bar, text='+ ' + kind, command=lambda k=kind: self.add(k)).pack(side='left', padx=3)
        for text, command in [('Relier', self.connect), ('Configurer', self.configure), ('Ping', self.ping), ('Ouvrir', self.load), ('Sauvegarder', self.save), ('Démo', self.reset)]:
            ttk.Button(bar, text=text, command=command).pack(side='left', padx=3)
        ttk.Label(root, text='Sélection : clic • Déplacement : glisser • Configuration : double-clic • Simulation de connectivité simplifiée', padding=8).pack(fill='x')
        self.canvas = tk.Canvas(root, bg='#101c30', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Button-1>', self.select)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<Double-Button-1>', lambda e: self.configure())
        self.output = tk.Text(root, height=8, bg='#0b1322', fg='#b6e3ce', padx=12, pady=12)
        self.output.pack(fill='x')
        self.log('Démo : sélectionner PC1 puis Ping vers 192.168.20.10.\nPrototype : pas encore de CLI, DHCP, ARP/MAC, STP ou paquets animés.')
        self.draw()

    def log(self, text):
        self.output.insert('end', text + '\n')
        self.output.see('end')

    def ask(self, title, prompt, initial=''):
        return simpledialog.askstring(title, prompt, initialvalue=initial, parent=self.root)

    def draw(self):
        self.canvas.delete('all')
        for l in self.lab.links:
            a, b = self.lab.nodes[l.a], self.lab.nodes[l.b]
            self.canvas.create_line(a.x, a.y, b.x, b.y, fill='#6485ac', width=3)
            self.canvas.create_text((a.x+b.x)/2, (a.y+b.y)/2-15, text=f'{l.mode} {l.vlans}', fill='#bccde4')
        for n in self.lab.nodes.values():
            color = {'PC': '#256d9d', 'Switch': '#177a70', 'Routeur': '#7050a6'}[n.kind]
            tags = ('node', n.name)
            self.canvas.create_rectangle(n.x-55, n.y-30, n.x+55, n.y+30, fill=color, outline='#ffce66' if n.name == self.selected else '#a5bdd7', width=2, tags=tags)
            self.canvas.create_text(n.x, n.y, text=f'{n.name}\n{n.kind}', fill='white', tags=tags)
            self.canvas.create_text(n.x, n.y+47, text=n.address, fill='#bccde4', tags=tags)

    def select(self, event):
        items = self.canvas.find_withtag('current')
        tags = self.canvas.gettags(items[0]) if items else ()
        self.selected = tags[1] if 'node' in tags else None
        self.draw()

    def drag(self, event):
        if self.selected:
            n = self.lab.nodes[self.selected]
            n.x, n.y = max(60,event.x), max(35,event.y)
            self.draw()

    def add(self, kind):
        name = self.ask('Équipement', 'Nom unique :')
        if name:
            try:
                self.lab.add(Node(name, kind))
                self.selected = name
                self.draw()
            except ValueError as e:
                messagebox.showerror('Erreur', str(e))

    def connect(self):
        text = self.ask('Câble', 'Format : PC1 SW1 access 10\nou : SW1 R1 trunk 10,20')
        if text is None:
            return
        try:
            a,b,mode,vlans = text.split()
            self.lab.connect(a,b,mode,[int(v) for v in vlans.split(',')])
            self.draw()
        except (ValueError, KeyError) as e:
            messagebox.showerror('Câble invalide', str(e))

    def configure(self):
        if not self.selected:
            return
        n = self.lab.nodes[self.selected]
        if n.kind == 'PC':
            address = self.ask(n.name, 'IPv4/CIDR (ex. 192.168.10.10/24)', n.address)
            if address is None:
                return
            gateway = self.ask(n.name, 'Passerelle IPv4', n.gateway)
            if gateway is None:
                return
            try:
                from ipaddress import IPv4Interface, IPv4Address
                IPv4Interface(address)
                if gateway:
                    IPv4Address(gateway)
                n.address, n.gateway = address, gateway
            except ValueError as e:
                messagebox.showerror('Adresse invalide', str(e))
        elif n.kind == 'Routeur':
            text = self.ask(n.name, 'Sous-interfaces VLAN=IPv4/CIDR séparées par virgule', ','.join(f'{v}={ip}' for v,ip in n.interfaces.items()))
            if text is None:
                return
            try:
                from ipaddress import IPv4Interface
                result = {}
                for entry in text.split(',') if text.strip() else []:
                    v, ip = entry.strip().split('=')
                    if not 1 <= int(v) <= 4094:
                        raise ValueError('VLAN invalide')
                    IPv4Interface(ip)
                    result[str(int(v))] = ip
                n.interfaces = result
            except ValueError as e:
                messagebox.showerror('Sous-interface invalide', str(e))
        else:
            self.log('Switch : VLAN access/trunk configurés sur les câbles. Pour modifier un câble : éditer le projet JSON puis le rouvrir.')
        self.draw()

    def ping(self):
        if not self.selected:
            return
        destination = self.ask('Ping simulé', 'IPv4 du PC destination :', '192.168.20.10')
        if destination:
            ok, trace = self.lab.ping(self.selected, destination)
            self.log(('✓ ' if ok else '✗ ') + '\n'.join(trace))

    def save(self):
        path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('Projet Network LABS', '*.json')])
        if path:
            try:
                with open(path, 'w') as f:
                    f.write(self.lab.dumps())
            except OSError as e:
                messagebox.showerror('Sauvegarde', str(e))

    def load(self):
        path = filedialog.askopenfilename(filetypes=[('Projet Network LABS', '*.json')])
        if path:
            try:
                with open(path) as f:
                    lab = Lab.loads(f.read())
                self.lab, self.selected = lab, None
                self.draw()
            except (OSError, ValueError, KeyError, TypeError) as e:
                messagebox.showerror('Projet invalide', str(e))

    def reset(self):
        if messagebox.askyesno('Démo', 'Remplacer la topologie actuelle par la démo ?'):
            self.lab, self.selected = demo(), None
            self.draw()

if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
