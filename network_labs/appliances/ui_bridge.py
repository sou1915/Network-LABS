"""Typed terminal/sudo handoff. Only the unprivileged client writes GUI results."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from .spec import identifier,load

ACTIONS=('start','status','stop','inspect','verify')
SOURCE=Path(__file__).resolve().parents[2]
BOOTSTRAP='import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("network_labs.appliances.ui_bridge",run_name="__main__")'


def private_json(path,value):
    path=Path(path);fd,temporary=tempfile.mkstemp(prefix='.native-gui-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def public_topology(spec):
    return {'name':spec['name'],'nodes':[{k:node[k] for k in ('name','role','runtime','interfaces')} for node in spec['nodes']],
            'links':spec['links']}


def validate_topology(graph):
    if not isinstance(graph,dict) or set(graph)!={'name','nodes','links'}:raise ValueError('Invalid native topology.')
    identifier(graph['name'])
    if not isinstance(graph['nodes'],list) or not 1<=len(graph['nodes'])<=256:raise ValueError('Invalid topology nodes.')
    nodes={}
    for node in graph['nodes']:
        if not isinstance(node,dict) or set(node)!={'name','role','runtime','interfaces'}:raise ValueError('Invalid topology node.')
        name=identifier(node['name'])
        if name in nodes or node['runtime'] not in ('oci','firecracker') or node['role'] not in ('host','switch','router','firewall'):
            raise ValueError('Invalid topology identity.')
        if not isinstance(node['interfaces'],dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in node['interfaces'].items()):
            raise ValueError('Invalid topology interfaces.')
        nodes[name]=node
    if not isinstance(graph['links'],list) or len(graph['links'])>16384:raise ValueError('Invalid topology links.')
    for link in graph['links']:
        if not isinstance(link,list) or len(link)!=2:raise ValueError('Invalid topology link.')
        for endpoint in link:
            if not isinstance(endpoint,list) or len(endpoint)!=2 or not all(isinstance(x,str) for x in endpoint):raise ValueError('Invalid link endpoint.')
            name,port=endpoint
            if name not in nodes or port not in nodes[name]['interfaces']:raise ValueError('Unknown topology endpoint.')
    return graph


def backend(action,target,node=None,destination=None):
    from .runtime import Manager
    from .radius_server import redact
    if action not in ACTIONS:raise ValueError('Unknown native GUI operation.')
    if action in ('inspect','verify'):identifier(node)
    elif node is not None:raise ValueError('Unexpected node argument.')
    if action=='verify':identifier(destination)
    elif destination is not None:raise ValueError('Unexpected destination argument.')
    spec=load(target) if action=='start' else None
    lab=spec['name'] if spec else identifier(target)
    with Manager(lab).locked() as manager:
        if action=='start':manager.start(spec)
        topology=public_topology(manager.read()['spec'])
        if action=='stop':manager.stop();data={'stopped':lab}
        elif action=='inspect':data=manager.inspect(node)
        elif action=='verify':
            from .verify import verify
            data=verify(manager,node,destination,count=2,bidirectional=True)
        else:data=manager.status()
    return {'ok':True,'action':action,'lab':lab,'topology':topology,'data':redact(data)}


def validate_request(request):
    if not isinstance(request,dict) or set(request)!={'id','owner_uid','action','target','lab','node','destination'}:
        raise ValueError('Invalid GUI request envelope.')
    if not isinstance(request['id'],str) or not re.fullmatch('[0-9a-f]{32}',request['id']):raise ValueError('Invalid request identity.')
    if type(request['owner_uid']) is not int or request['owner_uid']!=os.geteuid():raise ValueError('GUI request owner differs.')
    action=request['action'];identifier(request['lab'])
    if action not in ACTIONS:raise ValueError('Unknown GUI operation.')
    target=request['target']
    if not isinstance(target,str) or '\0' in target or len(target)>4096:raise ValueError('Invalid operation target.')
    if action=='start':
        if not Path(target).is_absolute():raise ValueError('Start requires an absolute manifest snapshot.')
    elif target!=request['lab']:raise ValueError('Operation lab differs.')
    if action in ('inspect','verify'):identifier(request['node'])
    elif request['node'] is not None:raise ValueError('Unexpected node argument.')
    if action=='verify':identifier(request['destination'])
    elif request['destination'] is not None:raise ValueError('Unexpected destination argument.')
    return request


def client_args(request_path):
    return [sys.executable,'-I','-c',BOOTSTRAP,str(SOURCE),'--request',str(request_path)]


def execute_request(request):
    validate_request(request)
    # Authentication keeps the real terminal's stdin/stderr: no password enters
    # a widget, result file, pipe capture, argv or application log.
    auth=subprocess.run(['sudo','-v'])
    if auth.returncode:return {'ok':False,'error':'Authentification sudo annulée ou refusée.'}
    args=['sudo','-n',sys.executable,'-I','-c',BOOTSTRAP,str(SOURCE),'--backend',request['action'],request['target']]
    if request['node'] is not None:args.append(request['node'])
    if request['destination'] is not None:args.append(request['destination'])
    result=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,text=True)
    try:
        if len(result.stdout)>8*1024*1024:raise ValueError('Response budget exceeded.')
        payload=json.loads(result.stdout)
        if not isinstance(payload,dict) or type(payload.get('ok')) is not bool:raise ValueError('Invalid response.')
        if payload['ok'] and (result.returncode or payload.get('action')!=request['action'] or payload.get('lab')!=request['lab']):
            raise ValueError('Response context differs.')
        if payload['ok']:
            validate_topology(payload.get('topology'))
            if payload['topology']['name']!=request['lab'] or not isinstance(payload.get('data'),dict):raise ValueError('Invalid backend data.')
        return payload
    except (ValueError,TypeError):
        return {'ok':False,'uncertain':True,'error':'Résultat backend non confirmé ; actualiser l’état réel.'}


def read_result(path,request):
    import stat
    info=Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>8*1024*1024:
        raise ValueError('Invalid private GUI result.')
    value=json.loads(Path(path).read_text())
    if value.get('id')!=request['id'] or value.get('lab')!=request['lab'] or value.get('action')!=request['action']:
        raise ValueError('Stale or foreign GUI result.')
    if not isinstance(value.get('response'),dict) or type(value['response'].get('ok')) is not bool:raise ValueError('Invalid GUI result.')
    if value['response']['ok'] and (value['response'].get('lab')!=request['lab'] or value['response'].get('action')!=request['action']):
        raise ValueError('Backend response context differs.')
    return value['response']


def main(argv=None):
    argv=sys.argv[1:] if argv is None else argv
    if len(argv) in (3,4,5) and argv[0]=='--backend':
        try:payload=backend(*argv[1:])
        except (OSError,ValueError,TypeError,KeyError,RuntimeError,subprocess.SubprocessError) as error:
            payload={'ok':False,'error':str(error)}
        print(json.dumps(payload,ensure_ascii=False));return 0 if payload['ok'] else 1
    if len(argv)==2 and argv[0]=='--request':
        path=Path(argv[1]);request=validate_request(json.loads(path.read_text()))
        try:response=execute_request(request)
        except (OSError,ValueError,subprocess.SubprocessError) as error:response={'ok':False,'uncertain':True,'error':str(error)}
        try:private_json(path.parent/'result.json',{'id':request['id'],'lab':request['lab'],'action':request['action'],'response':response})
        except OSError:pass  # GUI may have closed; never stop a lab as a side effect.
        print(json.dumps(response,ensure_ascii=False,indent=2))
        if sys.stdin.isatty():
            try:input('Entrée pour fermer…')
            except (EOFError,KeyboardInterrupt):pass
        return 0 if response['ok'] else 1
    raise ValueError('Expected a typed GUI request or backend operation.')


if __name__=='__main__':raise SystemExit(main())
