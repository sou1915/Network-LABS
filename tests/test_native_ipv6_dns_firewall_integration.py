"""Real DNS/IPv6 forward filtering, independent denial controls and restore."""
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
from network_labs.appliances.dns import start_servers
from network_labs.appliances.examples import ipv6_dns_firewall_lab
from network_labs.appliances.firewall import fingerprint
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from test_native_dual_stack_dns_integration import QUERY
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6DNSFirewallTests(unittest.TestCase):
    def test_dns_stateful_returns_default_deny_outage_stateless_control_and_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dnsmasq','crun','ip','busybox','nft','tcpdump','conntrack'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        forwarding=run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout
        host_nft=fingerprint(json.loads(run(['nft','-j','-n','list','ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=2) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dnsmasq=shutil.which('dnsmasq'))
            spec=ipv6_dns_firewall_lab(rootfs);spec['name']='ipv6-dns-fw-'+str(os.getpid());manager=Manager(spec['name'])
            def wait(predicate,label):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail(label)
            def query(tcp=False,kind=28,local=False):
                request=dict(family=6,tcp=tcp,kind=kind,name='server.lab.test',source='2001:db8:20::20' if local else '2001:db8:10::10',server='2001:db8:20::20')
                return json.loads(manager.ns(2 if local else 0,sys.executable,'-I','-c',QUERY,json.dumps(request),timeout=4).stdout)
            def echo():
                return manager.crun('exec','PC1','/bin/busybox','ping6','-c','1','-W','1','-w','2','2001:db8:20::20',check=False,timeout=4).returncode==0
            def healthy():
                wait(lambda:query()['status']=='passed','DNS unavailable through firewall')
                for tcp in (False,True):
                    for kind,address in ((1,'192.0.2.20'),(28,'2001:db8:20::20')):
                        reply=query(tcp,kind);self.assertEqual(reply['status'],'passed',reply)
                        self.assertEqual(reply['addresses'],[address])
                wait(echo,'Allowed echo unavailable')
            def refuse():
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
            def http(local=False):
                return manager.crun('exec','PC2' if local else 'PC1','/bin/busybox','wget','-q','-T','1','-O','-','http://[2001:db8:20::20]:8080/',check=False,timeout=4)
            def listener():
                manager.crun('exec','PC2','/bin/sh','-c','mkdir -p /tmp/www; printf dns-firewall-control > /tmp/www/index.html')
                manager.crun('exec','--detach','PC2','/bin/busybox','httpd','-f','-p','[::]:8080','-h','/tmp/www',log=manager.directory/'PC2/http-control.log')
                wait(lambda:http(True).returncode==0,'Independent denied-port listener unavailable')
            try:
                with manager.locked():manager.start(spec)
                healthy();listener()
                with manager.locked():
                    self.assertEqual(probe(manager,'PC1','server.lab.test',protocol='dns',family='ipv6',dns_transport='tcp')['status'],'passed')
                events=[threading.Event(),threading.Event()];paths=[root/'ingress.pcap',root/'egress.pcap']
                futures=[pool.submit(capture,Manager(spec['name']),'FW1',port,path,seconds=6,packets=1000,expression='ip6',ready=event.set) for port,path,event in zip(('eth0','eth1'),paths,events)]
                for event in events:self.assertTrue(event.wait(5))
                healthy();self.assertNotEqual(http().returncode,0);self.assertEqual(http(True).stdout,'dns-firewall-control')
                for future in futures:future.result(timeout=10)
                for path in paths:
                    for transport in ('udp','tcp'):self.assertTrue(run(['tcpdump','-nn','-r',path,'ip6','and',transport,'port','53']).stdout)
                self.assertTrue(run(['tcpdump','-nn','-r',paths[0],'tcp','port','8080']).stdout)
                self.assertFalse(run(['tcpdump','-nn','-r',paths[1],'tcp','port','8080']).stdout)
                counters={r['rule']['comment']:sum(e['counter']['packets'] for e in r['rule']['expr'] if 'counter' in e) for r in manager.inspect('FW1')['firewall_ipv6']['nftables'] if 'rule' in r}
                for label in ('state','rule:dns-udp','rule:dns-tcp','default'):self.assertGreater(counters[label],0,counters)
                for transport in ('udp','tcp'):
                    entries=manager.ns(1,'conntrack','-L','-f','ipv6','-p',transport).stdout
                    self.assertIn('dport=53',entries);self.assertIn('src=2001:db8:10::10',entries)
                manager.crun('exec','PC2','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/dnsmasq.pid)"')
                wait(lambda:not manager.ns(2,'ss','-H','-lntu','sport = :53').stdout,'DNS did not stop')
                for tcp in (False,True):self.assertEqual(query(tcp)['status'],'failed')
                wait(echo,'DNS outage affected independent allowed echo');start_servers(manager);healthy()
                manager.ns(1,'sysctl','-w','net/ipv6/conf/all/forwarding=0')
                self.assertEqual(query()['status'],'failed');self.assertEqual(query(local=True)['status'],'passed');refuse()
                manager.ns(1,'sysctl','-w','net/ipv6/conf/all/forwarding=1');healthy()
                manager.ns(1,'nft','add','table','ip6','unmanaged_dns_test');refuse()
                manager.ns(1,'nft','delete','table','ip6','unmanaged_dns_test')
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    manager.stop();manager.start(saved)
                healthy()
                # Complete the same route with echo return but deliberately
                # no DNS return rules. Positive local DNS proves a real server.
                stateless=copy.deepcopy(saved);policy=stateless['nodes'][1]['firewall_ipv6'];policy['stateful']=False
                policy['rules'].append({'name':'echo-return','action':'accept','in':'eth1','out':'eth0','source':'2001:db8:20::20/128','destination':'2001:db8:10::10/128','protocol':'icmpv6','icmp_type':'echo-reply'})
                with manager.locked():manager.stop();manager.start(stateless)
                wait(echo,'Stateless explicit echo return unavailable')
                for tcp in (False,True):
                    self.assertEqual(query(tcp,local=True)['status'],'passed')
                    self.assertEqual(query(tcp)['status'],'failed')
                with manager.locked():manager.stop();manager.start(saved)
                healthy()
                with manager.locked():manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        self.assertEqual(run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout,forwarding)
        self.assertEqual(fingerprint(json.loads(run(['nft','-j','-n','list','ruleset']).stdout)),host_nft)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
