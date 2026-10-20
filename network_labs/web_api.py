"""Device management API. All calls execute on the application's owner thread."""
import json
from dataclasses import asdict
from hashlib import sha256
from .cli import Session
from .device_config import apply_device_commands,apply_native_commands,fingerprint
from .profiles import PROFILES,profile_role
from .device_identity import identity

class Conflict(ValueError):
    pass

class DeviceAPI:
    def __init__(self,app):self.app=app

    def revision(self,node):return sha256((str(id(self.app.lab))+fingerprint(node)).encode()).hexdigest()

    def snapshot(self,node):
        n=self.app.lab.nodes[node];p=PROFILES[n.profile]
        data=asdict(n);data.pop('startup',None);data['mac']=self.app.lab.display_mac(node)
        from .firewall import ordered_rules
        data['firewall_rules']=[r.copy() for r in ordered_rules(n)]
        for port in data['ports'].values():port['allowed']=Session.compact(port['allowed'])
        links=[]
        for link in self.app.lab.links:
            if node in (link.a,link.b):
                local=link.a_port if node==link.a else link.b_port
                peer=link.b if node==link.a else link.a
                links.append({'port':local,'peer':peer,'enabled':link.enabled and not any(q.shutdown or q.errdisabled for q in self.app.lab.ends(link))})
        return {'node':data,'profile':{'brand':p.brand,'model':p.model,'role':profile_role(p),'scope':p.scope,**identity(n.profile)},
                'revision':self.revision(n),'links':links,
                'inventory':[{'id':name,'brand':PROFILES[x.profile].brand,'model':PROFILES[x.profile].model,'role':profile_role(PROFILES[x.profile])} for name,x in self.app.lab.nodes.items()],
                'configuration':self.configuration(n),
                'firewall_log':self.app.lab.firewall_log[-30:],'counters':self.app.lab.firewall_counters.get(node,{'allow':0,'deny':0})}

    def configuration(self,n):
        if identity(n.profile)['console']=='ios':return Session(self.app.lab,n.name).running_config()
        state={key:getattr(n,key) for key in ('name','profile','hostname','address_mode','address','gateway','dns','services')}
        state['ports']={name:{'shutdown':p.shutdown,'description':p.description,'mode':p.mode,'access_vlan':p.access_vlan} for name,p in n.ports.items()}
        if profile_role(PROFILES[n.profile])=='Firewall':
            state.update(mode=n.firewall_mode,default=n.firewall_default,rules=n.firewall_rules)
        elif n.kind=='Switch':state['vlans']=n.vlans
        return json.dumps(state,ensure_ascii=False,indent=2)

    def dispatch(self,action,payload):
        node=payload.get('node')
        if not isinstance(node,str) or node not in self.app.lab.nodes:raise ValueError('Équipement absent du lab courant.')
        if action=='state':return self.snapshot(node)
        if action=='cli':
            self.app.open_cli(node);self.app.root.lift()
            return {'ok':True}
        if action in ('apply','native'):
            if payload.get('revision')!=self.revision(self.app.lab.nodes[node]):
                raise Conflict('Configuration modifiée dans le logiciel ou la CLI. Actualiser avant de réappliquer.')
            commands=payload.get('commands')
            if not isinstance(commands,list) or not 1<=len(commands)<=256 or any(not isinstance(c,str) or len(c)>4096 or '\n' in c or '\r' in c for c in commands):
                raise ValueError('Liste de commandes invalide.')
            if action=='native':apply_native_commands(self.app.lab,node,commands)
            else:apply_device_commands(self.app.lab,node,commands)
            self.app.changed('Configuration web appliquée : '+node)
            return self.snapshot(node)
        if action=='test':
            target=payload.get('target','');protocol=payload.get('protocol','icmp')
            if not isinstance(target,str) or len(target)>253:raise ValueError('Destination invalide.')
            if protocol=='icmp':ok,trace=self.app.lab.ping(node,target)
            elif protocol in ('tcp','udp'):ok,trace=self.app.lab.probe(node,target,protocol,payload.get('port',0))
            else:raise ValueError('Protocole icmp/tcp/udp requis.')
            self.app.animate_result(ok,trace[-1])
            return {'ok':ok,'trace':trace,'paths':self.app.lab.last_paths,'firewall_log':self.app.lab.firewall_log[-30:],'explanation':self.app.lab.last_explanation}
        raise ValueError('Action inconnue.')
