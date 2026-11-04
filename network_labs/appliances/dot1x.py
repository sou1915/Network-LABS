"""One explicit finite wired EAP-MD5 authenticator and fail-closed kernel gate."""
import copy
import ipaddress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
from .spec import integer, keys, namespace
from .runtime import RuntimeFailure, process_identity
from .firewall import fingerprint

TABLE = 'network_labs_dot1x'
PROCESSES = {}


def validate_node(node):
    policy = node.get('dot1x')
    if policy is None: return
    keys(policy, ('port','peer','server','svi','users','seconds','reauthentications'), '802.1X')
    if (node['runtime'] != 'oci' or node['role'] != 'switch' or node.get('switch_backend','linux') != 'linux'
            or len(node['interfaces']) != 2 or node['vlans'] != [1] or node.get('startup') or node['shutdown']
            or node['port_channels'] or node['subinterfaces'] or node.get('ipv6') or node.get('forwarding')
            or node.get('spanning_tree',{}).get('mode','off')!='off' or any(p['mode']!='access' or p['vlan']!=1 for p in node['switchports'].values())
            or any(node.get(k) for k in ('ra_guard','port_security','dhcp_snooping','arp_inspection','ip_source_guard','multicast','management','ospf','ospfv3'))):
        raise ValueError('Initial 802.1X requires a two-port Linux access switch in VLAN 1, without other security/routing services.')
    if not isinstance(policy.get('port'),str) or policy['port'] not in node['interfaces']: raise ValueError('802.1X needs one declared physical controlled port.')
    if policy.get('svi') != 'vlan1' or set(node['svis']) != {'vlan1'} or not node['svis']['vlan1']['address']:
        raise ValueError('802.1X needs exactly one numbered VLAN 1 NAS SVI.')
    from .spec import identifier
    identifier(policy.get('peer'))
    if not isinstance(policy.get('server'),str): raise ValueError('802.1X backend must be remote IPv4.')
    address=ipaddress.IPv4Address(policy['server'])
    if address.is_multicast or address.is_unspecified or address.is_loopback or address.is_reserved:
        raise ValueError('802.1X backend must be remote unicast IPv4.')
    users=policy.get('users')
    import re
    if not isinstance(users,list) or not 1<=len(users)<=16 or any(not isinstance(u,str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}',u) for u in users) or len(set(users))!=len(users):
        raise ValueError('802.1X needs 1..16 distinct explicitly allowed identities.')
    policy['users']=sorted(users);integer(policy.setdefault('seconds',5),1,30,'802.1X authorization seconds')
    if 'reauthentications' in policy:integer(policy['reauthentications'],0,3,'802.1X finite reauthentications')


def backend(spec,node):
    policy=node['dot1x'];nas=str(ipaddress.IPv4Interface(node['svis'][policy['svi']]['address']).ip)
    candidates=[n for n in spec['nodes'] if n.get('radius_server') and str(ipaddress.IPv4Interface(n['interfaces']['eth0']).ip)==policy['server']]
    if len(candidates)!=1 or not candidates[0]['radius_server'].get('eap_md5'):raise ValueError('802.1X needs a separate managed EAP-MD5 backend.')
    clients=[c for c in candidates[0]['radius_server']['clients'] if c['address']==nas]
    if len(clients)!=1 or nas==policy['server']:raise ValueError('802.1X requires the declared NAS SVI client binding.')
    return nas,policy['server'],clients[0]['secret']


def validate_lab(spec):
    switches=[n for n in spec['nodes'] if n.get('dot1x')]
    if not switches:return
    if len(switches)!=1 or len(spec['nodes'])!=3:raise ValueError('Initial 802.1X reference requires exactly NAS, direct peer and backend.')
    node=switches[0];policy=node['dot1x'];backend(spec,node)
    peer=next((n for n in spec['nodes'] if n['name']==policy['peer']),None)
    if peer is None or peer.get('radius_server') or peer['runtime']!='oci' or peer['role']!='host' or set(peer['interfaces'])!={'eth0'} or not peer.get('interface_macs',{}).get('eth0'):
        raise ValueError('802.1X requires a single-interface peer with an explicit physical MAC.')
    if not any(set(map(tuple,link))=={(node['name'],policy['port']),(peer['name'],'eth0')} for link in spec['links']):
        raise ValueError('802.1X peer must be directly paired to the controlled port.')
    server=next(n for n in spec['nodes'] if n.get('radius_server'))
    uplink=next(p for p in node['interfaces'] if p!=policy['port'])
    if not any(set(map(tuple,link))=={(node['name'],uplink),(server['name'],'eth0')} for link in spec['links']):
        raise ValueError('802.1X backend must be directly paired to the uncontrolled uplink.')
    network=ipaddress.IPv4Interface(node['svis']['vlan1']['address']).network
    for n in spec['nodes']:
        if n.get('ipv6') or n.get('gateway') or n['routes'] or n['forwarding'] or n.get('management') or n.get('radius_access'):
            raise ValueError('Initial 802.1X excludes dual stack, routing and management composition.')
        if n is not node and (not n['interfaces']['eth0'] or ipaddress.IPv4Interface(n['interfaces']['eth0']).ip not in network):
            raise ValueError('Initial 802.1X uses one connected IPv4 subnet.')


def render(node,mac):
    port=json.dumps(node['dot1x']['port']);seconds=node['dot1x']['seconds']
    return f'''table bridge {TABLE} {{
set admitted {{ type ifname; flags timeout; timeout {seconds}s; size 1; }}
chain ingress {{
 type filter hook prerouting priority -340; policy accept;
 iifname {port} ether type 0x888e accept
 iifname {port} ether saddr != {mac} counter drop
 iifname {port} iifname @admitted return
 iifname {port} counter drop
}}
chain egress {{
 type filter hook postrouting priority -340; policy accept;
 oifname {port} ether type 0x888e accept
 oifname {port} oifname @admitted return
 oifname {port} counter drop
}}
}}
'''


def gate_snapshot(value,port,seconds):
    data=copy.deepcopy(value);admitted=False
    for row in data['nftables']:
        entry=row.get('set',{})
        if entry.get('name')=='admitted' and entry.get('table')==TABLE:
            elements=entry.pop('elem',[])
            if len(elements)>1:raise ValueError('Unexpected admission entries.')
            for element in elements:
                item=element.get('elem',{}) if isinstance(element,dict) else {}
                if item.get('val')!=port or type(item.get('expires')) is not int or not 0<=item['expires']<=seconds*1000 or item.get('timeout',seconds*1000)>seconds*1000:
                    raise ValueError('Unbounded or foreign admission.')
                admitted=True
    return fingerprint(data),admitted


def apply(manager,index,node):
    peer=next(n for n in manager.state['spec']['nodes'] if n['name']==node['dot1x']['peer'])
    manager.ns(index,'nft','-f','-',input_text=render(node,peer['interface_macs']['eth0']))
    data=json.loads(manager.ns(index,'nft','-j','list','table','bridge',TABLE).stdout)
    pin,admitted=gate_snapshot(data,node['dot1x']['port'],node['dot1x']['seconds'])
    if admitted:raise RuntimeFailure('802.1X gate unexpectedly starts admitted.')
    manager.state.setdefault('dot1x_fingerprints',{})[node['name']]=pin;manager.save()


def observe(manager,index,node):
    result={'configuration_verified':False,'admitted':None}
    try:
        data=json.loads(manager.ns(index,'nft','-j','list','table','bridge',TABLE).stdout)
        pin,admitted=gate_snapshot(data,node['dot1x']['port'],node['dot1x']['seconds'])
        result.update(configuration_verified=pin==manager.read().get('dot1x_fingerprints',{}).get(node['name']),admitted=admitted)
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired):pass
    return {**result,'port':node['dot1x']['port'],'maximum_seconds':node['dot1x']['seconds'],
            'reauthentications':node['dot1x'].get('reauthentications',0),
            'scope':'Finite explicit EAP-MD5 wired admission with optional bounded closed-port reauthentication; no persistent service, TLS, dynamic VLAN or multi-client support.'}


def stop(manager):
    from .snooping import alive
    for name,record in list(manager.state.get('dot1x_workers',{}).items()):
        if alive(record):
            if os.getpgid(record['pid'])!=record['pid']:raise RuntimeFailure('802.1X worker group differs; cleanup retained.')
            os.killpg(record['pid'],signal.SIGTERM)
            until=time.monotonic()+3
            while alive(record) and time.monotonic()<until:time.sleep(.02)
            if alive(record):
                if os.getpgid(record['pid'])!=record['pid']:raise RuntimeFailure('802.1X worker group differs; cleanup retained.')
                os.killpg(record['pid'],signal.SIGKILL)
                until=time.monotonic()+2
                while alive(record) and time.monotonic()<until:time.sleep(.02)
                if alive(record):raise RuntimeFailure('802.1X worker death unconfirmed; cleanup retained.')
        child=PROCESSES.pop(record['pid'],None)
        if child:child.wait(timeout=2)
        manager.state['dot1x_workers'].pop(name,None);manager.save()


def authenticate(manager,name,*,timeout=5):
    integer(timeout,1,5,'802.1X exchange deadline')
    process=None;token=uuid.uuid4().hex
    with manager.locked():
        manager.state=None
        state=manager.read()
        if state['phase']!='running' or 'pending_spec' in state or 'pending_node' in state or state.get('dot1x_workers'):raise RuntimeFailure('802.1X requires a stable running lab without an existing session.')
        index,node=next(((i,n) for i,n in enumerate(state['spec']['nodes']) if n['name']==name),(None,None))
        if node is None or not node.get('dot1x'):raise ValueError('Node has no explicit controlled port.')
        if not observe(manager,index,node)['configuration_verified']:raise RuntimeFailure('802.1X gate differs; recreate the lab.')
        nas,server,secret=backend(state['spec'],node);peer=next(n for n in state['spec']['nodes'] if n['name']==node['dot1x']['peer'])
        ns_path=Path('/run/netns')/namespace(state['spec'],index);info=ns_path.stat()
        port=node['dot1x']['port'];link=json.loads(manager.ns(index,'ip','-j','link','show','dev',port).stdout)[0]
        output=manager.directory/(name+'.dot1x-'+token+'.json')
        config=dict(port=port,peer_mac=peer['interface_macs']['eth0'],users=node['dot1x']['users'],seconds=node['dot1x']['seconds'],
                    reauthentications=node['dot1x'].get('reauthentications',0),
                    source=nas,address=server,secret=secret,timeout=timeout,namespace_dev=info.st_dev,namespace_ino=info.st_ino,
                    ifindex=link['ifindex'],fingerprint=state['dot1x_fingerprints'][name],output=str(output),
                    state_file=str(manager.directory/'state.json'),node=name,token=token)
        code='import sys;sys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[2]))+');from network_labs.appliances.dot1x_worker import main;main()'
        process=subprocess.Popen(['ip','netns','exec',str(ns_path.name),sys.executable,'-I','-c',code],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,text=True)
        if process_identity(process.pid) is None:
            process.kill();process.wait();raise RuntimeFailure('802.1X worker identity unavailable.')
        PROCESSES[process.pid]=process
        manager.state.setdefault('dot1x_workers',{})[name]={'pid':process.pid,'starttime':process_identity(process.pid),'token':token}
        manager.save()
        process.stdin.write(json.dumps(config));process.stdin.close()
    try:
        process.wait(timeout=(1+config['reauthentications'])*(timeout+node['dot1x']['seconds'])+8)
        result=json.loads(output.read_text())
        if process.returncode or result.get('phase')!='finished' or result.get('status') not in ('passed','failed','blocked','unknown') or (result.get('status')=='passed' and (not result.get('authenticated') or not result.get('port_closed'))):raise ValueError
        return result
    except (OSError,ValueError,subprocess.TimeoutExpired):return {'status':'unknown','error':'DOT1X_WORKER_UNCONFIRMED'}
    finally:
        if process.poll() is None:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=2)
        PROCESSES.pop(process.pid,None)
        if manager.directory.exists():
            with manager.locked():
                if manager.directory.exists():
                    manager.state=None;state=manager.read();record=state.get('dot1x_workers',{}).get(name,{})
                    if record.get('token')==token:
                        state['dot1x_workers'].pop(name);manager.save()
        output.unlink(missing_ok=True)
