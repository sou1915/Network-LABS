"""Real IPv6 DNS/TFTP coexistence, independent faults and cold restoration."""
from concurrent.futures import ThreadPoolExecutor
import base64
import copy
import hashlib
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
from network_labs.appliances.dns import start_servers as start_dns
from network_labs.appliances.examples import ipv6_dns_tftp_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from network_labs.appliances.tftp import read
from network_labs.appliances.tftp_server import start_servers as start_tftp
from test_native_dual_stack_dns_integration import QUERY
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6DNSTFTPTests(unittest.TestCase):
    def test_separate_services_tagged_wire_independent_faults_and_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dnsmasq','crun','ip','busybox','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        forwarding=run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=3) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dnsmasq=shutil.which('dnsmasq'))
            payloads={'empty':b'','exact':bytes(range(256))*8,'max':bytes(range(256))*256,'tail':b'\x00\xffDNS+TFTP'*200}
            spec=ipv6_dns_tftp_lab(rootfs,files={n:{'base64':base64.b64encode(v).decode()} for n,v in payloads.items()})
            spec['name']='ipv6-dns-tftp-'+str(os.getpid());manager=Manager(spec['name'])
            def wait(predicate,label):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail(label)
            def query(tcp=False,kind=28,name='files.lab.test'):
                request=dict(family=6,tcp=tcp,kind=kind,name=name,source='2001:db8:10::10',server='2001:db8:30::10')
                return json.loads(manager.ns(0,sys.executable,'-I','-c',QUERY,json.dumps(request),timeout=4).stdout)
            def dns_healthy():
                wait(lambda:query()['status']=='passed','DNS path unavailable')
                for tcp in (False,True):
                    answer=query(tcp);self.assertEqual(answer['status'],'passed',answer)
                    self.assertEqual(answer['addresses'],['2001:db8:20::10']);self.assertEqual(answer['rcode'],0)
                    empty=query(tcp,1);self.assertEqual(empty['rcode'],0);self.assertEqual(empty['addresses'],[])
                with manager.locked():
                    report=probe(manager,'PC1','files.lab.test',protocol='dns',family='ipv6',dns_transport='tcp')
                self.assertEqual(report['status'],'passed',report)
            def transfer(name='exact',size=1024,timeout=3):
                return read(manager,'PC1','2001:db8:20::10',name,family='ipv6',timeout=timeout,block_size=size,
                            expected_sha256=hashlib.sha256(payloads[name]).hexdigest())
            def tftp_healthy(name='exact',size=1024):
                result=transfer(name,size);self.assertEqual(result['status'],'passed',result)
                self.assertTrue(result['hash_matches']);self.assertEqual(result['transfer']['bytes_received'],len(payloads[name]))
                self.assertEqual(result['transfer']['block_size'],size or 512)
                self.assertEqual(result['transfer']['option_negotiated'],size is not None)
            def refuse():
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
            def local_delivery():
                wait(lambda:manager.crun('exec','PC1','/bin/busybox','ping6','-c','1','-W','1','2001:db8:10::20',check=False,timeout=4).returncode==0,'Same-VLAN control unavailable')
            try:
                with manager.locked():manager.start(spec)
                dns_healthy();wait(lambda:transfer('empty')['status']=='passed','TFTP unavailable');tftp_healthy()
                for index in range(7):
                    rows=json.loads(manager.ns(index,'ip','-j','-4','addr','show').stdout)
                    self.assertFalse([a for r in rows if r['ifname']!='lo' for a in r['addr_info'] if a['family']=='inet'])
                self.assertEqual(len(manager.ns(3,'ss','-H','-lntu','sport = :53').stdout.splitlines()),2)
                self.assertFalse(manager.ns(2,'ss','-H','-lntu','sport = :53').stdout)
                self.assertIn(':69',manager.ns(2,'ss','-H','-lun','sport = :69').stdout)
                self.assertFalse(manager.ns(3,'ss','-H','-lun','sport = :69').stdout)
                state=copy.deepcopy(manager.read());event=threading.Event();wire=root/'services.pcap'
                cap=pool.submit(capture,Manager(spec['name']),'R1','eth0',wire,seconds=6,packets=1000,ready=event.set)
                self.assertTrue(event.wait(5))
                dns_future=pool.submit(dns_healthy);tftp_future=pool.submit(tftp_healthy)
                dns_future.result(timeout=12);tftp_future.result(timeout=8);cap.result(timeout=10)
                for vlan in (10,100):
                    for transport in ('udp','tcp'):
                        for direction in ('src','dst'):
                            self.assertTrue(run(['tcpdump','-nn','-r',wire,'vlan',str(vlan),'and','ip6','and',transport,'port','53','and',direction,'host','2001:db8:30::10']).stdout)
                for vlan in (10,20):
                    for direction in ('src','dst'):
                        self.assertTrue(run(['tcpdump','-nn','-r',wire,'vlan',str(vlan),'and','ip6','and','udp','and',direction,'host','2001:db8:20::10']).stdout)
                for name,size in (('empty',None),('tail',512),('max',1428)):tftp_healthy(name,size)
                self.assertEqual(query(name='missing.lab.test')['rcode'],3)
                self.assertEqual(manager.read(),state)
                # DNS loss is isolated: literal-address TFTP needs no resolver.
                manager.crun('exec','PC4','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/dnsmasq.pid)"')
                wait(lambda:not manager.ns(3,'ss','-H','-lntu','sport = :53').stdout,'DNS did not stop')
                for tcp in (False,True):self.assertEqual(query(tcp)['status'],'failed')
                tftp_healthy();local_delivery()
                with manager.locked():
                    self.assertNotEqual(probe(manager,'PC1','files.lab.test',protocol='dns',family='ipv6')['status'],'passed')
                start_dns(manager);dns_healthy();tftp_healthy()
                # TFTP loss is isolated: AAAA lookup still describes the host.
                manager.crun('exec','PC3','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/tftp-dnsmasq.pid)"')
                wait(lambda:not manager.ns(2,'ss','-H','-lun','sport = :69').stdout,'TFTP did not stop')
                self.assertEqual(transfer(timeout=1)['status'],'failed');dns_healthy();local_delivery()
                start_tftp(manager);wait(lambda:transfer('empty')['status']=='passed','TFTP recovery failed');tftp_healthy()
                # Separate routed paths: root's subnet route versus file VLAN.
                manager.ns(5,'ip','-6','route','del','2001:db8:30::/64')
                self.assertEqual(query()['status'],'failed');tftp_healthy();local_delivery();refuse()
                manager.ns(5,'ip','-6','route','add','2001:db8:30::/64','via','2001:db8:100::2','dev','eth0.100','proto','static');dns_healthy()
                manager.ns(4,'bridge','vlan','del','dev','eth3','vid','20')
                self.assertEqual(transfer(timeout=1)['status'],'failed');dns_healthy();local_delivery();refuse()
                manager.ns(4,'bridge','vlan','add','dev','eth3','vid','20');tftp_healthy()
                for relative in ('PC4/files/dnsmasq.conf','PC3/files/tftp-server.conf'):
                    config=manager.directory/relative;original=config.read_text()
                    config.write_text(original+'# external drift\n');refuse();config.write_text(original)
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    manager.stop();manager.start(saved)
                dns_healthy();wait(lambda:transfer('empty')['status']=='passed','Cold-restored TFTP unavailable');tftp_healthy('max',1428)
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
