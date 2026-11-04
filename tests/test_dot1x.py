"""Controlled-port scope, bounded kernel admissions and EAPOL parsing boundaries."""
import copy
import json
import struct
import unittest
from unittest.mock import Mock, patch
from network_labs.appliances.examples import dot1x_lab
from network_labs.appliances.dot1x import TABLE, gate_snapshot, render, stop
from network_labs.appliances.dot1x_worker import envelope
from network_labs.appliances.firewall import fingerprint
from network_labs.appliances.lan import configure
from network_labs.appliances.spec import validate
from network_labs.appliances.runtime import RuntimeFailure


class Dot1xTests(unittest.TestCase):
    def spec(self):return dot1x_lab('/rootfs','private-dot1x-secret','a'*64,'/private/password')

    def test_bounded_explicit_topology_and_canonical_policy(self):
        spec=self.spec();self.assertEqual(spec,validate(spec))
        node=spec['nodes'][1];self.assertEqual(node['svis']['vlan1']['address'],'192.0.2.1/24')
        self.assertEqual(spec['nodes'][2]['radius_server']['clients'][0]['address'],'192.0.2.1')
        for fault in ({'seconds':0},{'seconds':31},{'seconds':True},{'port':'eth9'},{'port':[]},{'users':[]},{'users':['learner','learner']},{'peer':'PC2'},{'server':'127.0.0.1'},{'svi':'vlan9'}):
            with self.subTest(fault=fault),self.assertRaises((ValueError,TypeError)):
                bad=copy.deepcopy(spec);bad['nodes'][1]['dot1x'].update(fault);validate(bad)
        bad=copy.deepcopy(spec);bad['nodes'][0]['interface_macs']={}
        with self.assertRaises(ValueError):validate(bad)

    def test_default_closed_gate_covers_both_directions_before_forwarding(self):
        node=self.spec()['nodes'][1];text=render(node,'02:00:00:00:01:10')
        self.assertIn('hook prerouting priority -340',text);self.assertIn('hook postrouting priority -340',text)
        self.assertIn('flags timeout; timeout 5s; size 1;',text)
        self.assertNotIn('elements =',text);self.assertIn('ether saddr != 02:00:00:00:01:10 counter drop',text)
        self.assertIn('iifname "eth0" counter drop',text);self.assertIn('oifname "eth0" counter drop',text)

    def test_dynamic_lease_preserves_static_fingerprint_but_rejects_foreign_or_unbounded_entries(self):
        value={'nftables':[{'set':{'family':'bridge','table':TABLE,'name':'admitted','type':'ifname','flags':['timeout'],'timeout':5000,'size':1}}]}
        pin,active=gate_snapshot(value,'eth0',5);self.assertFalse(active)
        value['nftables'][0]['set']['elem']=[{'elem':{'val':'eth0','timeout':5000,'expires':4500}}]
        self.assertEqual(gate_snapshot(value,'eth0',5),(pin,True))
        for fault in ({'val':'eth1'},{'expires':5001},{'timeout':30000}):
            bad=copy.deepcopy(value);bad['nftables'][0]['set']['elem'][0]['elem'].update(fault)
            with self.assertRaises(ValueError):gate_snapshot(bad,'eth0',5)
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
