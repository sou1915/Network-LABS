"""Real persistent guest HTTPS, explicit client trust, method/path results and cold restore."""
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
from https_test_identity import identities
from network_labs.appliances.capture import capture
from network_labs.appliances.examples import https_lab
from network_labs.appliances.https_server import CA,CERT,KEY,PID,BODY,start_server
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from test_native_integration import unexpected_host_link_changes

REQUEST='''import json,socket,ssl,sys
r=json.load(sys.stdin);c=ssl.create_default_context(cafile=r['ca']);c.minimum_version=ssl.TLSVersion.TLSv1_2
with socket.create_connection(('192.0.2.10',443),3) as raw:
 with c.wrap_socket(raw,server_hostname=r['name']) as s:
  s.sendall((r['method']+' / HTTP/1.0\\r\\nHost: '+r['name']+'\\r\\n\\r\\n').encode());data=b''
  while len(data)<8192:
   part=s.recv(1024)
   if not part:break
   data+=part
  print(json.dumps({'verified':True,'version':s.version(),'response':data.decode('ascii')}))
'''


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeHTTPSServerTests(unittest.TestCase):
    def test_persistent_verified_https_rejection_drift_outage_and_cold_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('nginx','openssl','busybox','crun','ip','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);certs=identities(root);client=static_busybox_rootfs(shutil.which('busybox'),root/'client')
            for identity in ('valid','wrong'):
                with self.subTest(identity=identity):
                    server=static_busybox_rootfs(shutil.which('busybox'),root/('server-'+identity),nginx=shutil.which('nginx'),https_ca=certs['ca'],https_certificate=certs[identity+'_cert'],https_private_key=certs[identity+'_key'])
                    spec=https_lab(server,client);spec['name']='https-'+str(os.getpid())+'-'+identity;manager=Manager(spec['name'])
                    def wait(predicate,label,seconds=8):
                        until=time.monotonic()+seconds
                        while time.monotonic()<until:
                            if predicate():return
                            time.sleep(.1)
                        p=manager.directory/'PC1/https.log';self.fail(label+': '+(p.read_text(errors='replace') if p.exists() else 'no log'))
                    def ready():
                        wait(lambda:'192.0.2.10:443' in manager.ns(0,'ss','-H','-ltn','sport = :443').stdout,'HTTPS listener unavailable')
                        self.assertFalse(manager.ns(0,'ss','-H','-ltn','sport = :80').stdout,'No plaintext fallback listener expected')
                    def check(ca=certs['ca'],path='/'):
                        return probe(manager,'PC2','192.0.2.10',protocol='https',ca_pem=ca.read_text(),path=path)
                    def request(method='GET',name='https.lab'):
                        result=manager.ns(2,sys.executable,'-I','-c',REQUEST,input_text=json.dumps({'ca':str(certs['ca']),'name':name,'method':method}),timeout=6)
                        return json.loads(result.stdout)
                    try:
                        with manager.locked():manager.start(spec)
                        ready()
                        self.assertNotEqual(manager.crun('exec','SW1','/bin/busybox','cat',KEY,check=False).returncode,0)
                        if identity=='wrong':
                            denied=check();self.assertEqual(denied['status'],'failed',denied)
                            self.assertEqual(denied['stages'][-1]['error'],'CERTIFICATE_VERIFY_FAILED',denied)
                            self.assertIn('200',request(name='wrong.lab')['response'].split('\r\n',1)[0]);continue
                        state=copy.deepcopy(manager.read());event=threading.Event();pcap=root/'https.pcap'
                        future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=5,packets=1000,expression='tcp port 443',ready=event.set)
                        self.assertTrue(event.wait(5))
                        for _ in range(3):
                            result=check();self.assertEqual(result['status'],'passed',result);self.assertTrue(result['stages'][-1]['certificate_verified'])
                        actual=request();self.assertIn(actual['version'],('TLSv1.2','TLSv1.3'));self.assertIn(BODY.replace('\\n','\n'),actual['response'])
                        self.assertIn('405',request('POST')['response'].split('\r\n',1)[0])
                        missing=check(path='/missing');self.assertEqual(missing['status'],'failed');self.assertEqual(missing['stages'][-1]['http_status'],404)
                        denied=check(certs['wrong_ca']);self.assertEqual(denied['status'],'failed');self.assertEqual(denied['stages'][-1]['error'],'CERTIFICATE_VERIFY_FAILED')
                        future.result(timeout=8);self.assertNotIn(b'Network LABS HTTPS ready',pcap.read_bytes())
                        processes=manager.crun('exec','PC1','/bin/busybox','ps','-o','user,args').stdout
                        self.assertTrue(any(line.lstrip().startswith('https ') and 'nginx: worker process' in line for line in processes.splitlines()),processes)
                        self.assertEqual(manager.read(),state)
                        with manager.locked():
                            config=manager.directory/'PC1/files/https.conf';original=config.read_text();config.write_text(original+'# drift\n')
                            with self.assertRaises(RuntimeFailure):manager.write_startup()
                            config.write_text(original);manager.crun('exec','PC1','/bin/busybox','chmod','644',KEY)
                            with self.assertRaises(RuntimeFailure):manager.write_startup()
                            manager.crun('exec','PC1','/bin/busybox','chmod','600',KEY)
                            manager.crun('exec','PC1','/bin/sh','-c','printf altered > '+CA)
                            with self.assertRaises(RuntimeFailure):manager.write_startup()
                            manager.crun('exec','PC1','/bin/sh','-c','cat > '+CA,input_text=certs['ca'].read_text())
                            manager.crun('exec','PC1','/bin/sh','-c','/bin/kill -QUIT "$(/bin/cat '+PID+')"')
                            wait(lambda:not manager.ns(0,'ss','-H','-ltn','sport = :443').stdout,'Stopped HTTPS still listens')
                            wait(lambda:manager.crun('exec','PC1','/bin/busybox','test','-e',PID,check=False).returncode!=0,'Master did not remove PID file')
                            self.assertTrue(manager.inspect('PC1')['https_server']['configuration_verified'])
                            self.assertEqual(check()['status'],'failed')
                            start_server(manager,spec['nodes'][0]);ready();self.assertEqual(check()['status'],'passed')
                            manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec);self.assertNotIn('PRIVATE KEY',json.dumps(saved))
                            manager.stop();manager.start(saved)
                        ready();self.assertEqual(check()['status'],'passed')
                        with manager.locked():manager.write_startup()
                    finally:
                        if manager.directory.exists():
                            with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
