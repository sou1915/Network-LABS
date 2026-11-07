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

    def section(self,name,section,config):
        state=json.loads(self.request('GET','/api/state?node='+name,headers=self.headers)['body'])
        return self.request('POST','/api/apply',json.dumps({'node':name,'revision':state['revision'],'section':section,'config':config}),self.headers)

    def test_firewall_policy_nat_and_route_sections_preserve_unrelated_settings(self):
        from network_labs.appliances.firewall import render
        before=self.app.manifest()
        policy={'default':'drop','stateful':True,'rules':[{'name':'allow-admin','source':'192.168.10.10/32','destination':'172.16.0.10/32','protocol':'icmp','action':'accept'}],'nat':[{'name':'lan-out','type':'masquerade','out':'eth1','source':'192.168.10.0/24'}]}
        response=self.section('FW1','firewall',{'firewall':policy});self.assertEqual(response['status'],200,response['body'])
        fw=next(n for n in self.app.spec['nodes'] if n['name']=='FW1');rules=render(fw['firewall'])
        self.assertIn('rule:allow-admin',rules);self.assertIn('masquerade',rules)
        self.assertEqual([n for n in self.app.spec['nodes'] if n['name']!='FW1'],[n for n in before['nodes'] if n['name']!='FW1'])
        self.assertEqual(self.app.spec['links'],before['links'])
        original=self.app.manifest();policy['rules'][0]['protocol']='tcp; bad'
        self.assertEqual(self.section('FW1','firewall',{'firewall':policy})['status'],400);self.assertEqual(original,self.app.manifest())
        self.assertEqual(self.section('PC1','firewall',{'firewall':None})['status'],400)
        self.assertEqual(self.section('FW1','routing',{'routes':[],'gateway':'10.0.0.1','forwarding':True,'rootfs':'/new'})['status'],400)

    def test_switch_logical_routing_and_server_sections_validate_whole_lab(self):
        sw=next(n for n in self.app.spec['nodes'] if n['name']=='SW1')
        self.assertEqual(self.section('SW1','switching',{'vlans':[1,10,40],'switchports':sw['switchports']})['status'],200)
        self.assertEqual(self.section('SW1','svis',{'svis':{'vlan40':{'vlan':40,'address':'192.168.40.1/24'}}})['status'],200)
        self.assertEqual(self.section('SW1','routing',{'routes':[{'destination':'192.168.99.0/24','gateway':'192.168.40.2','interface':'vlan40'}],'gateway':'','forwarding':True})['status'],200)
        original=self.app.manifest()
        self.assertEqual(self.section('SW1','svis',{'svis':{}})['status'],400);self.assertEqual(original,self.app.manifest())
        self.assertEqual(self.section('SRV1','dnsserver',{'dns_server':{'interface':'eth0','zone':'lab.test','records':{'srv.lab.test':'172.16.0.10'},'ttl':60}})['status'],200)
        self.assertEqual(self.section('SRV1','dhcpserver',{'dhcp_server':{'interface':'eth0','start':'172.16.0.100','end':'172.16.0.110','router':'172.16.0.1','dns':['172.16.0.10'],'lease_seconds':3600,'reservations':[{'mac':'02:00:00:00:00:99','address':'172.16.0.99'}]}})['status'],200)
        original=self.app.manifest();self.app.pending={'action':'start'}
        self.assertEqual(self.section('SRV1','dnsserver',{'dns_server':None})['status'],400);self.assertEqual(original,self.app.manifest())

    def test_ipv6_and_addressing_are_typed_and_revision_guarded(self):
        from network_labs.appliances.spec import example
        self.app.spec=example('/tmp/rootfs');self.app.view_lab=self.app.spec['name']
        self.assertEqual(self.section('PC1','ipv6',{'ipv6':{'eth0':'2001:db8:10::10/64'},'ipv6_forwarding':False,'ipv6_routes':[]})['status'],200)
        original=self.app.manifest()
        self.assertEqual(self.section('PC1','addressing',{'resolvers':['192.168.10.1'],'dhcp_clients':[]})['status'],400)
        self.assertEqual(original,self.app.manifest())
        self.app.spec=example('/tmp/rootfs');self.app.view_lab=self.app.spec['name']
        self.assertEqual(self.section('PC1','addressing',{'resolvers':['192.168.10.1'],'dhcp_clients':[]})['status'],200)
        state=self.state();payload={'node':'PC1','revision':state['revision'],'section':'addressing','config':{'resolvers':[],'dhcp_clients':[]}}
        self.assertEqual(self.section('PC1','addressing',{'resolvers':['192.168.10.2'],'dhcp_clients':[]})['status'],200)
        original=self.app.manifest()
        self.assertEqual(self.request('POST','/api/apply',json.dumps(payload),self.headers)['status'],409);self.assertEqual(original,self.app.manifest())
        self.assertEqual(self.section('PC1','addressing',{'resolvers':[],'dhcp_clients':['eth0']})['status'],400);self.assertEqual(original,self.app.manifest())

    def test_stp_component_update_and_lacp_pair_edits_are_atomic(self):
        from network_labs.appliances.examples import lacp_lab
        self.app.spec=lacp_lab('/tmp/rootfs');self.app.view_lab=self.app.spec['name']
        original=self.app.manifest()
        policy={'mode':'stp','priority':4096,'hello_time':1,'max_age':6,'forward_delay':4,'carrier_recovery':False,'ports':{}}
        self.assertEqual(self.section('SW1','stp',{'spanning_tree':policy,'component':False})['status'],400)
        self.assertEqual(self.app.manifest(),original)
        self.assertEqual(self.section('SW1','stp',{'spanning_tree':policy,'component':True})['status'],200)
        nodes={n['name']:n for n in self.app.spec['nodes']}
        self.assertEqual(nodes['SW1']['spanning_tree']['priority'],4096)
        self.assertEqual(nodes['SW2']['spanning_tree']['priority'],32768)
        self.assertTrue(all(nodes[name]['spanning_tree']['mode']=='stp' for name in ('SW1','SW2')))
        config={'peer':'SW2','name':'bond1','peer_name':'bond1','members':['eth2','eth3'],'mode':'active','peer_mode':'passive','min_links':2,'strict':None,'switchport':nodes['SW1']['switchports']['bond1'],'operation':'upsert'}
        self.assertEqual(self.section('SW1','aggregation',config)['status'],200)
        self.assertTrue(all(n['port_channels']['bond1']['min_links']==2 for n in self.app.spec['nodes'] if n['role']=='switch'))
        original=self.app.manifest()
        for invalid in ({**config,'mode':'passive'},{**config,'members':['eth0','eth2']},{**config,'peer':'PC1'},{**config,'strict':'yes'},{**config,'rootfs':'/new'}):
            self.assertEqual(self.section('SW1','aggregation',invalid)['status'],400)
            self.assertEqual(self.app.manifest(),original)
        self.assertEqual(self.section('SW1','aggregation',{**config,'operation':'remove'})['status'],200)
        self.assertTrue(all(not n['port_channels'] for n in self.app.spec['nodes'] if n['role']=='switch'))
        self.assertEqual(self.section('SW1','aggregation',config)['status'],200)
        self.assertEqual(self.app.spec['links'],original['links'])

    def test_lldp_and_static_mac_admission_keep_backend_limits(self):
        self.assertEqual(self.section('SW1','lldp',{'lldp':{'ports':['eth0','eth1'],'tx_interval':2,'tx_hold':3}})['status'],200)
        original=self.app.manifest()
        self.assertEqual(self.section('SW1','lldp',{'lldp':{'ports':['missing'],'tx_interval':2,'tx_hold':3}})['status'],400)
        self.assertEqual(self.app.manifest(),original)
        policy={'eth1':{'maximum':1,'mac_addresses':['02:00:00:00:00:11'],'violation':'restrict'}}
        self.assertEqual(self.section('SW1','portsecurity',{'port_security':policy})['status'],200)
        original=self.app.manifest()
        for bad in ({'eth0':policy['eth1']},{'eth1':{**policy['eth1'],'violation':'shutdown'}},{'eth1':{**policy['eth1'],'maximum':2}}):
            self.assertEqual(self.section('SW1','portsecurity',{'port_security':bad})['status'],400)
            self.assertEqual(self.app.manifest(),original)
        from network_labs.appliances.examples import lacp_lab
        self.app.spec=lacp_lab('/tmp/rootfs');self.app.view_lab=self.app.spec['name']
        self.assertEqual(self.section('SW1','lldp',{'lldp':None})['status'],400)
