"""Real clockless chronyd IPv6 local reference, ACL and lifecycle evidence."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from network_labs.appliances.capture import capture
from network_labs.appliances.examples import ipv6_ntp_lab
from network_labs.appliances.ntp_server import observe, start_servers, read_cli
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from network_labs.appliances import service_probe_worker
from network_labs.appliances.spec import validate
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6NTPTests(unittest.TestCase):
    def test_real_reference_allowed_denied_clockless_outage_drift_and_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('chronyd','chronyc','crun','ip','busybox','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        forwarding=run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',chronyd=shutil.which('chronyd'),chronyc=shutil.which('chronyc'))
            spec=ipv6_ntp_lab(rootfs);spec['name']='ipv6-ntp-'+str(os.getpid())
            # An explicitly allowed router source supplies a live wire control
            # on the server side of the deliberately broken R1 path.
            spec['nodes'][3]['ntp_server']['clients'].append('2001:db8:100::2');spec=validate(spec)
            manager=Manager(spec['name']);server=spec['nodes'][3]
            def wait(predicate,label):
                until=time.monotonic()+15
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.1)
                self.fail(label)
            def query(source='PC1'):
                return probe(manager,source,'2001:db8:20::20',family='ipv6',protocol='sntp',timeout=1)
            def good():
                wait(lambda:query()['status']=='passed','Managed IPv6 SNTP reference unavailable')
                actual=query();self.assertEqual(actual['status'],'passed',actual)
                self.assertEqual(actual['stages'][-1]['stratum'],10)
                return actual
            def control():
                request=dict(stage='sntp',source='2001:db8:100::2',address='2001:db8:20::20',timeout=1)
                result=json.loads(manager.ns(2,sys.executable,'-I','-c',Path(service_probe_worker.__file__).read_text(),json.dumps(request),timeout=3).stdout)
                self.assertEqual(result['status'],'passed',result);self.assertEqual(result['stratum'],10)
            def denied():
                # Verify this client's actual routed connectivity independently
                # before interpreting its unsuccessful SNTP observation.
                wait(lambda:manager.crun('exec','PC3','/bin/busybox','ping6','-c','1','-W','1','2001:db8:20::20',check=False,timeout=4).returncode==0,'Denied-client network path unavailable')
                self.assertEqual(query('PC3')['status'],'failed')
            def evidence():
                actual=observe(manager,server)
                self.assertTrue(actual['configuration_verified']);self.assertEqual(actual['family'],'ipv6')
                self.assertEqual(actual['process']['status'],'observed',actual)
                self.assertEqual(actual['udp_socket']['status'],'observed',actual)
                pid=actual['process']['pid']
                status=manager.crun('exec','PC2','/bin/busybox','cat',f'/proc/{pid}/status').stdout
                caps={line.split(':')[0]:int(line.split(':')[1].strip(),16) for line in status.splitlines() if line.startswith(('CapInh:','CapPrm:','CapEff:','CapBnd:','CapAmb:'))}
                self.assertEqual(len(caps),5);self.assertTrue(all(bits & (1<<25)==0 for bits in caps.values()),caps)
                self.assertIn('Reference ID',read_cli(manager,'PC2','tracking'))
                self.assertFalse(manager.ns(3,'ss','-H','-4','-lun','sport = :123').stdout)
                return actual
            try:
                with manager.locked():manager.start(spec)
                good();evidence();denied();control()
                event=threading.Event();wire=root/'ipv6-ntp.pcap'
                cap=pool.submit(capture,Manager(spec['name']),'PC2','eth0',wire,seconds=5,packets=1000,expression='ip6 and udp port 123',ready=event.set)
                self.assertTrue(event.wait(5));good();denied();cap.result(timeout=9)
                for expression in (['src','host','2001:db8:10::10','and','dst','port','123'],['src','host','2001:db8:30::30','and','dst','port','123'],['src','host','2001:db8:20::20','and','dst','host','2001:db8:10::10']):
                    self.assertTrue(run(['tcpdump','-nn','-r',wire,*expression]).stdout)
                actual=evidence();manager.crun('exec','PC2','/bin/busybox','kill','-TERM',str(actual['process']['pid']))
                wait(lambda:observe(manager,server)['udp_socket']['status']=='absent','NTP socket did not stop')
                self.assertTrue(observe(manager,server)['configuration_verified'])
                self.assertEqual(query()['status'],'failed')
                with self.assertRaises(RuntimeFailure):read_cli(manager,'PC2','tracking')
                start_servers(manager);good();evidence();denied()
                manager.ns(1,'sysctl','-w','net/ipv6/conf/all/forwarding=0')
                self.assertEqual(query()['status'],'failed');control()
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                manager.ns(1,'sysctl','-w','net/ipv6/conf/all/forwarding=1');good()
                config=manager.directory/'PC2/files/ntp-server.conf';original=config.read_text();config.write_text(original+'# external drift\n')
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                config.write_text(original)
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    self.assertEqual(saved['nodes'][3]['ntp_server']['family'],'ipv6')
                    manager.stop();manager.start(saved)
                good();evidence();denied();control()
                with manager.locked():manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        self.assertEqual(run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout,forwarding)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
