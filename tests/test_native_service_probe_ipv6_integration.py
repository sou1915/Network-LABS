"""Managed IPv6 probes against real dnsmasq and explicitly owned wire fixtures."""
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
from https_test_identity import identities
from probe_ipv6_fixture import SERVICES
from network_labs.appliances.capture import capture
from network_labs.appliances.dns import start_servers
from network_labs.appliances.examples import dual_stack_dns_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.service_probe import probe
from network_labs.appliances.spec import validate,namespace
from network_labs.appliances.verify import verify
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6ProbeTests(unittest.TestCase):
    def test_real_ipv6_dns_http_https_sntp_faults_and_saved_restart(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dnsmasq','busybox','crun','ip','tcpdump','openssl'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);certs=identities(root,valid_ip='2001:db8:20::20',valid_name='server.lab.test');mode=root/'mode';mode.write_text('good')
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dnsmasq=shutil.which('dnsmasq'))
            spec=dual_stack_dns_lab(rootfs,resolver_family='ipv6');spec['name']='probe-v6-'+str(os.getpid());spec['nodes'][3]['dns_server']['records']['aonly.lab.test']='198.51.100.21';spec=validate(spec);manager=Manager(spec['name'])
            def check(protocol='dns',target='server.lab.test',family='ipv6',**kwargs):
                return probe(manager,'PC1',target,protocol=protocol,family=family,**kwargs)
            def good(protocol='dns',**kwargs):
                actual=check(protocol,**kwargs);self.assertEqual(actual['status'],'passed',actual);return actual
            def ready():
                until=time.monotonic()+8
                while time.monotonic()<until:
                    if len(manager.ns(3,'ss','-H','-lntu','sport = :53').stdout.splitlines())==4:
                        result=verify(manager,'PC1','PC2',family='ipv6',count=2,bidirectional=True)
                        if result['status']=='passed':return
                    time.sleep(.1)
                self.fail('IPv6 DNS/route readiness unavailable')
            @contextmanager
            def services():
                process=subprocess.Popen(['ip','netns','exec',namespace(spec,3),sys.executable,'-I','-c',SERVICES,'2001:db8:20::20',str(certs['valid_cert']),str(certs['valid_key']),str(mode)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
                try:
                    with selectors.DefaultSelector() as select:
                        select.register(process.stdout,selectors.EVENT_READ);self.assertTrue(select.select(5),'Owned IPv6 service fixture not ready')
                        self.assertTrue(json.loads(process.stdout.readline())['ready'])
                    yield
                finally:
                    if process.poll() is None:os.killpg(process.pid,signal.SIGTERM)
                    process.communicate(timeout=3);self.assertIsNotNone(process.returncode)
            try:
                with manager.locked():manager.start(spec)
                ready();state=copy.deepcopy(manager.read());event=threading.Event();pcap=root/'probe-v6.pcap'
                with services():
                    future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=8,packets=2000,expression='ip6 and (port 53 or tcp port 80 or tcp port 443 or udp port 123)',ready=event.set)
                    self.assertTrue(event.wait(5))
                    for transport in ('udp','tcp','auto'):
                        actual=good(dns_transport=transport);self.assertEqual(actual['stages'][0]['record_type'],'AAAA')
                        self.assertEqual(actual['stages'][0]['addresses'],['2001:db8:20::20']);self.assertEqual(actual['stages'][0]['request']['source'],'2001:db8:10::10')
                    # Target family and resolver transport family are independent.
                    actual=good(family='ipv4',dns_transport='tcp');self.assertEqual(actual['stages'][0]['record_type'],'A')
                    self.assertEqual(actual['stages'][0]['request']['source'],'2001:db8:10::10')
                    good('tcp',port=80);good('http');good('https',ca_pem=certs['ca'].read_text())
                    good('https',target='2001:db8:20::20',ca_pem=certs['ca'].read_text());good('sntp')
                    future.result(timeout=11)
                    for expression in (['udp','port','53'],['tcp','port','53'],['tcp','port','80'],['tcp','port','443'],['udp','port','123']):
                        self.assertTrue(run(['tcpdump','-nn','-r',pcap,*expression]).stdout)
                    for path,code in (('/missing',404),('/redirect',302)):
                        actual=check('http',path=path);self.assertEqual(actual['status'],'failed');self.assertEqual(actual['stages'][-1]['http_status'],code)
                    denied=check('https',ca_pem=certs['wrong_ca'].read_text());self.assertEqual(denied['status'],'failed');self.assertEqual(denied['stages'][-1]['error'],'CERTIFICATE_VERIFY_FAILED')
                    # The worker's TLS identity check rejects a wrong name on the same working endpoint.
                    request={'stage':'https','source':'2001:db8:10::10','address':'2001:db8:20::20','target':'wrong.lab','port':443,'path':'/','timeout':2,'ca_pem':certs['ca'].read_text()}
                    worker=Path(__file__).parents[1]/'network_labs/appliances/service_probe_worker.py'
                    actual=json.loads(manager.ns(0,sys.executable,'-I','-c',worker.read_text(),json.dumps(request),timeout=4).stdout)
                    self.assertEqual(actual['error'],'CERTIFICATE_VERIFY_FAILED')
                    missing=check(target='missing.lab.test');self.assertEqual(missing['status'],'failed');self.assertEqual(missing['stages'][0]['rcode'],3)
                    nodata=check(target='aonly.lab.test');self.assertEqual(nodata['status'],'failed');self.assertEqual(nodata['stages'][0]['rcode'],0)
                    self.assertIn('DNS_NO_DIRECT_AAAA',[f['code'] for f in nodata['findings']]);good(target='aonly.lab.test',family='ipv4')
                    no_fallback=check('http',family='ipv4');self.assertEqual(no_fallback['status'],'failed');self.assertEqual(no_fallback['address'],'198.51.100.20')
                    mode.write_text('bad');actual=check('sntp');self.assertEqual(actual['status'],'unknown');mode.write_text('good')
                    self.assertEqual(manager.read(),state)
                    # A temporary guest resolver change proves AAAA over IPv4 too;
                    # it remains audited drift until restored to the manifest.
                    resolver=manager.directory/'PC1/files/resolv.conf';original=resolver.read_text();resolver.write_text('nameserver 198.51.100.20\n')
                    actual=good('http');self.assertEqual(actual['stages'][0]['request']['source'],'192.0.2.10');self.assertEqual(actual['stages'][0]['request']['qtype'],28)
                    with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                    resolver.write_text(original)
                    manager.crun('exec','PC2','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/dnsmasq.pid)"')
                    until=time.monotonic()+5
                    while manager.ns(3,'ss','-H','-lntu','sport = :53').stdout and time.monotonic()<until:time.sleep(.1)
                    actual=check('http',timeout=1);self.assertEqual(actual['status'],'failed');good('http',target='2001:db8:20::20')
                    start_servers(manager);ready();good('http')
                    manager.ns(1,'ip','-6','route','del','2001:db8:20::/64')
                    self.assertEqual(check('http',target='2001:db8:20::20',timeout=1)['status'],'failed')
                    self.assertEqual(verify(manager,'PC1','PC2',family='ipv4',count=2,bidirectional=True)['status'],'passed')
                    with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                    manager.ns(1,'ip','-6','route','add','2001:db8:20::/64','via','2001:db8:100::2','dev','eth1','proto','static');good('http')
                    with manager.locked():manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                # All test-owned service processes are reaped before namespace teardown.
                self.assertEqual(check('tcp',target='2001:db8:20::20',port=80)['status'],'failed')
                with manager.locked():manager.stop();manager.start(saved)
                ready()
                with services():good('https',ca_pem=certs['ca'].read_text());good('sntp')
                with manager.locked():manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
