"""Real rsyslog pair preflight, explicit identity replacement and rollback."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from syslog_test_identity import lifecycle_certificates
from test_native_syslog_tls_integration import certificates
from network_labs.appliances.examples import syslog_tls_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.syslog_tls import CA,CERT,KEY
from network_labs.appliances.syslog_server import LOG
from test_native_integration import unexpected_host_link_changes

PROBE='''import hashlib,json,socket,ssl,sys
r=json.load(sys.stdin);out={'verified':False,'rejected':False}
try:
 c=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);c.load_verify_locations(cafile=r['ca']);c.load_cert_chain(r['cert'],r['key'])
 c.minimum_version=ssl.TLSVersion.TLSv1_2
 with socket.create_connection(('192.0.2.10',6514),3) as raw:
  with c.wrap_socket(raw,server_hostname='collector.lab') as s:
   out.update(verified=True,version=s.version(),leaf_der_sha256=hashlib.sha256(s.getpeercert(binary_form=True)).hexdigest())
   p=('<133>1 - probe lifecycle - - - '+r['token']).encode();s.sendall(str(len(p)).encode()+b' '+p)
   if r.get('reject'):out['rejected']=s.recv(1)==b''
except ssl.SSLError as e:out.update(rejected=True,detail=str(e)[:300])
except OSError as e:out['detail']=str(e)[:300]
print(json.dumps(out))
'''


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeSyslogTLSLifecycleTests(unittest.TestCase):
    def test_pair_rejection_rekey_ca_replacement_distinct_issuers_restore_and_rollback(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('openssl','rsyslogd','busybox','crun','ip'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        with tempfile.TemporaryDirectory() as folder,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);(root/'first').mkdir();(root/'second').mkdir()
            ca,wrong,leaves=lifecycle_certificates(root/'first');new_ca,_,new_leaves=certificates(root/'second')
            def image(name,trust,identity):
                return static_busybox_rootfs(shutil.which('busybox'),root/name,rsyslog=shutil.which('rsyslogd'),
                    rsyslog_tls=True,syslog_ca=trust,syslog_certificate=identity[0],syslog_private_key=identity[1])
            old=(image('old-server',ca,leaves['collector.lab']),image('old-client',ca,leaves['sender.lab']))
            renewed=(image('renewed-server',ca,leaves['renewed-collector.lab']),image('renewed-client',ca,leaves['renewed-sender.lab']))
            rotated=(image('new-server',new_ca,new_leaves['collector.lab']),image('new-client',new_ca,new_leaves['sender.lab']))
            cross=(image('cross-server',new_ca,leaves['collector.lab']),image('cross-client',ca,new_leaves['sender.lab']))
            hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for images in (old,renewed,rotated,cross)
                    for image_root in images for p in (Path(image_root)/v.lstrip('/') for v in (CA,CERT,KEY))}
            for old_root,new_root in zip(old,renewed):
                self.assertNotEqual(hashes[str(Path(old_root)/KEY.lstrip('/'))],hashes[str(Path(new_root)/KEY.lstrip('/'))])
            name='syslog-lifecycle-'+str(os.getpid());manager=Manager(name)
            def spec(images,server_name='collector.lab',client_name='sender.lab'):
                value=syslog_tls_lab(*images,server_name,client_name,verify_peer_on_start=True);value['name']=name;return value
            def wait(predicate,label):
                until=time.monotonic()+15
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                diagnostics=[p.read_text(errors='replace') for p in (manager.directory/'PC1/syslog-server.log',manager.directory/'PC2/syslog.log') if p.exists()]
                self.fail(label+': '+repr(diagnostics))
            def logs():return manager.crun('exec','PC1','/bin/busybox','cat',LOG,check=False).stdout
            def probe(token,trust,identity,reject=False):
                request={'token':token,'ca':str(trust),'cert':str(identity[0]),'key':str(identity[1]),'reject':reject}
                return json.loads(manager.ns(2,sys.executable,'-I','-c',PROBE,input_text=json.dumps(request),timeout=6).stdout)
            def healthy(label,trust,server_identity,client_identity):
                wait(lambda:'192.0.2.10:6514' in manager.ns(0,'ss','-H','-ltn','sport = :6514').stdout,'TLS listener unavailable')
                wait(lambda:manager.crun('exec','PC2','/bin/busybox','test','-S','/dev/log',check=False).returncode==0,'Local sender socket unavailable')
                token='LOGGER-'+label
                manager.crun('exec','PC2','/bin/busybox','logger','-p','local0.notice','-t','lifecycle',token)
                wait(lambda:token in logs(),'Actual sender marker missing')
                token='PROBE-'+label;actual=probe(token,trust,client_identity)
                self.assertTrue(actual['verified'],actual);self.assertIn(actual['version'],('TLSv1.2','TLSv1.3'))
                self.assertEqual(actual['leaf_der_sha256'],hashlib.sha256(ssl.PEM_cert_to_DER_cert(server_identity[0].read_text())).hexdigest())
                wait(lambda:token in logs(),'Independent TLS marker missing')
                for node in ('PC1','PC2'):
                    observed=manager.inspect(node)
                    if node=='PC1':self.assertTrue(observed['syslog_server']['configuration_verified'])
                    else:self.assertTrue(observed['management']['configuration_verified'])
                self.assertFalse(manager.ns(0,'ss','-H','-ltn','sport = :514').stdout)
                self.assertNotEqual(manager.crun('exec','SW1','/bin/busybox','cat',KEY,check=False).returncode,0)
            try:
                bad_server=root/'bad-server';bad_client=root/'bad-client';shutil.copytree(old[0],bad_server);shutil.copytree(old[1],bad_client)
                for role,images,image_root in (('collector.lab',(bad_server,old[1]),bad_server),('sender.lab',(old[0],bad_client),bad_client)):
                    for version in ('expired','future'):
                        identity=leaves[version+'-'+role]
                        for path,source in ((CERT,identity[0]),(KEY,identity[1])):(image_root/path.lstrip('/')).write_bytes(source.read_bytes())
                        with manager.locked(),self.assertRaisesRegex(RuntimeFailure,'expired|not yet valid'):manager.start(spec(images))
                        self.assertFalse(manager.directory.exists());self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
                # Correctly pinned role/trust/name faults must also fail offline.
                for role,images,image_root,identity in (('collector.lab',(bad_server,old[1]),bad_server,leaves['sender.lab']),('sender.lab',(old[0],bad_client),bad_client,leaves['collector.lab'])):
                    for path,source in ((CERT,identity[0]),(KEY,identity[1])):(image_root/path.lstrip('/')).write_bytes(source.read_bytes())
                    with manager.locked(),self.assertRaisesRegex(RuntimeFailure,'unsuitable certificate purpose'):manager.start(spec(images))
                    self.assertFalse(manager.directory.exists())
                for path,source in ((CERT,leaves['sender.lab'][0]),(KEY,leaves['sender.lab'][1]),(CA,wrong)):(bad_client/path.lstrip('/')).write_bytes(source.read_bytes())
                with manager.locked(),self.assertRaisesRegex(RuntimeFailure,'certificate verify failed'):manager.start(spec((old[0],bad_client)))
                for kwargs in ({'server_name':'wrong.lab'},{'client_name':'wrong.lab'}):
                    with manager.locked(),self.assertRaises(RuntimeFailure):manager.start(spec(old,**kwargs))
                    self.assertFalse(manager.directory.exists())
                original=spec(old)
                with manager.locked():manager.start(original)
                healthy('ORIGINAL',ca,leaves['collector.lab'],leaves['sender.lab'])
                with manager.locked():manager.write_startup();saved_old=load_startup(name);self.assertEqual(saved_old,original);manager.stop()
                stale=copy.deepcopy(original);stale['nodes'][0]['rootfs']=str(renewed[0]);stale['nodes'][2]['rootfs']=str(renewed[1])
                with manager.locked(),self.assertRaisesRegex(RuntimeFailure,'pins differ'):manager.start(stale)
                self.assertFalse(manager.directory.exists())
                with manager.locked():manager.start(spec(renewed))
                healthy('REKEYED',ca,leaves['renewed-collector.lab'],leaves['renewed-sender.lab'])
                with manager.locked():manager.write_startup();manager.stop();manager.start(spec(rotated))
                healthy('NEW-CA',new_ca,new_leaves['collector.lab'],new_leaves['sender.lab'])
                for token,trust,identity in (('OLD-TRUST',ca,new_leaves['sender.lab']),('OLD-CLIENT',new_ca,leaves['sender.lab'])):
                    rejected=probe(token,trust,identity,reject=True);self.assertTrue(rejected['rejected'],rejected);self.assertNotIn(token,logs())
                with manager.locked():
                    manager.write_startup();saved=load_startup(name);self.assertEqual(saved,spec(rotated))
                    self.assertNotIn('PRIVATE KEY',json.dumps(saved));manager.stop();manager.start(saved)
                healthy('COLD-RESTORE',new_ca,new_leaves['collector.lab'],new_leaves['sender.lab'])
                self.assertNotIn('LOGGER-NEW-CA',logs())  # No volatile log snapshot is restored.
                with manager.locked():manager.stop();manager.start(spec(cross))
                healthy('DISTINCT-ISSUERS',ca,leaves['collector.lab'],new_leaves['sender.lab'])
                with manager.locked():manager.stop();manager.start(saved_old)
                healthy('ROLLBACK',ca,leaves['collector.lab'],leaves['sender.lab'])
                self.assertTrue(probe('NEW-CLIENT-REJECTED',ca,new_leaves['sender.lab'],reject=True)['rejected'])
                self.assertNotIn('NEW-CLIENT-REJECTED',logs())
                for path,digest in hashes.items():self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(),digest)
                with manager.locked():manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
