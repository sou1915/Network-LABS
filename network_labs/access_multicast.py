"""Modeled access authorization and IGMP snooping; no EAP/RADIUS/IGMP packets."""
from ipaddress import IPv4Address,IPv4Interface,IPv4Network
from hmac import compare_digest

class AccessMulticast:
    def init_access_multicast(self):
        self.radius_users={}
        self.auth_sessions={}
        self.last_multicast=[]

    def access_allowed(self,node,port):
        switch=self.nodes[node]; p=switch.ports[port]
        if switch.kind!='Switch' or not switch.dot1x_enabled:
            return True
        if p.auth_control=='force-authorized':
            return True
        if p.auth_control=='force-unauthorized':
            return False
        if not switch.aaa_enabled or not switch.dot1x_radius or not p.authenticator:
            return False
        link=self.link_for(node,port)
        session=self.auth_sessions.get(node+'/'+port)
        if not link or not session:
            return False
        peer=link.b if link.a==node else link.a
        return session['mac']==self.nodes[peer].mac

    def authenticate(self,client,user,password):
        pc=self.nodes[client]
        link=next((l for l in self.links if client in (l.a,l.b)),None)
        if pc.kind!='PC' or not link:
            raise ValueError('802.1X: PC connecté directement à un switch requis.')
        switch_name=link.b if link.a==client else link.a
        port=link.b_port if link.a==client else link.a_port
        switch=self.nodes[switch_name]; p=switch.ports[port]
        if switch.kind!='Switch' or p.mode!='access':
            raise ValueError('802.1X: modèle limité aux PC sur ports access.')
        key=switch_name+'/'+port
        self.auth_sessions.pop(key,None)
        if not link.enabled or p.shutdown or p.errdisabled or not switch.dot1x_enabled or not switch.aaa_enabled or not switch.dot1x_radius or not p.authenticator or p.auth_control!='auto':
            raise ValueError('802.1X: vérifier AAA, méthode RADIUS, contrôle global, PAE, port-control auto et câble.')
        expected=self.radius_users.get(user)
        if expected is None or not compare_digest(expected.encode(),password.encode()):
            raise ValueError('802.1X Access-Reject (backend RADIUS local simulé).')
        self.auth_sessions[key]={'mac':pc.mac,'user':user}
        pc.dot1x_user=user; pc.dot1x_password=password
        return f'802.1X Access-Accept — {key} authorized.\nBackend local de simulation, sans EAPOL/EAP/RADIUS réel.'

    def logoff(self,client):
        pc=self.nodes[client]
        for key,record in list(self.auth_sessions.items()):
            if record['mac']==pc.mac:
                del self.auth_sessions[key]
        pc.dot1x_user=''; pc.dot1x_password=''

    def join_group(self,client,group):
        address=IPv4Address(group)
        if not address.is_multicast or address in IPv4Network('224.0.0.0/24'):
            raise ValueError('Utiliser un groupe multicast IPv4 hors 224.0.0.0/24, par exemple 239.1.1.1.')
        pc=self.nodes[client]
        if pc.kind!='PC' or not pc.address:
            raise ValueError('IGMP: PC avec adresse IPv4 requis.')
        IPv4Interface(pc.address)
        vlan=self.vlan(client)
        link=next((l for l in self.links if client in (l.a,l.b)),None)
        if link is None:
            raise ValueError('IGMP: PC non connecté.')
        if not self.forwarding(link,vlan):
            raise ValueError('IGMP: port non forwarding / non autorisé.')
        if group not in pc.groups:
            pc.groups.append(group)
        return f'IGMP membership: {client} joined {group} (table modélisée, sans querier/timers).'

    def group_members(self,group,vlan):
        members=[]
        for n in self.nodes.values():
            if n.kind=='PC' and n.address and group in n.groups:
                try:
                    if self.vlan(n.name)==vlan:
                        members.append(n.name)
                except ValueError:
                    pass
        return members

    def snooping_ports(self,switch,group,vlan):
        ports=set(); indexes=set()
        for member in self.group_members(group,vlan):
            _,hops=self.path_details(switch,member,vlan)
            if hops:
                i,a,b,_=hops[0]; link=self.links[i]
                indexes.add(i); ports.add(link.a_port if link.a==switch else link.b_port)
        return ports,indexes

    def multicast(self,source,group):
        address=IPv4Address(group)
        if not address.is_multicast or group.startswith('224.0.0.'):
            raise ValueError('Groupe multicast non pris en charge.')
        if self.nodes[source].kind!='PC' or not self.nodes[source].address:
            raise ValueError('Source multicast: PC IPv4 requis.')
        vlan=self.vlan(source)
        self.last_multicast=[]; self.last_paths=[]; self.last_hops=[]; self.events=[]
        queue=[(source,[source],[])]; seen={source}
        while queue:
            current,path,hops=queue.pop(0)
            node=self.nodes[current]
            if current!=source and node.kind=='PC':
                self.last_multicast.append(current); self.last_paths.append(path); self.last_hops.append(hops)
                continue
            if node.kind=='Routeur':
                continue
            allowed=None
            if node.kind=='Switch' and node.igmp_enabled and vlan not in node.igmp_disabled_vlans:
                _,allowed_indexes=self.snooping_ports(current,group,vlan)
                if allowed_indexes:
                    allowed=allowed_indexes
                elif node.igmp_unknown=='drop':
                    allowed=set()
            for i,link in enumerate(self.links):
                if current not in (link.a,link.b) or not self.forwarding(link,vlan):
                    continue
                other=link.b if current==link.a else link.a
                if other in seen or (allowed is not None and i not in allowed):
                    continue
                next_hop=(i,current,other,vlan)
                self.learn([next_hop],source)
                seen.add(other); queue.append((other,path+[other],hops+[next_hop]))
        return 'Multicast '+group+' — ports PC livrés: '+(', '.join(self.last_multicast) or 'aucun')+'\nModèle L2 sans routage multicast, querier, SSM, mrouter ou paquets IGMP.'
