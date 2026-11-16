"""Real socket framing, validated truncation retry and shared deadline boundaries."""
from contextlib import contextmanager
import socket
import struct
import threading
import time
import unittest
from unittest.mock import patch
from dns_transport_fixture import response
from network_labs.appliances.service_probe_worker import run_probe,dns_answers
from network_labs.appliances.service_probe import probe
from test_native_service_probe import manager_with_probes


@contextmanager
def responder(mode='answer',udp_delay=0,tcp_stall=False):
    tcp=socket.socket();tcp.bind(('127.0.0.1',0));tcp.listen(2);tcp.settimeout(.1)
    port=tcp.getsockname()[1];udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind(('127.0.0.1',port));udp.settimeout(.1)
    stop=threading.Event();seen=[];errors=[]
    def exact(c,n):
        data=b''
        while len(data)<n:
            p=c.recv(n-len(data))
            if not p:raise ValueError('short query')
            data+=p
        return data
    def serve_udp():
        while not stop.is_set():
            try:q,peer=udp.recvfrom(4096)
            except socket.timeout:continue
            seen.append(('udp',q));stop.wait(udp_delay)
            if not stop.is_set():udp.sendto(response(q,mode,truncated=True),peer)
    def serve_tcp():
        while not stop.is_set():
            try:c,_=tcp.accept()
            except socket.timeout:continue
            with c:
                c.settimeout(2);q=exact(c,struct.unpack('!H',exact(c,2))[0]);seen.append(('tcp',q))
                if tcp_stall:stop.wait(2);continue
                packet=response(q,mode);size=len(packet)
                if mode=='large':c.sendall(struct.pack('!H',5000));continue
                if mode=='short':c.sendall(struct.pack('!H',size)+packet[:-1]);continue
                if mode=='tcp-tc':packet=response(q,truncated=True)
                data=struct.pack('!H',len(packet))+packet
                for i in range(0,len(data),3):c.sendall(data[i:i+3]);time.sleep(.001)
    def guarded(fn):
        try:fn()
        except (OSError,ValueError) as e:
            if not stop.is_set():errors.append(e)
    threads=[threading.Thread(target=guarded,args=(fn,)) for fn in (serve_udp,serve_tcp)]
    for thread in threads:thread.start()
    try:
        with patch('network_labs.appliances.service_probe_worker.DNS_PORT',port):yield seen
    finally:
        stop.set()
        for thread in threads:thread.join(3)
        tcp.close();udp.close()
        if errors:raise errors[0]


def request(transport='tcp',timeout=2):
    return run_probe({'stage':'dns','source':'127.0.0.1','server':'127.0.0.1','target':'web.lab.test','timeout':timeout,'transport':transport})


class DNSTransportTests(unittest.TestCase):
    def test_segmented_tcp_and_validated_auto_retry_discard_partial_answers(self):
        with responder() as seen:
            actual=request();self.assertEqual(actual['status'],'passed',actual);self.assertEqual(actual['transport'],'tcp')
            self.assertEqual([m for m,_ in seen],['tcp'])
        with responder() as seen:
            actual=request('auto');self.assertEqual(actual['status'],'passed',actual);self.assertTrue(actual['fallback'])
            self.assertEqual(actual['addresses'],['203.0.113.10']);self.assertEqual([m for m,_ in seen],['udp','tcp'])
            self.assertEqual(seen[0][1],seen[1][1]);self.assertTrue(actual['attempts'][0]['truncated'])

    def test_invalid_udp_truncation_cannot_trigger_tcp_and_udp_default_stays_strict(self):
        for mode in ('answer','bad-id','bad-question'):
            with self.subTest(mode=mode),responder(mode) as seen:
                actual=request('udp' if mode=='answer' else 'auto')
                self.assertEqual(actual['status'],'unknown',actual);self.assertFalse(actual['fallback']);self.assertEqual([m for m,_ in seen],['udp'])
                self.assertNotIn('addresses',actual)

    def test_invalid_tcp_frames_or_replies_never_pass(self):
        for mode in ('large','short','bad-id','bad-question','tcp-tc'):
            with self.subTest(mode=mode),responder(mode):
                actual=request();self.assertEqual(actual['status'],'unknown',actual);self.assertNotIn('addresses',actual)

    def test_auto_deadline_is_shared_with_tcp_and_stall_is_not_success(self):
        with responder(udp_delay=.65,tcp_stall=True):
            start=time.monotonic();actual=request('auto',timeout=1);elapsed=time.monotonic()-start
            self.assertEqual(actual['status'],'failed',actual);self.assertTrue(actual['fallback']);self.assertLess(elapsed,1.5)
            self.assertNotIn('addresses',actual)

    def test_udp_timeout_never_tries_tcp_or_another_resolver(self):
        with responder(udp_delay=2) as seen:
            actual=request('auto',timeout=1)
            self.assertEqual(actual['status'],'failed',actual);self.assertFalse(actual['fallback'])
            self.assertEqual([mode for mode,_ in seen],['udp']);self.assertNotIn('addresses',actual)

    def test_all_declared_sections_and_trailing_data_are_checked(self):
        query=struct.pack('!6H',42,0x100,1,0,0,0)+b'\x03web\x03lab\x04test\x00\x00\x01\x00\x01'
        packet=response(query)
        for malformed in (packet+b'junk',packet[:8]+struct.pack('!H',1)+packet[10:]):
            with self.assertRaises(ValueError):dns_answers(malformed,42,'web.lab.test')

    def test_parent_propagates_transport_and_rejects_ineffective_ip_selection(self):
        manager=manager_with_probes();actual=probe(manager,'PC1','web.lab.test',protocol='dns',dns_transport='tcp')
        self.assertEqual(actual['stages'][0]['request']['transport'],'tcp');manager.save.assert_not_called()
        for value in ('tls',True,None):
            with self.assertRaises(ValueError):probe(manager_with_probes(),'PC1','web.lab.test',protocol='dns',dns_transport=value)
        with self.assertRaises(ValueError):probe(manager_with_probes(),'PC1','203.0.113.10',protocol='http',dns_transport='auto')
