"""Real IPv6 local-reference/relay/client chain without host clock adjustment."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from network_labs.appliances.capture import capture
from network_labs.appliances.examples import ipv6_ntp_relay_lab
from network_labs.appliances.ntp_server import observe,start_servers,read_cli
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6NTPRelayTests(unittest.TestCase):
    def test_managed_chain_acl_source_loss_fresh_relay_no_fallback_and_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('chronyd','chronyc','crun','ip','busybox','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        forwarding=run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=2) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',chronyd=shutil.which('chronyd'),chronyc=shutil.which('chronyc'))
            spec=ipv6_ntp_relay_lab(rootfs);spec['name']='ipv6-ntp-relay-'+str(os.getpid());manager=Manager(spec['name'])
            relay=spec['nodes'][3];source=spec['nodes'][5]
            def wait(predicate,label,seconds=50):
                until=time.monotonic()+seconds
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail(label)
            def query(client='PC1',target='2001:db8:20::20'):
                return probe(manager,client,target,family='ipv6',protocol='sntp',timeout=1)
            def good():
                wait(lambda:query()['status']=='passed','IPv6 relay did not acquire its managed reference')
                actual=query();self.assertEqual(actual['status'],'passed',actual)
                self.assertEqual(actual['stages'][-1]['stratum'],11)
                sources=read_cli(manager,'PC2','sources')
                self.assertTrue(any('2001:db8:40::40' in line and '^*' in line for line in sources.splitlines()),sources)
            def root_good():
                wait(lambda:query('PC2','2001:db8:40::40')['status']=='passed','Managed local reference unavailable',15)
                self.assertEqual(query('PC2','2001:db8:40::40')['stages'][-1]['stratum'],10)
            def ping(client,target):
                wait(lambda:manager.crun('exec',client,'/bin/busybox','ping6','-c','1','-W','1',target,check=False,timeout=4).returncode==0,'Independent route unavailable',15)
            def denied():
                ping('PC1','2001:db8:40::40');self.assertEqual(query('PC1','2001:db8:40::40')['status'],'failed')
                ping('PC3','2001:db8:20::20');self.assertEqual(query('PC3')['status'],'failed')
            def evidence(node):
                actual=observe(manager,node)
                self.assertTrue(actual['configuration_verified']);self.assertEqual(actual['process']['status'],'observed',actual)
                self.assertEqual(actual['udp_socket']['status'],'observed',actual)
                pid=actual['process']['pid'];status=manager.crun('exec',node['name'],'/bin/busybox','cat',f'/proc/{pid}/status').stdout
                caps=[int(line.split(':')[1].strip(),16) for line in status.splitlines() if line.startswith(('CapInh:','CapPrm:','CapEff:','CapBnd:','CapAmb:'))]
                self.assertEqual(len(caps),5);self.assertTrue(all(bits & (1<<25)==0 for bits in caps))
                return pid
            def stop(node):
                manager.crun('exec',node['name'],'/bin/busybox','kill','-TERM',str(evidence(node)))
                wait(lambda:observe(manager,node)['udp_socket']['status']=='absent','Stopped server retains UDP binding',10)
            try:
                with manager.locked():manager.start(spec)
                root_good();stop(relay)
                events=[threading.Event(),threading.Event()];paths=[root/'relay.pcap',root/'reference.pcap']
                captures=[pool.submit(capture,Manager(spec['name']),name,'eth0',path,seconds=15,packets=2000,expression='ip6 and udp port 123',ready=event.set) for name,path,event in zip(('PC2','PC4'),paths,events)]
                for event in events:self.assertTrue(event.wait(5))
                start_servers(manager,names={'PC2'});good();denied();evidence(relay);evidence(source)
                for capture_result in captures:capture_result.result(timeout=20)
                for expression in (['src','host','2001:db8:20::20','and','dst','host','2001:db8:40::40'],['src','host','2001:db8:40::40','and','dst','host','2001:db8:20::20'],['src','host','2001:db8:20::20','and','dst','host','2001:db8:10::10']):
                    self.assertTrue(run(['tcpdump','-nn','-r',paths[0],*expression]).stdout)
                self.assertTrue(run(['tcpdump','-nn','-r',paths[1],'src','host','2001:db8:10::10','and','dst','port','123']).stdout)
                # A live relay may hold its previous estimate after source loss.
                # Restart it without the source to test absence of local fallback.
                stop(source);stop(relay);start_servers(manager,names={'PC2'})
                wait(lambda:observe(manager,relay)['udp_socket']['status']=='observed','Fresh relay did not bind',10)
                ping('PC1','2001:db8:20::20')
                self.assertEqual(query()['status'],'failed')
                self.assertIn('Not synchronised',read_cli(manager,'PC2','tracking'))
                start_servers(manager,names={'PC4'});root_good()
                stop(relay);start_servers(manager,names={'PC2'});good();denied()
                config=manager.directory/'PC2/files/ntp-server.conf';original=config.read_text();config.write_text(original+'# drift\n')
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                config.write_text(original)
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    manager.stop();manager.start(saved)
                root_good();good();denied();evidence(relay);evidence(source)
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
