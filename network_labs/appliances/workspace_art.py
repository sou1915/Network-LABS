"""Original generic device artwork and declared access-VLAN presentation."""
import ipaddress


def draw_device(c,role,x,y,scale=1,tags=(),variant='blue'):
    def rect(a,b,d,e,**kw):return c.create_rectangle(x+a*scale,y+b*scale,x+d*scale,y+e*scale,tags=tags,**kw)
    def line(*points,**kw):return c.create_line(*[v*scale+(x if i%2==0 else y) for i,v in enumerate(points)],tags=tags,**kw)
    if role=='host':
        rect(-32,-27,32,14,fill='#172331',outline='#0b1520',width=2)
        for row in range(32):
            shade=f'#{195+row:02x}{18+row:02x}{27+row:02x}' if variant=='red' else f'#{8+row:02x}{104+row*2:02x}{222+row:02x}'
            rect(-29,-24+row,29,-23+row,fill=shade,outline='')
        if variant=='red':
            c.create_oval(x-10*scale,y-17*scale,x+10*scale,y+3*scale,outline='#ffffff',width=max(1,2*scale),tags=tags)
            line(-4,-10,1,-7,-4,-4,fill='white',width=max(1,2*scale));line(3,-3,8,-3,fill='white',width=max(1,2*scale))
        else:
            for a,b,d,e in [(-12,-16,-1,-7),(2,-18,13,-7),(-12,-4,-1,5),(2,-4,13,7)]:
                rect(a,b,d,e,fill='#69c6ff',outline='')
        rect(-5,15,5,23,fill='#344454',outline='');rect(-20,23,20,26,fill='#243547',outline='')
        rect(-29,10,29,12,fill='#8d9eac',outline='')
    elif role=='server':
        c.create_polygon(x-16*scale,y-29*scale,x+11*scale,y-34*scale,x+21*scale,y-28*scale,x-6*scale,y-22*scale,fill='#586975',outline='#263847',tags=tags)
        rect(-16,-29,12,29,fill='#263846',outline='#132331')
        c.create_polygon(x+12*scale,y-29*scale,x+21*scale,y-28*scale,x+21*scale,y+24*scale,x+12*scale,y+29*scale,fill='#142532',outline='#132331',tags=tags)
        for row in range(4):rect(-12,-23+row*9,8,-17+row*9,fill='#344c5c',outline='#526b79')
        for row in range(3):line(-11,16+row*3,7,16+row*3,fill='#647984')
        rect(-11,11,-8,13,fill='#31cf47',outline='')
    else:
        # A three-dimensional, unbranded rack chassis; not a firmware/model claim.
        c.create_polygon(x-51*scale,y-14*scale,x-40*scale,y-25*scale,x+45*scale,y-25*scale,x+54*scale,y-14*scale,fill='#314855',outline='#263848',tags=tags)
        rect(-51,-14,54,15,fill='#183441' if role=='router' else '#c8d3dc' if role=='switch' else '#f1f0eb',outline='#263848')
        rect(-49,12,52,16,fill='#152331',outline='')
        line(-37,-20,34,-20,fill='#778c99',width=1)
        if role=='firewall':
            rect(-45,-9,-21,-5,fill='#e62328',outline='')
            rect(-45,-4,-21,-1,fill='#a3abb2',outline='')
        count=12 if role=='switch' else 4 if role=='firewall' else 6
        start=-12 if role=='firewall' else -42;spacing=7 if role=='switch' else 12
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
    for i,n in enumerate(routers):positions[n['name']]=((i+1)*width*.8/(len(routers)+1),72)
    for i,n in enumerate(firewalls):positions[n['name']]=(width*(.52+(i+1)*.16/len(firewalls)),90)
    for i,name in enumerate(dmz):positions[name]=(width-48,100+i*125)
    for i,n in enumerate(switches):positions[n['name']]=((i+1)*width*.86/(len(switches)+1),194 if upper else 100)
    hosts=[n for n in graph['nodes'] if n['role']=='host' and n['name'] not in dmz]
    vids=sorted(set(members.values()));columns=max(1,int(width//115))
    if vids:
        groups=[(vid,[n for n in hosts if members.get(n['name'])==vid]) for vid in vids]
        other=[n for n in hosts if n['name'] not in members]
        if other:groups.append((None,other))
        cell=width/len(groups)
        for g,(_,nodes) in enumerate(groups):
            per_row=max(1,int(cell//95))
            for i,n in enumerate(nodes):
                row=i//per_row;count=min(per_row,len(nodes)-row*per_row)
                positions[n['name']]=(g*cell+(i%per_row+.5)*cell/count,(334 if upper else 270)+row*130)
    else:
        for i,n in enumerate(hosts):positions[n['name']]=((i%columns+.5)*width/min(columns,len(hosts)),(334 if upper else 270)+(i//columns)*130)
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
