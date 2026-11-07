"""Atomic, allowlisted native management sections; kernel validators stay authoritative."""
import copy
from .spec import validate

SECTIONS={
    'stp':{'label':'Spanning Tree / protections BPDU','roles':('switch',),'fields':('spanning_tree',)},
    'aggregation':{'label':'Agrégation LACP','roles':('switch',),'fields':('port_channels','switchports')},
    'lldp':{'label':'Découverte LLDP','roles':('host','router','switch','firewall'),'fields':('lldp',)},
    'portsecurity':{'label':'Sécurité des ports / MAC','roles':('switch',),'fields':('port_security',)},
    'svis':{'label':'Interfaces VLAN / SVI','roles':('switch',),'fields':('svis',)},
    'subinterfaces':{'label':'Sous-interfaces 802.1Q','roles':('router','firewall'),'fields':('subinterfaces',)},
    'dhcpserver':{'label':'Serveur DHCP','roles':('host','router','firewall'),'fields':('dhcp_server',)},
    'dnsserver':{'label':'Serveur DNS local','roles':('host','router','firewall'),'fields':('dns_server',)},
    'routing':{'label':'Routage IPv4','roles':('host','router','firewall','switch'),'fields':('routes','gateway','forwarding')},
    'firewall':{'label':'Politiques IPv4 & NAT','roles':('firewall',),'fields':('firewall',)},
    'switching':{'label':'VLAN & ports','roles':('switch',),'fields':('vlans','switchports')},
    'ipv6':{'label':'Adressage IPv6','roles':('host','router','firewall','switch'),'fields':('ipv6','ipv6_forwarding','ipv6_routes')},
    'addressing':{'label':'DNS & client DHCP','roles':('host','router','firewall','switch'),'fields':('resolvers','dhcp_clients')},
}
PUBLIC_FIELDS=tuple(dict.fromkeys(field for section in SECTIONS.values() for field in section['fields'] if field!='component'))


def sections(node):
    if node['runtime']!='oci' or node.get('startup'):return []
    return [{'id':key,'label':section['label'],'fields':list(section['fields'])} for key,section in SECTIONS.items() if node['role'] in section['roles'] and not (key=='lldp' and node.get('port_channels')) and not (key=='aggregation' and node.get('switch_backend')!='linux') and not (key=='firewall' and node.get('firewall_ipv6')) and not (key=='ipv6' and node['role']=='firewall' and not node.get('firewall_ipv6'))]


def configure_section(spec,name,section,config):
    draft=copy.deepcopy(spec)
    node=next((n for n in draft['nodes'] if n['name']==name),None)
    if node is None or section not in {item['id'] for item in sections(node)}:
        raise ValueError('Section non disponible pour cet équipement natif.')
    from .management_switching import set_tree,set_aggregation
    if not isinstance(config,dict):raise ValueError('Objet de configuration requis.')
    if section=='stp':
        set_tree(draft,node,config)
        return validate(draft)
    if section=='aggregation':
        set_aggregation(draft,node,config)
        return validate(draft)
    allowed=SECTIONS[section]['fields']
    if not isinstance(config,dict) or set(config)!=set(allowed):
        raise ValueError('La section exige exactement ces champs : '+', '.join(allowed))
    # Preserve all other node settings, node identities and other lab nodes.
    for field,value in config.items():
        if field=='gateway' and value=='':node.pop(field,None)
        else:node[field]=copy.deepcopy(value)
    return validate(draft)
