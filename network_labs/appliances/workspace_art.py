"""Original generic device artwork and declared access-VLAN presentation."""
import ipaddress


def draw_device(c,role,x,y,scale=1,tags=()):
    def rect(a,b,d,e,**kw):return c.create_rectangle(x+a*scale,y+b*scale,x+d*scale,y+e*scale,tags=tags,**kw)
    def line(*points,**kw):return c.create_line(*[v*scale+(x if i%2==0 else y) for i,v in enumerate(points)],tags=tags,**kw)
    if role=='host':
        rect(-32,-27,32,14,fill='#172331',outline='#0b1520',width=2)
        for row in range(32):
            shade=f'#{25+row:02x}{110+row*2:02x}{185+row:02x}'
            rect(-29,-24+row,29,-23+row,fill=shade,outline='')
        line(-20,1,0,-15,20,-4,fill='#70dbff',width=2)
        for xx,yy in ((-20,1),(0,-15),(20,-4)):
            c.create_oval(x+(xx-3)*scale,y+(yy-3)*scale,x+(xx+3)*scale,y+(yy+3)*scale,fill='white',outline='',tags=tags)
        rect(-5,15,5,23,fill='#344454',outline='');rect(-20,23,20,26,fill='#243547',outline='')
        rect(-29,10,29,12,fill='#8d9eac',outline='')
    else:
        # A three-dimensional, unbranded rack chassis; not a firmware/model claim.
        c.create_polygon(x-51*scale,y-14*scale,x-40*scale,y-25*scale,x+45*scale,y-25*scale,x+54*scale,y-14*scale,fill='#526575',outline='#263848',tags=tags)
        rect(-51,-14,54,15,fill='#263946' if role=='router' else '#d3dbe0' if role=='switch' else '#ecebe7',outline='#263848')
        rect(-49,12,52,16,fill='#152331',outline='')
        line(-37,-20,34,-20,fill='#778c99',width=1)
        count=12 if role=='switch' else 6
        start=-42;spacing=7 if role=='switch' else 12
        for index in range(count):
            px=start+index*spacing
            rect(px,-7,px+5,2,fill='#14202a',outline='#6b7d88')
            rect(px+1,3,px+4,4,fill='#54b97c',outline='')
        for px in (45,49):rect(px,-6,px+1,-4,fill='#2bb67c',outline='')
        line(-44,8,37,8,fill='#889aa5',width=1)


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


def place_nodes(graph,members,width):
    positions={};infra=[n for n in graph['nodes'] if n['role']!='host'];hosts=[n for n in graph['nodes'] if n['role']=='host']
    for row,kinds in enumerate((('router','firewall'),('switch',))):
        group=[n for n in infra if n['role'] in kinds]
        for index,n in enumerate(group):positions[n['name']]=((index+1)*width/(len(group)+1),80+row*105)
    has_upper=any(n['role'] in ('router','firewall') for n in infra)
    if not has_upper:
        for n in infra:positions[n['name']]=(positions[n['name']][0],105)
    ordered=sorted(hosts,key=lambda n:(members.get(n['name'],4095),n['name']))
    columns=max(1,int(width//165));rows=(len(ordered)+columns-1)//columns
    for index,n in enumerate(ordered):
        row=index//columns;in_row=min(columns,len(ordered)-row*columns)
        positions[n['name']]=((index%columns+.5)*width/in_row,(330 if has_upper else 265)+row*145)
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
