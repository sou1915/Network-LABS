"""Controlled-port scope, bounded kernel admissions and EAPOL parsing boundaries."""
import copy
import json
import struct
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from network_labs.appliances.examples import dot1x_lab
from network_labs.appliances.dot1x import TABLE, gate_snapshot, render, stop
from network_labs.appliances.dot1x_worker import current, envelope, serve, gate, admission_policy
from network_labs.appliances.firewall import fingerprint
from network_labs.appliances.lan import configure
from network_labs.appliances.spec import validate
from network_labs.appliances.runtime import Manager, RuntimeFailure


class Dot1xTests(unittest.TestCase):
    def spec(self):return dot1x_lab('/rootfs','private-dot1x-secret','a'*64,'/private/password')

    def test_verified_session_policy_caps_lease_and_rejects_ambiguous_or_unsupported_values(self):
        def field(kind,value):return bytes((kind,len(value)+2))+value
        self.assertEqual(admission_policy(bytes(20),5),(5,None,0))
        for maximum,timeout in ((30,1),(30,3),(2,30),(30,4294967295)):
            self.assertEqual(admission_policy(bytes(20)+field(27,timeout.to_bytes(4,'big'))+field(29,bytes(4)),maximum),(min(maximum,timeout),timeout,0))
        valid=field(27,(3).to_bytes(4,'big'))
        self.assertEqual(admission_policy(bytes(20)+valid+field(29,(1).to_bytes(4,'big')),30),(3,3,1))
        for invalid in (field(27,bytes(4)),valid+valid,field(27,b'\x01'),field(29,(1).to_bytes(4,'big')),valid+field(29,(2).to_bytes(4,'big')),field(29,bytes(4))*2,b'\x1b',b'\x1b\x01'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):admission_policy(bytes(20)+invalid,30)

    def test_shortened_kernel_element_keeps_configured_default_policy_and_checks_shorter_bound(self):
        config=dict(port='eth0',seconds=5,peer_mac='02:00:00:00:01:10',fingerprint='original')
        with patch('network_labs.appliances.dot1x_worker.nft',return_value='{}') as nft,patch('network_labs.appliances.dot1x_worker.gate_snapshot',side_effect=[('original',False),('original',True)]) as snapshot:
            gate(config,True,seconds=2)
        script=nft.call_args_list[1].kwargs['input_text']
        self.assertIn('timeout 5s; size 1;',script);self.assertIn('"eth0" timeout 2s',script)
        self.assertEqual(snapshot.call_args.args[2],2)
        for duration in (0,6,True):
            with patch('network_labs.appliances.dot1x_worker.nft') as nft,self.assertRaises(ValueError):gate(config,True,seconds=duration)
            nft.assert_not_called()

    def test_grant_atomically_replaces_verified_gate_without_increasing_capacity(self):
        config=dict(port='eth0',seconds=5,peer_mac='02:00:00:00:01:10',fingerprint='original')
        with patch('network_labs.appliances.dot1x_worker.nft',return_value='{}') as nft,patch('network_labs.appliances.dot1x_worker.gate_snapshot',side_effect=[('original',False),('original',True)]):
            gate(config,True)
        script=nft.call_args_list[1].kwargs['input_text']
        self.assertEqual(script,'delete table bridge '+TABLE+'\n'+render({'dot1x':config},config['peer_mac'])+'add element bridge '+TABLE+' admitted { "eth0" timeout 5s }\n')
        self.assertIn('size 1;',script);self.assertEqual(nft.call_count,3)
        with patch('network_labs.appliances.dot1x_worker.nft',return_value='{}') as nft,patch('network_labs.appliances.dot1x_worker.gate_snapshot',return_value=('foreign',False)):
            with self.assertRaises(ValueError):gate(config,True)
            self.assertEqual(nft.call_count,1,'Drift must refuse before replacement')

    def test_save_refreshes_cached_state_and_preserves_other_cli_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=Manager('dot1x-lan');manager.directory=Path(folder)
            manager.state={'phase':'running','spec':self.spec()}
            latest={**manager.state,'dot1x_workers':{'SW1':{'pid':99,'starttime':'123','token':'original'}}}
            (manager.directory/'state.json').write_text(json.dumps(latest))
            with patch('network_labs.appliances.persistence.drift',return_value=[]),patch('network_labs.appliances.persistence.save_startup'):
                manager.write_startup()
            self.assertEqual(json.loads((manager.directory/'state.json').read_text())['dot1x_workers'],latest['dot1x_workers'])

    def test_worker_refuses_recreated_namespace_interface_or_runtime_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json';info=Path('/proc/self/ns/net').stat()
            state={'phase':'running','dot1x_workers':{'SW1':{'token':'original'}}}
            path.write_text(json.dumps(state))
            config=dict(namespace_dev=info.st_dev,namespace_ino=info.st_ino,port='eth0',ifindex=4,state_file=str(path),node='SW1',token='original')
            with patch('socket.if_nametoindex',return_value=4):
                current(config)
                for fault in ({'namespace_ino':info.st_ino+1},{'ifindex':5},{'token':'recreated'}):
                    with self.subTest(fault=fault),self.assertRaises(ValueError):current({**config,**fault})
                state['pending_spec']={};path.write_text(json.dumps(state))
                with self.assertRaises(ValueError):current(config)
                current(config,False)  # Original owner may still close during teardown.

    def test_queued_logoff_precedes_backend_success_and_replayed_identity_is_discarded(self):
        raw=Mock();udp=Mock()
        for sock in (raw,udp):
            sock.__enter__=Mock(return_value=sock);sock.__exit__=Mock(return_value=False)
        own=bytes.fromhex('020000000101');peer=bytes.fromhex('020000000110')
        raw.getsockname.return_value=('eth0',0,0,0,own)
        def frame(payload):return own+peer+b'\x88\x8e'+struct.pack('!BBH',2,0,len(payload))+payload
        identity=struct.pack('!BBH',2,7,12)+b'\x01learner'
        replay=struct.pack('!BBH',2,6,12)+b'\x01learner'
        proof=struct.pack('!BBH',2,8,22)+b'\x04\x10'+bytes(16)
        raw.recv.side_effect=[frame(replay),frame(identity),frame(proof),own+peer+b'\x88\x8e\x02\x02\x00\x00']
        udp.recvfrom.return_value=(b'verified-challenge',('192.0.2.20',1812))
        challenge=struct.pack('!BBH',1,8,22)+b'\x04\x10'+bytes(16)
        ready=lambda *s:(list(s),[],[])
        config=dict(port='eth0',peer_mac='02:00:00:00:01:10',source='192.0.2.1',address='192.0.2.20',users=['learner'],timeout=5,seconds=5,secret='test')
        with patch('network_labs.appliances.dot1x_worker.LinkMonitor'),patch('network_labs.appliances.dot1x_worker.current'),patch('network_labs.appliances.dot1x_worker.publish'),patch('network_labs.appliances.dot1x_worker.gate') as gate,patch('socket.socket',side_effect=[raw,udp]),patch('secrets.randbelow',return_value=7),patch('select.select',side_effect=[ready(raw),ready(raw),ready(udp),ready(),ready(raw),ready(udp),ready(raw),ready(raw,udp)]),patch('network_labs.appliances.dot1x_worker.access_request',return_value=b'\x01\x09'),patch('network_labs.appliances.dot1x_worker.response_code',return_value=11),patch('network_labs.appliances.dot1x_worker.inner',return_value=(challenge,b'opaque-state')):
            result=serve(config)
        self.assertEqual(result['reason'],'LOGOFF');self.assertEqual(result['status'],'blocked')
        self.assertFalse(result['authenticated']);self.assertTrue(result['port_closed'])
        self.assertEqual(result['radius_requests'],2);self.assertEqual(result['discarded'],1)
        self.assertEqual(gate.call_count,2);self.assertTrue(all(len(call.args)==1 for call in gate.call_args_list))
        self.assertEqual(udp.recvfrom.call_count,1,'Queued Success must remain unread after Logoff')

    def test_bounded_explicit_topology_and_canonical_policy(self):
        spec=self.spec();self.assertEqual(spec,validate(spec))
        node=spec['nodes'][1];self.assertEqual(node['svis']['vlan1']['address'],'192.0.2.1/24')
        self.assertEqual(spec['nodes'][2]['radius_server']['clients'][0]['address'],'192.0.2.1')
        for fault in ({'seconds':0},{'seconds':31},{'seconds':True},{'reauthentications':-1},{'reauthentications':4},{'reauthentications':True},{'reauthentications':'1'},{'port':'eth9'},{'port':[]},{'users':[]},{'users':['learner','learner']},{'peer':'PC2'},{'server':'127.0.0.1'},{'svi':'vlan9'}):
            with self.subTest(fault=fault),self.assertRaises((ValueError,TypeError)):
                bad=copy.deepcopy(spec);bad['nodes'][1]['dot1x'].update(fault);validate(bad)
        bad=copy.deepcopy(spec);bad['nodes'][0]['interface_macs']={}
        with self.assertRaises(ValueError):validate(bad)

    def test_finite_reauthentication_resets_state_and_closes_before_each_fresh_exchange(self):
        for renewals in (0,1,3):
            with self.subTest(renewals=renewals):
                result,transitions,requests=self.simulated_cycles(renewals)
                self.assertEqual(result['status'],'passed',result)
                self.assertEqual(result['completed_authentications'],renewals+1)
                self.assertEqual(result['radius_requests'],2*(renewals+1))
                self.assertEqual(transitions,[False]+[v for _ in range(renewals+1) for v in (True,False)])
                for index,call in enumerate(requests):
                    if index%2==0:self.assertEqual(len(call.args),2,'Fresh exchange must not reuse old State')
                    else:self.assertEqual(call.args[2],b'state-'+bytes([index//2]))

    def simulated_cycles(self,renewals,*,outage=False,changed_identity=False,rejected=False,link_loss=None,policy=b''):
        raw=Mock();udp=Mock()
        for sock in (raw,udp):
            sock.__enter__=Mock(return_value=sock);sock.__exit__=Mock(return_value=False)
        own=bytes.fromhex('020000000101');peer=bytes.fromhex('020000000110')
        raw.getsockname.return_value=('eth0',0,0,0,own)
        def eap(code,identifier,payload=b''):return struct.pack('!BBH',code,identifier,4+len(payload))+payload
        def frame(packet):return own+peer+b'\x88\x8e'+struct.pack('!BBH',2,0,len(packet))+packet
        events=[];responses=[];clock=[0.0]
        for cycle in range(renewals+1):
            identifier=7+2*cycle;when=cycle*1.1
            user=b'other' if changed_identity and cycle else b'learner'
            events.append((when,raw,frame(eap(2,identifier,b'\x01'+user))))
            if outage and cycle:break
            reject=rejected and cycle>0
            events.extend([(when,udp,b'challenge'),(when,raw,frame(eap(2,identifier+1,b'\x04\x10'+bytes(16)))),(when,udp,b'reject' if reject else b'success')])
            responses.extend([(eap(1,identifier+1,b'\x04\x10'+bytes(16)),b'state-'+bytes([cycle])),(eap(4 if reject else 3,identifier+1),None)])
        def select_ready(read,write,error,timeout):
            if len(read)==1:return [],[],[]  # No queued EAPOL before these signed replies.
            if events and events[0][0]<=clock[0]+timeout:
                when,sock,payload=events.pop(0);clock[0]=max(clock[0],when)
                if sock is raw:raw.recv.return_value=payload
                else:udp.recvfrom.return_value=(payload,('192.0.2.20',1812))
                return [sock],[],[]
            clock[0]+=timeout
            return [],[],[]
        config=dict(port='eth0',peer_mac='02:00:00:00:01:10',source='192.0.2.1',address='192.0.2.20',users=['learner','other'],timeout=1,seconds=1,secret='test',reauthentications=renewals)
        transitions=[]
        with (
            patch('network_labs.appliances.dot1x_worker.LinkMonitor') as monitor,
            patch('network_labs.appliances.dot1x_worker.current'),
            patch('network_labs.appliances.dot1x_worker.publish'),
            patch('network_labs.appliances.dot1x_worker.gate',side_effect=lambda config,admit=False,**options:transitions.append(admit)),
            patch('socket.socket',side_effect=[raw,udp]),
            patch('secrets.randbelow',return_value=7),
            patch('time.monotonic',side_effect=lambda:clock[0]),
            patch('select.select',side_effect=select_ready),
            patch('network_labs.appliances.dot1x_worker.access_request',return_value=b'\x01\x09') as requests,
            patch('network_labs.appliances.dot1x_worker.response_code',side_effect=lambda packet,*_:{b'challenge':11,b'success':2,b'reject':3}[packet]),
            patch('network_labs.appliances.dot1x_worker.inner',side_effect=responses),
            patch('network_labs.appliances.dot1x_worker.admission_policy',side_effect=lambda packet,maximum:admission_policy(bytes(20)+policy,maximum)),
        ):
            if link_loss is not None:
                from network_labs.appliances.dot1x_link import LinkLost
                monitor.return_value.__enter__.return_value.check.side_effect=[None]*(link_loss-1)+[LinkLost()]
            result=serve(config)
        return result,transitions,requests.call_args_list

    def test_reauthentication_timeout_never_passes_on_earlier_success(self):
        result,transitions,_=self.simulated_cycles(1,outage=True)
        self.assertEqual(result['status'],'unknown');self.assertEqual(result['reason'],'AUTH_TIMEOUT')
        self.assertEqual(result['completed_authentications'],1);self.assertTrue(result['port_closed'])
        self.assertEqual(transitions,[False,True,False,False])

    def test_backend_session_timeout_ends_command_without_spending_unused_renewals(self):
        result,transitions,calls=self.simulated_cycles(3,policy=b'\x1b\x06\x00\x00\x00\x01')
        self.assertEqual(result['status'],'passed',result);self.assertEqual(result['reason'],'SERVER_SESSION_TIMEOUT')
        self.assertEqual(result['authorization_seconds'],1);self.assertEqual(result['server_session_timeout'],1)
        self.assertEqual(result['completed_authentications'],1);self.assertEqual(len(calls),2)
        self.assertEqual(transitions,[False,True,False]);self.assertTrue(result['port_closed'])

    def test_invalid_backend_policy_never_opens_gate_despite_verified_eap_success(self):
        for policy in (b'\x1b\x06'+bytes(4),b'\x1d\x06\x00\x00\x00\x01'):
            result,transitions,_=self.simulated_cycles(3,policy=policy)
            self.assertEqual(result['status'],'unknown',result);self.assertFalse(result['authenticated'])
            self.assertTrue(result['port_closed']);self.assertEqual(transitions,[False,False])

    def test_backend_reauthentication_uses_local_budget_closes_between_cycles_and_keeps_fresh_state(self):
        policy=b'\x1b\x06\x00\x00\x00\x01\x1d\x06\x00\x00\x00\x01'
        for budget in (0,1,3):
            result,transitions,calls=self.simulated_cycles(budget,policy=policy)
            self.assertEqual(result['status'],'passed',result);self.assertEqual(result['reason'],'SERVER_SESSION_TIMEOUT')
            self.assertEqual(result['completed_authentications'],budget+1);self.assertEqual(result['radius_requests'],2*(budget+1))
            self.assertEqual(result['server_termination_action'],1);self.assertTrue(result['port_closed'])
            self.assertEqual(transitions,[False]+[v for _ in range(budget+1) for v in (True,False)])
            for index,call in enumerate(calls):
                if index%2==0:self.assertEqual(len(call.args),2)
                else:self.assertEqual(call.args[2],b'state-'+bytes([index//2]))

    def test_backend_reauthentication_outage_or_identity_change_never_reuses_earlier_admission(self):
        policy=b'\x1b\x06\x00\x00\x00\x01\x1d\x06\x00\x00\x00\x01'
        for fault,status,reason in (({'outage':True},'unknown','AUTH_TIMEOUT'),({'changed_identity':True},'blocked','IDENTITY_CHANGED'),({'rejected':True},'failed','REJECTED')):
            result,transitions,_=self.simulated_cycles(1,policy=policy,**fault)
            self.assertEqual(result['status'],status,result);self.assertEqual(result['reason'],reason)
            self.assertEqual(result['completed_authentications'],1);self.assertTrue(result['port_closed'])
            self.assertEqual(transitions,[False,True,False,False])

    def test_carrier_loss_before_success_or_during_admission_ends_all_renewals_closed(self):
        for boundary,authenticated,requests in ((9,False,2),(10,True,2)):
            with self.subTest(boundary=boundary):
                result,transitions,calls=self.simulated_cycles(3,link_loss=boundary)
                self.assertEqual(result['status'],'blocked',result);self.assertEqual(result['reason'],'LINK_LOST')
                self.assertEqual(result['authenticated'],authenticated);self.assertTrue(result['port_closed'])
                self.assertEqual(result['radius_requests'],requests);self.assertEqual(len(calls),requests)
                self.assertEqual(transitions,[False,True,False] if authenticated else [False,False])

    def test_verified_reauthentication_reject_never_reopens_the_port(self):
        result,transitions,_=self.simulated_cycles(1,rejected=True)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['reason'],'REJECTED')
        self.assertEqual(result['completed_authentications'],1);self.assertEqual(result['radius_requests'],4)
        self.assertTrue(result['port_closed']);self.assertEqual(transitions,[False,True,False,False])

    def test_reauthentication_cannot_switch_to_another_allowed_identity(self):
        result,transitions,_=self.simulated_cycles(1,changed_identity=True)
        self.assertEqual(result['status'],'blocked');self.assertEqual(result['reason'],'IDENTITY_CHANGED')
        self.assertEqual(result['radius_requests'],2);self.assertEqual(transitions,[False,True,False,False])

    def test_default_closed_gate_covers_both_directions_before_forwarding(self):
        node=self.spec()['nodes'][1];text=render(node,'02:00:00:00:01:10')
        self.assertIn('hook prerouting priority -340',text);self.assertIn('hook postrouting priority -340',text)
        self.assertIn('flags timeout; timeout 5s; size 1;',text)
        self.assertNotIn('elements =',text);self.assertIn('ether saddr != 02:00:00:00:01:10 counter drop',text)
        self.assertIn('iifname "eth0" counter drop',text);self.assertIn('oifname "eth0" counter drop',text)

    def test_dynamic_lease_preserves_static_fingerprint_but_rejects_foreign_or_unbounded_entries(self):
        value={'nftables':[{'set':{'family':'bridge','table':TABLE,'name':'admitted','type':'ifname','flags':['timeout'],'timeout':5,'size':1}}]}
        pin,active=gate_snapshot(value,'eth0',5);self.assertFalse(active)
        value['nftables'][0]['set']['elem']=[{'elem':{'val':'eth0','timeout':5,'expires':4}}]
        self.assertEqual(gate_snapshot(value,'eth0',5),(pin,True))
        for fault in ({'val':'eth1'},{'expires':6},{'expires':True},{'timeout':30},{'timeout':0},{'timeout':True},{'timeout':'5'}):
            bad=copy.deepcopy(value);bad['nftables'][0]['set']['elem'][0]['elem'].update(fault)
            with self.assertRaises(ValueError):gate_snapshot(bad,'eth0',5)
        inherited=copy.deepcopy(value);del inherited['nftables'][0]['set']['elem'][0]['elem']['timeout']
        self.assertEqual(gate_snapshot(inherited,'eth0',5),(pin,True))
        with self.assertRaises(ValueError):gate_snapshot(inherited,'eth0',3)
        value['nftables'].append({'rule':{'family':'bridge','table':TABLE,'expr':[{'accept':None}]}})
        self.assertNotEqual(gate_snapshot(value,'eth0',5)[0],pin)

    def test_eapol_requires_pinned_source_destination_version_and_lengths(self):
        peer=bytes.fromhex('020000000110');own=bytes.fromhex('020000000101')
        eap=struct.pack('!BBH',2,7,12)+b'\x01learner'
        frame=own+peer+b'\x88\x8e'+struct.pack('!BBH',2,0,len(eap))+eap
        self.assertEqual(envelope(frame,peer,own),(0,eap))
        self.assertEqual(envelope(frame+bytes(20),peer,own),(0,eap))
        for bad in (frame[:16],bytes(6)+frame[6:],frame[:6]+own+frame[12:],frame[:12]+b'\x81\x00'+frame[14:],frame[:14]+b'\x03'+frame[15:],frame[:16]+b'\xff\xff'+frame[18:]):
            self.assertIsNone(envelope(bad,peer,own))
        self.assertEqual(envelope(own+peer+b'\x88\x8e\x02\x02\x00\x00',peer,own),(2,b''))

    def test_nas_edits_refuse_before_kernel_mutation_and_unowned_worker_is_never_killed(self):
        node=self.spec()['nodes'][1];changed=copy.deepcopy(node);changed['dot1x']['seconds']=3
        manager=Mock()
        with self.assertRaises(RuntimeFailure):configure(manager,1,changed,node)
        manager.ns.assert_not_called()
        manager.state={'dot1x_workers':{'SW1':{'pid':99,'starttime':'123'}}}
        with patch('network_labs.appliances.snooping.alive',return_value=True),patch('os.getpgid',return_value=98),patch('os.killpg') as kill:
            with self.assertRaises(RuntimeFailure):stop(manager)
            kill.assert_not_called()

    def test_stop_confirms_death_after_sigkill_in_another_cli(self):
        manager=Mock();manager.state={'dot1x_workers':{'SW1':{'pid':99,'starttime':'123'}}}
        with patch('network_labs.appliances.snooping.alive',side_effect=[True,True,True,True,False,False]),patch('os.getpgid',return_value=99),patch('os.killpg') as kill,patch('time.monotonic',side_effect=[0,4,4,4]),patch('time.sleep'):
            stop(manager)
        self.assertEqual([c.args[1] for c in kill.call_args_list],[15,9])
        self.assertFalse(manager.state['dot1x_workers'])

    def test_stop_retains_record_when_sigkill_death_is_unconfirmed(self):
        manager=Mock();manager.state={'dot1x_workers':{'SW1':{'pid':99,'starttime':'123'}}}
        with patch('network_labs.appliances.snooping.alive',return_value=True),patch('os.getpgid',return_value=99),patch('os.killpg'),patch('time.monotonic',side_effect=[0,4,4,7]),patch('time.sleep'):
            with self.assertRaises(RuntimeFailure):stop(manager)
        self.assertIn('SW1',manager.state['dot1x_workers']);manager.save.assert_not_called()
