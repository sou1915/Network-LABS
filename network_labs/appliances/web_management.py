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
        if action=='cli':
            # Vendor-workflow pages send the CLI block their form shows; the CLI tab's parser applies it to the draft.
            if set(payload)!={'node','revision','text'} or not isinstance(payload['text'],str):
                raise ValueError('Bloc CLI invalide.')
            if payload['revision']!=revision:
                raise Conflict('Le projet a changé. Actualiser avant d’appliquer.')
            from .vendor_config import apply
            result=apply(window.editing_spec(),name,payload['text'])
            window.config_key=None
            window.commit_edit(result)
            window.choose_node(name)
            window.load_config(force=True)
            window.record_event('web','Bloc CLI constructeur appliqué : '+name)
            return self.dispatch('state',{'node':name})
        if action=='host_ip':return self.host_ip(spec,node,payload,revision)
        if action=='open_cli':
            # The desktop's « Invite de commandes »: the device's terminal window in the application.
            if set(payload)!={'node'}:raise ValueError('Champs invalides.')
            window.open_cli(name)
            return {'opened':name}
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

    def host_ip(self,spec,node,payload,revision):
        """A PC's or server's « Configuration IP » (its desktop page): DHCP, or a static address with its default gateway,
        on one port of the project (applied to the micro-VM at ▶ Démarrer, as the CLI does on a stopped lab)."""
        import ipaddress
        from .vendor_config import _set_routes,routes
        window=self.window
        if set(payload)!={'node','revision','port','mode','address','gateway'}:raise ValueError('Champs de configuration IP invalides.')
        if payload['revision']!=revision:raise Conflict('Le projet a changé. Actualiser avant d’appliquer.')
        if node['role']!='host':raise ValueError('Configuration IP : un poste ou un serveur.')
        if window.pending:raise ValueError('Une opération est déjà en cours : attendre sa fin.')
        port,mode=payload['port'],payload['mode']
        if port not in node['interfaces'] or mode not in ('static','dhcp'):raise ValueError('Port ou mode invalide.')
        if not all(isinstance(payload[k],str) for k in ('address','gateway')):raise ValueError('Adresse et passerelle textuelles.')
        draft=window.editing_spec();target=next(n for n in draft['nodes'] if n['name']==node['name'])
        clients=[p for p in target.get('dhcp_clients',[]) if p!=port]
        others=[r for r in routes(target) if r[0]!='0.0.0.0/0']
        if mode=='dhcp':
            target['interfaces'][port]='';clients.append(port);_set_routes(target,others)  # the lease brings the gateway
        else:
            text,gateway=payload['address'].strip(),payload['gateway'].strip()
            try:
                address=ipaddress.IPv4Interface(text)
                if '/' not in text:raise ValueError
            except ValueError:
                raise ValueError('Adresse IPv4 et masque requis : a.b.c.d/nn (ou masque a.b.c.d).') from None
            if address.network.prefixlen<32 and address.ip in (address.network.network_address,address.network.broadcast_address):
                raise ValueError(f'{address.ip} est l’adresse du réseau ou de diffusion de {address.network}.')
            if gateway:
                try:hop=ipaddress.IPv4Address(gateway)
                except ValueError:raise ValueError('Passerelle : une adresse IPv4.') from None
                if hop not in address.network or hop==address.ip:
                    raise ValueError(f'La passerelle {gateway} doit être une autre adresse du réseau {address.network}.')
            target['interfaces'][port]=str(address)
            _set_routes(target,others+([('0.0.0.0/0',gateway)] if gateway else []))
        if clients:target['dhcp_clients']=clients
        else:target.pop('dhcp_clients',None)
        window.config_key=None;window.commit_edit(draft);window.choose_node(node['name']);window.load_config(force=True)
        window.record_event('web','Configuration IP : '+node['name'])
        return self.dispatch('state',{'node':node['name']})
