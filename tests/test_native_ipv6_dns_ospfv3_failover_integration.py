"""Real OSPFv3 DNS failover under carrier-up bidirectional IPv6 blackholes."""
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
from network_labs.appliances.examples import ipv6_dns_ospfv3_failover_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from test_native_dual_stack_dns_integration import QUERY
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6DNSOSPFv3FailoverTests(unittest.TestCase):
    def test_costed_failover_failback_total_loss_and_restore_without_static_fallback(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('bird','birdc','dnsmasq','crun','ip','tc','busybox','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        forwarding=run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=2) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',bird=shutil.which('bird'),birdc=shutil.which('birdc'),dnsmasq=shutil.which('dnsmasq'))
            spec=ipv6_dns_ospfv3_failover_lab(rootfs);spec['name']='dns-ospf-failover-'+str(os.getpid());manager=Manager(spec['name'])
            paths={'primary':((1,'eth1'),(2,'eth0')),'backup':((1,'eth2'),(2,'eth2'))};blocked=set()
            def wait(predicate,label):
                until=time.monotonic()+25
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.2)
                self.fail(label)
            def remote(index):
                prefix='2001:db8:20::/64' if index==1 else '2001:db8:10::/64'
                return [r for r in json.loads(manager.ns(index,'ip','-j','-6','route','show').stdout) if r.get('dst')==prefix]
            def selected(path,neighbors):
                for index,port in paths[path]:
                    wait(lambda:bool(remote(index)) and remote(index)[0].get('dev')==port,'OSPF did not select '+path)
                    row=remote(index)[0];self.assertIn(row.get('protocol'),('bird',192,'192'));self.assertTrue(row.get('gateway','').startswith('fe80:'),row)
                    wait(lambda:(manager.inspect('R'+str(index))['ospfv3']['neighbors'] or '').count('Full')>=neighbors,'OSPF adjacencies unavailable')
            def query(tcp=False,local=False):
                request=dict(family=6,tcp=tcp,kind=28,name='server.lab.test',source='2001:db8:20::1' if local else '2001:db8:10::10',server='2001:db8:20::20')
                return json.loads(manager.ns(2 if local else 0,sys.executable,'-I','-c',QUERY,json.dumps(request),timeout=4).stdout)
            def dns_healthy():
                wait(lambda:query()['status']=='passed','DNS did not recover')
                for tcp in (False,True):
                    reply=query(tcp);self.assertEqual(reply['status'],'passed',reply);self.assertEqual(reply['addresses'],['2001:db8:20::20'])
                with manager.locked():report=probe(manager,'PC1','server.lab.test',protocol='dns',family='ipv6',dns_transport='tcp')
                self.assertEqual(report['status'],'passed',report)
            def links_up():
                for endpoints in paths.values():
                    for index,port in endpoints:
                        row=json.loads(manager.ns(index,'ip','-j','link','show','dev',port).stdout)[0]
                        self.assertTrue({'UP','LOWER_UP'}.issubset(row['flags']),row)
            def drop(path):
                self.assertNotIn(path,blocked)
                for index,port in paths[path]:
                    manager.ns(index,'tc','qdisc','add','dev',port,'clsact')
                    manager.ns(index,'tc','filter','add','dev',port,'ingress','protocol','ipv6','pref','1','flower','skip_hw','action','drop')
                blocked.add(path);links_up()
            def dropped(path):
                for index,port in paths[path]:
                    rows=json.loads(manager.ns(index,'tc','-j','-s','filter','show','dev',port,'ingress').stdout)
                    actions=[a for row in rows for a in row.get('options',{}).get('actions',[])]
                    self.assertTrue(any(a.get('stats',{}).get('drops',0)>0 for a in actions),rows)
            def restore(path):
                dropped(path)
                for index,port in paths[path]:manager.ns(index,'tc','qdisc','del','dev',port,'clsact')
                blocked.remove(path);links_up()
            def wire_selected(label,path):
                events=[threading.Event(),threading.Event()];wires=[root/(label+'-'+p+'.pcap') for p in ('primary','backup')]
                futures=[pool.submit(capture,Manager(spec['name']),'R1',paths[p][0][1],wire,seconds=4,packets=500,
                    expression='ip6 and host 2001:db8:10::10 and (udp port 53 or tcp port 53)',ready=event.set)
                    for p,wire,event in zip(('primary','backup'),wires,events)]
                self.assertTrue(all(event.wait(5) for event in events));dns_healthy()
                for future in futures:future.result(timeout=9)
                for observed,wire in zip(('primary','backup'),wires):
                    for transport in ('udp','tcp'):
                        for direction in ('src','dst'):
                            text=run(['tcpdump','-nn','-r',wire,'ip6','and',transport,'port','53','and',direction,'host','2001:db8:20::20']).stdout
                            if observed==path:self.assertTrue(text,(observed,transport,direction))
                            else:self.assertFalse(text,(observed,transport,direction,text))
            def refuse():
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
            try:
                with manager.locked():manager.start(spec)
                selected('primary',2);dns_healthy();links_up()
                qdiscs={(i,p):json.loads(manager.ns(i,'tc','-j','qdisc','show','dev',p).stdout) for endpoints in paths.values() for i,p in endpoints}
                state=copy.deepcopy(manager.read())
                daemons={('R1','/run/bird.pid'):None,('R2','/run/bird.pid'):None,('PC2','/run/dnsmasq.pid'):None}
                for key in daemons:daemons[key]=manager.crun('exec',key[0],'/bin/busybox','cat',key[1]).stdout.strip()
                wire_selected('initial','primary')
                drop('primary');selected('backup',1);dns_healthy();dropped('primary');links_up();wire_selected('backup','backup')
                restore('primary');selected('primary',2);dns_healthy()
                # Complete transit loss withdraws both remote LAN prefixes;
                # directly connected DNS remains independently available.
                drop('primary');drop('backup')
                wait(lambda:not remote(1) and not remote(2),'Routes survived complete transit loss')
                for tcp in (False,True):
                    self.assertEqual(query(tcp)['status'],'failed')
                    local=query(tcp,True);self.assertEqual(local['status'],'passed',local);self.assertEqual(local['addresses'],['2001:db8:20::20'])
                dropped('primary');dropped('backup');links_up()
                restore('backup');selected('backup',1);dns_healthy()
                for (node,pidfile),pid in daemons.items():
                    self.assertEqual(manager.crun('exec',node,'/bin/busybox','cat',pidfile).stdout.strip(),pid)
                    self.assertEqual(manager.crun('exec',node,'/bin/busybox','kill','-0',pid,check=False).returncode,0)
                self.assertEqual(manager.read(),state)
                config=manager.directory/'R1/files/bird.conf';text=config.read_text();config.write_text(text+'# drift\n');refuse();config.write_text(text)
                manager.ns(1,'ip','-6','route','add','2001:db8:99::/64','via','2001:db8:100::2','dev','eth1','proto','static');refuse()
                manager.ns(1,'ip','-6','route','del','2001:db8:99::/64')
                # External tc fault rules are not managed/saved policy. Save
                # while the backup carries DNS, then recreate fresh namespaces.
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    self.assertTrue(all(not n['ipv6_routes'] for n in saved['nodes'][1:3]));manager.stop();manager.start(saved)
                blocked.clear();selected('primary',2);dns_healthy();wire_selected('cold-primary','primary')
                for (index,port),expected in qdiscs.items():
                    self.assertEqual(json.loads(manager.ns(index,'tc','-j','qdisc','show','dev',port).stdout),expected)
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
