"""Actual SIGKILL orphan recovery with original cgroup and runtime evidence."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
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
from network_labs.appliances.radius_login import login
from network_labs.appliances import radius_journal as journal,radius_outbox as outbox
from network_labs.appliances.radius_server import ACCOUNTING_FILE
from network_labs.appliances.runtime import Manager,run,static_busybox_rootfs
from test_native_radius_accounting_retry_integration import requests
from test_native_radius_accounting_retry import attrs
from test_native_integration import unexpected_host_link_changes

CHILD=r'''
import json,subprocess,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from network_labs.appliances import runtime
from network_labs.appliances.radius_login import login
r=json.load(sys.stdin);runtime.CONFIG_ROOT=Path(r['config_root'])
def launch(args,**options):
 return subprocess.run(args,input='/bin/busybox sleep 60\n',capture_output=True,text=True,timeout=options['timeout']).returncode
with runtime.Manager(r['lab']).locked() as manager:
 result=login(manager,'PC1','192.0.2.20',username='learner',password=r['password'],secret=r['secret'],timeout=2,seconds=60,launcher=launch)
 sys.exit(0 if result['status']=='passed' else 1)
'''


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeJournalTests(unittest.TestCase):
    def test_real_killed_supervisor_guarded_termination_stop_handoff_and_stale_runtime(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('freeradius','crun','busybox','ip','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        secret='native-session-journal-secret';password='native-session-journal-password';children=[]
        with tempfile.TemporaryDirectory() as d,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(d)/'saved'):
            root=Path(d);modules=next(p for p in ('/usr/lib/freeradius','/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p)/'rlm_pap.so').is_file())
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',freeradius=shutil.which('freeradius'),freeradius_modules=modules,freeradius_dictionaries='/usr/share/freeradius')
            spec=radius_lab(rootfs,secret,hashlib.sha256(password.encode()).hexdigest(),allow_shell=True,accounting=True,accounting_outbox=True,accounting_journal=True);spec['name']='journal-native-'+str(os.getpid());manager=Manager(spec['name'])
            def orphan():
                existing={r['session_id'] for r in journal.pending(manager)['entries']}
                with (root/'child.log').open('ab') as log:
                    process=subprocess.Popen([sys.executable,'-I','-c',CHILD,str(Path(__file__).parents[1])],stdin=subprocess.PIPE,stdout=log,stderr=log,start_new_session=True,text=True)
                children.append(process);process.stdin.write(json.dumps({'lab':spec['name'],'config_root':str(root/'saved'),'password':password,'secret':secret}));process.stdin.close()
                until=time.monotonic()+12
                while time.monotonic()<until:
                    records=journal.pending(manager)['entries'];fresh=[r for r in records if r['session_id'] not in existing]
                    if fresh:
                        sid=fresh[0]['session_id'];record=journal.read(journal.directory(manager)/(sid+'.json'),manager);path=journal.group_path(manager,record)
                        if path.exists() and not journal.empty(path):return process,sid,path
                    if process.poll() is not None:self.fail('Journal supervisor exited before creating an active owned session')
                    time.sleep(.1)
                self.fail('Journaled session did not become populated')
            try:
                with manager.locked():manager.start(spec);manager.write_startup();saved=load_startup(spec['name'])
                child,sid,path=orphan()
                with redirect_stdout(io.StringIO()) as output:self.assertEqual(main(['radius-accounting-sessions',spec['name'],'--json']),0)
                self.assertIn(sid,output.getvalue());self.assertNotIn(secret,output.getvalue());self.assertNotIn(password,output.getvalue())
                # The CLI rejects the live owner before waiting on its lock.
                with redirect_stdout(io.StringIO()) as output:self.assertEqual(main(['radius-accounting-reconcile',spec['name'],sid,'--terminate','--json']),1)
                refused=json.loads(output.getvalue());self.assertEqual(refused['error'],'SUPERVISOR_STILL_ACTIVE');self.assertFalse(journal.empty(path))
                child.kill();child.wait(timeout=3)
                with manager.locked():
                    refused=journal.reconcile(manager,sid);self.assertEqual(refused['error'],'SESSION_STILL_POPULATED')
                    self.assertEqual(outbox.pending(manager)['pending'],0);self.assertFalse(journal.empty(path))
                records=manager.crun('exec','PC2','/bin/cat',ACCOUNTING_FILE).stdout
                self.assertTrue(any(line.startswith('Start|'+sid+'|') for line in records.splitlines()))
                event=threading.Event();quiet=root/'reconcile.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',quiet,seconds=3,packets=50,expression='udp port 1813',ready=event.set)
                self.assertTrue(event.wait(5))
                with redirect_stdout(io.StringIO()) as output:self.assertEqual(main(['radius-accounting-reconcile',spec['name'],sid,'--terminate','--json']),0)
                result=json.loads(output.getvalue());self.assertTrue(result['terminated']);self.assertTrue(result['stop_queued']);self.assertFalse(path.exists())
                future.result(timeout=6);self.assertEqual(requests(quiet.read_bytes()),[])
                self.assertEqual(manager.crun('exec','PC2','/bin/cat',ACCOUNTING_FILE).stdout,records)
                self.assertEqual(journal.pending(manager)['pending'],0);self.assertEqual(outbox.pending(manager)['pending'],1)
                stop=outbox.read(outbox.folder(manager)/(sid+'.json'),manager);self.assertEqual(stop['session_seconds'],0);self.assertEqual(stop['terminate_cause'],9)
                event=threading.Event();pcap=root/'stop.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=3,packets=50,expression='udp port 1813',ready=event.set)
                self.assertTrue(event.wait(5))
                with manager.locked():self.assertEqual(outbox.flush(manager,limit=1)['status'],'passed')
                future.result(timeout=6);packets=requests(pcap.read_bytes());self.assertEqual(len(packets),1)
                self.assertEqual(int.from_bytes(attrs(packets[0])[40],'big'),2);self.assertEqual(attrs(packets[0])[44].decode(),sid)
                self.assertEqual(int.from_bytes(attrs(packets[0])[49],'big'),9);self.assertEqual(outbox.pending(manager)['pending'],0)
                # A second killed owner is deliberately left without an empty
                # checkpoint. Recreation must never turn absence into cleanup proof.
                child,stale,old_path=orphan();child.kill();child.wait(timeout=3)
                with manager.locked():
                    manager.stop();manager.start(saved)
                    refused=journal.reconcile(manager,stale,terminate=True)
                    self.assertEqual(refused['error'],'RUNTIME_IDENTITY_CHANGED',refused);self.assertEqual(outbox.pending(manager)['pending'],0)
                self.assertEqual(journal.pending(manager)['pending'],1)
                launches=[]
                def healthy(args,**options):
                    launches.append(1);p=subprocess.run(args,input='/bin/busybox id\nexit\n',capture_output=True,text=True,timeout=5)
                    self.assertEqual(p.returncode,0,p.stderr);self.assertIn('uid=65532',p.stdout);return p.returncode
                with manager.locked():
                    completed=login(manager,'PC1','192.0.2.20',username='learner',password=password,secret=secret,seconds=5,launcher=healthy)
                    self.assertEqual(completed['status'],'passed',completed);self.assertEqual(completed['accounting']['journal']['status'],'handed_off')
                    self.assertEqual(len(launches),1);self.assertEqual(journal.pending(manager)['pending'],1);self.assertEqual(outbox.pending(manager)['pending'],0);manager.write_startup()
            finally:
                for process in children:
                    if process.poll() is None:process.kill()
                    process.wait(timeout=3)
                if manager.directory.exists():
                    with manager.locked():
                        for record in journal.pending(manager)['entries']:
                            journal.reconcile(manager,record['session_id'],terminate=True)
                        manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
