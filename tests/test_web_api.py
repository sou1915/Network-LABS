import unittest,threading
from network_labs.__main__ import App
from network_labs.web_api import DeviceAPI,Conflict
from network_labs.cli import Session

class FakeRoot:
    def after(self,*args):return 'job'
    def after_cancel(self,*args):pass
    def lift(self):pass

class FakeApp:
    def __init__(self):self.lab=App.lan_demo();self.root=FakeRoot();self.owner=threading.get_ident();self.changes=[]
    def changed(self,message):
        assert threading.get_ident()==self.owner
        self.changes.append(message)
    def animate_result(self,ok,message):self.result=(ok,message)
    def open_cli(self,node):self.cli=node

class WebAPITests(unittest.TestCase):
    def setUp(self):self.app=FakeApp();self.api=DeviceAPI(self.app)
    def test_state_and_atomic_configuration(self):
        state=self.api.dispatch('state',{'node':'PRN1'})
        self.assertEqual(len(state['revision']),64);self.assertEqual(state['profile']['role'],'Imprimante')
        before=self.app.lab.dumps()
        with self.assertRaises(ValueError):
            self.api.dispatch('apply',{'node':'PRN1','revision':state['revision'],'commands':['ip address 10.0.0.2/24','ip gateway bad']})
        self.assertEqual(before,self.app.lab.dumps())
        updated=self.api.dispatch('apply',{'node':'PRN1','revision':state['revision'],'commands':['hostname PRINT_FLOOR1']})
        self.assertNotEqual(updated['revision'],state['revision'])
    def test_revision_conflict_and_lab_replacement(self):
        state=self.api.snapshot('PC1');Session(self.app.lab,'PC1').execute('hostname CLIENT')
        with self.assertRaises(Conflict):self.api.dispatch('apply',{'node':'PC1','revision':state['revision'],'commands':['hostname OLD']})
        state=self.api.snapshot('PC1');self.app.lab=App.lan_demo()
        with self.assertRaises(Conflict):self.api.dispatch('apply',{'node':'PC1','revision':state['revision'],'commands':['hostname OLD']})
    def test_port_probe_and_cli_action(self):
        result=self.api.dispatch('test',{'node':'PC1','protocol':'tcp','target':'nas.lan','port':445})
        self.assertTrue(result['ok']);self.assertTrue(self.app.result[0])
        self.api.dispatch('cli',{'node':'PC1'});self.assertEqual(self.app.cli,'PC1')
    def test_command_payload_rejection(self):
        revision=self.api.snapshot('PC1')['revision']
        for commands in [[],['hostname A\nip gateway 1.1.1.1'],[1]]:
            with self.assertRaises(ValueError):self.api.dispatch('apply',{'node':'PC1','revision':revision,'commands':commands})
