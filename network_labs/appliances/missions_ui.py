"""Missions, troubleshooting labs and generated scenarios: the Scénarios tab of the native workbench.

MissionsPanel is mixed into ApplianceWindow (ui.py), which provides the lab draft, the topology canvas and the
privileged bridge (launch). Everything here reads or replaces the draft and grades it; nothing runs as root.
"""
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from ..layout import ScrollPanel
from .reference_theme import BG,TEXT,MUTED,BLUE
from .workspace_art import access_vlans
from .ui_bridge import public_topology


class MissionsPanel:
    def build_missions(self,parent):
        """Guided labs: pick a mission, load its lab, configure it anywhere in the app, then check it."""
        from .missions import MISSIONS
        self.mission_current=MISSIONS[0]['id']
        self.mission_real={}
        self.mission_cards={}
        import os
        from . import progress
        saved=progress.load()['paths']
        self.mission_kernel=tk.StringVar(value=saved.get('kernel') or os.environ.get('NETWORK_LABS_MICROVM_KERNEL',''))
        self.mission_disk=tk.StringVar(value=saved.get('disk') or os.environ.get('NETWORK_LABS_MICROVM_DISK',''))
        self.mission_badges={}
        self.mission_progress=tk.StringVar()
        column=tk.Frame(parent,bg=BG,width=262)
        column.pack(side='left',fill='y',padx=(10,6),pady=10)
        column.pack_propagate(False)
        listing=ScrollPanel(column,BG)  # missions and panne labs scroll; the campus button stays below
        listing.canvas.configure(bd=0,relief='flat')
        listing.scroll.configure(style='Native.Vertical.TScrollbar')
        side=listing.inner
        self.label(side,'Missions guidées',TEXT,13,True).pack(anchor='w',pady=(4,2))
        intro='Chaque mission part d’un lab réel ; la note vient de votre configuration et de pings réels.'
        self.label(side,intro,MUTED,8).pack(anchor='w',pady=(0,4))
        side.winfo_children()[-1].configure(wraplength=235)
        tk.Label(side,textvariable=self.mission_progress,bg=BG,fg='#168942',font=(self.font,9,'bold'),anchor='w').pack(fill='x',pady=(0,6))
        for item in MISSIONS:
            card=tk.Frame(side,bg='white',highlightthickness=2,highlightbackground='#dfe7ef',cursor='hand2')
            card.pack(fill='x',pady=4)
            title=tk.Label(card,text=item['title'],bg='white',fg=TEXT,font=(self.font,10,'bold'),anchor='w',justify='left',wraplength=215)
            title.pack(fill='x',padx=10,pady=(8,0))
            meta=tk.Label(card,text=f"{item['level']} · {item['kind']}\n{item['vendors']}",bg='white',fg=MUTED,font=(self.font,8),
                          anchor='w',
                          justify='left')
            meta.pack(fill='x',padx=10,pady=(2,8))
            for widget in (card,title,meta):
                widget.bind('<Button-1>',lambda event,m=item['id']:self.select_mission(m))
            self.mission_cards[item['id']]=card
            self.mission_badges[item['id']]=tk.Label(card,bg='white',font=(self.font,8,'bold'),anchor='w')
            self.mission_badges[item['id']].pack(fill='x',padx=10,pady=(0,6))  # empty until there is progress
        from .faults import LABS
        self.panne=None
        self.label(side,'Mode panne',TEXT,11,True).pack(anchor='w',pady=(12,2))
        self.label(side,'Un lab qui marche, une panne cachée tirée au hasard : trouver et réparer.',MUTED,8).pack(anchor='w',pady=(0,4))
        side.winfo_children()[-1].configure(wraplength=235)
        for key,item in LABS.items():
            card=tk.Frame(side,bg='#fff8ef',highlightthickness=2,highlightbackground='#f1dfc6',cursor='hand2')
            card.pack(fill='x',pady=3)
            title=tk.Label(card,text='🛠 '+item['title'],bg='#fff8ef',fg=TEXT,font=(self.font,10,'bold'),anchor='w')
            title.pack(fill='x',padx=10,pady=(6,0))
            meta=tk.Label(card,text=item['vendors'],bg='#fff8ef',fg=MUTED,font=(self.font,8),anchor='w')
            meta.pack(fill='x',padx=10,pady=(0,6))
            for widget in (card,title,meta):
                widget.bind('<Button-1>',lambda event,m='panne-'+key:self.select_mission(m))
            self.mission_cards['panne-'+key]=card
            self.mission_badges['panne-'+key]=tk.Label(card,bg='#fff8ef',font=(self.font,8,'bold'),anchor='w')
            self.mission_badges['panne-'+key].pack(fill='x',padx=10,pady=(0,6))  # empty until there is progress
        self.build_scenario_card(side)
        self.refresh_mission_badges()

        campus=ttk.Button(column,text='Autre scénario : campus entreprise…',command=self.new_campus,style='Native.TButton')
        campus.pack(fill='x',side='bottom',pady=6)
        listing.pack(fill='both',expand=True)
        frame=tk.Frame(parent,bg='white',highlightthickness=1,highlightbackground='#dfe7ef')
        frame.pack(side='left',fill='both',expand=True,padx=(0,10),pady=10)
        scroll=ScrollPanel(frame,'white')
        scroll.canvas.configure(bd=0,relief='flat')
        scroll.scroll.configure(style='Native.Vertical.TScrollbar')
        scroll.pack(fill='both',expand=True)
        detail=self.mission_detail=scroll.inner
        self.mission_title=tk.StringVar()
        self.mission_meta=tk.StringVar()
        self.mission_story=tk.StringVar()
        self.mission_score=tk.StringVar()
        self.mission_status=tk.StringVar()
        title=tk.Label(detail,textvariable=self.mission_title,bg='white',fg=TEXT,font=(self.font,15,'bold'),anchor='w',justify='left')
        title.pack(fill='x',padx=18,pady=(16,0))
        title.bind('<Configure>',lambda event:title.configure(wraplength=max(200,event.width-6)))
        meta=tk.Label(detail,textvariable=self.mission_meta,bg='white',fg=BLUE,font=(self.font,9),anchor='w',justify='left')
        meta.pack(fill='x',padx=18)
        meta.bind('<Configure>',lambda event:meta.configure(wraplength=max(200,event.width-6)))
        story=tk.Label(detail,textvariable=self.mission_story,bg='white',fg=TEXT,font=(self.font,10),anchor='w',justify='left')
        story.pack(fill='x',padx=18,pady=(10,6))
        story.bind('<Configure>',lambda event:story.configure(wraplength=max(200,event.width-6)))
        paths=tk.Frame(detail,bg='white')
        paths.pack(fill='x',padx=18,pady=4)
        paths.columnconfigure(1,weight=1)
        for row,(text,variable) in enumerate((('Noyau micro-VM',self.mission_kernel),('Disque micro-VM',self.mission_disk))):
            self.label(paths,text,MUTED,8).grid(row=row,column=0,sticky='w',padx=(0,8),pady=2)
            ttk.Entry(paths,textvariable=variable,style='Native.TEntry').grid(row=row,column=1,sticky='ew',pady=2)
        self.setup_button=ttk.Button(paths,text='🛠 Préparer cet ordinateur (téléchargements vérifiés, disque complet)',
                                     style='Native.TButton',command=self.prepare_computer)
        self.setup_button.grid(row=2,column=0,columnspan=2,sticky='ew',pady=(4,0))
        actions=tk.Frame(detail,bg='white')
        actions.pack(fill='x',padx=18,pady=8)
        actions.columnconfigure((0,1),weight=1,uniform='mission')
        for index,(text,command,style) in enumerate((('Charger la mission',self.load_mission,'Native.Primary.TButton'),
                                                    ('Vérifier la configuration',self.check_mission,'Native.TButton'),
                                                    ('Tester sur le lab (pings réels)',self.test_mission,'Native.TButton'),
                                                    ('Indice',self.mission_hint,'Native.TButton'))):
            button=ttk.Button(actions,text=text,command=command,style=style)
            button.grid(row=index//2,column=index%2,sticky='ew',padx=3,pady=3)
        self.mission_help_button=button
        self.mission_help=tk.StringVar()
        self.mission_help_box=tk.Label(detail,textvariable=self.mission_help,bg='#f2f0ff',fg='#3d2c7a',font=(self.font,9),anchor='w',
                                       justify='left',padx=10,pady=6)
        self.mission_help_box.bind('<Configure>',lambda event:self.mission_help_box.configure(wraplength=max(200,event.width-24)))
        head=tk.Frame(detail,bg='white')
        self.mission_help_anchor=head
        head.pack(fill='x',padx=18,pady=(8,2))
        tk.Label(head,text='Objectifs',bg='white',fg=TEXT,font=(self.font,11,'bold')).pack(side='left')
        tk.Label(head,textvariable=self.mission_score,bg='white',fg=BLUE,font=(self.font,11,'bold')).pack(side='right')
        self.mission_bar=tk.Canvas(detail,height=8,bg='white',highlightthickness=0)
        self.mission_bar.pack(fill='x',padx=18,pady=(0,6))
        self.mission_rows=tk.Frame(detail,bg='white')
        self.mission_rows.pack(fill='both',expand=True,padx=18)
        status=tk.Label(detail,textvariable=self.mission_status,bg='white',fg=MUTED,font=(self.font,9),anchor='w',justify='left')
        status.pack(fill='x',padx=18,pady=(4,14))
        status.bind('<Configure>',lambda event:status.configure(wraplength=max(200,event.width-6)))
        self.mission_hints_shown=0
        self.select_mission(self.mission_current)

    def select_mission(self,mission_id):
        from .missions import mission
        if mission_id.startswith('panne-'):
            return self.select_panne(mission_id)
        if mission_id.startswith('scenario-'):
            return self.select_scenario(int(mission_id[len('scenario-'):]))
        if mission_id.startswith('gen-') and self.scenario and self.scenario['id']==mission_id:
            return self.show_scenario(self.scenario)
        self.mission_help_button.configure(text='Indice')
        self.mission_help_box.pack_forget()
        item=mission(mission_id)
        if mission_id!=self.mission_current:
            self.mission_real={}
            self.mission_hints_shown=0
        self.mission_current=mission_id
        for key,card in self.mission_cards.items():
            card.configure(highlightbackground=BLUE if key==mission_id else '#f1dfc6' if key.startswith('panne-') else '#dfe7ef')
        self.mission_title.set(item['title'])
        self.mission_meta.set(f"{item['level']} · {item['kind']} · {item['vendors']}")
        self.mission_story.set(item['story'])
        self.show_mission_results()

    def select_panne(self,mission_id):
        from .faults import LABS
        key=mission_id[len('panne-'):]
        if mission_id!=self.mission_current:
            self.mission_real={}
            self.mission_hints_shown=0
        self.mission_current=mission_id
        for name,card in self.mission_cards.items():
            card.configure(highlightbackground=BLUE if name==mission_id else '#f1dfc6' if name.startswith('panne-') else '#dfe7ef')
        self.mission_help_button.configure(text='Indice')
        self.mission_help_box.pack_forget()
        self.mission_title.set('Panne mystère · '+LABS[key]['title'])
        self.mission_meta.set('Dépannage · '+LABS[key]['vendors'])
        loaded=self.panne and self.panne['lab']==key and self.mission_lab_loaded()
        self.mission_story.set(('Ticket utilisateur : « '+self.panne['symptom']+' » Trouver la cause avec les commandes show, '
                                'le relevé de l’état réel et les pings, puis la corriger.') if loaded else
                               'Une panne tirée au hasard sera introduite dans un lab qui fonctionne. Seul le symptôme est donné.')
        self.show_mission_results()

    def build_scenario_card(self,side):
        """The generated scenarios: a number (or a random one), no hint unless asked."""
        from .scenarios import COUNT
        self.scenario=None
        self.scenario_help=[]
        self.scenario_number=tk.IntVar(value=1)
        card=tk.Frame(side,bg='#f2f0ff',highlightthickness=2,highlightbackground='#d9d2f5')
        card.pack(fill='x',pady=(8,3))
        tk.Label(card,text='🎲 Scénarios générés',bg='#f2f0ff',fg=TEXT,font=(self.font,10,'bold'),
                 anchor='w').pack(fill='x',padx=10,pady=(6,0))
        note=tk.Label(card,text=f'Un réseau, une panne cachée, aucun indice : l’aide se demande pas à pas. Catalogue de {COUNT} '
                                'numéros, ou un scénario neuf jamais vu.',bg='#f2f0ff',fg=MUTED,font=(self.font,8),anchor='w',
                      justify='left',wraplength=215)
        note.pack(fill='x',padx=10)
        grid=tk.Frame(card,bg='#f2f0ff')
        grid.pack(fill='x',padx=10,pady=6)
        grid.columnconfigure((0,1),weight=1,uniform='scenario')
        ttk.Spinbox(grid,from_=1,to=COUNT,textvariable=self.scenario_number,width=6).grid(row=0,column=0,sticky='ew',padx=(0,3))
        ttk.Button(grid,text='Ouvrir le n°',style='Native.TButton',
                   command=lambda:self.select_scenario(self.scenario_number.get())).grid(row=0,column=1,sticky='ew')
        ttk.Button(grid,text='Au hasard',style='Native.TButton',command=self.random_scenario).grid(row=1,column=0,sticky='ew',
                                                                                                padx=(0,3),pady=(3,0))
        ttk.Button(grid,text='✨ Nouveau',style='Native.Primary.TButton',command=self.new_unique_scenario).grid(
            row=1,column=1,sticky='ew',pady=(3,0))
        ttk.Button(grid,text='★ Garder ce scénario',style='Native.TButton',command=self.keep_scenario).grid(
            row=2,column=0,columnspan=2,sticky='ew',pady=(3,0))
        tk.Label(card,text='Mes scénarios gardés',bg='#f2f0ff',fg=MUTED,font=(self.font,8,'bold'),anchor='w').pack(fill='x',padx=10)
        kept=tk.Frame(card,bg='#f2f0ff')
        kept.pack(fill='x',padx=10,pady=(2,4))
        kept.columnconfigure(0,weight=1)
        self.saved_choice=tk.StringVar()
        self.saved_box=ttk.Combobox(kept,textvariable=self.saved_choice,state='readonly',width=22)
        self.saved_box.grid(row=0,column=0,columnspan=2,sticky='ew')
        ttk.Button(kept,text='Ouvrir',style='Native.TButton',command=self.open_saved_scenario).grid(row=1,column=0,sticky='ew',
                                                                                                    pady=(3,0),padx=(0,3))
        ttk.Button(kept,text='Supprimer',style='Native.TButton',command=self.delete_saved_scenario).grid(row=1,column=1,sticky='ew',
                                                                                                         pady=(3,0))
        self.refresh_saved_scenarios()
        self.scenario_solved=tk.StringVar()
        tk.Label(card,textvariable=self.scenario_solved,bg='#f2f0ff',fg='#168942',font=(self.font,8,'bold'),
                 anchor='w').pack(fill='x',padx=10,pady=(0,6))
        self.mission_cards['scenarios']=card

    def show_scenario_help(self):
        """The help asked for so far, in a box under the buttons (hidden while there is none)."""
        text='\n'.join(f'Aide {i} : {line}' for i,line in enumerate(self.scenario_help,1))
        self.mission_help.set(text)
        if text and self.is_scenario():
            self.mission_help_box.pack(fill='x',padx=18,pady=(0,6),before=self.mission_help_anchor)
        else:
            self.mission_help_box.pack_forget()

    def random_scenario(self):
        import random
        from . import progress
        from .scenarios import COUNT
        solved={k for k,v in progress.load()['missions'].items() if k.startswith('scenario-') and isinstance(v,dict) and v.get('solved')}
        left=[n for n in range(1,COUNT+1) if f'scenario-{n:04d}' not in solved] or list(range(1,COUNT+1))
        number=random.choice(left)
        self.scenario_number.set(number)
        self.select_scenario(number)

    def select_scenario(self,number):
        from .scenarios import COUNT,scenario
        try:
            number=int(number)
        except (TypeError,ValueError,tk.TclError):
            number=1
        number=min(COUNT,max(1,number))
        mission_id=f'scenario-{number:04d}'
        if mission_id!=self.mission_current:
            self.mission_real={}
            self.mission_hints_shown=0
            self.scenario_help=[]
        self.mission_current=mission_id
        self.scenario_number.set(number)
        for key,card in self.mission_cards.items():
            card.configure(highlightbackground=BLUE if key=='scenarios' else '#f1dfc6' if key.startswith('panne-') else '#dfe7ef')
        loaded=self.scenario and self.scenario['id']==mission_id and self.mission_lab_loaded()
        self.show_scenario(self.scenario if loaded else scenario(number),loaded)

    def is_scenario(self):
        return self.mission_current.startswith(('scenario-','gen-'))

    def show_scenario(self,item,loaded=True):
        """Title, ticket and requirements of a catalogue, generated or saved scenario."""
        from .scenarios import FAMILY_TITLES,HELP_STEPS
        for key,card in self.mission_cards.items():
            card.configure(highlightbackground=BLUE if key=='scenarios' else '#f1dfc6' if key.startswith('panne-') else '#dfe7ef')
        needs={'ospf':'image micro-VM avec BIRD (--with-routing)','802.1q':'noyau Network LABS (802.1Q)',
               'firewall':'image micro-VM avec iptables (--with-firewall)'}
        name=f'n° {item["number"]}' if item.get('number') else item.get('code') or item.get('key') or item['id']
        self.mission_title.set(f'Scénario {name} · {FAMILY_TITLES[item["family"]]}')
        kept=' · ★ gardé' if (item.get('key') or item.get('code') or item['id']) in {r['key'] for r in self.saved_records} else ''
        self.mission_meta.set(f'Dépannage · {item["detail"]} · {len(item["spec"]["nodes"])} équipements{kept}')
        required=(' Nécessite : '+', '.join(needs[n] for n in item['needs'])+'.') if item['needs'] else ''
        self.mission_story.set(('Ticket utilisateur : '+item['ticket']+' Aucun indice : enquêter avec show, ping, Suivre un paquet et '
                                'le relevé de l’état réel, puis réparer.'+required) if loaded else
                               'Un réseau généré pour ce numéro, avec une panne cachée. Charger le scénario pour lire le ticket.'+required)
        self.mission_help_button.configure(text=f'Un peu d’aide ({self.mission_hints_shown}/{HELP_STEPS})')
        self.show_scenario_help()
        self.show_mission_results()

    def prepare_computer(self):
        """First launch, from the workbench: the same checks, verified downloads and disk build as « setup »,
        in the background; no privilege. The paths are filled in and the checklist shown."""
        import threading
        from .setup import prepare
        if getattr(self,'setup_thread',None) and self.setup_thread.is_alive():
            return False
        self.setup_button.configure(state='disabled')
        self.mission_status.set('Préparation en cours : vérifications, téléchargements vérifiés, construction du disque…')
        holder={}
        kernel=self.mission_kernel.get().strip() or None  # Tk is read here: the worker thread never touches widgets
        def work():
            try:
                holder['result']=prepare(download=True,kernel=kernel)
            except Exception as error:  # reported in the panel, never lost in a thread
                holder['error']=str(error)
        self.setup_thread=threading.Thread(target=work,daemon=True)
        self.setup_thread.start()
        def finish():
            if self.setup_thread.is_alive():
                self.window.after(200,finish)
                return
            self.setup_button.configure(state='normal')
            self.show_setup(holder)
        self.window.after(200,finish)
        return True

    def show_setup(self,holder):
        if 'error' in holder:
            self.mission_status.set('Préparation interrompue : '+holder['error'])
            return
        result=holder['result']
        if Path(result['kernel']).is_file():
            self.mission_kernel.set(result['kernel'])
        if Path(result['disk']).is_file():
            self.mission_disk.set(result['disk'])
        lines=[('✔ ' if item['ok'] else '✖ ')+item['title']+(' → '+item['fix'] if item['fix'] else '') for item in result['steps']]
        self.mission_help.set('\n'.join(lines))
        self.mission_help_box.pack(fill='x',padx=18,pady=(0,6),before=self.mission_help_anchor)
        self.mission_status.set('Prêt : charger une mission ou un scénario.' if result['ready'] else
                                'Presque prêt : suivre les → (copier la commande dans un terminal), puis Préparer à nouveau.')
        self.record_event('setup','Prêt' if result['ready'] else 'Préparation incomplète')

    def scenario_paths(self):
        kernel,disk=self.mission_kernel.get().strip(),self.mission_disk.get().strip()
        if not kernel or not disk:
            self.mission_status.set('Indiquer le noyau et le disque des micro-VM (les mêmes que pour un lab micro-VM).')
            return None
        from . import progress
        progress.remember_paths(kernel,disk)
        return kernel,disk

    def open_scenario(self,item):
        """Load ITEM (catalogue, newly generated or saved) as the lab, in a tree layout, and remember it was seen."""
        from . import progress
        from .scenarios import fingerprint
        from .workspace_art import tree_layout
        if self.pending:
            return False
        self.scenario=item
        self.mission_current=item['id']
        self.mission_real={}
        self.mission_hints_shown=0
        self.scenario_help=[]
        progress.remember_seen(fingerprint(item))
        self.load_spec(item['spec'])
        graph=public_topology(item['spec'])
        self.positions=tree_layout(graph,access_vlans(graph,item['spec']))  # sites side by side, LANs under their router
        widest=max(x for x,_ in self.positions.values())+90
        self.zoom=max(.65,min(1.,max(600,self.canvas.winfo_width())/widest))  # the whole network in view
        self.draw(graph)
        self.show_scenario(item)
        self.mission_status.set('Scénario chargé. Enquêter, réparer, puis vérifier.')
        self.record_event('mission','Scénario chargé : '+item['id'])
        return True

    def new_unique_scenario(self):
        """A network and a fault this student has never been given."""
        from . import progress
        from .scenarios import unique
        paths=self.scenario_paths()
        if paths is None:
            return False
        try:
            item=unique(*paths,seen=progress.seen())
        except ValueError as error:
            self.mission_status.set(str(error))
            return False
        self.tabs.select(self.missions_tab)
        return self.open_scenario(item)

    def keep_scenario(self):
        from .scenarios import save
        if not (self.is_scenario() and self.scenario and self.scenario['id']==self.mission_current):
            self.mission_status.set('Charger d’abord un scénario à garder.')
            return None
        key=save(self.scenario)
        self.scenario['key']=key
        self.refresh_saved_scenarios()
        self.show_scenario(self.scenario,self.mission_lab_loaded())
        self.mission_status.set(f'Scénario gardé : {key}. Il revient à l’identique depuis « Mes scénarios gardés ».')
        return key

    def refresh_saved_scenarios(self):
        from .scenarios import saved
        self.saved_records=saved()
        self.saved_box.configure(values=[f'{r["key"]} · {r["title"]} · {r["saved"]}' for r in self.saved_records])
        if not self.saved_records:
            self.saved_choice.set('')
        elif not self.saved_choice.get():
            self.saved_box.current(0)

    def chosen_saved(self):
        choice=self.saved_choice.get().split(' · ')[0]
        if not choice:
            self.mission_status.set('Aucun scénario gardé choisi.')
        return choice or None

    def open_saved_scenario(self):
        from .scenarios import load_saved
        key=self.chosen_saved()
        paths=self.scenario_paths() if key else None
        if paths is None:
            return False
        try:
            item=load_saved(key,*paths)
        except (ValueError,KeyError) as error:
            self.mission_status.set(str(error))
            return False
        item['key']=key
        self.tabs.select(self.missions_tab)
        return self.open_scenario(item)

    def delete_saved_scenario(self):
        from .scenarios import delete_saved
        key=self.chosen_saved()
        if key:
            delete_saved(key)
            self.saved_choice.set('')
            self.refresh_saved_scenarios()
            self.mission_status.set(f'Scénario {key} retiré de la liste.')

    def mission_lab_loaded(self):
        from .missions import mission
        if not hasattr(self,'editor'):
            return False  # called while the window is still being built
        try:
            if self.mission_current.startswith('gen-') or (self.is_scenario() and self.scenario and self.scenario.get('key')):
                return bool(self.scenario) and self.manifest()['name']==self.scenario['spec']['name']
            return self.manifest()['name']==mission(self.mission_current)['lab']
        except (ValueError,TypeError,KeyError):
            return False

    def load_mission(self):
        from .missions import mission
        if self.pending:
            return False
        kernel,disk=self.mission_kernel.get().strip(),self.mission_disk.get().strip()
        if not kernel or not disk:
            self.mission_status.set('Indiquer le noyau et le disque des micro-VM (les mêmes que pour un lab micro-VM).')
            return False
        try:
            from . import progress
            progress.remember_paths(kernel,disk)
            if self.mission_current.startswith('panne-'):
                from .faults import create
                self.panne=create(self.mission_current[len('panne-'):],kernel,disk)
                self.load_spec(self.panne['spec'])
            elif self.is_scenario():
                from .scenarios import load_saved,scenario,unique
                current=self.scenario if self.scenario and self.scenario['id']==self.mission_current else None
                if current and current.get('key'):
                    item=dict(load_saved(current['key'],kernel,disk),key=current['key'])  # back to the saved start
                elif current and current.get('code'):
                    item=unique(kernel,disk,seed=current['code'])
                else:
                    item=scenario(int(self.mission_current[len('scenario-'):]),kernel,disk)
                return self.open_scenario(item)
            else:
                self.load_spec(mission(self.mission_current)['build'](kernel,disk))
        except (ValueError,TypeError,KeyError) as error:
            self.mission_status.set(str(error))
            return False
        self.mission_real={}
        self.mission_hints_shown=0
        self.scenario_help=[]
        if self.mission_current.startswith('panne-'):
            self.select_panne(self.mission_current)
        self.show_mission_results()
        self.mission_status.set('Lab de la mission chargé. Configurer les équipements (GUI, CLI, Gestion web), puis vérifier.')
        self.record_event('mission','Mission chargée : '+self.mission_current)
        return True

    def check_mission(self):
        if not self.mission_lab_loaded():
            self.mission_status.set('Charger d’abord le lab de cette mission.')
            return False
        self.record_mission(self.show_mission_results())
        return True

    def record_mission(self,result):
        """Keep the student's best result for the current mission, then refresh the badges."""
        from . import progress
        if result and result.get('total'):
            progress.record(self.mission_current,result['passed'],result['total'],self.mission_hints_shown,result['solved'])
        self.refresh_mission_badges()

    def refresh_mission_badges(self):
        from . import progress
        saved=progress.load()['missions']
        solved=0
        for key,badge in self.mission_badges.items():
            entry=saved.get(key) if isinstance(saved.get(key),dict) else None
            if entry and entry.get('solved'):
                solved+=1
                hints=int(entry.get('hints',0))
                badge.configure(text='✔ Réussie'+(f' · {hints} indice'+('s' if hints>1 else '') if hints else ''),fg='#168942')
            elif entry:
                badge.configure(text=f"{entry.get('best',0)}/{entry.get('total','?')}",fg='#b7791f')
            else:
                badge.configure(text='')
        self.mission_progress.set(f'Progression : {solved} / {len(self.mission_badges)} réussies')
        if hasattr(self,'scenario_solved'):
            count=sum(1 for k,v in saved.items() if k.startswith(('scenario-','gen-')) and isinstance(v,dict) and v.get('solved'))
            self.scenario_solved.set(f'{count} scénario{"s" if count>1 else ""} réussi{"s" if count>1 else ""}' if count else '')

    def test_mission(self):
        if not self.mission_lab_loaded():
            self.mission_status.set('Charger d’abord le lab de cette mission.')
            return False
        spec=self.manifest()
        running=all(self.states.get(n['name'],{}).get('status')=='running' for n in spec['nodes'])
        if self.view_lab!=spec['name'] or not self.states or not running:
            self.mission_status.set('Démarrer le lab de la mission (Enregistrer, puis Démarrer) avant les pings réels.')
            return False
        self.mission_status.set('Pings réels en cours : confirmer avec sudo dans le terminal.')
        return self.launch('mission')

    def mission_hint(self):
        from .missions import mission
        if self.is_scenario():
            from .scenarios import HELP_STEPS,help_step
            if not (self.scenario and self.scenario['id']==self.mission_current and self.mission_lab_loaded()):
                self.mission_status.set('Charger d’abord le scénario.')
                return
            self.mission_hints_shown=min(HELP_STEPS,self.mission_hints_shown+1)
            self.scenario_help.append(help_step(self.manifest(),self.scenario,self.mission_hints_shown))
            self.show_scenario_help()
            self.mission_help_button.configure(text=f'Un peu d’aide ({self.mission_hints_shown}/{HELP_STEPS})')
            return
        if self.mission_current.startswith('panne-'):
            if not (self.panne and self.mission_lab_loaded()):
                self.mission_status.set('Charger d’abord une panne.')
                return
            first=('Démarrer le lab, puis sur chaque routeur lire ses voisins OSPF (show ip ospf neighbor, show ospf neighbor, '
                   'display ospf peer brief) et ses routes.' if self.panne['lab']=='ospf' else
                   'Démarrer le lab, puis comparer chaque équipement à son projet (Gestion web › Relever l’état réel) '
                   'et lire show ip route / show vlan brief.')
            hints=[first,'Solution : '+self.panne['answer']]
        else:
            hints=mission(self.mission_current)['hints']
        self.mission_hints_shown=min(len(hints),self.mission_hints_shown+1)
        self.mission_status.set('Indice : '+' · '.join(hints[:self.mission_hints_shown]))

    def show_mission_results(self):
        from .missions import REAL_KINDS,grade,mission
        for child in self.mission_rows.winfo_children():
            child.destroy()
        loaded=self.mission_lab_loaded()
        panne=self.mission_current.startswith('panne-')
        if panne and not (self.panne and 'panne-'+self.panne['lab']==self.mission_current):
            loaded=False
        generated=self.is_scenario()
        if generated and not (self.scenario and self.scenario['id']==self.mission_current):
            loaded=False
        if loaded and generated:
            from .scenarios import grade as grade_scenario
            result=grade_scenario(self.manifest(),self.scenario,self.mission_real)
            rows=result['results']
        elif loaded and panne:
            from .faults import grade as grade_panne
            result=grade_panne(self.manifest(),self.panne,self.mission_real)
            rows=result['results']
        elif loaded:
            result=grade(self.manifest(),self.mission_current,self.mission_real)
            rows=result['results']
        else:
            from .scenarios import checks_for
            checks=(checks_for(self.scenario) if self.mission_current.startswith('gen-') and self.scenario
                    else mission(self.mission_current)['checks'])
            rows=[{'text':c['text'],'kind':'réel' if c['kind'] in REAL_KINDS else 'configuration','status':'idle','detail':''}
                  for c in checks]
            if panne or generated:
                rows.insert(0,{'text':'La panne est réparée','kind':'configuration','status':'idle','detail':''})
            result={'passed':0,'total':len(rows),'solved':False}
        marks={'ok':('✔','#168942'),'fail':('✖','#bb3646'),'pending':('○','#8b9cae'),'idle':('·','#8b9cae')}
        for row in rows:
            line=tk.Frame(self.mission_rows,bg='white')
            line.pack(fill='x',pady=3)
            line.columnconfigure(1,weight=1)
            mark,colour=marks[row['status']]
            tk.Label(line,text=mark,bg='white',fg=colour,font=(self.font,12,'bold'),width=2).grid(row=0,column=0,rowspan=2,sticky='n')
            tag='Config' if row['kind']=='configuration' else 'Réel'
            head=tk.Frame(line,bg='white')
            head.grid(row=0,column=1,sticky='w')
            tk.Label(head,text=tag,bg='#eef4fb' if tag=='Config' else '#efe9fb',fg='#1f5f9c' if tag=='Config' else '#5b3aa6',
                     font=(self.font,7,'bold'),padx=6).pack(side='left',padx=(0,8))
            tk.Label(head,text=row['text'],bg='white',fg=TEXT,font=(self.font,10),anchor='w').pack(side='left')
            if row['detail']:
                tk.Label(line,text=row['detail'],bg='white',fg=MUTED,font=(self.font,8),anchor='w').grid(row=1,column=1,sticky='w')
        self.mission_score.set(f"{result['passed']} / {result['total']}" + ('  ·  Mission réussie ✔' if result['solved'] else ''))
        self.mission_bar.delete('all')
        width=max(100,self.mission_bar.winfo_width())
        self.mission_bar.create_rectangle(0,1,width,7,fill='#e6edf4',outline='')
        if result['total']:
            done=width*result['passed']/result['total']
            self.mission_bar.create_rectangle(0,1,done,7,fill='#21a35a' if result['solved'] else BLUE,outline='')
        if not loaded:
            self.mission_status.set('Indiquer noyau et disque, puis « Charger la mission ».')
        return result if loaded else None
