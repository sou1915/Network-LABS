"""Real closed-session Stop persistence through lab teardown and manual replay."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from network_labs.appliances.__main__ import main
from network_labs.appliances.capture import capture
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.radius_login import login
from network_labs.appliances.radius_outbox import folder,pending,flush
from network_labs.appliances.radius_server import ACCOUNTING_FILE
from network_labs.appliances.runtime import Manager,run,static_busybox_rootfs
from network_labs.appliances.firewall import fingerprint
from test_native_radius_accounting_retry_integration import requests
from test_native_radius_accounting_retry import attrs
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeOutboxTests(unittest.TestCase):
    def test_real_stop_survives_teardown_policy_change_failed_replay_and_receipt(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('freeradius','crun','busybox','ip','nft','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        nft=fingerprint(json.loads(run(['nft','-j','list','ruleset']).stdout));secret='native-durable-outbox-secret';password='native-durable-outbox-password';launches=[]
        with tempfile.TemporaryDirectory() as d,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(d)/'saved'):
            root=Path(d);modules=next(p for p in ('/usr/lib/freeradius','/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p)/'rlm_pap.so').is_file())
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',freeradius=shutil.which('freeradius'),freeradius_modules=modules,freeradius_dictionaries='/usr/share/freeradius')
            spec=radius_lab(rootfs,secret,hashlib.sha256(password.encode()).hexdigest(),allow_shell=True,accounting=True,accounting_retries=1,accounting_outbox=True);spec['name']='outbox-native-'+str(os.getpid());manager=Manager(spec['name'])
            def drop():
                manager.ns(0,'nft','add','table','inet','outbox_loss')
                manager.ns(0,'nft','add','chain','inet','outbox_loss','input','{ type filter hook input priority 0; policy accept; }')
                manager.ns(0,'nft','add','rule','inet','outbox_loss','input','ip','saddr','192.0.2.20','udp','sport','1813','counter','drop')
            def shell(args,**options):
                launches.append(1);completed=subprocess.run(args,input='/bin/busybox id\n/bin/busybox sleep 1\nexit\n',capture_output=True,text=True,timeout=min(5,options['timeout']))
                self.assertEqual(completed.returncode,0,completed.stderr);self.assertIn('uid=65532',completed.stdout);return completed.returncode
            def session(lose_stop=False):
                def launch(args,**options):
                    if lose_stop:drop()
                    return shell(args,**options)
                return login(manager,'PC1','192.0.2.20',username='learner',password=password,secret=secret,timeout=1,terminal=False,seconds=5,launcher=launch)
            try:
                with manager.locked():
                    manager.start(spec);result=session(True)
                    self.assertEqual(result['status'],'unknown',result);self.assertTrue(result['cleanup_complete']);self.assertEqual(result['error'],'ACCOUNTING_STOP_UNCONFIRMED')
                    self.assertEqual(result['accounting']['outbox']['status'],'pending');self.assertEqual(pending(manager)['pending'],1)
                    sid=result['session_id'];path=folder(manager)/(sid+'.json');self.assertEqual(path.stat().st_mode&0o777,0o600);self.assertEqual(path.stat().st_uid,0)
                    self.assertNotIn(secret,path.read_text());self.assertNotIn(password,path.read_text())
                    event_record=json.loads(path.read_text());self.assertGreaterEqual(event_record['session_seconds'],1)
                    manager.ns(0,'nft','delete','table','inet','outbox_loss');manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    self.assertNotIn(sid,json.dumps(saved));manager.stop()
                self.assertFalse(manager.directory.exists());self.assertTrue(path.is_file())
                with redirect_stdout(io.StringIO()) as output:self.assertEqual(main(['radius-accounting-pending',spec['name'],'--json']),0)
                self.assertEqual(json.loads(output.getvalue())['pending'],1);self.assertNotIn(secret,output.getvalue())
                # Reusing the name with a rotated backend secret must not replay an old event.
                changed=copy.deepcopy(saved);changed['nodes'][2]['radius_server']['clients'][0]['secret']='rotated-native-outbox-secret'
                manager=Manager(spec['name'])
                with manager.locked():
                    manager.start(changed);blocked=flush(manager,limit=1,timeout=1)
                    self.assertEqual(blocked['attempted'],0,blocked);self.assertEqual(blocked['remaining'],1);manager.stop()
                    manager.start(saved)
                # Restoration itself sends nothing; it does not open a session or flush.
                self.assertEqual(len(launches),1);self.assertEqual(pending(manager)['pending'],1)
                existing=manager.crun('exec','PC2','/bin/cat',ACCOUNTING_FILE,check=False)
                self.assertTrue(existing.returncode or not existing.stdout)
                drop()
                with manager.locked():uncertain=flush(manager,limit=1,timeout=1)
                self.assertEqual(uncertain['remaining'],1);self.assertEqual(uncertain['status'],'unknown');self.assertTrue(path.exists())
                manager.ns(0,'nft','delete','table','inet','outbox_loss')
                event=threading.Event();pcap=root/'replay.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=3,packets=50,expression='udp port 1813',ready=event.set)
                self.assertTrue(event.wait(5))
                with redirect_stdout(io.StringIO()) as output:self.assertEqual(main(['radius-accounting-flush',spec['name'],'--limit','1','--timeout','2','--json']),0)
                flushed=json.loads(output.getvalue());self.assertEqual(flushed['remaining'],0);self.assertEqual(flushed['attempted'],1)
                self.assertNotIn(secret,output.getvalue());self.assertEqual(len(launches),1);self.assertFalse(path.exists())
                future.result(timeout=6);captured=requests(pcap.read_bytes());self.assertEqual(len(captured),1)
                fields=attrs(captured[0]);self.assertEqual(struct.unpack('!I',fields[40])[0],2);self.assertEqual(fields[44].decode(),sid)
                self.assertGreaterEqual(struct.unpack('!I',fields[41])[0],1)
                self.assertEqual(struct.unpack('!I',fields[46])[0],event_record['session_seconds'])
                self.assertEqual(struct.unpack('!I',fields[49])[0],event_record['terminate_cause'])
                records=manager.crun('exec','PC2','/bin/cat',ACCOUNTING_FILE).stdout.splitlines()
                self.assertTrue(records);self.assertTrue(all(line.startswith('Stop|'+sid+'|') for line in records))
                with manager.locked():
                    healthy=session();self.assertEqual(healthy['status'],'passed',healthy);self.assertEqual(healthy['accounting']['outbox']['status'],'cleared')
                    self.assertEqual(pending(manager)['pending'],0);self.assertEqual(len(launches),2);manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        self.assertEqual(fingerprint(json.loads(run(['nft','-j','list','ruleset']).stdout)),nft)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
