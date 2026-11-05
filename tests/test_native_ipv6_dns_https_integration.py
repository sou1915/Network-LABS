"""Real separate IPv6 DNS/TLS services, independent outages and saved restore."""
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
from network_labs.appliances.dns import start_servers as start_dns
from network_labs.appliances.examples import ipv6_dns_https_lab
from network_labs.appliances.https_server import BODY,PID,start_server
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from test_native_integration import unexpected_host_link_changes
from test_native_ipv6_https_integration import REQUEST


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6DNSHTTPSTests(unittest.TestCase):
    def test_dns_named_tls_independent_service_loss_drift_and_cold_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('nginx','dnsmasq','openssl','busybox','crun','ip','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        forwarding=run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);certs=identities(root,valid_ip='2001:db8:20::20',valid_name='secure.lab.test')
            client=static_busybox_rootfs(shutil.which('busybox'),root/'client',dnsmasq=shutil.which('dnsmasq'))
            server=static_busybox_rootfs(shutil.which('busybox'),root/'server',nginx=shutil.which('nginx'),
                https_ca=certs['ca'],https_certificate=certs['valid_cert'],https_private_key=certs['valid_key'])
            spec=ipv6_dns_https_lab(server,client);spec['name']='ipv6-dns-https-'+str(os.getpid());manager=Manager(spec['name'])
            def wait(predicate,label):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail(label)
            def query(target='secure.lab.test',protocol='https',transport='udp',ca=certs['ca']):
                with manager.locked():
                    return probe(manager,'PC1',target,protocol=protocol,family='ipv6',dns_transport=transport,
                        **({'ca_pem':ca.read_text()} if protocol=='https' else {}),timeout=1)
            def healthy():
                wait(lambda:query()['status']=='passed','Named IPv6 HTTPS unavailable')
                for transport in ('udp','tcp'):
                    result=query(transport=transport);self.assertEqual(result['status'],'passed',result)
                    self.assertTrue(result['stages'][-1]['certificate_verified'])
                    self.assertEqual(result['address_family'],'ipv6')
                    self.assertEqual(result['dns_endpoint']['address'],'2001:db8:10::10')
            def request(name='secure.lab.test'):
                return manager.ns(0,sys.executable,'-I','-c',REQUEST,input_text=json.dumps(
                    {'ca':str(certs['ca']),'source':'2001:db8:10::10','method':'GET','name':name}),timeout=6,check=False)
            def pid(node,path):return manager.crun('exec',node,'/bin/busybox','cat',path).stdout
            def refuse():
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
            try:
                with manager.locked():manager.start(spec)
                healthy();state=copy.deepcopy(manager.read())
                tls_pid=pid('PC2',PID);dns_pid=pid('PC3','/run/dnsmasq.pid')
                for index in range(5):
                    rows=json.loads(manager.ns(index,'ip','-j','-4','addr','show').stdout)
                    self.assertFalse([a for row in rows if row['ifname']!='lo' for a in row['addr_info'] if a['family']=='inet'])
                event=threading.Event();wire=root/'dns-tls.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',wire,seconds=4,packets=1000,
                    expression='ip6 and (port 53 or tcp port 443)',ready=event.set)
                self.assertTrue(event.wait(5));healthy()
                actual=request();self.assertEqual(actual.returncode,0,actual.stderr)
                self.assertIn(BODY.replace('\\n','\n'),json.loads(actual.stdout)['response'])
                future.result(timeout=8)
                for transport in ('udp','tcp'):
                    decoded=run(['tcpdump','-nn','-r',wire,'ip6','and',transport,'port','53']).stdout
                    self.assertIn('2001:db8:30::30.53',decoded);self.assertIn('secure.lab.test',decoded)
                self.assertIn('2001:db8:20::20.443',run(['tcpdump','-nn','-r',wire,'tcp','port','443']).stdout)
                self.assertNotIn(b'Network LABS HTTPS ready',wire.read_bytes())
                denied=query(ca=certs['wrong_ca']);self.assertEqual(denied['status'],'failed',denied)
                self.assertEqual(denied['stages'][-1]['error'],'CERTIFICATE_VERIFY_FAILED',denied)
                wrong=request('wrong.lab.test');self.assertNotEqual(wrong.returncode,0);self.assertIn('CERTIFICATE_VERIFY_FAILED',wrong.stderr)
                missing=query('missing.lab.test');self.assertEqual(missing['status'],'failed',missing)
                self.assertEqual(missing['stages'][-1]['stage'],'dns')
                # DNS loss breaks named HTTPS, while literal verified TLS survives.
                manager.crun('exec','PC3','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/dnsmasq.pid)"')
                wait(lambda:not manager.ns(4,'ss','-H','-lntu','sport = :53').stdout,'DNS did not stop')
                for transport in ('udp','tcp'):
                    failed=query(transport=transport);self.assertEqual(failed['status'],'failed',failed)
                    self.assertEqual(failed['stages'][-1]['stage'],'dns')
                self.assertEqual(query('2001:db8:20::20')['status'],'passed')
                self.assertEqual(pid('PC2',PID),tls_pid);start_dns(manager);healthy()
                # HTTPS loss leaves real DNS service and named AAAA answers working.
                dns_pid=pid('PC3','/run/dnsmasq.pid')
                manager.crun('exec','PC2','/bin/sh','-c','/bin/kill -QUIT "$(/bin/cat '+PID+')"')
                wait(lambda:manager.crun('exec','PC2','/bin/busybox','test','-e',PID,check=False).returncode!=0,'HTTPS master did not exit')
                for transport in ('udp','tcp'):
                    self.assertEqual(query(protocol='dns',transport=transport)['status'],'passed')
                    failed=query(transport=transport);self.assertEqual(failed['status'],'failed',failed)
                    self.assertNotEqual(failed['stages'][-1]['stage'],'dns')
                self.assertEqual(pid('PC3','/run/dnsmasq.pid'),dns_pid)
                start_server(manager,spec['nodes'][3]);healthy()
                for node,path in (('PC3','dnsmasq.conf'),('PC2','https.conf'),('PC1','resolv.conf')):
                    config=manager.directory/node/'files'/path;original=config.read_text();config.write_text(original+'# drift\n')
                    refuse();config.write_text(original)
                self.assertEqual(manager.read(),state)
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    self.assertNotIn('PRIVATE KEY',json.dumps(saved));manager.stop();manager.start(saved)
                healthy();self.assertEqual(query('missing.lab.test')['status'],'failed')
                self.assertTrue(manager.inspect('PC2')['https_server']['configuration_verified'])
                self.assertTrue(manager.inspect('PC3')['dns_server']['configuration_verified'])
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
