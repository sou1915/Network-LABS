import unittest,threading,time,json,http.client
from network_labs.web_portal import WebPortal
from test_web_api import FakeApp

class PortalTests(unittest.TestCase):
    def setUp(self):self.app=FakeApp();self.portal=WebPortal(self.app)
    def tearDown(self):self.portal.close()
    def request(self,method,path,body=None,headers=None):
        out={}
        def run():
            try:
                conn=http.client.HTTPConnection('127.0.0.1',self.portal.server.server_port,timeout=3)
                conn.request(method,path,body,headers or {});res=conn.getresponse();out.update(status=res.status,body=res.read(),headers=dict(res.getheaders()));conn.close()
            except Exception as error:out['error']=error
        worker=threading.Thread(target=run);worker.start();deadline=time.monotonic()+4
        while worker.is_alive() and time.monotonic()<deadline:self.portal.poll();time.sleep(.005)
        worker.join(.1)
        self.assertFalse(worker.is_alive());self.assertNotIn('error',out)
        return out
    def test_html_auth_and_host(self):
        response=self.request('GET','/')
        self.assertEqual(response['status'],200);self.assertIn(b'NETWORK LABS',response['body'])
        self.assertEqual(self.request('GET','/api/state?node=PC1')['status'],401)
        self.assertEqual(self.request('GET','/',headers={'Host':'evil.example'})['status'],403)
    def test_authenticated_roundtrip_and_csrf(self):
        headers={'Authorization':'Bearer '+self.portal.token,'Content-Type':'application/json'}
        state=self.request('GET','/api/state?node=PC1',headers=headers)
        self.assertEqual(state['status'],200);revision=json.loads(state['body'])['revision']
        body=json.dumps({'node':'PC1','revision':revision,'commands':['hostname WEB_CLIENT']})
        self.assertEqual(self.request('POST','/api/apply',body,{**headers,'Origin':'https://evil.example'})['status'],403)
        self.assertEqual(self.request('POST','/api/apply',body,headers)['status'],200)
        self.assertEqual(self.app.lab.nodes['PC1'].hostname,'WEB_CLIENT')
        self.assertEqual(self.request('POST','/api/apply',body,headers)['status'],409)
    def test_bad_json_and_paths(self):
        headers={'Authorization':'Bearer '+self.portal.token,'Content-Type':'application/json'}
        self.assertEqual(self.request('POST','/api/apply','bad',headers)['status'],400)
        self.assertEqual(self.request('GET','/../../README.md')['status'],404)

    def test_family_assets_are_served_without_arbitrary_files(self):
        for path,kind in [('/device_faces.css','text/css'),('/device_faces.js','text/javascript'),('/fortios_policy.css','text/css'),('/fortios_policy.js','text/javascript')]:
            response=self.request('GET',path)
            self.assertEqual(response['status'],200);self.assertTrue(response['headers']['Content-Type'].startswith(kind))
        self.assertEqual(self.request('GET','/vendor_cli.py')['status'],404)
