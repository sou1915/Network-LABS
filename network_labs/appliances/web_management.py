"""Unprivileged web management of the validated native project draft."""
import hashlib
import json
from ..web_api import Conflict
from . import topology_edit


class NativeDeviceAPI:
    def __init__(self,window):self.window=window

    def dispatch(self,action,payload):
        window=self.window;spec=window.manifest()
        name=payload.get('node')
        node=next((n for n in spec['nodes'] if n['name']==name),None)
        if node is None:raise ValueError('Équipement absent du projet natif.')
        revision=hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if action=='state':
            return {'revision':revision,'project':spec['name'],'node':{k:node[k] for k in ('name','role','runtime','interfaces','gateway','shutdown','routes','subinterfaces','firewall','dhcp_clients') if k in node},'observed':window.states.get(name,{}).get('status','non observé') if window.view_lab==spec['name'] else 'non observé','editable':not window.pending and node['runtime']=='oci'}
        if action!='apply':raise ValueError('Action non disponible dans la gestion web native.')
        if payload.get('revision')!=revision:raise Conflict('Le projet a changé. Actualiser avant d’appliquer.')
        if set(payload)-{'node','revision','name','port','address','gateway','enabled'}:raise ValueError('Champ de configuration inconnu.')
        for key in ('name','port','address','gateway'):
            if not isinstance(payload.get(key),str):raise ValueError('Champ texte requis : '+key)
        if not isinstance(payload.get('enabled'),bool):raise ValueError('État administratif invalide.')
        if node['role']=='switch' and (payload['address']!=node['interfaces'].get(payload['port'],'') or payload['gateway']!=node.get('gateway','')):
            raise ValueError('Switch : configuration IPv4 avancée dans le JSON.')
        if payload['port'] in node.get('dhcp_clients',[]) and payload['address']!=node['interfaces'].get(payload['port'],''):
            raise ValueError('Interface gérée par DHCP : adresse en lecture seule.')
        current=window.editing_spec()
        result=topology_edit.configure_node(current,name,new_name=payload['name'],port=payload['port'],address=payload['address'],gateway=payload['gateway'],enabled=payload['enabled'])
        if name!=payload['name'] and name in window.positions:window.positions[payload['name']]=window.positions.pop(name)
        window.config_key=None;window.commit_edit(result);window.choose_node(payload['name']);window.load_config(force=True)
        window.record_event('web','Brouillon modifié : '+payload['name'])
        return self.dispatch('state',{'node':payload['name']})
