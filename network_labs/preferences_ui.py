"""Settings navigation: one section at a time, without nested tab strips."""
import tkinter as tk
from tkinter import ttk

class PreferencesPages(ttk.Frame):
 def __init__(self,parent,skin='generic'):
  super().__init__(parent);self.pages={};self.active=None
  colors={'windows':('#eef3fa','#0067c0'),'linux':('#e9e9e9','#d65c30')}
  background,accent=colors.get(skin,('#f2f5f9','#265ed8'))
  self.nav=tk.Listbox(self,width=23,bg=background,fg='#25354a',selectbackground=accent,selectforeground='white',relief='flat',highlightthickness=0,exportselection=False,font=('DejaVu Sans',10),activestyle='none')
  self.nav.pack(side='left',fill='y',padx=(0,10));self.content=ttk.Frame(self);self.content.pack(fill='both',expand=True)
  self.nav.bind('<<ListboxSelect>>',self.choose)
 def add(self,widget,text):
  self.pages[str(widget)]={'widget':widget,'text':text};self.nav.insert('end',text)
  if self.active is None:self.select(widget)
 def tabs(self):return tuple(self.pages)
 def tab(self,key,option):return self.pages[str(key)][option]
 def select(self,key=None):
  if key is None:return self.active
  if isinstance(key,int):key=list(self.pages)[key]
  key=str(key)
  if self.active:self.pages[self.active]['widget'].pack_forget()
  self.active=key;self.pages[key]['widget'].pack(in_=self.content,fill='both',expand=True)
  index=list(self.pages).index(key);self.nav.selection_clear(0,'end');self.nav.selection_set(index)
 def choose(self,event=None):
  selected=self.nav.curselection()
  if selected:self.select(list(self.pages)[selected[0]])
