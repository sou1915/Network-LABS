"""Real engine-owned wired peer: no manual supplicant, finite NAS gate remains."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from network_labs.appliances.capture import capture
from network_labs.appliances.dot1x import authenticate,observe
from network_labs.appliances.examples import dot1x_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.snooping import alive
from test_native_dot1x_integration import eapol_packets
from test_native_radius_eap_md5_integration import radius_packets,attrs
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeManagedWiredPeerTests(unittest.TestCase):
    def test_owned_peer_repeated_auth_private_handoff_death_refusal_restore_and_cli_teardown(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('freeradius','wpa_supplicant','crun','busybox','ip','nft','tcpdump'):
            self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        routes={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        password='native-owned-peer-password';secret='native-owned-peer-backend-secret'
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=3) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);backend=root/'backend-password';asset=root/'peer-password'
            for path in (backend,asset):path.write_text(password);path.chmod(0o600)
            digest=hashlib.sha256(password.encode()).hexdigest()
            modules=next(p for p in ('/usr/lib/freeradius','/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p)/'rlm_pap.so').is_file())
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',freeradius=shutil.which('freeradius'),freeradius_modules=modules,
                freeradius_dictionaries='/usr/share/freeradius',freeradius_eap_md5=True)
            spec=dot1x_lab(rootfs,secret,digest,backend);spec['name']='owned-peer-'+str(os.getpid())
            spec['nodes'][0]['dot1x_supplicant']={'interface':'eth0','username':'learner','password_file':str(asset),'password_sha256':digest}
            spec['nodes'][1]['dot1x'].update(seconds=3,reauthentications=1);manager=Manager(spec['name'])
            def service():return Manager(spec['name']).inspect('PC1')['dot1x_supplicant']
            def gate():
                fresh=Manager(spec['name']);return observe(fresh,1,fresh.read()['spec']['nodes'][1])
            def ping(source='PC1',target='192.0.2.20'):
                return manager.crun('exec',source,'/bin/busybox','ping','-c','1','-W','1','-w','2',target,check=False,timeout=4).returncode
            def closed():
                self.assertTrue(gate()['configuration_verified']);self.assertFalse(gate()['admitted'])
                self.assertNotEqual(ping(),0);self.assertNotEqual(ping('PC2','192.0.2.10'),0)
            def admitted(future):
                until=time.monotonic()+7
                while time.monotonic()<until:
                    if gate()['admitted']:return
                    if future.done():self.fail('Managed peer did not admit: '+json.dumps(future.result()))
                    time.sleep(.03)
                self.fail('Managed peer did not reach admission')
            def session():return pool.submit(authenticate,Manager(spec['name']),'SW1',timeout=5)
            def owner():return Manager(spec['name']).read()['dot1x_supplicants']['PC1']
            def delivered(source='PC1',target='192.0.2.20'):
                until=time.monotonic()+2
                while ping(source,target)!=0:
                    self.assertTrue(gate()['configuration_verified'])
                    self.assertTrue(gate()['admitted'],'Delivery retry must remain within a verified admitted lease')
                    if time.monotonic()>=until:self.fail('Admitted managed peer did not deliver real data')
                    time.sleep(.03)
            def healthy(future):
                admitted(future);delivered();delivered('PC2','192.0.2.10')
                result=future.result(timeout=12)
                self.assertEqual(result['status'],'passed',result);self.assertEqual(result['completed_authentications'],2)
                self.assertEqual(result['radius_requests'],4);self.assertTrue(result['port_closed']);closed()
            try:
                with manager.locked():manager.start(spec)
                self.assertTrue(service()['configuration_verified']);self.assertTrue(service()['running']);closed()
                first=owner();self.assertTrue(alive(first))
                cmdline=(Path('/proc')/str(first['pid'])/'cmdline').read_bytes()
                self.assertIn(b'wpa_supplicant',cmdline);self.assertNotIn(password.encode(),cmdline)
                event=threading.Event();wire_event=threading.Event();radius=root/'radius.pcap';wire=root/'eapol.pcap'
                cap=pool.submit(capture,Manager(spec['name']),'SW1','eth1',radius,seconds=8,packets=100,expression='udp port 1812',ready=event.set)
                wire_cap=pool.submit(capture,Manager(spec['name']),'SW1','eth0',wire,seconds=8,packets=100,expression='ether proto 0x888e',ready=wire_event.set)
                self.assertTrue(event.wait(5));self.assertTrue(wire_event.wait(5));future=session();admitted(future)
                with manager.locked():manager.write_startup();saved=load_startup(spec['name'])
                self.assertEqual(saved['nodes'][0]['dot1x_supplicant'],spec['nodes'][0]['dot1x_supplicant'])
                self.assertNotIn('dot1x_supplicants',saved);self.assertNotIn('dot1x_workers',saved);self.assertNotIn(password,json.dumps(saved))
                healthy(future);cap.result(timeout=10);wire_cap.result(timeout=10)
                self.assertEqual(owner(),first,'Peer process must survive finite authenticator completion')
                frames=eapol_packets(wire.read_bytes());self.assertEqual(sum(p[0]==3 for p in frames),2)
                packets=radius_packets(radius.read_bytes());requests=[p for _,dst,p in packets if dst==1812];replies=[p for src,_,p in packets if src==1812]
                self.assertEqual(len(requests),4);self.assertEqual([p[0] for p in replies],[11,2,11,2])
                self.assertNotEqual(attrs(replies[0])[24],attrs(replies[2])[24])
                self.assertNotIn(password.encode(),wire.read_bytes());self.assertNotIn(secret.encode(),radius.read_bytes())
                # A second, independent CLI uses the same long-lived peer.
                completed=run([sys.executable,'-m','network_labs.appliances','dot1x-auth',spec['name'],'SW1','--json'],timeout=15)
                result=json.loads(completed.stdout);self.assertEqual(result['status'],'passed');self.assertEqual(result['completed_authentications'],2)
                self.assertEqual(owner(),first);closed();self.assertTrue(service()['running'])
                # Inspect/save must detect the declared peer's death. The NAS
                # remains independently finite and cannot reuse earlier success.
                future=session();admitted(future);os.kill(first['pid'],signal.SIGKILL)
                result=future.result(timeout=12)
                self.assertEqual(result['status'],'unknown',result);self.assertEqual(result['reason'],'AUTH_TIMEOUT')
                self.assertEqual(result['completed_authentications'],1);self.assertTrue(result['port_closed']);closed()
                self.assertFalse(service()['configuration_verified']);self.assertFalse(service()['running'])
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                with manager.locked():manager.stop()
                self.assertFalse(alive(first))
                # Offline credential drift is rejected before allocation.
                asset.write_text('changed-owned-peer-password');asset.chmod(0o600)
                with manager.locked(),self.assertRaises(ValueError):manager.start(saved)
                self.assertFalse(manager.directory.exists())
                asset.write_text(password);asset.chmod(0o600)
                with manager.locked():manager.start(saved)
                second=owner();self.assertNotEqual((second['pid'],second['starttime']),(first['pid'],first['starttime']));self.assertTrue(service()['configuration_verified']);closed()
                healthy(session())
                peer_files=list((manager.directory/'dot1x-peer').iterdir())
                self.assertEqual([p.name for p in peer_files],['eth0'])
                self.assertTrue(stat.S_ISSOCK(peer_files[0].stat().st_mode),'Peer runtime directory must contain only its control socket')
                # Separate-CLI teardown during admission must stop both owned
                # host workers before removing their namespaces/state.
                future=session();admitted(future);auth_owner=Manager(spec['name']).read()['dot1x_workers']['SW1']
                run([sys.executable,'-m','network_labs.appliances','stop',spec['name']],timeout=15)
                self.assertFalse(alive(second));self.assertFalse(alive(auth_owner));self.assertFalse(manager.directory.exists())
                self.assertIn(future.result(timeout=5)['status'],('passed','unknown'))
                # A separately pinned wrong peer password reaches real backend
                # rejection while the managed peer remains alive and closed.
                asset.write_text('wrong-owned-peer-password');asset.chmod(0o600)
                wrong=json.loads(json.dumps(saved));wrong['nodes'][0]['dot1x_supplicant']['password_sha256']=hashlib.sha256(asset.read_bytes()).hexdigest()
                with manager.locked():manager.start(wrong)
                result=session().result(timeout=10)
                self.assertEqual(result['status'],'failed',result);self.assertFalse(result['authenticated']);closed()
                self.assertTrue(service()['running']);self.assertTrue(service()['configuration_verified'])
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in routes.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
