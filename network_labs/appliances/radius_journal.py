"""Private pre-Start intents and explicit dead-supervisor reconciliation.

Never replays Start, never assumes a missing cgroup is empty, never sends packets.
"""
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from . import runtime,radius_outbox as outbox
from .spec import integer,identifier,namespace
from .radius_session import session_parent

KIND='accounting-sessions'
BOOT=Path('/proc/sys/kernel/random/boot_id')
FIELDS={'version','lab','source','server','username','session_id','policy_sha256','created_at','phase',
        'boot_id','namespace_dev','namespace_ino','container_pid','container_start','supervisor_pid','supervisor_start','cgroup_dev','cgroup_ino'}


def validate(record,manager):
    if not isinstance(record,dict) or set(record)!=FIELDS or type(record['version']) is not int or record['version']!=1 or record['lab']!=manager.name:
        raise ValueError('Invalid accounting session journal schema.')
    identifier(record['source'])
    if record['phase'] not in ('intent','empty'):raise ValueError('Invalid accounting journal phase.')
    for key in ('created_at','namespace_dev','namespace_ino','container_pid','supervisor_pid','cgroup_dev','cgroup_ino'):
        integer(record[key],0,2**63-1,key)
    if record['container_pid']<2 or record['supervisor_pid']<2:raise ValueError('Invalid journal process identity.')
    for key,pattern in (('username',r'[A-Za-z0-9_.@-]{1,64}'),('session_id',r'aaa-[0-9a-f]{32}'),('policy_sha256',r'[0-9a-f]{64}'),
                        ('container_start',r'[0-9]{1,32}'),('supervisor_start',r'[0-9]{1,32}'),('boot_id',r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')):
        if not isinstance(record[key],str) or not re.fullmatch(pattern,record[key]):raise ValueError('Invalid accounting journal identity.')
    import ipaddress
    if not isinstance(record['server'],str) or str(ipaddress.IPv4Address(record['server']))!=record['server']:raise ValueError('Invalid journal backend.')
    return record


def directory(manager,create=False):return outbox.folder(manager,create,kind=KIND)


def read(path,manager):return outbox.read(path,manager,validator=validate)


@outbox.serialized
def write(manager,record,previous=None):
    validate(record,manager);root=directory(manager,True);target=root/(record['session_id']+'.json')
    entries=outbox.paths(root)
    if previous is None:
        if target in entries:raise ValueError('Accounting session intent already exists.')
        if len(entries)>=outbox.MAX_ENTRIES:raise runtime.RuntimeFailure('Accounting session journal is full.')
    elif read(target,manager)!=previous:raise ValueError('Accounting journal changed before checkpoint.')
    temporary=None
    try:
        payload=(json.dumps(record,sort_keys=True,separators=(',',':'))+'\n').encode()
        if len(payload)>outbox.MAX_BYTES:raise ValueError('Accounting journal exceeds size budget.')
        with tempfile.NamedTemporaryFile(dir=root,prefix='.pending-',delete=False) as file:
            temporary=Path(file.name);file.write(payload);file.flush();os.fsync(file.fileno())
        if previous is None:
            os.link(temporary,target,follow_symlinks=False);temporary.unlink()
        else:os.replace(temporary,target)
        temporary=None;outbox.sync(root)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return record


@outbox.serialized
def prepare(manager):
    root=directory(manager,True);entries=outbox.paths(root)
    if len(entries)>=outbox.MAX_ENTRIES:raise runtime.RuntimeFailure('Accounting session journal is full.')
    for path in entries:read(path,manager)


def identity(manager,source):
    state=manager.read();index=next(i for i,n in enumerate(state['spec']['nodes']) if n['name']==source)
    observed=json.loads(manager.crun('state',source,check=False,timeout=3).stdout)
    pid=observed.get('pid');integer(pid,2,2**31-1,'Container PID')
    start=runtime.process_identity(pid)
    if observed.get('status')!='running' or start is None:raise ValueError('Original container is unavailable.')
    netns=Path('/run/netns')/namespace(state['spec'],index);info=netns.stat();actual=Path('/proc')/str(pid)/'ns/net'
    if (actual.stat().st_dev,actual.stat().st_ino)!=(info.st_dev,info.st_ino):raise ValueError('Container namespace differs.')
    return dict(boot_id=BOOT.read_text().strip(),namespace_dev=info.st_dev,namespace_ino=info.st_ino,container_pid=pid,container_start=start)


def group_path(manager,record):return session_parent(manager,record['source'])/record['session_id']


def group_info(path):
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode):raise ValueError('Accounting session cgroup is not a directory.')
    return info


def begin(manager,source,username,group):
    address,_,pin=outbox.binding(manager,source,username)
    node=next(n for n in manager.read()['spec']['nodes'] if n['name']==source)
    if not node['radius_access'].get('accounting_journal'):raise ValueError('Accounting journal is not enabled.')
    path=session_parent(manager,source)/group.name
    if group.path!=path:raise ValueError('Accounting session group path differs.')
    info=group_info(path);supervisor=runtime.process_identity(os.getpid())
    if supervisor is None:raise ValueError('Supervisor identity unavailable.')
    record=dict(version=1,lab=manager.name,source=source,server=address,username=username,session_id=group.name,
                policy_sha256=pin,created_at=int(time.time()),phase='intent',supervisor_pid=os.getpid(),supervisor_start=supervisor,
                cgroup_dev=info.st_dev,cgroup_ino=info.st_ino,**identity(manager,source))
    return write(manager,record)


def owned_group(manager,record):
    path=group_path(manager,record);info=group_info(path)
    if (info.st_dev,info.st_ino)!=(record['cgroup_dev'],record['cgroup_ino']):raise ValueError('Accounting cgroup identity changed.')
    return path


def empty(path):
    events=dict(line.split() for line in (path/'cgroup.events').read_text().splitlines())
    if events.get('populated') not in ('0','1'):raise ValueError('Accounting cgroup population is unavailable.')
    return events['populated']=='0'


def mark_empty(manager,record):
    if not empty(owned_group(manager,record)):raise ValueError('Accounting session still populated.')
    if record['phase']=='empty':return record
    updated={**record,'phase':'empty'}
    return write(manager,updated,previous=record)


@outbox.serialized
def handoff(manager,record):
    root=directory(manager)
    if root is None:raise runtime.RuntimeFailure('Accounting session journal disappeared.')
    target=root/(record['session_id']+'.json')
    if record['phase']!='empty' or read(target,manager)!=record:raise ValueError('Journal cleanup checkpoint is unconfirmed.')
    target.unlink();outbox.sync(root)


def pending(manager):
    try:
        records=[read(path,manager) for path in outbox.paths(directory(manager))]
        return {'status':'observed','pending':len(records),'entries':[{key:r[key] for key in ('source','username','session_id','phase','created_at')} for r in records]}
    except (OSError,ValueError,runtime.RuntimeFailure):return {'status':'unknown','pending':None,'entries':[],'error':'JOURNAL_UNAVAILABLE_OR_INVALID'}


def preflight(manager,session_id):
    if not isinstance(session_id,str) or not re.fullmatch(r'aaa-[0-9a-f]{32}',session_id):raise ValueError('Choose one accounting session.')
    result={'status':'unknown','session_id':session_id}
    try:
        root=directory(manager)
        if root is None:raise ValueError('Journal unavailable.')
        record=read(root/(session_id+'.json'),manager)
        if BOOT.read_text().strip()==record['boot_id'] and runtime.process_identity(record['supervisor_pid'])==record['supervisor_start']:
            return {**result,'status':'blocked','error':'SUPERVISOR_STILL_ACTIVE'}
        return {**result,'status':'ready'}
    except (OSError,ValueError,runtime.RuntimeFailure):return {**result,'error':'JOURNAL_UNAVAILABLE_OR_INVALID'}


def reconcile(manager,session_id,*,terminate=False):
    if type(terminate) is not bool or not isinstance(session_id,str) or not re.fullmatch(r'aaa-[0-9a-f]{32}',session_id):raise ValueError('Choose one explicit accounting session and boolean termination flag.')
    result={'status':'blocked','session_id':session_id,'terminated':False,'stop_queued':False}
    try:
        root=directory(manager)
        if root is None:raise ValueError('Journal unavailable.')
        record=read(root/(session_id+'.json'),manager)
        address,secret,pin=outbox.binding(manager,record['source'],record['username'])
        if pin!=record['policy_sha256'] or address!=record['server']:raise ValueError('Policy binding changed.')
        same_boot=BOOT.read_text().strip()==record['boot_id']
        if same_boot and runtime.process_identity(record['supervisor_pid'])==record['supervisor_start']:
            return {**result,'error':'SUPERVISOR_STILL_ACTIVE'}
        # A committed empty checkpoint is historical cleanup evidence; no current
        # kernel group is touched unless its full original runtime still matches.
        current=identity(manager,record['source'])
        same_runtime=all(current[key]==record[key] for key in current)
        if record['phase']=='intent' and not same_runtime:return {**result,'error':'RUNTIME_IDENTITY_CHANGED'}
        path=group_path(manager,record)
        if same_runtime:
            if record['phase']=='intent' or path.exists():
                path=owned_group(manager,record)
                if not empty(path):
                    if not terminate:return {**result,'error':'SESSION_STILL_POPULATED'}
                    (path/'cgroup.kill').write_text('1');result['terminated']=True
                    deadline=time.monotonic()+2
                    while not empty(owned_group(manager,record)):
                        if time.monotonic()>=deadline:raise runtime.RuntimeFailure('Session cleanup unconfirmed.')
                        time.sleep(.05)
                record=mark_empty(manager,record);path.rmdir()
        if record['phase']!='empty':raise ValueError('Session cleanup unconfirmed.')
        # Recover only a compensating Stop: actual execution/elapsed time may be
        # unknown after supervisor death. Never manufacture a normal completion.
        existing_root=outbox.folder(manager)
        existing_path=existing_root/(session_id+'.json') if existing_root else None
        if existing_path is not None and existing_path.exists():
            stop=outbox.read(existing_path,manager)
            if any(stop[key]!=record[key] for key in ('source','server','username','session_id','policy_sha256')):raise ValueError('Pending Stop differs.')
            outbox.sync(existing_root)
        else:
            outbox.enqueue(manager,record['source'],address,record['username'],secret,session_id,0,9,int(time.time()),cleanup_complete=True)
        result['stop_queued']=True;handoff(manager,record)
        return {**result,'status':'passed'}
    except (OSError,ValueError,KeyError,StopIteration,runtime.RuntimeFailure):return {**result,'status':'unknown','error':'JOURNAL_OR_CLEANUP_UNCONFIRMED'}
