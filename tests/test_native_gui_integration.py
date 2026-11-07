"""Unprivileged Tk workbench -> real sudo bridge -> OCI packets -> GUI result."""
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile
import unittest
from network_labs.appliances.runtime import Manager,run,static_busybox_rootfs
from network_labs.appliances.spec import example
from test_native_integration import unexpected_host_link_changes


CHILD=r'''
import json,os,sys,time,tkinter as tk
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from network_labs.appliances import ui,topology_edit as edit
from network_labs.appliances.runtime import Manager
from network_labs.appliances.campus import campus_example
from PIL import ImageGrab
from tkinter import font as tkfont
assert os.geteuid()!=0,'The GUI must run unprivileged'
spec=json.loads(Path(sys.argv[2]).read_text());directory=Path(sys.argv[3]);artifacts=Path(sys.argv[4])
from network_labs.__main__ import App
root=tk.Tk();app=App(root);root.geometry('1280x720+0+0');window=app.open_native_lab();window.load_spec(spec,directory/'project.json')
assert window.embedded and window.window.master is root
assert app.lab.execution_backend=='model'
errors=[];root.report_callback_exception=lambda *error:errors.append(str(error));owners=[]
original=ui.read_result
def checked_result(path,request):
    assert path.stat().st_uid==os.geteuid();assert path.stat().st_mode&0o777==0o600
    owners.append(path.stat().st_uid);return original(path,request)
def direct_terminal(command):
    # CI has passwordless sudo. Replace only terminal presentation: the same
    # unprivileged wrapper still authenticates and invokes the actual backend.
    return ui.subprocess.Popen(command,stdin=ui.subprocess.DEVNULL,stdout=ui.subprocess.DEVNULL,stderr=ui.subprocess.DEVNULL)
def drive(action,ok=True):
    assert window.launch(action),window.note.get()
    deadline=time.monotonic()+50
    while window.pending and time.monotonic()<deadline:root.update();time.sleep(.03)
    assert window.pending is None,action+' timed out'
    assert window.last_response is not None and window.last_response['ok']==ok,(action,window.last_response,window.note.get())
    assert os.geteuid()!=0
    return window.last_response
try:
    with patch.object(ui,'launch_terminal',side_effect=direct_terminal),patch.object(ui,'read_result',side_effect=checked_result):
        root.update();assert len(window.node_shapes)==3;assert len(window.canvas.find_withtag('link'))==2
        ui_font=tkfont.Font(root=root,font=(window.font,10)).actual('family')
        assert ui_font.casefold().replace(' ','').startswith('inter'),ui_font
        original_draft=window.manifest()
        window.canvas.event_generate('<MouseWheel>',x=200,y=140,delta=120);root.update()
        assert window.zoom>1 and window.manifest()==original_draft
        window.reset_view();root.update()
        # The supplied campus design is a real native template, not sample UI data.
        draft=campus_example(spec['nodes'][0]['rootfs'],spec['name'])
        for node in draft['nodes']:
            if node['name'] in ('PC1','PC4'):node['interface_macs']['eth0']='02:00:00:00:00:'+('11' if node['name']=='PC1' else '44')
        window.commit_edit(draft);window.draw(window.graph);root.update()
        assert len(window.node_shapes)==10 and len(window.canvas.find_withtag('link'))==9
        assert not window.states and len(window.manifest()['nodes'])==10
        window.choose_node('PC3');window.load_config(force=True)
        window.config_vars['name'].set('CLIENT3');window.config_vars['address'].set('192.168.20.32/24');window.config_vars['gateway'].set('192.168.20.1')
        assert window.apply_config(),window.config_message.get()
        assert 'CLIENT3' in window.node_shapes and 'PC3' not in window.node_shapes
        # Actual HTTP management edits the same native draft, then the kernel
        # probe below must reach the address configured from the web API.
        from network_labs.web_portal import WebPortal
        from network_labs.appliances.web_management import NativeDeviceAPI
        import http.client,threading
        window.web_portal=WebPortal(window,api=NativeDeviceAPI(window),native=True)
        portal=window.web_portal
        def web_request(method,path,payload=None):
            reply={}
            def worker():
                try:
                    connection=http.client.HTTPConnection('127.0.0.1',portal.server.server_port,timeout=4)
                    headers={'Authorization':'Bearer '+portal.token,'Content-Type':'application/json'}
                    connection.request(method,path,json.dumps(payload) if payload else None,headers)
                    response=connection.getresponse();reply.update(status=response.status,data=json.loads(response.read()));connection.close()
                except Exception as error:reply['error']=str(error)
            thread=threading.Thread(target=worker);thread.start();deadline=time.monotonic()+6
            while thread.is_alive() and time.monotonic()<deadline:root.update();time.sleep(.01)
            thread.join(.1);assert not thread.is_alive() and 'error' not in reply,reply
            assert reply['status']==200,reply
            return reply['data']
        web_state=web_request('GET','/api/state?node=CLIENT3')
        web_state=web_request('POST','/api/apply',{'node':'CLIENT3','revision':web_state['revision'],'name':'CLIENT3','port':'eth0','address':'192.168.20.33/24','gateway':'192.168.20.1','enabled':True})
        assert web_state['node']['interfaces']['eth0']=='192.168.20.33/24'
        assert window.config_vars['address'].get()=='192.168.20.33/24'
        firewall_state=web_request('GET','/api/state?node=FW1')
        firewall_policy={'default':'drop','stateful':True,'rules':[
            {'name':'web-admin-dmz','action':'accept','source':'192.168.10.10/32','destination':'172.16.0.10/32','protocol':'icmp'},
            {'name':'web-dmz-admin','action':'accept','source':'172.16.0.10/32','destination':'192.168.10.10/32','protocol':'icmp'}],'nat':[]}
        firewall_state=web_request('POST','/api/apply',{'node':'FW1','revision':firewall_state['revision'],'section':'firewall','config':{'firewall':firewall_policy}})
        assert len(firewall_state['node']['firewall']['rules'])==2
        for switch,port,mac in [('SW1','eth1','02:00:00:00:00:11'),('SW2','eth2','02:00:00:00:00:99')]:
            switch_state=web_request('GET','/api/state?node='+switch)
            switch_state=web_request('POST','/api/apply',{'node':switch,'revision':switch_state['revision'],'section':'portsecurity','config':{'port_security':{port:{'maximum':1,'mac_addresses':[mac],'violation':'restrict'}}}})
            assert switch_state['node']['port_security'][port]['mac_addresses']==[mac]
        drive('start');assert {v['status'] for v in window.states.values()}=={'running'}
        try:Manager(spec['name']).read()
        except PermissionError:root_state_denied=True
        else:raise AssertionError('GUI could directly read root-owned runtime state')
        drive('status');window.choose_node('CLIENT3')
        inspected=drive('inspect');assert inspected['data']['name']=='CLIENT3';assert inspected['data']['links']
        assert any(r.get('dst')=='default' and r.get('gateway')=='192.168.20.1' for r in inspected['data']['routes'])
        window.choose_node('PC2');window.destination.set('SRV1');isolated=drive('verify')
        assert isolated['data']['status']=='failed',isolated['data']
        assert isolated['data']['probe_commands_attempted']==2
        window.choose_node('PC1');window.destination.set('SRV1');firewall_allowed=drive('verify')
        assert firewall_allowed['data']['status']=='passed',firewall_allowed['data']
        window.choose_node('PC4');window.destination.set('CLIENT3');mac_blocked=drive('verify')
        assert mac_blocked['data']['status']=='failed',mac_blocked['data']
        security_observed={}
        for switch,port,counter in [('SW1','eth1','accepted_packets'),('SW2','eth2','dropped_packets')]:
            window.choose_node(switch);security=drive('inspect')['data']['port_security']
            assert security['available'] and security['fingerprint_matches'],security
            assert security['ports'][port][counter]>0,security
            security_observed[switch]=security
        window.choose_node('PC1')
        window.destination.set('CLIENT3');verified=drive('verify')
        assert verified['data']['status']=='passed',verified['data']
        assert verified['data']['directions'][0]['destination_address']=='192.168.20.33'
        assert len(window.activity.get_children())==13
        assert window.vlan_members=={'PC1':10,'PC2':10,'CLIENT3':20,'PC4':20,'PC5':30}
        assert len(window.canvas.find_withtag('vlan-group'))==3
        assert 'PING 192.168.20.33' in window.output.get('1.0','end')
        assert window.output_tab.master is window.dock
        root.update()
        assert window.verify_button.winfo_rooty()+window.verify_button.winfo_height()<=window.window.winfo_rooty()+window.window.winfo_height()-190
        window.choose_node('FW1');window.device_tabs.select(window.config_panel)
        window.tabs.select(window.topology_tab);root.update();time.sleep(.1);root.update()
        assert window.config_apply.winfo_ismapped()
        assert window.config_apply.winfo_rooty()+window.config_apply.winfo_height()<=window.window.winfo_rooty()+window.window.winfo_height()
        assert window.nav_current=='Topologie'
        root.event_generate('<Motion>',warp=True,x=90,y=15);root.update()
        box=(window.window.winfo_rootx(),window.window.winfo_rooty(),window.window.winfo_rootx()+window.window.winfo_width(),window.window.winfo_rooty()+window.window.winfo_height())
        ImageGrab.grab(bbox=box).save(artifacts/'native-gui-running.png')
        window.set_zoom(1.35);root.update();time.sleep(.1);root.update()
        ImageGrab.grab(bbox=box).save(artifacts/'native-gui-zoomed.png')
        assert window.zoom==1.35
        window.reset_view();root.update()
        drive('stop');assert {v['status'] for v in window.states.values()}=={'stopped'}
        drive('status',ok=False);assert all(v['values'][1]=='non observé' for v in (window.nodes.item(i) for i in window.nodes.get_children()))
        assert set(owners)=={os.geteuid()} and len(owners)==11,owners
        assert (directory/'project.json').stat().st_mode&0o777==0o600
        (artifacts/'native-gui-result.json').write_text(json.dumps({'ui_font':ui_font,'viewport_zoom_verified':True,'native_web_http_apply_verified':True,'native_web_firewall_policy_verified':True,'native_web_port_security_verified':True,'mac_blocked':mac_blocked['data'],'port_security':security_observed,'firewall_allowed':firewall_allowed['data'],'gui_uid':os.geteuid(),'result_owner_uids':owners,'root_state_denied':root_state_denied,'node_count':10,'link_count':9,'verified':verified['data'],'isolated':isolated['data'],'stopped':True,'callback_errors':errors},indent=2))
        window.close();root.update()
        assert app.workspace.winfo_ismapped() and app.lab.execution_backend=='model'
        assert not errors,errors
finally:root.destroy()
'''


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_GUI_TESTS')=='1','Opt-in privileged native GUI integration')
class NativeWorkbenchIntegrationTests(unittest.TestCase):
    def test_unprivileged_gui_lifecycle_observations_packets_and_private_root_results(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('crun','ip','busybox','sudo','xvfb-run'):self.assertIsNotNone(shutil.which(tool),tool)
        uid=int(os.environ.get('SUDO_UID','-1'));self.assertGreater(uid,0,'Run from a non-root hosted-runner account via sudo')
        user=pwd.getpwuid(uid)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        routes={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);root.chmod(0o755)
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs')
            spec=example(rootfs);spec['name']='Campus-entreprise-'+str(os.getpid());manager=Manager(spec['name'])
            manifest=root/'input.json';manifest.write_text(json.dumps(spec));manifest.chmod(0o644)
            work=root/'user';work.mkdir(mode=0o700);os.chown(work,user.pw_uid,user.pw_gid)
            artifacts=Path(os.environ.get('NETWORK_LABS_NATIVE_GUI_ARTIFACT_DIR',str(root/'artifacts')))
            artifacts.mkdir(mode=0o755,parents=True,exist_ok=True);os.chown(artifacts,user.pw_uid,user.pw_gid)
            try:
                completed=run(['sudo','-u',user.pw_name,'--','xvfb-run','-a','/usr/bin/python3','-I','-c',CHILD,
                               str(Path(__file__).parents[1]),str(manifest),str(work),str(artifacts)],check=False,timeout=180)
                self.assertEqual(completed.returncode,0,completed.stderr[-6000:])
                result=json.loads((artifacts/'native-gui-result.json').read_text())
                self.assertEqual(result['gui_uid'],uid);self.assertTrue(result['root_state_denied']);self.assertTrue(result['stopped'])
                self.assertEqual(result['callback_errors'],[]);self.assertFalse(manager.directory.exists())
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in routes.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
