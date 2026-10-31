"""Real mutual-TLS rsyslog, explicit trust/name failures, retry and cold restore."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from network_labs.appliances.capture import capture
from network_labs.appliances.examples import syslog_tls_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.syslog_server import LOG,start_server
from network_labs.appliances.syslog_tls import CA,CERT,KEY
from test_native_integration import unexpected_host_link_changes

PROBE='''import json,socket,ssl,sys
r=json.load(sys.stdin);out={'verified':False,'rejected':False}
try:
 c=ssl.create_default_context(cafile=r['ca']);c.minimum_version=ssl.TLSVersion.TLSv1_2;c.load_cert_chain(r['cert'],r['key'])
 with socket.create_connection(('192.0.2.10',6514),3) as raw:
  with c.wrap_socket(raw,server_hostname=r['name']) as s:
   out.update(verified=True,version=s.version());p=('<133>1 - probe native - - - '+r['token']).encode();s.sendall(str(len(p)).encode()+b' '+p)
   if r.get('reject'):
    out['rejected']=s.recv(1)==b''
except ssl.SSLError as e:out.update(rejected=True,detail=str(e)[:300])
except OSError as e:out['detail']=str(e)[:300]
print(json.dumps(out))
'''


def certificates(folder):
    def openssl(*args): run(['openssl',*args],timeout=15)
    def ca(name):
        key=folder/(name+'.key');cert=folder/(name+'.pem')
        openssl('req','-x509','-newkey','rsa:2048','-nodes','-days','2','-subj','/CN='+name,'-addext','basicConstraints=critical,CA:TRUE','-keyout',key,'-out',cert)
        return cert,key
    authority,authority_key=ca('LabCA');wrong,_=ca('OtherCA');leaves={}
    for name,purpose in (('collector.lab','serverAuth'),('sender.lab','clientAuth'),('intruder.lab','clientAuth')):
        key=folder/(name+'.key');csr=folder/(name+'.csr');cert=folder/(name+'.pem');ext=folder/(name+'.ext')
        openssl('req','-new','-newkey','rsa:2048','-nodes','-subj','/CN='+name,'-keyout',key,'-out',csr)
        ext.write_text('subjectAltName=DNS:'+name+'\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage='+purpose+'\n')
        openssl('x509','-req','-in',csr,'-CA',authority,'-CAkey',authority_key,'-CAcreateserial','-days','1','-extfile',ext,'-out',cert)
        key.chmod(0o600);leaves[name]=(cert,key)
    return authority,wrong,leaves


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeSyslogTLSTests(unittest.TestCase):
    def test_mutual_trust_name_rejection_encrypted_retry_assets_and_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('openssl','rsyslogd','busybox','crun','ip','tcpdump'): self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        with tempfile.TemporaryDirectory() as directory,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(directory)/'saved'):
            root=Path(directory);authority,wrong,leaves=certificates(root)
            def rootfs(name,identity,ca):
                cert,key=leaves[identity]
                return static_busybox_rootfs(shutil.which('busybox'),root/name,rsyslog=shutil.which('rsyslogd'),rsyslog_tls=True,syslog_ca=ca,syslog_certificate=cert,syslog_private_key=key)
            server=rootfs('server','collector.lab',authority);client=rootfs('client','sender.lab',authority);bad_ca=rootfs('client-bad-ca','sender.lab',wrong)
            for case in ('valid','wrong-name','wrong-ca'):
                with self.subTest(case=case):
                    spec=syslog_tls_lab(server,bad_ca if case=='wrong-ca' else client,'wrong.lab' if case=='wrong-name' else 'collector.lab','sender.lab')
                    spec['name']='syslog-tls-'+str(os.getpid())+'-'+case;manager=Manager(spec['name'])
                    def logs(node='PC1',path=LOG): return manager.crun('exec',node,'/bin/busybox','cat',path,check=False).stdout
                    def diagnostic():
                        p=manager.directory/'PC2/syslog.log';return p.read_text(errors='replace') if p.exists() else ''
                    def wait(predicate,label,seconds=15):
                        end=time.monotonic()+seconds
                        while time.monotonic()<end:
                            if predicate():return
                            time.sleep(.1)
                        p=manager.directory/'PC1/syslog-server.log'
                        self.fail(label+': sender='+diagnostic()+'; server='+p.read_text(errors='replace'))
                    def ready():
                        wait(lambda:'192.0.2.10:6514' in manager.ns(0,'ss','-H','-ltn','sport = :6514').stdout,'TLS listener unavailable')
                        wait(lambda:manager.crun('exec','PC2','/bin/busybox','test','-S','/dev/log',check=False).returncode==0,'local input unavailable')
                        self.assertFalse(manager.ns(0,'ss','-H','-ltn','sport = :514').stdout)
                        self.assertFalse(manager.ns(0,'ss','-H','-lun','sport = :514').stdout)
                    def emit(token): manager.crun('exec','PC2','/bin/busybox','logger','-p','local0.notice','-t','tls-native',token)
                    def received(token): wait(lambda:token in logs(),'missing stored TLS marker '+token,20)
                    def probe(token,identity='sender.lab',name='collector.lab',ca=authority,reject=False):
                        cert,key=leaves[identity]
                        result=manager.ns(2,sys.executable,'-I','-c',PROBE,input_text=json.dumps({'ca':str(ca),'cert':str(cert),'key':str(key),'name':name,'token':token,'reject':reject}),timeout=6)
                        return json.loads(result.stdout)
                    try:
                        with manager.locked(): manager.start(spec)
                        ready()
                        self.assertNotEqual(manager.crun('exec','SW1','/bin/busybox','cat',KEY,check=False).returncode,0,'Non-TLS switch must not see a shared base identity')
                        if case!='valid':
                            token='DENIED-'+case;emit(token)
                            wait(lambda:token in logs('PC2','/run/messages'),'local failed-TLS logging unavailable')
                            wait(lambda:any(t in (diagnostic()+logs('PC2','/run/messages')).lower() for t in ('certificate','not permitted','peer name','handshake')),'TLS failure evidence unavailable')
                            self.assertTrue(probe('DENIED-PROBE',name='wrong.lab' if case=='wrong-name' else 'collector.lab',ca=wrong if case=='wrong-ca' else authority)['rejected'])
                            self.assertTrue(probe('POSITIVE-CONTROL')['verified']);received('POSITIVE-CONTROL')
                            self.assertNotIn(token,logs());self.assertNotIn('DENIED-PROBE',logs())
                            continue
                        event=threading.Event();pcap=root/'encrypted.pcap'
                        future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=5,packets=1000,expression='tcp port 6514',ready=event.set)
                        self.assertTrue(event.wait(5))
                        emit('TLS-AUTOMATIC-SECRET-MARKER');received('TLS-AUTOMATIC-SECRET-MARKER')
                        verified=probe('TLS-INDEPENDENT-PROBE');self.assertTrue(verified['verified'],verified);self.assertIn(verified['version'],('TLSv1.2','TLSv1.3'));received('TLS-INDEPENDENT-PROBE')
                        denied=probe('BAD-CLIENT-MUST-NOT-STORE',identity='intruder.lab',reject=True);self.assertTrue(denied['rejected'],denied)
                        manager.ns(2,sys.executable,'-I','-c',"import socket;s=socket.create_connection(('192.0.2.10',6514),3);s.sendall(b'<133>PLAINTEXT-MUST-DROP\\n');s.close()")
                        future.result(timeout=8);self.assertNotIn(b'TLS-AUTOMATIC-SECRET-MARKER',pcap.read_bytes());self.assertNotIn(b'TLS-INDEPENDENT-PROBE',pcap.read_bytes())
                        self.assertNotIn('BAD-CLIENT-MUST-NOT-STORE',logs());self.assertNotIn('PLAINTEXT-MUST-DROP',logs())
                        with manager.locked():
                            manager.crun('exec','PC2','/bin/busybox','chmod','644',KEY)
                            with self.assertRaises(RuntimeFailure):manager.write_startup()
                            manager.crun('exec','PC2','/bin/busybox','chmod','600',KEY)
                            manager.crun('exec','PC2','/bin/sh','-c','printf altered > '+CA)
                            with self.assertRaises(RuntimeFailure):manager.write_startup()
                            manager.crun('exec','PC2','/bin/sh','-c','cat > '+CA,input_text=authority.read_text())
                        offset=len(diagnostic());local_offset=len(logs('PC2','/run/messages'))
                        manager.crun('exec','PC1','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/rsyslogd.pid)"')
                        wait(lambda:not manager.ns(0,'ss','-H','-ltn','sport = :6514').stdout,'stopped collector still listens')
                        def suspended():
                            emit('TLS-OUTAGE-TRIGGER');return 'suspended' in (diagnostic()[offset:]+logs('PC2','/run/messages')[local_offset:]).lower()
                        wait(suspended,'no fresh TLS retry suspension',20);emit('TLS-QUEUED-RECOVERY')
                        wait(lambda:'TLS-QUEUED-RECOVERY' in logs('PC2','/run/messages'),'local logging blocked')
                        start_server(manager,spec['nodes'][0]);ready();received('TLS-QUEUED-RECOVERY')
                        with manager.locked():
                            manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec);self.assertNotIn('PRIVATE KEY',json.dumps(saved))
                            manager.stop();manager.start(saved)
                        ready();self.assertNotIn('TLS-QUEUED-RECOVERY',logs());emit('TLS-COLD-RESTORE');received('TLS-COLD-RESTORE')
                        with manager.locked():manager.write_startup()
                    finally:
                        if manager.directory.exists():
                            with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
