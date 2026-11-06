"""Independent signed UDP peer checks EAP state, MD5 proof and fail-closed limits."""
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from network_labs.appliances.radius_eap_worker import authenticate, inner
from network_labs.appliances.radius import probe, render
from network_labs.appliances.radius_server import config_text, eap_password
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main
from test_native_radius import response, SECRET, PASSWORD


def attrs(packet):
    result = {}; offset = 20
    while offset < len(packet):
        kind, size = packet[offset:offset+2]; result.setdefault(kind, []).append(packet[offset+2:offset+size]); offset += size
    return result


def attr(kind, data): return bytes([kind, len(data)+2]) + data


def eap(code, identifier, data=b''): return struct.pack('!BBH', code, identifier, 4+len(data)) + data


class EAPMD5Tests(unittest.TestCase):
    def test_eap_termination_action_requires_duration_and_only_declared_default_or_request(self):
        spec=radius_lab('/rootfs',SECRET,'a'*64,eap_password_file='/private/password')
        user=spec['nodes'][2]['radius_server']['users']['learner'];user['session_timeout']=3
        for value in (0,1):
            user['termination_action']=value;normalized=validate(spec)
            with patch('network_labs.appliances.radius_server.eap_literal',return_value="'private'"):
                text=config_text(normalized['nodes'][2])
                self.assertIn('Session-Timeout := 3',text);self.assertIn('Termination-Action := '+str(value),text)
        for value in (-1,2,True,'1',None):
            user['termination_action']=value
            with self.subTest(value=value),self.assertRaises(ValueError):validate(spec)
        user['termination_action']=1;del user['session_timeout']
        with self.assertRaises(ValueError):validate(spec)
        pap=radius_lab('/rootfs',SECRET,'a'*64);pap['nodes'][2]['radius_server']['users']['learner']['termination_action']=1
        with self.assertRaises(ValueError):validate(pap)

    def test_eap_only_session_timeout_is_validated_and_rendered_as_integer_reply(self):
        spec=radius_lab('/rootfs',SECRET,'a'*64,eap_password_file='/private/password')
        for value in (1,3,4294967295):
            spec['nodes'][2]['radius_server']['users']['learner']['session_timeout']=value
            normalized=validate(spec)
            with patch('network_labs.appliances.radius_server.eap_literal',return_value="'private'"):
                self.assertIn('Session-Timeout := '+str(value),config_text(normalized['nodes'][2]))
        for value in (0,-1,4294967296,True,'3',None):
            spec['nodes'][2]['radius_server']['users']['learner']['session_timeout']=value
            with self.subTest(value=value),self.assertRaises(ValueError):validate(spec)
        pap=radius_lab('/rootfs',SECRET,'a'*64)
        pap['nodes'][2]['radius_server']['users']['learner']['session_timeout']=3
        with self.assertRaises(ValueError):validate(pap)

    def exchange(self, fault=None, reject=False):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1',0)); server.settimeout(2); errors=[]; seen=[]
            def serve():
                try:
                    first, peer = server.recvfrom(4097); seen.append(first); values=attrs(first)
                    self.assertNotIn(2, values); self.assertNotIn(24, values)
                    ident = values[79][0]; self.assertEqual(ident[0],2); self.assertEqual(ident[4:],b'\x01learner')
                    if fault == 'early-accept':
                        server.sendto(response(first,2,attributes=attr(79,eap(3,ident[1]))),peer); return
                    challenge = bytes(range(16)); state=b'opaque\x00state\xff'; eid=37
                    msg=eap(1,eid,b'\x04\x10'+challenge)
                    if fault == 'other-method': msg=eap(1,eid,b'\x0d\x00')
                    if fault == 'bad-length': msg=msg[:2]+b'\x00\x04'+msg[4:]
                    payload=attr(79,msg)+attr(24,state)
                    if fault == 'missing-state': payload=attr(79,msg)
                    if fault == 'duplicate-state': payload+=attr(24,state)
                    if fault == 'bad-first-mac':
                        server.sendto(response(first,11,attributes=payload,bad_mac=True),peer)
                    server.sendto(response(first,11,attributes=payload),peer)
                    if fault in ('other-method','bad-length','missing-state','duplicate-state'): return
                    second, peer2=server.recvfrom(4097); seen.append(second); self.assertEqual(peer2,peer)
                    values=attrs(second); self.assertEqual(values[24],[state]); self.assertNotIn(2,values)
                    self.assertNotEqual(first[1],second[1]); self.assertNotEqual(first[4:20],second[4:20])
                    expected=hashlib.md5(bytes([eid])+PASSWORD.encode()+challenge).digest()
                    self.assertEqual(values[79][0],eap(2,eid,b'\x04\x10'+expected+b'learner'))
                    if fault == 'late-first': server.sendto(response(first,11,attributes=payload),peer)
                    if fault == 'second-challenge': final=response(second,11,attributes=payload)
                    else:
                        final_id = eid+1 if fault=='wrong-final-id' else eid
                        final=response(second,3 if reject else 2,attributes=attr(79,eap(4 if reject else 3,final_id)))
                    server.sendto(final,peer)
                except BaseException as error: errors.append(error)
            thread=threading.Thread(target=serve); thread.start()
            result=authenticate(dict(source='127.0.0.1',address='127.0.0.1',port=server.getsockname()[1],username='learner',password=PASSWORD,secret=SECRET,timeout=1))
            thread.join(3); self.assertFalse(thread.is_alive())
            if errors: raise errors[0]
            self.assertNotIn(PASSWORD,str(result)); self.assertNotIn(SECRET,str(result))
            return result, seen

    def test_valid_two_step_proof_opaque_state_and_verified_reject(self):
        for reject in (False,True):
            result,seen=self.exchange(reject=reject)
            self.assertEqual(result['status'],'failed' if reject else 'passed'); self.assertTrue(result['response_verified'])
            self.assertTrue(result['challenge_verified']); self.assertEqual(result['requests_sent'],2)
            self.assertEqual(len(seen),2)

    def test_malformed_or_wrong_method_never_falls_back_or_reports_accept(self):
        for fault in ('early-accept','other-method','bad-length','missing-state','duplicate-state','second-challenge','wrong-final-id'):
            with self.subTest(fault=fault):
                result,seen=self.exchange(fault)
                self.assertEqual(result['status'],'unknown'); self.assertEqual(result['error'],'PROTOCOL_ERROR')
                self.assertFalse(result['response_verified']); self.assertLessEqual(len(seen),2)

    def test_unverified_challenge_and_replayed_previous_round_are_discarded(self):
        for fault in ('bad-first-mac','late-first'):
            result,_=self.exchange(fault); self.assertEqual(result['status'],'passed'); self.assertEqual(result['discarded_responses'],1)

    def test_silence_keeps_one_deadline_and_does_not_retransmit(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1',0))
            result=authenticate(dict(source='127.0.0.1',address='127.0.0.1',port=server.getsockname()[1],username='learner',password=PASSWORD,secret=SECRET,timeout=.03))
            self.assertEqual(result['error'],'TIMEOUT'); self.assertEqual(result['requests_sent'],1)

    def test_fragment_reassembly_requires_consecutive_eap_attributes(self):
        msg=eap(1,2,b'\x04\x10'+bytes(16)); base=bytes(20)
        self.assertEqual(inner(base+attr(79,msg[:7])+attr(79,msg[7:])+attr(24,b'state')),(msg,b'state'))
        with self.assertRaises(ValueError): inner(base+attr(79,msg[:7])+attr(24,b'state')+attr(79,msg[7:]))

    def test_private_password_asset_pin_and_eap_only_opt_in(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'password'; path.write_text(PASSWORD); path.chmod(0o600)
            spec=radius_lab('/rootfs',SECRET,hashlib.sha256(PASSWORD.encode()).hexdigest(),eap_password_file=path)
            user=spec['nodes'][2]['radius_server']['users']['learner']; config=config_text(spec['nodes'][2])
            self.assertIn('default_eap_type = md5',config); self.assertIn("Cleartext-Password := '"+PASSWORD+"'",config)
            self.assertNotIn(PASSWORD,json.dumps(spec))
            self.assertEqual(spec,validate(spec))
            for fault in ('mode','content','hardlink'):
                path.write_text(PASSWORD); path.chmod(0o600)
                if fault=='mode': path.chmod(0o644)
                elif fault=='content': path.write_text('changed-password')
                else: os.link(path,Path(d)/'copy')
                with self.assertRaises(ValueError): eap_password(user)
            base=radius_lab('/rootfs',SECRET,'a'*64)
            self.assertNotIn('default_eap_type',config_text(base['nodes'][2]))
            base['nodes'][2]['radius_server']['users']['learner']['password_file']=str(path)
            with self.assertRaises(ValueError): validate(base)

    def test_cli_example_keeps_the_password_out_of_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name,value in (('password',PASSWORD),('secret',SECRET)):
                p=root/name;p.write_text(value);p.chmod(0o600)
            args=['example','--rootfs','/rootfs','--radius','--radius-eap-md5','--radius-user','learner','--radius-password-file',str(root/'password'),'--radius-secret-file',str(root/'secret')]
            with redirect_stdout(io.StringIO()) as output:self.assertEqual(main(args),0)
            spec=json.loads(output.getvalue());self.assertTrue(spec['nodes'][2]['radius_server']['eap_md5'])
            self.assertEqual(spec['nodes'][2]['radius_server']['users']['learner']['password_file'],str(root/'password'))
            self.assertNotIn(PASSWORD,output.getvalue())
