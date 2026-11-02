"""Real routed DNS A/AAAA over IPv4/IPv6 UDP/TCP, independent faults and restore."""
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
from network_labs.appliances.examples import dual_stack_dns_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from network_labs.appliances.verify import verify
from test_native_integration import unexpected_host_link_changes

# Independent stdlib client explicitly binds the selected guest source address.
# This is test traffic, not an expansion of the IPv4-only managed probe command.
QUERY=r'''
import ipaddress,json,socket,struct,sys
r=json.loads(sys.argv[1]);name=r['name'];kind=r['kind'];family=socket.AF_INET6 if r['family']==6 else socket.AF_INET
wire=b''.join(bytes([len(p)])+p.encode() for p in name.split('.'))+b'\x00'
q=struct.pack('!6H',42,0x100,1,0,0,0)+wire+struct.pack('!HH',kind,1)
def exact(s,n):
 b=b''
 while len(b)<n:
  p=s.recv(n-len(b))
  if not p:raise ValueError('short TCP frame')
  b+=p
 return b
def skip(p,i):
 while p[i]:
  if p[i]&0xc0==0xc0:return i+2
  i+=1+p[i]
 return i+1
try:
 with socket.socket(family,socket.SOCK_STREAM if r['tcp'] else socket.SOCK_DGRAM) as s:
  s.settimeout(1);s.bind((r['source'],0));s.connect((r['server'],53))
  if r['tcp']:
   s.sendall(struct.pack('!H',len(q))+q);n=struct.unpack('!H',exact(s,2))[0]
   if not 12<=n<=4096:raise ValueError('frame size')
   p=exact(s,n)
  else:s.send(q);p=s.recv(4096)
  rid,flags,qd,an,ns,ar=struct.unpack('!6H',p[:12])
  if rid!=42 or not flags&0x8000 or flags&0x200 or qd!=1 or p[12:len(q)]!=q[12:]:raise ValueError('unmatched DNS reply')
  i=len(q);answers=[];ttls=[]
  for _ in range(an):
   i=skip(p,i);t,c,ttl,n=struct.unpack('!HHIH',p[i:i+10]);i+=10;data=p[i:i+n];i+=n
   if t==kind and c==1:
    if n!=(16 if kind==28 else 4):raise ValueError('address size')
    answers.append(str(ipaddress.ip_address(data)));ttls.append(ttl)
  print(json.dumps({'status':'passed','rcode':flags&15,'addresses':answers,'ttls':ttls}))
except (OSError,ValueError,IndexError,struct.error) as e:print(json.dumps({'status':'failed','error':type(e).__name__}))
'''


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeDualStackDNSTests(unittest.TestCase):
    def test_routed_a_aaaa_both_transports_family_faults_and_cold_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dnsmasq','busybox','crun','ip','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        sysctls={key:run(['sysctl','-n',key]).stdout for key in ('net.ipv4.ip_forward','net.ipv6.conf.all.forwarding')}
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dnsmasq=shutil.which('dnsmasq'))
            spec=dual_stack_dns_lab(rootfs);spec['name']='dual-dns-'+str(os.getpid());manager=Manager(spec['name'])
            def query(family=6,tcp=False,kind=28,name='server.lab.test'):
                request={'family':family,'tcp':tcp,'kind':kind,'name':name,'source':'2001:db8:10::10' if family==6 else '192.0.2.10','server':'2001:db8:20::20' if family==6 else '198.51.100.20'}
                return json.loads(manager.ns(0,sys.executable,'-I','-c',QUERY,json.dumps(request),timeout=4).stdout)
            def good(family=6,tcp=False,kind=28):
                actual=query(family,tcp,kind);self.assertEqual(actual['status'],'passed',actual)
                self.assertEqual(actual['rcode'],0);self.assertEqual(actual['addresses'],['2001:db8:20::20' if kind==28 else '198.51.100.20']);self.assertEqual(actual['ttls'],[60])
            def ready():
                until=time.monotonic()+5
                expected={'198.51.100.20:53','[2001:db8:20::20]:53'}
                while time.monotonic()<until:
                    rows=manager.ns(3,'ss','-H','-lntu','sport = :53').stdout.splitlines()
                    if len(rows)==4 and {row.split()[4] for row in rows}==expected:return
                    time.sleep(.1)
                self.fail('DNS did not bind exactly the declared IPv4/IPv6 UDP/TCP endpoints: '+str(rows))
            def echo():
                for family in ('ipv4','ipv6'):
                    # Readiness allows initial neighbor discovery; success still requires
                    # complete bidirectional delivery, without installing neighbor entries.
                    until=time.monotonic()+8
                    while True:
                        actual=verify(manager,'PC1','PC2',family=family,count=2,bidirectional=True)
                        if actual['status']=='passed':break
                        if time.monotonic()>=until:self.fail(str(actual))
                        time.sleep(.2)
            try:
                with manager.locked():manager.start(spec);ready();echo()
                state=copy.deepcopy(manager.read());event=threading.Event();pcap=root/'dns.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=6,packets=1000,expression='port 53',ready=event.set)
                self.assertTrue(event.wait(5))
                for family in (4,6):
                    for tcp in (False,True):
                        for kind in (1,28):good(family,tcp,kind)
                    denied=query(family,True,28,'missing.lab.test');self.assertEqual(denied['rcode'],3);self.assertEqual(denied['addresses'],[])
                self.assertEqual(probe(manager,'PC1','server.lab.test',protocol='dns',dns_transport='tcp')['status'],'passed')
                future.result(timeout=9)
                for fam in ('ip','ip6'):
                    for transport in ('udp','tcp'):
                        self.assertTrue(run(['tcpdump','-nn','-r',pcap,fam,'and',transport,'and','port','53']).stdout)
                self.assertEqual(manager.read(),state)
                with manager.locked():
                    manager.ns(1,'sysctl','-w','net.ipv4.ip_forward=0')
                    self.assertEqual(query(4)['status'],'failed');good(6,True)
                    with self.assertRaises(RuntimeFailure):manager.write_startup()
                    manager.ns(1,'sysctl','-w','net.ipv4.ip_forward=1')
                    manager.ns(1,'sysctl','-w','net/ipv6/conf/all/forwarding=0')
                    self.assertEqual(query(6)['status'],'failed');good(4,True)
                    with self.assertRaises(RuntimeFailure):manager.write_startup()
                    manager.ns(1,'sysctl','-w','net/ipv6/conf/all/forwarding=1')
                good(4);good(6)
                manager.crun('exec','PC2','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/dnsmasq.pid)"')
                until=time.monotonic()+5
                while manager.ns(3,'ss','-H','-lntu','sport = :53').stdout and time.monotonic()<until:time.sleep(.1)
                self.assertFalse(manager.ns(3,'ss','-H','-lntu','sport = :53').stdout)
                self.assertEqual(query(4,True)['status'],'failed');self.assertEqual(query(6,True)['status'],'failed');echo()
                start_servers(manager);ready();good(4,True);good(6,True)
                with manager.locked():
                    config=manager.directory/'PC2/files/dnsmasq.conf';original=config.read_text();config.write_text(original+'# drift\n')
                    with self.assertRaises(RuntimeFailure):manager.write_startup()
                    config.write_text(original)
                    resolver=manager.directory/'PC1/files/resolv.conf';original_resolver=resolver.read_text();resolver.write_text('nameserver 192.0.2.99\n')
                    with self.assertRaises(RuntimeFailure):manager.write_startup()
                    resolver.write_text(original_resolver);manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    manager.stop();manager.start(saved)
                ready();echo();good(4,True,1);good(6,True,28)
                with manager.locked():manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        for key,value in sysctls.items():self.assertEqual(run(['sysctl','-n',key]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
