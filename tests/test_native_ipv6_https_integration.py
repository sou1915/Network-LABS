"""Persistent guest IPv6 HTTPS across two routers, faults and cold restore."""
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
from network_labs.appliances.examples import ipv6_https_lab
from network_labs.appliances.https_server import BODY,PID,start_server
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from test_native_integration import unexpected_host_link_changes

REQUEST='''import json,socket,ssl,sys
r=json.load(sys.stdin);c=ssl.create_default_context(cafile=r['ca']);c.minimum_version=ssl.TLSVersion.TLSv1_2
with socket.socket(socket.AF_INET6,socket.SOCK_STREAM) as raw:
 raw.settimeout(3);raw.bind((r['source'],0));raw.connect(('2001:db8:20::20',443))
 with c.wrap_socket(raw,server_hostname=r['name']) as s:
  s.sendall((r['method']+' / HTTP/1.0\\r\\nHost: '+r['name']+'\\r\\n\\r\\n').encode());data=b''
  while len(data)<8192:
   part=s.recv(1024)
   if not part:break
   data+=part
  print(json.dumps({'version':s.version(),'response':data.decode('ascii')}))
'''


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6HTTPSTests(unittest.TestCase):
    def test_routed_ipv6_https_trust_wire_independent_faults_and_cold_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('nginx','openssl','busybox','crun','ip','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        forwarding=run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);certs=identities(root,valid_ip='2001:db8:20::20')
            client=static_busybox_rootfs(shutil.which('busybox'),root/'client')
            server=static_busybox_rootfs(shutil.which('busybox'),root/'server',nginx=shutil.which('nginx'),
                https_ca=certs['ca'],https_certificate=certs['valid_cert'],https_private_key=certs['valid_key'])
            spec=ipv6_https_lab(server,client);spec['name']='ipv6-https-'+str(os.getpid());manager=Manager(spec['name'])
            def wait(predicate,label):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail(label)
            def query(ca=certs['ca'],path='/'):
                return probe(manager,'PC1','2001:db8:20::20',protocol='https',family='ipv6',ca_pem=ca.read_text(),path=path,timeout=2)
            def passed():
                result=query();self.assertEqual(result['status'],'passed',result)
                self.assertEqual(result['address_family'],'ipv6');self.assertTrue(result['stages'][-1]['certificate_verified'])
            def request(index=0,source='2001:db8:10::10',method='GET',name='https.lab'):
                return manager.ns(index,sys.executable,'-I','-c',REQUEST,input_text=json.dumps(
                    {'ca':str(certs['ca']),'source':source,'method':method,'name':name}),timeout=6,check=False)
            def pid():return manager.crun('exec','PC2','/bin/busybox','cat',PID).stdout
            try:
                with manager.locked():manager.start(spec)
                wait(lambda:query()['status']=='passed','IPv6 HTTPS unavailable')
                passed();state=copy.deepcopy(manager.read());initial_pid=pid()
                sockets=manager.ns(3,'ss','-H','-ltn','sport = :443').stdout
                self.assertIn('[2001:db8:20::20]:443',sockets)
                self.assertFalse(manager.ns(3,'ss','-4','-H','-ltn','sport = :443').stdout)
                self.assertFalse(manager.ns(3,'ss','-H','-ltn','sport = :80').stdout)
                for index in range(4):
                    rows=json.loads(manager.ns(index,'ip','-j','-4','addr','show').stdout)
                    self.assertFalse([a for row in rows if row['ifname']!='lo' for a in row['addr_info'] if a['family']=='inet'])
                event=threading.Event();wire=root/'https6.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',wire,seconds=3,packets=1000,expression='ip6 and tcp port 443',ready=event.set)
                self.assertTrue(event.wait(5));passed()
                actual=request();self.assertEqual(actual.returncode,0,actual.stderr)
                response=json.loads(actual.stdout);self.assertIn(response['version'],('TLSv1.2','TLSv1.3'))
                self.assertIn(BODY.replace('\\n','\n'),response['response'])
                self.assertIn('405',json.loads(request(method='POST').stdout)['response'].split('\r\n',1)[0])
                future.result(timeout=7)
                decoded=run(['tcpdump','-nn','-r',wire]).stdout
                self.assertIn('2001:db8:10::10',decoded);self.assertIn('2001:db8:20::20.443',decoded)
                self.assertNotIn(b'Network LABS HTTPS ready',wire.read_bytes())
                for ca in (certs['wrong_ca'],):
                    denied=query(ca);self.assertEqual(denied['status'],'failed',denied)
                    self.assertEqual(denied['stages'][-1]['error'],'CERTIFICATE_VERIFY_FAILED',denied)
                wrong_name=request(name='wrong.lab');self.assertNotEqual(wrong_name.returncode,0)
                self.assertIn('CERTIFICATE_VERIFY_FAILED',wrong_name.stderr)
                missing=query(path='/missing');self.assertEqual(missing['stages'][-1]['http_status'],404)
                # Routing loss leaves the same server alive and locally reachable.
                manager.ns(1,'sysctl','-w','net/ipv6/conf/all/forwarding=0')
                self.assertEqual(query()['status'],'failed')
                local=request(index=2,source='2001:db8:20::1');self.assertEqual(local.returncode,0,local.stderr)
                self.assertEqual(pid(),initial_pid)
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                manager.ns(1,'sysctl','-w','net/ipv6/conf/all/forwarding=1');passed()
                # Service loss leaves routed ICMPv6 working; no automatic restart.
                manager.crun('exec','PC2','/bin/sh','-c','/bin/kill -QUIT "$(/bin/cat '+PID+')"')
                wait(lambda:manager.crun('exec','PC2','/bin/busybox','test','-e',PID,check=False).returncode!=0,'HTTPS master did not exit')
                self.assertEqual(query()['status'],'failed')
                self.assertEqual(manager.ns(0,'ping','-6','-c','1','-W','2','2001:db8:20::20',check=False).returncode,0)
                self.assertTrue(manager.inspect('PC2')['https_server']['configuration_verified'])
                start_server(manager,spec['nodes'][3]);wait(lambda:query()['status']=='passed','Explicit HTTPS restart failed')
                config=manager.directory/'PC2/files/https.conf';original=config.read_text();config.write_text(original+'# drift\n')
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                config.write_text(original);self.assertEqual(manager.read(),state)
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    self.assertNotIn('PRIVATE KEY',json.dumps(saved));manager.stop();manager.start(saved)
                wait(lambda:query()['status']=='passed','Cold restored IPv6 HTTPS unavailable');passed()
                self.assertTrue(manager.inspect('PC2')['https_server']['configuration_verified'])
                with manager.locked():manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        self.assertEqual(run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout,forwarding)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
