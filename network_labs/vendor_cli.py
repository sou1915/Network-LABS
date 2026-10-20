"""Bounded native-syntax consoles. Never execute commands on the host OS.

The engine's canonical grammar remains separate, for imports and typed forms.
Only documented subsets are exposed as native commands. Unsupported syntax fails.
"""
import copy,json,re,shlex
from ipaddress import IPv4Network
from .cli import Session
from .device_identity import identity
from .device_config import fingerprint
from .firewall import firewall_rule,ordered_rules,forget_native_policy

SERVICES={'ALL':('any',0),'PING':('icmp',0),'HTTP':('tcp',80),'HTTPS':('tcp',443),'DNS':('tcpudp',53),'SMB':('tcp',445),'RDP':('tcp',3389)}

def hostname(value):
 if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',value):raise ValueError('Nom système : 1..32 lettres/chiffres/_/-.')
 return value

class NativeConsole:
 def __init__(self,lab,node):
  self.lab,self.node=lab,node;self.mode='user';self.changed=False;self.history=[]
  self.dialect=identity(self.n.profile)['console'];self.context='';self.entry=None;self.draft=None;self.base=None
 @property
 def n(self):return self.lab.nodes[self.node]
 @property
 def prompt(self):
  name=self.n.hostname or self.node
  if self.dialect=='fortios':return name+(f' ({self.entry if self.entry is not None else self.context.split()[-1]})' if self.context else '')+' #'
  if self.dialect=='panos':return 'admin@'+name+('#' if self.mode=='config' else '>')
  if self.dialect=='routeros':return f'[admin@{name}] >'
  return name+' [console indisponible]'
 def help(self,prefix=''):
  return '\n'.join(p for p in self.help_patterns() if p.startswith(prefix.strip())) or 'Commande hors du sous-ensemble implémenté.'
 def help_patterns(self):
  return {'fortios':['get system status','show system interface','show firewall address','show firewall policy','config system global','set hostname <name>','config system interface','edit port1','set status up','set status down','set alias <text>','unset alias','config firewall address','edit <name>','set subnet <IPv4> <mask>','delete <name>','config firewall policy','edit <id>','set name <text>','set comments <text>','unset name','unset comments','set srcintf any','set dstintf any','set srcaddr all','set dstaddr all','set action accept','set action deny','set schedule always','set service HTTPS','delete <id>','move <id> before <id>','move <id> after <id>','show','next','end'],
   'panos':['show system info','show config running','configure','set deviceconfig system hostname <name>','set rulebase security rules <name> from any to any source any destination any application any service service-https action allow','delete rulebase security rules <name>','show','commit','revert config','exit'],
   'routeros':['/system identity print','/system identity set name=<name>','/interface print','/interface ethernet print','/interface set ether1 disabled=yes','/interface set ether1 disabled=no','/interface set ether1 comment=<text>'],
   'unavailable':['Aucune CLI constructeur implémentée pour ce profil. Utiliser son interface graphique/web.'],
  }.get(self.dialect,[])
 def completion_candidates(self,prefix):return [x for x in self.help_patterns() if '<' not in x and x.startswith(prefix)]
 def execute(self,line):
  self.changed=False;line=line.strip()
  if not line:return ''
  self.history.append(line)
  if line in ('?','help'):return self.help()
  try:
   if self.dialect=='fortios':return self.fortios(line)
   if self.dialect=='panos':return self.panos(line)
   if self.dialect=='routeros':return self.routeros(line)
   raise ValueError('CLI constructeur non implémentée pour ce profil. Utiliser la gestion web ; aucune syntaxe IOS de substitution.')
  except (ValueError,KeyError,IndexError) as error:return '% '+str(error)
 def checkpoint(self):
  if self.base is not None and self.base!=fingerprint(self.n):raise ValueError('Configuration modifiée ailleurs. Quitter/recharger le contexte avant de réappliquer.')
 def touch(self):
  self.changed=True;self.base=fingerprint(self.n);self.lab.firewall_sessions.pop(self.node,None)
 def rule(self,number,entry,addresses=None):
  if not {'srcintf','dstintf','srcaddr','dstaddr','action','schedule','service'}<=entry.keys():raise ValueError('Règle incomplète : srcintf/dstintf/srcaddr/dstaddr/action/schedule/service requis.')
  if entry['srcintf']!='any' or entry['dstintf']!='any' or entry['schedule']!='always':raise ValueError('Sous-ensemble transparent : interfaces any et schedule always uniquement.')
  addresses=self.n.vendor.get('fortios_addresses',{}) if addresses is None else addresses
  def addr(name):
   if name=='all':return 'any'
   if name not in addresses:raise ValueError('Objet adresse absent : '+name)
   return addresses[name]
  if entry['service'].upper() not in SERVICES:raise ValueError('Services implémentés : '+', '.join(SERVICES))
  proto,port=SERVICES[entry['service'].upper()]
  if entry['action'] not in ('accept','deny'):raise ValueError('Action accept/deny attendue.')
  return firewall_rule(number,'allow' if entry['action']=='accept' else 'deny',addr(entry['srcaddr']),addr(entry['dstaddr']),proto,port)
 def fortios(self,line):
  words=shlex.split(line)
  if line=='get system status':return 'Hostname: '+(self.n.hostname or self.node)+'\nVirtual transparent LAN model · no FortiOS firmware'
  if line=='show system interface':return 'config system interface\n'+'\n'.join(f'    edit "port{i}"\n        set status {"down" if p.shutdown else "up"}\n        set alias {json.dumps(p.description,ensure_ascii=False)}\n    next' for i,p in enumerate(self.n.ports.values(),1))+'\nend'
  if line=='show firewall address':
   entries=[]
   for name,cidr in self.n.vendor.get('fortios_addresses',{}).items():
    net=IPv4Network(cidr);entries.append('    edit '+json.dumps(name,ensure_ascii=False)+'\n        set subnet '+str(net.network_address)+' '+str(net.netmask)+'\n    next')
   return 'config firewall address\n'+'\n'.join(entries)+'\nend'
  if line=='show firewall policy':
   by_id={r['id']:r for r in self.n.vendor.get('fortios_policies',[])}
   entries=[];unmapped=[]
   for rule in ordered_rules(self.n):
    r=by_id.get(rule['id'])
    if r is None:unmapped.append(str(rule['id']));continue
    entries.append('    edit '+str(r['id'])+'\n'+'\n'.join('        set '+key+' '+(value if key=='action' else json.dumps(value,ensure_ascii=False)) for key,value in r.items() if key!='id')+'\n    next')
   return 'config firewall policy\n'+'\n'.join(entries)+'\nend'+ ('\nSimulation: politiques sans objets FortiOS natifs non exportées : '+', '.join(unmapped) if unmapped else '')
  if line.startswith('config '):
   if self.context:raise ValueError('Utiliser end avant un nouveau contexte.')
   if line not in ('config system global','config system interface','config firewall address','config firewall policy'):raise ValueError('Contexte FortiOS non implémenté.')
   self.context=line;self.mode='config';self.entry=None;self.draft={};self.base=fingerprint(self.n);return ''
  if line=='end':
   if self.entry is not None:self.finish_fortios_entry()
   self.context='';self.entry=None;self.draft=None;self.base=None;self.mode='user';return ''
  if line=='abort':self.context='';self.entry=None;self.draft=None;self.base=None;self.mode='user';return ''
  if not self.context:raise ValueError('Commande FortiOS non implémentée. Utiliser help.')
  if line=='show':
   if self.entry is not None:return 'edit '+json.dumps(self.entry,ensure_ascii=False)+'\n'+'\n'.join('    set '+key+' '+json.dumps(value,ensure_ascii=False) for key,value in self.draft.items())+'\nnext'
   return self.fortios('show '+self.context[len('config '):]) if self.context!='config system global' else 'config system global\n    set hostname '+json.dumps(self.n.hostname or self.node)+'\nend'
  if words[0]=='delete' and len(words)==2 and self.entry is None:
   self.checkpoint()
   if self.context=='config firewall policy':
    number=int(words[1])
    if not any(r['id']==number for r in self.n.firewall_rules):raise ValueError('ID de politique absent.')
    self.n.firewall_rules=[r for r in self.n.firewall_rules if r['id']!=number];forget_native_policy(self.n,number)
    self.n.vendor['fortios_policy_order']=[r['id'] for r in ordered_rules(self.n)]
   elif self.context=='config firewall address':
    name=words[1];objects=self.n.vendor.get('fortios_addresses',{})
    if name not in objects:raise ValueError('Objet adresse absent.')
    if any(name in (r.get('srcaddr'),r.get('dstaddr')) for r in self.n.vendor.get('fortios_policies',[])):raise ValueError('Objet adresse utilisé par une politique.')
    del objects[name]
   else:raise ValueError('delete non implémenté dans ce contexte.')
   self.touch();return ''
  if words[0]=='move' and len(words)==4 and self.context=='config firewall policy' and self.entry is None:
   self.checkpoint();number,anchor=int(words[1]),int(words[3])
   order=[r['id'] for r in ordered_rules(self.n)]
   if words[2] not in ('before','after') or number==anchor or number not in order or anchor not in order:raise ValueError('move : deux IDs existants distincts et before/after requis.')
   order.remove(number);order.insert(order.index(anchor)+(words[2]=='after'),number)
   self.n.vendor['fortios_policy_order']=order;self.touch();return ''
  if words[0]=='unset' and len(words)==2 and self.entry is not None:
   key=words[1]
   if self.context=='config firewall policy' and key in ('name','comments'):self.draft.pop(key,None);return ''
   if self.context=='config system interface' and key=='alias':self.draft['alias']='';return ''
   raise ValueError('unset non implémenté pour cette propriété.')
  if words[0]=='edit' and len(words)==2 and self.context!='config system global':
   if self.entry is not None:raise ValueError('Terminer avec next.')
   entry=words[1]
   if self.context.endswith('policy'):
    entry=int(entry)
    if entry==0:entry=next((i for i in range(1,65536) if all(r['id']!=i for r in self.n.firewall_rules)),0)
    if not 1<=entry<=65535:raise ValueError('ID 1..65535 attendu.')
    self.draft=copy.deepcopy(next((r for r in self.n.vendor.get('fortios_policies',[]) if r['id']==entry),{}));self.draft.pop('id',None)
   elif self.context=='config firewall address':
    if not entry or '\n' in entry or '\r' in entry or len(entry)>255:raise ValueError('Nom d’objet non vide, une ligne, 255 caractères maximum dans le lab.')
    if entry=='all':raise ValueError('Objet intégré all réservé dans ce sous-ensemble.')
    stored=self.n.vendor.get('fortios_addresses',{}).get(entry);self.draft={'subnet':stored} if stored else {}
   else:self.draft={}
   if self.context=='config system interface' and entry not in ('port1','port2'):raise ValueError('Interfaces disponibles : port1 et port2.')
   self.entry=entry;return ''
  if line=='next':self.finish_fortios_entry();self.entry=None;self.draft={};return ''
  if words[0]=='set' and len(words)==3:
   key,value=words[1:]
   if self.context=='config system global' and key=='hostname':
    value=hostname(value);self.checkpoint();self.n.hostname=value;self.touch();return ''
   if self.entry is None:raise ValueError('Utiliser edit avant set.')
   if self.context=='config system interface':
    if key=='status' and value not in ('up','down'):raise ValueError('status up/down attendu.')
    if key not in ('status','alias'):raise ValueError('Options implémentées : status et alias.')
   elif self.context=='config firewall policy':
    if key not in ('srcintf','dstintf','srcaddr','dstaddr','action','schedule','service','name','comments'):raise ValueError('Option policy non implémentée.')
    if key in ('name','comments') and (len(value)>255 or '\n' in value or '\r' in value):raise ValueError('Texte limité à 255 caractères sans retour à la ligne.')
    if key in ('srcintf','dstintf') and value!='any':raise ValueError('Interfaces directionnelles non modélisées : utiliser any.')
    if key=='schedule' and value!='always':raise ValueError('Seul always est implémenté.')
    if key=='action' and value not in ('accept','deny'):raise ValueError('Action accept/deny attendue.')
    if key=='service' and value.upper() not in SERVICES:raise ValueError('Service non implémenté.')
   else:raise ValueError('Objet adresse : set subnet <IPv4> <masque>.')
   self.draft[key]=value;return ''
  if self.context=='config firewall address' and words[:2]==['set','subnet'] and len(words)==4 and self.entry is not None:
   self.draft['subnet']=str(IPv4Network(words[2]+'/'+words[3],strict=False));return ''
  raise ValueError('Syntaxe non implémentée dans ce contexte FortiOS.')
 def finish_fortios_entry(self):
  if self.entry is None:raise ValueError('Aucune entrée edit active.')
  self.checkpoint()
  if self.context=='config system interface':
   p=list(self.n.ports.values())[int(str(self.entry)[4:])-1]
   if 'status' in self.draft:p.shutdown=self.draft['status']=='down'
   if 'alias' in self.draft:p.description=self.draft['alias']
  elif self.context=='config firewall address':
   if 'subnet' not in self.draft:raise ValueError('Adresse incomplète : subnet requis.')
   objects={**self.n.vendor.get('fortios_addresses',{}),self.entry:self.draft['subnet']}
   ids={r['id'] for r in self.n.firewall_rules}
   updates={r['id']:self.rule(r['id'],r,objects) for r in self.n.vendor.get('fortios_policies',[]) if r['id'] in ids and self.entry in (r.get('srcaddr'),r.get('dstaddr'))}
   self.n.vendor['fortios_addresses']=objects
   self.n.firewall_rules=[updates.get(r['id'],r) for r in self.n.firewall_rules]
  elif self.context=='config firewall policy':
   rule=self.rule(self.entry,self.draft)
   order=[r['id'] for r in ordered_rules(self.n)]
   if self.entry not in order:order.append(self.entry)
   self.n.firewall_rules=[r for r in self.n.firewall_rules if r['id']!=self.entry]+[rule]
   self.n.vendor['fortios_policy_order']=order
   policies=self.n.vendor.setdefault('fortios_policies',[])
   self.n.vendor['fortios_policies']=[r for r in policies if r['id']!=self.entry]+[{'id':self.entry,**self.draft}]
  self.touch()
 def panos(self,line):
  w=shlex.split(line)
  if line=='show system info':return 'hostname: '+(self.n.hostname or self.node)+'\ntransparent LAN model · no PAN-OS firmware'
  if line=='show config running':return json.dumps({'hostname':self.n.hostname,'rules':self.n.firewall_rules},indent=2)
  if line=='configure' and self.mode=='user':
   if self.draft is None:self.reload_panos()
   self.mode='config';return 'Entering configuration mode'
  if self.mode!='config':raise ValueError('Commande opérationnelle PAN-OS non implémentée. Utiliser configure.')
  if line=='exit':self.mode='user';return ''
  if line=='revert config':
   self.reload_panos();return 'Candidate reloaded.'
  if line=='show':return json.dumps(self.draft,indent=2)
  if w[:4]==['set','deviceconfig','system','hostname'] and len(w)==5:self.draft['hostname']=hostname(w[4]);return ''
  if w[:4]==['delete','rulebase','security','rules'] and len(w)==5:
   if w[4] not in self.draft['rules']:raise ValueError('Règle candidate absente.')
   del self.draft['rules'][w[4]];return ''
  if w[:4]==['set','rulebase','security','rules'] and len(w)>=7:
   if (len(w)-5)%2:raise ValueError('Paires propriété/valeur attendues, une valeur par propriété.')
   pairs={};allowed={'from','to','source','destination','application','service','action'}
   for i in range(5,len(w),2):
    key,value=w[i:i+2]
    if key not in allowed or key in pairs:raise ValueError('Propriété non implémentée ou dupliquée : '+key)
    if key in ('from','to','application') and value!='any':raise ValueError('Sous-ensemble transparent : from/to/application any uniquement.')
    if key=='action' and value not in ('allow','deny'):raise ValueError('Action allow/deny attendue.')
    if key=='service' and value not in ('any','service-http','service-https'):raise ValueError('Services : any, service-http, service-https.')
    if key in ('source','destination') and value!='any':value=str(IPv4Network(value,strict=False))
    pairs[key]=value
   self.draft['rules'].setdefault(w[4],{}).update(pairs);return ''
  if line=='commit':
   self.checkpoint();rules=copy.deepcopy(self.preserved);existing={}
   used={r['id'] for r in rules}|set(self.ruleids.values())
   for name in self.draft['rules']:
    number=self.ruleids.get(name)
    if number is None:
     number=next((i for i in range(1,65536) if i not in used),None)
     if number is None:raise ValueError('Aucun ID de règle disponible.')
     used.add(number)
    existing[name]=number
   for name,r in self.draft['rules'].items():
    if set(r)!={'from','to','source','destination','application','service','action'}:raise ValueError('Règle incomplète : '+name)
    service=r['service'];proto,port=('any',0) if service=='any' else ('tcp',80 if service=='service-http' else 443)
    rules.append(firewall_rule(existing[name],r['action'],r['source'],r['destination'],proto,port))
   self.n.hostname=self.draft['hostname'];self.n.firewall_rules=rules;self.n.vendor['panos_rules']=copy.deepcopy(self.draft['rules']);self.n.vendor['panos_ids']=existing;self.touch();self.reload_panos();return 'Commit complete (simulation).'
  raise ValueError('Syntaxe PAN-OS non implémentée. Utiliser help.')
 def reload_panos(self):
  self.base=fingerprint(self.n);self.ruleids={};self.preserved=[];native={}
  mapping=self.n.vendor.get('panos_ids',{})
  names={number:name for name,number in mapping.items()}
  for r in self.n.firewall_rules:
   name=names.get(r['id']);proto=r.get('protocol','icmp');port=r.get('port',0)
   service='any' if proto=='any' and port==0 else 'service-http' if proto=='tcp' and port==80 else 'service-https' if proto=='tcp' and port==443 else None
   if not name or service is None:self.preserved.append(copy.deepcopy(r));continue
   self.ruleids[name]=r['id'];native[name]={'from':'any','to':'any','source':r['source'],'destination':r['target'],'application':'any','service':service,'action':r['action']}
  self.draft={'hostname':self.n.hostname,'rules':native}
 def routeros(self,line):
  if line=='/system identity print':return 'name: '+(self.n.hostname or self.node)
  if line.startswith('/system identity set name='):
   words=shlex.split(line)
   if len(words)!=4:raise ValueError('Une propriété name attendue.')
   self.n.hostname=hostname(words[3].split('=',1)[1]);self.touch();return ''
  ports={('ether'+str(i+1) if i<24 else 'sfp-sfpplus'+str(i-23)):p for i,p in enumerate(self.n.ports.values())}
  if line in ('/interface print','/interface ethernet print'):
   return 'Flags: X - disabled, R - running\n'+ '\n'.join(f'{i} {"X" if p.shutdown else " "} {name} {p.description}' for i,(name,p) in enumerate(ports.items()))
  w=shlex.split(line)
  if len(w)==4 and w[:2]==['/interface','set'] and '=' in w[3]:
   if w[2] not in ports:raise ValueError('Interface absente.')
   p=ports[w[2]];key,value=w[3].split('=',1)
   if key=='disabled' and value in ('yes','no'):p.shutdown=value=='yes'
   elif key=='comment':p.description=value
   else:raise ValueError('Propriétés implémentées : disabled=yes/no et comment.')
   self.touch();return ''
  raise ValueError('Sous-ensemble RouterOS : identité et état/commentaire des interfaces. Bridge/VLAN non implémenté en syntaxe RouterOS.')

class OSConsole(Session):
 """Expose OS command syntax; keep simulator-only operations out of the OS shell."""
 def execute(self,line):
  self.changed=False;low=line.strip().lower();family=identity(self.n.profile)['console']
  if not low:return ''
  if low in ('help','?'):return self.help()
  accepted=(r'(?:sudo )?(?:ip (?:a|addr|link|route)(?: .*?)?|dhclient(?: .*?)?|resolvectl (?:dns|status)(?: .*?)?)|uname -a|ping (?:-c [1-9][0-9]* )?[^ ]+|nslookup [^ ]+' if family=='linux' else r'ver|ipconfig(?: /(?:all|renew|release))?|route print|netsh interface ipv4 (?:show|set) .+|ping (?:-n [1-9][0-9]* )?[^ ]+|nslookup [^ ]+')
  if not re.fullmatch(accepted,low):return '% Commande '+family+' non implémentée. Utiliser help ; les commandes internes du simulateur ne sont pas des commandes OS.'
  if re.fullmatch(r'ping -[cn] [1-9][0-9]* [^ ]+',low):line='ping '+line.split()[-1]
  return super().execute(line)
 def help(self,prefix=''):
  patterns=self.help_patterns();return '\n'.join(x for x in patterns if x.startswith(prefix.strip()))
 def help_patterns(self):
  if identity(self.n.profile)['console']=='windows':return ['ver','ipconfig','ipconfig /all','ipconfig /renew','ipconfig /release','route print','netsh interface ipv4 show config','netsh interface ipv4 set address name="Ethernet" source=static address=<IPv4> mask=<mask> gateway=<IPv4>','netsh interface ipv4 set dnsservers name="Ethernet" source=static address=<IPv4>','ping <IPv4|nom>','nslookup <nom>']
  return ['uname -a','ip addr show','ip route show','sudo ip addr replace <IPv4/CIDR> dev eth0','sudo ip route replace default via <IPv4> dev eth0','sudo ip link set dev eth0 up','sudo ip link set dev eth0 down','sudo dhclient eth0','sudo resolvectl dns eth0 <IPv4>','ping -c 4 <IPv4|nom>','nslookup <nom>']

def console_session(lab,node):
 dialect=identity(lab.nodes[node].profile)['console']
 if dialect in ('windows','linux'):return OSConsole(lab,node)
 if dialect in ('ios','simulator'):return Session(lab,node)
 return NativeConsole(lab,node)
