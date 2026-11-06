"""Atomic offline topology edits, validated by the native manifest grammar."""
import copy
from .spec import validate


def add_node(spec, *, name, role, rootfs, ports=1, address=''):
    draft=copy.deepcopy(spec)
    if role not in ('host','switch','router'):
        raise ValueError('Création graphique : poste Linux, switch ou routeur OCI.')
    if type(ports) is not int or not 1<=ports<=16:
        raise ValueError('Choisir entre 1 et 16 interfaces.')
    draft['nodes'].append({'name':name,'role':role,'runtime':'oci','rootfs':rootfs,
                           'interfaces':{f'eth{i}':address if i==0 else '' for i in range(ports)}})
    return validate(draft)


def connect(spec, a, b):
    draft=copy.deepcopy(spec)
    draft['links'].append([list(a),list(b)])
    return validate(draft)


def disconnect(spec, a, b):
    draft=copy.deepcopy(spec);endpoints={tuple(a),tuple(b)}
    matches=[link for link in draft['links'] if {tuple(e) for e in link}==endpoints]
    if len(matches)!=1:raise ValueError('Le câble sélectionné ne correspond plus au brouillon.')
    draft['links'].remove(matches[0])
    return validate(draft)


def remove_node(spec, name):
    draft=copy.deepcopy(spec)
    if not any(n['name']==name for n in draft['nodes']):raise ValueError('Équipement absent du brouillon.')
    draft['nodes']=[n for n in draft['nodes'] if n['name']!=name]
    draft['links']=[link for link in draft['links'] if all(e[0]!=name for e in link)]
    return validate(draft)


def free_ports(spec,name):
    node=next((n for n in spec['nodes'] if n['name']==name),None)
    if node is None:raise ValueError('Équipement absent du brouillon.')
    occupied={tuple(e) for link in spec['links'] for e in link}
    return [p for p in node['interfaces'] if (name,p) not in occupied]


def next_port(spec,name):
    node=next((n for n in spec['nodes'] if n['name']==name),None)
    if node is None or node['runtime']!='oci' or len(node['interfaces'])>=64:
        raise ValueError('Ajout de port disponible uniquement pour les nœuds OCI avec moins de 64 interfaces.')
    return next(f'eth{i}' for i in range(100) if f'eth{i}' not in node['interfaces'])


def add_port(spec,name,port):
    draft=copy.deepcopy(spec)
    if next_port(draft,name)!=port:raise ValueError('Le nouveau port ne correspond plus au brouillon.')
    next(n for n in draft['nodes'] if n['name']==name)['interfaces'][port]=''
    return validate(draft)


def configure_node(spec,name,*,new_name,port,address,gateway,enabled):
    """Edit one physical port and basic identity without guessing advanced refs."""
    draft=copy.deepcopy(spec)
    node=next((n for n in draft['nodes'] if n['name']==name),None)
    if node is None or node['runtime']!='oci':raise ValueError('Configuration de base : équipement OCI existant requis.')
    if port not in node['interfaces']:raise ValueError('Choisir une interface physique existante.')
    if not all(isinstance(v,str) for v in (new_name,address,gateway)) or type(enabled) is not bool:
        raise ValueError('Nom, IPv4 et passerelle textuels ; état du port booléen requis.')
    if new_name!=name:
        def referenced(value):
            if isinstance(value,dict):return any(k==name or referenced(v) for k,v in value.items())
            if isinstance(value,list):return any(referenced(v) for v in value)
            return value==name
        if any(n.get('startup') or n.get('command',['/bin/sleep','2147483647'])!=['/bin/sleep','2147483647'] or referenced({k:v for k,v in n.items() if k!='name'}) for n in draft['nodes']):
            raise ValueError('Référence avancée à cet équipement : renommer explicitement dans le JSON.')
        node['name']=new_name
        for link in draft['links']:
            for endpoint in link:
                if endpoint[0]==name:endpoint[0]=new_name
    node['interfaces'][port]=address
    if gateway:node['gateway']=gateway
    else:node.pop('gateway',None)
    shutdown=[p for p in node.get('shutdown',[]) if p!=port]
    if not enabled:shutdown.append(port)
    node['shutdown']=shutdown
    return validate(draft)
