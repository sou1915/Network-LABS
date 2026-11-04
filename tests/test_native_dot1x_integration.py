"""Real wired wpa_supplicant, EAPOL/RADIUS and finite kernel port admission."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from network_labs.appliances.capture import capture
from network_labs.appliances.dot1x import authenticate, observe, TABLE
from network_labs.appliances.examples import dot1x_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.radius_server import start_servers
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.spec import namespace
from test_native_integration import unexpected_host_link_changes
from test_native_radius_eap_md5_integration import radius_packets, attrs


def eapol_packets(data):
    endian={b'\xd4\xc3\xb2\xa1':'<',b'\xa1\xb2\xc3\xd4':'>',b'\x4d\x3c\xb2\xa1':'<',b'\xa1\xb2\x3c\x4d':'>'}[data[:4]];offset=24;out=[]
    while offset+16<=len(data):
        size=struct.unpack(endian+'4I',data[offset:offset+16])[2];offset+=16;frame=data[offset:offset+size];offset+=size
        if len(frame)>=22 and frame[12:14]==b'\x88\x8e' and frame[15]==0:
            length=int.from_bytes(frame[16:18],'big');out.append(frame[18:18+length])
    return out


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeDot1xTests(unittest.TestCase):
    def test_real_wired_port_blocks_admits_expires_logoff_worker_kill_and_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('freeradius','wpa_supplicant','wpa_cli','crun','busybox','nft','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        password='native-dot1x-password';secret='native-dot1x-backend-secret';supplicant=None
        with tempfile.TemporaryDirectory() as d,ThreadPoolExecutor(max_workers=4) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(d)/'saved'):
            root=Path(d);asset=root/'password';asset.write_text(password);asset.chmod(0o600)
            modules=next(p for p in ('/usr/lib/freeradius','/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p)/'rlm_pap.so').is_file())
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',freeradius=shutil.which('freeradius'),freeradius_modules=modules,freeradius_dictionaries='/usr/share/freeradius',freeradius_eap_md5=True)
            spec=dot1x_lab(rootfs,secret,hashlib.sha256(password.encode()).hexdigest(),asset);spec['name']='dot1x-'+str(os.getpid());manager=Manager(spec['name'])
            ctrl=root/'ctrl';ctrl.mkdir(mode=0o700)
            def stop_peer():
                nonlocal supplicant
                if supplicant is not None:
                    if supplicant.poll() is None:supplicant.terminate()
                    supplicant.wait(timeout=3);supplicant=None
            def start_peer(credential=password,identity='learner'):
                nonlocal supplicant
                stop_peer();config=root/'supplicant.conf'
                config.write_text(f'ctrl_interface={ctrl}\nap_scan=0\nnetwork={{\n key_mgmt=IEEE8021X\n eap=MD5\n identity="{identity}"\n password="{credential}"\n eapol_flags=0\n}}\n');config.chmod(0o600)
                with (root/'wpa.log').open('ab') as log:
                    supplicant=subprocess.Popen(['ip','netns','exec',namespace(spec,0),'wpa_supplicant','-D','wired','-i','eth0','-c',str(config),'-q'],stdin=subprocess.DEVNULL,stdout=log,stderr=log)
                until=time.monotonic()+5
                while time.monotonic()<until:
                    if supplicant.poll() is not None:self.fail('Independent wired supplicant failed startup')
                    if (ctrl/'eth0').exists():return
                    time.sleep(.05)
                self.fail('Supplicant control interface unavailable')
            def gate():
                fresh=Manager(spec['name']);node=fresh.read()['spec']['nodes'][1];return observe(fresh,1,node)
            def ping(source='PC1',target='192.0.2.20'):
                return manager.crun('exec',source,'/bin/busybox','ping','-c','1','-W','1','-w','2',target,check=False,timeout=4).returncode
            def admitted(future):
                until=time.monotonic()+7
                while time.monotonic()<until:
                    if gate()['admitted']:return
                    if future.done():self.fail('Port never admitted: '+json.dumps(future.result()))
                    time.sleep(.03)
                self.fail('Controlled port did not open')
            def session():return pool.submit(authenticate,Manager(spec['name']),'SW1',timeout=5)
            def close_check():
                self.assertTrue(gate()['configuration_verified']);self.assertFalse(gate()['admitted']);self.assertNotEqual(ping(),0)
                self.assertNotEqual(ping('PC2','192.0.2.10'),0,'Closed port must block backend-to-peer data too')
            try:
                with manager.locked():manager.start(spec)
                self.assertEqual(ping('SW1'),0,'Uncontrolled NAS/backend path must work before authentication')
                close_check();start_peer()
                event1=threading.Event();event2=threading.Event();wire=root/'eapol.pcap';radius=root/'radius.pcap'
                cap1=pool.submit(capture,Manager(spec['name']),'SW1','eth0',wire,seconds=4,packets=100,expression='ether proto 0x888e',ready=event1.set)
                cap2=pool.submit(capture,Manager(spec['name']),'SW1','eth1',radius,seconds=4,packets=100,expression='udp port 1812',ready=event2.set)
                self.assertTrue(event1.wait(5));self.assertTrue(event2.wait(5))
                future=session();admitted(future)
                until=time.monotonic()+2
                while ping()!=0:
                    if time.monotonic()>=until:self.fail('Admitted peer data did not cross the controlled port')
                self.assertEqual(ping('PC2','192.0.2.10'),0)
                with manager.locked():manager.write_startup();saved=load_startup(spec['name'])
                self.assertNotIn('admitted',json.dumps(saved));self.assertNotIn('dot1x_workers',json.dumps(saved))
                result=future.result(timeout=10);self.assertEqual(result['status'],'passed',result)
                self.assertTrue(result['port_closed']);self.assertEqual(result['radius_requests'],2);close_check()
                cap1.result(timeout=6);cap2.result(timeout=6)
                frames=eapol_packets(wire.read_bytes());self.assertTrue(any(p[0:1]==b'\x01' and p[4:5]==b'\x01' for p in frames))
                self.assertTrue(any(p[0:1]==b'\x01' and p[4:5]==b'\x04' for p in frames));self.assertTrue(any(p[0]==3 for p in frames))
                packets=radius_packets(radius.read_bytes());requests=[p for _,dst,p in packets if dst==1812];replies=[p for src,_,p in packets if src==1812]
                self.assertEqual(len(requests),2);self.assertEqual([p[0] for p in replies],[11,2]);self.assertEqual(attrs(requests[1])[24],attrs(replies[0])[24])
                self.assertNotIn(password.encode(),wire.read_bytes());self.assertNotIn(secret.encode(),radius.read_bytes())
                start_peer('incorrect-password');failed=session().result(timeout=10);self.assertEqual(failed['status'],'failed',failed);close_check()
                start_peer(identity='unknown');blocked=session().result(timeout=10);self.assertEqual(blocked['status'],'blocked',blocked);self.assertEqual(blocked['radius_requests'],0);close_check()
                start_peer();future=session();admitted(future)
                logoff=manager.ns(0,'wpa_cli','-p',str(ctrl),'-i','eth0','logoff',check=False,timeout=3)
                self.assertIn('OK',logoff.stdout);result=future.result(timeout=6);self.assertEqual(result['reason'],'LOGOFF',result);close_check()
                start_peer();future=session();admitted(future)
                owner=Manager(spec['name']).read()['dot1x_workers']['SW1'];os.kill(owner['pid'],signal.SIGKILL)
                self.assertEqual(future.result(timeout=5)['status'],'unknown')
                until=time.monotonic()+7
                while gate()['admitted']:
                    if time.monotonic()>=until:self.fail('Kernel admission survived its finite timeout after worker death')
                    time.sleep(.05)
                close_check();stop_peer()
                observed=manager.inspect('PC2')['radius_server'];manager.crun('exec','PC2','/bin/busybox','kill','-TERM',str(observed['process']['pid']))
                until=time.monotonic()+5
                while manager.inspect('PC2')['radius_server']['udp_socket']['status']!='absent':
                    if time.monotonic()>=until:self.fail('Backend listener did not stop')
                    time.sleep(.05)
                start_peer();failed=session().result(timeout=10);self.assertFalse(failed['authenticated']);close_check();stop_peer()
                with manager.locked():manager.stop();manager.start(saved)
                close_check();start_peer();future=session();admitted(future);self.assertEqual(ping(),0)
                self.assertEqual(future.result(timeout=10)['status'],'passed');stop_peer();close_check()
                # A separate CLI owns teardown while the original command is
                # waiting outside the lab lock. Namespace removal must wait
                # for the pinned worker to die, and neither command may
                # resurrect runtime state after removal.
                start_peer();future=session();admitted(future)
                owner=Manager(spec['name']).read()['dot1x_workers']['SW1']
                stop_peer()
                run([sys.executable,'-m','network_labs.appliances','stop',spec['name']],timeout=15)
                from network_labs.appliances.snooping import alive
                self.assertFalse(alive(owner));self.assertFalse(manager.directory.exists())
                self.assertIn(future.result(timeout=5)['status'],('passed','unknown'))
                with manager.locked():manager.start(saved)
                close_check()
                manager.ns(1,'nft','add','rule','bridge',TABLE,'ingress','counter','accept')
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                with self.assertRaises(RuntimeFailure):authenticate(Manager(spec['name']),'SW1')
            finally:
                stop_peer()
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
