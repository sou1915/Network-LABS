import copy
import json
import unittest
from network_labs.appliances.campus import campus_example
from network_labs.appliances.web_management import NativeDeviceAPI
from network_labs.web_portal import WebPortal
from test_web_api import FakeRoot
import test_web_portal


class Workbench:
    def __init__(self):
        self.root=FakeRoot();self.spec=campus_example('/tmp/native-rootfs');self.view_lab=self.spec['name'];self.states={};self.pending=None;self.positions={};self.config_key=None;self.events=[]
    def manifest(self):return copy.deepcopy(self.spec)
    def editing_spec(self):
        if self.pending:raise ValueError('Opération en cours.')
        return self.manifest()
    def commit_edit(self,spec):self.spec=spec
    def choose_node(self,name):self.selected=name
    def load_config(self,force=False):pass
    def record_event(self,*args):self.events.append(args)


class NativePortalTests(unittest.TestCase):
    request=test_web_portal.PortalTests.request
    def setUp(self):self.app=Workbench();self.portal=WebPortal(self.app,api=NativeDeviceAPI(self.app),native=True);self.headers={'Authorization':'Bearer '+self.portal.token,'Content-Type':'application/json'}
    def tearDown(self):self.portal.close()
    def state(self):return json.loads(self.request('GET','/api/state?node=PC1',headers=self.headers)['body'])
    def payload(self):return {'node':'PC1','revision':self.state()['revision'],'name':'WEBCLIENT','port':'eth0','address':'192.168.10.44/24','gateway':'192.168.10.1','enabled':True}
    def test_web_roundtrip_updates_native_draft_and_rejects_stale_or_invalid_writes(self):
        payload=self.payload();original=self.app.manifest();bad={**payload,'address':'not-an-ip'}
        self.assertEqual(self.request('POST','/api/apply',json.dumps(bad),self.headers)['status'],400);self.assertEqual(self.app.manifest(),original)
        response=self.request('POST','/api/apply',json.dumps(payload),self.headers)
        self.assertEqual(response['status'],200);self.assertEqual(self.app.selected,'WEBCLIENT')
        updated=json.loads(response['body']);self.assertEqual(updated['node']['interfaces']['eth0'],'192.168.10.44/24');self.assertNotIn('rootfs',updated['node'])
        stale={**payload,'node':'WEBCLIENT'}
        self.assertEqual(self.request('POST','/api/apply',json.dumps(stale),self.headers)['status'],409)
    def test_native_portal_auth_origin_busy_and_operation_boundaries(self):
        payload=self.payload();original=self.app.manifest()
        self.assertEqual(self.request('GET','/api/state?node=PC1')['status'],401)
        self.assertEqual(self.request('POST','/api/apply',json.dumps(payload),{**self.headers,'Origin':'https://example.com'})['status'],403)
        self.app.pending={'action':'start'}
        self.assertFalse(self.state()['editable'])
        self.assertEqual(self.request('POST','/api/apply',json.dumps(payload),self.headers)['status'],400)
        self.assertEqual(self.request('POST','/api/native',json.dumps(payload),self.headers)['status'],400)
        self.assertEqual(self.app.manifest(),original)
    def test_native_assets_and_state_are_specific_to_native_management(self):
        page=self.request('GET','/');self.assertIn(b'Gestion native',page['body']);self.assertIn(b'Appliquer au brouillon',page['body'])
        font=self.request('GET','/InterVariable.ttf');self.assertEqual(font['status'],200);self.assertEqual(font['headers']['Content-Type'],'font/ttf')
        self.assertEqual(self.request('GET','/appliances/assets/INTER-LICENSE.txt')['status'],404)
        self.app.view_lab='another-lab';self.app.states={'PC1':{'status':'running'}}
        self.assertEqual(self.state()['observed'],'non observé')
        self.assertIn("frame-ancestors 'none'",page['headers']['Content-Security-Policy'])

    def test_switch_and_dhcp_addresses_keep_the_same_readonly_boundary_as_tk(self):
        state=json.loads(self.request('GET','/api/state?node=SW1',headers=self.headers)['body'])
        payload={'node':'SW1','revision':state['revision'],'name':'SW1','port':'eth0','address':'192.168.10.2/24','gateway':'','enabled':True}
        original=self.app.manifest()
        self.assertEqual(self.request('POST','/api/apply',json.dumps(payload),self.headers)['status'],400)
        self.assertEqual(self.app.manifest(),original)
        pc=next(n for n in self.app.spec['nodes'] if n['name']=='PC1');pc['interfaces']['eth0']='';pc['dhcp_clients']=['eth0']
        payload=self.payload()
        original=self.app.manifest()
        self.assertEqual(self.request('POST','/api/apply',json.dumps(payload),self.headers)['status'],400)
        self.assertEqual(self.app.manifest(),original)
