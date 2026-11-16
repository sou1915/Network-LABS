"""LAN service/port probes. No host sockets, packet stack or application execution."""
from ipaddress import IPv4Address,IPv4Interface
from .explanation import recorded

def service_key(protocol,port):
    port=int(port)
    if protocol not in ('tcp','udp') or not 1<=port<=65535:
        raise ValueError('Service : tcp/udp et port 1..65535.')
    return f'{protocol}/{port}'

class Transport:
    @recorded("probe")
    def probe(self,source,destination,protocol,port):
        if self.execution_backend == 'wasm':
            from .micro_appliances.project import execute
            return execute(self,source,destination,protocol,port)
        try:
            key=service_key(protocol,port);port=int(port)
            dns_trace=[]
            try:address=str(IPv4Address(destination))
            except ValueError:
                address,server=self.resolve_name(source,destination)
                dns_trace=[f'DNS: {destination} → {address} via {server}']
            ok,trace=self._ping_ipv4(source,address,protocol,port)
            trace=dns_trace+trace
            if not ok:return False,trace
            targets=[n for n in self.nodes.values() if n.kind=='PC' and n.address and str(IPv4Interface(n.address).ip)==address]
            if len(targets)!=1:return False,['Service endpoint absent ou ambigu.']
            node=targets[0]
            label='DNS local' if key in ('udp/53','tcp/53') and node.dns_service else node.services.get(key)
            if not label:
                return False,trace+[f'{protocol.upper()}/{port}: aucun service activé sur {node.name}.']
            return True,trace+[f'{protocol.upper()}/{port}: service {label} accessible sur {node.name}. Test de port simulé, pas d’application ni handshake réel.']
        except (ValueError,KeyError) as error:
            self.last_paths,self.last_hops,self.events=[],[],[]
            return False,[str(error)]
