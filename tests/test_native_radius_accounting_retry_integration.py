"""Actual FreeRADIUS receipts with deterministic response loss in an owned NAS."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
from network_labs.appliances.capture import capture
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.radius_login import login
from network_labs.appliances.radius_accounting import send
from network_labs.appliances.radius_accounting_worker import verified_response
from network_labs.appliances.radius_server import ACCOUNTING_FILE
from network_labs.appliances.runtime import Manager,run,static_busybox_rootfs
from network_labs.appliances.firewall import fingerprint
from test_native_radius_accounting_retry import attrs
from test_native_integration import unexpected_host_link_changes


def requests(data):
    endian={b'\xd4\xc3\xb2\xa1':'<',b'\xa1\xb2\xc3\xd4':'>',b'\x4d\x3c\xb2\xa1':'<',b'\xa1\xb2\x3c\x4d':'>'}.get(data[:4]);out=[];offset=24
    if endian is None:raise ValueError('Unsupported pcap header')
    while offset+16<=len(data):
        n=struct.unpack(endian+'4I',data[offset:offset+16])[2];offset+=16;frame=data[offset:offset+n];offset+=n
        if len(frame)<42 or frame[12:14]!=b'\x08\x00':continue
        ip=frame[14:];header=(ip[0]&15)*4
        if ip[9]!=17:continue
        udp=ip[header:];src,dst,n,_=struct.unpack('!4H',udp[:8])
        if dst==1813 and len(udp)>=n and udp[8:9]==b'\x04':out.append(udp[8:n])
    return out


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeAccountingRetryTests(unittest.TestCase):
    def test_actual_loss_start_gate_stop_uncertainty_duplicates_and_saved_restart(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('freeradius','crun','busybox','ip','nft','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        nft=fingerprint(json.loads(run(['nft','-j','list','ruleset']).stdout));secret='native-account-retry-secret';password='native-account-retry-password'
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);modules=next(p for p in ('/usr/lib/freeradius','/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p)/'rlm_pap.so').is_file())
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',freeradius=shutil.which('freeradius'),freeradius_modules=modules,freeradius_dictionaries='/usr/share/freeradius')
            spec=radius_lab(rootfs,secret,hashlib.sha256(password.encode()).hexdigest(),allow_shell=True,accounting=True,accounting_retries=2);spec['name']='account-retry-'+str(os.getpid());manager=Manager(spec['name']);launches=[]
            def loss(mode):
                manager.ns(0,'nft','flush','chain','inet','account_retry','input')
                if mode=='pass':return
                rule=['nft','add','rule','inet','account_retry','input','ip','saddr','192.0.2.20','udp','sport','1813']
                if mode=='two':rule+=['numgen','inc','mod','3','<','2']
                manager.ns(0,*rule,'counter','drop')
            def shell(args,**options):
                launches.append(1)
                completed=subprocess.run(args,input='/bin/busybox id\n/bin/busybox cat /proc/self/status\nexit\n',capture_output=True,text=True,timeout=min(5,options['timeout']))
                self.assertEqual(completed.returncode,0,completed.stderr);self.assertIn('uid=65532',completed.stdout)
                fields=dict(line.split(':',1) for line in completed.stdout.splitlines() if ':' in line)
                self.assertEqual(fields['NoNewPrivs'].strip(),'1');self.assertEqual(int(fields['CapEff'].strip(),16),0)
                return completed.returncode
            def session(launcher=shell):
                return login(manager,'PC1','192.0.2.20',username='learner',password=password,secret=secret,timeout=3,terminal=False,seconds=5,launcher=launcher)
            try:
                with manager.locked():manager.start(spec)
                manager.ns(0,'nft','add','table','inet','account_retry')
                manager.ns(0,'nft','add','chain','inet','account_retry','input','{ type filter hook input priority 0; policy accept; }')
                loss('two');event=threading.Event();pcap=root/'accounting.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=8,packets=500,expression='udp port 1813',ready=event.set)
                self.assertTrue(event.wait(5))
                with manager.locked():accepted=session()
                self.assertEqual(accepted['status'],'passed',accepted);self.assertTrue(accepted['cleanup_complete']);self.assertEqual(len(launches),1)
                for event in ('start','stop'):
                    receipt=accepted['accounting'][event];self.assertEqual(receipt['status'],'passed',receipt);self.assertEqual(receipt['requests_sent'],3);self.assertTrue(receipt['response_verified'])
                future.result(timeout=11)
                captured=requests(pcap.read_bytes());self.assertEqual(len(captured),6)
                for event in (1,2):
                    group=[p for p in captured if struct.unpack('!I',attrs(p)[40])[0]==event]
                    self.assertEqual(len(group),3);self.assertTrue(all(attrs(p)[44].decode()==accepted['session_id'] for p in group))
                    for p in group:self.assertEqual(p[4:20],hashlib.md5(p[:4]+bytes(16)+p[20:]+secret.encode()).digest())
                    self.assertGreaterEqual(struct.unpack('!I',attrs(group[-1])[41])[0],1)
                    for first,second in zip(group,group[1:]):
                        if attrs(first)[41]==attrs(second)[41]:self.assertEqual(first,second)
                        else:self.assertNotEqual(first[1],second[1]);self.assertNotEqual(first[4:20],second[4:20])
                rules=json.loads(manager.ns(0,'nft','-j','list','chain','inet','account_retry','input').stdout)
                drops=sum(expr['counter']['packets'] for row in rules['nftables'] for expr in row.get('rule',{}).get('expr',[]) if 'counter' in expr)
                self.assertEqual(drops,4)
                records=manager.crun('exec','PC2','/bin/cat',ACCOUNTING_FILE).stdout.splitlines()
                for event in ('Start','Stop'):self.assertTrue(any(line.startswith(event+'|'+accepted['session_id']+'|') for line in records))
                # The backend may append duplicates. No exactly-once storage is asserted.
                loss('all');blocked=Mock()
                with manager.locked():denied=session(blocked)
                blocked.assert_not_called();self.assertEqual(denied['authentication']['status'],'passed')
                self.assertEqual(denied['error'],'ACCOUNTING_START_UNCONFIRMED');self.assertFalse(denied['session_attempted']);self.assertTrue(denied['cleanup_complete'])
                self.assertEqual(denied['accounting']['start']['requests_sent'],3)
                loss('pass')
                def lose_stop(args,**options):loss('all');return shell(args,**options)
                with manager.locked():uncertain=session(lose_stop)
                self.assertTrue(uncertain['session_attempted']);self.assertTrue(uncertain['cleanup_complete']);self.assertEqual(len(launches),2)
                self.assertEqual(uncertain['status'],'unknown');self.assertEqual(uncertain['error'],'ACCOUNTING_STOP_UNCONFIRMED')
                self.assertEqual(uncertain['accounting']['start']['requests_sent'],1);self.assertEqual(uncertain['accounting']['stop']['requests_sent'],3)
                loss('pass')
                with manager.locked():
                    receipt=send(manager,'PC1','192.0.2.20',username='learner',secret=secret,session_id=uncertain['session_id'],event='stop')
                    self.assertEqual(receipt['status'],'passed');self.assertEqual(receipt['requests_sent'],1)
                    manager.ns(0,'nft','delete','table','inet','account_retry')
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec);manager.stop();manager.start(saved)
                    restored=session()
                    self.assertEqual(restored['status'],'passed',restored);self.assertTrue(restored['cleanup_complete'])
                    self.assertEqual(restored['accounting']['start']['requests_sent'],1);self.assertEqual(restored['accounting']['stop']['requests_sent'],1)
                    self.assertEqual(saved['nodes'][0]['radius_access']['accounting_retries'],2);manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        self.assertEqual(fingerprint(json.loads(run(['nft','-j','list','ruleset']).stdout)),nft)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
