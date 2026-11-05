"""Real TCP/TLS queue replay after sender SIGKILL inside the retained node."""
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
from network_labs.appliances.examples import syslog_tcp_lab,syslog_tls_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.syslog_forward import SPOOL,PID,command,start as start_sender
from network_labs.appliances.syslog_server import LOG,start_server
from test_native_integration import unexpected_host_link_changes
from test_native_syslog_tls_integration import certificates


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeSyslogDiskQueueTests(unittest.TestCase):
    def test_tcp_tls_spooled_markers_survive_sender_crash_but_not_lab_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('openssl','rsyslogd','busybox','crun','ip','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(family,kind):run(['ip','-j',family,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for family in ('-4','-6') for kind in ('route','rule')}
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);ca,_,leaves=certificates(root)
            plain=static_busybox_rootfs(shutil.which('busybox'),root/'plain',rsyslog=shutil.which('rsyslogd'),rsyslog_tcp=True,rsyslog_forward=True)
            def tls_image(label,identity):
                return static_busybox_rootfs(shutil.which('busybox'),root/label,rsyslog=shutil.which('rsyslogd'),rsyslog_tls=True,
                    syslog_ca=ca,syslog_certificate=leaves[identity][0],syslog_private_key=leaves[identity][1])
            server=tls_image('server','collector.lab');client=tls_image('client','sender.lab')
            for transport in ('tcp','tls'):
                with self.subTest(transport=transport):
                    spec=(syslog_tcp_lab(plain,forward=True,disk_queue=True) if transport=='tcp' else
                          syslog_tls_lab(server,client,'collector.lab','sender.lab',verify_peer_on_start=True,disk_queue=True))
                    spec['name']='syslog-disk-'+transport+'-'+str(os.getpid());manager=Manager(spec['name']);port=514 if transport=='tcp' else 6514
                    node=spec['nodes'][2]
                    def logs(name='PC1',path=LOG):return manager.crun('exec',name,'/bin/busybox','cat',path,check=False).stdout
                    def diagnostic():
                        path=manager.directory/'PC2/syslog.log';return path.read_text(errors='replace') if path.exists() else ''
                    def wait(predicate,label,seconds=15):
                        until=time.monotonic()+seconds
                        while time.monotonic()<until:
                            if predicate():return
                            time.sleep(.1)
                        self.fail(label+': '+diagnostic())
                    def emit(token):manager.crun('exec','PC2','/bin/busybox','logger','-p','local0.notice','-t','disk-native',token,timeout=3)
                    def received(token):wait(lambda:token in logs(),'Collector missing '+token,20)
                    def ready():
                        wait(lambda:('192.0.2.10:'+str(port)) in manager.ns(0,'ss','-H','-ltn','sport = :'+str(port)).stdout,'Collector unavailable')
                        wait(lambda:manager.crun('exec','PC2','/bin/busybox','test','-S','/dev/log',check=False).returncode==0,'Sender socket unavailable')
                    def suspend():
                        offset=len(diagnostic());local_offset=len(logs('PC2','/run/messages'))
                        manager.crun('exec','PC1','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/rsyslogd.pid)"')
                        wait(lambda:not manager.ns(0,'ss','-H','-ltn','sport = :'+str(port)).stdout,'Collector still listening')
                        def suspended():
                            emit('OUTAGE-TRIGGER-'+transport)
                            return 'suspended' in (diagnostic()[offset:]+logs('PC2','/run/messages')[local_offset:]).lower()
                        wait(suspended,'No fresh forwarding suspension',20)
                    def spooled(token):
                        # Inspect only fixture marker presence; never replay
                        # or modify any rsyslog queue record in this test.
                        return manager.crun('exec','PC2','/bin/sh','-c','/bin/busybox grep -a -l '+token+' '+SPOOL+'/forward*',check=False,timeout=3).returncode==0
                    def sender_pid():
                        result=manager.crun('exec','PC2','/bin/busybox','cat',PID,check=False)
                        return int(result.stdout.strip()) if result.returncode==0 and result.stdout.strip().isdigit() else None
                    def status(pid):
                        result=manager.crun('exec','PC2','/bin/busybox','cat','/proc/'+str(pid)+'/stat',check=False)
                        return result.stdout.rsplit(')',1)[1].split()[0] if result.returncode==0 else None
                    try:
                        with manager.locked():manager.start(spec)
                        ready();emit('BEFORE-'+transport);received('BEFORE-'+transport)
                        declared=copy.deepcopy(manager.read());container_pid=json.loads(manager.crun('state','PC2').stdout)['pid']
                        observed=manager.inspect('PC2')['management'];self.assertTrue(observed['configuration_verified'])
                        self.assertEqual(observed['syslog_spool']['storage'],'owned node overlay')
                        suspend();tokens=['SPOOLED-'+transport+'-'+str(i) for i in range(3)]
                        for token in tokens:
                            emit(token);wait(lambda:spooled(token),'Marker never reached disk queue: '+token)
                            self.assertNotIn(token,logs())
                        self.assertEqual(manager.crun('exec','PC2','/bin/busybox','stat','-c','%a:%u:%g',SPOOL).stdout,'700:0:0\n')
                        modes=manager.crun('exec','PC2','/bin/sh','-c','/bin/busybox stat -c "%a:%u:%g" '+SPOOL+'/forward*').stdout.splitlines()
                        self.assertTrue(modes);self.assertTrue(all(mode=='600:0:0' for mode in modes),modes)
                        old_pid=sender_pid();self.assertIsNotNone(old_pid)
                        argv=manager.crun('exec','PC2','/bin/busybox','cat','/proc/'+str(old_pid)+'/cmdline').stdout.rstrip('\0').split('\0')
                        self.assertEqual(argv,command());self.assertNotEqual(status(old_pid),'Z')
                        manager.crun('exec','PC2','/bin/busybox','kill','-KILL',str(old_pid))
                        wait(lambda:status(old_pid) in (None,'Z'),'Killed sender is still running')
                        self.assertTrue(manager.inspect('PC2')['management']['configuration_verified'])  # Conformity is not liveness.
                        for token in tokens:self.assertTrue(spooled(token))
                        # Clear only the verified dead sender's PID file and
                        # volatile local output. The fixture leaves all spool
                        # bytes in place and never resubmits the markers.
                        manager.crun('exec','PC2','/bin/busybox','rm','-f',PID,'/run/messages')
                        start_sender(manager,node)
                        wait(lambda:sender_pid() is not None and sender_pid()!=old_pid and status(sender_pid()) not in (None,'Z'),'Sender did not restart')
                        self.assertEqual(json.loads(manager.crun('state','PC2').stdout)['pid'],container_pid)
                        event=threading.Event();wire=root/(transport+'.pcap')
                        cap=pool.submit(capture,Manager(spec['name']),'PC2','eth0',wire,seconds=5,packets=1000,expression='tcp port '+str(port),ready=event.set)
                        self.assertTrue(event.wait(5));start_server(manager,spec['nodes'][0]);ready()
                        for token in tokens:received(token)
                        cap.result(timeout=9);self.assertTrue(run(['tcpdump','-nn','-r',wire]).stdout)
                        if transport=='tcp':self.assertIn(tokens[-1].encode(),wire.read_bytes())
                        else:
                            for token in tokens:self.assertNotIn(token.encode(),wire.read_bytes())
                        emit('RECOVERED-'+transport);received('RECOVERED-'+transport)
                        self.assertEqual(manager.read(),declared)
                        manager.crun('exec','PC2','/bin/busybox','chmod','777',SPOOL)
                        with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                        manager.crun('exec','PC2','/bin/busybox','chmod','700',SPOOL)
                        config=manager.directory/'PC2/files/syslog-forward.conf';original=config.read_text();config.write_text(original+'# drift\n')
                        with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                        config.write_text(original)
                        suspend();pending='NOT-EXPORTED-'+transport;emit(pending);wait(lambda:spooled(pending),'Second pending marker not spooled')
                        with manager.locked():
                            manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                            self.assertNotIn(pending,json.dumps(saved));manager.stop();manager.start(saved)
                        ready();self.assertFalse(spooled(pending));self.assertNotIn(pending,logs());self.assertNotIn(pending,logs('PC2','/run/messages'))
                        emit('COLD-'+transport);received('COLD-'+transport)
                        self.assertNotIn(pending,logs())
                        with manager.locked():manager.write_startup()
                    finally:
                        if manager.directory.exists():
                            with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (family,kind),value in baseline.items():self.assertEqual(run(['ip','-j',family,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
