"""The workbench's device library: the palette, its search and the projects list. A mixin of ui.ApplianceWindow."""
import time
import tkinter as tk
from tkinter import messagebox
from ..layout import ScrollPanel
from .soft_widgets import SoftCard
from .reference_theme import PANEL, SIDEBAR, TEXT, MUTED
from .workspace_art import draw_device


class LibraryPalette:
    def build_library_palette(self,parent):
        from .native_models import grouped,short_name
        generic={'Routeurs':[('router',None,'Routeur Linux','Routage / 802.1Q','blue')],
                 'Switches':[('switch',None,'Switch Linux','VLAN / ports','blue')],
                 'Pare-feu':[('firewall',None,'Pare-feu Linux','Politique nftables','blue')],
                 'Postes clients':[('host',None,'Poste Linux','Thème bleu','blue'),('host',None,'Poste Linux','Thème rouge','red')],
                 'Serveurs et stockage':[('server',None,'Serveur Linux','Réseau Ethernet','blue')],'Périphériques':[]}
        catalog=[]
        for category,models in grouped():
            entries=list(generic.get(category,[]))
            for model in models:
                kind='server' if model['presentation']=='server' else model['role']
                entries.append((kind,model['id'],model['brand'],short_name(model),'blue'))
            catalog.append((category,entries))
        scroll=ScrollPanel(parent,SIDEBAR)
        scroll.canvas.configure(bd=0,relief='flat')
        scroll.scroll.configure(style='Native.Vertical.TScrollbar')
        scroll.pack(fill='both',expand=True)
        self.library_scroll=scroll
        container=scroll.inner
        self.palette_groups=[]
        for category,entries in catalog:
            group=tk.Frame(container,bg=SIDEBAR)
            group.pack(fill='x')
            tiles=[]
            self.palette_groups.append((group,tiles))
            self.label(group,category,TEXT,8,True).pack(anchor='w',padx=9,pady=(7,2))
            for kind,model,title,subtitle,variant in entries:
                tile=SoftCard(group,SIDEBAR)
                tile.pack(fill='x',padx=7,pady=3)
                icon=tk.Canvas(tile.inner,width=62,height=38,bg=PANEL,highlightthickness=0)
                icon.pack(side='left',padx=(0,4))
                draw_device(icon,kind,31,19,scale=.5,variant=variant)
                caption=tk.Frame(tile.inner,bg=PANEL)
                caption.pack(side='left',fill='x',expand=True)
                # Left-anchored and trimmed: an overflowing label would otherwise lose its first letters.
                for text,colour,size,limit in ((title,TEXT,9,13),(subtitle,MUTED,7,16)):
                    shown=text if len(text)<=limit else text[:limit-1]+'…'
                    self.label(caption,shown,colour,size).configure(anchor='w')
                    caption.winfo_children()[-1].pack(fill='x')
                def bind(widget,r=kind,m=model,card=tile):
                    # Click or drag onto the canvas: the device is added at once; right-click: the full form.
                    widget.bind('<ButtonRelease-1>',lambda event:self.tile_released(event,r,m))
                    widget.bind('<Button-3>',lambda event:self.add_device_dialog(r,model=m))
                    widget.bind('<Enter>',lambda event:card.hover(True))
                    widget.bind('<Leave>',lambda event:card.hover(False))
                    for child in widget.winfo_children():
                        bind(child,r,m,card)
                bind(tile)
                tiles.append((tile,(category+' '+title+' '+subtitle+' '+kind+' '+(model or '')).casefold()))

    def toggle_project_list(self):
        self.project_list_open=not self.project_list_open
        if self.project_list_open:
            self.project_list.pack(fill='both',expand=True,padx=7)
        else:self.project_list.pack_forget()
        self.project_toggle.configure(text=('▾' if self.project_list_open else '▸')+' Équipements du projet')

    def model_mode_refusal(self,action):
        """On Windows, macOS, or a Linux without KVM for a micro-VM lab: say once why the lab cannot start and what still
        works (the CLIs, ping and simulation on the model), instead of failing in a terminal. True when refused."""
        from .platform_support import MODEL_MODE,blocker
        try:
            spec=self.manifest() if action=='start' else None
        except (ValueError,TypeError,KeyError):
            spec=None
        why=blocker(spec)
        if why is None:
            return False
        self.note.set('Mode modèle : CLI, ping et ✉ Simulation fonctionnent ; démarrer les micro-VM demande Linux avec KVM.')
        messagebox.showinfo('Mode modèle',MODEL_MODE.format(why=why),parent=self.window)
        return True

    def record_event(self,action,result):
        tag='failed' if 'failed' in result or 'blocked' in result else 'passed' if 'passed' in result else ''
        if self.activity.exists('empty'):
            self.activity.delete('empty')
        self.activity.insert('','end',values=(time.strftime('%H:%M:%S'),action,result),tags=(tag,))
        children=self.activity.get_children()
        if len(children)>200:
            self.activity.delete(*children[:-200])
        self.activity.see(self.activity.get_children()[-1])

    def filter_library(self,*args):
        if not hasattr(self,'graph'):
            return
        self.refresh_search_hint()
        query=self.search.get().strip().casefold()
        for node in self.graph['nodes']:
            name=node['name']
            if not query or query in (name+' '+node['role']+' '+node['runtime']).casefold():
                self.library.reattach(name,'','end')
            else:self.library.detach(name)
        for group,tiles in self.palette_groups:
            group.pack_forget()
            for tile,words in tiles:
                tile.pack_forget()
            matches=[tile for tile,words in tiles if not query or query in words]
            if matches:
                group.pack(fill='x')
                for tile in matches:
                    tile.pack(fill='x',padx=7,pady=1)
        if query and self.library.get_children() and not self.project_list_open:
            self.toggle_project_list()

    def library_selected(self,event=None):
        selected=self.library.selection()
        if selected and self.nodes.selection()!=selected:
            self.choose_node(selected[0])
