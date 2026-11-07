"""Small native rounded surfaces; no extra GUI runtime dependency."""
import base64
import struct
import tkinter as tk
import zlib


def rounded_box(c,x1,y1,x2,y2,r=8,**options):
    r=min(r,(x2-x1)/2,(y2-y1)/2)
    return c.create_polygon(x1+r,y1,x2-r,y1,x2,y1,x2,y1+r,x2,y2-r,x2,y2,x2-r,y2,x1+r,y2,x1,y2,x1,y2-r,x1,y1+r,x1,y1,smooth=True,splinesteps=24,**options)


def surface(root,fill,border,radius=8,size=24):
    """Antialiased RGBA nine-slice element, generated in memory for ttk."""
    rgb=lambda value:tuple(int(value[i:i+2],16) for i in (1,3,5))
    face,edge=rgb(fill),rgb(border);rows=[]
    def inside(x,y,inset):
        left=top=inset;right=bottom=size-inset;r=max(0,radius-inset)
        if not(left<=x<right and top<=y<bottom):return False
        dx=max(left+r-x,0,x-(right-r));dy=max(top+r-y,0,y-(bottom-r))
        return dx*dx+dy*dy<=r*r
    for y in range(size):
        row=bytearray([0])
        for x in range(size):
            count=0;colors=[0,0,0]
            for oy in (.125,.375,.625,.875):
                for ox in (.125,.375,.625,.875):
                    if inside(x+ox,y+oy,0):
                        color=face if inside(x+ox,y+oy,1) else edge
                        count+=1
                        for i in range(3):colors[i]+=color[i]
            row.extend([*(round(v/count) if count else 0 for v in colors),round(255*count/16)])
        rows.append(bytes(row))
    def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',size,size,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')
    return tk.PhotoImage(master=root,data=base64.b64encode(png),format='png')


class SoftCard(tk.Canvas):
    def __init__(self,parent,background,face='#ffffff',border='#e1e9f3'):
        super().__init__(parent,bg=background,height=44,highlightthickness=0,bd=0,cursor='hand2')
        self.face=face;self.edge=border
        self.inner=tk.Frame(self,bg=face)
        self.inner_window=self.create_window(6,5,window=self.inner,anchor='nw')
        self.bind('<Configure>',self.arrange)
        self.inner.bind('<Configure>',lambda event:self.configure(height=self.inner.winfo_reqheight()+10))
        self.paint_id=None
    def arrange(self,event=None):
        w=max(20,self.winfo_width());h=max(20,self.winfo_height())
        if self.paint_id is not None:self.delete(self.paint_id)
        self.paint_id=rounded_box(self,1,1,w-1,h-1,r=10,fill=self.face,outline=self.edge)
        self.tag_lower(self.paint_id)
        self.itemconfigure(self.inner_window,width=max(1,w-12))
    def hover(self,active):
        self.face='#edf5ff' if active else '#ffffff';self.edge='#b7d6fa' if active else '#e1e9f3'
        def recolor(widget):
            widget.configure(bg=self.face)
            for child in widget.winfo_children():recolor(child)
        recolor(self.inner);self.arrange()


class SoftPanel(tk.Canvas):
    def __init__(self,parent,background,face='#ffffff'):
        super().__init__(parent,bg=background,highlightthickness=0,bd=0)
        self.face=face;self.inner=tk.Frame(self,bg=face)
        self.inner_window=self.create_window(6,6,window=self.inner,anchor='nw');self.paint_id=None
        self.bind('<Configure>',self.arrange)
    def arrange(self,event=None):
        w=max(20,self.winfo_width());h=max(20,self.winfo_height())
        if self.paint_id is not None:self.delete(self.paint_id)
        self.paint_id=rounded_box(self,1,1,w-1,h-1,r=12,fill=self.face,outline='#e1e9f3')
        self.tag_lower(self.paint_id);self.itemconfigure(self.inner_window,width=max(1,w-12),height=max(1,h-12))
