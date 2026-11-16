"""Real IPv6-only DNS over tagged ROAS and a two-router static path."""
from concurrent.futures import ThreadPoolExecutor
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
from network_labs.appliances.dns import start_servers
from network_labs.appliances.examples import ipv6_dns_subinterfaces_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from test_native_dual_stack_dns_integration import QUERY
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6DNSSubinterfaceTests(unittest.TestCase):
    def test_dns_tagged_wire_outage_isolation_drift_and_cold_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dnsmasq','crun','ip','busybox','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        forwarding=run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder)
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dnsmasq=shutil.which('dnsmasq'))
            spec=ipv6_dns_subinterfaces_lab(rootfs);spec['name']='ipv6-dns-roas-'+str(os.getpid());manager=Manager(spec['name'])
            def wait(predicate,label):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail(label)
            def query(tcp=False,kind=28,name='server.lab.test'):
                request=dict(family=6,tcp=tcp,kind=kind,name=name,source='2001:db8:10::10',server='2001:db8:30::10')
                return json.loads(manager.ns(0,sys.executable,'-I','-c',QUERY,json.dumps(request),timeout=4).stdout)
            def healthy():
                wait(lambda:query()['status']=='passed','IPv6 DNS path unavailable')
                for tcp in (False,True):
                    for kind,address in ((1,'192.0.2.10'),(28,'2001:db8:30::10')):
                        reply=query(tcp,kind);self.assertEqual(reply['status'],'passed',reply)
                        self.assertEqual(reply['rcode'],0);self.assertEqual(reply['addresses'],[address])
            def refuse():
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
            def local_delivery():
                wait(lambda:manager.crun('exec','PC1','/bin/busybox','ping6','-c','1','-W','1','2001:db8:10::20',check=False,timeout=4).returncode==0,'Unrelated same-VLAN traffic unavailable')
            try:
                with manager.locked():manager.start(spec)
                healthy()
                with manager.locked():
                    report=probe(manager,'PC1','server.lab.test',protocol='dns',family='ipv6',dns_transport='tcp')
                    self.assertEqual(report['status'],'passed',report)
                for index in (0,3,5,6):
                    rows=json.loads(manager.ns(index,'ip','-j','-4','addr','show').stdout)
                    self.assertFalse([a for r in rows if r['ifname']!='lo' for a in r['addr_info'] if a['family']=='inet'])
                sockets=manager.ns(3,'ss','-H','-lntu','sport = :53').stdout
                self.assertEqual(len(sockets.splitlines()),2);self.assertIn('[2001:db8:30::10]:53',sockets)
                self.assertEqual(query(name='missing.lab.test')['rcode'],3)
                event=threading.Event();wire=root/'dns-roas.pcap'
                cap=pool.submit(capture,Manager(spec['name']),'R1','eth0',wire,seconds=6,packets=500,ready=event.set)
                self.assertTrue(event.wait(5));healthy();cap.result(timeout=10)
                for vlan in (10,100):
                    for transport in ('udp','tcp'):
                        self.assertTrue(run(['tcpdump','-nn','-r',wire,'vlan',str(vlan),'and','ip6','and',transport,'port','53']).stdout)
                manager.crun('exec','PC4','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/dnsmasq.pid)"')
                wait(lambda:not manager.ns(3,'ss','-H','-lntu','sport = :53').stdout,'DNS did not stop')
                self.assertEqual(query()['status'],'failed');self.assertEqual(query(True)['status'],'failed');local_delivery()
                start_servers(manager);healthy()
                manager.ns(5,'ip','-6','route','del','2001:db8:30::/64')
                self.assertEqual(query()['status'],'failed');local_delivery();refuse()
                manager.ns(5,'ip','-6','route','add','2001:db8:30::/64','via','2001:db8:100::2','dev','eth0.100','proto','static');healthy()
                manager.ns(4,'bridge','vlan','del','dev','eth3','vid','100')
                self.assertEqual(query(True)['status'],'failed');local_delivery();refuse()
                manager.ns(4,'bridge','vlan','add','dev','eth3','vid','100');healthy()
                config=manager.directory/'PC4/files/dnsmasq.conf';original=config.read_text()
                config.write_text(original+'# external drift\n');refuse();config.write_text(original)
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    manager.stop();manager.start(saved)
                healthy()
                with manager.locked():manager.write_startup()
                # A genuine AAAA-only zone requires no manufactured IPv4 data.
                only=json.loads(json.dumps(saved));only['nodes'][3]['dns_server']['records']={}
                with manager.locked():manager.stop();manager.start(only)
                def only_aaaa():
                    wait(lambda:query()['status']=='passed','AAAA-only IPv6 DNS unavailable')
                    for tcp in (False,True):
                        answer=query(tcp,28);self.assertEqual(answer['addresses'],['2001:db8:30::10'])
                        empty=query(tcp,1);self.assertEqual(empty['status'],'passed',empty)
                        self.assertEqual(empty['rcode'],0);self.assertEqual(empty['addresses'],[])
                    with manager.locked():
                        self.assertEqual(probe(manager,'PC1','server.lab.test',protocol='dns',family='ipv6',dns_transport='tcp')['status'],'passed')
                only_aaaa()
                with manager.locked():
                    manager.write_startup();saved_only=load_startup(spec['name'])
                    self.assertEqual(saved_only['nodes'][3]['dns_server']['records'],{})
                    manager.stop();manager.start(saved_only)
                only_aaaa()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        self.assertEqual(run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout,forwarding)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
