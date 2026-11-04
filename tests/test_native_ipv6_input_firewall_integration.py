"""Real local input filtering, preserved forwarding and bounded NDP exceptions."""
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
from network_labs.appliances.examples import ipv6_input_firewall_lab
from network_labs.appliances.firewall import fingerprint
from network_labs.appliances.firewall_ipv6 import TABLE
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from test_native_dual_stack_dns_integration import QUERY
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6InputFirewallTests(unittest.TestCase):
    def test_local_allow_deny_state_ndp_forwarding_drift_and_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dnsmasq','crun','ip','busybox','nft','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        forwarding=run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout
        host_nft=fingerprint(json.loads(run(['nft','-j','-n','list','ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dnsmasq=shutil.which('dnsmasq'))
            spec=ipv6_input_firewall_lab(rootfs);spec['name']='ipv6-input-'+str(os.getpid());manager=Manager(spec['name'])
            def wait(predicate,label):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail(label)
            def query(source='PC1'):
                index,address={'PC1':(0,'2001:db8:10::10'),'FW1':(1,'2001:db8:10::1'),'PC2':(2,'2001:db8:20::20')}[source]
                request=dict(family=6,tcp=False,kind=28,name='server.lab.test',source=address,server='2001:db8:20::20')
                return json.loads(manager.ns(index,sys.executable,'-I','-c',QUERY,json.dumps(request),timeout=4).stdout)
            def http(port=8080,source='PC1'):
                address='2001:db8:20::1' if source=='PC2' else '2001:db8:10::1'
                return manager.crun('exec',source,'/bin/busybox','wget','-q','-T','1','-O','-',f'http://[{address}]:{port}/',check=False,timeout=4)
            def listeners():
                manager.crun('exec','FW1','/bin/sh','-c','mkdir -p /tmp/www; printf local-input-ok > /tmp/www/index.html')
                for port in (8080,8081):
                    manager.crun('exec','--detach','FW1','/bin/busybox','httpd','-f','-p','[::]:'+str(port),'-h','/tmp/www',log=manager.directory/('FW1/http-'+str(port)+'.log'))
                    wait(lambda:http(port,'FW1').returncode==0,'Local listener unavailable')
            def healthy():
                wait(lambda:query()['status']=='passed','Forwarded DNS unavailable')
                wait(lambda:query('FW1')['status']=='passed','Stateful local DNS return unavailable')
                wait(lambda:http().returncode==0,'Permitted local HTTP unavailable')
                self.assertEqual(http().stdout,'local-input-ok')
                self.assertNotEqual(http(8081).returncode,0)
                self.assertNotEqual(http(8080,'PC2').returncode,0)
                self.assertEqual(http(8081,'FW1').returncode,0)
            try:
                with manager.locked():manager.start(spec)
                listeners();healthy()
                # Force fresh neighbor discovery through the input policy.
                event=threading.Event();wire=root/'local-input.pcap'
                cap=pool.submit(capture,Manager(spec['name']),'FW1','eth0',wire,seconds=7,packets=1000,expression='ip6',ready=event.set)
                self.assertTrue(event.wait(5))
                for index in (0,1):manager.ns(index,'ip','-6','neigh','flush','all')
                healthy();cap.result(timeout=10)
                for expression in (['tcp','port','8080'],['tcp','dst','port','8081'],['icmp6']):
                    self.assertTrue(run(['tcpdump','-nn','-r',wire,*expression]).stdout)
                self.assertFalse(run(['tcpdump','-nn','-r',wire,'tcp','src','port','8081']).stdout)
                counters={r['rule']['comment']:sum(e['counter']['packets'] for e in r['rule']['expr'] if 'counter' in e) for r in manager.inspect('FW1')['firewall_ipv6']['nftables'] if 'rule' in r and r['rule']['chain']=='input'}
                for label in ('input-loopback','input-ndp','state','rule:local-http','default'):self.assertGreater(counters[label],0,counters)
                with manager.locked():manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                # Local output stays free; without input state, its DNS replies
                # are denied while the independent forward chain still works.
                stateless=copy.deepcopy(saved);stateless['nodes'][1]['firewall_ipv6']['input']['stateful']=False
                with manager.locked():manager.stop();manager.start(stateless)
                listeners();wait(lambda:query()['status']=='passed','Forwarding changed with input state policy')
                self.assertEqual(query('PC2')['status'],'passed')
                self.assertEqual(query('FW1')['status'],'failed')
                self.assertEqual(http().returncode,0)
                with manager.locked():manager.stop();manager.start(saved)
                listeners();healthy()
                manager.ns(1,'nft','insert','rule','ip6',TABLE,'input','tcp','dport','8081','accept')
                wait(lambda:http(8081).returncode==0,'External drift control did not open the proven listener')
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                with manager.locked():manager.stop();manager.start(saved)
                listeners();healthy()
                # Omission restores the previously validated forward-only
                # behavior, rather than silently installing input filtering.
                legacy=copy.deepcopy(saved);legacy['nodes'][1]['firewall_ipv6'].pop('input')
                with manager.locked():manager.stop();manager.start(legacy)
                listeners();wait(lambda:http(8081).returncode==0,'Omitted input policy unexpectedly filters local input')
                self.assertEqual(query()['status'],'passed')
                with manager.locked():manager.stop();manager.start(saved)
                listeners();healthy()
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
