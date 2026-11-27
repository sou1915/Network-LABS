"""The workbench's packet trace: a path through the project, step by step and animated. A mixin of ui.ApplianceWindow."""
import tkinter as tk
from tkinter import ttk
from .reference_theme import BG, TEXT, MUTED


class PacketTrace:
    def build_trace_form(self,parent):
        """Follow one real ping across the lab: every link is recorded, then the packet is replayed on the topology."""
        self.label(parent,'Suivre un paquet',TEXT,11,True).pack(anchor='w',padx=14,pady=(18,4))
        self.label(parent,'Depuis le nœud sélectionné, vers l’adresse IPv4',MUTED,9).pack(anchor='w',padx=14)
        self.trace_destination=tk.StringVar()
        ttk.Entry(parent,textvariable=self.trace_destination,style='Native.TEntry').pack(fill='x',padx=14,pady=4)
        self.trace_button=ttk.Button(parent,text='Envoyer un ping et le suivre',command=self.trace_packet,style='Native.TButton')
        self.trace_button.pack(fill='x',padx=14,pady=(4,2))
        note=('Chaque câble est enregistré pendant un ping réel ; l’animation rejoue ce que chaque fil a porté '
              '(adresses, étiquette VLAN, NAT). Authentification sudo dans le terminal.')
        tk.Label(parent,text=note,bg=BG,fg=MUTED,font=(self.font,8),justify='left',wraplength=275).pack(fill='x',padx=14,pady=(2,10))
        self.trace_after=None

    def trace_packet(self):
        selected=self.nodes.selection()
        node=next((n for n in self.graph['nodes'] if selected and n['name']==selected[0]),None)
        try:
            import ipaddress
            ipaddress.IPv4Address(self.trace_destination.get().strip())
            if not node or self.states.get(node['name'],{}).get('status')!='running':
                raise ValueError('Démarrer le lab, actualiser son état et sélectionner le nœud source.')
            if self.manifest()['name']!=self.view_lab:
                raise ValueError('Le projet et le laboratoire observé diffèrent.')
        except (ValueError,TypeError,KeyError) as error:
            self.error(error)
            return False
        return self.launch('trace')

    def trace_steps(self,data):
        """Each recorded crossing with the direction it went: the walk starts at the source node."""
        steps,current,previous=[],data['source'],{}
        for hop in data['hops']:
            a,b=hop['endpoints']
            if a[0]==current:
                start,end=a,b
            elif b[0]==current:
                start,end=b,a
            else:
                start,end=a,b
            seen=previous.get(hop['type'])
            nat=seen and (seen['source'],seen['destination'])!=(hop['source'],hop['destination'])
            steps.append(dict(hop,start=start,end=end,nat=bool(nat)))
            previous[hop['type']]=hop
            current=end[0]
        return steps

    def animate_trace(self,data):
        if self.trace_after is not None:
            try:
                self.window.after_cancel(self.trace_after)
            except tk.TclError:
                pass
        self.canvas.delete('trace')
        steps=self.trace_steps(data)
        lines=[f"Ping {data['source']} → {data['destination']} : {'réponse reçue' if data['answered'] else 'pas de réponse'}",'',
               f"{'#':>2}  {'t (ms)':>7}  {'Type':<8} {'VLAN':<5} {'Câble':<24} Sur le fil"]
        for number,step in enumerate(steps,1):
            cable=f"{step['start'][0]}:{step['start'][1]} → {step['end'][0]}:{step['end'][1]}"
            wire=f"{step['source']} → {step['destination']}"+(' (NAT)' if step['nat'] else '')
            kind='requête' if step['type']=='request' else 'réponse'
            lines.append(f"{number:>2}  {step['time_ms']:>7}  {kind:<8} {str(step['vlan'] or '—'):<5} {cable:<24} {wire}")
        if not steps:
            lines.append('Aucun câble n’a porté ce ping : vérifier la source, la destination et les routes.')
        self.write_output('\n'.join(lines),data,'Trajet du paquet')
        self.dock.select(self.output_tab)
        frames=22

        def frame(index,tick):
            self.canvas.delete('trace')
            if index>=len(steps):
                self.trace_after=None
                return
            step=steps[index]
            shape=self.link_shapes.get(step['link'])
            if shape is None:
                return frame(index+1,0)
            points=self.canvas.coords(shape)
            pairs=list(zip(points[0::2],points[1::2]))
            a=step['endpoints'][0]
            if step['start']!=a:
                pairs.reverse()
            lengths=[((x2-x1)**2+(y2-y1)**2)**.5 for (x1,y1),(x2,y2) in zip(pairs,pairs[1:])]
            target=sum(lengths)*tick/frames
            x,y=pairs[0]
            for ((x1,y1),(x2,y2)),length in zip(zip(pairs,pairs[1:]),lengths):
                if target<=length and length:
                    x,y=x1+(x2-x1)*target/length,y1+(y2-y1)*target/length
                    break
                target-=length
                x,y=x2,y2
            colour='#ff8a1f' if step['type']=='request' else '#21c66b'
            self.canvas.create_oval(x-11,y-11,x+11,y+11,fill='',outline=colour,width=2,tags=('trace',))
            self.canvas.create_oval(x-6,y-6,x+6,y+6,fill=colour,outline='white',width=2,tags=('trace',))
            text=f"{'requête' if step['type']=='request' else 'réponse'} · {step['source']} → {step['destination']}"
            text+=(f" · VLAN {step['vlan']}" if step['vlan'] else '')+(' · NAT' if step['nat'] else '')
            label=self.canvas.create_text(x+14,y-14,text=text,anchor='w',fill='#13324b',font=(self.font,8,'bold'),tags=('trace',))
            box=self.canvas.bbox(label)
            backing=self.canvas.create_rectangle(box[0]-5,box[1]-3,box[2]+5,box[3]+3,fill='white',outline=colour,tags=('trace',))
            self.canvas.tag_lower(backing,label)
            following=(index,tick+1) if tick<frames else (index+1,0)
            self.trace_after=self.window.after(35,lambda:frame(*following))

        frame(0,0)
