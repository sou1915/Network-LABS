"""Simplified DHCP allocation and ingress identity checks; not a packet engine."""
from ipaddress import IPv4Interface, IPv4Network, IPv4Address
from itertools import islice
import time

class Services:
    def init_services(self):
        self.bindings={}
        self.leases={}
        self.service_events=[]
        self.inspection_stats={}
        self.clock=time.time

    def validate_sender(self,switch,port,vlan,mac,ip):
        node=self.nodes[switch]; p=node.ports[port]
        need_arp=vlan in node.dai_vlans and not p.arp_trust
        if not need_arp and not p.source_guard:
            return
        binding=self.bindings.get(switch,{}).get(f'{vlan}/{mac}')
        valid=bool(binding and binding['ip']==ip and binding['port']==port and binding['expires']>self.clock())
        stats=self.inspection_stats.setdefault(switch,{'passed':0,'dropped':0})
        if not valid:
            stats['dropped']+=1
            reason='Dynamic ARP Inspection' if need_arp else 'IP Source Guard'
            raise ValueError(f'{switch}/{port} : {reason} — association IP/MAC/VLAN/port absente ou invalide.')
        stats['passed']+=1

    def request_dhcp(self,client):
        """Atomic allocation after validating the modeled Offer/ACK return path."""
        node=self.nodes[client]
        if node.kind!='PC':
            raise ValueError('DHCP client disponible sur PC uniquement.')
        vlan=self.vlan(client)
        self.service_events=[{'phase':'DISCOVER','client':client,'vlan':vlan}]
        candidates=[]
        for server in sorted(self.nodes.values(),key=lambda n:n.name):
            if server.kind!='Routeur' or not server.dhcp_service:
                continue
            interface=server.interfaces.get(str(vlan))
            if not interface or not self.router_interface_up(server,vlan):
                continue
            path,hops=self.path_details(client,server.name,vlan)
            if not path:
                continue
            for name,pool in server.dhcp_pools.items():
                if 'network' not in pool:
                    continue
                network=IPv4Network(pool['network'])
                if IPv4Interface(interface).ip in network:
                    candidates.append((server,name,pool,network,path,hops))
        if not candidates:
            raise ValueError('DHCP timeout : aucun pool joignable dans ce VLAN (pas de relais DHCP).')
        rejected=[]
        for server,name,pool,network,path,hops in candidates:
            reverse=[(i,b,a,v) for i,a,b,v in reversed(hops)]
            blocked=False
            for i,a,b,v in reverse:
                if self.nodes[b].kind!='Switch':
                    continue
                l=self.links[i]; ingress=l.a_port if l.a==b else l.b_port
                switch=self.nodes[b]
                if switch.dhcp_snooping and v in switch.snooping_vlans and not switch.ports[ingress].dhcp_trust:
                    rejected.append(f'{b}/{ingress} : réponse DHCP rejetée (port non trusted).')
                    blocked=True; break
            if blocked:
                continue
            used={IPv4Interface(n.address).ip for n in self.nodes.values() if n.address and n.name!=client}
            used.update(IPv4Interface(ip).ip for n in self.nodes.values() for ip in n.interfaces.values())
            used.update(IPv4Address(lease['ip']) for key,lease in self.leases.items() if key!=client and lease['expires']>self.clock())
            excluded=[(IPv4Address(a),IPv4Address(b)) for a,b in server.dhcp_excluded]
            def available(ip):
                return ip in network and ip not in (network.network_address,network.broadcast_address) and ip not in used and not any(a<=ip<=b for a,b in excluded)
            old=self.leases.get(client)
            ip=IPv4Address(old['ip']) if old and old['server']==server.name and old['pool']==name and available(IPv4Address(old['ip'])) else next((ip for ip in islice(network.hosts(),65536) if available(ip)),None)
            if ip is None:
                rejected.append('Pool épuisé ou recherche limitée aux 65536 premiers hôtes.'); continue
            gateway=pool.get('gateway','')
            if gateway and IPv4Address(gateway) not in network:
                raise ValueError('Passerelle du pool hors sous-réseau.')
            expires=self.clock()+pool.get('lease',86400)
            record={'ip':str(ip),'mac':node.mac,'vlan':vlan,'client':client,'server':server.name,'pool':name,'expires':expires}
            self.service_events.extend([{'phase':phase,'client':client,'server':server.name,'vlan':vlan,'ip':str(ip)} for phase in ('OFFER','REQUEST','ACK')])
            # Bind only client-facing untrusted ingress ports along the request path.
            for i,a,b,v in hops:
                if self.nodes[b].kind!='Switch':
                    continue
                l=self.links[i]; ingress=l.a_port if l.a==b else l.b_port
                switch=self.nodes[b]
                if switch.dhcp_snooping and v in switch.snooping_vlans and not switch.ports[ingress].dhcp_trust:
                    self.bindings.setdefault(b,{})[f'{v}/{node.mac}']={**record,'port':ingress}
            self.leases[client]=record
            node.address_mode='dhcp'
            node.address=f'{ip}/{network.prefixlen}'; node.gateway=gateway; node.dns=pool.get('dns',[])[:]
            return f'DHCP DISCOVER on eth0 (modeled)\nDHCP OFFER from {server.name}: {ip}\nDHCP REQUEST for {ip}\nDHCP ACK from {server.name}\nIP address: {node.address}\nDefault gateway: {gateway or "none"}\nDNS: {", ".join(node.dns) or "none"}\nLease: {pool.get("lease",86400)} seconds'
        raise ValueError('DHCP failed : '+' '.join(rejected))

    def release_dhcp(self,client):
        lease=self.leases.pop(client,None)
        if lease:
            for table in self.bindings.values():
                for key,record in list(table.items()):
                    if record['client']==client:
                        del table[key]
        self.nodes[client].address=''; self.nodes[client].gateway=''; self.nodes[client].dns=[]
