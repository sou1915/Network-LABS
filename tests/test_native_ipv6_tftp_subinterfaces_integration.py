"""Real IPv6 TFTP over tagged ROAS and transit, faults and saved recreation."""
from concurrent.futures import ThreadPoolExecutor
import base64
import copy
import hashlib
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
from network_labs.appliances.examples import ipv6_tftp_subinterfaces_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from network_labs.appliances.tftp import read
from network_labs.appliances.tftp_server import start_servers
from network_labs.appliances import tftp_worker
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeIPv6TFTPSubinterfaceTests(unittest.TestCase):
    def test_tagged_binary_transfers_route_pruning_outages_and_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dnsmasq','crun','ip','busybox','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        forwarding=run(['sysctl','-n','net.ipv6.conf.all.forwarding']).stdout
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dnsmasq=shutil.which('dnsmasq'))
            payloads={'empty':b'','exact':bytes(range(256))*8,'max':bytes(range(256))*256,'tail':b'\x00\xffIPv6'*420}
            spec=ipv6_tftp_subinterfaces_lab(rootfs,files={name:{'base64':base64.b64encode(value).decode()} for name,value in payloads.items()})
            spec['name']='ipv6-tftp-roas-'+str(os.getpid());manager=Manager(spec['name'])
            def query(name='exact',size=1024,expected=None,timeout=3):
                return read(manager,'PC1','2001:db8:30::10',name,family='ipv6',timeout=timeout,block_size=size,expected_sha256=expected)
            def wait(predicate,label):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.05)
                self.fail(label)
            def refuse():
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
            def local_delivery():
                wait(lambda:manager.crun('exec','PC1','/bin/busybox','ping6','-c','1','-W','1','2001:db8:10::20',check=False,timeout=4).returncode==0,'Same-VLAN control unavailable')
            def transfer(name='exact',size=1024):
                expected=hashlib.sha256(payloads[name]).hexdigest()
                result=query(name,size,expected)
                self.assertEqual(result['status'],'passed',result);self.assertTrue(result['hash_matches'])
                self.assertEqual(result['transfer']['bytes_received'],len(payloads[name]))
                self.assertEqual(result['transfer']['block_size'],size or 512)
                self.assertEqual(result['transfer']['option_negotiated'],size is not None)
                self.assertEqual(result['address_family'],'ipv6')
                return result
            try:
                with manager.locked():manager.start(spec)
                wait(lambda:query('empty',timeout=2)['status']=='passed','IPv6 TFTP not ready')
                for index in range(7):
                    addresses=json.loads(manager.ns(index,'ip','-j','-4','addr','show').stdout)
                    self.assertFalse([a for row in addresses if row['ifname']!='lo' for a in row['addr_info'] if a['family']=='inet'])
                self.assertIn(':69',manager.ns(3,'ss','-H','-lun','sport = :69').stdout)
                state=copy.deepcopy(manager.read());event=threading.Event();wire=root/'ipv6-tftp.pcap'
                cap=pool.submit(capture,Manager(spec['name']),'R1','eth0',wire,seconds=5,packets=1000,ready=event.set)
                self.assertTrue(event.wait(5));transfer();cap.result(timeout=9)
                decoded=run(['tcpdump','-nn','-X','-r',wire]).stdout
                self.assertIn('2001:db8:10::10',decoded);self.assertIn('2001:db8:30::10',decoded)
                self.assertIn('626c 6b73',decoded)  # actual blksize request/negotiation bytes
                # Both requests and service replies traverse the actual tagged
                # parent on client VLAN 10 and routed transit VLAN 100.
                for vlan in (10,100):
                    for endpoint in ('src','dst'):
                        packets=run(['tcpdump','-nn','-r',wire,'vlan',str(vlan),'and','ip6','and','udp','and',endpoint,'host','2001:db8:30::10']).stdout
                        self.assertTrue(packets,(vlan,endpoint))
                other=read(manager,'PC3','2001:db8:30::10','tail',family='ipv6',block_size=1024,
                           expected_sha256=hashlib.sha256(payloads['tail']).hexdigest())
                self.assertEqual(other['status'],'passed',other)
                for name,size in (('empty',None),('exact',None),('tail',512),('max',1428)):
                    transfer(name,size)
                wrong=query('tail',1024,'0'*64);self.assertEqual(wrong['status'],'failed');self.assertFalse(wrong['hash_matches'])
                missing=query('absent');self.assertEqual(missing['status'],'failed');self.assertEqual(missing['transfer']['error_code'],1)
                self.assertEqual(manager.read(),state)
                manager.crun('exec','PC4','/bin/sh','-c','/bin/kill -TERM "$(/bin/cat /run/tftp-dnsmasq.pid)"')
                wait(lambda:not manager.ns(3,'ss','-H','-lun','sport = :69').stdout,'TFTP listener did not stop')
                self.assertEqual(query(timeout=1)['status'],'failed');local_delivery()
                start_servers(manager);wait(lambda:query('empty',timeout=2)['status']=='passed','TFTP did not recover');transfer()
                manager.ns(5,'sysctl','-w','net/ipv6/conf/all/forwarding=0')
                self.assertEqual(query(timeout=1)['status'],'failed');local_delivery()
                # A local wire control proves the server still serves the same
                # bytes while the routed client is isolated. This is a test
                # fixture, not permission for local-target managed reads.
                request=dict(source='2001:db8:30::10',address='2001:db8:30::10',family='ipv6',port=69,filename='exact',timeout=3,block_size=1024)
                local=json.loads(manager.ns(3,sys.executable,'-I','-c',Path(tftp_worker.__file__).read_text(),json.dumps(request),timeout=5).stdout)
                self.assertEqual(local['status'],'passed',local);self.assertEqual(local['sha256'],hashlib.sha256(payloads['exact']).hexdigest())
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                manager.ns(5,'sysctl','-w','net/ipv6/conf/all/forwarding=1');transfer()
                manager.ns(5,'ip','-6','route','del','2001:db8:30::/64')
                self.assertEqual(query(timeout=1)['status'],'failed');local_delivery();refuse()
                manager.ns(5,'ip','-6','route','add','2001:db8:30::/64','via','2001:db8:100::2','dev','eth0.100','proto','static');transfer()
                manager.ns(4,'bridge','vlan','del','dev','eth3','vid','100')
                self.assertEqual(query(timeout=1)['status'],'failed');local_delivery();refuse()
                manager.ns(4,'bridge','vlan','add','dev','eth3','vid','100');transfer()
                asset=manager.directory/'PC4/files/tftp/exact';original=asset.read_bytes();asset.write_bytes(b'drift')
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
                asset.write_bytes(original)
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    self.assertEqual(saved['nodes'][3]['tftp_server']['family'],'ipv6')
                    manager.stop();manager.start(saved)
                wait(lambda:query('empty',timeout=2)['status']=='passed','Cold-restored IPv6 TFTP not ready');transfer('max',1428)
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
