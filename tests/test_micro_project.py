"""Canonical project configuration drives guest bytes; never a model fallback."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from network_labs.engine import Lab, Node
from network_labs.cli import Session
from network_labs.micro_appliances.project import demo, RAM_TARGET

AVAILABLE = importlib.util.find_spec('wasmtime') is not None


class ProjectBackendPersistenceTests(unittest.TestCase):
    def test_backend_roundtrip_legacy_default_and_validation(self):
        lab = demo()
        restored = Lab.loads(lab.dumps())
        self.assertEqual(restored.execution_backend,'wasm')
        data = json.loads(lab.dumps());data.pop('execution_backend')
        self.assertEqual(Lab.loads(json.dumps(data)).execution_backend,'model')
        data['execution_backend']='unknown'
        with self.assertRaises(ValueError):Lab.loads(json.dumps(data))


@unittest.skipUnless(AVAILABLE,'Optional Wasmtime dependency not installed')
class ProjectExecutionTests(unittest.TestCase):
    def test_current_names_addresses_and_cables_execute_without_model_path(self):
        lab = demo()
        with patch.object(lab,'_ping_ipv4',side_effect=AssertionError('model fallback')),patch.object(lab,'path_details',side_effect=AssertionError('model path')):
            ok,trace = lab.ping('PC1','192.168.50.20')
        self.assertTrue(ok,trace)
        capture = lab.last_micro_capture
        self.assertEqual({r['name'] for r in capture.counters['nodes']},set(lab.nodes))
        self.assertEqual(capture.port_names['SW1'][0],'fa0/1')
        self.assertTrue(any('ICMP' in s['body'] for s in lab.last_explanation['steps']))
        self.assertNotIn('Transaction calculée',str(lab.last_explanation))
        self.assertTrue(all(f.source in lab.nodes and f.destination in lab.nodes for f in capture.frames))
        self.assertFalse(hasattr(capture,'engine'))
        first=next(f for f in capture.frames if f.source=='PC1')
        self.assertEqual(first.data[6:12].hex(':'),lab.display_mac('PC1'))
        self.assertIn(lab.display_mac('PC1'),Session(lab,'PC1').execute('ipconfig'))

    def test_configured_shutdown_and_cable_state_are_used(self):
        lab = demo();port = lab.links[0].b_port
        config = Session(lab,'SW1');config.mode='config'
        self.assertFalse(config.execute('interface '+port).startswith('%'))
        config.execute('shutdown')
        self.assertFalse(lab.ping('PC1','192.168.50.20')[0])
        config.execute('no shutdown')
        self.assertTrue(lab.ping('PC1','192.168.50.20')[0])
        lab.links[1].enabled=False
        self.assertFalse(lab.ping('PC1','192.168.50.20')[0])
        lab.links[1].enabled=True
        self.assertTrue(lab.ping('PC1','192.168.50.20')[0])

    def test_windows_and_linux_ping_use_the_selected_backend(self):
        from network_labs.vendor_cli import console_session
        lab = demo()
        for source,target in [('PC1','192.168.50.20'),('SRV1','192.168.50.10')]:
            result = console_session(lab,source).execute('ping '+target)
            self.assertIn('Wasm',result)
            self.assertTrue(lab.last_outcome,result)
            self.assertIsNotNone(lab.last_micro_capture)

    def test_tcp_echo_requires_service_and_is_repeatable(self):
        lab = demo()
        for _ in range(2):
            self.assertTrue(lab.probe('PC1','192.168.50.20','tcp',8080)[0])
        lab.nodes['SRV1'].services={}
        self.assertFalse(lab.probe('PC1','192.168.50.20','tcp',8080)[0])
        self.assertIsNotNone(lab.last_micro_capture)

    def test_unsupported_requests_do_not_reuse_previous_capture(self):
        lab = demo();self.assertTrue(lab.ping('PC1','192.168.50.20')[0])
        for args in [('tcp',443),('udp',8080)]:
            self.assertFalse(lab.probe('PC1','192.168.50.20',*args)[0])
            self.assertIsNone(lab.last_micro_capture)
            self.assertFalse(lab.last_hops)
        self.assertFalse(lab.ping('PC1','example.lan')[0])
        self.assertIsNone(lab.last_micro_capture)

    def test_auxiliary_protocols_cannot_silently_use_the_model(self):
        lab=demo()
        for operation in (lambda:lab.request_dhcp('PC1'),lambda:lab.resolve_name('PC1','example.lan'),lambda:lab.authenticate('PC1','user','password'),lambda:lab.multicast('PC1','239.1.1.1')):
            with self.assertRaisesRegex(ValueError,'Wasm'):operation()

    def test_unsupported_topologies_and_configuration_fail_closed(self):
        def vlan(lab):lab.nodes['SW1'].ports[lab.links[0].b_port].access_vlan=10
        def trunk(lab):lab.nodes['SW1'].ports[lab.links[1].a_port].mode='trunk'
        def router(lab):lab.add(Node('R1','Routeur'));lab.connect('R1','SW1')
        def firewall(lab):lab.add(Node('FW1','Switch',profile='fortigate'));lab.connect('FW1','SW1')
        def address(lab):lab.nodes['SRV1'].address='192.168.60.20/24'
        def duplicate(lab):lab.nodes['SRV1'].address=lab.nodes['PC1'].address
        def security(lab):lab.nodes['SW1'].ports[lab.links[0].b_port].security=True
        for change in (vlan,trunk,router,firewall,address,duplicate,security):
            with self.subTest(change=change.__name__):
                lab=demo();change(lab)
                with patch.object(lab,'_ping_ipv4',side_effect=AssertionError('fallback')):
                    self.assertFalse(lab.ping('PC1','192.168.50.20')[0])
                self.assertIsNone(lab.last_micro_capture)

    def test_loop_rejected_but_disabled_edge_and_disconnected_router_allowed(self):
        lab=demo();lab.add(Node('SW2','Switch'));lab.add(Node('SW3','Switch'))
        lab.connect('SW1','SW2');lab.connect('SW2','SW3');edge=lab.connect('SW3','SW1')
        self.assertFalse(lab.ping('PC1','192.168.50.20')[0])
        self.assertIn('boucle',lab.last_trace[-1])
        edge.enabled=False;lab.add(Node('R1','Routeur'))
        self.assertTrue(lab.ping('PC1','192.168.50.20')[0])
        self.assertNotIn('R1',{r['name'] for r in lab.last_micro_capture.counters['nodes']})

    def test_ram_target_checked_before_creating_engine(self):
        lab=demo()
        with patch('network_labs.micro_appliances.project.memory_sample',return_value={'rss_bytes':RAM_TARGET}),patch('network_labs.micro_appliances.project.Fabric',side_effect=AssertionError('instantiated')):
            self.assertFalse(lab.ping('PC1','192.168.50.20')[0])
        self.assertIn('2 Gio',lab.last_trace[-1])

    def test_captures_survive_next_test_and_model_state_is_not_claimed_as_guest_fdb(self):
        lab=demo();lab.ping('PC1','192.168.50.20');capture=lab.last_micro_capture
        before=list(capture.frames)
        lab.links[0].enabled=False;lab.ping('PC1','192.168.50.20')
        self.assertEqual(capture.frames,before)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'project.pcap';capture.write_pcap(path)
            self.assertGreater(path.stat().st_size,24)
        lab.links[0].enabled=True;lab.ping('PC1','192.168.50.20')
        self.assertIn('2 MAC apprises',Session(lab,'SW1').show('show mac address-table'))
        self.assertIn('non disponible',Session(lab,'SW1').show('show spanning-tree'))


@unittest.skipUnless(AVAILABLE and os.environ.get('DISPLAY'),'GUI requires Wasmtime and DISPLAY')
class ProjectExecutionGUITests(unittest.TestCase):
    def test_main_topology_selector_tests_capture_and_config_invalidation(self):
        import tkinter as tk
        from network_labs.__main__ import App
        root=tk.Tk();app=App(root);errors=[]
        root.report_callback_exception=lambda *e:errors.append(str(e))
        try:
            app.load_wasm_lab();root.update()
            self.assertEqual(app.lab.execution_backend,'wasm')
            self.assertEqual(app.backend_choice.get(),'Wasm · LAN')
            app.ping();app.pause();root.update()
            self.assertTrue(app.result);self.assertTrue(app.hops)
            self.assertEqual(str(app.capture_button['state']),'normal')
            view=app.open_project_capture();root.update()
            self.assertFalse(view.owns_fabric);self.assertTrue(view.trace.get_children())
            snapshot=list(view.fabric.frames)
            app.lab.links[0].enabled=False;app.changed('Cable off');app.ping();app.pause()
            self.assertFalse(app.result);self.assertEqual(view.fabric.frames,snapshot)
            view.close()
            app.changed('Configuration changed')
            self.assertIsNone(app.lab.last_micro_capture)
            self.assertEqual(str(app.capture_button['state']),'disabled')
            app.backend_choice.set('Pédagogique');app.set_backend()
            self.assertEqual(app.lab.execution_backend,'model')
        finally:root.destroy()
        self.assertEqual(errors,[])
