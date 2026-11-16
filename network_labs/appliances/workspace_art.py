"""Original generic device artwork and declared access-VLAN presentation."""
import ipaddress
from pathlib import Path
import tkinter as tk
from .soft_widgets import rounded_box


def _mix(a, b, t):
    """Colour between a and b ('#rrggbb'), t in 0..1."""
    pa, pb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(u + (v - u) * t):02x}' for u, v in zip(pa, pb))


# Chassis palettes per role: top face, front panel top/bottom, side, outline, emblem.
_CHASSIS = {
    'router': ('#3f6f8f', '#1e4560', '#0f2738', '#0b1d2a', '#091620', '#2f9be0'),
    'switch': ('#dfe7ee', '#c9d5df', '#9fb0bf', '#7d8e9c', '#5b6c7a', '#2f8fd8'),
    'firewall': ('#5b4a4a', '#3b2f31', '#221a1c', '#1a1314', '#120c0d', '#e4572e'),
}


DEVICE_ART = Path(__file__).resolve().parent / 'assets' / 'devices'
ART_SCALES = (0.5, 0.65, 0.8, 1.0, 1.2, 1.45, 1.75)  # sizes rendered by tools/render_device_art.py


def device_image(c, role, variant, scale):
    """The pre-rendered, antialiased drawing nearest to SCALE, cached on the canvas; None when unavailable."""
    name = f'host-{variant}' if role == 'host' else role
    size = min(ART_SCALES, key=lambda value: abs(value - scale))
    path = DEVICE_ART / f'{name}@{round(size * 100)}.png'
    cache = c.__dict__.setdefault('_device_images', {})
    if path not in cache:
        try:
            cache[path] = tk.PhotoImage(master=c, file=str(path))
        except (tk.TclError, OSError):
            cache[path] = None
    return cache[path]


def draw_device(c,role,x,y,scale=1,tags=(),variant='blue',zoom=1):
    """Draw a device: the antialiased PNG for its role when present (ZOOM picks the size, since canvas
    scaling moves images without resizing them), else the vector drawing below."""
    image = device_image(c, role, variant, scale * zoom)
    if image is not None:
        return c.create_image(x, y, image=image, tags=tags)
    return draw_device_vector(c, role, x, y, scale, tags, variant)


def draw_device_vector(c,role,x,y,scale=1,tags=(),variant='blue'):
    """Unbranded device drawings: 3D chassis with front panel, ports, LEDs and a role emblem; monitors and towers."""
    def pt(points):
        return [v*scale+(x if i%2==0 else y) for i,v in enumerate(points)]

    def rect(a,b,d,e,**kw):
        return c.create_rectangle(x+a*scale,y+b*scale,x+d*scale,y+e*scale,tags=tags,**kw)

    def line(*points,**kw):
        return c.create_line(*pt(points),tags=tags,**kw)

    def poly(*points,**kw):
        return c.create_polygon(*pt(points),tags=tags,**kw)

    def oval(a,b,d,e,**kw):
        return c.create_oval(x+a*scale,y+b*scale,x+d*scale,y+e*scale,tags=tags,**kw)

    def gradient(a,b,d,e,top,bottom,steps=10):
        height=(e-b)/steps
        for i in range(steps):
            rect(a,b+i*height,d,b+(i+1)*height+.6,fill=_mix(top,bottom,i/(steps-1)),outline='')

    width=max(1,round(scale))
    if role=='host':
        oval(-30,20,30,30,fill='#d5dde5',outline='')                      # shadow on the desk
        poly(-8,13,8,13,11,24,-11,24,fill='#3a4b5c',outline='')            # stand neck
        poly(-21,23,21,23,24,27,-24,27,fill='#2b3a49',outline='')          # base
        line(-21,23,21,23,fill='#5d7083',width=width)
        rect(-34,-30,34,15,fill='#1b2836',outline='#0b1520',width=width)  # bezel
        rect(-34,-30,34,-28,fill='#2e3e4f',outline='')
        top,bottom=(('#e8573a','#9c1f27') if variant=='red' else ('#2ea8ff','#0b4fbf'))
        gradient(-30,-26,30,10,top,bottom,steps=12)
        poly(-30,-26,-4,-26,-30,0,fill=_mix(top,'#ffffff',.25),outline='')  # screen glare
        if variant=='red':
            oval(-10,-17,10,3,outline='#ffffff',width=max(1,2*scale))
            line(-4,-10,1,-7,-4,-4,fill='white',width=max(1,2*scale))
            line(3,-3,8,-3,fill='white',width=max(1,2*scale))
        else:
            for a,b,d,e in [(-12,-16,-1,-7),(2,-18,13,-7),(-12,-4,-1,5),(2,-4,13,7)]:
                rect(a,b,d,e,fill='#bfe6ff',outline='')
        rect(-34,10,34,15,fill='#c3ccd5',outline='')                     # chin
        oval(-1.5,11.5,1.5,13.5,fill='#31cf47',outline='')                # power LED
    elif role=='server':
        oval(-22,25,26,33,fill='#d5dde5',outline='')
        poly(-16,-29,11,-34,21,-28,-6,-22,fill='#6f818d',outline='#263847')            # top
        poly(12,-29,21,-28,21,24,12,29,fill='#142532',outline='#132331')               # side
        rect(-16,-29,12,29,fill='#263846',outline='#132331')
        gradient(-15,-28,11,28,'#34495a','#1d2c39',steps=8)
        for row in range(4):                                                            # drive bays
            rect(-12,-23+row*9,8,-17+row*9,fill='#3c5567',outline='#5f7b8c')
            rect(-10,-21+row*9,-6,-19+row*9,fill='#9fb4c2',outline='')
            oval(4,-21+row*9,6,-19+row*9,fill='#31cf47' if row != 2 else '#f1b434',outline='')
        for row in range(4):
            line(-11,14+row*3,7,14+row*3,fill='#647984')
        oval(-11,25,-7,28,fill='#31cf47',outline='')
    else:
        top,front_top,front_bottom,side,edge,accent=_CHASSIS.get(role,_CHASSIS['router'])
        oval(-52,10,58,24,fill='#d5dde5',outline='')                                   # shadow
        poly(-51,-14,-40,-25,45,-25,54,-14,fill=top,outline=edge)                       # top face
        line(-38,-22,43,-22,fill=_mix(top,'#ffffff',.35))
        poly(54,-14,58,-18,58,11,54,15,fill=side,outline=edge)                          # right side
        gradient(-51,-14,54,15,front_top,front_bottom,steps=9)                          # front panel
        rect(-51,-14,54,15,fill='',outline=edge,width=width)
        line(-51,-13,54,-13,fill=_mix(front_top,'#ffffff',.3))
        rect(-49,12,52,15,fill=_mix(front_bottom,'#000000',.35),outline='')            # base rail
        # Role emblem in a round badge on the left of the panel.
        badge=accent if role=='switch' else _mix(front_bottom,'#000000',.3)
        oval(-47,-11,-29,7,fill=badge,outline=_mix(accent,'#000000',.25) if role=='switch' else accent,width=width)
        if role=='router':
            for dx,dy in ((0,-5),(0,5),(-5,0),(5,0)):
                line(-38,-2,-38+dx,-2+dy,fill='white',width=max(1,1.6*scale),arrow='last',arrowshape=(3*scale,3.5*scale,1.5*scale))
        elif role=='switch':
            line(-44,-5,-32,-5,fill='white',width=max(1,1.6*scale),arrow='last',arrowshape=(3*scale,3.5*scale,1.5*scale))
            line(-32,1,-44,1,fill='white',width=max(1,1.6*scale),arrow='last',arrowshape=(3*scale,3.5*scale,1.5*scale))
        else:
            for row in range(3):                                                        # brick wall
                offset=0 if row%2==0 else 3
                for col in range(3):
                    bx=-45+offset+col*5
                    if bx+4<=-31:
                        rect(bx,-8+row*4,bx+4,-5+row*4,fill=accent,outline='')
        # Ports: two rows on switches, one row with link LEDs elsewhere.
        if role=='switch':
            for row in range(2):
                for index in range(10):
                    px=-24+index*6
                    rect(px,-10+row*9,px+4.5,-4+row*9,fill='#121c25',outline='#3f505d')
                    rect(px+.8,-11.4+row*9,px+2.2,-10.4+row*9,fill='#3ddc84' if (index+row)%3 else '#f1b434',outline='')
            for index in range(2):                                                      # uplinks
                px=37+index*6
                rect(px,-8,px+5,0,fill='#2b3946',outline='#9fb0bf')
        else:
            count=4 if role=='firewall' else 6
            for index in range(count):
                px=-22+index*9
                rect(px,-8,px+6,1,fill='#0d151c',outline=_mix(front_top,'#ffffff',.35))
                rect(px+1,-7,px+5,-5,fill='#26323c',outline='')
                rect(px+1,3,px+3,5,fill='#3ddc84' if index%4 != 3 else '#f1b434',outline='')
            line(30,-10,30,10,fill=_mix(front_top,'#ffffff',.2))
        # Status LEDs and a vent grille on the right.
        for i,colour in enumerate(('#3ddc84','#2f9be0','#3ddc84')):
            oval(46,-10+i*5,49,-7+i*5,fill=colour,outline='')
        for i in range(4):
            line(34+i*2.4,-9,34+i*2.4,8,fill=_mix(front_bottom,'#000000',.4) if role!='switch' else '#8798a6')


def port_offset(node,port):
    """Horizontal offset where a port's cable leaves a chassis: ports spread over its front panel."""
    ports=list(node['interfaces'])
    count=min(len(ports),8)
    step=min(18,90/max(1,count-1)) if count>1 else 0
    return (ports.index(port)%8-(count-1)/2)*step


def access_vlans(graph,spec):
    """Taxonomy from explicit host-to-access-port declarations, not reachability."""
    nodes={n['name']:n for n in spec['nodes']};members={}
    for a,b in graph['links']:
        for host,sw in ((a,b),(b,a)):
            h=nodes.get(host[0],{});s=nodes.get(sw[0],{})
            policy=s.get('switchports',{}).get(sw[1],{})
            if h.get('role')=='host' and s.get('role')=='switch' and policy.get('mode')=='access':
                members.setdefault(host[0],set()).add(policy['vlan'])
    return {name:next(iter(vids)) for name,vids in members.items() if len(vids)==1}


def firewall_hosts(graph):
    nodes={n['name']:n for n in graph['nodes']};result={}
    for a,b in graph['links']:
        for host,fw in ((a,b),(b,a)):
            if nodes[host[0]]['role']=='host' and nodes[fw[0]]['role']=='firewall':result[host[0]]=fw[0]
    return result


def place_nodes(graph,members,width):
    positions={};dmz=firewall_hosts(graph)
    routers=[n for n in graph['nodes'] if n['role']=='router'];firewalls=[n for n in graph['nodes'] if n['role']=='firewall']
    switches=[n for n in graph['nodes'] if n['role']=='switch'];upper=bool(routers or firewalls)
    # Routers and firewalls sit low enough that their titles clear the zoom bar over the canvas corner.
    for i,n in enumerate(routers):
        positions[n['name']]=((i+1)*width*.8/(len(routers)+1),100)
    for i,n in enumerate(firewalls):
        # Beside routers when there are any; otherwise spread across the canvas like routers.
        x=width*(.52+(i+1)*.16/len(firewalls)) if routers else (i+1)*width/(len(firewalls)+1)
        positions[n['name']]=(x,100)
    # Hosts cabled straight to a firewall sit in a row under it, centred on it and kept inside the canvas.
    by_firewall={}
    for host,firewall in dmz.items():
        by_firewall.setdefault(firewall,[]).append(host)
    for firewall,names in by_firewall.items():
        fx,fy=positions[firewall]
        spacing=min(170,max(110,width*.8/len(names)))
        start=min(max(70,fx-spacing*(len(names)-1)/2),max(70,width-70-spacing*(len(names)-1)))
        for i,name in enumerate(names):
            positions[name]=(start+i*spacing,fy+190)
    # Under routers and firewalls, switches leave room for the uplink captions and port labels in between.
    for i,n in enumerate(switches):
        positions[n['name']]=((i+1)*width*.86/(len(switches)+1),222 if upper else 100)
    hosts=[n for n in graph['nodes'] if n['role']=='host' and n['name'] not in dmz]
    vids=sorted(set(members.values()));columns=max(1,int(width//115))
    # Other hosts go below the firewall rows when there are any.
    base=(362 if upper else 270)+(140 if dmz else 0)
    if vids:
        groups=[(vid,[n for n in hosts if members.get(n['name'])==vid]) for vid in vids]
        other=[n for n in hosts if n['name'] not in members]
        if other:groups.append((None,other))
        cell=width/len(groups)
        for g,(_,nodes) in enumerate(groups):
            per_row=max(1,int(cell//95))
            for i,n in enumerate(nodes):
                row=i//per_row;count=min(per_row,len(nodes)-row*per_row)
                positions[n['name']]=(g*cell+(i%per_row+.5)*cell/count,base+row*130)
    else:
        for i,n in enumerate(hosts):
            positions[n['name']]=((i%columns+.5)*width/min(columns,len(hosts)),base+(i//columns)*130)
    return positions


def networks(graph,names,spec,vid):
    nodes={n['name']:n for n in spec['nodes']};ports=set();result=set()
    for a,b in graph['links']:
        for host,sw in ((a,b),(b,a)):
            policy=nodes.get(sw[0],{}).get('switchports',{}).get(sw[1],{})
            if host[0] in names and policy.get('mode')=='access' and policy.get('vlan')==vid:ports.add(tuple(host))
    for name,port in ports:
        address=nodes[name]['interfaces'].get(port,'')
        if address:result.add(str(ipaddress.IPv4Interface(address).network))
    return ', '.join(sorted(result))


def link_caption(a,b,config):
    def tagged(endpoint):
        n=config.get(endpoint[0],{});p=endpoint[1]
        return n.get('switchports',{}).get(p,{}).get('mode')=='trunk' or any(s.get('parent')==p for s in n.get('subinterfaces',{}).values())
    if all(tagged(end) for end in (a,b)):return 'Trunk · 802.1Q'
    addresses=[config.get(end[0],{}).get('interfaces',{}).get(end[1],'') for end in (a,b)]
    if all(addresses):
        nets=[ipaddress.IPv4Interface(v).network for v in addresses]
        if nets[0]==nets[1]:return str(nets[0])
    return ''


def draw_port_labels(canvas,labels,obstacles,font,color):
    """Prefer nearby free positions; reserve badges separately from wire geometry."""
    occupied=[box for box in obstacles if box]
    offsets=[(0,0),(18,0),(-18,0),(0,12),(18,12),(-18,12),(0,-12),(32,0),(-32,0),(0,24),(32,12),(-32,12),(0,-24),(0,36)]
    def overlap(box):
        x1,y1,x2,y2=box
        return sum(max(0,min(x2+2,b[2])-max(x1-2,b[0]))*max(0,min(y2+2,b[3])-max(y1-2,b[1])) for b in occupied)
    for label in labels:
        x,y=label['x'],label['y'];tags=('port-label',label['tag'])
        item=canvas.create_text(x,y,text=label['text'],anchor=label['anchor'],fill=color,font=font,tags=tags)
        best=None
        for dx,dy in offsets:
            canvas.coords(item,x+dx,y+dy);box=canvas.bbox(item)
            score=overlap(box)
            if best is None or score<best[0]:best=(score,dx,dy,box)
            if score==0:break
        _,dx,dy,box=best;canvas.coords(item,x+dx,y+dy)
        bg=rounded_box(canvas,box[0]-3,box[1]-2,box[2]+3,box[3]+2,r=4,fill='#ffffff',outline='#e0e9f2',tags=('port-label-bg',label['tag']))
        canvas.tag_raise(item,bg);occupied.append((box[0]-2,box[1]-1,box[2]+2,box[3]+1))
