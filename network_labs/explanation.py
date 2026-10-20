"""Explain recorded model decisions without inventing packet captures or handshakes."""
from functools import wraps
from ipaddress import IPv4Interface,IPv4Address

def recorded(protocol):
 def decorate(fn):
  @wraps(fn)
  def run(self,source,destination,*args,**kwargs):
   proto=protocol if protocol!='probe' else (args[0] if args else kwargs.get('protocol','tcp'))
   port=0 if protocol!='probe' else (args[1] if len(args)>1 else kwargs.get('port',0))
   self.last_paths,self.last_hops,self.events=[],[],[]
   self.last_micro_capture=None
   self.firewall_log=[]
   ok,trace=fn(self,source,destination,*args,**kwargs)
   self.last_request={'source':source,'destination':destination,'protocol':proto,'port':port}
   self.last_trace=list(trace);self.last_outcome=ok
   if getattr(self,'execution_backend','model')=='wasm':
    from .micro_appliances.project import explain as explain_micro
    self.last_explanation=explain_micro(self,ok,trace)
   else:self.last_explanation=explain(self,ok,trace)
   return ok,trace
  return run
 return decorate

def explain(lab,ok,trace):
 request=getattr(lab,'last_request',{});source=request.get('source','');dest=request.get('destination','')
 proto=str(request.get('protocol','icmp')).upper();port=request.get('port',0)
 steps=[]
 def add(title,body,phase='Préparation',evidence=''):
  steps.append({'number':len(steps)+1,'phase':phase,'title':title,'body':body,'evidence':evidence})
 add('Demande de communication',f'{source} veut joindre {dest} avec {proto}'+(f', port de service {port}.' if port else '.'),evidence='Transaction calculée dans le moteur ; aucun paquet réel envoyé.')
 for line in trace:
  if line.startswith('DNS:'):add('Résolution du nom',line,evidence='Le contrôle DNS est une transaction UDP/53 distincte.')
 n=lab.nodes.get(source)
 if n and n.address:
  try:
   address=IPv4Interface(n.address);target=IPv4Address(dest)
   if target in address.network:add('Destination dans le réseau local',f'{target} appartient à {address.network}. Le poste cherche un chemin dans son VLAN ; une passerelle n’est pas nécessaire.')
   else:add('Destination hors du réseau local',f'{target} n’appartient pas à {address.network}. Le poste doit utiliser sa passerelle configurée : {n.gateway or "aucune"}.')
  except ValueError:pass
 for phase,hops in enumerate(lab.last_hops):
  for index,a,b,vlan in hops:
   link=lab.links[index];ap=link.a_port if link.a==a else link.b_port;bp=link.b_port if link.b==b else link.a_port
   p=lab.nodes[a].ports[ap];q=lab.nodes[b].ports[bp]
   tagged=(p.mode=='trunk' and vlan!=p.native_vlan) or (q.mode=='trunk' and vlan!=q.native_vlan)
   add(f'{a} → {b}',f'La liaison {ap} → {bp} transporte le VLAN {vlan}. '+('La représentation du lien utilise une trame 802.1Q taguée.' if tagged else 'La représentation du lien utilise une trame non taguée.'), 'Aller' if phase==0 else 'Retour',f'Chemin effectivement retenu par le moteur, lien {index+1}.')
 for line in getattr(lab,'firewall_log',[]):add('Décision du firewall',line,'Filtrage', 'Journal du test courant, pas un journal système constructeur.')
 final=trace[-1] if trace else ('Communication accessible.' if ok else 'Aucun résultat disponible.')
 add('Résultat : accessible' if ok else 'Résultat : interrompu',final,'Résultat')
 checks=[]
 if not ok:
  text=' '.join(trace).lower()
  if 'service' in text and ('aucun' in text or 'absent' in text):checks=['Vérifier que le service est activé sur le port TCP/UDP demandé.']
  elif 'firewall' in text or 'deny' in text or 'refus' in text:checks=['Lire la décision firewall ci-dessus et vérifier la première règle correspondante, son protocole et son port.']
  elif 'dns' in text or 'nom' in text:checks=['Vérifier le DNS du client, l’enregistrement A et l’accès UDP/53 au serveur.']
  else:checks=['Vérifier les interfaces et câbles, le VLAN access et les VLANs autorisés sur les trunks.','Vérifier le masque IPv4, puis la passerelle et les sous-interfaces si la destination est dans un autre réseau.','Consulter STP et les protections de port. Ces pistes ne désignent pas une cause unique prouvée.']
 return {'title':f'{source} → {dest} · {proto}'+(f'/{port}' if port else ''),'ok':ok,'summary':(('Service accessible : trajet aller-retour validé et port disponible.' if proto in ('TCP','UDP') else 'Communication autorisée : trajet aller-retour validé.') if ok else 'Test interrompu : '+final),'steps':steps,'checks':checks,'limits':'Les sauts représentent le chemin retenu. ARP, négociations TCP et temps de transmission ne sont pas capturés ni rejoués.'}
