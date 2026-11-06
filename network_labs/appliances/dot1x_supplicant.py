"""Opt-in owned wired peer service; the NAS still requires explicit finite auth."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import time
import uuid
from .radius_server import eap_password
from .runtime import RuntimeFailure,process_identity
from .snooping import alive
from .spec import keys,namespace

PROCESSES={}
# Stable Linux UAPI values; some Python sysroots omit the symbolic bindings.
ADD_SEALS=getattr(fcntl,'F_ADD_SEALS',1033)
PRIVATE_SEALS=15  # F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE


def validate_node(node):
    policy=node.get('dot1x_supplicant')
    if policy is None:return
    keys(policy,('interface','username','password_file','password_sha256'),'Wired supplicant')
    if (node['runtime']!='oci' or node['role']!='host' or set(node['interfaces'])!={'eth0'}
            or policy.get('interface')!='eth0' or node['shutdown'] or node.get('startup')):
        raise ValueError('Managed wired supplicant requires one UP physical OCI host interface without startup.')
    if not isinstance(policy.get('username'),str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}',policy['username']):
        raise ValueError('Managed wired supplicant requires an explicit login identity.')
    path=policy.get('password_file')
    if not isinstance(path,str) or not Path(path).is_absolute() or '..' in Path(path).parts or '\0' in path or len(path)>4096:
        raise ValueError('Managed wired supplicant requires an absolute private password asset.')
    if not isinstance(policy.get('password_sha256'),str) or not re.fullmatch(r'[0-9a-f]{64}',policy['password_sha256']):
        raise ValueError('Managed wired supplicant requires a SHA-256 password pin.')


def validate_lab(spec):
    for node in spec['nodes']:
        policy=node.get('dot1x_supplicant')
        if policy is None:continue
        nas=[n for n in spec['nodes'] if (n.get('dot1x') or {}).get('peer')==node['name']]
        if len(nas)!=1 or policy['username'] not in nas[0]['dot1x']['users']:
            raise ValueError('Managed supplicant requires the declared peer and allowed identity of a wired NAS.')


def preflight(node):
    if not node.get('dot1x_supplicant'):return
    if not shutil.which('wpa_supplicant') or not hasattr(os,'memfd_create'):
        raise RuntimeFailure('Managed wired peer requires host wpa_supplicant and Linux memfd support.')
    eap_password(node['dot1x_supplicant'])


def control(manager):return manager.directory/'dot1x-peer'


def namespace_identity(spec,index):
    info=(Path('/run/netns')/namespace(spec,index)).stat()
    return [info.st_dev,info.st_ino]


def config_text(node,directory):
    policy=node['dot1x_supplicant'];password=eap_password(policy).encode('ascii').hex()
    return (f'ctrl_interface={directory}\nap_scan=0\nnetwork={{\n key_mgmt=IEEE8021X\n eap=MD5\n'
            f' identity="{policy["username"]}"\n password={password}\n eapol_flags=0\n}}\n')


def ping(directory):
    local=directory/('p-'+uuid.uuid4().hex)
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as client:
            client.settimeout(.2);client.bind(str(local));client.connect(str(directory/'eth0'))
            client.send(b'PING');return client.recv(32)==b'PONG\n'
    except (OSError,ValueError):return False
    finally:local.unlink(missing_ok=True)


def observe(manager,index,node):
    record=manager.read().get('dot1x_supplicants',{}).get(node['name'])
    result={'configuration_verified':False,'running':False,'scope':'Owned peer service; explicit finite NAS admission remains required.'}
    try:
        if not alive(record):return result
        result['running']=True
        ns=(Path('/proc')/str(record['pid'])/'ns/net').stat()
        pinned=namespace_identity(manager.read()['spec'],index)
        if [ns.st_dev,ns.st_ino]!=pinned or pinned!=record['namespace']:return result
        link=json.loads(manager.ns(index,'ip','-j','link','show','dev','eth0').stdout)[0]
        if link['ifindex']!=record['ifindex']:return result
        expected=hashlib.sha256(config_text(node,control(manager)).encode()).hexdigest()
        running=ping(control(manager))
        result.update(running=running,configuration_verified=running and expected==record['config_sha256'])
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):pass
    return result


def start(manager):
    for index,node in enumerate(manager.state['spec']['nodes']):
        if not node.get('dot1x_supplicant'):continue
        directory=control(manager)
        if directory.exists():raise RuntimeFailure('Managed wired peer control path already exists; refusing adoption.')
        directory.mkdir(mode=0o700)
        if len(str(directory/'eth0').encode())>=108:raise RuntimeFailure('Managed wired peer control path is too long.')
        text=config_text(node,directory)
        fd=os.memfd_create('network-labs-wired-peer',os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
        try:
            os.fchmod(fd,0o600)
            with os.fdopen(os.dup(fd),'wb') as stream:stream.write(text.encode())
            fcntl.fcntl(fd,ADD_SEALS,PRIVATE_SEALS)
            os.lseek(fd,0,os.SEEK_SET)
            info=namespace_identity(manager.state['spec'],index)
            link=json.loads(manager.ns(index,'ip','-j','link','show','dev','eth0').stdout)[0]
            process=subprocess.Popen(['ip','netns','exec',namespace(manager.state['spec'],index),shutil.which('wpa_supplicant'),
                                      '-D','wired','-i','eth0','-c','/proc/self/fd/'+str(fd),'-q'],
                                     pass_fds=(fd,),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            identity=process_identity(process.pid)
            if identity is None:
                process.kill();process.wait();raise RuntimeFailure('Managed wired peer identity unavailable.')
            PROCESSES[process.pid]=process
            manager.state.setdefault('dot1x_supplicants',{})[node['name']]={
                'pid':process.pid,'starttime':identity,'namespace':info,
                'ifindex':link['ifindex'],'config_sha256':hashlib.sha256(text.encode()).hexdigest()}
            manager.save()
        finally:os.close(fd)
        until=time.monotonic()+4
        while time.monotonic()<until:
            if process.poll() is not None:break
            if observe(manager,index,node)['configuration_verified']:break
            time.sleep(.03)
        else:raise RuntimeFailure('Managed wired peer readiness unconfirmed.')
        if process.poll() is not None or not observe(manager,index,node)['configuration_verified']:
            raise RuntimeFailure('Managed wired peer readiness unconfirmed; private configuration not logged.')


def stop(manager):
    for name,record in list(manager.state.get('dot1x_supplicants',{}).items()):
        if alive(record):
            try:
                if os.getpgid(record['pid'])!=record['pid']:raise RuntimeFailure('Managed wired peer group differs; cleanup retained.')
                os.killpg(record['pid'],signal.SIGTERM)
            except ProcessLookupError:pass
            until=time.monotonic()+2
            while alive(record) and time.monotonic()<until:time.sleep(.02)
            if alive(record):
                try:
                    if os.getpgid(record['pid'])!=record['pid']:raise RuntimeFailure('Managed wired peer group differs; cleanup retained.')
                    os.killpg(record['pid'],signal.SIGKILL)
                except ProcessLookupError:pass
                until=time.monotonic()+2
                while alive(record) and time.monotonic()<until:time.sleep(.02)
                if alive(record):raise RuntimeFailure('Managed wired peer death unconfirmed; cleanup retained.')
        child=PROCESSES.pop(record['pid'],None)
        if child:child.wait(timeout=2)
        manager.state['dot1x_supplicants'].pop(name);manager.save()
