"""Real UDP packet loss, bounded backoff and RFC accounting retry identity rules."""
import hashlib
import io
import json
import socket
import struct
import threading
import time
import unittest
import tempfile
from pathlib import Path
from contextlib import redirect_stdout,redirect_stderr
from network_labs.appliances.__main__ import main
from unittest.mock import Mock,patch
from network_labs.appliances.radius_accounting_worker import account,accounting_request
from network_labs.appliances.radius_accounting import send
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.spec import validate
from test_native_radius_accounting import request,reply,SECRET


def attrs(packet):
    result={};i=20
    while i<len(packet):
        kind,size=packet[i:i+2];result[kind]=packet[i+2:i+size];i+=size
    return result


class AccountingRetryTests(unittest.TestCase):
    def test_lost_responses_retry_identical_packet_before_delay_changes(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1',0));server.settimeout(2);seen=[];errors=[]
            def serve():
                try:
                    for _ in range(3):packet,peer=server.recvfrom(4096);seen.append(packet)
                    server.sendto(reply(packet),peer)
                except Exception as e:errors.append(e)
            thread=threading.Thread(target=serve);thread.start();started=time.monotonic()
            actual=account(request(port=server.getsockname()[1],timeout=.35,retries=2));elapsed=time.monotonic()-started;thread.join(3)
            self.assertFalse(thread.is_alive());self.assertFalse(errors);self.assertEqual(actual['status'],'passed',actual)
            self.assertEqual(actual['requests_sent'],3);self.assertEqual(seen,[seen[0]]*3);self.assertLess(elapsed,.8)

    def test_changed_delay_updates_identifier_authenticator_and_accepts_late_valid_ack(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1',0));server.settimeout(3);seen=[];errors=[]
            def serve():
                try:
                    for _ in range(2):packet,peer=server.recvfrom(4096);seen.append(packet)
                    server.sendto(reply(seen[0]),peer)
                except Exception as e:errors.append(e)
            thread=threading.Thread(target=serve);thread.start()
            actual=account(request(port=server.getsockname()[1],timeout=3.3,retries=1));thread.join(4)
            self.assertFalse(thread.is_alive());self.assertFalse(errors);self.assertEqual(actual['status'],'passed',actual)
            first,second=seen;self.assertNotEqual(first[1],second[1]);self.assertNotEqual(first[4:20],second[4:20])
            self.assertGreaterEqual(struct.unpack('!I',attrs(second)[41])[0],1)
            self.assertEqual(attrs(first)[44],attrs(second)[44]);self.assertEqual(attrs(first)[40],attrs(second)[40])
            self.assertEqual(second[4:20],hashlib.md5(second[:4]+bytes(16)+second[20:]+SECRET.encode()).digest())

    def test_silent_peer_never_exceeds_count_or_absolute_deadline(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1',0));server.settimeout(.02);start=time.monotonic()
            actual=account(request(port=server.getsockname()[1],timeout=.2,retries=2));self.assertLess(time.monotonic()-start,.7)
            self.assertEqual(actual['status'],'unknown');self.assertEqual(actual['requests_sent'],3);self.assertEqual(actual['error'],'TIMEOUT')
            seen=[]
            try:
                while True:seen.append(server.recvfrom(4096)[0])
            except socket.timeout:pass
            self.assertEqual(len(seen),3)

    def test_packet_flood_does_not_reset_budget_with_retries_enabled(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1',0));server.settimeout(2)
            def serve():
                packet,peer=server.recvfrom(4096)
                for _ in range(64):server.sendto(reply(packet,secret='incorrect-secret'),peer)
            thread=threading.Thread(target=serve);thread.start()
            actual=account(request(port=server.getsockname()[1],timeout=1,retries=2));thread.join(3)
            self.assertEqual(actual['error'],'PACKET_LIMIT');self.assertEqual(actual['discarded_responses'],64);self.assertFalse(actual['response_verified'])

    def test_policy_requires_explicit_accounting_and_bounded_integer(self):
        for value in (-1,3,True,'1'):
            with self.subTest(value=value),self.assertRaises(ValueError):radius_lab('/rootfs',SECRET,'a'*64,allow_shell=True,accounting=True,accounting_retries=value)
        with self.assertRaises(ValueError):radius_lab('/rootfs',SECRET,'a'*64,accounting_retries=1)
        spec=radius_lab('/rootfs',SECRET,'a'*64,allow_shell=True,accounting=True,accounting_retries=2)
        self.assertEqual(validate(spec),spec);self.assertEqual(spec['nodes'][0]['radius_access']['accounting_retries'],2)
        self.assertNotIn('accounting_retries',radius_lab('/rootfs',SECRET,'a'*64,allow_shell=True,accounting=True)['nodes'][0]['radius_access'])

    def test_cli_retry_selection_requires_accounting_and_survives_manifest_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,value in (('secret',SECRET),('password','accounting-test-password')):
                path=root/name;path.write_text(value);path.chmod(0o600)
            args=['example','--rootfs','/rootfs','--radius','--radius-shell','--radius-accounting','--radius-accounting-retries','2',
                  '--radius-user','learner','--radius-password-file',str(root/'password'),'--radius-secret-file',str(root/'secret')]
            with redirect_stdout(io.StringIO()) as out:self.assertEqual(main(args),0)
            self.assertEqual(json.loads(out.getvalue())['nodes'][0]['radius_access']['accounting_retries'],2)
            self.assertNotIn('accounting-test-password',out.getvalue())
        with redirect_stderr(io.StringIO()),redirect_stdout(io.StringIO()):
            self.assertEqual(main(['example','--rootfs','/rootfs','--radius-accounting-retries','1']),1)

    def test_wrapper_accepts_only_verified_results_within_declared_send_limit(self):
        manager=Mock();manager.read.return_value={'phase':'running','spec':radius_lab('/rootfs',SECRET,'a'*64,allow_shell=True,accounting=True,accounting_retries=2)}
        value={'status':'passed','response_verified':True,'requests_sent':3,'discarded_responses':0,'response_code':5,'error':None}
        manager.ns.return_value=Mock(returncode=0,stdout=json.dumps(value))
        with patch('network_labs.appliances.radius_accounting._endpoint',return_value={'status':'ready','address':'192.0.2.10'}),patch('network_labs.appliances.radius_accounting._json_read',return_value={'records':[]}):
            actual=send(manager,'PC1','192.0.2.20',username='learner',secret=SECRET,session_id='test',event='start')
            self.assertEqual(actual['status'],'passed');self.assertEqual(actual['retries_allowed'],2)
            self.assertEqual(json.loads(manager.ns.call_args.kwargs['input_text'])['retries'],2)
            self.assertNotIn(SECRET,str(manager.ns.call_args.args))
            value['requests_sent']=4;manager.ns.return_value.stdout=json.dumps(value)
            actual=send(manager,'PC1','192.0.2.20',username='learner',secret=SECRET,session_id='test',event='start')
            self.assertEqual(actual['error'],'WORKER_UNAVAILABLE')
