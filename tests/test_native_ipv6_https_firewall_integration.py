"""Real IPv6 TLS over default-deny forwarding, independent controls and restore."""
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
from network_labs.appliances.examples import ipv6_https_firewall_lab
from network_labs.appliances.firewall import fingerprint
from network_labs.appliances.https_server import BODY,PID,start_server
from network_labs.appliances.ipv6 import drift as ipv6_drift
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from test_native_integration import unexpected_host_link_changes
from test_native_ipv6_https_integration import REQUEST


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6HTTPSFirewallTests(unittest.TestCase):
    def test_tls_allow_default_deny_stateful_return_controls_and_cold_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('nginx','openssl','busybox','crun','ip','tcpdump','nft','conntrack'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        forwarding=run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout
        host_nft=fingerprint(json.loads(run(['nft','-j','-n','list','ruleset']).stdout))
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=2) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);certs=identities(root,valid_ip='2001:db8:20::20')
            client=static_busybox_rootfs(shutil.which('busybox'),root/'client')
            server=static_busybox_rootfs(shutil.which('busybox'),root/'server',nginx=shutil.which('nginx'),
                https_ca=certs['ca'],https_certificate=certs['valid_cert'],https_private_key=certs['valid_key'])
            spec=ipv6_https_firewall_lab(server,client);spec['name']='ipv6-https-fw-'+str(os.getpid());manager=Manager(spec['name'])
            def wait(predicate,label):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail(label)
            def query(ca=certs['ca']):
                with manager.locked():
                    return probe(manager,'PC1','2001:db8:20::20',protocol='https',family='ipv6',ca_pem=ca.read_text(),timeout=1)
            def healthy():
                wait(lambda:query()['status']=='passed','Trusted HTTPS blocked')
                self.assertTrue(query()['stages'][-1]['certificate_verified'])
                wait(echo,'Allowed independent echo blocked')
            def echo():
                return manager.crun('exec','PC1','/bin/busybox','ping6','-c','1','-W','1','-w','2','2001:db8:20::20',check=False,timeout=4).returncode==0
            def raw_request(local=False,source=None):
                return manager.ns(1 if local else 0,sys.executable,'-I','-c',REQUEST,input_text=json.dumps(
                    {'ca':str(certs['ca']),'source':source or ('2001:db8:20::1' if local else '2001:db8:10::10'),
                     'method':'GET','name':'https.lab'}),timeout=6,check=False)
            def request(local=False):
                result=raw_request(local)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn(BODY.replace('\\n','\n'),json.loads(result.stdout)['response'])
            def http(local=False):
                return manager.crun('exec','PC2' if local else 'PC1','/bin/busybox','wget','-q','-T','1','-O','-','http://[2001:db8:20::20]:8080/',check=False,timeout=4)
            def refuse():
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
            def pid():return manager.crun('exec','PC2','/bin/busybox','cat',PID).stdout
            def counters():
                return {r['rule']['comment']:sum(e['counter']['packets'] for e in r['rule']['expr'] if 'counter' in e)
                    for r in manager.inspect('FW1')['firewall_ipv6']['nftables'] if 'rule' in r}
            def source_isolation(label):
                # Same interface, destination and port: only the source differs.
                # The extra address is an external test fault, never saved policy.
                alternate='2001:db8:10::99'
                manager.ns(0,'ip','-6','addr','add',alternate+'/64','dev','eth0')
                try:
                    def usable():
                        rows=json.loads(manager.ns(0,'ip','-j','-6','addr','show','dev','eth0').stdout)
                        return any(a.get('local')==alternate and not any(a.get(f) or f in a.get('flags',[]) for f in ('tentative','dadfailed'))
                            for row in rows for a in row.get('addr_info',[]))
                    wait(usable,'Alternate source did not complete DAD')
                    control=manager.crun('exec','PC1','/bin/busybox','ping6','-I',alternate,'-c','1','-W','1','-w','2',
                        '2001:db8:10::1',check=False,timeout=4)
                    self.assertEqual(control.returncode,0,control.stderr)
                    route=json.loads(manager.ns(0,'ip','-j','-6','route','get','2001:db8:20::20','from',alternate).stdout)
                    self.assertEqual(route[0]['gateway'],'2001:db8:10::1');self.assertEqual(route[0]['dev'],'eth0')
                    before_drop=counters()['default'];server_pid=pid()
                    events=[threading.Event(),threading.Event()];paths=[root/(label+'-source-in.pcap'),root/(label+'-source-out.pcap')]
                    futures=[pool.submit(capture,Manager(spec['name']),'FW1',port,path,seconds=5,packets=1000,
                        expression='ip6 and src host '+alternate+' and tcp dst port 443',ready=event.set)
                        for port,path,event in zip(('eth0','eth1'),paths,events)]
                    for event in events:self.assertTrue(event.wait(5))
                    denied=raw_request(source=alternate)
                    self.assertNotEqual(denied.returncode,0);self.assertIn('TimeoutError',denied.stderr)
                    self.assertNotIn('CERTIFICATE_VERIFY_FAILED',denied.stderr)
                    request();request(local=True);self.assertEqual(pid(),server_pid)
                    for future in futures:future.result(timeout=9)
                    ingress=run(['tcpdump','-nn','-r',paths[0]]).stdout
                    self.assertIn(alternate,ingress);self.assertIn('2001:db8:20::20.443',ingress)
                    self.assertFalse(run(['tcpdump','-nn','-r',paths[1]]).stdout)
                    self.assertGreater(counters()['default'],before_drop)
                    self.assertTrue(any('IPv6 addresses differ' in error for error in ipv6_drift(manager,0,spec['nodes'][0])),
                        'Extra source must remain observable drift')
                    refuse()
                finally:
                    manager.ns(0,'ip','-6','addr','del',alternate+'/64','dev','eth0')
                healthy();request()
            try:
                with manager.locked():manager.start(spec)
                healthy();initial_pid=pid();state=copy.deepcopy(manager.read())
                manager.crun('exec','PC2','/bin/sh','-c','mkdir -p /tmp/www; printf https-firewall-control > /tmp/www/index.html')
                manager.crun('exec','--detach','PC2','/bin/busybox','httpd','-f','-p','[::]:8080','-h','/tmp/www',log=manager.directory/'PC2/http-control.log')
                wait(lambda:http(True).returncode==0,'Independent denied-port listener unavailable')
                events=[threading.Event(),threading.Event()];paths=[root/'in.pcap',root/'out.pcap']
                futures=[pool.submit(capture,Manager(spec['name']),'FW1',port,path,seconds=5,packets=1000,
                    expression='ip6',ready=event.set) for port,path,event in zip(('eth0','eth1'),paths,events)]
                for event in events:self.assertTrue(event.wait(5))
                healthy();request();self.assertNotEqual(http().returncode,0)
                self.assertEqual(http(True).stdout,'https-firewall-control');request(local=True)
                for future in futures:future.result(timeout=9)
                for path in paths:
                    traffic=run(['tcpdump','-nn','-r',path,'ip6','and','tcp','port','443']).stdout
                    self.assertIn('2001:db8:10::10',traffic);self.assertIn('2001:db8:20::20.443',traffic)
                    self.assertNotIn(b'Network LABS HTTPS ready',path.read_bytes())
                self.assertTrue(run(['tcpdump','-nn','-r',paths[0],'tcp','port','8080']).stdout)
                self.assertFalse(run(['tcpdump','-nn','-r',paths[1],'tcp','port','8080']).stdout)
                observed=counters()
                for label in ('state','rule:https-out','default'):self.assertGreater(observed[label],0,observed)
                entries=manager.ns(1,'conntrack','-L','-f','ipv6','-p','tcp').stdout
                self.assertIn('dport=443',entries);self.assertIn('src=2001:db8:10::10',entries)
                source_isolation('initial')
                denied=query(certs['wrong_ca']);self.assertEqual(denied['status'],'failed',denied)
                self.assertEqual(denied['stages'][-1]['error'],'CERTIFICATE_VERIFY_FAILED',denied)
                manager.ns(1,'sysctl','-w','net/ipv6/conf/all/forwarding=0')
                self.assertEqual(query()['status'],'failed');request(local=True);self.assertEqual(pid(),initial_pid);refuse()
                manager.ns(1,'sysctl','-w','net/ipv6/conf/all/forwarding=1');healthy()
                manager.crun('exec','PC2','/bin/sh','-c','/bin/kill -QUIT "$(/bin/cat '+PID+')"')
                wait(lambda:manager.crun('exec','PC2','/bin/busybox','test','-e',PID,check=False).returncode!=0,'HTTPS master did not exit')
                self.assertEqual(query()['status'],'failed');wait(echo,'HTTPS outage affected allowed ICMPv6')
                start_server(manager,spec['nodes'][2]);healthy()
                manager.ns(1,'nft','add','table','ip6','unmanaged_https_test');refuse()
                manager.ns(1,'nft','delete','table','ip6','unmanaged_https_test')
                self.assertEqual(manager.read(),state)
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    manager.stop();manager.start(saved)
                healthy();request();source_isolation('restored')
                # With identical outbound permission but no stateful TCP return,
                # direct server TLS and explicitly returned echo still work.
                stateless=copy.deepcopy(saved);policy=stateless['nodes'][1]['firewall_ipv6'];policy['stateful']=False
                policy['rules'].append({'name':'echo-return','action':'accept','in':'eth1','out':'eth0',
                    'source':'2001:db8:20::20/128','destination':'2001:db8:10::10/128','protocol':'icmpv6','icmp_type':'echo-reply'})
                with manager.locked():manager.stop();manager.start(stateless)
                wait(echo,'Explicit stateless echo return unavailable');request(local=True)
                self.assertEqual(query()['status'],'failed')
                with manager.locked():manager.stop();manager.start(saved)
                healthy();request()
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
