"""Unprivileged web management of the validated native project draft."""
from ..web_api import Conflict
from . import topology_edit
from .web_observations import revision as draft_revision,snapshot
from .management_switching import component,peers
from .management_options import PUBLIC_FIELDS,sections,configure_section
from .device_view import summary as device_summary


class NativeDeviceAPI:
    def __init__(self,window):self.window=window

    def live(self,spec,node):
        """The last observation of this node in this lab, compared with the draft; None when there is none."""
        held=getattr(self.window,'vendor_observation',None)
        if not held or held['key']!=(spec['name'],node['name']):
            return None
        from .device_view import live
        return dict(live(spec,node,held['data']),time=held['time'])

    def dispatch(self,action,payload):
        window=self.window;spec=window.manifest()
        name=payload.get('node')
        node=next((n for n in spec['nodes'] if n['name']==name),None)
        if node is None:raise ValueError('Équipement absent du projet natif.')
        revision=draft_revision(spec)
        if action=='state':
            fields=('name','role','runtime','interfaces','gateway','shutdown','routes','subinterfaces','firewall','dhcp_clients','svis',
                    'switch_backend',*PUBLIC_FIELDS)
            switch=node['role']=='switch'
            observed=window.states.get(name,{}).get('status','non observé') if window.view_lab==spec['name'] else 'non observé'
            observing=bool(window.pending and (window.pending.get('request') or {}).get('action')=='show')
            return {'inspection':snapshot(window,spec,name),'revision':revision,'project':spec['name'],
                    'equipment':[{'name':n['name'],'role':n['role']} for n in spec['nodes']],
                    'node':{k:node[k] for k in fields if k in node},'observed':observed,
                    'switch_component':component(spec,name) if switch else [],'aggregation_peers':peers(spec,name) if switch else {},
                    'sections':sections(node),'section_editable':not window.pending,
                    'editable':not window.pending and node['runtime']=='oci','device':device_summary(spec,node),
                    'live':self.live(spec,node),'observing':observing}
        if action=='observe':
            # Read the running node (sudo-confirmed in a terminal, like the CLI tab's show commands).
            if window.view_lab!=spec['name'] or window.states.get(name,{}).get('status')!='running':
                raise ValueError('Démarrer le laboratoire et actualiser son état avant le relevé.')
            if window.pending:
                raise ValueError('Une opération est déjà en cours : attendre sa fin.')
            window.choose_node(name)
            window.vendor_pending_command=None
            if not window.launch('show'):
                raise ValueError('Relevé non lancé : voir le journal des événements.')
            return self.dispatch('state',{'node':name})
        if action!='apply':raise ValueError('Action non disponible dans la gestion web native.')
        if payload.get('revision')!=revision:raise Conflict('Le projet a changé. Actualiser avant d’appliquer.')
        if 'section' in payload:
            if set(payload)!={'node','revision','section','config'}:raise ValueError('Champs de section invalides.')
            result=configure_section(window.editing_spec(),name,payload['section'],payload['config'])
            window.config_key=None;window.commit_edit(result);window.choose_node(name);window.load_config(force=True)
            window.record_event('web','Section appliquée : '+payload['section']+' / '+name)
            return self.dispatch('state',{'node':name})
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
