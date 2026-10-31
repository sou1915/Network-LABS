"""Real guest logger -> rsyslog Unix input -> TCP collector, including suspended retry."""
from concurrent.futures import ThreadPoolExecutor
import copy
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
from network_labs.appliances.examples import syslog_tcp_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.syslog_server import LOG, start_server
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeSyslogForwardTests(unittest.TestCase):
    def test_automatic_tcp_suspended_retry_volatile_queue_drift_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        for tool in ('busybox','crun','rsyslogd','ip','tcpdump'): self.assertIsNotNone(shutil.which(tool), tool)
        namespaces = run(['ip','netns','list']).stdout
        before = {(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline = {(family,kind): run(['ip','-j',family,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for family in ('-4','-6') for kind in ('route','rule')}
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool, patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder); rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',rsyslog=shutil.which('rsyslogd'),rsyslog_tcp=True,rsyslog_forward=True)
            spec=syslog_tcp_lab(rootfs,forward=True); spec['name']='syslog-forward-'+str(os.getpid()); manager=Manager(spec['name'])
            def logs(node='PC1',path=LOG): return manager.crun('exec',node,'/bin/busybox','cat',path,check=False).stdout
            def sender_log():
                p=manager.directory/'PC2/syslog.log'; return p.read_text(errors='replace') if p.exists() else ''
            def wait(predicate,label,seconds=15):
                end=time.monotonic()+seconds
                while time.monotonic()<end:
                    if predicate(): return
                    time.sleep(.1)
                self.fail(label+': sender='+sender_log()+'; collector='+logs())
            def ready():
                wait(lambda:'192.0.2.10:514' in manager.ns(0,'ss','-H','-ltn','sport = :514').stdout,'collector not ready')
                wait(lambda:manager.crun('exec','PC2','/bin/busybox','test','-S','/dev/log',check=False).returncode==0,'sender socket not ready')
            def emit(token): manager.crun('exec','PC2','/bin/busybox','logger','-p','local0.notice','-t','native-forward',token,timeout=3)
            def received(token):
                wait(lambda:token in logs(),'collector did not store '+token,20)
                self.assertTrue(any(line.startswith('192.0.2.20 <133>') and token in line for line in logs().splitlines()),logs())
            def suspend_collector():
                offset=len(sender_log())
                manager.crun('exec','PC1','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/rsyslogd.pid)"')
                wait(lambda:not manager.ns(0,'ss','-H','-ltn','sport = :514').stdout,'collector still listening')
                count=0
                def suspended():
                    nonlocal count
                    count+=1; emit('OUTAGE-TRIGGER-'+str(count))
                    return 'suspended' in sender_log()[offset:].lower()
                wait(suspended,'TCP action did not report a fresh suspension',20)
            try:
                with manager.locked(): manager.start(spec)
                ready(); saved_state=copy.deepcopy(manager.read())
                event=threading.Event(); pcap=root/'forward.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=5,packets=1000,expression='port 514',ready=event.set)
                self.assertTrue(event.wait(5))
                for token in ('AUTO-TCP-ONE','AUTO-TCP-TWO','AUTO-TCP-THREE'): emit(token); received(token)
                future.result(timeout=8)
                decoded=run(['tcpdump','-nn','-r',pcap]).stdout
                self.assertIn(b'AUTO-TCP-ONE',pcap.read_bytes()); self.assertNotIn('UDP',decoded)
                suspend_collector(); emit('QUEUED-AFTER-SUSPENSION')
                wait(lambda:'QUEUED-AFTER-SUSPENSION' in logs('PC2','/run/messages'),'local logging blocked while TCP was down')
                self.assertNotIn('QUEUED-AFTER-SUSPENSION',logs())
                self.assertTrue(manager.inspect('PC2')['management']['configuration_verified'])
                start_server(manager,spec['nodes'][0]); ready(); received('QUEUED-AFTER-SUSPENSION')
                emit('AUTOMATIC-RECOVERY-OK'); received('AUTOMATIC-RECOVERY-OK')
                self.assertEqual(manager.read(),saved_state)
                with manager.locked():
                    config=manager.directory/'PC2/files/syslog-forward.conf'; original=config.read_text(); config.write_text(original+'# drift\n')
                    with self.assertRaises(RuntimeFailure): manager.write_startup()
                    config.write_text(original)
                suspend_collector(); emit('VOLATILE-QUEUE-NOT-SNAPSHOT')
                wait(lambda:'VOLATILE-QUEUE-NOT-SNAPSHOT' in logs('PC2','/run/messages'),'second outage local storage unavailable')
                with manager.locked():
                    manager.write_startup(); saved=load_startup(spec['name']); self.assertEqual(saved,spec)
                    manager.stop(); manager.start(saved)
                ready(); self.assertNotIn('AUTOMATIC-RECOVERY-OK',logs())
                self.assertNotIn('VOLATILE-QUEUE-NOT-SNAPSHOT',logs('PC2','/run/messages'))
                emit('COLD-RESTORE-OK'); received('COLD-RESTORE-OK')
                self.assertNotIn('VOLATILE-QUEUE-NOT-SNAPSHOT',logs())
                with manager.locked(): manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (family,kind),value in baseline.items(): self.assertEqual(run(['ip','-j',family,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
