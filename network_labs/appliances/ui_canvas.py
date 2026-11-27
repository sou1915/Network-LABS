"""The workbench's topology canvas: drawing the devices and cables, selection, zoom and pan. A mixin of ui.ApplianceWindow."""
from .soft_widgets import rounded_box
from .reference_theme import MUTED
from .native_models import port_label
from .workspace_art import port_offset, access_vlans, auto_layout, layout_bounds, networks, firewall_hosts, link_caption, draw_port_labels
from .workspace_art import vlan_groups
from .design import CANVAS
from . import studio_art
from .ui_bridge import public_topology, validate_topology


class TopologyCanvas:
    def refit_topology(self):
        if self.closed or not getattr(self,'graph',None):
            return
        self.draw(self.graph,self.states)
        if self.zoom==1. and not getattr(self,'view_moved',False):
            self.view_origin(0,0)

    def resize_graph(self,event=None):
        if hasattr(self,'graph'):
            self.draw(self.graph,self.states)

    def draw(self,graph,states=None):
        validate_topology(graph)
        selected=self.nodes.selection()
        previous=selected[0] if selected else None
        destination=self.destination.get()
        self.graph=graph
        self.view_lab=graph['name']
        self.states=states or {}
        self.node_shapes={}
        self.link_shapes={}
        self.canvas.delete('all')
        self.nodes.delete(*self.nodes.get_children())
        self.library.delete(*[n['name'] for n in getattr(self,'library_graph',{}).get('nodes',[]) if self.library.exists(n['name'])])
        self.library_graph=graph
        width=max(600,self.canvas.winfo_width())
        height=max(360,self.canvas.winfo_height())
        spec=None
        members={}
        try:
            candidate=self.manifest()
            if public_topology(candidate)==graph:
                spec=candidate
                members=access_vlans(graph,spec)
        except (ValueError,TypeError,KeyError):pass
        config={n['name']:n for n in spec['nodes']} if spec else {}
        positions=auto_layout(graph,members,width)
        positions.update({name:point for name,point in self.positions.items() if name in positions})
        self.drawn_positions=positions
        for xx in range(-142,int(width/max(.65,self.zoom))+160,22):
            for yy in range(-142,int(height/max(.65,self.zoom))+160,22):
                self.canvas.create_oval(xx,yy,xx+1,yy+1,fill=CANVAS['grid'],outline='',tags=('grid',))
        if not graph['nodes']:
            # A blank project says how to begin, as an empty Packet Tracer workspace invites a first device.
            where='le dock, en bas'
            self.canvas.create_text(width/2,height/2-24,text='Cliquer ou glisser un équipement depuis '+where,
                                    fill=MUTED,font=(self.font,13,'bold'),tags=('hint',))
            cable='l’outil câble de la barre d’outils'  # the toolbar's second tool
            self.canvas.create_text(width/2,height/2+6,text='puis '+cable+' : deux clics · ▶ Démarrer · double-clic : '
                                    'le terminal de l’équipement',fill=MUTED,font=(self.font,10),tags=('hint',))
        palette=CANVAS['vlans']
        self.vlan_members=members
        captions=[]
        groups=vlan_groups(graph,members)
        for index,(vid,names) in enumerate(groups):
            points=[positions[n] for n in names]
            spread=max(x for x,y in points)-min(x for x,y in points)+104
            # Laid-out sites (tree layout or moved by hand): a box hugs its hosts and never covers a neighbour's.
            span=spread
            middle=(min(x for x,y in points)+max(x for x,y in points))/2
            x1=middle-span/2
            x2=middle+span/2
            # Keep the group inside the canvas, clear of the vertical scrollbar.
            right=width-24
            if x2>right:
                x1,x2=x1-(x2-right),right
            if x1<8:
                x2,x1=x2+(8-x1),8
            y1=min(y for x,y in points)-82
            y2=max(y for x,y in points)+64
            bg,border,ink=palette[index%len(palette)]
            rounded_box(self.canvas,x1,y1,x2,y2,r=16,fill=bg,outline=border,dash=(3,2),tags=('vlan-group',))
            captions.append((x1,y1,x2,bg,ink,vid,networks(graph,names,spec,vid)))
        dmz=firewall_hosts(graph)
        for name in dmz:
            xx,yy=positions[name]
            zone_fill,zone_line,zone_ink=CANVAS['zone']
            rounded_box(self.canvas,xx-58,yy-56,xx+58,yy+62,r=14,fill=zone_fill,outline=zone_line,dash=(3,2),tags=('firewall-zone',))
            zone=self.canvas.create_text(xx-50,yy-46,text='Zone pare-feu',anchor='w',fill=zone_ink,font=(self.font,7,'bold'),
                                         tags=('zone-label',))
            bx1,by1,bx2,by2=self.canvas.bbox(zone)  # on a card of its own: the firewall's cable passes behind it
            card=rounded_box(self.canvas,bx1-3,by1-1,bx2+3,by2+1,r=5,fill=zone_fill,outline='',tags=('zone-label',))
            self.canvas.tag_lower(card,zone)
        graph_nodes={n['name']:n for n in graph['nodes']}
        port_labels=[]
        blocked=set()
        try:
            from .guest_stp import blocked_ports
            if spec:
                blocked=blocked_ports(spec)  # amber link lights: the ports spanning tree blocks
        except (ValueError,KeyError,TypeError):pass
        shut={(n['name'],port) for n in (spec or {}).get('nodes',[]) for port in n.get('shutdown') or []}
        try:
            from .port_guard import model as guarded
            if spec:  # red too: a port that port security or BPDU guard err-disables
                shut|={end for end,state in guarded(spec).items() if state['state']=='err-disabled'}
        except (ValueError,KeyError,TypeError):pass
        parallel={}  # several cables between the same two devices (a redundant link): drawn side by side
        for a,b in graph['links']:
            parallel.setdefault(frozenset((a[0],b[0])),[]).append((a,b))
        router_links={}
        for a,b in graph['links']:
            if graph_nodes[a[0]]['role']==graph_nodes[b[0]]['role']=='router':
                router_links[a[0]]=router_links.get(a[0],0)+1
                router_links[b[0]]=router_links.get(b[0],0)+1
        # Where a cable meets a device: the classic chassis is wide; a studio tile is a 56 px square.
        reach,drop,beside,spread=32,30,34,.45
        for index,(a,b) in enumerate(graph['links']):
            x,y=positions[a[0]]
            xx,yy=positions[b[0]]
            # Staggered routers (different rows, apart sideways): an L from one to the other's side.
            side=(abs(y-yy)>=45 and abs(x-xx)>=120 and graph_nodes[a[0]]['role']==graph_nodes[b[0]]['role']=='router'
                  and max(router_links.get(a[0],0),router_links.get(b[0],0))<=2)  # a chain, not a hub with its branches
            if abs(y-yy)<45:
                group=parallel[frozenset((a[0],b[0]))]
                shift=(group.index((a,b))-(len(group)-1)/2)*12
                sign=1 if xx>x else -1
                ax,ay,bx,by=x+sign*reach,y+shift,xx-sign*reach,yy+shift
                points=(ax,ay,bx,by)
            elif side:
                # An L: down from the upper device's port, then into the lower device's side, clear of its title.
                if y<yy:
                    ax,ay=x+port_offset(graph_nodes[a[0]],a[1])*spread,y+drop
                    bx,by=xx-(beside if xx>x else -beside),yy
                    points,mid=(ax,ay,ax,by,bx,by),ax
                else:
                    bx,by=xx+port_offset(graph_nodes[b[0]],b[1])*spread,yy+drop
                    ax,ay=x-(beside if x>xx else -beside),y
                    points,mid=(ax,ay,bx,ay,bx,by),bx
            else:
                sign=1 if yy>y else -1
                ax,ay,bx,by=x,y+sign*drop,xx,yy-sign*drop
                # Ports leave the chassis spread across its width, so cables and their captions stay apart.
                if graph_nodes[a[0]]['role']!='host':
                    ax+=port_offset(graph_nodes[a[0]],a[1])*spread
                if graph_nodes[b[0]]['role']!='host':
                    bx+=port_offset(graph_nodes[b[0]],b[1])*spread
                mid=min(ay,by)+8+(index%3)*8
                points=(ax,ay,ax,mid,bx,mid,bx,by)
            self.link_shapes[index]=self.canvas.create_line(*points,fill=CANVAS['link'],width=2,joinstyle='round',
                                                            capstyle='round',tags=('link','link:'+str(index)))
            self.canvas.tag_bind('link:'+str(index),'<Button-3>',lambda event,aa=a,bb=b:self.remove_cable(aa,bb))
            for endpoint,peer,px,py in ((a,b,ax,ay),(b,a,bx,by)):
                light=tuple(endpoint)
                if light in blocked or light in shut:  # amber: blocked by spanning tree; red: shutdown
                    colour='#e8a317' if light in blocked else '#d64541'
                    self.canvas.create_oval(px-4,py-4,px+4,py+4,fill=colour,outline=CANVAS['light_ring'],tags=('port-light',))
                else:
                    self.canvas.create_oval(px-2,py-2,px+2,py+2,fill=CANVAS['link_end'],outline='',tags=('link-end',))
                nx,ny=positions[endpoint[0]]
                other_y=positions[peer[0]][1]
                ordinal=list(graph_nodes[endpoint[0]]['interfaces']).index(endpoint[1])
                tx,ty,anchor=px+5,py-8,'w'
                if side and abs(py-ny)<5:
                    outward=1 if px>nx else -1  # entering the lower device's side
                    tx,ty,anchor=px+outward*4,py-9,'w' if outward>0 else 'e'
                elif side:
                    tx,ty,anchor=px+5,py+8,'w'
                elif graph_nodes[endpoint[0]]['role']!='host':
                    if other_y<ny-45:
                        tx,ty,anchor=nx-36,ny-19,'e'
                    else:
                        tx,ty=px+5,ny+drop+5+(ordinal%4)*10
                shown=port_label(graph_nodes[endpoint[0]],endpoint[1])
                port_labels.append(dict(x=tx,y=ty,text=shown,anchor=anchor,tag='link:'+str(index)))
            caption=link_caption(a,b,config)
            if caption:
                if abs(y-yy)<45:
                    self.link_caption((ax+bx)/2,(ay+by)/2-12,caption,'center')
                elif side:
                    lower=xx if y<yy else x  # the caption faces the lower device, away from the upper one's other cables
                    self.link_caption(mid+(6 if lower>mid else -6),(min(ay,by)+max(ay,by))/2+6,caption,'w' if lower>mid else 'e')
                elif abs(ax-bx)<40:
                    # A cable going almost straight down: label its vertical run, clear of both devices.
                    self.link_caption(bx+6,(mid+by)/2,caption,'w')
                else:
                    # On the lower device's own vertical run: the upper device's port labels keep their room.
                    lower_x,lower_y=(bx,by) if by>ay else (ax,ay)
                    self.link_caption(lower_x+6,(mid+lower_y)/2,caption,'w')
        for x1,y1,x2,bg,ink,vid,subnets in captions:
            rounded_box(self.canvas,x1+3,y1+3,x2-3,y1+41,r=9,fill=bg,outline='')
            self.canvas.create_text((x1+x2)/2,y1+14,text=f'VLAN {vid}',fill=ink,font=(self.font,8,'bold'),tags=('vlan-label',))
            self.canvas.create_text((x1+x2)/2,y1+30,text=subnets,fill=MUTED,font=(self.font,7))
        for node in graph['nodes']:
            name=node['name']
            x,y=positions[name]
            observed=self.states.get(name,{})
            state=observed.get('status','non observé')
            memory=observed.get('memory')
            tags=('node','node:'+name)
            # The selection box encloses the device and its title (and, for hosts, the captions below).
            host=node['role']=='host'
            box=(x-48,y-40,x+48,y+68) if host else (x-70,y-68,x+70,y+40)
            self.node_shapes[name]=rounded_box(self.canvas,*box,r=16,fill='',outline='',width=1,tags=tags)
            from .native_models import MODELS,label as model_label
            presentation=MODELS[node['model']]['presentation'] if node.get('model') in MODELS else None
            kind='server' if presentation=='server' or name in dmz or name.upper().startswith('SRV') else node['role']
            studio_art.tile(self.canvas,kind,x,y,56,state if state in ('running','stopped') else 'unknown',tags=tags)
            if node['role']=='host':
                self.canvas.create_text(x,y+44,text=name,fill=CANVAS['name'],font=(self.font,9,'bold'),tags=tags)
                ips=[v.split('/')[0] for v in node['interfaces'].values() if v]
                # Under a host: its address (what a lab is about); the model only while it has none.
                caption=', '.join(ips) if ips else (MODELS[node['model']]['model'][:20] if node.get('model') in MODELS
                                                    else 'Linux · micro-VM' if node.get('runtime')=='firecracker' else 'Linux · OCI')
                if node.get('dhcp_clients') and not ips:
                    caption='DHCP'
                self.canvas.create_text(x,y+58,text=caption,fill=CANVAS['address'] if ips else CANVAS['detail'],
                                        font=(self.font,8),tags=tags)
            else:
                title=self.canvas.create_text(x,y-54,text=name,fill=CANVAS['name'],font=(self.font,9,'bold'),tags=tags)
                subtitle=model_label(node,short=True)
                subtitle=subtitle if len(subtitle)<=30 else subtitle[:29]+'…'
                detail=self.canvas.create_text(x,y-40,text=subtitle,fill=CANVAS['detail'],font=(self.font,8),tags=tags)
                self.title_patch(title,detail,tags)
            self.canvas.tag_bind('node:'+name,'<Button-1>',lambda event,n=name:self.node_pressed(event,n))
            self.canvas.tag_bind('node:'+name,'<Double-Button-1>',lambda event,n=name:self.device_double_click(n))
            self.canvas.tag_bind('node:'+name,'<Enter>',lambda event,n=name:self.hover_node(n,True))
            self.canvas.tag_bind('node:'+name,'<Leave>',lambda event,n=name:self.hover_node(n,False))
            # in the window's language
            shown={'running':'en marche','stopped':'arrêté','exited':'arrêté','failed':'en échec'}.get(state,state)
            self.nodes.insert('','end',iid=name,text=name,values=(node['runtime'],shown,
                                                                  '—' if memory is None else f'{memory/1048576:.1f} MiB'))
            self.library.insert('','end',iid=name,text=name)
        # Every device listed (up to eight rows, then the wheel): a fixed three hid the rest of a larger lab.
        self.nodes.configure(height=max(3,min(8,len(self.nodes.get_children()))))
        obstacles=[self.canvas.bbox(item) for item in self.canvas.find_all() if self.canvas.type(item)=='text']
        for node in graph['nodes']:
            x,y=positions[node['name']]
            host=node['role']=='host'
            obstacles.append((x-32 if host else x-50,y-29,x+32 if host else x+50,y+24))
        chip=CANVAS['chip'] or ('#ffffff','#e0e9f2',MUTED)
        draw_port_labels(self.canvas,port_labels,obstacles,(self.font,7),chip[2],chip[0],chip[1])
        if graph['links']:
            self.canvas.tag_lower('glow','link')  # cables run over the tiles' glow, under the tiles
        self.canvas.tag_raise('zone-label')
        self.canvas.tag_raise('port-light')  # above the devices' artwork, as a port's link light
        for index,(a,b) in enumerate(graph['links']):
            self.canvas.tag_bind('link:'+str(index),'<Button-3>',lambda event,aa=a,bb=b:self.remove_cable(aa,bb))
        running=sum(n['runtime']=='oci' and self.states.get(n['name'],{}).get('status')=='running' for n in graph['nodes'])
        stopped=bool(self.states) and all(self.states.get(n['name'],{}).get('status')=='stopped' for n in graph['nodes'])
        from .platform_support import model_mode
        self.runtime_hint.set(f'● Relevé : {running} processus OCI en marche' if running else '● Arrêt confirmé' if stopped
                              else '◇ Mode modèle : CLI, ping et simulation' if model_mode() else '○ État non observé')
        self.runtime_label.configure(fg='#159746' if running else MUTED)
        guests=sum(self.states.get(n['name'],{}).get('status')=='running' for n in graph['nodes'])
        if guests:
            self.lab_chip.configure(text=f'● Lab en marche · {guests} équipement{"s" if guests>1 else ""}',bg='#e3f6ea',fg='#157a3e')
        elif model_mode():
            self.lab_chip.configure(text='◇ Mode modèle',bg='#efe9fb',fg='#5b3aa6')
        else:
            self.lab_chip.configure(text='○ Lab arrêté · '+str(len(graph['nodes']))+' équipement'+('s' if len(graph['nodes'])>1 else ''),
                                    bg='#e8eef5',fg=MUTED)
        self.studio_lab_state(guests,len(graph['nodes']))
        self.filter_library()
        self.project_title.set(graph['name'])
        self.counts.set(f"{len(graph['nodes'])} équipements  /  {len(graph['links'])} liens  /  {graph['name']}")
        if self.zoom!=1.:
            for item in self.canvas.find_all():
                if self.canvas.type(item)=='text':
                    font=self.canvas.tk.splitlist(self.canvas.itemcget(item,'font'))
                    self.canvas.itemconfigure(item,font=(font[0],max(6,round(int(font[1])*self.zoom)),*font[2:]))
            self.canvas.scale('all',0,0,self.zoom,self.zoom)
        right=max((x for x,y in positions.values()),default=0)
        bottom=max((y for x,y in positions.values()),default=0)
        self.canvas.configure(scrollregion=(-100,-100,max(width,(right+90)*self.zoom)+100,max(height,(bottom+90)*self.zoom)+100))
        self.zoom_label.set(f'{round(self.zoom*100)} %')
        hosts=[n['name'] for n in graph['nodes'] if n['runtime']=='oci' and n['role']=='host']
        self.targets.configure(values=hosts)
        self.destination.set(destination if destination in hosts else hosts[-1] if hosts else '')
        self.show_oci_controls(bool(hosts))
        if graph['nodes']:
            self.choose_node(previous if previous in positions else graph['nodes'][0]['name'])
        else:self.refresh_overview(None)

    def title_patch(self,title,detail,tags):
        """Under the studio design, a device's title sits on a patch of the canvas's colour: a cable coming from above
        goes behind the title instead of across it."""
        x1,y1,x2,y2=self.canvas.bbox(title)
        bx1,by1,bx2,by2=self.canvas.bbox(detail)
        patch=rounded_box(self.canvas,min(x1,bx1)-5,y1-1,max(x2,bx2)+5,by2+1,r=6,fill=CANVAS['background'],outline='',tags=tags)
        self.canvas.tag_lower(patch,title)

    def link_caption(self,x,y,text,anchor):
        """A cable's caption (its subnet, « trunk »…): plain text in the classic design, a small pill in the studio one."""
        item=self.canvas.create_text(x,y,text=text,anchor=anchor,fill=CANVAS['caption'],font=(self.font,7),tags=('link-caption',))
        if CANVAS['chip']:
            fill,border,ink=CANVAS['chip']
            x1,y1,x2,y2=self.canvas.bbox(item)
            self.canvas.itemconfigure(item,fill=ink)
            self.canvas.tag_lower(rounded_box(self.canvas,x1-7,y1-3,x2+7,y2+3,r=9,fill=fill,outline=border,tags=('link-caption',)),item)
        return item

    def choose_node(self,name):
        self.nodes.selection_set(name)
        self.nodes.see(name)
        self.select_node()

    def select_node(self,event=None):
        selected=self.nodes.selection()
        node=next((n for n in self.graph['nodes'] if selected and n['name']==selected[0]),None)
        if node:
            name=node['name']
            self.selected_title.set(name)
            if self.library.selection()!=(name,):
                self.library.selection_set(name)
            for key,shape in self.node_shapes.items():
                self.canvas.itemconfigure(shape,outline=CANVAS['selection'] if key==name else '',width=2 if key==name else 1)
        self.inspect_button.state(['!disabled'] if node and node['runtime']=='oci' and not self.pending else ['disabled'])
        running=node and self.states.get(node['name'],{}).get('status')=='running' and not self.pending
        # A micro-VM's terminal is its node console (typed requests to the agent, no shell); an OCI node's is a Linux shell.
        self.console_button.state(['!disabled'] if running else ['disabled'])
        guest=bool(node) and node['runtime']=='firecracker'
        self.linux_console_title.configure(text='Terminal du nœud' if guest else 'Console Linux native')
        self.console_button.configure(text=f'Ouvrir le terminal de {node["name"]}' if guest else 'Ouvrir la console Linux')
        self.catalogue_button.state(['!disabled'] if guest else ['disabled'])
        self.capture_button.state(['!disabled'] if running else ['disabled'])
        capture_ports=list(node['interfaces']) if node else []
        if node and node['runtime']=='oci':
            try:
                configured=next(n for n in self.manifest()['nodes'] if n['name']==node['name'])
            except (ValueError,KeyError,StopIteration):configured={}
            capture_ports+=list(configured.get('port_channels',{}))+list(configured.get('svis',{}))+[p for p,
                    sub in configured.get('subinterfaces',{}).items() if sub.get('vlan') is not None]
            capture_ports+=['lo']+(['br0'] if node['role']=='switch' else [])
        self.capture_ports.configure(values=list(dict.fromkeys(capture_ports)))
        if self.capture_interface.get() not in capture_ports:
            self.capture_interface.set(capture_ports[0] if capture_ports else '')

        self.verify_button.state(['!disabled'] if node and node['runtime']=='oci' and node['role']=='host' and not self.pending
                                 else ['disabled'])
        self.refresh_overview(node)
        if node:
            self.load_config()
        self.config_apply.state(['!disabled'] if node and not self.pending and self.config_baseline is not None else ['disabled'])

    def set_zoom(self,value,x=None,y=None):
        value=max(.65,min(1.75,value))
        if abs(value-self.zoom)<.001:
            return
        x=self.canvas.winfo_width()/2 if x is None else x
        y=self.canvas.winfo_height()/2 if y is None else y
        logical_x=self.canvas.canvasx(x)/self.zoom
        logical_y=self.canvas.canvasy(y)/self.zoom
        self.dragging=None
        self.panning=False
        self.zoom=value
        self.draw(self.graph,self.states)
        self.view_origin(logical_x*self.zoom-x,logical_y*self.zoom-y)

    def wheel_zoom(self,event,direction=None):
        direction=direction if direction is not None else (1 if event.delta>0 else -1)
        self.set_zoom(self.zoom*(1.12 if direction>0 else 1/1.12),event.x,event.y)
        return 'break'

    def reset_view(self):
        self.dragging=None
        self.panning=False
        self.zoom=1.
        self.view_moved=False
        self.draw(self.graph,self.states)
        self.fit_view()

    def fit_view(self):
        """Zoom out (never below 65 %) until every device shows, then centre the drawing in the canvas."""
        bounds=layout_bounds(self.graph,getattr(self,'drawn_positions',{})) if getattr(self,'graph',None) else None
        self.canvas.update_idletasks()
        width,height=max(300,self.canvas.winfo_width()-16),max(200,self.canvas.winfo_height()-16)
        if bounds is None:
            return self.view_origin(0,0)
        x1,y1,x2,y2=bounds
        wanted=max(.65,min(1.,width/max(1,x2-x1),height/max(1,y2-y1)))
        if abs(wanted-self.zoom)>.001:
            self.zoom=wanted
            self.draw(self.graph,self.states)
        z=self.zoom
        self.view_origin(((x1+x2)/2)*z-width/2,max(y1*z-8,((y1+y2)/2)*z-height/2))
        self.zoom_label.set(f'{round(self.zoom*100)} %')

    def view_origin(self,x,y):
        region=tuple(float(v) for v in self.canvas.cget('scrollregion').split())
        self.canvas.xview_moveto((x-region[0])/max(1,region[2]-region[0]))
        self.canvas.yview_moveto((y-region[1])/max(1,region[3]-region[1]))

    def begin_pan(self,event):
        self.view_moved=True
        self.dragging=None
        self.panning=True
        self.canvas.focus_set()
        self.canvas.configure(cursor='fleur')
        self.canvas.scan_mark(event.x,event.y)
        return 'break'

    def pan_motion(self,event):
        if self.panning:
            self.canvas.scan_dragto(event.x,event.y,gain=1)
        return 'break'

    def end_pan(self,event=None):
        self.panning=False
        self.canvas.configure(cursor='crosshair' if self.edit_mode=='cable' else '')
        return 'break'

    def hover_node(self,name,active):
        if name not in self.node_shapes:
            return
        selected=self.nodes.selection()
        self.canvas.itemconfigure(self.node_shapes[name],outline=CANVAS['selection'] if active or name in selected else '',width=2)
        for index,link in enumerate(self.graph['links']):
            if any(end[0]==name for end in link) and index in self.link_shapes:
                width=2.8 if active else 2
                self.canvas.itemconfigure(self.link_shapes[index],fill=CANVAS['link_hover'] if active else CANVAS['link'],width=width)
        if not self.panning:
            self.canvas.configure(cursor='crosshair' if self.edit_mode=='cable' else 'hand2' if active else '')
