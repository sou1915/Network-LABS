"""Real HTTPS offline rejection, leaf rekey, CA replacement and cold restore."""
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
from https_test_identity import identities,lifecycle_identities
from network_labs.appliances.examples import https_lab
from network_labs.appliances.https_server import CA,CERT,KEY
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from test_native_integration import unexpected_host_link_changes

PEER='''import hashlib,json,socket,ssl,sys
r=json.load(sys.stdin);c=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);c.load_verify_locations(cadata=r['ca'])
c.minimum_version=ssl.TLSVersion.TLSv1_2
with socket.create_connection(('192.0.2.10',443),3) as raw:
 with c.wrap_socket(raw,server_hostname='192.0.2.10') as s:
  digest=hashlib.sha256(s.getpeercert(binary_form=True)).hexdigest()
  s.sendall(b'HEAD / HTTP/1.0\\r\\nHost: https.lab\\r\\n\\r\\n');data=b''
  while len(data)<8192:
   part=s.recv(1024)
   if not part:break
   data+=part
  print(json.dumps({'leaf_der_sha256':digest,'version':s.version(),'status':data.decode('ascii').split('\\r\\n',1)[0]}))
'''


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeHTTPSIdentityLifecycleTests(unittest.TestCase):
    def test_offline_time_purpose_rejection_leaf_ca_rotation_and_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('nginx','openssl','busybox','crun','ip'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        with tempfile.TemporaryDirectory() as folder,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);(root/'first').mkdir();(root/'second').mkdir()
            certs=lifecycle_identities(root/'first');other=identities(root/'second')
            client=static_busybox_rootfs(shutil.which('busybox'),root/'client')
            def image(name,ca,cert,key):
                return static_busybox_rootfs(shutil.which('busybox'),root/name,nginx=shutil.which('nginx'),
                    https_ca=ca,https_certificate=cert,https_private_key=key)
            old=image('old',certs['ca'],certs['valid_cert'],certs['valid_key'])
            renewed=image('renewed',certs['ca'],certs['renewed_cert'],certs['renewed_key'])
            rotated=image('rotated',other['ca'],other['valid_cert'],other['valid_key'])
            initial_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for image_root in (old,renewed,rotated)
                            for p in (Path(image_root)/v.lstrip('/') for v in (CA,CERT,KEY))}
            self.assertNotEqual(initial_hashes[str(Path(old)/KEY.lstrip('/'))],initial_hashes[str(Path(renewed)/KEY.lstrip('/'))])
            name='https-lifecycle-'+str(os.getpid());manager=Manager(name)
            def specification(server):
                spec=https_lab(server,client);spec['name']=name;return spec
            def check(ca):
                with manager.locked():
                    return probe(manager,'PC2','192.0.2.10',protocol='https',ca_pem=ca.read_text())
            def healthy(ca,cert):
                until=time.monotonic()+8
                while '192.0.2.10:443' not in manager.ns(0,'ss','-H','-ltn','sport = :443').stdout:
                    if time.monotonic()>=until:self.fail('HTTPS listener unavailable')
                    time.sleep(.1)
                report=check(ca);self.assertEqual(report['status'],'passed',report)
                self.assertTrue(report['stages'][-1]['certificate_verified'])
                actual=json.loads(manager.ns(2,sys.executable,'-I','-c',PEER,input_text=json.dumps({'ca':ca.read_text()}),timeout=6).stdout)
                expected=hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
                self.assertEqual(actual['leaf_der_sha256'],expected)
                self.assertIn(actual['version'],('TLSv1.2','TLSv1.3'));self.assertIn(' 200 ',actual['status'])
                self.assertNotEqual(manager.crun('exec','PC2','/bin/busybox','cat',KEY,check=False).returncode,0)
                return actual['leaf_der_sha256']
            try:
                # Exercise preflight with correctly updated public pins too:
                # invalid local identities must fail before any lab allocation.
                invalid=root/'invalid';shutil.copytree(old,invalid)
                for identity,reason in (('expired','expired'),('future','not yet valid'),('client-only','unsuitable certificate purpose')):
                    (invalid/CERT.lstrip('/')).write_bytes(certs[identity+'_cert'].read_bytes())
                    with manager.locked(),self.assertRaisesRegex(RuntimeFailure,reason):manager.start(specification(invalid))
                    self.assertFalse(manager.directory.exists());self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
                (invalid/CERT.lstrip('/')).write_bytes(certs['valid_cert'].read_bytes())
                (invalid/CA.lstrip('/')).write_bytes(certs['wrong_ca'].read_bytes())
                with manager.locked(),self.assertRaisesRegex(RuntimeFailure,'certificate verify failed'):manager.start(specification(invalid))
                self.assertFalse(manager.directory.exists())
                old_spec=specification(old)
                with manager.locked():manager.start(old_spec)
                old_leaf=healthy(certs['ca'],certs['valid_cert'])
                with manager.locked():
                    manager.write_startup();saved_old=load_startup(name);self.assertEqual(saved_old,old_spec);manager.stop()
                # Repointing an old manifest at new assets cannot silently
                # change identity, even with a valid replacement chain/key.
                stale=copy.deepcopy(saved_old);stale['nodes'][0]['rootfs']=str(renewed)
                with manager.locked(),self.assertRaisesRegex(RuntimeFailure,'pins differ'):manager.start(stale)
                self.assertFalse(manager.directory.exists())
                renewal=specification(renewed)
                self.assertEqual(renewal['nodes'][0]['https_server']['ca_sha256'],old_spec['nodes'][0]['https_server']['ca_sha256'])
                self.assertNotEqual(renewal['nodes'][0]['https_server']['certificate_sha256'],old_spec['nodes'][0]['https_server']['certificate_sha256'])
                with manager.locked():manager.start(renewal)
                self.assertNotEqual(healthy(certs['ca'],certs['renewed_cert']),old_leaf)
                with manager.locked():manager.write_startup();manager.stop()
                replacement=specification(rotated)
                self.assertNotEqual(replacement['nodes'][0]['https_server']['ca_sha256'],old_spec['nodes'][0]['https_server']['ca_sha256'])
                with manager.locked():manager.start(replacement)
                healthy(other['ca'],other['valid_cert'])
                rejected=check(certs['ca']);self.assertEqual(rejected['status'],'failed',rejected)
                self.assertEqual(rejected['stages'][-1]['error'],'CERTIFICATE_VERIFY_FAILED')
                with manager.locked():
                    manager.write_startup();saved=load_startup(name);self.assertEqual(saved,replacement)
                    self.assertNotIn('PRIVATE KEY',json.dumps(saved));manager.stop();manager.start(saved)
                healthy(other['ca'],other['valid_cert']);self.assertEqual(check(certs['ca'])['status'],'failed')
                # Rollback is another explicit recreation with retained assets.
                with manager.locked():manager.stop();manager.start(saved_old)
                self.assertEqual(healthy(certs['ca'],certs['valid_cert']),old_leaf)
                self.assertEqual(check(other['ca'])['status'],'failed')
                for path,digest in initial_hashes.items():self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(),digest)
                with manager.locked():manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
