"""Readable simulation story with selectable steps and technical evidence."""
import tkinter as tk
from tkinter import ttk
from .theme import PANEL,TEXT,MUTED,BLUE,RED,TEAL,LINE

class ExplanationPanel(ttk.Frame):
 def __init__(self,parent):
  super().__init__(parent,padding=10);self.report=None;self.current=0
  self.heading=tk.StringVar(value='Comprendre la simulation')
  self.summary=tk.StringVar(value='Lancer un test depuis l’onglet Simulation : ce panneau expliquera les décisions du moteur.')
  ttk.Label(self,textvariable=self.heading,font=('DejaVu Sans',12,'bold')).pack(anchor='w')
  summary=ttk.Label(self,textvariable=self.summary,wraplength=700);summary.pack(fill='x',pady=(3,9))
  self.bind('<Configure>',lambda ev:summary.configure(wraplength=max(180,ev.width-25)))
  split=ttk.Panedwindow(self,orient='horizontal');split.pack(fill='both',expand=True)
  left=ttk.Frame(split);split.add(left,weight=1)
  self.steps=tk.Listbox(left,bg=PANEL,fg=TEXT,selectbackground=BLUE,selectforeground='white',relief='flat',highlightthickness=1,highlightbackground=LINE,width=30,height=6,exportselection=False,font=('DejaVu Sans',9))
  scroll=ttk.Scrollbar(left,command=self.steps.yview);self.steps.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.steps.pack(fill='both',expand=True)
  self.steps.bind('<<ListboxSelect>>',lambda ev:self.select(self.steps.curselection()[0]) if self.steps.curselection() else None)
  right=ttk.Frame(split);split.add(right,weight=2)
  self.body=tk.Text(right,bg=PANEL,fg=TEXT,wrap='word',relief='flat',height=6,width=35,padx=14,pady=8,font=('DejaVu Sans',10),state='disabled')
  sb=ttk.Scrollbar(right,command=self.body.yview);self.body.configure(yscrollcommand=sb.set);sb.pack(side='right',fill='y');self.body.pack(fill='both',expand=True)
  self.body.tag_configure('title',font=('DejaVu Sans',11,'bold'),foreground=BLUE,spacing3=10)
  self.body.tag_configure('evidence',foreground=MUTED,spacing1=12)
  controls=ttk.Frame(self);controls.pack(fill='x',pady=(8,0))
  self.previous=ttk.Button(controls,text='← Décision précédente',command=lambda:self.select(self.current-1));self.previous.pack(side='left')
  self.following=ttk.Button(controls,text='Décision suivante →',command=lambda:self.select(self.current+1));self.following.pack(side='right')
  self.show(None)
 def show(self,report):
  self.report=report;self.steps.delete(0,'end');self.current=0
  if not report:
   self.heading.set('Comprendre la simulation');self.summary.set('Lancer un test pour consulter le parcours et les décisions du moteur.')
   self.write('Aucun test courant.','Les explications afficheront les faits calculés et distingueront les pistes de vérification.');self.previous.state(['disabled']);self.following.state(['disabled']);return
  self.heading.set(('✓ ' if report['ok'] else '✕ ')+report['title']);self.summary.set(report['summary'])
  for step in report['steps']:self.steps.insert('end',f'{step["number"]:02} · {step["phase"]} · {step["title"]}')
  self.select(0)
 def write(self,title,body,evidence=''):
  self.body.configure(state='normal');self.body.delete('1.0','end');self.body.insert('end',title+'\n','title');self.body.insert('end',body)
  if evidence:self.body.insert('end','\n\n'+evidence,'evidence')
  self.body.configure(state='disabled');self.body.yview_moveto(0)
 def select(self,index):
  if not self.report:return
  self.current=max(0,min(index,len(self.report['steps'])-1));step=self.report['steps'][self.current]
  body=step['body'];evidence=step['evidence']
  if self.current==len(self.report['steps'])-1:
   if self.report['checks']:body+='\n\nÀ vérifier :\n'+'\n'.join('• '+text for text in self.report['checks'])
   evidence=self.report['limits']
  self.write(step['title'],body,evidence);self.steps.selection_clear(0,'end');self.steps.selection_set(self.current);self.steps.see(self.current)
  self.previous.state(['disabled'] if self.current==0 else ['!disabled']);self.following.state(['disabled'] if self.current==len(self.report['steps'])-1 else ['!disabled'])
