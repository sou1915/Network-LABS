"""Preview/validate/apply workflow for text labs and per-device CLI files."""
from pathlib import Path
import tkinter as tk
from .theme import PANEL,BG,TEXT,MUTED
from tkinter import ttk,filedialog,messagebox
from .text_lab import parse_lab,import_device_config,export_lab,LabTextError
from .layout import fit_dialog

class ImportDialog:
    def __init__(self,app,device_mode=False):
        self.app=app; self.result=None; self.signature=None
        self.window=win=tk.Toplevel(app.root)
        win.title('Importer une configuration texte / Network LABS'); win.configure(bg=PANEL); win.transient(app.root)
        fit_dialog(win,1080,650)
        win.grab_set()
        top=tk.Frame(win,bg=PANEL,padx=12,pady=12); top.pack(fill='x')
        self.mode=tk.StringVar(value='CLI équipement' if device_mode else 'Créer un lab')
        self.target=tk.StringVar(value=app.selected if app.selected in app.lab.nodes else next(iter(app.lab.nodes),''))
        mode=ttk.Combobox(top,textvariable=self.mode,values=['Créer un lab','CLI équipement'],state='readonly',width=19)
        mode.pack(side='left',padx=4); mode.bind('<<ComboboxSelected>>',lambda e:self.invalidate())
        target=ttk.Combobox(top,textvariable=self.target,values=list(app.lab.nodes),state='readonly',width=13)
        target.pack(side='left',padx=4); target.bind('<<ComboboxSelected>>',lambda e:self.invalidate())
        ttk.Button(top,text='Ouvrir .txt',command=self.load).pack(side='right',padx=4)
        ttk.Button(top,text='Exemple',command=self.sample).pack(side='right',padx=4)
        bottom=tk.Frame(win,bg=PANEL,padx=12,pady=10); bottom.pack(side='bottom',fill='x')
        self.summary=tk.StringVar(value='Éditer ou ouvrir un fichier, puis Valider.')
        tk.Label(bottom,textvariable=self.summary,bg=PANEL,fg=MUTED,anchor='w',width=1).pack(side='left',fill='x',expand=True)
        self.apply_button=ttk.Button(bottom,text='Appliquer au logiciel',command=self.apply,state='disabled',style='Accent.TButton')
        self.apply_button.pack(side='right',padx=4)
        ttk.Button(bottom,text='Valider / Aperçu',command=self.validate).pack(side='right',padx=4)
        self.report=tk.Text(win,height=3,bg=BG,fg=TEXT,font=('DejaVu Sans',9),relief='flat',wrap='word',padx=12,pady=6,state='disabled')
        self.report.pack(side='bottom',fill='x',padx=12)
        panes=ttk.Panedwindow(win,orient='horizontal'); panes.pack(fill='both',expand=True,padx=12,pady=(0,8))
        editing=tk.Frame(panes,bg='black'); panes.add(editing,weight=3)
        self.gutter=tk.Canvas(editing,width=45,bg='#0c1018',highlightthickness=0)
        self.gutter.pack(side='left',fill='y')
        self.editor=tk.Text(editing,bg='black',fg='#d5d5d5',insertbackground='white',font=('DejaVu Sans Mono',10),wrap='none',undo=True,padx=9,pady=8,height=12)
        scroll=ttk.Scrollbar(editing,command=self.editor.yview); scroll.pack(side='right',fill='y')
        def scrolled(first,last):
            scroll.set(first,last); self.line_numbers()
        self.editor.configure(yscrollcommand=scrolled)
        self.editor.pack(side='top',fill='both',expand=True)
        xscroll=ttk.Scrollbar(editing,orient='horizontal',command=self.editor.xview)
        xscroll.pack(side='bottom',fill='x'); self.editor.configure(xscrollcommand=xscroll.set)
        self.editor.tag_configure('errorline',background='#512631')
        self.editor.bind('<<Modified>>',self.modified)
        self.editor.bind('<Configure>',lambda e:self.line_numbers())
        preview=tk.Frame(panes,bg=PANEL,width=235); panes.add(preview,weight=1)
        ttk.Label(preview,text='Aperçu du lab validé',padding=8).pack(fill='x')
        self.preview=ttk.Treeview(preview,columns=('type','name'),show='headings',height=10)
        self.preview.heading('type',text='Type'); self.preview.heading('name',text='Équipement')
        self.preview.column('type',width=85); self.preview.column('name',width=120)
        self.preview.pack(fill='both',expand=True)
        self.sample()
        self.editor.focus_set()

    def line_numbers(self):
        self.gutter.delete('all')
        index=self.editor.index('@0,0')
        while True:
            info=self.editor.dlineinfo(index)
            if info is None:
                break
            self.gutter.create_text(38,info[1],anchor='ne',text=index.split('.')[0],fill='#718399',font=('DejaVu Sans Mono',9))
            index=self.editor.index(index+'+1line')

    def invalidate(self):
        self.result=None; self.signature=None; self.apply_button.configure(state='disabled')
        self.summary.set('Texte modifié • validation nécessaire')
        self.preview.delete(*self.preview.get_children())

    def modified(self,event=None):
        if self.editor.edit_modified():
            self.editor.edit_modified(False); self.invalidate(); self.line_numbers()

    def set_text(self,text):
        self.editor.delete('1.0','end'); self.editor.insert('1.0',text); self.editor.edit_modified(False)
        self.invalidate(); self.line_numbers()

    def load(self):
        path=filedialog.askopenfilename(parent=self.window,filetypes=[('Texte / configuration','*.txt *.cfg *.conf'),('Tous les fichiers','*')])
        if path:
            try:
                self.set_text(Path(path).read_text(encoding='utf-8-sig'))
            except (OSError,UnicodeError) as e:
                messagebox.showerror('Lecture du fichier UTF-8',str(e),parent=self.window)

    def sample(self):
        if self.mode.get()=='Créer un lab':
            path=Path(__file__).resolve().parent.parent/'examples'/'inter_vlan.lab.txt'
            try:
                self.set_text(path.read_text(encoding='utf-8'))
            except OSError:
                self.set_text('[devices]\nPC1 PC\nSW1 Switch\n\n[links]\nPC1:eth0 SW1:gi0/1\n\n[config PC1]\nip address 192.168.1.10/24\n')
        else:
            node=self.app.lab.nodes.get(self.target.get())
            sample='ip address 192.168.10.10/24\nip gateway 192.168.10.1\n' if node and node.kind=='PC' else 'interface gi0/0.10\nencapsulation dot1Q 10\nip address 192.168.10.1/24\nend\n' if node and node.kind=='Routeur' else 'vlan 10\nname USERS\nexit\ninterface gi0/1\nswitchport mode access\nswitchport access vlan 10\nno shutdown\nend\n'
            self.set_text(sample)

    def report_text(self,text):
        self.report.configure(state='normal'); self.report.delete('1.0','end'); self.report.insert('1.0',text); self.report.configure(state='disabled')

    def validate(self):
        self.editor.edit_modified(False); self.editor.tag_remove('errorline','1.0','end')
        text=self.editor.get('1.0','end-1c')
        self.invalidate()
        try:
            result=parse_lab(text) if self.mode.get()=='Créer un lab' else import_device_config(text,self.app.lab,self.target.get())
        except LabTextError as e:
            self.report_text(str(e))
            self.summary.set(f'{len(e.issues)} erreur(s) • aucun changement appliqué')
            for issue in e.issues:
                self.editor.tag_add('errorline',f'{issue.line}.0',f'{issue.line}.end')
            if e.issues:
                self.editor.see(f'{e.issues[0].line}.0')
            return False
        self.result=result; self.signature=(text,self.mode.get(),self.target.get())
        for n in result.lab.nodes.values():
            self.preview.insert('', 'end',values=(n.kind,n.hostname or n.name))
        self.report_text('Validation réussie.\n'+'\n'.join(result.warnings))
        self.summary.set(result.summary)
        self.apply_button.configure(state='normal')
        return True

    def apply(self):
        current=(self.editor.get('1.0','end-1c'),self.mode.get(),self.target.get())
        if self.result is None or self.signature!=current:
            self.invalidate(); return
        previous_path=self.app.path
        if self.app.replace_lab(lambda:self.result.lab) is False:
            return
        self.app.path=previous_path if self.mode.get()=='CLI équipement' else None
        self.app.dirty=True; self.app.status.set('Import texte appliqué : '+self.result.summary)
        self.window.destroy()


def export_dialog(app):
    path=filedialog.asksaveasfilename(parent=app.root,defaultextension='.lab.txt',filetypes=[('Lab texte','*.lab.txt')])
    if path:
        try:
            Path(path).write_text(export_lab(app.lab),encoding='utf-8')
            app.status.set('Lab exporté : '+Path(path).name)
        except OSError as e:
            messagebox.showerror('Export texte',str(e),parent=app.root)
