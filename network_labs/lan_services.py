"""LAN DNS service: authoritative IPv4 records and reachability checks, no DNS packets."""
from ipaddress import IPv4Address,IPv4Interface
import re

def dns_name(value):
    value=value.rstrip('.').lower()
    if len(value)>253 or not value or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in value.split('.')):
        raise ValueError('Nom DNS invalide (ASCII, labels de 1 à 63 caractères).')
    return value

class LANServices:
    def resolve_name(self,client,name,server_address=None):
        if self.execution_backend=='wasm':
            raise ValueError('Wasm : DNS pas encore exécuté dans les invités. Utiliser une adresse IPv4.')
        name=dns_name(name)
        node=self.nodes[client]
        servers=[str(IPv4Address(server_address))] if server_address else node.dns[:]
        self.last_paths,self.last_hops,self.events=[],[],[]
        if not servers:
            raise ValueError('DNS: aucun serveur configuré sur '+client)
        errors=[]
        for address in servers:
            matches=[n for n in self.nodes.values() if n.kind=='PC' and n.address and str(IPv4Interface(n.address).ip)==address]
            if len(matches)!=1 or not matches[0].dns_service:
                errors.append(address+': service DNS absent ou adresse ambiguë');continue
            ok,_=self._ping_ipv4(client,address,'udp',53)
            if not ok:
                errors.append(address+': serveur inaccessible');continue
            server=matches[0]
            if name not in server.dns_records:
                raise ValueError(f'DNS NXDOMAIN: {name} sur {address} (zone locale simulée).')
            return server.dns_records[name],address
        self.last_paths,self.last_hops,self.events=[],[],[]
        raise ValueError('DNS: '+ '; '.join(errors))
