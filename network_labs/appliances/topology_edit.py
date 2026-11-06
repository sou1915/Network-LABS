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
