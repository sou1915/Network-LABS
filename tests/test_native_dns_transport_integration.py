"""Real dnsmasq TCP/UDP plus owned TC/framing controls and declarative restart."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from dns_transport_fixture import WORKER
from network_labs.appliances.capture import capture
from network_labs.appliances.dns import start_servers
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from network_labs.appliances.spec import example,validate,namespace
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeDNSTransportTests(unittest.TestCase):
    def test_real_dnsmasq_tcp_matched_tc_controls_and_saved_restart(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dnsmasq','busybox','crun','ip','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dnsmasq=shutil.which('dnsmasq'))
            spec=example(rootfs);spec['name']='dns-transport-'+str(os.getpid())
            spec['nodes'][0]['resolvers']=['192.0.2.20'];spec['nodes'][2]['dns_server']={'interface':'eth0','zone':'lab.test','records':{'web.lab.test':'192.0.2.20'}};spec=validate(spec)
            manager=Manager(spec['name'])
            def wait(predicate,label):
                until=time.monotonic()+8
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail(label)
            def query(mode='tcp',target='web.lab.test',protocol='dns',timeout=2):
                return probe(manager,'PC1',target,protocol=protocol,dns_transport=mode,timeout=timeout)
            def ready():
                wait(lambda:'192.0.2.20:53' in manager.ns(2,'ss','-H','-ltn','sport = :53').stdout,'DNS TCP listener unavailable')
                wait(lambda:'192.0.2.20:53' in manager.ns(2,'ss','-H','-lun','sport = :53').stdout,'DNS UDP listener unavailable')
            @contextmanager
            def controlled(mode):
                process=subprocess.Popen(['ip','netns','exec',namespace(spec,2),sys.executable,'-I','-c',WORKER,'192.0.2.20',mode],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout,selectors.EVENT_READ)
                        self.assertTrue(selector.select(3),'Controlled DNS responder not ready')
                        self.assertTrue(json.loads(process.stdout.readline())['ready'])
                    yield
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid,signal.SIGTERM)
                    process.communicate(timeout=3)
                    self.assertIsNotNone(process.returncode)
            try:
                with manager.locked():manager.start(spec)
                ready();state=copy.deepcopy(manager.read());event=threading.Event();pcap=root/'dnsmasq.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=5,packets=1000,expression='port 53',ready=event.set)
                self.assertTrue(event.wait(5))
                for mode in ('udp','tcp','auto'):
                    actual=query(mode);self.assertEqual(actual['status'],'passed',actual)
                    self.assertEqual(actual['stages'][0]['addresses'],['192.0.2.20']);self.assertFalse(actual['stages'][0]['fallback'])
                    denied=query(mode,target='missing.lab.test');self.assertEqual(denied['status'],'failed',denied);self.assertEqual(denied['stages'][0]['rcode'],3)
                manager.crun('exec','PC2','/bin/sh','-c','mkdir -p /tmp/http; echo transport > /tmp/http/index.html')
                manager.crun('exec','--detach','PC2','/bin/busybox','httpd','-f','-p','80','-h','/tmp/http',log=manager.directory/'http-fixture.log')
                self.assertEqual(query('tcp',protocol='http')['status'],'passed')
                future.result(timeout=8)
                self.assertTrue(run(['tcpdump','-nn','-r',pcap,'udp','port','53']).stdout)
                self.assertTrue(run(['tcpdump','-nn','-r',pcap,'tcp','port','53']).stdout)
                self.assertEqual(manager.read(),state)
                manager.crun('exec','PC2','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/dnsmasq.pid)"')
                wait(lambda:not manager.ns(2,'ss','-H','-lnt','sport = :53').stdout,'Stopped dnsmasq still listens')
                actual=query('tcp');self.assertEqual(actual['status'],'failed',actual)
                event=threading.Event();fallback_pcap=root/'dns-fallback.pcap'
                with controlled('answer'):
                    future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',fallback_pcap,seconds=5,packets=1000,expression='port 53',ready=event.set)
                    self.assertTrue(event.wait(5));actual=query('auto');self.assertEqual(actual['status'],'passed',actual)
                    stage=actual['stages'][0];self.assertTrue(stage['fallback']);self.assertEqual(stage['addresses'],['203.0.113.10'])
                    self.assertEqual([a['transport'] for a in stage['attempts']],['udp','tcp']);self.assertTrue(stage['attempts'][0]['truncated'])
                    strict=query('udp');self.assertEqual(strict['status'],'unknown');self.assertFalse(strict['stages'][0]['fallback'])
                    future.result(timeout=8)
                self.assertTrue(run(['tcpdump','-nn','-r',fallback_pcap,'udp','port','53']).stdout)
                self.assertTrue(run(['tcpdump','-nn','-r',fallback_pcap,'tcp','port','53']).stdout)
                for mode in ('bad-id','bad-question','large','short','refused'):
                    with self.subTest(control=mode),controlled(mode):
                        result=query('auto',timeout=1);stage=result['stages'][0]
                        self.assertEqual(result['status'],'failed' if mode=='refused' else 'unknown',result)
                        self.assertNotIn('addresses',stage)
                        self.assertEqual(stage['fallback'],mode not in ('bad-id','bad-question'))
                        if mode in ('bad-id','bad-question'):self.assertEqual([a['transport'] for a in stage['attempts']],['udp'])
                start_servers(manager);ready();self.assertEqual(query('tcp')['status'],'passed')
                with manager.locked():
                    config=manager.directory/'PC2/files/dnsmasq.conf';original=config.read_text();config.write_text(original+'# drift\n')
                    with self.assertRaises(RuntimeFailure):manager.write_startup()
                    config.write_text(original);manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    manager.stop();manager.start(saved)
                ready();self.assertEqual(query('tcp')['status'],'passed');self.assertEqual(query('auto')['status'],'passed')
                with manager.locked():manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
