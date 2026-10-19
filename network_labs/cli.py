"""Small IOS-inspired CLI. Unsupported commands are rejected, never silently accepted."""
from ipaddress import IPv4Interface, IPv4Address, IPv4Network
import copy
import re
from .engine import Port, port_name, vlan_list
from .layer2_cli import Layer2Commands
from .cli_editing import CLIEditing
from .access_multicast_cli import AccessMulticastCLI
from .profiles import PROFILES
from .pc_cli import PCCommands
from .lan_cli import LANCommands
from .firewall_cli import FirewallCommands
from .firewall import is_firewall

FEATURES = '''NETWORK LABS / CLI pédagogique (inspirée IOS, pas un IOS réel)
Modes : enable, configure terminal, vlan, interface, interface range, end, exit
Switching : VLAN/name, access/trunk, allowed/native VLAN, shutdown, description
STP : pvst/rapid-pvst (état convergé), priorité/root, coût/priorité de port
EtherChannel : LACP active/passive, PAgP desirable/auto, statique on
Sécurité : port-security/maximum/MAC/sticky/violation, BPDU guard, PortFast
Inspection : show vlan brief, interfaces, spanning-tree, etherchannel summary,
             mac address-table, port-security, cdp/lldp neighbors, running-config
Routeur : sous-interfaces 802.1Q et IPv4, routes connectées uniquement
LAN : postes, serveurs, imprimantes, NAS, caméras, téléphones et IoT Ethernet
Endpoints : ip address CIDR, DHCP, DNS client, ping IPv4/nom, nslookup
Serveurs : DNS local A uniquement, service dns, dns record / show dns records
Firewalls LAN : bridge transparent 2 ports, règles IPv4 sur tests ICMP, stateful/stateless
                pas de TCP/UDP/NAT/VPN/IPS/WAF ni CLI constructeur réelle
Nouveau : DTP auto/desirable/nonegotiate, serveur/client DHCP (sans relais),
          DHCP snooping, DAI et IP Source Guard (contrôle d’identité simplifié).
Nouveau : VTP v2 (server/client/transparent/off), MST mono-région (état convergé).
Nouveau : IGMP snooping sans querier/timers, 802.1X avec backend RADIUS local simulé.
Non implémentés : VTP v1/v3, MST multi-région, voix, QoS, EAP/RADIUS réels,
                 LLDP/CDP réels, ACL/NAT, OSPF/BGP.
Les voisins sont déduits des câbles ; STP/LACP sont calculés sans temporisation.
Aucune commande non prise en charge n'est enregistrée comme fonctionnelle.'''

ALIASES={'en':'enable','conf':'configure','t':'terminal','int':'interface','sh':'show','run':'running-config','desc':'description','wr':'write'}

class Session(Layer2Commands,CLIEditing,AccessMulticastCLI,PCCommands,LANCommands,FirewallCommands):
    def __init__(self,lab,node):
        self.lab,self.node=lab,node
        self.mode='user'
        self.selection=[]
        self.vlan_id=None
        self.pool_name=None
        self.mst_pending=None
        self.changed=False
        self.history=[]

    @property
    def n(self):
        return self.lab.nodes[self.node]

    @property
    def prompt(self):
        if self.n.kind=='PC':
            if PROFILES[self.n.profile].family=='lab':
                return f'{self.n.hostname or self.n.name} [LAN]>'
            return 'C:\\Users\\student>' if PROFILES[self.n.profile].family=='windows' else f'student@{self.n.hostname or self.n.name}:~$'
        if is_firewall(self.n):
            return f'{self.n.hostname or self.n.name} [Firewall LAN]>'
        suffix={'mst':'(config-mst)#','dhcp':'(dhcp-config)#','user':'>','priv':'#','config':'(config)#','vlan':'(config-vlan)#','if':'(config-if)#','range':'(config-if-range)#'}[self.mode]
        return (self.n.hostname or self.n.name)+suffix

    def help(self,prefix=''):
        return self.context_help(prefix)

    def execute(self,line):
        self.changed=False
        line=line.strip()
        if not line:
            return ''
        self.history.append(line)
        if line=='show capabilities':
            return FEATURES
        if line=='?' or line.endswith(' ?') or line=='help':
            return self.help(line[:-2] if line.endswith(' ?') else '')
        try:
            line=self.normalize_command(line)
        except ValueError as e:
            return '% '+str(e)
        raw=line
        line=' '.join(line.split())
        if line.lower().startswith('show interface '):
            line='show interfaces '+line.split(' ',2)[2]
        low=line.lower()
        try:
            if low in ('show','configure','interface','switchport','switchport mode','spanning-tree','channel-group','vtp','ip','hostname','vlan','no','do'):
                raise ValueError('Incomplete command.')
            if '|' in line and (low.startswith('show ') or low.startswith('do show ')):
                base,filter_text=line.split('|',1)
                if base.lower().startswith('do '):
                    base=base[3:]
                elif self.mode not in ('user','priv'):
                    raise ValueError('Use do show in configuration mode.')
                operation,pattern=filter_text.strip().split(maxsplit=1)
                if operation not in ('include','exclude','begin'):
                    raise ValueError('Supported filters: include, exclude, begin.')
                try:
                    regex=re.compile(pattern)
                except re.error:
                    raise ValueError('Invalid filter expression.')
                lines=self.show(self.normalize_command(base.strip()).lower()).splitlines()
                if operation=='begin':
                    start=next((i for i,text in enumerate(lines) if regex.search(text)),len(lines))
                    return '\n'.join(lines[start:])
                return '\n'.join(text for text in lines if bool(regex.search(text))==(operation=='include'))
            fw=self.firewall_command(low,line)
            if fw is not None:
                return fw
            if self.n.kind=='PC':
                return self.pc(low,line)
            if low=='enable' and self.mode=='user':
                self.mode='priv'
                return ''
            if low=='disable' and self.mode=='priv':
                self.mode='user'
                return ''
            if low=='exit':
                if self.mode=='mst':
                    self.commit_mst()
                self.mode='config' if self.mode in ('if','range','vlan','dhcp','mst') else 'priv' if self.mode=='config' else 'user'
                return ''
            if low=='end':
                if self.mode=='user':
                    raise ValueError('Invalid input detected at user EXEC mode.')
                if self.mode=='mst':
                    self.commit_mst()
                self.mode='priv'
                return ''
            if low=='show pending' and self.mode=='mst':
                return self.layer2_show(low)
            if low.startswith('do show ') and self.mode not in ('user','priv'):
                return self.show(low[3:])
            if low.startswith('show '):
                if self.mode not in ('user','priv'):
                    raise ValueError('Utiliser do show ... depuis le mode configuration.')
                return self.show(low)
            if low in ('write','write memory','copy running-config startup-config'):
                self.require('priv')
                self.n.startup={'text':self.running_config()}
                self.changed=True
                return 'Configuration enregistrée dans le projet. Sauvegarder le fichier JSON pour la conserver sur disque.'
            if low=='configure terminal':
                self.require('priv')
                self.mode='config'
                return 'Enter configuration commands, one per line. End with end.'
            if low=='clear mac address-table dynamic':
                self.require('priv')
                self.lab.fdb.pop(self.node,None)
                self.changed=True
                return 'Table MAC vidée.'
            if low.startswith('ping '):
                raise ValueError('Ping source : disponible sur les PC dans ce prototype.')
            if self.mode in ('config','if','range','vlan','dhcp','mst'):
                feature=self.feature_command(low,line)
                if feature is not None:
                    return feature
                layer2=self.layer2_command(low,line)
                if layer2 is not None:
                    return layer2
                services=self.service_command(low,line)
                if services is not None:
                    return services
                if low.startswith('hostname '):
                    value=line.split(maxsplit=1)[1]
                    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,32}',value):
                        raise ValueError('Hostname invalide.')
                    self.n.hostname=value
                    self.changed=True
                    return ''
                if low.startswith('interface range '):
                    names=self.parse_range(low[len('interface range '):])
                    self.selection=names
                    self.mode='range'
                    return ''
                if low.startswith('interface '):
                    name=port_name(low.split(maxsplit=1)[1])
                    self.ensure_port(name)
                    self.selection=[name]
                    self.mode='if'
                    return ''
                if low.startswith('vlan ') and self.n.kind=='Switch':
                    if self.n.vtp_mode=='client':
                        raise ValueError('VTP client mode: VLAN changes are not allowed.')
                    ids=vlan_list(low[5:])
                    for v in ids:
                        self.n.vlans.setdefault(str(v),f'VLAN{v:04}')
                    self.lab.vlan_changed(self.node)
                    self.vlan_id=ids
                    self.mode='vlan'
                    self.changed=True
                    return ''
                if low.startswith('no vlan ') and self.n.kind=='Switch':
                    if self.n.vtp_mode=='client':
                        raise ValueError('VTP client mode: VLAN changes are not allowed.')
                    ids=vlan_list(low[8:])
                    if 1 in ids:
                        raise ValueError('VLAN 1 ne peut pas être supprimé.')
                    for v in ids:
                        self.n.vlans.pop(str(v),None)
                    self.lab.vlan_changed(self.node)
                    self.changed=True
                    return ''
                if self.mode=='vlan' and low.startswith('name '):
                    if self.n.vtp_mode=='client':
                        raise ValueError('VTP client mode: VLAN changes are not allowed.')
                    for v in self.vlan_id:
                        self.n.vlans[str(v)]=line[5:]
                    self.lab.vlan_changed(self.node)
                    self.changed=True
                    return ''
                if low.startswith('spanning-tree ') and self.mode not in ('if','range'):
                    return self.global_stp(low)
                if self.mode in ('if','range'):
                    # Validate a range atomically, then apply to its members.
                    affected=set(self.selection)
                    for selected in self.selection:
                        if selected.startswith('po'):
                            group=int(selected[2:])
                            affected.update(k for k,p in self.n.ports.items() if p.channel==group)
                    saved={k:copy.deepcopy(self.n.ports[k],{id(self.n.ports[k].allowed):self.n.ports[k].allowed[:]}) for k in affected}
                    interfaces=self.n.interfaces.copy()
                    vlan_state={name:(node.vlans.copy(),node.vtp_revision) for name,node in self.lab.nodes.items()}
                    try:
                        for name in self.selection:
                            self.port_command(name,low,line)
                    except ValueError:
                        self.n.ports.update(saved)
                        self.n.interfaces=interfaces
                        for node,(vlans,revision) in vlan_state.items():
                            self.lab.nodes[node].vlans=vlans; self.lab.nodes[node].vtp_revision=revision
                        raise
                    self.lab.sync_vtp()
                    self.changed=True
                    return ''
            raise ValueError('Commande non prise en charge ici. Utiliser ? ou show capabilities.')
        except (ValueError,KeyError,IndexError) as e:
            return '% '+str(e)

    def require(self,mode):
        if self.mode!=mode:
            raise ValueError('Mode requis : '+mode)

    def ensure_port(self,name):
        if name in self.n.ports:
            return
        if self.n.kind=='Routeur' and '.' in name and name.split('.')[0] in self.n.ports:
            self.n.ports[name]=Port(mode='trunk')
            self.changed=True
            return
        if self.n.kind=='Switch' and name.startswith('po') and 1<=int(name[2:])<=64:
            self.n.ports[name]=Port(description='__logical__')
            self.changed=True
            return
        raise ValueError('Interface absente : '+name)

    def parse_range(self,text):
        names=[]
        for item in text.split(','):
            match=re.fullmatch(r'\s*((?:gi|fa)\d+/(?:\d+/)?)(\d+)\s*(?:-\s*(\d+))?\s*',item)
            if not match:
                raise ValueError('Exemple : interface range gi0/1 - 4, gi0/8')
            prefix,start,end=match.groups()
            start,end=int(start),int(end or start)
            if start>end or end>48:
                raise ValueError('Plage invalide.')
            names.extend(prefix+str(i) for i in range(start,end+1))
        if any(name not in self.n.ports for name in names):
            raise ValueError('Une interface de la plage est absente.')
        return list(dict.fromkeys(names))

    def global_stp(self,low):
        if self.n.kind!='Switch':
            raise ValueError('STP concerne les switches.')
        if low in ('spanning-tree mode pvst','spanning-tree mode rapid-pvst'):
            self.n.stp_mode=low.split()[-1]
        else:
            m=re.fullmatch(r'spanning-tree vlan ([\d,-]+) (priority (\d+)|root (primary|secondary))',low)
            if not m:
                raise ValueError('Syntaxe : spanning-tree vlan <liste> priority <multiple de 4096> | root primary/secondary')
            ids=vlan_list(m[1])
            priority=int(m[3]) if m[3] else 28672 if m[4]=='secondary' else 24576
            if not 0<=priority<=61440 or priority%4096:
                raise ValueError('Priorité : multiple de 4096 entre 0 et 61440.')
            if m[4]=='primary':
                lowest=min((n.bridge_id(v)[0] for n in self.lab.nodes.values() if n.kind=='Switch' for v in ids),default=32768)
                priority=min(24576,max(0,lowest-4096))
            for v in ids:
                self.n.priorities[str(v)]=priority
        self.changed=True
        return ''

    def port_command(self,name,low,line):
        p=self.n.ports[name]
        if self.feature_port(name,low):
            return
        if low.startswith('description '):
            p.description=line[12:]
            return
        if low in ('shutdown','no shutdown'):
            p.shutdown=low=='shutdown'
            if low=='no shutdown':
                p.errdisabled=False
            return
        if self.n.kind=='Routeur':
            if low.startswith('encapsulation dot1q '):
                if '.' not in name:
                    raise ValueError('Créer une sous-interface : interface gi0/0.10')
                v=vlan_list(low.split()[-1])
                if len(v)!=1:
                    raise ValueError('Un VLAN par sous-interface.')
                if p.sub_vlan:
                    self.n.interfaces.pop(str(p.sub_vlan),None)
                if any(other!=name and sub.sub_vlan==v[0] for other,sub in self.n.ports.items()):
                    raise ValueError('VLAN déjà associé à une autre sous-interface.')
                p.sub_vlan=v[0]
                if p.address:
                    self.n.interfaces[str(p.sub_vlan)]=p.address
                # Physical router interface represents a tagged uplink.
                self.n.ports[name.split('.')[0]].mode='trunk'
                return
            if low.startswith('ip address '):
                if not p.sub_vlan:
                    raise ValueError('Configurer encapsulation dot1Q avant l’adresse sur une sous-interface.')
                parts=low.split()[2:]
                value=parts[0] if len(parts)==1 else parts[0]+'/'+parts[1]
                address=str(IPv4Interface(value))
                p.address=address
                self.n.interfaces[str(p.sub_vlan)]=address
                return
            if low=='no ip address':
                p.address=''
                self.n.interfaces.pop(str(p.sub_vlan),None)
                return
            raise ValueError('Routeur : description, shutdown, encapsulation dot1Q, ip address. Autres fonctions non implémentées.')
        if self.n.kind!='Switch':
            raise ValueError('Commande réservée au switch.')
        if low in ('switchport mode access','switchport mode trunk','switchport mode dynamic auto','switchport mode dynamic desirable'):
            if low!='switchport mode access' and p.security:
                raise ValueError('Désactiver port-security avant le mode trunk.')
            mode=low[len('switchport mode '):]
            if p.auth_control!='force-authorized' and mode!='access':
                raise ValueError('802.1X configuré : conserver le mode access ou force-authorized.')
            if p.source_guard and mode!='access':
                raise ValueError('Désactiver IP Source Guard avant de quitter le mode access.')
            if mode.startswith('dynamic') and p.nonegotiate:
                raise ValueError('Désactiver nonegotiate avant le mode dynamique.')
            p.mode=mode
        elif low in ('switchport nonegotiate','no switchport nonegotiate'):
            if low=='switchport nonegotiate' and p.mode.startswith('dynamic'):
                raise ValueError('nonegotiate requiert un mode access ou trunk statique.')
            p.nonegotiate=not low.startswith('no ')
        elif low in ('ip dhcp snooping trust','no ip dhcp snooping trust'):
            p.dhcp_trust=not low.startswith('no ')
        elif low in ('ip arp inspection trust','no ip arp inspection trust'):
            p.arp_trust=not low.startswith('no ')
        elif low in ('ip verify source','no ip verify source'):
            if low=='ip verify source' and p.mode!='access':
                raise ValueError('IP Source Guard : access uniquement dans ce modèle.')
            p.source_guard=not low.startswith('no ')
        elif low=='no switchport access vlan':
            p.access_vlan=1
        elif low=='no switchport trunk allowed vlan':
            p.allowed=list(range(1,4095))
        elif low=='no switchport trunk native vlan':
            p.native_vlan=1
        elif low=='no spanning-tree cost':
            p.cost=19
        elif low=='no spanning-tree port-priority':
            p.port_priority=128
        elif low=='no switchport port-security mac-address sticky':
            p.sticky=False
        elif low.startswith('switchport access vlan '):
            ids=vlan_list(low.split()[-1])
            if len(ids)!=1:
                raise ValueError('Un VLAN access attendu.')
            if self.n.vtp_mode=='client' and str(ids[0]) not in self.n.vlans:
                raise ValueError('VLAN absent from VTP client database.')
            p.access_vlan=ids[0]
            if str(ids[0]) not in self.n.vlans:
                self.n.vlans[str(ids[0])]=f'VLAN{ids[0]:04}'
                self.lab.vlan_changed(self.node)
        elif low.startswith('switchport trunk native vlan '):
            ids=vlan_list(low.split()[-1])
            if len(ids)!=1:
                raise ValueError('Un VLAN natif attendu.')
            p.native_vlan=ids[0]
        elif low.startswith('switchport trunk allowed vlan '):
            parts=low[len('switchport trunk allowed vlan '):].split()
            action=parts[0] if len(parts)==2 else 'set'
            ids=vlan_list(parts[-1])
            if action not in ('set','add','remove'):
                raise ValueError('Utiliser une liste, add ou remove.')
            p.allowed=sorted(set(p.allowed)|set(ids)) if action=='add' else sorted(set(p.allowed)-set(ids)) if action=='remove' else ids
        elif low in ('spanning-tree portfast','no spanning-tree portfast'):
            p.portfast=not low.startswith('no ')
        elif low in ('spanning-tree bpduguard enable','no spanning-tree bpduguard enable'):
            p.bpduguard=not low.startswith('no ')
        elif low.startswith('spanning-tree cost '):
            value=int(low.split()[-1])
            if not 1<=value<=200000000:
                raise ValueError('Coût invalide.')
            p.cost=value
        elif low.startswith('spanning-tree port-priority '):
            value=int(low.split()[-1])
            if value%16 or not 0<=value<=240:
                raise ValueError('Priorité de port : multiple de 16 de 0 à 240.')
            p.port_priority=value
        elif low.startswith('channel-group '):
            m=re.fullmatch(r'channel-group (\d+) mode (active|passive|on|auto|desirable)',low)
            if not m or not 1<=int(m[1])<=64:
                raise ValueError('channel-group <1..64> mode active|passive|on|auto|desirable')
            p.channel,p.channel_mode=int(m[1]),m[2]
        elif low=='no channel-group' or re.fullmatch(r'no channel-group \d+',low):
            p.channel,p.channel_mode=0,''
        elif low in ('switchport port-security','no switchport port-security'):
            if low=='switchport port-security' and p.mode!='access':
                raise ValueError('Port-security : ports access uniquement dans ce modèle.')
            p.security=not low.startswith('no ')
        elif low.startswith('switchport port-security maximum '):
            maximum=int(low.split()[-1])
            if not 1<=maximum<=1024:
                raise ValueError('Maximum invalide.')
            p.maximum=maximum
        elif low.startswith('switchport port-security violation '):
            value=low.split()[-1]
            if value not in ('shutdown','restrict','protect'):
                raise ValueError('Violation : shutdown, restrict ou protect.')
            p.violation=value
        elif low=='switchport port-security mac-address sticky':
            p.sticky=True
        elif low.startswith('switchport port-security mac-address '):
            mac=low.split()[-1].replace(':','').replace('.','').replace('-','')
            if not re.fullmatch('[0-9a-f]{12}',mac):
                raise ValueError('Adresse MAC invalide.')
            mac=':'.join(mac[i:i+2] for i in range(0,12,2))
            if mac not in p.secure_macs:
                if len(p.secure_macs)>=p.maximum:
                    raise ValueError('Maximum de MAC sécurisées atteint.')
                p.secure_macs.append(mac)
        else:
            raise ValueError('Commande d’interface non implémentée. Utiliser ?.')
        if name.startswith('po'):
            number=int(name[2:])
            for key,member in self.n.ports.items():
                if not key.startswith('po') and member.channel==number:
                    for field in ('mode','access_vlan','allowed','native_vlan','shutdown','cost'):
                        setattr(member,field,copy.deepcopy(getattr(p,field)))

    def service_command(self,low,line):
        if self.mode in ('if','range'):
            return None
        if self.n.kind=='Switch':
            if low in ('ip dhcp snooping','no ip dhcp snooping'):
                self.n.dhcp_snooping=not low.startswith('no ')
            elif low.startswith(('ip dhcp snooping vlan ','no ip dhcp snooping vlan ')):
                ids=vlan_list(low.split()[-1])
                self.n.snooping_vlans=sorted(set(self.n.snooping_vlans)-set(ids)) if low.startswith('no ') else sorted(set(self.n.snooping_vlans)|set(ids))
            elif low.startswith(('ip arp inspection vlan ','no ip arp inspection vlan ')):
                ids=vlan_list(low.split()[-1])
                self.n.dai_vlans=sorted(set(self.n.dai_vlans)-set(ids)) if low.startswith('no ') else sorted(set(self.n.dai_vlans)|set(ids))
            else:
                return None
            self.changed=True
            return ''
        if self.n.kind!='Routeur':
            return None
        if low in ('service dhcp','no service dhcp'):
            self.n.dhcp_service=not low.startswith('no ')
        elif low.startswith(('ip dhcp excluded-address ','no ip dhcp excluded-address ')):
            parts=low.split('excluded-address ',1)[1].split()
            if not 1<=len(parts)<=2:
                raise ValueError('ip dhcp excluded-address <début> [fin]')
            a,b=str(IPv4Address(parts[0])),str(IPv4Address(parts[-1]))
            if IPv4Address(a)>IPv4Address(b):
                raise ValueError('Plage exclue inversée.')
            if low.startswith('no '):
                self.n.dhcp_excluded=[pair for pair in self.n.dhcp_excluded if list(pair)!=[a,b]]
            elif [a,b] not in self.n.dhcp_excluded:
                self.n.dhcp_excluded.append([a,b])
        elif low.startswith('ip dhcp pool '):
            name=line[len('ip dhcp pool '):]
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',name):
                raise ValueError('Nom du pool invalide.')
            self.n.dhcp_pools.setdefault(name,{})
            self.pool_name=name; self.mode='dhcp'
        elif low.startswith('no ip dhcp pool '):
            self.n.dhcp_pools.pop(line[len('no ip dhcp pool '):],None)
        elif self.mode=='dhcp':
            pool=self.n.dhcp_pools[self.pool_name]
            if low.startswith('network '):
                parts=low.split()[1:]
                if len(parts) not in (1,2):
                    raise ValueError('network <CIDR> ou <réseau> <masque>')
                network=IPv4Network(parts[0] if len(parts)==1 else '/'.join(parts),strict=False)
                pool['network']=str(network)
            elif low.startswith('default-router '):
                pool['gateway']=str(IPv4Address(low.split(' ',1)[1]))
            elif low.startswith('dns-server '):
                pool['dns']=[str(IPv4Address(ip)) for ip in low.split()[1:]]
            elif low.startswith('lease '):
                parts=list(map(int,low.split()[1:]))
                if not 1<=len(parts)<=3:
                    raise ValueError('lease <jours> [heures] [minutes]')
                parts+= [0]*(3-len(parts))
                days,hours,minutes=parts
                if days<0 or not 0<=hours<=23 or not 0<=minutes<=59 or not 60<=days*86400+hours*3600+minutes*60<=31536000:
                    raise ValueError('Durée de bail : 1 minute à 365 jours.')
                pool['lease']=days*86400+hours*3600+minutes*60
            else:
                return None
        else:
            return None
        self.changed=True
        return ''

    def service_show(self,low):
        if low in ('show ip dhcp binding','show ip dhcp pool'):
            if self.n.kind!='Routeur':
                raise ValueError('Serveur DHCP disponible sur routeur.')
            if low.endswith('pool'):
                return '\n'.join(f'Pool {name}: {pool.get("network","not configured")} gateway {pool.get("gateway","none")}' for name,pool in self.n.dhcp_pools.items()) or 'No DHCP pools.'
            return '\n'.join(['IP address        Client MAC          Pool       Remaining(s)']+[f'{b["ip"]:17} {b["mac"]:19} {b["pool"]:10} {int(b["expires"]-self.lab.clock())}' for b in self.lab.leases.values() if b['server']==self.node and b['expires']>self.lab.clock()])
        if low=='show ip dhcp snooping':
            return f'DHCP snooping: {"enabled" if self.n.dhcp_snooping else "disabled"}\nConfigured VLANs: {self.compact(self.n.snooping_vlans)}\nTrusted ports: '+', '.join(name for name,p in self.n.ports.items() if p.dhcp_trust)
        if low=='show ip dhcp snooping binding':
            return '\n'.join(['MacAddress          IpAddress         VLAN Interface  Remaining(s)']+[f'{b["mac"]:19} {b["ip"]:17} {b["vlan"]:<4} {b["port"]:10} {int(b["expires"]-self.lab.clock())}' for b in self.lab.bindings.get(self.node,{}).values() if b['expires']>self.lab.clock()])
        if low in ('show ip arp inspection','show ip arp inspection statistics'):
            stats=self.lab.inspection_stats.get(self.node,{'passed':0,'dropped':0})
            return f'DAI VLANs: {self.compact(self.n.dai_vlans)}\nIngress identity checks passed: {stats["passed"]} dropped: {stats["dropped"]}\nSimplified checks during reachability tests, not real ARP packets.'
        if low.startswith('show dtp interface '):
            name=port_name(low.split()[-1]); p=self.n.ports[name]
            link=self.lab.link_for(self.node,name)
            mode=self.lab.operational_mode(link,self.node) if link else 'down'
            return f'Interface: {name}\nAdministrative mode: {p.mode}\nOperational mode: {mode}\nNegotiation: {"off" if p.nonegotiate else "on"}\nDTP state calculated without frames/timers; VTP domains not modeled.'
        if low=='show ip verify source':
            return '\n'.join(f'{name}: IP Source Guard enabled (DHCP binding required)' for name,p in self.n.ports.items() if p.source_guard) or 'IP Source Guard disabled.'
        return None

    def pc(self,low,line):
        lan=self.lan_command(low,line)
        if lan is not None:
            return lan
        native=self.pc_native(low,line)
        if native is not None:
            return native
        feature=self.feature_pc(low,line)
        if feature is not None:
            return feature
        if low in ('ip link down','ip link up'):
            self.n.ports['eth0'].shutdown=low.endswith('down'); self.changed=True; return ''
        if low in ('ip dhcp','ipconfig /renew'):
            result=self.lab.request_dhcp(self.node)
            self.changed=True
            return result
        if low in ('ip release','ipconfig /release'):
            self.lab.release_dhcp(self.node)
            self.changed=True
            return 'DHCP lease released.'
        if low=='ipconfig' or low=='ip addr' or low=='show ip interface brief':
            return f'{self.n.name} / eth0\nMAC {self.n.mac}\nIPv4 {self.n.address or "non configurée"}\nPasserelle {self.n.gateway or "aucune"}\nDNS {', '.join(self.n.dns) or "aucun"}'
        if low.startswith('hostname '):
            value=line.split(maxsplit=1)[1]
            if not re.fullmatch('[A-Za-z0-9_-]{1,32}',value):
                raise ValueError('Hostname invalide.')
            self.n.hostname=value; self.changed=True; return ''
        if low.startswith('ip dns '):
            self.n.dns=[str(IPv4Address(ip)) for ip in low.split()[2:]]
            self.changed=True; return 'DNS appliqués.'
        if low.startswith('ip address '):
            address=str(IPv4Interface(low[len('ip address '):]))
            self.pc_static_address(address)
            return 'Adresse appliquée.'
        if low.startswith('ip gateway '):
            self.n.gateway=str(IPv4Address(low[len('ip gateway '):]))
            self.changed=True
            return 'Passerelle appliquée.'
        if low.startswith('ping '):
            destination=low.split()[-1]
            resolved=[]
            try:
                IPv4Address(destination)
            except ValueError:
                destination,server=self.lab.resolve_name(self.node,destination)
                resolved=[f'DNS: {low.split()[-1]} → {destination} via {server}']
            ok,trace=self.lab.ping(self.node,destination)
            trace=resolved+trace
            return ('SUCCESS\n' if ok else 'FAILED\n')+'\n'.join(trace)
        if low=='show capabilities':
            return FEATURES
        raise ValueError('Commande PC non implémentée. Utiliser ?. Aucune commande shell réelle n’est exécutée.')

    def show(self,low):
        feature=self.feature_show(low)
        if feature is not None:
            return feature
        layer2=self.layer2_show(low)
        if layer2 is not None:
            return layer2
        service=self.service_show(low)
        if service is not None:
            return service
        if low in ('show running-config','show run'):
            return self.running_config()
        if low=='show startup-config':
            return self.n.startup.get('text','Aucune configuration startup enregistrée.')
        if low=='show version':
            return 'Network LABS 0.3 / CLI pédagogique IOS-like\nSimulation locale, sans système constructeur.\n'+FEATURES
        if low in ('show interfaces status','show ip interface brief'):
            lines=['Port           Status          Mode     VLAN / Adresse']
            for name,p in self.n.ports.items():
                if name.startswith('po'):
                    continue
                link=self.lab.link_for(self.node,name.split('.')[0])
                state='err-disabled' if p.errdisabled else 'disabled' if p.shutdown else 'connected' if link and link.enabled else 'notconnect'
                lines.append(f'{name:14} {state:15} {p.mode:8} {p.address or ("trunk" if p.mode=="trunk" else str(p.access_vlan))}')
            return '\n'.join(lines)
        if low.startswith('show interfaces'):
            if low=='show interfaces trunk':
                return '\n'.join(['Port       Native   Allowed VLANs']+[f'{name:10} {p.native_vlan:<8} {self.compact(p.allowed)}' for name,p in self.n.ports.items() if self.lab.link_for(self.node,name) and self.lab.operational_mode(self.lab.link_for(self.node,name),self.node)=='trunk'])
            if low=='show interfaces switchport':
                names=list(self.n.ports)
            else:
                m=re.fullmatch(r'show interfaces (\S+)(?: switchport)?',low)
                if not m:
                    raise ValueError('show interfaces status | trunk | switchport | gi0/1 switchport')
                names=[port_name(m[1])]
            return '\n\n'.join(f'Name: {name}\nDescription: {self.n.ports[name].description}\nAdministrative Mode: {self.n.ports[name].mode}\nOperational Mode: {self.lab.operational_mode(self.lab.link_for(self.node,name),self.node) if self.lab.link_for(self.node,name) else 'down'}\nAccess VLAN: {self.n.ports[name].access_vlan}\nNative VLAN: {self.n.ports[name].native_vlan}\nAllowed: {self.compact(self.n.ports[name].allowed)}' for name in names)
        if low in ('show vlan','show vlan brief'):
            return '\n'.join(['VLAN  Name                     Access ports']+[f'{v:5} {label:24} '+', '.join(p for p,c in self.n.ports.items() if c.mode=='access' and str(c.access_vlan)==v) for v,label in sorted(self.n.vlans.items(),key=lambda kv:int(kv[0]))])
        if low.startswith('show spanning-tree'):
            m=re.fullmatch(r'show spanning-tree(?: vlan (\d+))?',low)
            if not m:
                raise ValueError('show spanning-tree [vlan N]')
            ids=[int(m[1])] if m[1] else sorted(map(int,self.n.vlans))
            lines=[]
            for v in ids:
                info=self.lab.stp(v).get(self.node)
                if not info:
                    continue
                lines.append(f'VLAN{v:04} / {self.n.stp_mode} — état convergé calculé\nRoot: {info["root"]}  Cost: {info["cost"]}')
                for name,p in self.n.ports.items():
                    link=self.lab.link_for(self.node,name)
                    if not link or not self.lab.eligible(link,v):
                        continue
                    role,state=info['ports'].get(name,('DESG','FWD'))
                    lines.append(f'{name:12} {role:5} {state:5} cost {p.cost} priority {p.port_priority}')
            return '\n'.join(lines) or 'Aucune instance active.'
        if low=='show etherchannel summary':
            lines=['Group  Mode         Ports / état']
            for group in sorted({p.channel for p in self.n.ports.values() if p.channel}):
                members=[]
                for name,p in self.n.ports.items():
                    if p.channel!=group or name.startswith('po'):
                        continue
                    link=self.lab.link_for(self.node,name)
                    ok=bool(link and not p.shutdown and not p.errdisabled and self.lab.channel_state(link)[0])
                    members.append(f'{name}({"P" if ok else "s"})')
                lines.append(f'{group:<6} logical      '+', '.join(members))
            return '\n'.join(lines)+'\nP: agrégé ; s: suspendu (calcul sans LACP/PAgP PDUs).'
        if low in ('show mac address-table','show mac address-table dynamic'):
            return '\n'.join(['VLAN  MAC                Type     Port']+[f'{key.split("/")[0]:5} {key.split("/")[1]:18} DYNAMIC  {port}' for key,port in self.lab.fdb.get(self.node,{}).items()])+'\nApprentissage limité aux chemins parcourus par les tests.'
        if low in ('show cdp neighbors','show lldp neighbors'):
            return '\n'.join(['Voisins physiques déduits des câbles (pas de protocole CDP/LLDP) :']+[f'{l.a_port if l.a==self.node else l.b_port:10} → {l.b if l.a==self.node else l.a}' for l in self.lab.links if self.node in (l.a,l.b)])
        if low.startswith('show port-security'):
            m=re.fullmatch(r'show port-security(?: interface (\S+))?',low)
            if not m:
                raise ValueError('show port-security [interface gi0/1]')
            names=[port_name(m[1])] if m[1] else [n for n,p in self.n.ports.items() if p.security]
            return '\n'.join(f'{n}: enabled={self.n.ports[n].security} maximum={self.n.ports[n].maximum} violation={self.n.ports[n].violation} violations={self.n.ports[n].violations}\n  secure MAC: '+', '.join(self.n.ports[n].secure_macs+self.lab.secure_dynamic.get(self.node+'/'+n,[])) for n in names) or 'Port-security désactivé.'
        if low=='show ip route' and self.n.kind=='Routeur':
            return '\n'.join(f'C {IPv4Interface(ip).network} directly connected, VLAN {v}' for v,ip in self.n.interfaces.items()) or 'Aucune route connectée.'
        raise ValueError('Commande show non implémentée. Utiliser ?. ')

    @staticmethod
    def compact(ids):
        return 'all' if len(ids)==4094 else 'none' if not ids else ','.join(map(str,ids))

    def running_config(self):
        lines=['! Network LABS — sous-ensemble IOS-like',f'hostname {self.n.hostname or self.n.name}']
        if is_firewall(self.n):
            lines.extend(['firewall mode '+self.n.firewall_mode,'firewall default '+self.n.firewall_default])
            lines.extend(f'firewall rule {r["id"]} {r["action"]} {r["source"]} {r["target"]}' for r in sorted(self.n.firewall_rules,key=lambda r:r['id']))
        if self.n.kind=='Routeur':
            if not self.n.dhcp_service:
                lines.append('no service dhcp')
            for a,b in self.n.dhcp_excluded:
                lines.append(f'ip dhcp excluded-address {a} {b}')
            for name,pool in self.n.dhcp_pools.items():
                lines.append('ip dhcp pool '+name)
                if 'network' in pool:
                    lines.append(' network '+pool['network'])
                if pool.get('gateway'):
                    lines.append(' default-router '+pool['gateway'])
                if pool.get('dns'):
                    lines.append(' dns-server '+' '.join(pool['dns']))
                seconds=pool.get('lease',86400)
                days,rem=divmod(seconds,86400); hours,rem=divmod(rem,3600)
                lines.append(f' lease {days} {hours} {rem//60}')
                lines.append(' exit')
        if self.n.kind=='Switch':
            if self.n.aaa_enabled:
                lines.append('aaa new-model')
            if self.n.dot1x_radius:
                lines.append('aaa authentication dot1x default group radius')
            if self.n.dot1x_enabled:
                lines.append('dot1x system-auth-control')
            if not self.n.igmp_enabled:
                lines.append('no ip igmp snooping')
            if self.n.igmp_disabled_vlans:
                lines.append('no ip igmp snooping vlan '+self.compact(self.n.igmp_disabled_vlans))
            if self.n.igmp_unknown!='flood':
                lines.append('ip igmp snooping unknown-multicast action '+self.n.igmp_unknown)
            if self.n.dhcp_snooping:
                lines.append('ip dhcp snooping')
            if self.n.snooping_vlans:
                lines.append('ip dhcp snooping vlan '+self.compact(self.n.snooping_vlans))
            if self.n.dai_vlans:
                lines.append('ip arp inspection vlan '+self.compact(self.n.dai_vlans))
            lines.extend(['vtp version 2','vtp mode '+self.n.vtp_mode])
            if self.n.vtp_domain:
                lines.append('vtp domain '+self.n.vtp_domain)
            if self.n.vtp_password:
                lines.append('vtp password '+self.n.vtp_password)
            lines.append('spanning-tree mode '+self.n.stp_mode)
            if self.n.stp_mode=='mst':
                lines.append('spanning-tree mst configuration')
                if self.n.mst_name:
                    lines.append(' name '+self.n.mst_name)
                lines.append(' revision '+str(self.n.mst_revision))
                for instance in sorted(set(self.n.mst_map.values())):
                    lines.append(' instance '+str(instance)+' vlan '+','.join(v for v,i in self.n.mst_map.items() if i==instance))
                lines.append(' exit')
            for v,name in sorted(self.n.vlans.items(),key=lambda x:int(x[0])):
                lines.extend([f'vlan {v}',f' name {name}'])
            for v,priority in self.n.priorities.items():
                lines.append(f'spanning-tree mst {v[4:]} priority {priority}' if v.startswith('mst:') else f'spanning-tree vlan {v} priority {priority}')
        for name,p in sorted(self.n.ports.items(),key=lambda item:not item[0].startswith('po')):
            lines.append('interface '+name)
            if p.description and not p.description.startswith('__logical__'):
                lines.append(' description '+p.description)
            if self.n.kind=='Switch':
                lines.extend([' switchport mode '+p.mode,' switchport access vlan '+str(p.access_vlan),' switchport trunk native vlan '+str(p.native_vlan),' switchport trunk allowed vlan '+self.compact(p.allowed)])
                if p.auth_control!='force-authorized':
                    lines.append(' authentication port-control '+p.auth_control)
                if p.authenticator:
                    lines.append(' dot1x pae authenticator')
                if p.nonegotiate:
                    lines.append(' switchport nonegotiate')
                if p.dhcp_trust:
                    lines.append(' ip dhcp snooping trust')
                if p.arp_trust:
                    lines.append(' ip arp inspection trust')
                if p.source_guard:
                    lines.append(' ip verify source')
                if p.cost!=19:
                    lines.append(' spanning-tree cost '+str(p.cost))
                if p.port_priority!=128:
                    lines.append(' spanning-tree port-priority '+str(p.port_priority))
                if p.portfast:
                    lines.append(' spanning-tree portfast')
                if p.bpduguard:
                    lines.append(' spanning-tree bpduguard enable')
                if p.channel:
                    lines.append(f' channel-group {p.channel} mode {p.channel_mode}')
                if p.security:
                    lines.extend([' switchport port-security',f' switchport port-security maximum {p.maximum}',f' switchport port-security violation {p.violation}'])
                    if p.sticky:
                        lines.append(' switchport port-security mac-address sticky')
                    lines.extend(' switchport port-security mac-address '+mac for mac in p.secure_macs)
            if p.sub_vlan:
                lines.append(' encapsulation dot1Q '+str(p.sub_vlan))
            if p.address:
                lines.append(' ip address '+p.address)
            lines.extend([' shutdown' if p.shutdown else ' no shutdown','!'])
        lines.append('end')
        return '\n'.join(lines)
