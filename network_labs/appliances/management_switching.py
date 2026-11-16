"""Topology-aware, offline switching edits; no invented peers or protocol state."""
import copy


def component(spec,name):
    switches={n['name'] for n in spec['nodes'] if n['role']=='switch'}
    found={name};pending=[name]
    while pending:
        current=pending.pop()
        for a,b in spec['links']:
            for local,remote in ((a,b),(b,a)):
                if local[0]==current and remote[0] in switches and remote[0] not in found:
                    found.add(remote[0]);pending.append(remote[0])
    return sorted(found)


def peers(spec,name):
    nodes={n['name']:n for n in spec['nodes']};result={}
    for a,b in spec['links']:
        for local,remote in ((a,b),(b,a)):
            peer=nodes[remote[0]]
            if local[0]!=name or peer['role']!='switch' or peer['runtime']!='oci' or peer.get('startup') or peer.get('switch_backend')!='linux':continue
            item=result.setdefault(peer['name'],{'links':{},'channels':copy.deepcopy(peer['port_channels'])})
            item['links'][local[1]]=remote[1]
    return result


def set_tree(spec,node,config):
    if set(config)!={'spanning_tree','component'} or type(config['component']) is not bool or not isinstance(config['spanning_tree'],dict):
        raise ValueError('STP exige une politique et un choix de composant booléen.')
    policy=copy.deepcopy(config['spanning_tree'])
    targets=component(spec,node['name']) if config['component'] else [node['name']]
    for current in spec['nodes']:
        if current['name'] not in targets:continue
        if current['runtime']!='oci' or current.get('startup'):raise ValueError('Le composant doit contenir uniquement des switches OCI gérés.')
        if current is node:current['spanning_tree']=copy.deepcopy(policy)
        else:
            existing=copy.deepcopy(current['spanning_tree'])
            for key in ('mode','hello_time','max_age','forward_delay','carrier_recovery'):
                if key in policy:existing[key]=policy[key]
            current['spanning_tree']=existing
        if policy.get('mode')=='off':current['spanning_tree']['ports']={}


def set_aggregation(spec,node,config):
    expected={'peer','name','peer_name','members','mode','peer_mode','min_links','strict','switchport','operation'}
    if set(config)!=expected:raise ValueError('Champs LACP incomplets ou inconnus.')
    peer=next((n for n in spec['nodes'] if n['name']==config['peer']),None)
    if peer is None or peer is node or peer['role']!='switch' or peer['runtime']!='oci' or peer.get('startup') or peer.get('switch_backend')!='linux':raise ValueError('LACP exige un autre switch OCI Linux géré.')
    if config['operation'] not in ('upsert','remove'):raise ValueError('Opération LACP : upsert ou remove.')
    for key in ('name','peer_name'):
        if not isinstance(config[key],str):raise ValueError('Nom de port-channel textuel requis.')
    members=config['members']
    if not isinstance(members,list) or not 2<=len(members)<=8 or any(not isinstance(p,str) for p in members) or len(set(members))!=len(members):raise ValueError('LACP exige 2..8 membres physiques distincts.')
    links=peers(spec,node['name']).get(peer['name'],{}).get('links',{})
    if any(port not in links for port in members):raise ValueError('Chaque membre LACP doit être câblé au même switch pair.')
    remote=[links[p] for p in members]
    if len(set(remote))!=len(remote):raise ValueError('Membres LACP distants dupliqués.')
    if config['strict'] is not None and type(config['strict']) is not bool:raise ValueError('lacp_strict : booléen ou absence explicite.')
    if not isinstance(config['switchport'],dict):raise ValueError('Politique access/trunk du port-channel requise.')
    for current,name,ports,mode in ((node,config['name'],members,config['mode']),(peer,config['peer_name'],remote,config['peer_mode'])):
        channels=current['port_channels'];old=channels.get(name)
        for other,value in channels.items():
            if other!=name and set(value['members'])&set(ports):raise ValueError('Un membre appartient déjà à un autre port-channel.')
        if config['operation']=='remove':
            if old is None or set(old['members'])!=set(ports):raise ValueError('Retrait LACP : sélectionner exactement les membres des deux port-channels existants.')
            policy=copy.deepcopy(current['switchports'].get(name,config['switchport']))
            del channels[name];current['switchports'].pop(name,None);current['spanning_tree']['ports'].pop(name,None)
            for port in ports:current['switchports'][port]=copy.deepcopy(policy)
            continue
        old_policy=copy.deepcopy(current['switchports'].get(name,config['switchport']))
        if old:
            for port in set(old['members'])-set(ports):current['switchports'][port]=copy.deepcopy(old_policy)
        channels[name]={'members':list(ports),'mode':mode,'min_links':config['min_links']}
        if config['strict'] is not None:channels[name]['lacp_strict']=config['strict']
        for port in ports:
            current['switchports'].pop(port,None);current['spanning_tree']['ports'].pop(port,None)
        current['switchports'][name]=copy.deepcopy(config['switchport'])
