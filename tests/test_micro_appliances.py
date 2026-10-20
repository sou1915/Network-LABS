"""Optional executable appliance tests. Install experimental requirements to run."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from network_labs.micro_appliances.runtime import Fabric,make_lab,ApplianceFault,MEMORY_LIMIT,Frame
from network_labs.micro_appliances.experiment import functional_demo,echo_ping,isolation_demo
from network_labs.micro_appliances.packets import describe

AVAILABLE=importlib.util.find_spec('wasmtime') is not None
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(AVAILABLE,'Optional Wasmtime dependency not installed')
class MicroApplianceTests(unittest.TestCase):
    def setUp(self):self.fabric=None
    def tearDown(self):
        if self.fabric is not None:self.fabric.close()

    def test_bundled_module_source_manifest_abi_and_imports(self):
        self.fabric=f=make_lab()
        self.assertEqual([(x.module,x.name) for x in f.module.imports],[('lab','emit')])
        manifest=json.loads((ROOT/'network_labs/micro_appliances/build.json').read_text())
        artifact=(ROOT/'network_labs/micro_appliances/device.wasm').read_bytes()
        self.assertEqual(hashlib.sha256(artifact).hexdigest(),manifest['artifact_sha256'])
        for path,digest in manifest['inputs'].items():
            self.assertEqual(hashlib.sha256((ROOT/'experiments/micro_appliances'/path).read_bytes()).hexdigest(),digest,path)
        self.assertTrue(all(n.call('abi_version')==1 for n in f.nodes.values()))

    def test_arp_icmp_and_tcp_are_serialized_with_valid_checksums(self):
        f,report=functional_demo();self.fabric=f
        self.assertTrue(report['ok']);self.assertTrue(report['tcp_handshake_observed'])
        packets=report['frames'];self.assertTrue(any(x['protocol']=='ARP' and x['operation']=='request' for x in packets))
        self.assertTrue(any(x['protocol']=='ARP' and x['operation']=='reply' for x in packets))
        self.assertTrue(any(x['protocol']=='ICMP' and x['operation']=='echo reply' for x in packets))
        for p in packets:
            self.assertTrue(p.get('checksum_ok',True));self.assertTrue(p.get('ip_checksum_ok',True))
        self.assertEqual(f.nodes['SW1'].call('fdb_size'),2)

    def test_switch_learns_and_does_not_flood_known_tcp_unicast(self):
        self.fabric=f=make_lab(3)
        self.assertTrue(echo_ping(f,'PC1','10.0.0.3')['ok'])
        bystander=f.nodes['PC2'].call('rx_count')
        f.nodes['PC1'].connect('10.0.0.3',8080,b'payload')
        self.assertTrue(f.run_until(lambda:f.nodes['PC1'].reply()==b'payload'))
        self.assertEqual(f.nodes['PC2'].call('rx_count'),bystander)
        self.assertEqual(f.nodes['SW1'].call('fdb_size'),2)

    def test_closed_tcp_port_resets_without_fabricating_a_service(self):
        self.fabric=f=make_lab();client=f.nodes['PC1']
        client.connect('10.0.0.2',9999,b'not delivered')
        self.assertFalse(f.run_until(lambda:bool(client.reply()),100))
        self.assertTrue(any('RST' in describe(x).get('flags',[]) for x in f.frames))
        self.assertEqual(client.reply(),b'')

    def test_lost_syn_ack_is_retransmitted_by_the_guest_stack(self):
        self.fabric=f=make_lab();original=f.transmit;dropped=[]
        def lossy(source,port,data):
            p=describe(Frame(f.now_ms,source,port,'',0,data))
            if source=='PC2' and p.get('flags')==['SYN','ACK'] and not dropped:
                dropped.append(data);return
            original(source,port,data)
        with patch.object(f,'transmit',side_effect=lossy):
            f.nodes['PC1'].connect('10.0.0.2',8080,b'retransmitted')
            self.assertTrue(f.run_until(lambda:f.nodes['PC1'].reply()==b'retransmitted'))
        self.assertEqual(len(dropped),1)
        self.assertGreaterEqual(sum(describe(x).get('flags')==['SYN'] and x.source=='PC1' for x in f.frames),2)

    def test_link_down_timeout_and_reconnect(self):
        self.fabric=f=make_lab();f.set_link_enabled('PC2',0,False)
        self.assertFalse(echo_ping(f,'PC1','10.0.0.2',attempts=1)['ok'])
        self.assertEqual(f.nodes['PC2'].call('rx_count'),0)
        f.set_link_enabled('PC2',0,True)
        self.assertTrue(echo_ping(f,'PC1','10.0.0.2')['ok'])

    def test_old_echo_reply_does_not_satisfy_a_new_destination(self):
        self.fabric=f=make_lab();node=f.nodes['PC1']
        node.ping('10.0.0.2',b'old')
        node.ping('10.0.0.99',b'new')
        self.assertFalse(f.run_until(lambda:node.call('ping_count')>0,1000))
        self.assertEqual(node.reply('icmp'),b'')

    def test_sandbox_memory_and_cpu_isolation(self):
        self.assertTrue(isolation_demo()['ok'])

    def test_trapped_guest_does_not_destroy_other_instances(self):
        self.fabric=f=make_lab(3)
        with self.assertRaises(ApplianceFault):f.nodes['PC1'].call('crash')
        self.assertTrue(f.nodes['PC1'].fault)
        self.assertTrue(echo_ping(f,'PC2','10.0.0.3')['ok'])

    def test_pcap_records_match_actual_virtual_egress_bytes(self):
        self.fabric=f=make_lab();self.assertTrue(echo_ping(f,'PC1','10.0.0.2')['ok'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.pcap';f.write_pcap(path);raw=path.read_bytes()
        self.assertEqual(struct.unpack('<I',raw[:4])[0],0xa1b2c3d4)
        offset=24;frames=[]
        while offset<len(raw):
            _,_,size,original=struct.unpack('<IIII',raw[offset:offset+16]);self.assertEqual(size,original)
            frames.append(raw[offset+16:offset+16+size]);offset+=16+size
        self.assertEqual(frames,[x.data for x in f.frames]);self.assertEqual(offset,len(raw))

    def test_bounded_configuration_and_private_guest_memory(self):
        self.fabric=f=make_lab()
        with self.assertRaises(ValueError):f.add('DUPLICATE',address='10.0.0.4',identity=1)
        with self.assertRaises(ValueError):f.connect('PC1',0,'SW1',0)
        with self.assertRaises(ValueError):f.nodes['PC1'].ping('10.0.0.2',b'x'*513)
        a,b=f.nodes['PC1'],f.nodes['PC2'];a.write_input(b'ISOLATED')
        self.assertNotEqual(bytes(a.memory.read(a.store,a.input_pointer,a.input_pointer+8)),bytes(b.memory.read(b.store,b.input_pointer,b.input_pointer+8)))
        with self.assertRaises(Exception):a.memory.grow(a.store,MEMORY_LIMIT//65536)

@unittest.skipUnless(AVAILABLE and os.environ.get('DISPLAY'),'Optional prototype GUI requires Wasmtime and DISPLAY')
class MicroApplianceGUITests(unittest.TestCase):
    def test_separate_lab_gui_live_packets_and_lifecycle(self):
        import tkinter as tk
        from network_labs.__main__ import App
        root=tk.Tk();app=App(root);window=None;errors=[]
        root.report_callback_exception=lambda *e:errors.append(str(e))
        try:
            original=app.lab.dumps();window=app.open_micro_lab();root.update()
            window.ping();root.update();self.assertIn('réponse reçue',window.status.get())
            window.tcp();root.update();self.assertIn('réussis',window.status.get())
            self.assertTrue(any('SYN' in str(window.trace.item(key,'values')) for key in window.trace.get_children()))
            self.assertEqual(app.lab.dumps(),original)
            window.reset();window.toggle_link();window.ping();self.assertIn('aucune réponse',window.status.get())
            window.toggle_link();window.ping();self.assertIn('réponse reçue',window.status.get())
            window.close();self.assertTrue(window.closed);self.assertFalse(window.fabric.nodes)
        finally:root.destroy()
        self.assertEqual(errors,[])
