"""Deterministic educational switching model; no real network sockets or vendor OS."""
from dataclasses import dataclass, field, asdict
from ipaddress import IPv4Interface, IPv4Address
from hashlib import sha256
from heapq import heappush, heappop
from .services import Services
from .layer2 import Layer2
from .access_multicast import AccessMulticast
from .lan_services import LANServices
from .firewall import Firewall,firewall_rule
from .transport import Transport
from .explanation import recorded
import json
import re


def vlan_list(text):
    if text == 'all':
        return list(range(1, 4095))
    if text == 'none':
        return []
    result = set()
    for part in text.split(','):
        pair = part.strip().split('-')
        if len(pair) > 2:
            raise ValueError('Liste VLAN invalide.')
        start, end = int(pair[0]), int(pair[-1])
        if not 1 <= start <= end <= 4094:
            raise ValueError('VLAN attendu entre 1 et 4094.')
        result.update(range(start, end + 1))
    return sorted(result)


def port_name(name):
    name = name.lower().replace('gigabitethernet', 'gi').replace('fastethernet', 'fa')
    name = re.sub(r'^g(?=\d)', 'gi', name)
    name = re.sub(r'^f(?=\d)', 'fa', name)
    name = name.replace('port-channel', 'po').replace('ethernet', 'eth').replace(' ', '')
    if not re.fullmatch(r'(?:gi|fa)\d+/(?:\d+/)?\d+(?:\.\d+)?|eth\d+|po\d+', name):
        raise ValueError('Interface inconnue. Exemple : gi0/1, gi0/0.10, po1.')
    return name


def mac_for(name):
    value = '02' + sha256(name.encode()).hexdigest()[:10]
    return ':'.join(value[i:i+2] for i in range(0, 12, 2))

@dataclass
class Port:
    mode: str = 'access'
    nonegotiate: bool = False
    dhcp_trust: bool = False
    arp_trust: bool = False
    source_guard: bool = False
    auth_control: str = 'force-authorized'
    authenticator: bool = False
    access_vlan: int = 1
    native_vlan: int = 1
    allowed: list = field(default_factory=lambda: list(range(1, 4095)))
    shutdown: bool = False
    description: str = ''
    cost: int = 19
    port_priority: int = 128
    portfast: bool = False
    bpduguard: bool = False
    errdisabled: bool = False
    channel: int = 0
    channel_mode: str = ''
    security: bool = False
    maximum: int = 1
    violation: str = 'shutdown'
    sticky: bool = False
    secure_macs: list = field(default_factory=list)
    violations: int = 0
    sub_vlan: int = 0
    address: str = ''

    def __post_init__(self):
        if isinstance(self.allowed,str):
            self.allowed=vlan_list(self.allowed)

@dataclass
class Node:
    name: str
    kind: str
    x: int = 200
    y: int = 150
    address: str = ''
    gateway: str = ''
    interfaces: dict = field(default_factory=dict)
    hostname: str = ''
    ports: dict = field(default_factory=dict)
    vlans: dict = field(default_factory=lambda: {'1': 'default'})
    stp_mode: str = 'rapid-pvst'
    priorities: dict = field(default_factory=dict)
    startup: dict = field(default_factory=dict)
    dhcp_pools: dict = field(default_factory=dict)
    dhcp_excluded: list = field(default_factory=list)
    dhcp_service: bool = True
    dhcp_snooping: bool = False
    snooping_vlans: list = field(default_factory=list)
    dai_vlans: list = field(default_factory=list)
    dns: list = field(default_factory=list)
    mst_name: str = ''
    mst_revision: int = 0
    mst_map: dict = field(default_factory=dict)
    vtp_mode: str = 'transparent'
    vtp_domain: str = ''
    vtp_password: str = ''
    vtp_version: int = 2
    vtp_revision: int = 0
    address_mode: str = 'static'
    dot1x_enabled: bool = False
    aaa_enabled: bool = False
    dot1x_radius: bool = False
    dot1x_user: str = ''
    dot1x_password: str = ''
    groups: list = field(default_factory=list)
    igmp_enabled: bool = True
    igmp_disabled_vlans: list = field(default_factory=list)
    igmp_unknown: str = 'flood'
    profile: str = ''
    services: dict | None = None
    dns_service: bool = False
    dns_records: dict = field(default_factory=dict)
    firewall_mode: str = ''
    firewall_default: str = 'deny'
    firewall_rules: list = field(default_factory=list)
    vendor: dict = field(default_factory=dict)

    def __post_init__(self):
        from .profiles import PROFILES, default_profile, profile_ports
        self.profile = self.profile or default_profile(self.kind)
        profile = PROFILES.get(self.profile)
        if not profile or not profile.creatable or profile.kind != self.kind:
            raise ValueError('Profil non simulé ou incompatible : '+self.profile)
        if not isinstance(self.vendor,dict):raise ValueError('Métadonnées constructeur : objet requis.')
        from .lan_services import dns_name
        if not isinstance(self.dns_records,dict):
            raise ValueError('DNS: dictionnaire de records requis.')
        self.dns_records={dns_name(host):str(IPv4Address(address)) for host,address in self.dns_records.items()}
        if self.services is None:
            from .profiles import profile_role
            role=profile_role(profile)
            self.services={'Serveur':{'tcp/80':'HTTP','tcp/443':'HTTPS'},'NAS':{'tcp/445':'SMB'},'Imprimante':{'tcp/9100':'Impression RAW'},'Caméra':{'tcp/554':'RTSP'},'Téléphone IP':{'udp/5060':'SIP'}}.get(role,{}).copy()
        if not isinstance(self.services,dict):
            raise ValueError('Services : dictionnaire requis.')
        from .transport import service_key
        self.services={service_key(*key.split('/')):str(label) for key,label in self.services.items()}
        if any(len(label)>80 or '\n' in label or '\r' in label for label in self.services.values()):
            raise ValueError('Nom de service invalide.')
        self.firewall_mode=self.firewall_mode or ('stateless' if self.profile=='fw-stateless' else 'stateful')
        if self.firewall_mode not in ('stateful','stateless') or self.firewall_default not in ('allow','deny'):
            raise ValueError('Politique firewall invalide.')
        self.firewall_rules=[firewall_rule(r['id'],r['action'],r['source'],r['target'],r.get('protocol','icmp'),r.get('port',0)) for r in self.firewall_rules]
        if len({r['id'] for r in self.firewall_rules})!=len(self.firewall_rules):
            raise ValueError('IDs de règles firewall dupliqués.')
        self.ports = {k: Port(**v) if isinstance(v, dict) else v for k,v in self.ports.items()}
        if not self.ports:
            names = profile_ports(self.profile,self.kind)
            self.ports = {name: Port() for name in names}

    @property
    def mac(self):
        return mac_for(self.name)

    def bridge_id(self, vlan):
        key='mst:'+str(self.mst_map.get(str(vlan),0)) if self.stp_mode=='mst' else str(vlan)
        return (int(self.priorities.get(key,32768)), self.mac)

@dataclass
class Link:
    a: str
    b: str
    mode: str = 'access'  # Kept for v1 migration; ports are authoritative in v2.
    vlans: list = field(default_factory=lambda: [1])
    a_port: str = ''
    b_port: str = ''
    enabled: bool = True

class Lab(Services,Layer2,AccessMulticast,LANServices,Firewall,Transport):
    def __init__(self):
        self.execution_backend = 'model'
        self.nodes, self.links = {}, []
        self.last_paths, self.last_hops, self.events = [], [], []
        self.fdb = {}
        self.firewall_sessions={}; self.firewall_counters={}; self.firewall_log=[]
        self.secure_dynamic = {}
        self.init_services()
        self.init_access_multicast()

    def add(self, node):
        if not node.name or node.name in self.nodes:
            raise ValueError('Nom vide ou déjà utilisé.')
        if node.kind not in ('PC', 'Switch', 'Routeur'):
            raise ValueError('Type non pris en charge.')
        if node.kind == 'Routeur':
            for vlan, address in node.interfaces.items():
                key = f'gi0/0.{vlan}'
                node.ports.setdefault(key, Port(mode='trunk', sub_vlan=int(vlan), address=address))
        self.nodes[node.name] = node

    def available_ports(self, name):
        used = {l.a_port if l.a == name else l.b_port for l in self.links if name in (l.a,l.b)}
        return [p for p in self.nodes[name].ports if p not in used and '.' not in p and not p.startswith('po')]

    def display_mac(self,name):
        if self.execution_backend=='wasm':
            if self.nodes[name].kind!='PC':return '— (aucune MAC de gestion Wasm)'
            from .micro_appliances.project import endpoint_mac
            return endpoint_mac(self,name)
        return self.nodes[name].mac

    def connect(self, a, b, mode='access', vlans=None, a_port='', b_port='', enabled=True, configure=True):
        vlans = [1] if vlans is None else list(vlans)
        if a == b or a not in self.nodes or b not in self.nodes:
            raise ValueError('Extrémités invalides.')
        if mode not in ('access', 'trunk') or not vlans or any(type(v) is not int or not 1 <= v <= 4094 for v in vlans):
            raise ValueError('Mode ou VLAN invalide.')
        if mode == 'access' and len(vlans) != 1:
            raise ValueError('Un port access appartient à un seul VLAN.')
        if any(self.nodes[n].kind == 'PC' for n in (a,b)) and mode != 'access':
            raise ValueError('Les PC utilisent un lien access.')
        selected = []
        for node, requested in ((a,a_port),(b,b_port)):
            available = self.available_ports(node)
            requested = port_name(requested) if requested else (available[0] if available else '')
            if requested not in available:
                raise ValueError(f'{node} : port indisponible {requested}.')
            selected.append(requested)
        link = Link(a,b,mode,vlans,*selected,enabled)
        self.links.append(link)
        if configure:
            self.configure_link(link, mode, vlans)
            self.sync_vtp()
        return link

    def configure_link(self, link, mode, vlans):
        if mode not in ('access','trunk') or not vlans or (mode == 'access' and len(vlans) != 1):
            raise ValueError('Configuration de lien invalide.')
        for node,p in ((link.a,link.a_port),(link.b,link.b_port)):
            port = self.nodes[node].ports[p]
            port.mode, port.access_vlan, port.allowed = mode, vlans[0], list(vlans)
            if self.nodes[node].kind == 'Switch' and self.nodes[node].vtp_mode!='client':
                for vlan in vlans:
                    self.nodes[node].vlans.setdefault(str(vlan), f'VLAN{vlan:04}')
        link.mode,link.vlans = mode,list(vlans)

    def ends(self, link):
        return self.nodes[link.a].ports[link.a_port],self.nodes[link.b].ports[link.b_port]

    def link_for(self, name, port):
        return next((l for l in self.links if (l.a,l.a_port)==(name,port) or (l.b,l.b_port)==(name,port)),None)

    def channel_state(self, link):
        a,b=self.ends(link)
        if not a.channel and not b.channel:
            return True, ''
        if not a.channel or not b.channel:
            return False, 'EtherChannel : partenaire non configuré'
        modes={a.channel_mode,b.channel_mode}
        compatible = modes=={'on'} or (modes <= {'active','passive'} and 'active' in modes) or (modes <= {'auto','desirable'} and 'desirable' in modes)
        if not compatible:
            return False, 'EtherChannel : négociation incompatible'
        def signature(p):
            return (p.mode,p.access_vlan,p.native_vlan,tuple(p.allowed))
        if signature(a)!=signature(b):
            return False, 'EtherChannel : paramètres différents'
        for name,port in ((link.a,a),(link.b,b)):
            group=[p for key,p in self.nodes[name].ports.items() if p.channel==port.channel and not p.shutdown and not p.errdisabled and not key.startswith('po')]
            if any(signature(p)!=signature(port) for p in group):
                return False, 'EtherChannel : membres incohérents'
            peers=set()
            for other in self.links:
                local = other.a_port if other.a==name else other.b_port if other.b==name else None
                if local and self.nodes[name].ports[local].channel==port.channel:
                    peers.add(other.b if other.a==name else other.a)
            if len(peers)>1:
                return False, 'EtherChannel : plusieurs partenaires'
        return True, ''

    def operational_mode(self,link,name):
        p=self.nodes[name].ports[link.a_port if link.a==name else link.b_port]
        if p.mode in ('access','trunk'):
            return p.mode
        other=link.b if name==link.a else link.a
        peer=self.nodes[other].ports[link.b_port if name==link.a else link.a_port]
        if self.nodes[name].kind!='Switch' or self.nodes[other].kind!='Switch' or p.nonegotiate or peer.nonegotiate or self.nodes[name].vtp_domain!=self.nodes[other].vtp_domain:
            return 'access'
        forms=peer.mode=='trunk' or peer.mode=='dynamic desirable' or (p.mode=='dynamic desirable' and peer.mode=='dynamic auto')
        return 'trunk' if forms else 'access'

    def eligible(self, link, vlan):
        if not link.enabled or self.boundary_reason(link):
            return False
        pa,pb=self.ends(link)
        for name,p,other in ((link.a,pa,link.b),(link.b,pb,link.a)):
            if self.nodes[name].kind=='Switch' and p.bpduguard and self.nodes[other].kind=='Switch':
                p.errdisabled=True
        if any(p.shutdown or p.errdisabled for p in (pa,pb)) or not self.channel_state(link)[0]:
            return False
        if not self.access_allowed(link.a,link.a_port) or not self.access_allowed(link.b,link.b_port):
            return False
        ma,mb=self.operational_mode(link,link.a),self.operational_mode(link,link.b)
        for name,port,mode in ((link.a,pa,ma),(link.b,pb,mb)):
            node=self.nodes[name]
            if node.kind=='Switch' and str(vlan) not in node.vlans:
                return False
            if node.kind!='PC' and (vlan not in port.allowed if mode=='trunk' else vlan!=port.access_vlan):
                return False
        if ma=='trunk' and mb=='trunk' and pa.native_vlan!=pb.native_vlan:
            # Conservative simulator policy; real devices can map native VLANs differently.
            return False
        if ma!=mb and all(self.nodes[n].kind=='Switch' for n in (link.a,link.b)):
            trunk=pa if ma=='trunk' else pb
            access=pb if ma=='trunk' else pa
            return vlan==trunk.native_vlan==access.access_vlan
        return True

    def stp(self, vlan):
        """Converged per-VLAN STP; no BPDU timers. EtherChannels are logical edges."""
        switches={n.name:n for n in self.nodes.values() if n.kind=='Switch' and (n.stp_mode=='mst' or str(vlan) in n.vlans)}
        logical={}
        for i,l in enumerate(self.links):
            if l.a not in switches or l.b not in switches or not self.tree_link_eligible(l,vlan):
                continue
            pa,pb=self.ends(l)
            key=tuple(sorted(((l.a,pa.channel),(l.b,pb.channel)))) if pa.channel and pb.channel else ('link',i)
            logical.setdefault(key,[]).append(i)
        edges=[ids for ids in logical.values()]
        adjacency={n:[] for n in switches}
        for e,ids in enumerate(edges):
            l=self.links[ids[0]]
            adjacency[l.a].append((l.b,e))
            adjacency[l.b].append((l.a,e))
        state={}
        remaining=set(switches)
        while remaining:
            seed=next(iter(remaining))
            component,stack=set(),[seed]
            while stack:
                n=stack.pop()
                if n in component:
                    continue
                component.add(n)
                stack.extend(other for other,_ in adjacency[n])
            remaining-=component
            root=min(component,key=lambda n:switches[n].bridge_id(vlan))
            distance={root:0}
            parent={}
            ranks={root:(0,(-1,''),(-1,-1),(-1,-1))}
            queue=[(0,root)]
            while queue:
                d,n=heappop(queue)
                if d!=distance[n]:
                    continue
                for other,e in adjacency[n]:
                    ids=edges[e]
                    l=self.links[ids[0]]
                    local=l.b_port if l.b==other else l.a_port
                    sender=l.a_port if l.a==n else l.b_port
                    cost=max(1,switches[other].ports[local].cost//len(ids))
                    rank=(d+cost,switches[n].bridge_id(vlan),(switches[n].ports[sender].port_priority, int(sender.split('/')[-1])),(switches[other].ports[local].port_priority,int(local.split('/')[-1])))
                    if other not in ranks or rank<ranks[other]:
                        distance[other],ranks[other],parent[other]=d+cost,rank,e
                        heappush(queue,(d+cost,other))
            for n in component:
                state[n]={'root':root,'cost':distance[n],'ports':{}}
            for e,ids in enumerate(edges):
                l=self.links[ids[0]]
                if l.a not in component:
                    continue
                designated=min((l.a,l.b),key=lambda n:(distance[n],switches[n].bridge_id(vlan)))
                for i in ids:
                    link=self.links[i]
                    for n,p in ((link.a,link.a_port),(link.b,link.b_port)):
                        role='ROOT' if parent.get(n)==e else 'DESG' if n==designated else 'ALTN'
                        state[n]['ports'][p]=(role,'BLK' if role=='ALTN' else 'FWD')
        return state

    def forwarding(self, link, vlan):
        if not self.eligible(link,vlan):
            return False
        for name,port in ((link.a,link.a_port),(link.b,link.b_port)):
            p=self.nodes[name].ports[port]
            if self.nodes[name].kind=='Switch':
                other=link.b if name==link.a else link.a
                if p.bpduguard and self.nodes[other].kind=='Switch':
                    p.errdisabled=True
                    return False
                state=self.stp(vlan).get(name,{}).get('ports',{}).get(port,('DESG','FWD'))
                if state[1]=='BLK':
                    return False
        return True

    def path_details(self, source, target, vlan):
        queue=[(source,[source],[])]
        seen={source}
        while queue:
            current,path,hops=queue.pop(0)
            if current==target:
                return path,hops
            if current!=source and self.nodes[current].kind!='Switch':
                continue
            for i,l in enumerate(self.links):
                if current not in (l.a,l.b) or not self.forwarding(l,vlan):
                    continue
                other=l.b if current==l.a else l.a
                if other not in seen:
                    seen.add(other)
                    queue.append((other,path+[other],hops+[(i,current,other,vlan)]))
        return None,None

    def path(self, source,target,vlan):
        return self.path_details(source,target,vlan)[0]

    def vlan(self,name):
        link=next((l for l in self.links if name in (l.a,l.b)),None)
        if not link:
            raise ValueError(f'{name} : aucun câble.')
        other=link.b if link.a==name else link.a
        p=link.b_port if link.a==name else link.a_port
        port=self.nodes[other].ports[p]
        return port.native_vlan if self.operational_mode(link,other)=='trunk' else port.access_vlan

    def learn(self,hops,source):
        mac=self.nodes[source].mac
        ip=self.nodes[source].address.split('/')[0] if self.nodes[source].address else ''
        for i,a,b,v in hops:
            link=self.links[i]
            if self.nodes[a].kind=='Routeur':
                mac=self.nodes[a].mac
                ip=self.nodes[a].interfaces.get(str(v),'').split('/')[0]
            if self.nodes[b].kind=='Switch':
                name=link.b_port if link.b==b else link.a_port
                p=self.nodes[b].ports[name]
                self.validate_sender(b,name,v,mac,ip)
                if p.security:
                    dynamic=self.secure_dynamic.setdefault(b+'/'+name,[])
                    known=set(p.secure_macs)|set(dynamic)
                    if mac not in known:
                        if len(known)>=p.maximum:
                            if p.violation!='protect':
                                p.violations+=1
                            if p.violation=='shutdown':
                                p.errdisabled=True
                            raise ValueError(f'{b}/{name} : violation port-security ({p.violation}).')
                        (p.secure_macs if p.sticky else dynamic).append(mac)
                self.fdb.setdefault(b,{})[f'{v}/{mac}']=name
            self.events.append({'link':i,'source':a,'target':b,'vlan':v,'mac':mac})

    def router_interface_up(self, node, vlan):
        sub = next((p for p in node.ports.values() if p.sub_vlan==vlan),None)
        return sub is None or not sub.shutdown

    @recorded("icmp")
    def ping(self,source,destination):
        if self.execution_backend == 'wasm':
            from .micro_appliances.project import execute
            return execute(self,source,destination)
        try:
            IPv4Address(destination)
        except ValueError:
            try:
                address,server=self.resolve_name(source,destination)
            except (ValueError,KeyError) as error:
                self.last_paths,self.last_hops,self.events=[],[],[]
                return False,[str(error)]
            ok,trace=self._ping_ipv4(source,address)
            return ok,[f'DNS: {destination} → {address} via {server}']+trace
        return self._ping_ipv4(source,destination)

    def _ping_ipv4(self,source,destination,protocol='icmp',port=0):
        self.last_protocol=protocol;self.last_service_port=port
        self.firewall_sessions={}; self.firewall_log=[]
        self.last_paths,self.last_hops,self.events=[],[],[]
        try:
            src=self.nodes[source]
            if src.kind!='PC':
                raise ValueError('Ping actuellement disponible depuis les PC uniquement.')
            si=IPv4Interface(src.address)
            ip=IPv4Address(destination)
            pcs=[n for n in self.nodes.values() if n.kind=='PC' and n.address and IPv4Interface(n.address).ip==ip]
            router_targets=[(n,int(v)) for n in self.nodes.values() if n.kind=='Routeur' for v,cidr in n.interfaces.items() if IPv4Interface(cidr).ip==ip and self.router_interface_up(n,int(v))]
            trace=[]
            if len(pcs)+len(router_targets)!=1:
                raise ValueError('Destination absente ou adresse IPv4 ambiguë.')
            if router_targets:
                router,v=router_targets[0]
                if ip not in si.network or self.vlan(source)!=v:
                    raise ValueError('Ce prototype permet de pinguer uniquement une interface routeur du sous-réseau local.')
                path,hops=self.path_details(source,router.name,v)
                if not path:
                    raise ValueError('Interface de passerelle inaccessible : VLAN, port ou trunk.')
                reverse=[(i,b,a,v) for i,a,b,v in reversed(hops)]
                self.firewall_check(hops,si.ip,ip,protocol,port)
                self.learn(hops,source)
                self.last_paths.append(path)
                self.last_hops.append(hops)
                self.firewall_check(reverse,ip,si.ip,protocol,port)
                self.learn(reverse,router.name)
                self.last_paths.append(list(reversed(path)))
                self.last_hops.append(reverse)
            else:
                dst=pcs[0]
                for a,b in ((src,dst),(dst,src)):
                    ai,bi=IPv4Interface(a.address),IPv4Interface(b.address)
                    av,bv=self.vlan(a.name),self.vlan(b.name)
                    path,hops=None,None
                    if bi.ip in ai.network:
                        if av==bv:
                            path,hops=self.path_details(a.name,b.name,av)
                    else:
                        gateway=IPv4Address(a.gateway)
                        if gateway not in ai.network:
                            raise ValueError(f'{a.name} : passerelle hors sous-réseau.')
                        for router in self.nodes.values():
                            if router.kind!='Routeur':
                                continue
                            incoming,outgoing=router.interfaces.get(str(av)),router.interfaces.get(str(bv))
                            if not incoming or not outgoing or not self.router_interface_up(router,av) or not self.router_interface_up(router,bv) or IPv4Interface(incoming).ip!=gateway or bi.ip not in IPv4Interface(outgoing).network:
                                continue
                            p1,h1=self.path_details(a.name,router.name,av)
                            p2,h2=self.path_details(router.name,b.name,bv)
                            if p1 and p2:
                                path,hops=p1+p2[1:],h1+h2
                                break
                    if not path:
                        raise ValueError(f'{a.name} : chemin inaccessible (VLAN, trunk, état du port, STP ou passerelle).')
                    self.firewall_check(hops,ai.ip,bi.ip,protocol,port)
                    self.learn(hops,a.name)
                    self.last_paths.append(path)
                    self.last_hops.append(hops)
                    trace.append('Chemin : '+' → '.join(path))
            return True,trace+['Réussite : aller et retour accessibles (modèle pédagogique simplifié).']
        except (ValueError,KeyError) as error:
            return False,[str(error)]

    def dumps(self):
        nodes=[asdict(n) for n in self.nodes.values()]
        for node in nodes:
            for port in node['ports'].values():
                if len(port['allowed'])==4094:
                    port['allowed']='all'
        return json.dumps({'version':2,'execution_backend':self.execution_backend,'nodes':nodes,'links':[asdict(l) for l in self.links],'radius_users':self.radius_users},indent=2)

    @classmethod
    def loads(cls,text):
        data=json.loads(text)
        if data.get('version') not in (1,2):
            raise ValueError('Version de projet incompatible.')
        lab=cls()
        lab.execution_backend=data.get('execution_backend','model')
        if lab.execution_backend not in ('model','wasm'):
            raise ValueError('Moteur de projet inconnu.')
        for node in data['nodes']:
            lab.add(Node(**node))
        lab.radius_users=data.get('radius_users',{}).copy()
        if any(not isinstance(k,str) or not isinstance(v,str) for k,v in lab.radius_users.items()):
            raise ValueError('RADIUS stub: identifiants invalides.')
        for link in data['links']:
            lab.connect(**link,configure=data['version']==1)
        return lab


def demo():
    lab=Lab()
    for n in (Node('PC1','PC',160,160,'192.168.10.10/24','192.168.10.1'),Node('PC2','PC',160,400,'192.168.20.10/24','192.168.20.1'),Node('SW1','Switch',430,280),Node('R1','Routeur',710,280,interfaces={'10':'192.168.10.1/24','20':'192.168.20.1/24'})):
        lab.add(n)
    lab.connect('PC1','SW1',vlans=[10])
    lab.connect('PC2','SW1',vlans=[20])
    lab.connect('SW1','R1','trunk',[10,20])
    return lab


def switching_demo():
    lab=demo()
    lab.add(Node('SW2','Switch',430,500))
    lab.add(Node('SW3','Switch',710,500))
    for a,b in [('SW1','SW2'),('SW2','SW3'),('SW3','SW1')]:
        lab.connect(a,b,'trunk',[10,20])
    return lab
