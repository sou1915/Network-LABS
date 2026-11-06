"""Native GUI provenance/private transport and display behavior."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from network_labs.appliances import ui_bridge as bridge
from network_labs.appliances.spec import example


class BridgeTests(unittest.TestCase):
    def request(self,action='status'):
        return {'id':'a'*32,'owner_uid':os.geteuid(),'action':action,'target':'gui-lab','lab':'gui-lab','node':None,'destination':None}

    def test_private_results_reject_stale_context_and_public_permissions(self):
        request=self.request()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'result.json';value={'id':request['id'],'action':'status','lab':'gui-lab','response':{'ok':False,'error':'test'}}
            bridge.private_json(path,value);self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertFalse(bridge.read_result(path,request)['ok'])
            value['id']='b'*32;bridge.private_json(path,value)
            with self.assertRaises(ValueError):bridge.read_result(path,request)
            value['id']=request['id'];bridge.private_json(path,value);path.chmod(0o644)
            with self.assertRaises(ValueError):bridge.read_result(path,request)

    def test_sudo_auth_uses_terminal_then_typed_argv_without_shell_or_password_capture(self):
        request=self.request('start');request['target']='/tmp/lab with spaces;$(literal).json'
        graph=bridge.public_topology(example('/rootfs'));graph['name']='gui-lab'
        payload={'ok':True,'lab':'gui-lab','action':'start','data':{},'topology':graph}
        with patch.object(bridge.subprocess,'run',side_effect=[subprocess.CompletedProcess([],0),subprocess.CompletedProcess([],0,json.dumps(payload),'')]) as run:
            self.assertTrue(bridge.execute_request(request)['ok'])
        self.assertEqual(run.call_args_list[0].args[0],['sudo','-v']);self.assertEqual(run.call_args_list[0].kwargs,{})
        argv=run.call_args_list[1].args[0];self.assertEqual(argv[:2],['sudo','-n']);self.assertEqual(argv[-1],request['target'])
        self.assertNotIn('shell',run.call_args_list[1].kwargs)

    def test_denied_auth_never_calls_backend_and_malformed_reply_never_claims_success(self):
        with patch.object(bridge.subprocess,'run',return_value=subprocess.CompletedProcess([],1)) as run:
            self.assertFalse(bridge.execute_request(self.request())['ok']);self.assertEqual(run.call_count,1)
        for output in ('not JSON',json.dumps({'ok':True,'action':'status','lab':'another-lab'})):
            with patch.object(bridge.subprocess,'run',side_effect=[subprocess.CompletedProcess([],0),subprocess.CompletedProcess([],0,output,'')]):
                result=bridge.execute_request(self.request())
            self.assertFalse(result['ok']);self.assertTrue(result['uncertain'])

    def test_operation_and_owner_allowlist_refuse_before_subprocess(self):
        for fault in ({'action':'exec'},{'owner_uid':os.geteuid()+1},{'lab':'bad;name'},{'node':'PC1'},{'target':'other-lab'}):
            request={**self.request(),**fault}
            with patch.object(bridge.subprocess,'run') as run,self.assertRaises(ValueError):bridge.execute_request(request)
            run.assert_not_called()

    def test_backend_topology_omits_assets_credentials_and_model_state(self):
        spec=example('/rootfs');spec['name']='gui-lab';spec['nodes'][0]['private_test']='secret-not-for-topology'
        manager=Mock();manager.locked.return_value=nullcontext(manager);manager.read.return_value={'spec':spec}
        manager.status.return_value={'name':'gui-lab','phase':'running','nodes':[]}
        with patch('network_labs.appliances.runtime.Manager',return_value=manager):result=bridge.backend('status','gui-lab')
        self.assertEqual(len(result['topology']['nodes']),3);self.assertEqual(len(result['topology']['links']),2)
        self.assertNotIn('rootfs',json.dumps(result['topology']));self.assertNotIn('secret-not-for-topology',json.dumps(result))
        manager.start.assert_not_called();manager.stop.assert_not_called()

    def test_bad_topology_is_rejected_before_replacing_view(self):
        graph=bridge.public_topology(example('/rootfs'));self.assertIs(bridge.validate_topology(graph),graph)
        for fault in ({'nodes':[]},{'links':[[['missing','eth0'],['PC1','eth0']]]},{'nodes':[{'name':'PC1','role':'host','runtime':'oci','interfaces':{},'rootfs':'private'}]}):
            with self.subTest(fault=fault),self.assertRaises(ValueError):bridge.validate_topology({**graph,**fault})


@unittest.skipUnless(os.environ.get('DISPLAY'),'GUI requires X display')
class WorkbenchGUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from network_labs.appliances.ui import ApplianceWindow
        self.root=tk.Tk();self.root.withdraw();self.window=ApplianceWindow(SimpleNamespace(root=self.root));self.errors=[]
        self.root.report_callback_exception=lambda *error:self.errors.append(str(error))
        self.root.update()

    def tearDown(self):
        self.root.destroy();self.assertEqual(self.errors,[])

    def test_declared_topology_is_unobserved_until_real_result_and_stop_requires_confirmation(self):
        window=self.window;self.assertEqual(len(window.node_shapes),3);self.assertEqual(len(window.canvas.find_withtag('link')),2)
        self.assertTrue(all(n['values'][1]=='non observé' for n in (window.nodes.item(i) for i in window.nodes.get_children())))
        graph=bridge.public_topology(example('/rootfs'));lab=graph['name']
        response={'ok':True,'lab':lab,'action':'status','topology':graph,'data':{'name':lab,'phase':'running','nodes':[{'name':n['name'],'state':{'status':'running'},'memory_current_bytes':1048576} for n in graph['nodes']]}}
        window.apply_response(response,{'lab':lab,'action':'status'});self.root.update()
        self.assertTrue(all(n['values'][1]=='running' for n in (window.nodes.item(i) for i in window.nodes.get_children())))
        with self.assertRaises(ValueError):window.apply_response({**response,'lab':'wrong-lab'},{'lab':lab,'action':'status'})
        window.apply_response({'ok':False,'error':'Root result unconfirmed'},{'lab':lab,'action':'stop'})
        self.assertTrue(all(n['values'][1]=='non observé' for n in (window.nodes.item(i) for i in window.nodes.get_children())))

    def test_launch_uses_private_snapshot_and_correlated_async_result(self):
        window=self.window
        with tempfile.TemporaryDirectory() as directory,patch('network_labs.appliances.ui.launch_terminal',return_value=Mock()) as launch:
            window.path=Path(directory)/'canonical.json';self.assertTrue(window.launch('start'))
            pending=window.pending;request=pending['request'];self.assertNotEqual(request['target'],str(window.path))
            self.assertEqual(Path(request['target']).stat().st_mode&0o777,0o600);self.assertEqual(window.path.stat().st_mode&0o777,0o600)
            self.assertNotIn('sudo',launch.call_args.args[0]);self.assertEqual(window.editor.cget('state'),'disabled')
            bridge.private_json(Path(pending['directory'].name)/'result.json',{'id':request['id'],'action':'start','lab':request['lab'],'response':{'ok':False,'error':'Cancelled auth'}})
            window.poll_result();self.root.update();self.assertIsNone(window.pending)
            self.assertIn('Cancelled auth',window.note.get());self.assertEqual(window.editor.cget('state'),'normal')

    def test_search_redraw_and_backend_events_keep_real_results(self):
        window=self.window
        window.search.set('PC1');self.root.update()
        self.assertEqual(window.library.get_children(),('PC1',))
        window.draw(window.graph);self.root.update()
        self.assertEqual(window.library.get_children(),('PC1',))
        window.search.set('');self.root.update()
        self.assertEqual(len(window.library.get_children()),3)
        window.apply_response({'ok':False,'error':'Authentication canceled'}, {'lab':window.view_lab,'action':'start'})
        self.assertEqual(len(window.activity.get_children()),1)
        self.assertIn('Authentication canceled',str(window.activity.item(window.activity.get_children()[0])['values']))
        self.assertIs(window.output_tab.master,window.dock)

    def test_graphical_edit_click_drag_and_pending_or_mismatched_view_guards(self):
        from network_labs.appliances import topology_edit as edit
        window=self.window;spec=window.manifest()
        window.commit_edit(edit.add_node(spec,name='SW2',role='switch',rootfs='/tmp/rootfs',ports=4))
        self.root.update();self.assertIn('SW2',window.node_shapes);self.assertFalse(window.states)
        window.set_edit_mode('cable')
        with patch.object(window,'connect_dialog') as connect:
            window.node_pressed(SimpleNamespace(x=10,y=10),'SW1')
            window.node_pressed(SimpleNamespace(x=30,y=30),'SW2')
            connect.assert_called_once_with('SW1','SW2')
        window.set_edit_mode(None);before=window.drawn_positions['SW2']
        window.node_pressed(SimpleNamespace(x=100,y=100),'SW2')
        window.drag_node(SimpleNamespace(x=140,y=130));window.drop_node(SimpleNamespace())
        self.assertAlmostEqual(window.positions['SW2'][0],before[0]+40)
        self.assertAlmostEqual(window.positions['SW2'][1],before[1]+30)
        window.pending={'test':True}
        try:
            with self.assertRaises(ValueError):window.editing_spec()
        finally:window.pending=None
        window.editor.insert('1.0','invalid')
        with self.assertRaises(ValueError):window.editing_spec()
        window.editor.delete('1.0','end');window.editor.insert('1.0',json.dumps(spec))
        with self.assertRaises(ValueError):window.editing_spec()

    def test_add_and_connect_forms_apply_validated_draft(self):
        import tkinter as tk
        window=self.window
        def dialog():return [w for w in window.window.winfo_children() if isinstance(w,tk.Toplevel)][-1]
        def button(win,text):
            return next(w for f in win.winfo_children() for w in f.winfo_children() if 'text' in w.keys() and w.cget('text')==text)
        window.add_device_dialog();win=dialog();form=win.winfo_children()[0]
        for row,value in [(0,'SW2'),(1,'switch'),(3,'4')]:
            field=form.grid_slaves(row=row,column=1)[0]
            if row==1:field.set(value)
            else:field.delete(0,'end');field.insert(0,value)
        button(win,'Ajouter au brouillon').invoke();self.root.update()
        self.assertEqual(len(window.manifest()['nodes']),4)
        window.remove_cable(('SW1','eth1'),('PC2','eth0'))
        window.connect_dialog('SW1','SW2');win=dialog();button(win,'Connecter au brouillon').invoke();self.root.update()
        self.assertIn([['SW1','eth1'],['SW2','eth0']],window.manifest()['links'])

        window.connect_dialog('SW1','SW2');win=dialog();button(win,'Connecter au brouillon').invoke();self.root.update()
        self.assertIn([['SW1','eth2'],['SW2','eth1']],window.manifest()['links'])
