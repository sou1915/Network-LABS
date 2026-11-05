"""Real IPv4/IPv6 SSH diagnostics with fail-closed routed IPv4 RADIUS."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
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
from network_labs.appliances.examples import dual_stack_radius_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.radius_server import start_servers
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.ssh_radius import alive
from network_labs.appliances.spec import validate
from network_labs.appliances.verify import verify
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeDualStackRadiusTests(unittest.TestCase):
    PINNED_HOST_KEY=False

    def test_real_ssh_both_families_radius_denials_faults_and_cold_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dropbear','freeradius','ssh','ssh-keygen','ssh-keyscan','crun','ip','busybox','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        sysctls={key:run(['sysctl','-n',key]).stdout for key in ('net.ipv4.ip_forward','net.ipv6.conf.all.forwarding','net.ipv4.ip_unprivileged_port_start')}
        secret='native-dual-stack-radius-secret';password='native-dual-stack-password';workers=[]
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);key=root/'identity';wrong=root/'wrong'
            for path in (key,wrong):run(['ssh-keygen','-q','-t','ed25519','-N','','-f',path])
            host_key=None
            if self.PINNED_HOST_KEY:
                self.assertIsNotNone(shutil.which('dropbearkey'))
                host_key=root/'host-key';run(['dropbearkey','-t','ed25519','-f',host_key]);host_key.chmod(0o600)
            modules=next(p for p in ('/usr/lib/freeradius','/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p)/'rlm_pap.so').is_file())
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dropbear=shutil.which('dropbear'),freeradius=shutil.which('freeradius'),freeradius_modules=modules,freeradius_dictionaries='/usr/share/freeradius')
            digest=hashlib.sha256(password.encode()).hexdigest()
            spec=dual_stack_radius_lab(rootfs,secret,digest,ssh_key=key.with_suffix('.pub').read_text().strip(),ssh_host_key_file=host_key);spec['name']='dual-radius-'+str(os.getpid())
            spec['nodes'][0]['radius_access']['users']['viewer']=['hostname'];spec['nodes'][3]['radius_server']['users']['viewer']={'password_sha256':digest};spec=validate(spec)
            manager=Manager(spec['name']);known=root/'known_hosts'
            def wait(predicate,label):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail(label)
            def ready():
                expected={'192.0.2.10:22','[2001:db8:10::10]:22'}
                def listeners():
                    rows=manager.ns(0,'ss','-H','-lnt','sport = :22').stdout.splitlines()
                    return len(rows)==2 and {row.split()[3] for row in rows}==expected
                wait(listeners,'SSH did not bind exactly its declared IPv4/IPv6 addresses')
                wait(lambda:'198.51.100.20:1812' in manager.ns(3,'ss','-H','-lun','sport = :1812').stdout,'RADIUS unavailable')
            def trust():
                if self.PINNED_HOST_KEY:
                    public=spec['nodes'][0]['management']['ssh_host_key']['public_key']
                    expected=''.join(address+' '+public+'\n' for address in ('192.0.2.10','2001:db8:10::10'))
                    if known.exists():self.assertEqual(known.read_text(),expected)
                    else:known.write_text(expected)
                    return
                keys=[]
                for family,address in ((4,'192.0.2.10'),(6,'2001:db8:10::10')):
                    result=manager.ns(3,'ssh-keyscan','-'+str(family),'-T','3','-t','ed25519',address,check=False,timeout=5)
                    self.assertEqual(result.returncode,0);lines=[l for l in result.stdout.splitlines() if 'ssh-ed25519' in l]
                    self.assertTrue(lines);keys.extend(lines)
                self.assertEqual(keys[0].split()[1:],keys[1].split()[1:]);known.write_text('\n'.join(keys)+'\n')
            def ssh(family=6,action='identity',username='learner',credential=password,identity=key):
                address='192.0.2.10' if family==4 else '2001:db8:10::10'
                return manager.ns(3,'ssh','-'+str(family),'-F','/dev/null','-T','-o','BatchMode=yes','-o','IdentitiesOnly=yes',
                                  '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known),'-o','GlobalKnownHostsFile=/dev/null',
                                  '-o','ConnectTimeout=3','-o','LogLevel=ERROR','-i',str(identity),'lab@'+address,action,
                                  timeout=20,check=False,input_text=username+'\n'+credential+'\n')
            def allowed(family=6):
                result=ssh(family);self.assertEqual(result.returncode,0,result);self.assertIn('uid=65532',result.stdout)
                result=ssh(family,'security-context');self.assertEqual(result.returncode,0,result)
                fields=dict(line.split(':',1) for line in result.stdout.splitlines() if ':' in line)
                self.assertEqual(fields['NoNewPrivs'].strip(),'1');self.assertEqual(int(fields['CapEff'].strip(),16),0)
            def denied(family=6,**kwargs):
                result=ssh(family,**kwargs);self.assertEqual(result.returncode,126,result);self.assertEqual(result.stdout,'')
            def echo(family='ipv6'):
                # Readiness allows initial neighbor discovery; success still requires
                # complete bidirectional delivery, without installing neighbor entries.
                until=time.monotonic()+8
                while True:
                    result=verify(manager,'PC1','PC2',family=family,count=2,bidirectional=True)
                    if result['status']=='passed':break
                    if time.monotonic()>=until:self.fail(str(result))
                    time.sleep(.2)
            try:
                with manager.locked():manager.start(spec)
                workers.append(dict(manager.state['ssh_radius_workers']['PC1']));ready();trust();echo('ipv4');echo()
                event=threading.Event();pcap=root/'aaa.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=8,packets=2000,expression='tcp port 22 or udp port 1812',ready=event.set)
                self.assertTrue(event.wait(5))
                for family in (4,6):
                    allowed(family);denied(family,credential='incorrect-password');denied(family,username='viewer')
                    result=ssh(family,'hostname',username='viewer');self.assertEqual(result.returncode,0,result);self.assertEqual(result.stdout.strip(),'PC1')
                    result=ssh(family,identity=wrong);self.assertEqual(result.returncode,255,result)
                    denied(family,action='sh -c id')
                future.result(timeout=11)
                if self.PINNED_HOST_KEY:
                    expected=known.read_text();wrong_public=wrong.with_suffix('.pub').read_text().strip()
                    known.write_text(''.join(address+' '+wrong_public+'\n' for address in ('192.0.2.10','2001:db8:10::10')))
                    for family in (4,6):
                        result=ssh(family);self.assertEqual(result.returncode,255)
                        self.assertIn('Host key verification failed',result.stderr)
                    known.write_text(expected);allowed(4);allowed(6)
                    self.assertTrue(manager.inspect('PC1')['management']['ssh_host_key']['configuration_verified'])
                for expression in (['ip','and','tcp','port','22'],['ip6','and','tcp','port','22'],['ip','and','udp','port','1812']):
                    self.assertTrue(run(['tcpdump','-nn','-r',pcap,*expression]).stdout)
                # Credentials sent through SSH must not appear in plaintext on TCP/22.
                wire=run(['tcpdump','-nn','-A','-r',pcap,'tcp','port','22']).stdout
                self.assertNotIn(password,wire);self.assertNotIn(secret,wire)
                with manager.locked():
                    manager.ns(1,'sysctl','-w','net.ipv4.ip_forward=0')
                    echo();denied(6)
                    with self.assertRaises(RuntimeFailure):manager.write_startup()
                    manager.ns(1,'sysctl','-w','net.ipv4.ip_forward=1')
                allowed(6)
                with manager.locked():
                    manager.ns(1,'sysctl','-w','net/ipv6/conf/all/forwarding=0')
                    result=ssh(6);self.assertEqual(result.returncode,255,result);allowed(4)
                    with self.assertRaises(RuntimeFailure):manager.write_startup()
                    manager.ns(1,'sysctl','-w','net/ipv6/conf/all/forwarding=1')
                allowed(6)
                manager.crun('exec','PC2','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/network-labs-radius.pid)"')
                wait(lambda:not manager.ns(3,'ss','-H','-lun','sport = :1812').stdout,'Stopped RADIUS still listens')
                denied(4);denied(6);echo('ipv4');echo()
                # Restart with a fresh readiness log, not the old daemon's marker.
                (manager.directory/'PC2/radius.log').write_text('');start_servers(manager);ready();allowed(4);allowed(6)
                with manager.locked():
                    config=manager.directory/'PC1/files/management.json';original=config.read_text();config.write_text(original+'\n')
                    with self.assertRaises(RuntimeFailure):manager.write_startup()
                    config.write_text(original)
                    config=manager.directory/'PC2/files/radius/radiusd.conf';original=config.read_text();config.write_text(original+'\n')
                    with self.assertRaises(RuntimeFailure):manager.write_startup()
                    config.write_text(original);manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    manager.stop();self.assertFalse(alive(workers[-1]));manager.start(saved)
                workers.append(dict(manager.state['ssh_radius_workers']['PC1']));self.assertNotEqual(workers[0]['token'],workers[1]['token'])
                ready();trust();allowed(4);allowed(6);denied(6,username='viewer')
                with manager.locked():manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertTrue(all(not alive(record) for record in workers))
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        for key,value in sysctls.items():self.assertEqual(run(['sysctl','-n',key]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
