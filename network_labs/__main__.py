"""Network LABS desktop workbench. Pure Tk; simulation never executes shell commands."""
import json
import math
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from ipaddress import IPv4Interface, IPv4Address
from pathlib import Path
from .engine import Lab, Node, demo, switching_demo, vlan_list
from .cli import Session, FEATURES
from .layout import ScrollPanel, initial_geometry, fit_dialog

BG='#0a101c'; PANEL='#111d2e'; CARD='#17263a'; LINE='#2b405a'
TEXT='#e3edf9'; MUTED='#91a5c0'; TEAL='#40dfba'; BLUE='#67aafa'; GOLD='#f6c566'; RED='#fb818d'
FONT=('DejaVu Sans',10); MONO=('DejaVu Sans Mono',10)


def label(parent,text,color=TEXT,size=10,bold=False):
    return tk.Label(parent,text=text,bg=parent['bg'],fg=color,font=('DejaVu Sans',size,'bold' if bold else 'normal'),anchor='w',justify='left')


def button(parent,text,command,accent=False):
    return ttk.Button(parent,text=text,command=command,style='Accent.TButton' if accent else 'TButton')


def roundrect(c,x1,y1,x2,y2,r=12,**kw):
    return c.create_polygon(x1+r,y1,x2-r,y1,x2,y1,x2,y1+r,x2,y2-r,x2,y2,x2-r,y2,x1+r,y2,x1,y2,x1,y2-r,x1,y1+r,x1,y1,smooth=True,**kw)

class Terminal:
    """Console with a protected transcript and direct, inline command editing."""
    def __init__(self,app,node):
        self.app=app; self.session=Session(app.lab,node)
        self.history=[]; self.cursor=0
        self.tail_job=None; self.follow_tail=True
        self.frame=tk.Frame(app.dock,bg='#000000')
        bar=tk.Frame(self.frame,bg='#1c2026',padx=9,pady=4); bar.pack(fill='x')
        tk.Label(bar,text=f'{node} — Console 0  |  Local simulation',bg='#1c2026',fg='#a8afb8',font=('DejaVu Sans',9)).pack(side='left')
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
        self.write('Network LABS virtual console\nEducational simulation — no vendor operating system loaded.\n\n')
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
        self.text.delete('prompt_start','end-1c')
        for command in commands:
            self.history.append(command); self.cursor=len(self.history)
            self.write(self.session.prompt+' '+command+'\n')
            result=self.session.execute(command)
            if result:
                self.write(result+'\n')
            if self.session.changed:
                self.app.dirty=True; self.app.invalidate(); self.app.refresh()
            elif command.lower().strip().startswith('ping '):
                self.app.animate_result(not result.startswith(('FAILED','%')),result.splitlines()[-1] if result else ''); self.app.draw()
            if result.startswith('%'):
                break
        self.new_prompt()

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
        label(legend,'● Forwarding',TEAL,9).pack(side='left',padx=6)
        label(legend,'● STP bloqué',GOLD,9).pack(side='left',padx=6)
        label(legend,'● Down',RED,9).pack(side='left',padx=6)
        label(legend,'● Hors VLAN',MUTED,9).pack(side='left',padx=6)
        label(legend,'Double-clic : CLI  ·  F10/F11 : agrandir',MUTED,9).pack(side='right')
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
        self.refresh(); self.open_cli('SW1')
        root.update_idletasks()
        self.fit()
        root.bind('<Configure>',self.window_resized,add='+')
        root.bind('<Destroy>',self.cleanup,add='+')
        self.apply_layout()

    def cleanup(self,event):
        if event.widget==self.root:
            self.pause()
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
                terminal.schedule_tail()

    def style(self):
        s=ttk.Style(self.root); s.theme_use('clam')
        s.configure('.',background=PANEL,foreground=TEXT,font=FONT)
        s.configure('TButton',background='#21334a',foreground=TEXT,padding=(10,8),borderwidth=0)
        s.map('TButton',background=[('active','#304e6c')],foreground=[('disabled',MUTED)])
        s.configure('Small.TButton',padding=(7,7),width=0)
        s.configure('Accent.TButton',background='#147d70',foreground='white')
        s.map('Accent.TButton',background=[('active','#219d88')])
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
        s.map('Treeview',background=[('selected','#254a64')])
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
        for title,callback in [('Sauvegarder',self.save),('Ouvrir',self.load),('Nouveau',self.new)]:
            button(top,title,callback,title=='Sauvegarder').pack(side='right',padx=4)

    def build_sidebar(self):
        parent=self.sidebar.inner
        label(parent,'BIBLIOTHÈQUE',MUTED,9,True).pack(fill='x',padx=14,pady=(17,10))
        for kind,title,subtitle in [('PC','Poste client','IPv4 · ping · CLI'),('Switch','Switch L2','24 ports · VLAN · STP'),('Routeur','Routeur','802.1Q · inter-VLAN')]:
            card=tk.Frame(parent,bg=CARD,padx=10,pady=10,cursor='hand2'); card.pack(fill='x',padx=10,pady=5)
            name=tk.Label(card,text=title,bg=CARD,fg=TEXT,font=('DejaVu Sans',11,'bold'),anchor='w'); name.pack(fill='x')
            sub=tk.Label(card,text=subtitle,bg=CARD,fg=MUTED,font=('DejaVu Sans',8),anchor='w'); sub.pack(fill='x',pady=(4,0))
            for w in (card,name,sub):
                w.bind('<Button-1>',lambda e,k=kind:self.set_place(k))
        label(parent,'OUTILS',MUTED,9,True).pack(fill='x',padx=14,pady=(20,8))
        for title,callback in [('↖  Sélection',lambda:self.set_mode('select')),('⌁  Câbler',lambda:self.set_mode('cable')),('⌨  Ouvrir CLI',lambda:self.open_cli(self.selected)),('Supprimer',self.delete)]:
            button(parent,title,callback).pack(fill='x',padx=10,pady=3)
        label(parent,'LABS INTÉGRÉS',MUTED,9,True).pack(fill='x',padx=14,pady=(22,8))
        for title,factory in [('01  Inter-VLAN',demo),('02  Boucle STP',switching_demo),('03  EtherChannel',self.channel_demo),('04  DHCP / Sécurité',self.security_demo),('05  VTP v2',self.vtp_demo),('06  MST instances',self.mst_demo)]:
            button(parent,title,lambda f=factory:self.replace_lab(f)).pack(fill='x',padx=10,pady=3)
        label(parent,'CLI inspirée IOS\nSimulation pédagogique\nSans VM / sans IOS',MUTED,8).pack(fill='x',padx=14,pady=20)

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
        frame=tk.Frame(self.dock,bg=PANEL)
        self.dock.add(frame,text='Journal des parcours')
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
        ref=tk.Text(self.reference,bg=PANEL,fg=MUTED,font=('DejaVu Sans',9),wrap='word',relief='flat',width=28,height=15)
        ref.pack(fill='both',expand=True)
        ref.insert('1.0',FEATURES+'\n\nEXEMPLE SWITCH\nenable\nconfigure terminal\nvlan 10\nname USERS\nexit\ninterface gi0/1\nswitchport mode access\nswitchport access vlan 10\nno shutdown\nend\nshow vlan brief\n\nEXEMPLE TRUNK\nenable\nconfigure terminal\ninterface gi0/3\nswitchport mode trunk\nswitchport trunk allowed vlan 10,20\nend\nshow interfaces trunk')
        ref.configure(state='disabled')
        test=self.test_panel=tk.Frame(self.inspector_book,bg=CARD,padx=12,pady=12)
        self.inspector_book.add(test,text='Simulation')
        label(test,'TEST / VISUALISATION',TEAL,9,True).pack(fill='x',pady=(0,8))
        self.source=tk.StringVar(value='PC1'); self.destination=tk.StringVar(value='192.168.20.10')
        self.source_box=ttk.Combobox(test,textvariable=self.source,state='readonly',width=24)
        self.source_box.pack(fill='x',pady=3)
        ttk.Entry(test,textvariable=self.destination).pack(fill='x',pady=3)
        button(test,'Lancer le ping simulé',self.ping,True).pack(fill='x',pady=(7,5))
        controls=tk.Frame(test,bg=CARD); controls.pack(fill='x')
        for title,command in [('Lire',self.play),('Pause',self.pause),('Étape',self.step),('Rejouer',self.replay)]:
            ttk.Button(controls,text=title,command=command,style='Small.TButton').pack(side='left',padx=2,expand=True,fill='x')
        self.speed=tk.DoubleVar(value=1.)
        label(test,'Vitesse de lecture',MUTED,8).pack(fill='x',pady=(8,1))
        ttk.Scale(test,from_=0.3,to=3,variable=self.speed).pack(fill='x')
        label(test,'Parcours calculé • pas de timing réel ARP/ICMP',MUTED,8).pack(fill='x',pady=(7,0))

    def refresh(self):
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

    def inspect(self):
        for w in self.inspector.winfo_children():
            w.destroy()
        panel=self.inspector
        if self.selected in self.lab.nodes:
            n=self.lab.nodes[self.selected]
            label(panel,n.hostname or n.name,TEAL,16,True).pack(fill='x',pady=(3,5))
            label(panel,n.kind+'  /  '+n.mac,MUTED,8).pack(fill='x',pady=(0,10))
            button(panel,'Ouvrir la console CLI',lambda:self.open_cli(n.name),True).pack(fill='x',pady=5)
            if n.kind=='PC':
                self.fields={}
                for title,value in [('IPv4 / CIDR',n.address),('Passerelle',n.gateway)]:
                    label(panel,title,MUTED,9).pack(fill='x',pady=(12,4))
                    var=tk.StringVar(value=value); self.fields[title]=var
                    ttk.Entry(panel,textvariable=var).pack(fill='x')
                def apply():
                    try:
                        address=str(IPv4Interface(self.fields['IPv4 / CIDR'].get()))
                        gateway=self.fields['Passerelle'].get().strip()
                        if gateway:
                            IPv4Address(gateway)
                        n.address,n.gateway=address,gateway
                        self.changed('Configuration IPv4 appliquée')
                    except ValueError as e:
                        messagebox.showerror('IPv4',str(e),parent=self.root)
                button(panel,'Appliquer IPv4',apply).pack(fill='x',pady=12)
            elif n.kind=='Switch':
                label(panel,'PORTS PHYSIQUES',MUTED,9,True).pack(fill='x',pady=(14,7))
                port_frame=tk.Frame(panel,bg=PANEL)
                port_frame.pack(fill='both',expand=True)
                ports=ttk.Treeview(port_frame,columns=('port','state','vlan'),show='headings',height=12)
                for col,title,width in [('port','Port',65),('state','État',80),('vlan','VLAN',65)]:
                    ports.heading(col,text=title); ports.column(col,width=width,stretch=True)
                stp=self.lab.stp(int(self.view_vlan.get())).get(n.name,{}).get('ports',{})
                for name,p in n.ports.items():
                    if '.' in name or name.startswith('po'):
                        continue
                    link=self.lab.link_for(n.name,name)
                    state='ERR' if p.errdisabled else 'DOWN' if p.shutdown or (link and not link.enabled) else 'BOUND' if link and self.lab.boundary_reason(link) else 'SUSP' if link and not self.lab.channel_state(link)[0] else stp.get(name,('','UP'))[1] if link else 'libre'
                    operational=self.lab.operational_mode(link,n.name) if link else p.mode
                    ports.insert('', 'end',iid=name,values=(name,state,'trunk' if operational=='trunk' else p.access_vlan),tags=('bad',) if state in ('ERR','DOWN','BLK','BOUND','SUSP') else ())
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
                label(panel,'Configurer dans la console :\ninterface gi0/0.10\nencapsulation dot1Q 10\nip address 192.168.10.1/24',MUTED,9).pack(fill='x',pady=15)
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
            label(panel,'Choisir un équipement dans\nla bibliothèque puis cliquer\ndans la topologie.\n\nDouble-clic sur un équipement\npour ouvrir sa console.\n\nCâbler : cliquer sur les deux\néquipements à connecter.',MUTED,10).pack(fill='x')

    def edit_port(self,node,name):
        n=self.lab.nodes[node]; p=n.ports[name]
        win=tk.Toplevel(self.root); win.title(f'Interface / {node} / {name}')
        win.configure(bg=PANEL); win.transient(self.root); fit_dialog(win,480,620)
        label(win,f'{node} / {name}',TEAL,15,True).pack(fill='x',padx=22,pady=18)
        scroller=ScrollPanel(win,PANEL); scroller.pack(fill='both',expand=True)
        body=scroller.inner; body.configure(padx=22)
        fields={}
        for title,value in [('Description',p.description),('Mode',p.mode),('VLAN access',str(p.access_vlan)),('VLAN natif',str(p.native_vlan)),('VLAN autorisés',Session.compact(p.allowed)),('Coût STP',str(p.cost))]:
            label(body,title,MUTED,9).pack(fill='x',pady=(8,3))
            var=tk.StringVar(value=value); fields[title]=var
            if title=='Mode':
                ttk.Combobox(body,textvariable=var,values=['access','trunk','dynamic auto','dynamic desirable'],state='readonly').pack(fill='x')
            else:
                ttk.Entry(body,textvariable=var).pack(fill='x')
        admin=tk.BooleanVar(value=not p.shutdown)
        ttk.Checkbutton(body,text='Port administrativement actif',variable=admin).pack(anchor='w',pady=14)
        label(body,'STP / EtherChannel / sécurité : commandes CLI',MUTED,9).pack(fill='x')
        def apply():
            try:
                access=vlan_list(fields['VLAN access'].get()); native=vlan_list(fields['VLAN natif'].get())
                allowed=vlan_list(fields['VLAN autorisés'].get()); cost=int(fields['Coût STP'].get())
                if len(access)!=1 or len(native)!=1 or not 1<=cost<=200000000:
                    raise ValueError('VLAN ou coût invalide.')
                mode=fields['Mode'].get()
                if (p.security or p.source_guard) and mode!='access':
                    raise ValueError('Désactiver port-security avant le mode trunk.')
                if mode.startswith('dynamic') and p.nonegotiate:
                    raise ValueError('Désactiver nonegotiate dans la CLI avant le mode dynamique.')
                if n.kind=='Switch' and n.vtp_mode=='client' and str(access[0]) not in n.vlans:
                    raise ValueError('VLAN absent du client VTP.')
                p.description=fields['Description'].get(); p.mode=mode; p.access_vlan=access[0]; p.native_vlan=native[0]; p.allowed=allowed; p.cost=cost; p.shutdown=not admin.get()
                if admin.get():
                    p.errdisabled=False
                if n.kind=='Switch' and str(access[0]) not in n.vlans:
                    n.vlans[str(access[0])]=f'VLAN{access[0]:04}'
                    self.lab.vlan_changed(n.name)
                self.lab.sync_vtp()
                win.destroy(); self.changed('Port configuré : '+node+'/'+name)
            except ValueError as e:
                messagebox.showerror('Configuration',str(e),parent=win)
        button(win,'Appliquer la configuration',apply,True).pack(side='bottom',before=scroller,fill='x',padx=22,pady=15)

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
                c.create_oval(x,y,x+1,y+1,fill='#243246',outline='')
        vlan=int(self.view_vlan.get() or 1)
        states=self.lab.stp(vlan)
        for i,l in enumerate(self.lab.links):
            pa,pb=self.lab.ends(l)
            eligible=self.lab.eligible(l,vlan)
            blocked=any(states.get(n,{}).get('ports',{}).get(p,('',''))[1]=='BLK' for n,p in ((l.a,l.a_port),(l.b,l.b_port)))
            physically_down=bool(self.lab.boundary_reason(l)) or not l.enabled or pa.shutdown or pb.shutdown or pa.errdisabled or pb.errdisabled or not self.lab.channel_state(l)[0]
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
            roundrect(c,x-width/2+3,y-height/2+5,x+width/2+3,y+height/2+5,r=12*z,fill='#050b13',outline='',tags=tags)
            roundrect(c,x-width/2,y-height/2,x+width/2,y+height/2,r=12*z,fill=CARD,outline=TEAL if self.selected==n.name or self.anchor==n.name else LINE,width=2 if self.selected==n.name else 1,tags=tags)
            color=BLUE if n.kind=='PC' else TEAL if n.kind=='Switch' else '#bb9aff'
            self.icon(n.kind,x,y-8*z,z,color,tags)
            c.create_text(x,y+31*z,text=n.hostname or n.name,fill=TEXT,font=('DejaVu Sans',max(8,int(10*z)),'bold'),tags=tags)
            if z>=.7:
                c.create_text(x,y+63*z,text=n.address if n.kind=='PC' else 'L2 • 24 ports' if n.kind=='Switch' else 'Router-on-a-stick',fill=MUTED,font=('DejaVu Sans',max(7,int(8*z))),tags=tags)
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
            c.create_text(x,y-27,text=f'{phase} · VLAN {v}',fill=color,font=('DejaVu Sans',9,'bold'))
        if not self.lab.nodes:
            c.create_text(w/2,h/2,text='Construisez votre premier lab\nChoisir un équipement à gauche, puis cliquer ici.',fill=MUTED,font=('DejaVu Sans',14),justify='center')
        if self.mode=='cable':
            c.create_text(15,18,text='CÂBLAGE  /  '+(self.anchor+' → destination' if self.anchor else 'Choisir le premier équipement'),fill=GOLD,anchor='w',font=('DejaVu Sans',10,'bold'))
        elif self.place_kind:
            c.create_text(15,18,text='PLACER  /  '+self.place_kind+' · cliquer dans la topologie',fill=TEAL,anchor='w',font=('DejaVu Sans',10,'bold'))

    def icon(self,kind,x,y,z,color,tags):
        c=self.canvas
        if kind=='PC':
            c.create_rectangle(x-23*z,y-17*z,x+23*z,y+11*z,outline=color,width=2,tags=tags)
            c.create_rectangle(x-18*z,y-12*z,x+18*z,y+6*z,fill='#142e45',outline='',tags=tags)
            c.create_line(x,y+11*z,x,y+18*z,fill=color,width=2,tags=tags)
            c.create_line(x-12*z,y+18*z,x+12*z,y+18*z,fill=color,width=2,tags=tags)
        elif kind=='Switch':
            roundrect(c,x-32*z,y-13*z,x+32*z,y+12*z,r=5*z,fill='#133a3d',outline=color,width=2,tags=tags)
            for j in range(6):
                xx=x-24*z+j*9*z
                c.create_rectangle(xx,y-4*z,xx+5*z,y+3*z,outline=color,tags=tags)
            c.create_line(x-12*z,y-20*z,x+12*z,y-20*z,arrow='last',fill=color,tags=tags)
        else:
            c.create_oval(x-25*z,y-22*z,x+25*z,y+22*z,outline=color,width=2,fill='#302841',tags=tags)
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                c.create_line(x+dx*3*z,y+dy*3*z,x+dx*17*z,y+dy*15*z,fill=color,width=2,arrow='last',tags=tags)

    def set_mode(self,mode):
        self.mode=mode; self.anchor=None; self.place_kind=None
        self.canvas.configure(cursor='crosshair' if mode=='cable' else '')
        self.status.set('Câbler : cliquer sur deux équipements' if mode=='cable' else 'Sélection / déplacement')
        self.draw()

    def set_place(self,kind):
        if self.console_focus:
            self.toggle_console_focus()
        self.set_mode('select'); self.place_kind=kind; self.canvas.configure(cursor='crosshair'); self.draw()

    def hit(self):
        found=self.canvas.find_withtag('current')
        tags=self.canvas.gettags(found[0]) if found else ()
        return tags[:2] if tags and tags[0] in ('node','link') else ()

    def select(self,event):
        self.canvas.focus_set()
        hit=self.hit()
        if self.place_kind:
            kind=self.place_kind; prefix={'PC':'PC','Switch':'SW','Routeur':'R'}[kind]; i=1
            while f'{prefix}{i}' in self.lab.nodes:
                i+=1
            name=f'{prefix}{i}'
            self.lab.add(Node(name,kind,int((event.x-self.panx)/self.zoom),int((event.y-self.pany)/self.zoom)))
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
            self.open_cli(hit[1])

    def context(self,event):
        self.select(event)
        menu=tk.Menu(self.root,tearoff=False,bg=PANEL,fg=TEXT,activebackground=LINE,activeforeground=TEAL)
        if self.selected:
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

    def open_cli(self,node):
        if self.topology_focus:
            self.toggle_topology_focus()
        if node not in self.lab.nodes:
            return
        if node not in self.terminals:
            terminal=Terminal(self,node); self.terminals[node]=terminal
            self.dock.add(terminal.frame,text='⌨ '+node)
        terminal=self.terminals[node]
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

    def invalidate(self):
        self.pause(); self.hops=[]; self.index=0; self.progress=0.; self.result=None
        self.events.delete(*self.events.get_children())

    def ping(self):
        ok,trace=self.lab.ping(self.source.get(),self.destination.get())
        self.animate_result(ok,trace[-1])

    def animate_result(self,ok,message=''):
        self.invalidate(); self.result=ok
        for j,hops in enumerate(self.lab.last_hops):
            phase='Aller' if j==0 else 'Retour'
            for i,a,b,v in hops:
                l=self.lab.links[i]
                aport=l.a_port if l.a==a else l.b_port; bport=l.b_port if l.b==b else l.a_port
                self.events.insert('', 'end',values=(phase,v,a+'/'+aport,b+'/'+bport,'Parcours calculé • apprentissage MAC simplifié'))
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
        self.pause(); self.status.set('✓ Aller / retour accessibles' if self.result else '✗ Parcours interrompu • consulter le diagnostic'); self.draw()

    def step(self):
        self.pause()
        if self.index<len(self.hops):
            _,a,b,v,phase=self.hops[self.index]; self.status.set(f'{phase} / {b} atteint / VLAN {v}')
            self.index+=1; self.progress=0.
            if self.index==len(self.hops):
                self.finish()
            self.draw()

    def replay(self):
        self.pause(); self.index=0; self.progress=0.; self.play()

    def inspect_event(self,event):
        selection=self.events.selection()
        if selection:
            values=self.events.item(selection[0],'values')
            self.status.set('  /  '.join(str(v) for v in values if v))

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
            return
        self.invalidate()
        for terminal in self.terminals.values():
            self.dock.forget(terminal.frame); terminal.frame.destroy()
        self.terminals={}; self.lab=factory(); self.selected=self.selected_link=None; self.path=None; self.dirty=False
        self.set_mode('select'); self.refresh(); self.fit()

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
            if self.layout_job is not None:
                self.root.after_cancel(self.layout_job)
            self.root.destroy()

if __name__=='__main__':
    root=tk.Tk(); App(root); root.mainloop()
