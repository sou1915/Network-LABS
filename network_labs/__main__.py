"""Network LABS desktop workbench. Pure Tk; simulation never executes shell commands."""
import json
import math
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from ipaddress import IPv4Interface, IPv4Address
from pathlib import Path
from .engine import Lab, Node, demo, switching_demo, vlan_list
from .cli import Session, FEATURES
from .vendor_cli import console_session
from .profiles import PROFILES,profile_role
from .firewall import is_firewall
from .layout import ScrollPanel, initial_geometry, fit_dialog

from .theme import BG,PANEL,CARD,LINE,TEXT,MUTED,TEAL,BLUE,GOLD,RED
FONT=('DejaVu Sans',10); MONO=('DejaVu Sans Mono',10)


def label(parent,text,color=TEXT,size=10,bold=False):
    return tk.Label(parent,text=text,bg=parent['bg'],fg=color,font=('DejaVu Sans',size,'bold' if bold else 'normal'),anchor='w',justify='left')


def button(parent,text,command,accent=False):
    return ttk.Button(parent,text=text,command=command,style='Accent.TButton' if accent else 'TButton')


def roundrect(c,x1,y1,x2,y2,r=12,**kw):
    return c.create_polygon(x1+r,y1,x2-r,y1,x2,y1,x2,y1+r,x2,y2-r,x2,y2,x2-r,y2,x1+r,y2,x1,y2,x1,y2-r,x1,y1+r,x1,y1,smooth=True,**kw)

class Terminal:
    """Console with a protected transcript and direct, inline command editing."""
    def __init__(self,app,node,parent=None):
        self.executing=False
        self.app=app; self.session=console_session(app.lab,node)
        self.history=[]; self.cursor=0
        self.tail_job=None; self.follow_tail=True
        self.frame=tk.Frame(parent if parent is not None else app.dock,bg='#000000')
        bar=tk.Frame(self.frame,bg='#1c2026',padx=9,pady=4); bar.pack(fill='x')
        tk.Label(bar,text=f'{node} — {PROFILES[self.session.n.profile].model} | Simulation',bg='#1c2026',fg='#a8afb8',font=('DejaVu Sans',9)).pack(side='left')
        for title,callback in [('?',lambda:self.send('?')),('Coller un bloc',self.block),('Effacer',self.clear)]:
            ttk.Button(bar,text=title,command=callback,style='Small.TButton').pack(side='right',padx=3)
        content=tk.Frame(self.frame,bg='black'); content.pack(fill='both',expand=True)
        self.text=tk.Text(content,bg='#000000',fg='#d5d5d5',font=('DejaVu Sans Mono',11),relief='flat',wrap='char',padx=12,pady=12,height=7,insertbackground='#e0e0e0',insertwidth=9,insertofftime=450,insertontime=650,selectbackground='#38485d',selectforeground='white',undo=False)
        scroll=ttk.Scrollbar(content,command=self.text.yview); self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y'); self.text.pack(fill='both',expand=True)
        self.entry=self.text  # Kept as the focus target for the workbench.
        self.prompt=tk.StringVar(value=self.session.prompt)
        self.text.tag_configure('hint',foreground='#9b9b9b')
        self.text.tag_configure('error',foreground='#d5d5d5')
        self.text.tag_configure('prompt',foreground='#d5d5d5')
        self.text.bind('<Configure>',lambda e:self.schedule_tail())
        self.text.bind('<Map>',lambda e:self.schedule_tail())
        self.text.bind('<Destroy>',self.destroyed)
        self.text.bind('<KeyPress>',self.key)
        self.text.bind('<Return>',lambda e:self.enter())
        self.text.bind('<Up>',lambda e:self.recall(-1))
        self.text.bind('<Down>',lambda e:self.recall(1))
        self.text.bind('<Tab>',self.complete)
        self.text.bind('<Home>',self.home)
        self.text.bind('<Control-a>',self.home)
        self.text.bind('<Control-e>',self.end)
        self.text.bind('<Control-l>',lambda e:self.clear())
        self.text.bind('<Control-c>',self.interrupt)
        self.text.bind('<Control-z>',self.ctrl_z)
        self.text.bind('<<Paste>>',self.paste)
        self.text.bind('<<Cut>>',self.cut)
        self.text.bind('<Control-k>',self.kill_line)
        self.text.bind('<Control-h>',self.backspace)
        self.text.bind('<Control-w>',self.delete_word)
        self.text.bind('<Control-BackSpace>',self.delete_word)
        self.text.bind('<Control-u>',self.clear_input)
        from .device_identity import identity
        face=identity(self.session.n.profile)
        self.write('Network LABS · '+face['console']+' console\nSous-ensemble de commandes simulées ; aucun OS constructeur exécuté.\n\n')
        if self.session.n.kind=='PC':
            self.write('Network workstation. Type help for network commands.\n\n')
        else:
            self.write('Console line 0 ready.\n\n')
        self.new_prompt()

    def write(self,text,tag=None):
        self.text.insert('end-1c',text,tag or ())
        self.schedule_tail()

    def destroyed(self,event):
        if event.widget==self.text and self.tail_job is not None:
            self.app.root.after_cancel(self.tail_job); self.tail_job=None

    def schedule_tail(self):
        if self.tail_job is not None:
            self.app.root.after_cancel(self.tail_job)
        self.tail_job=self.app.root.after_idle(self.ensure_prompt_visible)

    def ensure_prompt_visible(self):
        self.tail_job=None
        if self.text.winfo_exists() and self.text.winfo_ismapped():
            self.text.yview_moveto(1.0)
            self.text.see('end-1c')

    def new_prompt(self,value=''):
        self.prompt.set(self.session.prompt)
        self.text.mark_set('prompt_start','end-1c'); self.text.mark_gravity('prompt_start','left')
        self.write(self.session.prompt+' ')
        self.text.mark_set('input_start','end-1c'); self.text.mark_gravity('input_start','left')
        self.write(value); self.text.mark_set('insert','end-1c'); self.schedule_tail()

    def refresh_prompt(self):
        if not self.executing and self.text.winfo_exists() and self.prompt.get()!=self.session.prompt:
            value=self.pending(); self.text.delete('prompt_start','end-1c'); self.new_prompt(value)

    def pending(self):
        return self.text.get('input_start','end-1c')

    def replace_input(self,value):
        self.text.delete('input_start','end-1c'); self.write(value); self.text.mark_set('insert','end-1c')

    def protected_selection(self):
        selection=self.text.tag_ranges('sel')
        return bool(selection and self.text.compare(selection[0],'<','input_start'))

    def key(self,event):
        if event.state & 4 and event.keysym.lower() in ('h','d','backspace','delete','w','y','o','t'):
            return 'break'
        if event.char=='?':
            value=self.pending()
            self.write('?\n'+self.session.help(value)+'\n'); self.new_prompt(value); return 'break'
        if event.keysym in ('Return','Up','Down','Tab','Home') or event.state & 4:
            return None
        if event.keysym in ('BackSpace','Left') and self.text.compare('insert','<=','input_start'):
            return 'break'
        if event.keysym in ('BackSpace','Delete') and self.protected_selection():
            return 'break'
        if event.char and event.char.isprintable():
            if self.protected_selection():
                self.text.tag_remove('sel','1.0','end')
            if self.text.compare('insert','<','input_start'):
                self.text.mark_set('insert','end-1c')
        if event.keysym=='Delete' and self.text.compare('insert','<','input_start'):
            return 'break'
        return None

    def backspace(self,event=None):
        if self.protected_selection():
            return 'break'
        selected=self.text.tag_ranges('sel')
        if selected:
            self.text.delete(*selected)
        elif self.text.compare('insert','>','input_start'):
            self.text.delete('insert-1c','insert')
        return 'break'

    def delete_word(self,event=None):
        if self.text.compare('insert','>','input_start'):
            start=self.text.index('insert-1c wordstart')
            if self.text.compare(start,'<','input_start'):
                start='input_start'
            self.text.delete(start,'insert')
        return 'break'

    def clear_input(self,event=None):
        if self.text.compare('insert','>','input_start'):
            self.text.delete('input_start','insert')
        return 'break'

    def home(self,event=None):
        self.text.mark_set('insert','input_start'); return 'break'

    def end(self,event=None):
        self.text.mark_set('insert','end-1c'); return 'break'

    def cut(self,event=None):
        if self.protected_selection():
            return 'break'
        return None

    def kill_line(self,event=None):
        if self.text.compare('insert','<','input_start'):
            self.text.mark_set('insert','input_start')
        self.text.delete('insert','end-1c'); return 'break'

    def interrupt(self,event=None):
        selection=self.text.tag_ranges('sel')
        if selection:
            self.text.clipboard_clear(); self.text.clipboard_append(self.text.get(*selection)); return 'break'
        self.write('^C\n'); self.new_prompt(); return 'break'

    def ctrl_z(self,event=None):
        if getattr(self.session,'dialect','')=='panos':
            self.send('exit'); return 'break'
        if self.session.n.kind!='PC' and self.session.mode not in ('user','priv'):
            self.send('end')
        else:
            self.interrupt()
        return 'break'

    def clear(self):
        self.text.delete('1.0','end'); self.new_prompt(); return 'break'

    def recall(self,direction):
        if self.history:
            self.cursor=max(0,min(len(self.history),self.cursor+direction))
            self.replace_input(self.history[self.cursor] if self.cursor<len(self.history) else '')
        return 'break'

    def complete(self,event=None):
        value=self.pending(); matches=self.session.completion_candidates(value)
        if len(matches)==1:
            self.replace_input(matches[0])
        elif matches:
            self.write('\n'+'    '.join(matches)+'\n'); self.new_prompt(value)
        return 'break'

    def enter(self):
        line=self.pending()
        if line.strip():
            self.send(line)
        else:
            self.write('\n'); self.new_prompt()
        self.text.focus_set(); return 'break'

    def send(self,line):
        if self.session.node not in self.app.lab.nodes:
            return
        commands=[c for c in line.splitlines() if c.strip() and not c.strip().startswith('!')]
        if not commands:
            return
        self.executing=True
        self.text.delete('prompt_start','end-1c')
        for command in commands:
            self.history.append(command); self.cursor=len(self.history)
            self.write(self.session.prompt+' '+command+'\n')
            result=self.session.execute(command)
            if result:
                self.write(result+'\n')
            if self.session.changed:
                self.app.dirty=True; self.app.invalidate(); self.app.refresh()
            elif command.lower().strip().startswith(('ping ','probe ')):
                self.app.animate_result(not result.startswith(('FAILED','%')),result.splitlines()[-1] if result else ''); self.app.draw()
            if result.startswith('%'):
                break
        self.new_prompt(); self.executing=False

    def paste(self,event=None):
        try:
            value=self.frame.clipboard_get()
        except tk.TclError:
            return 'break'
        if '\n' in value or '\r' in value:
            self.open_block(value)
        else:
            if self.protected_selection():
                self.text.tag_remove('sel','1.0','end')
            if self.text.compare('insert','<','input_start'):
                self.text.mark_set('insert','end-1c')
            selection=self.text.tag_ranges('sel')
            if selection:
                self.text.delete(*selection)
            self.text.insert('insert',value)
        return 'break'

    def block(self):
        self.open_block('')

    def open_block(self,initial):
        win=tk.Toplevel(self.app.root); win.title('Configuration / '+self.session.node)
        fit_dialog(win,700,460); win.configure(bg=PANEL); win.transient(self.app.root)
        label(win,'Une commande par ligne • arrêt à la première erreur',MUTED).pack(padx=15,pady=12)
        editor=tk.Text(win,bg='black',fg='#d5d5d5',insertbackground='white',font=MONO,padx=12,pady=12)
        editor.pack(fill='both',expand=True,padx=12); editor.insert('1.0',initial)
        def run():
            value=editor.get('1.0','end-1c'); win.destroy(); self.send(value); self.text.focus_set()
        button(win,'Exécuter le bloc',run,True).pack(side='bottom',before=editor,anchor='e',padx=12,pady=12); editor.focus_set()

class App:
    def __init__(self,root):
        self.root=root; self.lab=demo(); self.selected='SW1'; self.selected_link=None
        self.mode='select'; self.anchor=None; self.place_kind=None
        self.zoom=1.; self.panx=15.; self.pany=10.; self.pan_start=None
        self.timer=None; self.running=False; self.hops=[]; self.index=0; self.progress=0.; self.result=None
        self.terminals={}; self.dirty=False; self.path=None
        root.title('Network LABS  /  Switching Studio')
        width,height,x,y=initial_geometry(root.winfo_screenwidth(),root.winfo_screenheight())
        root.geometry(f'{width}x{height}+{x}+{y}')
        root.minsize(min(900,width),min(500,height)); root.configure(bg=BG)
        self.layout_job=None; self.last_size=None; self.dock_ratio=.57; self.console_focus=False; self.topology_focus=False
        self.panel_preference={'library':None,'inspector':None}
        self.style()
        self.header()
        modes=tk.Frame(root,bg=PANEL,padx=12,pady=6);modes.pack(fill='x')
        self.workspace_mode=tk.StringVar(value='Conception')
        for name in ('Conception','Simulation','Consoles'):
            ttk.Radiobutton(modes,text=name,value=name,variable=self.workspace_mode,command=lambda:self.set_workspace_mode(self.workspace_mode.get())).pack(side='left',padx=(0,18))
        label(modes,'1 · Construire     2 · Tester et comprendre     3 · Configurer en CLI',MUTED,9).pack(side='right')
        engine_bar=ttk.Frame(root,padding=(14,4));engine_bar.pack(fill='x')
        ttk.Label(engine_bar,text='Moteur du projet').pack(side='left',padx=(0,8))
        self.backend_choice=tk.StringVar(value='Pédagogique')
        self.backend_box=ttk.Combobox(engine_bar,textvariable=self.backend_choice,values=['Pédagogique','Wasm · LAN'],state='readonly',width=18)
        self.backend_box.pack(side='left');self.backend_box.bind('<<ComboboxSelected>>',self.set_backend)
        ttk.Button(engine_bar,text='Ouvrir le LAN Wasm',command=self.load_wasm_lab).pack(side='left',padx=8)
        self.capture_button=ttk.Button(engine_bar,text='Paquets / PCAP',command=self.open_project_capture,state='disabled');self.capture_button.pack(side='left')
        ttk.Label(engine_bar,text='Budget cible : 2 Gio RAM').pack(side='right',padx=8)
        workspace=self.workspace=ttk.Panedwindow(root,orient='horizontal')
        workspace.pack(fill='both',expand=True,padx=10,pady=(8,0))
        self.sidebar=ScrollPanel(workspace,PANEL)
        self.sidebar.configure(width=195)
        self.sidebar.pack_propagate(False)
        workspace.add(self.sidebar,weight=0)
        middle=self.middle=ttk.Panedwindow(workspace,orient='vertical')
        workspace.add(middle,weight=1)
        self.right=tk.Frame(workspace,bg=PANEL,width=330)
        self.right.pack_propagate(False)
        workspace.add(self.right,weight=0)
        self.build_sidebar()
        topology=self.topology=tk.Frame(middle,bg=BG)
        middle.add(topology,weight=3)
        self.canvas_toolbar(topology)
        self.canvas=tk.Canvas(topology,bg=BG,highlightthickness=0,height=200)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Button-1>',self.select)
        self.canvas.bind('<B1-Motion>',self.drag)
        self.canvas.bind('<Double-Button-1>',self.double_click)
        self.canvas.bind('<Button-3>',self.context)
        self.canvas.bind('<Button-2>',self.pan_begin)
        self.canvas.bind('<B2-Motion>',self.pan_move)
        self.canvas.bind('<MouseWheel>',lambda e:self.change_zoom(1.1 if e.delta>0 else 1/1.1))
        self.canvas.bind('<Button-4>',lambda e:self.change_zoom(1.1))
        self.canvas.bind('<Button-5>',lambda e:self.change_zoom(1/1.1))
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<Delete>',lambda e:self.delete())
        self.canvas.bind('<Escape>',lambda e:self.set_mode('select'))
        legend=tk.Frame(topology,bg=PANEL,padx=12,pady=7)
        legend.pack(fill='x')
        self.legend_labels=[]
        for text,color in [('● Forwarding',TEAL),('● STP bloqué',GOLD),('● Down',RED),('● Hors VLAN',MUTED)]:
            item=label(legend,text,color,9);item.pack(side='left',padx=6);self.legend_labels.append(item)
        label(legend,'Double-clic : Web / GUI · F10/F11',MUTED,9).pack(side='right')
        self.dock=ttk.Notebook(middle,height=180)
        middle.add(self.dock,weight=2)
        self.build_events()
        self.build_right()
        self.dock.bind('<<NotebookTabChanged>>',self.console_tab_changed)
        self.middle.bind('<ButtonRelease-1>',self.remember_split)
        self.status=tk.StringVar(value='Prêt • Sélectionner un équipement ou ouvrir sa console')
        statusbar=tk.Frame(root,bg=PANEL,padx=14,pady=7)
        statusbar.pack(fill='x',pady=(6,0))
        tk.Label(statusbar,textvariable=self.status,bg=PANEL,fg=MUTED,font=('DejaVu Sans',9),width=1,anchor='w').pack(side='left',fill='x',expand=True)
        self.counts=tk.StringVar()
        tk.Label(statusbar,textvariable=self.counts,bg=PANEL,fg=TEAL,font=('DejaVu Sans',9)).pack(side='right')
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.bind('<Control-s>',lambda e:self.save())
        self.refresh(); self.open_cli('SW1'); self.set_workspace_mode('Conception')
        root.update_idletasks()
        self.fit()
        root.bind('<Configure>',self.window_resized,add='+')
        root.bind('<Destroy>',self.cleanup,add='+')
        self.apply_layout()

    def set_workspace_mode(self,name):
        self.workspace_mode.set(name)
        if name=='Conception':
            if self.console_focus:self.toggle_console_focus()
            if not self.topology_focus:self.toggle_topology_focus()
            self.panel_preference={'library':True,'inspector':None}
            self.inspector_book.select(self.inspector_scroll)
        elif name=='Simulation':
            if self.console_focus:self.toggle_console_focus()
            if self.topology_focus:self.toggle_topology_focus()
            self.panel_preference={'library':False,'inspector':True}
            self.inspector_book.select(self.test_panel);self.dock.select(self.story)
            self.dock_ratio=.45
        elif name=='Consoles':
            if self.topology_focus:self.toggle_topology_focus()
            if not self.console_focus:self.toggle_console_focus()
            self.panel_preference={'library':False,'inspector':False}
            if self.terminals and self.dock.select() not in [str(t.frame) for t in self.terminals.values()]:self.dock.select(self.terminals.get(getattr(self,'active_console',None),next(iter(self.terminals.values()))).frame)
        self.apply_layout()

    def cleanup(self,event):
        if event.widget==self.root:
            self.pause()
            if getattr(self,'web_portal',None) is not None:self.web_portal.close()
            if self.layout_job is not None:
                self.root.after_cancel(self.layout_job); self.layout_job=None

    def window_resized(self,event):
        if event.widget!=self.root:
            return
        size=(event.width,event.height)
        if size==self.last_size:
            return
        self.last_size=size
        if self.layout_job is not None:
            self.root.after_cancel(self.layout_job)
        self.layout_job=self.root.after(60,self.apply_layout)

    def remember_split(self,event=None):
        if not self.console_focus and len(self.middle.panes())>1:
            self.dock_ratio=self.middle.sashpos(0)/max(1,self.middle.winfo_height())

    def apply_layout(self):
        self.layout_job=None
        width=self.root.winfo_width()
        for key,frame,index,automatic in [('library',self.sidebar,0,width>=1180),('inspector',self.right,'end',width>=1100)]:
            show=self.panel_preference[key] if self.panel_preference[key] is not None else automatic
            managed=str(frame) in self.workspace.panes()
            if show and not managed:
                self.workspace.insert(index,frame,weight=0)
            elif not show and managed:
                self.workspace.forget(frame)
        if not self.console_focus and len(self.middle.panes())>1:
            height=max(1,self.middle.winfo_height())
            dock_min=min(210,max(120,height//2))
            self.middle.sashpos(0,max(min(120,height//3),min(int(height*self.dock_ratio),height-dock_min)))
        for terminal in self.terminals.values():
            terminal.schedule_tail()

    def toggle_panel(self,key):
        frame=self.sidebar if key=='library' else self.right
        self.panel_preference[key]=str(frame) not in self.workspace.panes()
        self.apply_layout()

    def toggle_topology_focus(self):
        if self.console_focus:
            self.toggle_console_focus()
        self.topology_focus=not self.topology_focus
        if self.topology_focus:
            self.middle.forget(self.dock)
        else:
            self.middle.insert('end',self.dock,weight=2)
        self.root.update_idletasks(); self.apply_layout(); self.fit()

    def show_test_panel(self):
        self.set_workspace_mode('Simulation')
        self.panel_preference['inspector']=True; self.apply_layout()
        self.inspector_book.select(self.test_panel)

    def toggle_console_focus(self):
        if self.topology_focus:
            self.topology_focus=False
            self.middle.insert('end',self.dock,weight=2)
        self.console_focus=not self.console_focus
        if self.console_focus:
            self.middle.forget(self.topology)
        else:
            self.middle.insert(0,self.topology,weight=3)
        self.apply_layout()

    def console_tab_changed(self,event=None):
        current=self.dock.select()
        for terminal in self.terminals.values():
            if str(terminal.frame)==current:
                self.active_console=terminal.session.node
                terminal.schedule_tail()

    def style(self):
        s=ttk.Style(self.root); s.theme_use('clam')
        s.configure('.',background=PANEL,foreground=TEXT,font=FONT)
        s.configure('TButton',background='#e8edf4',foreground=TEXT,padding=(10,8),borderwidth=0)
        s.map('TButton',background=[('active','#dce6f4')],foreground=[('disabled',MUTED)])
        s.configure('Small.TButton',padding=(7,7),width=0)
        s.configure('Accent.TButton',background=BLUE,foreground='white')
        s.map('Accent.TButton',background=[('active','#174fbb')])
        s.configure('TEntry',fieldbackground=BG,foreground=TEXT,insertcolor=TEAL,padding=6,bordercolor=LINE)
        s.configure('TCombobox',fieldbackground=BG,foreground=TEXT,padding=5,arrowcolor=TEAL)
        s.map('TCombobox',fieldbackground=[('readonly',BG)],foreground=[('readonly',TEXT)])
        self.root.option_add('*TCombobox*Listbox.background',PANEL)
        self.root.option_add('*TCombobox*Listbox.foreground',TEXT)
        s.configure('TNotebook',background=BG,borderwidth=0)
        s.configure('TNotebook.Tab',background=PANEL,padding=(15,9),foreground=MUTED)
        s.map('TNotebook.Tab',background=[('selected',CARD)],foreground=[('selected',TEAL)])
        s.configure('Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT,rowheight=26,borderwidth=0)
        s.configure('Treeview.Heading',background=CARD,foreground=MUTED,font=('DejaVu Sans',9,'bold'),padding=7,relief='flat')
        s.map('Treeview',background=[('selected','#e1ebfb')],foreground=[('selected',TEXT)])
        s.configure('TPanedwindow',background=BG)
        s.configure('TScale',background=PANEL,troughcolor=BG)

    def header(self):
        top=tk.Frame(self.root,bg=PANEL,padx=18,pady=12); top.pack(fill='x')
        logo=tk.Canvas(top,width=35,height=35,bg=PANEL,highlightthickness=0)
        logo.pack(side='left',padx=(0,10))
        for x,y in [(7,7),(27,7),(17,28)]:
            for xx,yy in [(7,7),(27,7),(17,28)]:
                logo.create_line(x,y,xx,yy,fill='#2f887e',width=2)
            logo.create_oval(x-4,y-4,x+4,y+4,fill=TEAL,outline='')
        label(top,'NETWORK LABS',TEAL,16,True).pack(side='left')
        files=tk.Menubutton(top,text='Fichier ▾',bg=PANEL,fg=TEXT,activebackground=CARD,activeforeground=TEAL,padx=8,pady=6)
        file_menu=tk.Menu(files,tearoff=False,bg=PANEL,fg=TEXT)
        file_menu.add_command(label='Importer un lab texte',command=self.import_text)
        file_menu.add_command(label='Importer CLI sur la sélection',command=lambda:self.import_text(True))
        file_menu.add_command(label='Exporter le lab en texte',command=self.export_text)
        file_menu.add_separator()
        file_menu.add_command(label='Lab micro-appliances (expérimental)',command=self.open_micro_lab)
        file_menu.add_command(label='Micro-nodes natifs · runtimes / manifest',command=self.open_native_lab)
        file_menu.add_command(label='Lab FortiGate · Firewall Policy',command=self.load_fortigate_lab)
        files.configure(menu=file_menu); files.pack(side='left',padx=4)
        view=tk.Menubutton(top,text='Vue ▾',bg=PANEL,fg=TEXT,activebackground=CARD,activeforeground=TEAL,padx=10,pady=6)
        menu=tk.Menu(view,tearoff=False,bg=PANEL,fg=TEXT)
        menu.add_command(label='Bibliothèque',command=lambda:self.toggle_panel('library'))
        menu.add_command(label='Inspecteur',command=lambda:self.toggle_panel('inspector'))
        menu.add_command(label='Simulation / Ping',command=self.show_test_panel)
        menu.add_command(label='Agrandir / restaurer la topologie (F10)',command=self.toggle_topology_focus)
        menu.add_command(label='Agrandir / restaurer la console (F11)',command=self.toggle_console_focus)
        view.configure(menu=menu); view.pack(side='left',padx=12)
        self.root.bind('<F11>',lambda e:self.toggle_console_focus())
        self.root.bind('<F10>',lambda e:self.toggle_topology_focus())
        for title,callback in [('Sauvegarder',self.save),('Ouvrir',self.load),('Importer .txt',self.import_text),('Nouveau',self.new)]:
            control=button(top,title,callback,title=='Sauvegarder');control.configure(width=0);control.pack(side='right',padx=4)

    def import_text(self,device_mode=False):
        from .text_ui import ImportDialog
        return ImportDialog(self,device_mode)

    def export_text(self):
        from .text_ui import export_dialog
        export_dialog(self)

    def open_micro_lab(self):
        from .micro_appliances.runtime import DependencyMissing
        from .micro_appliances.ui import MicroLabWindow
        window=getattr(self,'micro_lab_window',None)
        if window is not None and not window.closed:
            window.window.lift();return window
        try:
            self.micro_lab_window=MicroLabWindow(self)
            return self.micro_lab_window
        except (DependencyMissing,OSError,ValueError) as error:
            messagebox.showinfo('Prototype micro-appliances',str(error)+'\n\nVoir docs/MICRO_APPLIANCES.md pour l’installation facultative.',parent=self.root)

    def set_backend(self,event=None):
        self.lab.execution_backend='wasm' if self.backend_choice.get()=='Wasm · LAN' else 'model'
        self.changed('Moteur Wasm : access VLAN 1, IPv4 statique /24, ICMP et TCP echo/8080. Nouvelles instances par test.' if self.lab.execution_backend=='wasm' else 'Moteur pédagogique sélectionné.')

    def open_native_lab(self):
        from .appliances.ui import ApplianceWindow
        previous=getattr(self,'native_lab_window',None)
        if previous is not None and previous.window.winfo_exists():
            previous.window.lift();return previous
        self.native_lab_window=ApplianceWindow(self)
        return self.native_lab_window

    def load_wasm_lab(self):
        from .micro_appliances.project import demo
        if self.replace_lab(demo):
            self.source.set('PC1');self.destination.set('192.168.50.20');self.test_protocol.set('icmp');self.test_port.set('8080')
            self.status.set('LAN Wasm chargé dans le projet. Modifier, câbler ou lancer un ping depuis la GUI / CLI.')

    def load_fortigate_lab(self):
        if self.replace_lab(self.service_demo):
            self.selected='FW1';self.refresh();self.open_web('FW1','firewall')

    def open_project_capture(self):
        capture=getattr(self.lab,'last_micro_capture',None)
        if capture is None:
            messagebox.showinfo('Capture Wasm','Lancer un test avec le moteur Wasm dans le projet courant.',parent=self.root);return
        from .micro_appliances.ui import MicroLabWindow
        previous=getattr(self,'project_capture_window',None)
        if previous is not None and not previous.closed:previous.close()
        self.project_capture_window=MicroLabWindow(self,snapshot=capture)
        return self.project_capture_window

    def build_sidebar(self):
        tabs=ttk.Notebook(self.sidebar.inner);tabs.pack(fill='both',expand=True)
        parent=tk.Frame(tabs,bg=PANEL);tools=tk.Frame(tabs,bg=PANEL);labs=tk.Frame(tabs,bg=PANEL)
        tabs.add(parent,text='Nodes');tabs.add(tools,text='Outils');tabs.add(labs,text='Labs')
        label(parent,'ÉQUIPEMENTS',MUTED,9,True).pack(fill='x',padx=14,pady=(17,10))
        for kind,title,subtitle in [('PC','Poste client','IPv4 · ping · CLI'),('Switch','Switch L2','24 ports · VLAN · STP'),('Routeur','Routeur','802.1Q · inter-VLAN')]:
            card=tk.Frame(parent,bg=CARD,padx=10,pady=10,cursor='hand2'); card.pack(fill='x',padx=10,pady=5)
            name=tk.Label(card,text=title,bg=CARD,fg=TEXT,font=('DejaVu Sans',11,'bold'),anchor='w'); name.pack(fill='x')
            sub=tk.Label(card,text=subtitle,bg=CARD,fg=MUTED,font=('DejaVu Sans',8),anchor='w'); sub.pack(fill='x',pady=(4,0))
            for w in (card,name,sub):
                w.bind('<Button-1>',lambda e,k=kind:self.set_place(k))
        button(parent,'Catalogue LAN',self.catalogue).pack(fill='x',padx=10,pady=8)
        parent=tools
        label(parent,'OUTILS',MUTED,9,True).pack(fill='x',padx=14,pady=(20,8))
        for title,callback in [('↖  Sélection',lambda:self.set_mode('select')),('⌁  Câbler',lambda:self.set_mode('cable')),('⌨  Ouvrir CLI',lambda:self.open_cli(self.selected)),('Supprimer',self.delete)]:
            button(parent,title,callback).pack(fill='x',padx=10,pady=3)
        parent=labs
        label(parent,'LABS INTÉGRÉS',MUTED,9,True).pack(fill='x',padx=14,pady=(22,8))
        for title,factory in [('01  Inter-VLAN',demo),('02  Boucle STP',switching_demo),('03  EtherChannel',self.channel_demo),('04  DHCP / Sécurité',self.security_demo),('05  VTP v2',self.vtp_demo),('06  MST instances',self.mst_demo),('07  LAN entreprise',self.lan_demo),('08  Firewall LAN',self.firewall_demo),('09  Services TCP/UDP',self.service_demo)]:
            button(parent,title,lambda f=factory:self.replace_lab(f)).pack(fill='x',padx=10,pady=3)
        label(parent,'Simulation LAN\nSans VM / firmware',MUTED,8).pack(fill='x',padx=14,pady=20)

    @staticmethod
    def lan_demo():
        from .text_lab import parse_lab
        return parse_lab((Path(__file__).resolve().parent.parent/'examples'/'enterprise_lan.lab.txt').read_text(encoding='utf-8')).lab

    @staticmethod
    def firewall_demo():
        from .text_lab import parse_lab
        return parse_lab((Path(__file__).resolve().parent.parent/'examples'/'firewall_lan.lab.txt').read_text(encoding='utf-8')).lab

    @staticmethod
    def service_demo():
        from .text_lab import parse_lab
        return parse_lab((Path(__file__).resolve().parent.parent/'examples'/'service_firewall.lab.txt').read_text(encoding='utf-8')).lab

    @staticmethod
    def channel_demo():
        lab=demo(); lab.add(Node('SW2','Switch',710,490))
        for _ in range(2):
            link=lab.connect('SW1','SW2','trunk',[10,20])
            for node,port in ((link.a,link.a_port),(link.b,link.b_port)):
                p=lab.nodes[node].ports[port]; p.channel=1; p.channel_mode='active'
        return lab

    @staticmethod
    def security_demo():
        lab=demo()
        for node,lines in {
            'R1':['enable','configure terminal','ip dhcp excluded-address 192.168.10.1 192.168.10.20','ip dhcp pool USERS','network 192.168.10.0/24','default-router 192.168.10.1','dns-server 1.1.1.1','exit','ip dhcp excluded-address 192.168.20.1 192.168.20.20','ip dhcp pool SERVERS','network 192.168.20.0/24','default-router 192.168.20.1','end'],
            'SW1':['enable','configure terminal','ip dhcp snooping','ip dhcp snooping vlan 10,20','ip arp inspection vlan 10,20','interface gi0/3','ip dhcp snooping trust','ip arp inspection trust','exit','interface range gi0/1 - 2','ip verify source','end']}.items():
            session=Session(lab,node)
            for line in lines:
                result=session.execute(line)
                if result.startswith('%'):
                    raise ValueError(result)
        for name in ('PC1','PC2'):
            lab.nodes[name].address=''; lab.nodes[name].gateway=''
        return lab

    @staticmethod
    def mst_demo():
        lab=switching_demo()
        for node in ('SW1','SW2','SW3'):
            session=Session(lab,node)
            for command in ['enable','configure terminal','spanning-tree mst configuration','name CAMPUS','revision 1','instance 1 vlan 10','instance 2 vlan 20','exit','spanning-tree mode mst','end']:
                result=session.execute(command)
                if result.startswith('%'):
                    raise ValueError(result)
        lab.nodes['SW1'].priorities['mst:1']=0
        lab.nodes['SW3'].priorities['mst:2']=0
        return lab

    @staticmethod
    def vtp_demo():
        lab=switching_demo()
        for node,mode in [('SW1','server'),('SW2','client'),('SW3','transparent')]:
            session=Session(lab,node)
            for command in ['enable','configure terminal','vtp domain LAB','vtp mode '+mode,'end']:
                result=session.execute(command)
                if result.startswith('%'):
                    raise ValueError(result)
        session=Session(lab,'SW1')
        for command in ['enable','configure terminal','vlan 30','name USERS','end']:
            session.execute(command)
        return lab

    def canvas_toolbar(self,parent):
        bar=tk.Frame(parent,bg=PANEL,padx=10,pady=8); bar.pack(fill='x')
        label(bar,'TOPOLOGIE',TEXT,10,True).pack(side='left',padx=(0,15))
        label(bar,'VLAN observé',MUTED,9).pack(side='left',padx=5)
        self.view_vlan=tk.StringVar(value='10')
        self.vlan_box=ttk.Combobox(bar,textvariable=self.view_vlan,values=['1','10','20'],state='readonly',width=6)
        self.vlan_box.pack(side='left')
        self.vlan_box.bind('<<ComboboxSelected>>',lambda e:self.draw())
        for title,callback in [('+',lambda:self.change_zoom(1.15)),('-',lambda:self.change_zoom(1/1.15)),('Centrer',self.fit)]:
            ttk.Button(bar,text=title,command=callback,style='Small.TButton').pack(side='right',padx=3)
        self.zoom_label=tk.StringVar(value='100 %')
        tk.Label(bar,textvariable=self.zoom_label,bg=PANEL,fg=MUTED,font=('DejaVu Sans',9)).pack(side='right',padx=7)

    def build_events(self):
        from .explanation_ui import ExplanationPanel
        self.story=ExplanationPanel(self.dock)
        self.dock.add(self.story,text='Explication pas à pas')
        frame=tk.Frame(self.dock,bg=PANEL);self.events_frame=frame
        self.dock.add(frame,text='Détails techniques')
        columns=('phase','vlan','source','target','details')
        self.events=ttk.Treeview(frame,columns=columns,show='headings',height=8)
        for col,title,width in zip(columns,['Phase','VLAN','Source','Destination','Détails'],[80,60,120,120,300]):
            self.events.heading(col,text=title); self.events.column(col,width=width,stretch=col=='details')
        scroll=ttk.Scrollbar(frame,command=self.events.yview); self.events.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y'); self.events.pack(fill='both',expand=True)
        self.events.tag_configure('error',foreground=RED)
        self.events.bind('<<TreeviewSelect>>',self.inspect_event)

    def build_right(self):
        self.inspector_book=ttk.Notebook(self.right)
        self.inspector_book.pack(fill='both',expand=True)
        self.inspector_scroll=ScrollPanel(self.inspector_book,PANEL)
        self.inspector=self.inspector_scroll.inner
        self.inspector.configure(padx=10,pady=10)
        self.reference=tk.Frame(self.inspector_book,bg=PANEL,padx=12,pady=10)
        self.inspector_book.add(self.inspector_scroll,text='Inspecteur')
        self.inspector_book.add(self.reference,text='Commandes')
        ref=self.reference_text=tk.Text(self.reference,bg=PANEL,fg=MUTED,font=('DejaVu Sans',9),wrap='word',relief='flat',width=28,height=15)
        ref.pack(fill='both',expand=True)
        ref.insert('1.0',FEATURES+'\n\nEXEMPLE SWITCH\nenable\nconfigure terminal\nvlan 10\nname USERS\nexit\ninterface gi0/1\nswitchport mode access\nswitchport access vlan 10\nno shutdown\nend\nshow vlan brief\n\nEXEMPLE TRUNK\nenable\nconfigure terminal\ninterface gi0/3\nswitchport mode trunk\nswitchport trunk allowed vlan 10,20\nend\nshow interfaces trunk')
        ref.configure(state='disabled')
        self.test_panel=ScrollPanel(self.inspector_book,CARD)
        test=self.test_panel.inner;test.configure(padx=12,pady=12)
        self.inspector_book.add(self.test_panel,text='Simulation')
        label(test,'TEST / VISUALISATION',TEAL,9,True).pack(fill='x',pady=(0,8))
        self.source=tk.StringVar(value='PC1'); self.destination=tk.StringVar(value='192.168.20.10')
        label(test,'Équipement source',MUTED,9).pack(fill='x',pady=(4,0))
        self.source_box=ttk.Combobox(test,textvariable=self.source,state='readonly',width=24)
        self.source_box.pack(fill='x',pady=3)
        label(test,'Destination IPv4 ou nom DNS',MUTED,9).pack(fill='x',pady=(7,0))
        ttk.Entry(test,textvariable=self.destination).pack(fill='x',pady=3)
        self.test_protocol=tk.StringVar(value='icmp');self.test_port=tk.StringVar(value='443')
        label(test,'Protocole de test',MUTED,9).pack(fill='x',pady=(7,0))
        ttk.Combobox(test,textvariable=self.test_protocol,values=['icmp','tcp','udp'],state='readonly',width=10).pack(fill='x',pady=3)
        label(test,'Port de service (TCP / UDP)',MUTED,9).pack(fill='x',pady=(7,0))
        self.test_port_entry=ttk.Entry(test,textvariable=self.test_port);self.test_port_entry.pack(fill='x',pady=3)
        self.test_protocol.trace_add('write',lambda *a:self.test_port_entry.configure(state='disabled' if self.test_protocol.get()=='icmp' else 'normal'))
        self.test_port_entry.configure(state='disabled')
        button(test,'Tester et expliquer',self.ping,True).pack(fill='x',pady=(7,5))
        controls=tk.Frame(test,bg=CARD); controls.pack(fill='x')
        for title,command in [('Lire',self.play),('Pause',self.pause),('Étape',self.step),('Rejouer',self.replay)]:
            ttk.Button(controls,text=title,command=command,style='Small.TButton').pack(side='left',padx=2,expand=True,fill='x')
        self.speed=tk.DoubleVar(value=1.)
        label(test,'Vitesse de lecture',MUTED,8).pack(fill='x',pady=(8,1))
        ttk.Scale(test,from_=0.3,to=3,variable=self.speed).pack(fill='x')
        self.test_scope=tk.StringVar()
        ttk.Label(test,textvariable=self.test_scope,wraplength=270).pack(fill='x',pady=(7,0))

    def refresh(self):
        self.backend_choice.set('Wasm · LAN' if self.lab.execution_backend=='wasm' else 'Pédagogique')
        self.root.title('Network LABS / '+('Wasm LAN · projet exécuté' if self.lab.execution_backend=='wasm' else 'Switching Studio'))
        self.test_scope.set('Wasm : access VLAN 1 · IPv4 /24 · trames ARP/ICMP/TCP · horloge virtuelle.' if self.lab.execution_backend=='wasm' else 'Parcours calculé · pas de timing réel ARP/ICMP.')
        legend=['● Câblé','STP non exécuté','● Down',''] if self.lab.execution_backend=='wasm' else ['● Forwarding','● STP bloqué','● Down','● Hors VLAN']
        for item,text in zip(self.legend_labels,legend):item.configure(text=text)
        self.capture_button.configure(state='normal' if getattr(self.lab,'last_micro_capture',None) else 'disabled')
        values=[n.name for n in self.lab.nodes.values() if n.kind=='PC']
        self.source_box['values']=values
        if self.source.get() not in values:
            self.source.set(values[0] if values else '')
        vlans=sorted({int(v) for n in self.lab.nodes.values() if n.kind=='Switch' for v in n.vlans} or {1})
        self.vlan_box['values']=[str(v) for v in vlans]
        if self.view_vlan.get() not in self.vlan_box['values']:
            self.view_vlan.set(str(vlans[0]))
        self.counts.set(f'{len(self.lab.nodes)} équipements  /  {len(self.lab.links)} liens  /  {len(vlans)} VLAN')
        self.inspect(); self.draw()
        for terminal in self.terminals.values():
            terminal.refresh_prompt()
        for window in list(getattr(self,'device_windows',{}).values()):
            window.external_changed()

    def inspect(self):
        for w in self.inspector.winfo_children():
            w.destroy()
        panel=self.inspector
        if self.selected in self.lab.nodes:
            n=self.lab.nodes[self.selected]
            console=console_session(self.lab,n.name)
            self.reference_text.configure(state='normal');self.reference_text.delete('1.0','end')
            self.reference_text.insert('end',PROFILES[n.profile].brand+' · '+PROFILES[n.profile].model+'\n\n'+console.help()+'\n\nFonctions listées uniquement. Une commande non implémentée est refusée.')
            self.reference_text.configure(state='disabled')
            label(panel,n.hostname or n.name,TEAL,16,True).pack(fill='x',pady=(3,5))
            label(panel,PROFILES[n.profile].brand+' · '+PROFILES[n.profile].model,MUTED,8).pack(fill='x',pady=(0,10))
            label(panel,profile_role(PROFILES[n.profile])+' · '+n.mac,MUTED,8).pack(fill='x')
            button(panel,'Interface web · navigateur',lambda:self.open_web(n.name),True).pack(fill='x',pady=5)
            button(panel,'Configuration bureau / CLI',lambda:self.open_device(n.name)).pack(fill='x',pady=3)
            button(panel,'Console CLI dans le dock',lambda:self.open_cli(n.name)).pack(fill='x',pady=3)
            if n.kind=='PC':
                self.fields={}
                for title,value in [('IPv4 / CIDR',n.address),('Passerelle',n.gateway),('DNS (séparés par espace)',' '.join(n.dns))]:
                    label(panel,title,MUTED,9).pack(fill='x',pady=(12,4))
                    var=tk.StringVar(value=value); self.fields[title]=var
                    ttk.Entry(panel,textvariable=var).pack(fill='x')
                def apply():
                    try:
                        address=str(IPv4Interface(self.fields['IPv4 / CIDR'].get()))
                        gateway=self.fields['Passerelle'].get().strip()
                        if gateway:
                            IPv4Address(gateway)
                        dns=[str(IPv4Address(ip)) for ip in self.fields['DNS (séparés par espace)'].get().split()]
                        Session(self.lab,n.name).pc_static_address(address,gateway)
                        n.dns=dns
                        self.changed('Configuration IPv4 appliquée')
                    except ValueError as e:
                        messagebox.showerror('IPv4',str(e),parent=self.root)
                button(panel,'Appliquer IPv4',apply).pack(fill='x',pady=12)
                def dhcp():
                    result=Session(self.lab,n.name).execute('ip dhcp')
                    self.status.set(result)
                    self.dirty=True; self.refresh()
                button(panel,'Obtenir une adresse DHCP',dhcp).pack(fill='x',pady=3)
                def toggle_link():
                    n.ports['eth0'].shutdown=not n.ports['eth0'].shutdown
                    self.changed('Interface eth0 '+('désactivée' if n.ports['eth0'].shutdown else 'activée'))
                button(panel,'Activer eth0' if n.ports['eth0'].shutdown else 'Désactiver eth0',toggle_link).pack(fill='x',pady=3)
                if profile_role(PROFILES[n.profile])=='Serveur':
                    button(panel,'Configurer DNS local',lambda:self.dns_editor(n.name)).pack(fill='x',pady=5)
            elif n.kind=='Switch':
                if is_firewall(n):
                    button(panel,'Politique firewall LAN',lambda:self.firewall_editor(n.name),True).pack(fill='x',pady=6)
                    label(panel,f'{n.firewall_mode} · défaut {n.firewall_default} · ICMP',MUTED,9).pack(fill='x')
                label(panel,'PORTS PHYSIQUES',MUTED,9,True).pack(fill='x',pady=(14,7))
                port_frame=tk.Frame(panel,bg=PANEL)
                port_frame.pack(fill='both',expand=True)
                ports=ttk.Treeview(port_frame,columns=('port','state','vlan'),show='headings',height=12)
                for col,title,width in [('port','Port',65),('state','État',80),('vlan','VLAN',65)]:
                    ports.heading(col,text=title); ports.column(col,width=width,stretch=True)
                stp={} if self.lab.execution_backend=='wasm' else self.lab.stp(int(self.view_vlan.get())).get(n.name,{}).get('ports',{})
                for name,p in n.ports.items():
                    if '.' in name or name.startswith('po'):
                        continue
                    link=self.lab.link_for(n.name,name)
                    if self.lab.execution_backend=='wasm':
                        state='ERR' if p.errdisabled else 'DOWN' if p.shutdown or link and not link.enabled else 'câblé' if link else 'libre'
                        operational=p.mode
                    else:
                        state='ERR' if p.errdisabled else 'DOWN' if p.shutdown or (link and not link.enabled) else 'AUTH' if not self.lab.access_allowed(n.name,name) else 'BOUND' if link and self.lab.boundary_reason(link) else 'SUSP' if link and not self.lab.channel_state(link)[0] else stp.get(name,('','UP'))[1] if link else 'libre'
                        operational=self.lab.operational_mode(link,n.name) if link else p.mode
                    ports.insert('', 'end',iid=name,values=(name,state,'trunk' if operational=='trunk' else p.access_vlan),tags=('bad',) if state in ('ERR','DOWN','BLK','BOUND','SUSP','AUTH') else ())
                ports.tag_configure('bad',foreground=GOLD)
                scroll=ttk.Scrollbar(port_frame,command=ports.yview)
                ports.configure(yscrollcommand=scroll.set)
                scroll.pack(side='right',fill='y'); ports.pack(fill='both',expand=True)
                ports.bind('<Double-Button-1>',lambda e:self.edit_port(n.name,ports.selection()[0]) if ports.selection() else None)
                label(panel,'Double-clic sur un port : configuration',MUTED,8).pack(fill='x',pady=7)
            else:
                label(panel,'SOUS-INTERFACES 802.1Q',MUTED,9,True).pack(fill='x',pady=(16,8))
                for v,ip in n.interfaces.items():
                    label(panel,f'VLAN {v}  /  {ip}',TEXT,9).pack(fill='x',pady=4)
                label(panel,'GUI : onglet 802.1Q / IPv4.\nCLI : interface gi0/0.10\nencapsulation dot1Q 10\nip address 192.168.10.1/24',MUTED,9).pack(fill='x',pady=15)
        elif self.selected_link is not None and self.selected_link<len(self.lab.links):
            l=self.lab.links[self.selected_link]
            label(panel,'LIAISON PHYSIQUE',TEAL,12,True).pack(fill='x',pady=(5,12))
            for name,port in ((l.a,l.a_port),(l.b,l.b_port)):
                p=self.lab.nodes[name].ports[port]
                label(panel,f'{name} / {port}',TEXT,11,True).pack(fill='x',pady=(15,5))
                label(panel,f'{p.mode}  ·  access {p.access_vlan}\nNative {p.native_vlan}\nAllowed : {Session.compact(p.allowed)[:55]}',MUTED,9).pack(fill='x')
                button(panel,'Configurer ce port',lambda n=name,p=port:self.edit_port(n,p)).pack(fill='x',pady=6)
            def toggle():
                l.enabled=not l.enabled; self.changed('État du câble modifié')
            button(panel,'Couper le câble' if l.enabled else 'Rétablir le câble',toggle).pack(fill='x',pady=18)
            ok,reason=self.lab.channel_state(l)
            boundary=self.lab.boundary_reason(l)
            if boundary:
                tk.Label(panel,text=boundary,bg=PANEL,fg=RED,wraplength=260,justify='left').pack(fill='x',pady=8)
            if not ok:
                label(panel,reason,RED,9).pack(fill='x',pady=8)
        else:
            label(panel,'Votre espace réseau',TEAL,13,True).pack(fill='x',pady=(10,12))
            label(panel,'Choisir un équipement dans\nla bibliothèque puis cliquer\ndans la topologie.\n\nDouble-clic sur un équipement\npour choisir GUI ou CLI.\n\nCâbler : cliquer sur les deux\néquipements à connecter.',MUTED,10).pack(fill='x')

    def edit_port(self,node,name):
        window=self.open_device(node)
        if window is None or name not in self.lab.nodes[node].ports:
            return
        before=window.loading;window.loading=True
        window.vars['port'].set(name);window.load_port();window.loading=before
        window.show_page('Interfaces')

    def xy(self,n):
        return n.x*self.zoom+self.panx,n.y*self.zoom+self.pany

    def geometry(self,index):
        l=self.lab.links[index]; a=self.xy(self.lab.nodes[l.a]); b=self.xy(self.lab.nodes[l.b])
        siblings=[i for i,k in enumerate(self.lab.links) if {k.a,k.b}=={l.a,l.b}]
        rank=siblings.index(index)-(len(siblings)-1)/2
        dx,dy=b[0]-a[0],b[1]-a[1]; length=max(1,math.hypot(dx,dy))
        # Offset parallel cables in a stable orientation, even when endpoints reverse.
        sign=1 if l.a<l.b else -1
        off=rank*42*self.zoom*sign
        control=((a[0]+b[0])/2-dy/length*off,(a[1]+b[1])/2+dx/length*off)
        return a,control,b

    def point(self,index,t):
        a,c,b=self.geometry(index)
        return ((1-t)**2*a[0]+2*(1-t)*t*c[0]+t*t*b[0],(1-t)**2*a[1]+2*(1-t)*t*c[1]+t*t*b[1])

    def draw(self):
        c=self.canvas; c.delete('all')
        w,h=c.winfo_width(),c.winfo_height()
        grid=max(14,int(32*self.zoom))
        for x in range(int(self.panx)%grid,w,grid):
            for y in range(int(self.pany)%grid,h,grid):
                c.create_oval(x,y,x+1,y+1,fill='#dce3ed',outline='')
        vlan=int(self.view_vlan.get() or 1)
        wasm=self.lab.execution_backend=='wasm'
        states={} if wasm else self.lab.stp(vlan)
        for i,l in enumerate(self.lab.links):
            pa,pb=self.lab.ends(l)
            eligible=(pa.mode==pb.mode=='access' and pa.access_vlan==pb.access_vlan==1) if wasm else self.lab.eligible(l,vlan)
            blocked=any(states.get(n,{}).get('ports',{}).get(p,('',''))[1]=='BLK' for n,p in ((l.a,l.a_port),(l.b,l.b_port)))
            physically_down=not l.enabled or pa.shutdown or pb.shutdown or pa.errdisabled or pb.errdisabled
            if not wasm:physically_down=physically_down or bool(self.lab.boundary_reason(l)) or not self.lab.channel_state(l)[0]
            color=RED if physically_down else GOLD if blocked else TEAL if eligible else '#4b5d77'
            if self.selected_link==i:
                color=BLUE
            a,mid,b=self.geometry(i); tags=('link',str(i))
            c.create_line(*a,*mid,*b,smooth=True,fill=color,width=2.4 if eligible else 1.5,dash=(6,4) if blocked or physically_down else (),tags=tags)
            x,y=self.point(i,.5)
            caption='Po'+str(pa.channel) if pa.channel else 'DTP' if pa.mode.startswith('dynamic') or pb.mode.startswith('dynamic') else '802.1Q' if pa.mode=='trunk' or pb.mode=='trunk' else f'VLAN {pa.access_vlan if self.lab.nodes[l.a].kind=="Switch" else pb.access_vlan}'
            roundrect(c,x-35,y-10,x+35,y+10,r=5,fill=PANEL,outline=LINE,tags=tags)
            c.create_text(x,y,text=caption,fill=color,font=('DejaVu Sans',8),tags=tags)
            for t,name in (((.33,l.a_port),(.67,l.b_port)) if self.zoom>=.7 else ()):
                xx,yy=self.point(i,t)
                c.create_text(xx,yy-13,text=name,fill=MUTED,font=('DejaVu Sans',8),tags=tags)
        for n in self.lab.nodes.values():
            x,y=self.xy(n); z=self.zoom; tags=('node',n.name)
            width,height=136*z,100*z
            roundrect(c,x-width/2+3,y-height/2+5,x+width/2+3,y+height/2+5,r=12*z,fill='#dce2eb',outline='',tags=tags)
            roundrect(c,x-width/2,y-height/2,x+width/2,y+height/2,r=12*z,fill=CARD,outline=TEAL if self.selected==n.name or self.anchor==n.name else LINE,width=2 if self.selected==n.name else 1,tags=tags)
            color=BLUE if n.kind=='PC' else TEAL if n.kind=='Switch' else '#7851b4'
            role=profile_role(PROFILES[n.profile])
            self.icon(role if n.kind=='PC' or is_firewall(n) else n.kind,x,y-8*z,z,color,tags)
            c.create_text(x,y+31*z,text=n.hostname or n.name,fill=TEXT,font=('DejaVu Sans',max(8,int(10*z)),'bold'),tags=tags)
            if z>=.7:
                c.create_text(x,y+63*z,text=(PROFILES[n.profile].model+' · '+(n.address or 'sans IPv4')) if n.kind=='PC' else f'L2 • {sum(not p.startswith("po") and "." not in p for p in n.ports)} ports' if n.kind=='Switch' else 'Router-on-a-stick',fill=MUTED,font=('DejaVu Sans',max(7,int(8*z))),tags=tags)
            c.create_oval(x+width/2-14*z,y-height/2+9*z,x+width/2-8*z,y-height/2+15*z,fill=color,outline='',tags=tags)
            if n.kind=='Switch' and states.get(n.name,{}).get('root')==n.name:
                c.create_text(x,y-height/2-13*z,text=('ROOT / MST '+str(n.mst_map.get(str(vlan),0))) if n.stp_mode=='mst' else 'ROOT / VLAN '+str(vlan),fill=GOLD,font=('DejaVu Sans',max(7,int(8*z)),'bold'),tags=tags)
        if self.hops and self.index<len(self.hops):
            i,a,b,v,phase=self.hops[self.index]
            link=self.lab.links[i]
            t=self.progress if link.a==a else 1-self.progress
            x,y=self.point(i,t)
            color=GOLD if phase=='Aller' else BLUE
            c.create_oval(x-15,y-15,x+15,y+15,fill='#3a3e4b',outline='')
            c.create_rectangle(x-9,y-6,x+9,y+6,fill=color,outline='white')
            c.create_line(x-9,y-6,x,y+1,x+9,y-6,fill='#23334b')
            c.create_text(x,y+35,text=f'{phase} · VLAN {v}',fill=color,font=('DejaVu Sans',9,'bold'))
        if not self.lab.nodes:
            c.create_text(w/2,h/2,text='Construisez votre premier lab\nChoisir un équipement à gauche, puis cliquer ici.',fill=MUTED,font=('DejaVu Sans',14),justify='center')
        if self.mode=='cable':
            c.create_text(15,18,text='CÂBLAGE  /  '+(self.anchor+' → destination' if self.anchor else 'Choisir le premier équipement'),fill=GOLD,anchor='w',font=('DejaVu Sans',10,'bold'))
        elif self.place_kind:
            c.create_text(15,18,text='PLACER  /  '+self.place_kind+' · cliquer dans la topologie',fill=TEAL,anchor='w',font=('DejaVu Sans',10,'bold'))

    def icon(self,kind,x,y,z,color,tags):
        c=self.canvas
        if kind in ('PC','Poste','Portable'):
            c.create_rectangle(x-23*z,y-17*z,x+23*z,y+11*z,outline=color,width=2,tags=tags)
            c.create_rectangle(x-18*z,y-12*z,x+18*z,y+6*z,fill='#e3ebf6',outline='',tags=tags)
            c.create_line(x,y+11*z,x,y+18*z,fill=color,width=2,tags=tags)
            c.create_line(x-12*z,y+18*z,x+12*z,y+18*z,fill=color,width=2,tags=tags)
        elif kind=='Firewall':
            for row in range(3):
                for col in range(3):
                    left=x-28*z+col*19*z+(9*z if row==1 else 0)
                    c.create_rectangle(left,y-22*z+row*15*z,left+17*z,y-9*z+row*15*z,outline=color,fill='#fae3e7',width=2,tags=tags)
        elif kind in ('Serveur','NAS'):
            c.create_rectangle(x-22*z,y-24*z,x+22*z,y+23*z,outline=color,width=2,fill='#e3ebf6',tags=tags)
            for row in range(3):
                yy=y-17*z+row*14*z
                c.create_rectangle(x-16*z,yy,x+16*z,yy+9*z,outline=color,tags=tags)
                c.create_oval(x+9*z,yy+3*z,x+12*z,yy+6*z,fill=color,outline='',tags=tags)
        elif kind=='Imprimante':
            c.create_rectangle(x-15*z,y-24*z,x+15*z,y-4*z,outline=color,fill='#e3ebf6',tags=tags)
            c.create_rectangle(x-27*z,y-8*z,x+27*z,y+16*z,outline=color,width=2,tags=tags)
            c.create_rectangle(x-16*z,y+5*z,x+16*z,y+25*z,outline=color,fill='#e3ebf6',tags=tags)
        elif kind=='Caméra':
            c.create_rectangle(x-28*z,y-16*z,x+12*z,y+8*z,outline=color,width=2,tags=tags)
            c.create_oval(x+4*z,y-13*z,x+24*z,y+5*z,outline=color,width=2,tags=tags)
            c.create_line(x-8*z,y+9*z,x-8*z,y+23*z,x+14*z,y+23*z,fill=color,width=2,tags=tags)
        elif kind=='Téléphone IP':
            roundrect(c,x-25*z,y-19*z,x+25*z,y+20*z,r=5*z,outline=color,fill='#e3ebf6',width=2,tags=tags)
            c.create_rectangle(x-12*z,y-13*z,x+18*z,y-2*z,outline=color,tags=tags)
            for row in range(2):
                for col in range(3):
                    c.create_rectangle(x-7*z+col*8*z,y+5*z+row*7*z,x-3*z+col*8*z,y+8*z+row*7*z,fill=color,tags=tags)
        elif kind=='IoT':
            c.create_oval(x-18*z,y-18*z,x+18*z,y+18*z,outline=color,width=2,tags=tags)
            c.create_oval(x-6*z,y-6*z,x+6*z,y+6*z,fill=color,outline='',tags=tags)
        elif kind=='Switch':
            roundrect(c,x-32*z,y-13*z,x+32*z,y+12*z,r=5*z,fill='#e1f0ec',outline=color,width=2,tags=tags)
            for j in range(6):
                xx=x-24*z+j*9*z
                c.create_rectangle(xx,y-4*z,xx+5*z,y+3*z,outline=color,tags=tags)
            c.create_line(x-12*z,y-20*z,x+12*z,y-20*z,arrow='last',fill=color,tags=tags)
        else:
            c.create_oval(x-25*z,y-22*z,x+25*z,y+22*z,outline=color,width=2,fill='#eee8f6',tags=tags)
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                c.create_line(x+dx*3*z,y+dy*3*z,x+dx*17*z,y+dy*15*z,fill=color,width=2,arrow='last',tags=tags)

    def set_mode(self,mode):
        self.mode=mode; self.anchor=None; self.place_kind=None
        self.canvas.configure(cursor='crosshair' if mode=='cable' else '')
        self.status.set('Câbler : cliquer sur deux équipements' if mode=='cable' else 'Sélection / déplacement')
        self.draw()

    def firewall_editor(self,node):
        from .firewall_ui import FirewallEditor
        return FirewallEditor(self,node)

    def dns_editor(self,node,parent=None):
        if parent is None:
            win=tk.Toplevel(self.root); win.title('DNS local · '+node); win.configure(bg=PANEL)
            fit_dialog(win,700,470)
        else:
            win=parent
        server=self.lab.nodes[node]
        enabled=tk.BooleanVar(value=server.dns_service)
        label(win,'Zone locale IPv4 · A uniquement · pas de récursion/cache',MUTED,10).pack(fill='x',padx=14,pady=12)
        def service():
            server.dns_service=enabled.get(); self.changed('Service DNS local mis à jour')
        ttk.Checkbutton(win,text='Activer le service DNS simulé',variable=enabled,command=service).pack(anchor='w',padx=14)
        table=ttk.Treeview(win,columns=('name','ip'),show='headings',height=8)
        table.heading('name',text='Nom DNS'); table.heading('ip',text='IPv4')
        table.pack(fill='both',expand=True,padx=14,pady=10)
        label(win,'Nom DNS (gauche) · Adresse IPv4 (droite)',MUTED,9).pack(fill='x',padx=14,pady=(0,4))
        fields=tk.Frame(win,bg=PANEL); fields.pack(fill='x',padx=14)
        name=tk.StringVar(); address=tk.StringVar()
        ttk.Entry(fields,textvariable=name).pack(side='left',fill='x',expand=True,padx=(0,6))
        ttk.Entry(fields,textvariable=address,width=19).pack(side='left')
        def refresh():
            enabled.set(server.dns_service)
            table.delete(*table.get_children())
            for host,ip in sorted(server.dns_records.items()):
                table.insert('', 'end',iid=host,values=(host,ip))
        def add():
            result=Session(self.lab,node).execute('dns record '+name.get().strip()+' '+address.get().strip())
            if result.startswith('%'):
                messagebox.showerror('DNS',result,parent=win); return
            refresh(); self.changed('Enregistrement DNS ajouté')
        def remove():
            if table.selection():
                server.dns_records.pop(table.selection()[0],None); refresh(); self.changed('Enregistrement DNS supprimé')
        actions=tk.Frame(win,bg=PANEL); actions.pack(fill='x',padx=14,pady=12)
        button(actions,'Ajouter / remplacer',add).pack(side='left')
        button(actions,'Supprimer la sélection',remove).pack(side='right')
        refresh()
        return refresh

    def catalogue(self):
        dialog=tk.Toplevel(self.root)
        dialog.title('Catalogue des équipements'); dialog.configure(bg=PANEL)
        fit_dialog(dialog,880,540)
        query=tk.StringVar()
        category=tk.StringVar(value='Tous')
        categories=['Tous']+sorted({profile_role(p) for p in PROFILES.values()})
        category_box=ttk.Combobox(dialog,textvariable=category,values=categories,state='readonly')
        category_box.pack(fill='x',padx=12,pady=(10,0))
        label(dialog,'Rechercher une marque, un modèle ou un OS',MUTED,9).pack(fill='x',padx=12,pady=(10,0))
        ttk.Entry(dialog,textvariable=query).pack(fill='x',padx=12,pady=12)
        table=ttk.Treeview(dialog,columns=('brand','model','kind','support'),show='headings')
        for key,title,width in [('brand','Marque',115),('model','Modèle / OS',280),('kind','Type',80),('support','Simulation',170)]:
            table.heading(key,text=title); table.column(key,width=width)
        scrolling=ttk.Scrollbar(dialog,orient='vertical',command=table.yview)
        scrolling.pack(side='right',fill='y')
        table.configure(yscrollcommand=scrolling.set)
        table.pack(fill='both',expand=True,padx=12)
        details=tk.StringVar(value='Choisir un profil. Les OS simulent uniquement les commandes réseau.')
        ttk.Label(dialog,textvariable=details,wraplength=760).pack(fill='x',padx=12,pady=10)
        def refresh(*args):
            table.delete(*table.get_children())
            create.configure(state='disabled')
            for profile in PROFILES.values():
                if (category.get()=='Tous' or profile_role(profile)==category.get()) and query.get().lower() in (profile.brand+' '+profile.model+' '+profile_role(profile)).lower():
                    table.insert('', 'end',iid=profile.id,values=(profile.brand,profile.model,profile_role(profile),'Partielle' if profile.creatable else 'Référence uniquement'))
        def selected(event=None):
            items=table.selection()
            if items:
                profile=PROFILES[items[0]]
                details.set(profile.scope+' '+('OS : commandes réseau uniquement.' if profile.kind=='PC' else ''))
                create.configure(state='normal' if profile.creatable else 'disabled')
        def place():
            if not table.selection():
                return
            profile=PROFILES[table.selection()[0]]
            if not profile.creatable:
                return
            self.set_place(profile.kind)
            self.place_profile=profile.id
            dialog.destroy()
        create=ttk.Button(dialog,text='Placer dans la topologie',command=place,state='disabled')
        create.pack(pady=(0,12))
        table.bind('<<TreeviewSelect>>',selected)
        query.trace_add('write',refresh); category.trace_add('write',refresh); refresh()

    def set_place(self,kind):
        if self.console_focus:
            self.toggle_console_focus()
        self.set_mode('select'); self.place_kind=kind; self.place_profile=''; self.canvas.configure(cursor='crosshair'); self.draw()

    def hit(self):
        found=self.canvas.find_withtag('current')
        tags=self.canvas.gettags(found[0]) if found else ()
        return tags[:2] if tags and tags[0] in ('node','link') else ()

    def select(self,event):
        self.canvas.focus_set()
        hit=self.hit()
        if self.place_kind:
            kind=self.place_kind; profile=PROFILES.get(getattr(self,'place_profile',''))
            role=profile_role(profile) if profile else kind
            prefix={'Serveur':'SRV','Imprimante':'PRN','NAS':'NAS','Caméra':'CAM','Téléphone IP':'TEL','IoT':'IOT','Portable':'LAP','Firewall':'FW'}.get(role,{'PC':'PC','Switch':'SW','Routeur':'R'}[kind]); i=1
            while f'{prefix}{i}' in self.lab.nodes:
                i+=1
            name=f'{prefix}{i}'
            self.lab.add(Node(name,kind,int((event.x-self.panx)/self.zoom),int((event.y-self.pany)/self.zoom),profile=getattr(self,'place_profile','')))
            self.selected,self.selected_link=name,None; self.set_mode('select'); self.changed('Équipement ajouté : '+name)
            return
        if hit and hit[0]=='node':
            name=hit[1]
            if self.mode=='cable':
                if self.anchor is None:
                    self.anchor=name; self.draw()
                else:
                    source=self.anchor; self.anchor=None
                    if source!=name:
                        self.cable_dialog(source,name)
                return
            self.selected,self.selected_link=name,None
            if self.lab.nodes[name].kind=='PC':
                self.source.set(name)
        elif hit:
            self.selected,self.selected_link=None,int(hit[1])
        else:
            self.selected,self.selected_link=None,None
        self.inspect(); self.draw()

    def drag(self,event):
        if self.mode=='select' and not self.place_kind and self.selected in self.lab.nodes:
            n=self.lab.nodes[self.selected]
            n.x=int((event.x-self.panx)/self.zoom); n.y=int((event.y-self.pany)/self.zoom)
            self.dirty=True; self.draw()

    def double_click(self,event):
        hit=self.hit()
        if hit and hit[0]=='node' and self.mode!='cable':
            self.open_management(hit[1])

    def context(self,event):
        self.select(event)
        menu=tk.Menu(self.root,tearoff=False,bg=PANEL,fg=TEXT,activebackground=LINE,activeforeground=TEAL)
        if self.selected:
            menu.add_command(label='Interface web',command=lambda:self.open_web(self.selected))
            menu.add_command(label='Configurer en GUI / CLI',command=lambda:self.open_device(self.selected))
            menu.add_command(label='Ouvrir la console CLI',command=lambda:self.open_cli(self.selected))
        if self.selected or self.selected_link is not None:
            menu.add_command(label='Supprimer la sélection',command=self.delete)
        else:
            for kind in ('PC','Switch','Routeur'):
                menu.add_command(label='Placer '+kind,command=lambda k=kind:self.set_place(k))
        menu.tk_popup(event.x_root,event.y_root)

    def cable_dialog(self,a,b):
        ap,bp=self.lab.available_ports(a),self.lab.available_ports(b)
        if not ap or not bp:
            messagebox.showerror('Câblage','Aucun port disponible sur une extrémité.',parent=self.root); return
        win=tk.Toplevel(self.root); win.title('Nouvelle liaison'); win.configure(bg=PANEL); win.transient(self.root)
        body=tk.Frame(win,bg=PANEL,padx=24,pady=20); body.pack(fill='both',expand=True)
        label(body,a+' ↔ '+b,TEAL,14,True).pack(fill='x',pady=(0,15))
        fields=[]
        for title,values in [(a,ap),(b,bp),('Mode',['access','trunk'])]:
            label(body,title,MUTED,9).pack(fill='x',pady=(7,3))
            var=tk.StringVar(value=values[0]); fields.append(var)
            ttk.Combobox(body,textvariable=var,values=values,state='readonly',width=30).pack(fill='x')
        vlans=tk.StringVar(value=self.view_vlan.get())
        label(body,'VLAN initial (ou liste pour trunk)',MUTED,9).pack(fill='x',pady=(10,3))
        ttk.Entry(body,textvariable=vlans).pack(fill='x')
        label(body,'Configure les deux ports au départ.\nEnsuite chaque extrémité se configure séparément.',MUTED,8).pack(fill='x',pady=12)
        def create():
            try:
                self.lab.connect(a,b,fields[2].get(),vlan_list(vlans.get()),fields[0].get(),fields[1].get())
                win.destroy(); self.changed('Liaison ajoutée'); self.set_mode('select')
            except ValueError as e:
                messagebox.showerror('Câblage',str(e),parent=win)
        button(body,'Créer la liaison',create,True).pack(fill='x',pady=10)

    def open_web(self,node,page='overview'):
        if node not in self.lab.nodes:return
        if getattr(self,'web_portal',None) is None or self.web_portal.closed:
            from .web_portal import WebPortal
            self.web_portal=WebPortal(self)
        self.status.set('Interface web locale prête : '+node)
        return self.web_portal.open(node,page)

    def open_management(self,node):
        if node not in self.lab.nodes:return
        if profile_role(PROFILES[self.lab.nodes[node].profile]) in ('Poste','Portable'):
            return self.open_device(node)
        return self.open_web(node)

    def open_device(self,node):
        if node not in self.lab.nodes:
            return
        from .device_ui import DeviceWindow
        if not hasattr(self,'device_windows'):
            self.device_windows={}
        if node in self.device_windows:
            self.device_windows[node].window.lift()
            return self.device_windows[node]
        window=DeviceWindow(self,node)
        self.device_windows[node]=window
        return window

    def open_cli(self,node):
        if self.topology_focus:
            self.toggle_topology_focus()
        if node not in self.lab.nodes:
            return
        if node not in self.terminals:
            terminal=Terminal(self,node); self.terminals[node]=terminal
            self.dock.add(terminal.frame,text='⌨ '+node)
        terminal=self.terminals[node];self.active_console=node
        self.set_workspace_mode('Consoles')
        self.dock.select(terminal.frame); terminal.entry.focus_set(); terminal.schedule_tail()

    def pan_begin(self,event):
        self.pan_start=(event.x,event.y,self.panx,self.pany)

    def pan_move(self,event):
        if self.pan_start:
            x,y,px,py=self.pan_start; self.panx=px+event.x-x; self.pany=py+event.y-y; self.draw()

    def change_zoom(self,factor):
        old=self.zoom; self.zoom=max(.45,min(1.8,self.zoom*factor))
        cx,cy=self.canvas.winfo_width()/2,self.canvas.winfo_height()/2
        self.panx=cx-(cx-self.panx)*self.zoom/old; self.pany=cy-(cy-self.pany)*self.zoom/old
        self.zoom_label.set(f'{self.zoom:.0%}'); self.draw()

    def fit(self):
        if not self.lab.nodes:
            return
        xs=[n.x for n in self.lab.nodes.values()]; ys=[n.y for n in self.lab.nodes.values()]
        w,h=self.canvas.winfo_width(),self.canvas.winfo_height()
        self.zoom=max(.45,min(1.15,(w-70)/max(220,max(xs)-min(xs)+170),(h-60)/max(200,max(ys)-min(ys)+170)))
        self.panx=w/2-(min(xs)+max(xs))/2*self.zoom; self.pany=h/2-(min(ys)+max(ys))/2*self.zoom
        self.zoom_label.set(f'{self.zoom:.0%}'); self.draw()

    def changed(self,text):
        self.dirty=True; self.invalidate(); self.refresh(); self.status.set(text)

    def invalidate(self,clear_capture=True):
        if clear_capture:
            self.lab.last_micro_capture=None
            self.capture_button.configure(state='disabled')
        self.pause(); self.hops=[]; self.index=0; self.progress=0.; self.result=None
        self.events.delete(*self.events.get_children())
        self.story.show(None)

    def ping(self):
        if self.test_protocol.get()=='icmp':ok,trace=self.lab.ping(self.source.get(),self.destination.get())
        else:ok,trace=self.lab.probe(self.source.get(),self.destination.get(),self.test_protocol.get(),self.test_port.get())
        self.animate_result(ok,trace[-1])

    def animate_result(self,ok,message=''):
        self.invalidate(clear_capture=False); self.result=ok
        capture=getattr(self.lab,'last_micro_capture',None)
        self.capture_button.configure(state='normal' if capture else 'disabled')
        self.story.show(getattr(self.lab,'last_explanation',None))
        request=getattr(self.lab,'last_request',{})
        if request:
            self.source.set(request['source']);self.destination.set(request['destination']);self.test_protocol.set(request['protocol'])
            if request['port']:self.test_port.set(str(request['port']))
        self.set_workspace_mode('Simulation')
        self.dock.select(self.story)
        for j,hops in enumerate(self.lab.last_hops):
            phase='Trames' if capture else 'Aller' if j==0 else 'Retour'
            for position,(i,a,b,v) in enumerate(hops):
                l=self.lab.links[i]
                aport=l.a_port if l.a==a else l.b_port; bport=l.b_port if l.b==b else l.a_port
                proto=getattr(self.lab,'last_protocol','icmp').upper();port=getattr(self.lab,'last_service_port',0)
                detail=proto+(('/'+str(port)) if port else '')+' · parcours simulé / MAC'
                if capture:
                    from .micro_appliances.packets import describe
                    frame=capture.frames[position];packet=describe(frame)
                    detail=f'{frame.time_ms} ms virtuelles · '+packet.get('explanation',packet['protocol'])
                self.events.insert('', 'end',values=(phase,v,a+'/'+aport,b+'/'+bport,detail))
                self.hops.append((i,a,b,v,phase))
        if not ok:
            self.events.insert('', 'end',values=('Échec','','','',message or 'Voir le diagnostic dans la console'),tags=('error',))
        self.status.set(message or ('Chemin accessible' if ok else 'Échec de connectivité'))
        if self.hops:
            self.play()
        self.draw()

    def play(self):
        if self.running or self.index>=len(self.hops):
            return
        self.running=True; self.tick()

    def tick(self):
        self.timer=None
        if not self.running:
            return
        i,a,b,v,phase=self.hops[self.index]
        if self.progress==0:self.explain_hop(a,b,phase)
        self.progress=min(1.,self.progress+.024*self.speed.get())
        self.status.set(f'{phase}  /  {a} → {b}  /  VLAN {v}  /  saut {self.index+1}/{len(self.hops)}')
        self.draw()
        if self.progress>=1:
            self.index+=1; self.progress=0.
        if self.index>=len(self.hops):
            self.finish()
        else:
            self.timer=self.root.after(25,self.tick)

    def pause(self):
        self.running=False
        if self.timer is not None:
            self.root.after_cancel(self.timer); self.timer=None

    def finish(self):
        self.pause()
        if self.story.report:self.story.select(len(self.story.report['steps'])-1)
        self.status.set(('✓ Échange Wasm vérifié' if self.result else '✗ Échange Wasm interrompu') if self.lab.execution_backend=='wasm' else ('✓ Aller / retour accessibles' if self.result else '✗ Parcours interrompu • consulter le diagnostic')); self.draw()

    def step(self):
        self.pause()
        if self.index<len(self.hops):
            _,a,b,v,phase=self.hops[self.index]; self.explain_hop(a,b,phase);self.status.set(f'{phase} / {b} atteint / VLAN {v}')
            self.index+=1; self.progress=0.
            if self.index==len(self.hops):
                self.finish()
            self.draw()

    def explain_hop(self,a,b,phase):
        if self.story.report:
            index=next((i for i,x in enumerate(self.story.report['steps']) if x['title']==a+' → '+b and x['phase']==phase),None)
            if index is not None:self.story.select(index)

    def replay(self):
        self.pause(); self.index=0; self.progress=0.; self.play()

    def inspect_event(self,event):
        selection=self.events.selection()
        if selection:
            values=self.events.item(selection[0],'values')
            self.status.set('  /  '.join(str(v) for v in values if v))
            if self.story.report:
                title=str(values[2]).split('/')[0]+' → '+str(values[3]).split('/')[0]
                index=next((i for i,x in enumerate(self.story.report['steps']) if x['title']==title and x['phase']==values[0]),None)
                if index is not None:self.story.select(index);self.dock.select(self.story)

    def delete(self):
        if not self.selected and self.selected_link is None:
            return
        self.invalidate()
        if self.selected_link is not None:
            self.lab.links.pop(self.selected_link)
        elif self.selected in self.lab.nodes:
            name=self.selected
            self.lab.links=[l for l in self.lab.links if name not in (l.a,l.b)]
            del self.lab.nodes[name]
            if name in self.terminals:
                terminal=self.terminals.pop(name); self.dock.forget(terminal.frame); terminal.frame.destroy()
        self.selected=self.selected_link=None; self.changed('Sélection supprimée')

    def discard(self):
        if not self.dirty:
            return True
        answer=messagebox.askyesnocancel('Projet modifié','Sauvegarder le projet avant de continuer ?',parent=self.root)
        return False if answer is None else self.save() if answer else True

    def replace_lab(self,factory):
        if not self.discard():
            return False
        self.invalidate()
        for terminal in self.terminals.values():
            self.dock.forget(terminal.frame); terminal.frame.destroy()
        self.terminals={}; self.lab=factory(); self.selected=self.selected_link=None; self.path=None; self.dirty=False
        self.set_mode('select'); self.refresh(); self.fit()
        return True

    def new(self):
        self.replace_lab(Lab)

    def save(self):
        path=self.path or filedialog.asksaveasfilename(parent=self.root,defaultextension='.json',filetypes=[('Network LABS','*.json')])
        if not path:
            return False
        try:
            Path(path).write_text(self.lab.dumps(),encoding='utf-8')
            self.path=path; self.dirty=False; self.status.set('Projet sauvegardé : '+Path(path).name); return True
        except OSError as e:
            messagebox.showerror('Sauvegarde',str(e),parent=self.root); return False

    def load(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('Network LABS','*.json')])
        if not path:
            return
        try:
            lab=Lab.loads(Path(path).read_text(encoding='utf-8'))
            if not self.discard():
                return
            self.dirty=False; self.replace_lab(lambda:lab); self.path=path
        except (OSError,ValueError,KeyError,TypeError) as e:
            messagebox.showerror('Projet invalide',str(e),parent=self.root)

    def close(self):
        if self.discard():
            self.pause()
            if getattr(self,'web_portal',None) is not None:self.web_portal.close()
            if self.layout_job is not None:
                self.root.after_cancel(self.layout_job)
            self.root.destroy()

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Network LABS desktop')
    initial=parser.add_mutually_exclusive_group()
    initial.add_argument('--wasm-lan',action='store_true',help='Open the editable LAN project with the Wasm backend selected.')
    initial.add_argument('--fortigate-lab',action='store_true',help='Open the FortiGate policy lab in the local browser (model backend).')
    initial.add_argument('--native-lab',action='store_true',help='Open the native OCI / Firecracker workbench; no automatic startup.')
    args=parser.parse_args()
    root=tk.Tk();app=App(root)
    if args.wasm_lan:app.load_wasm_lab()
    if args.fortigate_lab:app.load_fortigate_lab()
    if args.native_lab:app.open_native_lab()
    root.mainloop()
