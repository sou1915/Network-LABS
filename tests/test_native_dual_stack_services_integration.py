"""Real DNS/AAA service isolation over shared static IPv4/IPv6 routing."""
from concurrent.futures import ThreadPoolExecutor
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
from network_labs.appliances.examples import dual_stack_services_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.radius_server import start_servers as start_radius
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from network_labs.appliances.ssh_radius import alive
from network_labs.appliances.verify import verify
from test_native_dual_stack_dns_integration import QUERY
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeDualStackServicesTests(unittest.TestCase):
    def test_dns_and_radius_independent_outages_routes_policy_and_saved_restart(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dnsmasq','dropbear','freeradius','ssh','ssh-keygen','ssh-keyscan','crun','ip','busybox','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        sysctls={key:run(['sysctl','-n',key]).stdout for key in ('net.ipv4.ip_forward','net.ipv6.conf.all.forwarding','net.ipv4.ip_unprivileged_port_start')}
        secret='native-combined-radius-secret';password='native-combined-password';workers=[]
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);key=root/'identity';run(['ssh-keygen','-q','-t','ed25519','-N','','-f',key])
            modules=next(p for p in ('/usr/lib/freeradius','/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p)/'rlm_pap.so').is_file())
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dnsmasq=shutil.which('dnsmasq'),dropbear=shutil.which('dropbear'),freeradius=shutil.which('freeradius'),freeradius_modules=modules,freeradius_dictionaries='/usr/share/freeradius')
            spec=dual_stack_services_lab(rootfs,secret,hashlib.sha256(password.encode()).hexdigest(),ssh_key=key.with_suffix('.pub').read_text().strip());spec['name']='combined-services-'+str(os.getpid());manager=Manager(spec['name']);known=root/'known_hosts'
            def wait(predicate,label):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail(label)
            def ready():
                wait(lambda:len(manager.ns(0,'ss','-H','-lnt','sport = :22').stdout.splitlines())==2,'SSH listeners unavailable')
                wait(lambda:len(manager.ns(4,'ss','-H','-lntu','sport = :53').stdout.splitlines())==4,'DNS listeners unavailable')
                wait(lambda:bool(manager.ns(3,'ss','-H','-lun','sport = :1812').stdout),'RADIUS listener unavailable')
            def trust():
                lines=[]
                for family,address in ((4,'192.0.2.10'),(6,'2001:db8:10::10')):
                    actual=manager.ns(3,'ssh-keyscan','-'+str(family),'-T','3','-t','ed25519',address,timeout=5)
                    lines.extend(l for l in actual.stdout.splitlines() if 'ssh-ed25519' in l)
                self.assertEqual(len(lines),2);self.assertEqual(lines[0].split()[1:],lines[1].split()[1:]);known.write_text('\n'.join(lines)+'\n')
            def ssh(family=6,credential=password,action='identity'):
                address='192.0.2.10' if family==4 else '2001:db8:10::10'
                return manager.ns(3,'ssh','-'+str(family),'-F','/dev/null','-T','-o','BatchMode=yes','-o','IdentitiesOnly=yes',
                    '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known),'-o','GlobalKnownHostsFile=/dev/null','-o','ConnectTimeout=3',
                    '-o','LogLevel=ERROR','-i',str(key),'lab@'+address,action,timeout=20,check=False,input_text='learner\n'+credential+'\n')
            def allowed():
                for family in (4,6):
                    actual=ssh(family);self.assertEqual(actual.returncode,0,actual);self.assertIn('uid=65532',actual.stdout)
            def dns(family=6,tcp=True,kind=28,name='nas.lab.test'):
                request={'family':family,'tcp':tcp,'kind':kind,'name':name,'source':'2001:db8:10::10' if family==6 else '192.0.2.10','server':'2001:db8:30::53' if family==6 else '203.0.113.53'}
                return json.loads(manager.ns(0,sys.executable,'-I','-c',QUERY,json.dumps(request),timeout=4).stdout)
            def names():
                for family in (4,6):
                    for tcp in (False,True):
                        for kind in (1,28):
                            actual=dns(family,tcp,kind);self.assertEqual(actual['status'],'passed',actual);self.assertEqual(actual['rcode'],0)
                            self.assertEqual(actual['addresses'],['192.0.2.10' if kind==1 else '2001:db8:10::10'])
                self.assertEqual(probe(manager,'PC1','nas.lab.test',protocol='dns',dns_transport='tcp')['status'],'passed')
            def echo():
                for family in ('ipv4','ipv6'):
                    # Readiness allows initial neighbor discovery; success still requires
                    # complete bidirectional delivery, without installing neighbor entries.
                    until=time.monotonic()+8
                    while True:
                        actual=verify(manager,'PC1','DNS1',family=family,count=2,bidirectional=True)
                        if actual['status']=='passed':break
                        if time.monotonic()>=until:self.fail(str(actual))
                        time.sleep(.2)
            try:
                with manager.locked():manager.start(spec)
                workers.append(dict(manager.state['ssh_radius_workers']['PC1']));ready();trust();echo()
                event=threading.Event();pcap=root/'services.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=8,packets=2000,expression='port 53 or tcp port 22 or udp port 1812',ready=event.set)
                self.assertTrue(event.wait(5));names();allowed()
                for family in (4,6):
                    for kwargs in ({'credential':'incorrect-password'},{'action':'sh -c id'}):
                        actual=ssh(family,**kwargs);self.assertEqual(actual.returncode,126,actual);self.assertEqual(actual.stdout,'')
                    negative=dns(family,name='missing.lab.test');self.assertEqual(negative['rcode'],3)
                future.result(timeout=11)
                for expression in (['ip','and','port','53'],['ip6','and','port','53'],['ip','and','tcp','port','22'],['ip6','and','tcp','port','22'],['udp','port','1812']):
                    self.assertTrue(run(['tcpdump','-nn','-r',pcap,*expression]).stdout)
                manager.crun('exec','DNS1','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/dnsmasq.pid)"')
                wait(lambda:not manager.ns(4,'ss','-H','-lntu','sport = :53').stdout,'Stopped DNS still listens')
                for family in (4,6):self.assertEqual(dns(family)['status'],'failed')
                allowed();echo();start_dns(manager);ready();names()
                manager.crun('exec','PC2','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/network-labs-radius.pid)"')
                wait(lambda:not manager.ns(3,'ss','-H','-lun','sport = :1812').stdout,'Stopped RADIUS still listens')
                names()
                for family in (4,6):
                    actual=ssh(family);self.assertEqual(actual.returncode,126,actual);self.assertEqual(actual.stdout,'')
                (manager.directory/'PC2/radius.log').write_text('');start_radius(manager);ready();allowed()
                with manager.locked():
                    manager.ns(1,'ip','-4','route','del','203.0.113.0/24');manager.ns(1,'ip','-6','route','del','2001:db8:30::/64')
                    for family in (4,6):self.assertEqual(dns(family)['status'],'failed')
                    allowed()
                    with self.assertRaises(RuntimeFailure):manager.write_startup()
                    manager.ns(1,'ip','-4','route','add','203.0.113.0/24','via','198.18.0.2','dev','eth1','proto','static')
                    manager.ns(1,'ip','-6','route','add','2001:db8:30::/64','via','2001:db8:100::2','dev','eth1','proto','static')
                names();echo()
                with manager.locked():
                    for filename in ('DNS1/files/dnsmasq.conf','PC1/files/resolv.conf','PC1/files/management.json','PC2/files/radius/radiusd.conf'):
                        path=manager.directory/filename;original=path.read_text();path.write_text(original+'# drift\n')
                        with self.assertRaises(RuntimeFailure):manager.write_startup()
                        path.write_text(original)
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    manager.stop();self.assertFalse(alive(workers[-1]));manager.start(saved)
                workers.append(dict(manager.state['ssh_radius_workers']['PC1']));self.assertNotEqual(workers[0]['token'],workers[1]['token'])
                ready();trust();names();allowed();echo()
                with manager.locked():manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertTrue(all(not alive(record) for record in workers));self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        for key,value in sysctls.items():self.assertEqual(run(['sysctl','-n',key]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
