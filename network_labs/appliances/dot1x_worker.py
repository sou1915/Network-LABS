"""Finite EAPOL pass-through authenticator; authorization is a kernel timeout lease."""
import json
import os
from pathlib import Path
import re
import secrets
import select
import signal
import socket
import struct
import subprocess
import sys
import time
from .dot1x import TABLE, gate_snapshot
from .radius_eap_worker import access_request, eap_packet, inner
from .radius_worker import response_code

PAE=bytes.fromhex('0180c2000003')


def nft(*args,input_text=None):
    return subprocess.run(['nft',*args],input=input_text,text=True,capture_output=True,check=True,timeout=2).stdout


def gate(config,admit=False):
    data=json.loads(nft('-j','list','table','bridge',TABLE))
    pin,_=gate_snapshot(data,config['port'],config['seconds'])
    if pin!=config['fingerprint']:raise ValueError('Gate differs')
    command=f'flush set bridge {TABLE} admitted\n'
    if admit:command+=f'add element bridge {TABLE} admitted {{ {json.dumps(config["port"])} timeout {config["seconds"]}s }}\n'
    nft('-f','-',input_text=command)
    data=json.loads(nft('-j','list','table','bridge',TABLE))
    pin,opened=gate_snapshot(data,config['port'],config['seconds'])
    if pin!=config['fingerprint'] or opened!=admit:raise ValueError('Gate transition unconfirmed')


def current(config,require_running=True):
    info=Path('/proc/self/ns/net').stat()
    if (info.st_dev,info.st_ino)!=(config['namespace_dev'],config['namespace_ino']) or socket.if_nametoindex(config['port'])!=config['ifindex']:
        raise ValueError('Original namespace/interface differs')
    with open(config['state_file'],'rb') as file:raw=file.read(262145)
    if len(raw)>262144:raise ValueError('State budget')
    state=json.loads(raw);record=state.get('dot1x_workers',{}).get(config['node'],{})
    if (require_running and (state.get('phase')!='running' or 'pending_spec' in state or 'pending_node' in state)) or record.get('token')!=config['token']:raise ValueError('Runtime generation differs')


def publish(config,result):
    try:current(config,False)
    except (OSError,ValueError,KeyError):return
    path=Path(config['output']);temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(result));temporary.chmod(0o600);temporary.replace(path)


def envelope(frame,peer,own):
    if not 18<=len(frame)<=1100 or frame[:6] not in (own,PAE) or frame[6:12]!=peer or frame[12:14]!=b'\x88\x8e':return None
    version,kind,length=struct.unpack('!BBH',frame[14:18])
    # Ethernet padding is permitted; parsing is limited to the declared PDU.
    if version not in (1,2) or length>1024 or 18+length>len(frame):return None
    payload=frame[18:18+length]
    if kind in (1,2):return (kind,b'') if not payload else None
    if kind!=0 or len(payload)<4 or int.from_bytes(payload[2:4],'big')!=len(payload):return None
    return kind,payload


def serve(config):
    result={'status':'unknown','authenticated':False,'port_closed':False,'reason':'UNCONFIRMED','radius_requests':0,'discarded':0}
    phase='initial'
    try:
        current(config);gate(config)
        with socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(0x888e)) as raw, socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as udp:
            raw.bind((config['port'],0));own=raw.getsockname()[4];peer=bytes.fromhex(config['peer_mac'].replace(':',''))
            udp.bind((config['source'],0));server=(config['address'],1812)
            def emit(eap):raw.send(peer+own+b'\x88\x8e'+struct.pack('!BBH',2,0,len(eap))+eap)
            identity=secrets.randbelow(256);emit(eap_packet(1,identity,b'\x01'))
            phase='identity';deadline=time.monotonic()+config['timeout'];packet=None;state=None;username=None
            publish(config,{**result,'phase':phase})
            while time.monotonic()<deadline:
                current(config)
                if result['discarded']>=64:result['reason']='PACKET_LIMIT';break
                readable,_,_=select.select([raw,udp],[],[],min(.1,max(0,deadline-time.monotonic())))
                # Process EAPOL first so queued Logoff cannot be ignored at authorization.
                if raw in readable:
                    frame=raw.recv(1101);message=envelope(frame,peer,own)
                    if message is None:
                        result['discarded']+=1
                    else:
                        kind,eap=message
                        if kind==2:
                            result.update(status='passed' if result['authenticated'] else 'blocked',reason='LOGOFF');break
                        if kind==1:
                            if phase=='authorized':result.update(status='passed',reason='RESTART_REQUESTED');break
                            if phase=='identity':emit(eap_packet(1,identity,b'\x01'))
                        elif phase in ('identity','md5'):
                            if eap[0]!=2 or eap[1]!=identity:result['discarded']+=1
                            elif phase=='identity':
                                if len(eap)<6 or eap[4]!=1:raise ValueError('Identity required')
                                username=eap[5:].decode('ascii')
                                if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}',username) or username not in config['users']:
                                    emit(eap_packet(4,identity));result.update(status='blocked',reason='IDENTITY_NOT_ALLOWED');break
                                request={**config,'username':username}
                                packet=access_request(request,eap);udp.sendto(packet,server);result['radius_requests']+=1;phase='radius_identity'
                            else:
                                if len(eap)<22 or eap[4:6]!=b'\x04\x10':raise ValueError('MD5 response required')
                                packet=access_request({**config,'username':username},eap,state,packet[1]);udp.sendto(packet,server)
                                result['radius_requests']+=1;phase='radius_md5'
                if udp in readable and select.select([raw],[],[],0)[0]:continue
                if udp in readable:
                    received,sender=udp.recvfrom(4097)
                    code=response_code(received,packet,config['secret'].encode('ascii')) if packet is not None and sender==server and phase in ('radius_identity','radius_md5') else None
                    if code is None:result['discarded']+=1
                    else:
                        eap,new_state=inner(received)
                        if code==3 and eap==eap_packet(4,identity):
                            emit(eap);result.update(status='failed',reason='REJECTED');break
                        if phase=='radius_identity':
                            if code!=11 or len(eap)<22 or eap[0]!=1 or eap[4:6]!=b'\x04\x10' or new_state is None:raise ValueError('Verified MD5 challenge required')
                            state=new_state;identity=eap[1];emit(eap);phase='md5'
                        elif code==2 and eap==eap_packet(3,identity) and new_state is None:
                            current(config);gate(config,True);emit(eap);phase='authorized';result['authenticated']=True
                            deadline=time.monotonic()+config['seconds'];publish(config,{**result,'phase':phase})
                        else:raise ValueError('Verified EAP success required')
                if result['discarded']>=64:result['reason']='PACKET_LIMIT';break
            else:result.update(status='passed' if result['authenticated'] else 'unknown',reason='LEASE_EXPIRED' if result['authenticated'] else 'AUTH_TIMEOUT')
    except (OSError,ValueError,KeyError,UnicodeError,subprocess.SubprocessError) as error:result.update(status='unknown',reason='PROTOCOL_OR_GATE_UNCONFIRMED',last_stage=phase,error_type=type(error).__name__)
    except (KeyboardInterrupt,SystemExit):result.update(status='unknown',reason='INTERRUPTED')
    finally:
        try:current(config,False);gate(config);result['port_closed']=True
        except (OSError,ValueError,KeyError,subprocess.SubprocessError):result.update(status='unknown',reason='GATE_CLOSURE_UNCONFIRMED')
        publish(config,{**result,'phase':'finished'})
    return result


def main():
    os.umask(0o077)
    def stop(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    try:serve(json.loads(sys.stdin.read(4097)))
    except (OSError,ValueError,KeyError,TypeError):raise SystemExit(1)


if __name__=='__main__':main()
