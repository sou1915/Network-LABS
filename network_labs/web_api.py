"""Device management API. All calls execute on the application's owner thread."""
from dataclasses import asdict
from hashlib import sha256
from .cli import Session
from .device_config import apply_device_commands,fingerprint
from .profiles import PROFILES,profile_role

class Conflict(ValueError):
    pass

class DeviceAPI:
    def __init__(self,app):self.app=app

    def revision(self,node):return sha256((str(id(self.app.lab))+fingerprint(node)).encode()).hexdigest()

    def snapshot(self,node):
        n=self.app.lab.nodes[node];p=PROFILES[n.profile]
        data=asdict(n);data.pop('startup',None);data['mac']=n.mac
        for port in data['ports'].values():port['allowed']=Session.compact(port['allowed'])
        links=[]
        for link in self.app.lab.links:
            if node in (link.a,link.b):
                local=link.a_port if node==link.a else link.b_port
                peer=link.b if node==link.a else link.a
                links.append({'port':local,'peer':peer,'enabled':link.enabled and not any(q.shutdown or q.errdisabled for q in self.app.lab.ends(link))})
        return {'node':data,'profile':{'brand':p.brand,'model':p.model,'role':profile_role(p),'scope':p.scope},
                'revision':self.revision(n),'links':links,
                'inventory':[{'id':name,'brand':PROFILES[x.profile].brand,'model':PROFILES[x.profile].model,'role':profile_role(PROFILES[x.profile])} for name,x in self.app.lab.nodes.items()],
                'configuration':Session(self.app.lab,node).execute('ipconfig') if n.kind=='PC' else Session(self.app.lab,node).running_config(),
                'firewall_log':self.app.lab.firewall_log[-30:],'counters':self.app.lab.firewall_counters.get(node,{'allow':0,'deny':0})}

    def dispatch(self,action,payload):
        node=payload.get('node')
        if not isinstance(node,str) or node not in self.app.lab.nodes:raise ValueError('Équipement absent du lab courant.')
        if action=='state':return self.snapshot(node)
        if action=='cli':
            self.app.open_cli(node);self.app.root.lift()
            return {'ok':True}
        if action=='apply':
            if payload.get('revision')!=self.revision(self.app.lab.nodes[node]):
                raise Conflict('Configuration modifiée dans le logiciel ou la CLI. Actualiser avant de réappliquer.')
            commands=payload.get('commands')
            if not isinstance(commands,list) or not 1<=len(commands)<=256 or any(not isinstance(c,str) or len(c)>4096 or '\n' in c or '\r' in c for c in commands):
                raise ValueError('Liste de commandes invalide.')
            apply_device_commands(self.app.lab,node,commands)
            self.app.changed('Configuration web appliquée : '+node)
            return self.snapshot(node)
        if action=='test':
            target=payload.get('target','');protocol=payload.get('protocol','icmp')
            if not isinstance(target,str) or len(target)>253:raise ValueError('Destination invalide.')
            if protocol=='icmp':ok,trace=self.app.lab.ping(node,target)
            elif protocol in ('tcp','udp'):ok,trace=self.app.lab.probe(node,target,protocol,payload.get('port',0))
            else:raise ValueError('Protocole icmp/tcp/udp requis.')
            self.app.animate_result(ok,trace[-1])
            return {'ok':ok,'trace':trace,'paths':self.app.lab.last_paths,'firewall_log':self.app.lab.firewall_log[-30:]}
        raise ValueError('Action inconnue.')
