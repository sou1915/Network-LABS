"""Private, bounded, Stop-only outbox after confirmed session cleanup.

Callers hold the lab lifecycle lock. No secret/password or live session is saved.
"""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from . import runtime
from .spec import identifier,integer

MAX_ENTRIES=32
MAX_BYTES=4096
FIELDS={'version','lab','source','server','username','session_id','session_seconds','terminate_cause','event_time','policy_sha256'}


def folder(manager,create=False,*,kind='accounting-outbox'):
    if kind not in ('accounting-outbox','accounting-sessions'):raise ValueError('Invalid accounting store.')
    root=runtime.CONFIG_ROOT
    if root.is_symlink():raise runtime.RuntimeFailure('Accounting outbox refuses a symlink configuration root.')
    if not root.exists() and not create:return None
    if create:
        root.mkdir(mode=0o700,parents=True,exist_ok=True)
        sync(root.parent)
    info=root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o022:
        raise runtime.RuntimeFailure('Accounting outbox configuration root has unsafe ownership/permissions.')
    for path in (root/identifier(manager.name),root/manager.name/kind):
        if not path.exists() and not path.is_symlink() and not create:return None
        if create:path.mkdir(mode=0o700,exist_ok=True)
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077:
            raise runtime.RuntimeFailure('Accounting outbox directories require private ownership and mode 0700.')
        if create:sync(path.parent)
    return path


def paths(directory):
    if directory is None:return []
    result=[]
    with os.scandir(directory) as entries:
        for entry in entries:
            if not re.fullmatch(r'aaa-[0-9a-f]{32}\.json',entry.name):
                raise runtime.RuntimeFailure('Accounting outbox contains an unexpected entry; retained for review.')
            result.append(Path(entry.path))
            if len(result)>MAX_ENTRIES:raise runtime.RuntimeFailure('Accounting outbox entry limit exceeded; retained for review.')
    return sorted(result)


def sync(directory):
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def validate_record(record,manager):
    if not isinstance(record,dict) or set(record)!=FIELDS or type(record['version']) is not int or record['version']!=1 or record['lab']!=manager.name:
        raise ValueError('Invalid accounting outbox schema.')
    identifier(record['source'])
    if not isinstance(record['username'],str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}',record['username']):raise ValueError('Invalid outbox username.')
    if not isinstance(record['session_id'],str) or not re.fullmatch(r'aaa-[0-9a-f]{32}',record['session_id']):raise ValueError('Invalid outbox session.')
    if not isinstance(record['server'],str) or str(ipaddress.IPv4Address(record['server']))!=record['server']:raise ValueError('Invalid outbox server.')
    integer(record['session_seconds'],0,0xffffffff,'Accounting seconds')
    integer(record['event_time'],0,2**63-1,'Accounting event time')
    if type(record['terminate_cause']) is not int or record['terminate_cause'] not in (1,5,6,9):raise ValueError('Invalid outbox termination cause.')
    if not isinstance(record['policy_sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',record['policy_sha256']):raise ValueError('Invalid outbox policy pin.')
    return record


def read(path,manager,*,validator=validate_record):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1 or not 0<info.st_size<=MAX_BYTES:
            raise runtime.RuntimeFailure('Accounting outbox record requires a private bounded regular file.')
        record=validator(json.loads(stream.read(MAX_BYTES+1)),manager)
    if path.name!=record['session_id']+'.json':raise ValueError('Accounting outbox filename differs from session.')
    return record


def binding(manager,source,username):
    from .ssh_radius import managed_secret
    state=manager.read()
    if state['phase']!='running' or 'pending_spec' in state or 'pending_node' in state:raise ValueError('Outbox requires an unchanged running lab.')
    node=next(n for n in state['spec']['nodes'] if n['name']==source)
    policy=node.get('radius_access') or {}
    if not policy.get('accounting') or not policy.get('accounting_outbox') or 'shell' not in policy.get('users',{}).get(username,[]):
        raise ValueError('Accounting outbox policy/user is unavailable.')
    address,secret=managed_secret(state['spec'],node)
    server=next(n for n in state['spec']['nodes'] if n.get('radius_server') and str(ipaddress.IPv4Interface(n['interfaces']['eth0']).ip)==address)
    if not server['radius_server'].get('accounting'):raise ValueError('Outbox requires managed accounting server.')
    values={'source':source,'interface':node['interfaces']['eth0'],'server':address,'server_node':server['name'],
            'username':username,'policy':policy,'secret_sha256':hashlib.sha256(secret.encode('ascii')).hexdigest()}
    pin=hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return address,secret,pin


def prepare(manager):
    directory=folder(manager,True);existing=paths(directory)
    if len(existing)>=MAX_ENTRIES:raise runtime.RuntimeFailure('Accounting outbox is full; new accounted session refused.')
    for path in existing:read(path,manager)


def enqueue(manager,source,server,username,secret,session_id,session_seconds,terminate_cause,event_time,*,cleanup_complete):
    if cleanup_complete is not True:raise ValueError('Stop outbox requires confirmed session cleanup.')
    address,expected,pin=binding(manager,source,username)
    if address!=server or expected!=secret:raise ValueError('Accounting outbox backend binding differs.')
    record=validate_record(dict(version=1,lab=manager.name,source=source,server=server,username=username,session_id=session_id,
                                session_seconds=session_seconds,terminate_cause=terminate_cause,event_time=event_time,policy_sha256=pin),manager)
    directory=folder(manager,True);target=directory/(session_id+'.json');existing=paths(directory)
    if target in existing:
        if read(target,manager)!=record:raise ValueError('Existing accounting outbox event differs.')
        return record
    if len(existing)>=MAX_ENTRIES:raise runtime.RuntimeFailure('Accounting outbox is full; no event was discarded.')
    payload=(json.dumps(record,sort_keys=True,separators=(',',':'))+'\n').encode()
    if len(payload)>MAX_BYTES:raise ValueError('Accounting outbox record exceeds size limit.')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=directory,prefix='.pending-',delete=False) as stream:
            temporary=Path(stream.name);stream.write(payload);stream.flush();os.fsync(stream.fileno())
        os.link(temporary,target,follow_symlinks=False);temporary.unlink();temporary=None;sync(directory)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return record


def acknowledge(manager,record):
    directory=folder(manager)
    if directory is None:raise runtime.RuntimeFailure('Accounting outbox disappeared before local acknowledgement.')
    path=directory/(record['session_id']+'.json')
    if read(path,manager)!=record:raise ValueError('Accounting outbox changed before acknowledgement.')
    path.unlink();sync(directory)


def pending(manager):
    try:
        records=[read(path,manager) for path in paths(folder(manager))]
        return {'status':'observed','pending':len(records),'entries':[{k:r[k] for k in ('source','server','username','session_id','session_seconds','terminate_cause','event_time')} for r in records]}
    except (OSError,ValueError,runtime.RuntimeFailure):
        return {'status':'unknown','pending':None,'entries':[],'error':'OUTBOX_UNAVAILABLE_OR_INVALID'}


def flush(manager,*,limit=4,timeout=3):
    from .radius_accounting import send
    integer(limit,1,8,'Outbox flush limit');integer(timeout,1,5,'Accounting timeout')
    result={'status':'passed','entries':[],'attempted':0}
    try:records=[read(path,manager) for path in paths(folder(manager))]
    except (OSError,ValueError,runtime.RuntimeFailure):return {**result,'status':'unknown','error':'OUTBOX_UNAVAILABLE_OR_INVALID'}
    for record in records[:limit]:
        item={'session_id':record['session_id'],'status':'blocked'}
        try:
            address,secret,pin=binding(manager,record['source'],record['username'])
            if address!=record['server'] or pin!=record['policy_sha256']:raise ValueError('Policy changed.')
            delay=max(0,int(time.time())-record['event_time'])
            if delay>0xffffffff:raise ValueError('Event too old.')
        except (OSError,ValueError,StopIteration,runtime.RuntimeFailure):
            item['error']='POLICY_BINDING_UNAVAILABLE_OR_CHANGED'
        else:
            result['attempted']+=1
            try:
                receipt=send(manager,record['source'],address,username=record['username'],secret=secret,
                    session_id=record['session_id'],event='stop',session_seconds=record['session_seconds'],
                    terminate_cause=record['terminate_cause'],timeout=timeout,delay_seconds=delay)
                item.update(status=receipt['status'],receipt=receipt)
                if receipt.get('status')=='passed' and receipt.get('response_verified') is True:acknowledge(manager,record)
                else:item['status']='unknown'
            except (OSError,ValueError,runtime.RuntimeFailure):item.update(status='unknown',error='DELIVERY_OR_LOCAL_ACK_UNCONFIRMED')
        result['entries'].append(item)
        if item['status']!='passed':result['status']='unknown'
    snapshot=pending(manager);result['remaining']=snapshot['pending']
    if snapshot['status']!='observed' or snapshot['pending']:result['status']='unknown'
    return result
