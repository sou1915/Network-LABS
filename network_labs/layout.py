"""Screen-aware layout helpers and scrollable side panels."""
import tkinter as tk
from tkinter import ttk


def initial_geometry(screen_width,screen_height):
    width=max(600,min(1420,screen_width-64))
    height=max(360,min(850,screen_height-100))
    return width,height,min(24,max(0,(screen_width-width)//2)),20


def fit_dialog(window,width,height):
    sw,sh=window.winfo_screenwidth(),window.winfo_screenheight()
    width=min(width,max(320,sw-80)); height=min(height,max(280,sh-110))
    x=max(0,(sw-width)//2); y=max(20,(sh-height)//2-30)
    window.geometry(f'{width}x{height}+{x}+{y}')


class ScrollPanel(tk.Frame):
    def __init__(self,parent,bg):
        super().__init__(parent,bg=bg)
        self.canvas=tk.Canvas(self,bg=bg,highlightthickness=0,width=1,height=1)
        self.scroll=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side='right',fill='y'); self.canvas.pack(side='left',fill='both',expand=True)
        self.inner=tk.Frame(self.canvas,bg=bg)
        self.window=self.canvas.create_window(0,0,window=self.inner,anchor='nw')
        self.inner.bind('<Configure>',self.update_region)
        self.canvas.bind('<Configure>',self.resize)
        self.tag='ScrollPanel'+str(id(self))
        self.bind_class(self.tag,'<MouseWheel>',self.wheel)
        self.bind_class(self.tag,'<Button-4>',lambda e:self.wheel_units(-3))
        self.bind_class(self.tag,'<Button-5>',lambda e:self.wheel_units(3))

    def resize(self,event):
        self.canvas.itemconfigure(self.window,width=max(1,event.width))
        self.update_region()

    def update_region(self,event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        self.bind_children(self.inner)

    def bind_children(self,widget):
        tags=widget.bindtags()
        if self.tag not in tags and not isinstance(widget,(tk.Text,ttk.Treeview)):
            widget.bindtags((tags[0],self.tag,*tags[1:]))
        for child in widget.winfo_children():
            self.bind_children(child)

    def wheel_units(self,units):
        self.canvas.yview_scroll(units,'units'); return 'break'

    def wheel(self,event):
        return self.wheel_units(-1 if event.delta>0 else 1)
