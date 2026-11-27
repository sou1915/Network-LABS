"""The workbench's vendor console: a device's configuration in its own dialect, applied and shown. A mixin of ui.ApplianceWindow."""
import json
import tkinter as tk
from tkinter import ttk
from .reference_theme import BG, TEXT, MUTED


class VendorConsole:
    def build_vendor_console(self,parent):
        """Vendor-syntax configuration (IOS, FortiOS, Junos, RouterOS) of the selected node's lab draft."""
        frame=self.vendor_frame=tk.Frame(parent,bg=BG)
        self.vendor_title=tk.StringVar()
        title=self.label(frame,'',TEXT,11,True)
        title.configure(textvariable=self.vendor_title)
        title.pack(fill='x',padx=14,pady=(14,2))
        title.configure(anchor='w')
        title.bind('<Configure>',lambda event:title.configure(wraplength=max(120,event.width-4)))
        self.vendor_hint=tk.StringVar()
        hint=tk.Label(frame,textvariable=self.vendor_hint,bg=BG,fg=MUTED,font=(self.font,8),justify='left',anchor='w')
        hint.pack(fill='x',padx=14)
        hint.bind('<Configure>',lambda event:hint.configure(wraplength=max(120,event.width-4)))
        box=tk.Frame(frame,bg='#0d1520')
        box.pack(fill='both',expand=True,padx=14,pady=8)
        self.vendor_text=tk.Text(box,wrap='none',font=('DejaVu Sans Mono',8),height=13,bg='#0d1520',fg='#d7e3f0',
                                 insertbackground='#d7e3f0',bd=0,highlightthickness=0,padx=8,pady=6,undo=True)
        scroll=ttk.Scrollbar(box,orient='vertical',command=self.vendor_text.yview,style='Native.Vertical.TScrollbar')
        across=ttk.Scrollbar(box,orient='horizontal',command=self.vendor_text.xview)
        self.vendor_text.configure(yscrollcommand=scroll.set,xscrollcommand=across.set)
        across.pack(side='bottom',fill='x')
        scroll.pack(side='right',fill='y')
        self.vendor_text.pack(side='left',fill='both',expand=True)
        actions=tk.Frame(frame,bg=BG)
        actions.pack(fill='x',padx=14)
        self.vendor_show=ttk.Button(actions,text='Afficher la configuration',command=self.show_vendor_config,style='Native.TButton')
        self.vendor_show.pack(side='left',fill='x',expand=True,padx=(0,5))
        self.vendor_apply=ttk.Button(actions,text='Appliquer au brouillon',command=self.apply_vendor_config,
                                     style='Native.Primary.TButton')
        self.vendor_apply.pack(side='right',fill='x',expand=True)
        self.vendor_live=ttk.Button(frame,text='⚡ Appliquer au lab en marche',
                                    command=self.apply_routing_live,style='Native.TButton')
        self.vendor_live.pack(fill='x',padx=14,pady=(5,0))
        live=tk.Frame(frame,bg=BG)
        live.pack(fill='x',padx=14,pady=(8,0))
        self.vendor_command=tk.StringVar()
        self.vendor_commands=ttk.Combobox(live,textvariable=self.vendor_command,style='Native.TCombobox',font=('DejaVu Sans Mono',9))
        self.vendor_commands.pack(side='left',fill='x',expand=True,padx=(0,5))
        self.vendor_commands.bind('<Return>',lambda event:self.run_vendor_show())
        self.vendor_run=ttk.Button(live,text='Exécuter',command=self.run_vendor_show,style='Native.TButton')
        self.vendor_run.pack(side='left')
        self.vendor_refresh=ttk.Button(live,text='Relire',command=lambda:self.run_vendor_show(refresh=True),
                                       style='Native.TButton')
        self.vendor_refresh.pack(side='right',padx=(5,0))
        self.vendor_observation=None
        self.vendor_pending_command=None
        self.vendor_ping_destination=None
        self.vendor_ping_command=''
        self.vendor_message=tk.StringVar()
        message=tk.Label(frame,textvariable=self.vendor_message,bg=BG,fg=MUTED,font=(self.font,8),justify='left',anchor='w')
        message.pack(fill='x',padx=14,pady=6)
        message.bind('<Configure>',lambda event:message.configure(wraplength=max(120,event.width-4)))
        self.vendor_node=None

    def load_vendor_console(self,spec,node):
        from . import vendor_config
        from .native_models import label as model_label
        syntax=vendor_config.dialect(node)
        if syntax is None:
            self.vendor_node=None
            self.vendor_frame.pack_forget()
            return
        self.vendor_frame.pack(fill='both',expand=True,before=self.linux_console_title)
        self.vendor_node=node['name']
        from .vendor_show import COMMANDS
        self.vendor_commands.configure(values=COMMANDS[syntax])
        if self.vendor_command.get() not in COMMANDS[syntax]:
            self.vendor_command.set(COMMANDS[syntax][0])
        self.vendor_title.set(f'{vendor_config.TITLES[syntax]} · {model_label(node,short=True)}')
        self.vendor_hint.set(vendor_config.HINTS[syntax]+' Les commandes écrivent dans le brouillon du lab, '
                             'validé comme le formulaire ; le nœud exécute Linux, pas le système du constructeur.')
        self.show_vendor_config(spec)
        from .vendor_show import PING_HELP
        self.vendor_message.set('Configuration du brouillon. Lab actif : commandes show et '+PING_HELP[syntax]+'.')

    def show_vendor_config(self,spec=None):
        from . import vendor_config
        try:
            text=vendor_config.render(spec or self.editing_spec(),self.vendor_node)
        except (ValueError,TypeError,KeyError) as error:
            self.vendor_message.set(str(error))
            return
        self.vendor_text.delete('1.0','end')
        self.vendor_text.insert('1.0',text)
        self.vendor_message.set('Configuration du brouillon. Modifier ou taper des commandes, puis appliquer.')

    def apply_routing_live(self):
        """Apply the draft (vendor commands or forms) first, then send the saved node's static routes, gateway and OSPF
        to the running micro-VM: no restart. Other changes still need one; the bridge refuses them."""
        name=self.vendor_node
        node=next((n for n in self.editing_spec()['nodes'] if n['name']==name),None)
        running=self.view_lab==self.manifest()['name'] and self.states.get(name,{}).get('status')=='running'
        if node is None or node['runtime']!='firecracker' or node['role']=='switch' or not running:
            self.vendor_message.set('À chaud : un poste, routeur ou pare-feu micro-VM d’un lab démarré. '
                                    'Sinon, enregistrer puis redémarrer.')
            return False
        if self.vendor_text.get('1.0','end').strip() and not self.apply_vendor_config():
            return False
        self.nodes.selection_set(name)
        self.vendor_message.set('Application à chaud : confirmer avec sudo dans le terminal.')
        return self.launch('routing')

    def apply_vendor_config(self):
        from . import vendor_config
        name=self.vendor_node
        try:
            result=vendor_config.apply(self.editing_spec(),name,self.vendor_text.get('1.0','end'))
        except (ValueError,TypeError,KeyError) as error:
            self.vendor_message.set(str(error))
            return False
        self.config_key=None
        self.commit_edit(result)
        self.choose_node(name)
        self.load_config(force=True)
        self.device_tabs.select(self.console_panel)
        self.vendor_message.set('Brouillon appliqué. Enregistrer puis arrêter / démarrer pour activer les changements.')
        return True

    def run_vendor_show(self,refresh=False):
        """Print the running node's state in its vendor's format; observe it first when no observation is held."""
        from .vendor_show import show
        name=self.vendor_node
        if not name:
            return False
        if self.states.get(name,{}).get('status')!='running':
            self.vendor_message.set('Démarrer le lab et actualiser l’état : les commandes show lisent le nœud actif.')
            return False
        from .vendor_show import ping_destination
        try:
            node=next(n for n in self.manifest()['nodes'] if n['name']==name)
            target=ping_destination(node,self.vendor_command.get())
        except (ValueError,TypeError,KeyError,StopIteration) as error:
            self.vendor_message.set(str(error))
            return False
        if target:
            # Each ping is a new, sudo-confirmed request: echo requests leave the running node.
            self.vendor_ping_destination=target
            self.vendor_ping_command=self.vendor_command.get().strip()
            return self.launch('ping')
        held=self.vendor_observation
        if refresh or not held or held['key']!=(self.view_lab,name):
            self.vendor_pending_command=self.vendor_command.get()
            return self.launch('show')
        try:
            node=next(n for n in self.manifest()['nodes'] if n['name']==name)
            text=show(node,held['data'],self.vendor_command.get())
        except (ValueError,TypeError,KeyError,StopIteration) as error:
            self.vendor_message.set(str(error))
            return False
        from .vendor_show import PROMPTS
        from .vendor_config import dialect
        prompt=PROMPTS[dialect(node)].format(name)
        header=f'{prompt} {self.vendor_command.get().strip()}'
        note=f'(état Linux observé à {held["time"]} ; « Relire » interroge à nouveau le nœud)'
        self.write_output(header+'\n'+text+'\n\n'+note,held['data'],'CLI · '+name)
        self.vendor_message.set('Sortie dans « Diagnostic réseau ». Les valeurs viennent du nœud Linux actif.')
        self.dock.select(self.output_tab)
        return True

    EMPTY_OUTPUT=('  Aucun relevé pour l’instant.\n\n'
                  '  Les sorties des commandes lancées depuis l’application (état, inspection, show d’un équipement)\n'
                  '  s’affichent ici. Pour taper des commandes : double-clic sur un équipement.')

    def write_output(self,display,raw,title):
        if display and getattr(self,'log_shown',None) is False:
            self.toggle_log(True)
        self.dock.tab(self.output_tab,text=title)
        raw=json.dumps(raw,ensure_ascii=False,indent=2)
        for target,text in ((self.output,display),(self.raw_output,raw)):
            target.configure(state='normal')
            target.delete('1.0','end')
            target.insert('1.0',text)
            if target is self.output and not display:
                target.insert('1.0',self.EMPTY_OUTPUT,('empty',))  # an empty terminal says what will come in it
            target.configure(state='disabled')
