"""Real dnsmasq negotiated binary reads, error/hash checks and saved restart."""
from concurrent.futures import ThreadPoolExecutor
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
from network_labs.appliances.capture import capture
from network_labs.appliances.examples import tftp_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.tftp import read
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeTFTPBlockSizeTests(unittest.TestCase):
    def test_real_dnsmasq_negotiated_content_capture_and_cold_restore(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dnsmasq','busybox','crun','ip','tcpdump'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dnsmasq=shutil.which('dnsmasq'))
            payloads={'empty':b'','exact':bytes(range(256))*8,'max':bytes(range(256))*256,'tail':b'\x00\xffabc'*500}
            spec=tftp_lab(rootfs,files={name:{'base64':base64.b64encode(data).decode()} for name,data in payloads.items()});spec['name']='tftp-options-'+str(os.getpid());manager=Manager(spec['name'])
            def query(name,size=None,expected=None):
                return read(manager,'PC1','192.0.2.20',name,timeout=3,block_size=size,expected_sha256=expected)
            try:
                with manager.locked():manager.start(spec)
                state=copy.deepcopy(manager.read());event=threading.Event();pcap=root/'tftp.pcap'
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',pcap,seconds=8,packets=1000,expression='udp',ready=event.set)
                self.assertTrue(event.wait(5))
                for size in (None,512,1024,1428):
                    result=query('exact',size,hashlib.sha256(payloads['exact']).hexdigest())
                    self.assertEqual(result['status'],'passed',result);self.assertTrue(result['hash_matches'])
                    self.assertEqual(result['transfer']['block_size'],size or 512)
                    self.assertEqual(result['transfer']['option_negotiated'],size is not None)
                future.result(timeout=10)
                packets=run(['tcpdump','-nn','-X','-r',pcap]).stdout
                self.assertIn('626c 6b73',packets) # ASCII blksize in actual RRQ/OACK
                for name in ('empty','max','tail'):
                    result=query(name,1428,hashlib.sha256(payloads[name]).hexdigest())
                    self.assertEqual(result['status'],'passed',result);self.assertEqual(result['transfer']['bytes_received'],len(payloads[name]))
                wrong=query('tail',1024,'0'*64);self.assertEqual(wrong['status'],'failed');self.assertFalse(wrong['hash_matches'])
                missing=query('absent',1024);self.assertEqual(missing['status'],'failed');self.assertEqual(missing['transfer']['error_code'],1)
                self.assertEqual(manager.read(),state)
                with manager.locked():
                    config=manager.directory/'PC2/files/tftp-server.conf';original=config.read_text();config.write_text(original+'# drift\n')
                    with self.assertRaises(RuntimeFailure):manager.write_startup()
                    config.write_text(original);manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    manager.stop();manager.start(saved)
                result=query('max',1428,hashlib.sha256(payloads['max']).hexdigest());self.assertEqual(result['status'],'passed',result)
                with manager.locked():manager.write_startup()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)};hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
