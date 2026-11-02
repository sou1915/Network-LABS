"""Actual FreeRADIUS EAP-MD5 continuation, wire evidence, assets and cold restore."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from network_labs.appliances.__main__ import main
from network_labs.appliances.capture import capture
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.radius import probe
from network_labs.appliances.radius_server import start_servers
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from test_native_integration import unexpected_host_link_changes


def radius_packets(data):
    endian={b'\xd4\xc3\xb2\xa1':'<',b'\xa1\xb2\xc3\xd4':'>',b'\x4d\x3c\xb2\xa1':'<',b'\xa1\xb2\x3c\x4d':'>'}[data[:4]]
    offset=24; packets=[]
    while offset+16<=len(data):
        n=struct.unpack(endian+'4I',data[offset:offset+16])[2];offset+=16;frame=data[offset:offset+n];offset+=n
        if len(frame)<42 or frame[12:14]!=b'\x08\x00':continue
        ip=frame[14:]
        if ip[9]!=17:continue
        udp=ip[(ip[0]&15)*4:];source,dest,length,_=struct.unpack('!4H',udp[:8])
        if 1812 in (source,dest):packets.append((source,dest,udp[8:length]))
    return packets


def attrs(packet):
    values={}; offset=20
    while offset<len(packet):
        kind,n=packet[offset:offset+2]; values.setdefault(kind,[]).append(packet[offset+2:offset+n]);offset+=n
    return values


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeEAPMD5Tests(unittest.TestCase):
    def test_real_eap_md5_state_proof_denials_assets_outage_and_cold_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('freeradius','busybox','crun','ip','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        password='native-eap-md5-private-password';secret='native-eap-md5-private-secret'
        with tempfile.TemporaryDirectory() as d,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(d)/'saved'):
            root=Path(d);asset=root/'password';asset.write_text(password);asset.chmod(0o600)
            secret_file=root/'secret';secret_file.write_text(secret);secret_file.chmod(0o600)
            modules=next(p for p in ('/usr/lib/freeradius','/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p)/'rlm_pap.so').is_file())
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',freeradius=shutil.which('freeradius'),freeradius_modules=modules,freeradius_dictionaries='/usr/share/freeradius',freeradius_eap_md5=True)
            spec=radius_lab(rootfs,secret,hashlib.sha256(password.encode()).hexdigest(),eap_password_file=asset);spec['name']='eap-md5-'+str(os.getpid());manager=Manager(spec['name'])
            def auth(credential=password,username='learner',key=secret,protocol='eap-md5'):
                with manager.locked():return probe(manager,'PC1','192.0.2.20',username=username,password=credential,secret=key,timeout=1,protocol=protocol)
            def accepted():
                result=auth();self.assertEqual(result['status'],'passed',result)
                self.assertEqual(result['authentication']['requests_sent'],2);self.assertTrue(result['authentication']['challenge_verified'])
                self.assertTrue(result['authentication']['response_verified']);self.assertFalse(result['configuration_changed'])
                self.assertNotIn(password,json.dumps(result));self.assertNotIn(secret,json.dumps(result));return result
            try:
                with manager.locked():manager.start(spec)
                snapshot=json.dumps(manager.read()['spec'],sort_keys=True)
                ready=threading.Event();pcap=root/'eap.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=3,packets=30,expression='udp port 1812',ready=ready.set)
                self.assertTrue(ready.wait(5));accepted();future.result(timeout=6)
                packets=radius_packets(pcap.read_bytes());requests=[p for _,dst,p in packets if dst==1812];replies=[p for src,_,p in packets if src==1812]
                self.assertEqual(len(requests),2);self.assertEqual([p[0] for p in replies],[11,2])
                first,second=map(attrs,requests);challenge,final=map(attrs,replies)
                self.assertNotIn(2,first);self.assertNotIn(2,second);self.assertNotIn(24,first)
                self.assertEqual(second[24],challenge[24]);self.assertEqual(len(first[80][0]),16)
                identity=b''.join(first[79]);self.assertEqual(identity[0],2);self.assertEqual(identity[4:],b'\x01learner')
                demand=b''.join(challenge[79]);answer=b''.join(second[79]);self.assertEqual(demand[4:6],b'\x04\x10')
                self.assertEqual(answer[1],demand[1]);self.assertEqual(answer[6:22],hashlib.md5(bytes([demand[1]])+password.encode()+demand[6:22]).digest())
                self.assertEqual(b''.join(final[79]),struct.pack('!BBH',3,answer[1],4))
                self.assertNotIn(password.encode(),pcap.read_bytes());self.assertNotIn(secret.encode(),pcap.read_bytes())
                for options in ({'credential':'incorrect-password'},{'username':'unknown'}):
                    denied=auth(**options);self.assertEqual(denied['status'],'failed',denied);self.assertTrue(denied['authentication']['response_verified'])
                unknown=auth(key='incorrect-private-shared-secret');self.assertEqual(unknown['status'],'unknown');self.assertFalse(unknown['authentication']['response_verified'])
                self.assertEqual(auth(protocol='pap')['status'],'passed')
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(['radius-eap-md5',spec['name'],'PC1','192.0.2.20','--username','learner','--password-file',str(asset),'--secret-file',str(secret_file),'--json']),0)
                self.assertEqual(json.loads(output.getvalue())['protocol'],'eap-md5');self.assertNotIn(password,output.getvalue())
                self.assertEqual(json.dumps(manager.read()['spec'],sort_keys=True),snapshot)
                self.assertTrue(manager.inspect('PC2')['radius_server']['configuration_verified'])
                asset.write_text('changed-private-password')
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                asset.write_text(password)
                observed=manager.inspect('PC2')['radius_server']
                manager.crun('exec','PC2','/bin/busybox','kill','-TERM',str(observed['process']['pid']))
                until=time.monotonic()+5
                while manager.inspect('PC2')['radius_server']['udp_socket']['status']!='absent':
                    if time.monotonic()>=until:self.fail('RADIUS listener did not stop')
                    time.sleep(.05)
                self.assertEqual(auth()['status'],'unknown')
                with manager.locked():start_servers(manager)
                until=time.monotonic()+5
                while manager.inspect('PC2')['radius_server']['udp_socket']['status']=='absent':
                    if time.monotonic()>=until:self.fail('RADIUS listener did not recover')
                    time.sleep(.05)
                accepted()
                with manager.locked():manager.write_startup();saved=load_startup(spec['name']);manager.stop()
                self.assertEqual(saved['nodes'][2]['radius_server']['users']['learner']['password_file'],str(asset))
                self.assertNotIn(password,json.dumps(saved));asset.write_text('changed-private-password')
                with manager.locked(),self.assertRaises((RuntimeFailure,ValueError)):manager.start(saved)
                self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
                asset.write_text(password)
                with manager.locked():manager.start(saved)
                accepted()
            finally:
                asset.write_text(password)
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
