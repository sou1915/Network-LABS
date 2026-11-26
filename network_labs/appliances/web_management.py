"""Unprivileged web management of the validated native project draft."""
from ..web_api import Conflict
from . import topology_edit
from .web_observations import revision as draft_revision,snapshot
from .management_switching import component,peers
from .management_options import PUBLIC_FIELDS,sections,configure_section
from .device_view import summary as device_summary
from .spec import validate


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
                    'switch_backend','services','resolvers',*PUBLIC_FIELDS)
            switch=node['role']=='switch'
            observed=window.states.get(name,{}).get('status','non observé') if window.view_lab==spec['name'] else 'non observé'
            observing=bool(window.pending and (window.pending.get('request') or {}).get('action')=='show')
            return {'inspection':snapshot(window,spec,name),'revision':revision,'project':spec['name'],
                    'equipment':[{'name':n['name'],'role':n['role']} for n in spec['nodes']],
                    'node':{k:node[k] for k in fields if k in node},'observed':observed,
                    'switch_component':component(spec,name) if switch else [],'aggregation_peers':peers(spec,name) if switch else {},
                    'sections':sections(node),'section_editable':not window.pending,
                    'editable':not window.pending and node['runtime']=='oci','device':device_summary(spec,node),
                    'live':self.live(spec,node),'observing':observing,
                    'config_text':running_config(spec,node)}  # the product pages show it as the device's configuration
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
        if action=='services':return self.services(spec,node,payload,revision)
        if action=='browse':return self.browse(spec,node,payload)
        if action=='syslog':return self.syslog(spec,node)
        if action=='host_command':return self.host_command(spec,node,payload)
        if action=='tftp':return self.tftp(spec,node,payload)
        if action=='route':return self.route(node,payload,revision)
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

    def route(self,node,payload,revision):
        """One static route added, changed or removed (empty gateway) from a product page whose brand has no command set in
        the laboratory (Sophos, SonicWall, WatchGuard, Check Point, pfSense, EdgeOS…); checked like every other change."""
        import ipaddress
        from .vendor_config import _delete_route,_network,_upsert_route
        window=self.window
        if set(payload)!={'node','revision','network','gateway'}:raise ValueError('Champs de route invalides.')
        if payload['revision']!=revision:raise Conflict('Le projet a changé. Actualiser avant d’appliquer.')
        if window.pending:raise ValueError('Une opération est déjà en cours : attendre sa fin.')
        if not all(isinstance(payload[k],str) for k in ('network','gateway')):raise ValueError('Réseau et passerelle textuels.')
        network=_network(payload['network'].strip())
        draft=window.editing_spec()
        target=next(n for n in draft['nodes'] if n['name']==node['name'])
        if target['role']=='switch':raise ValueError('Un switch du laboratoire ne route pas.')
        if payload['gateway'].strip():
            _upsert_route(target,network,str(ipaddress.IPv4Address(payload['gateway'].strip())))
        else:
            _delete_route(target,network)
        window.config_key=None
        window.commit_edit(validate(draft))
        window.choose_node(node['name'])
        window.load_config(force=True)
        window.record_event('web',f"Route {network} {'via '+payload['gateway'] if payload['gateway'] else 'supprimée'} : {node['name']}")
        return self.dispatch('state',{'node':node['name']})

    def host_ip(self,spec,node,payload,revision):
        """A PC's or server's « Configuration IP » (its desktop page): DHCP, or a static address with its default gateway,
        on one port of the project (applied to the micro-VM at ▶ Démarrer, as the CLI does on a stopped lab)."""
        import ipaddress
        from .vendor_config import _set_routes,routes
        window=self.window
        if set(payload)-{'dns'}!={'node','revision','port','mode','address','gateway'}:raise ValueError('Champs de configuration IP invalides.')
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
        if 'dns' in payload and target['runtime']=='firecracker':  # the PC's DNS server (nslookup, ping NAME, the browser)
            if not isinstance(payload['dns'],str):raise ValueError('Serveur DNS : une adresse IPv4.')
            dns=payload['dns'].strip()
            if dns:
                try:dns=str(ipaddress.IPv4Address(dns))
                except ValueError:raise ValueError('Serveur DNS : une adresse IPv4.') from None
            target['resolvers']=[dns] if dns else []
        draft=validate(draft)
        running=window.view_lab==spec['name'] and window.states.get(node['name'],{}).get('status')=='running'
        live=self.host_ip_live(spec['name'],node,target,port,mode) if running else None
        window.config_key=None;window.commit_edit(draft);window.choose_node(node['name']);window.load_config(force=True)
        window.record_event('web','Configuration IP : '+node['name']+('' if live is None else ' · en direct : '+live))
        return dict(self.dispatch('state',{'node':node['name']}),ip_live=live)  # None: the lab is not running

    def services(self,spec,node,payload,revision):
        """A server's services (Packet Tracer's « Services » tab: HTTP, DNS, NTP, SYSLOG) set in the project; the lab running,
        ⚡ Appliquer au lab en marche (or a restart) brings them to the server."""
        window=self.window
        if set(payload)!={'node','revision','services'}:raise ValueError('Champs de services invalides.')
        if payload['revision']!=revision:raise Conflict('Le projet a changé. Actualiser avant d’appliquer.')
        if window.pending:raise ValueError('Une opération est déjà en cours : attendre sa fin.')
        if node['role']!='host' or node['runtime']!='firecracker':raise ValueError('Services : un serveur micro-VM.')
        draft=window.editing_spec();target=next(n for n in draft['nodes'] if n['name']==node['name'])
        target['services']=payload['services']
        draft=validate(draft)
        window.config_key=None;window.commit_edit(draft);window.choose_node(node['name']);window.load_config(force=True)
        window.record_event('web','Services du serveur : '+node['name'])
        return self.dispatch('state',{'node':node['name']})

    def browse(self,spec,node,payload):
        """The PC's web browser: an HTTP GET from the device (curl -i), through the lab's real network when it runs."""
        import re
        if set(payload)!={'node','url'} or not isinstance(payload['url'],str):raise ValueError('Adresse invalide.')
        if node['role']!='host' or node['runtime']!='firecracker':raise ValueError('Navigateur : un poste ou un serveur micro-VM.')
        url=payload['url'].strip()
        if not re.fullmatch(r'(?:http://)?[A-Za-z0-9_.-]{1,90}(?::\d{1,5})?(?:/[A-Za-z0-9/._-]{0,99})?',url):
            raise ValueError('Adresse : http://NOM ou ADRESSE[/page.html].')
        text=_host_line(self.window,spec,node,'curl -i '+url)
        if not text.startswith('HTTP/'):return {'url':url,'error':text}
        head,_,body=text.partition('\r\n\r\n')
        status=head.splitlines()[0].split(None,2)
        return {'url':url,'status':int(status[1]) if len(status)>1 and status[1].isdigit() else None,'reason':status[2] if len(status)>2 else '',
                'body':body}

    def host_command(self,spec,node,payload):
        """A diagnostic typed in a PC's or a server's command prompt or terminal on its page (ping, tracert, nslookup, curl, arp;
        on Linux also ip addr / route / neigh, ifconfig, hostname, wget -qO-): run on the device as its terminal does, the running
        guest or the project. Read-only: nothing else is accepted (no « ip addr add », no « hostname NAME »)."""
        import re
        if set(payload)!={'node','line'} or not isinstance(payload['line'],str):raise ValueError('Commande invalide.')
        if node['role']!='host' or node['runtime']!='firecracker':raise ValueError('Invite de commandes : un poste ou un serveur micro-VM.')
        line=' '.join(payload['line'].split())
        word=r'[A-Za-z0-9_./:\-]+'
        shown=(rf'(?:ping|tracert|traceroute|nslookup|curl|arp|logread)(?: {word}){{0,4}}'
               r'|ip(?: -[46])? (?:a|addr|address|r|route|n|neigh|neighbor|l|link)(?: show)?(?: dev [a-z0-9.]+)?'
               rf'|ifconfig(?: [a-z0-9.]+)?|hostname|wget -qO- {word}')
        if len(line)>120 or not re.fullmatch(rf'(?i)(?:{shown})',line):
            raise ValueError('Commande non disponible ici.')
        return {'reply':_host_line(self.window,spec,node,line)}

    def tftp(self,spec,node,payload):
        """A server's TFTP files (Services › TFTP): the running guest's (what routers copied there) or the project's; with
        a name, that file's text."""
        import re
        if set(payload)-{'name'}!={'node'}:raise ValueError('Champs TFTP invalides.')
        if node['role']!='host' or node['runtime']!='firecracker':raise ValueError('TFTP : un serveur micro-VM.')
        running=self.window.view_lab==spec['name'] and self.window.states.get(node['name'],{}).get('status')=='running'
        if 'name' in payload:
            name=payload['name']
            if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}',name):raise ValueError('Nom de fichier invalide.')
            if not running:
                from .guest_services import tftp_files
                files=tftp_files(node)
                if name not in files:raise ValueError('Fichier absent.')
                return {'name':name,'text':files[name]}
            return {'name':name,'text':_host_line(self.window,spec,node,'cat /tftpboot/'+name)}
        rows=[]
        for line in _host_line(self.window,spec,node,'ls -l /tftpboot').splitlines():
            parts=line.split()
            if len(parts)>=6 and parts[-2].isdigit():rows.append({'name':parts[-1],'size':int(parts[-2])})
        return {'running':running,'files':rows}

    def syslog(self,spec,node):
        """The messages a syslog server has collected (its guest), for the Services › SYSLOG table."""
        if node['role']!='host' or node['runtime']!='firecracker':raise ValueError('Syslog : un serveur micro-VM.')
        running=self.window.view_lab==spec['name'] and self.window.states.get(node['name'],{}).get('status')=='running'
        if not running:return {'running':False,'messages':[]}
        rows=[]
        for line in _host_line(self.window,spec,node,'logread').splitlines():  # « Nov 26 10:13:24 SOURCE MESSAGE »
            parts=line.split(' ',4)
            if len(parts)==5 and parts[2].count(':')==2:rows.append({'time':' '.join(parts[:3]),'source':parts[3],'message':parts[4]})
        return {'running':True,'messages':rows}

    def host_ip_live(self,lab,before,after,port,mode):
        """The same change on the running PC, typed in its console as a user would (ip addr / ip route): 'appliqué', or why
        not. DHCP waits for the next start (the lease comes at boot)."""
        import secrets
        from . import console_server
        if mode=='dhcp':
            return 'DHCP au prochain démarrage du lab'
        old,new=before['interfaces'].get(port,''),after['interfaces'][port]
        old_gateway,new_gateway=before.get('gateway',''),after.get('gateway','')
        lines=[]
        if old_gateway and old_gateway!=new_gateway:lines.append(f'ip route del default via {old_gateway}')
        if old and old!=new:lines.append(f'ip addr del {old} dev {port}')
        if new and new!=old:lines.append(f'ip addr add {new} dev {port}')
        if new_gateway and new_gateway!=old_gateway:lines.append(f'ip route add default via {new_gateway}')
        if not lines:return 'rien à changer'
        session=secrets.token_hex(8)
        try:
            console_server.request(lab,{'op':'open','session':session,'node':before['name']},timeout=6)
            for line in lines:
                reply=console_server.request(lab,{'op':'line','session':session,'node':before['name'],'text':line},timeout=6)
                if not reply.get('ok') or str(reply.get('reply','')).startswith('%'):
                    return f'« {line} » refusé : '+str(reply.get('reply') or reply.get('error','')).lstrip('% ')
            console_server.request(lab,{'op':'close','session':session,'node':before['name']},timeout=6)
        except (OSError,ValueError) as error:
            return f'consoles du lab injoignables ({error})'
        return 'appliqué'


def _host_line(window,spec,node,line):
    """One line typed in a PC's or a server's shell, as its terminal does: in the running guest (the lab's console server,
    root), or on the project while the lab is stopped."""
    import secrets
    running=window.view_lab==spec['name'] and window.states.get(node['name'],{}).get('status')=='running'
    if running:
        from . import console_server
        session=secrets.token_hex(8)
        console_server.request(spec['name'],{'op':'open','session':session,'node':node['name']},timeout=6)
        try:
            reply=console_server.request(spec['name'],{'op':'line','session':session,'node':node['name'],'text':line},timeout=12)
        finally:
            console_server.request(spec['name'],{'op':'close','session':session,'node':node['name']},timeout=6)
        if not reply.get('ok'):raise ValueError(str(reply.get('error') or reply.get('reply') or 'console du lab injoignable'))
        return str(reply.get('reply',''))
    from .draft_lab import DraftLab
    from .guest_console import Console
    def refuse(_):raise ValueError('Lecture seule.')
    draft=DraftLab(lambda:window.editing_spec(),refuse)
    return Console(spec['name'],node['name'],lambda _:draft).line(line)


def running_config(spec,node):
    """The device's configuration in its own syntax (IOS, Junos, RouterOS…), as its product page shows it; None when the
    brand has no command set in the laboratory."""
    from .vendor_config import dialect,render
    try:
        return render(spec,node['name']) if dialect(node) else None
    except (ValueError,KeyError,TypeError):
        return None
