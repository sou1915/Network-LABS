"""Real IPv6 DNS over OSPFv3, independent faults and route-free cold restore."""
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
from network_labs.appliances.examples import ipv6_dns_ospfv3_lab
from network_labs.appliances.ospf import start_one,stop_one
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from test_native_dual_stack_dns_integration import QUERY
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6DNSOSPFv3Tests(unittest.TestCase):
    def test_dns_dynamic_routes_wire_independent_failures_and_cold_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('bird','birdc','dnsmasq','crun','ip','busybox','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        forwarding=run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',
                bird=shutil.which('bird'),birdc=shutil.which('birdc'),dnsmasq=shutil.which('dnsmasq'))
            spec=ipv6_dns_ospfv3_lab(rootfs);spec['name']='ipv6-dns-ospf-'+str(os.getpid());manager=Manager(spec['name'])
            def wait(predicate,label):
                until=time.monotonic()+25
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.2)
                self.fail(label)
            def remote(index):
                prefix='2001:db8:20::/64' if index==1 else '2001:db8:10::/64'
                return [r for r in json.loads(manager.ns(index,'ip','-j','-6','route','show').stdout) if r.get('dst')==prefix]
            def routes_healthy():
                for index in (1,2):
                    wait(lambda:'Full' in (manager.inspect('R'+str(index))['ospfv3']['neighbors'] or ''),'OSPFv3 adjacency unavailable')
                    wait(lambda:bool(remote(index)),'OSPFv3 remote route unavailable')
                    row=remote(index)[0];self.assertIn(row.get('protocol'),('bird',192,'192'))
                    self.assertTrue(row.get('gateway','').startswith('fe80:'),row)
            def query(tcp=False,kind=28,name='server.lab.test',local=False):
                request=dict(family=6,tcp=tcp,kind=kind,name=name,source='2001:db8:20::1' if local else '2001:db8:10::10',server='2001:db8:20::20')
                return json.loads(manager.ns(2 if local else 0,sys.executable,'-I','-c',QUERY,json.dumps(request),timeout=4).stdout)
            def dns_healthy():
                wait(lambda:query()['status']=='passed','DNS over OSPFv3 unavailable')
                for tcp in (False,True):
                    answer=query(tcp);self.assertEqual(answer['status'],'passed',answer)
                    self.assertEqual(answer['addresses'],['2001:db8:20::20']);self.assertEqual(answer['rcode'],0)
                    empty=query(tcp,1);self.assertEqual(empty['rcode'],0);self.assertEqual(empty['addresses'],[])
                with manager.locked():
                    report=probe(manager,'PC1','server.lab.test',protocol='dns',family='ipv6',dns_transport='tcp')
                self.assertEqual(report['status'],'passed',report)
            def healthy():routes_healthy();dns_healthy()
            def refuse():
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
            try:
                with manager.locked():manager.start(spec)
                healthy()
                for index in range(4):
                    rows=json.loads(manager.ns(index,'ip','-j','-4','addr','show').stdout)
                    self.assertFalse([a for r in rows if r['ifname']!='lo' for a in r['addr_info'] if a['family']=='inet'])
                self.assertEqual(query(name='missing.lab.test')['rcode'],3)
                event=threading.Event();wire=root/'ospf-dns.pcap'
                cap=pool.submit(capture,Manager(spec['name']),'R1','eth1',wire,seconds=6,packets=1000,ready=event.set)
                self.assertTrue(event.wait(5));dns_healthy();cap.result(timeout=10)
                ospf=run(['tcpdump','-nn','-vv','-r',wire,'ip6','proto','89']).stdout
                self.assertIn('OSPFv3',ospf)
                for transport in ('udp','tcp'):
                    for direction in ('src','dst'):
                        self.assertTrue(run(['tcpdump','-nn','-r',wire,'ip6','and',transport,'port','53','and',direction,'host','2001:db8:20::20']).stdout)
                # A stopped DNS process must not look like lost OSPF routing.
                manager.crun('exec','PC2','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/dnsmasq.pid)"')
                wait(lambda:not manager.ns(3,'ss','-H','-lntu','sport = :53').stdout,'DNS listener did not stop')
                for tcp in (False,True):self.assertEqual(query(tcp)['status'],'failed')
                routes_healthy()
                self.assertEqual(manager.crun('exec','PC1','/bin/busybox','ping6','-c','1','-W','1','2001:db8:20::20',check=False,timeout=4).returncode,0)
                start_servers(manager);dns_healthy()
                # Withdraw the learned route while the independently reachable
                # server remains live on R2's directly connected LAN.
                stop_one(manager,spec['nodes'][2]);wait(lambda:not remote(1),'Dead OSPF peer route did not withdraw')
                for tcp in (False,True):
                    self.assertEqual(query(tcp)['status'],'failed')
                    local=query(tcp,local=True);self.assertEqual(local['status'],'passed',local)
                    self.assertEqual(local['addresses'],['2001:db8:20::20'])
                self.assertIn('configuration_verified',manager.inspect('PC2')['dns_server'])
                self.assertTrue(manager.inspect('PC2')['dns_server']['configuration_verified'])
                start_one(manager,spec['nodes'][2]);healthy()
                manager.ns(1,'ip','-6','route','add','2001:db8:99::/64','via','2001:db8:100::2','dev','eth1','proto','static');refuse()
                manager.ns(1,'ip','-6','route','del','2001:db8:99::/64')
                for relative in ('PC2/files/dnsmasq.conf','R1/files/bird.conf'):
                    config=manager.directory/relative;text=config.read_text();config.write_text(text+'# drift\n');refuse();config.write_text(text)
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    self.assertTrue(all(n['ipv6_routes']==[] for n in saved['nodes'][1:3]));manager.stop();manager.start(saved)
                healthy()
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
