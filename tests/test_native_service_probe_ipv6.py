"""Real IPv6 wire exchanges plus explicit family, record and resolver boundaries."""
from contextlib import contextmanager,redirect_stdout,redirect_stderr
import io
import json
import select
import socket
import struct
import threading
import time
import unittest
from unittest.mock import patch
from network_labs.appliances.service_probe_worker import run_probe
from network_labs.appliances.service_probe import probe
from network_labs.appliances.dns import resolver_config
from network_labs.appliances.examples import dual_stack_dns_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main
from network_labs.appliances.service_findings import findings
from test_native_service_probe import manager_with_probes


@contextmanager
def dns6(mode='answer'):
    tcp=socket.socket(socket.AF_INET6,socket.SOCK_STREAM);tcp.bind(('::1',0));tcp.listen(3)
    port=tcp.getsockname()[1];udp=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM);udp.bind(('::1',port))
    stop=threading.Event();seen=[];errors=[]
    def response(query,tc=False):
        question=query[12:]
        if mode=='wrong-question':question=question[:-4]+b'\x00\x01\x00\x01'
        data=socket.inet_pton(socket.AF_INET6,'2001:db8::66' if tc else '2001:db8::10')
        if mode=='short-data':data=data[:-1]
        return query[:2]+struct.pack('!5H',0x8380 if tc else 0x8180,1,1,0,0)+question+b'\xc0\x0c'+struct.pack('!HHIH',28,1,60,len(data))+data
    def exact(c,n):
        value=b''
        while len(value)<n:
            part=c.recv(n-len(value))
            if not part:raise ValueError('short query')
            value+=part
        return value
    def serve():
        try:
            while not stop.is_set():
                for s in select.select([tcp,udp],[],[],.05)[0]:
                    if s is udp:
                        query,peer=udp.recvfrom(4096);seen.append(('udp',query));udp.sendto(response(query,True),peer)
                    else:
                        c,_=tcp.accept()
                        with c:
                            c.settimeout(2);query=exact(c,struct.unpack('!H',exact(c,2))[0]);seen.append(('tcp',query));p=response(query)
                            data=struct.pack('!H',len(p))+p
                            for i in range(0,len(data),3):c.sendall(data[i:i+3]);time.sleep(.001)
        except Exception as e:errors.append(e)
    thread=threading.Thread(target=serve);thread.start()
    try:
        with patch('network_labs.appliances.service_probe_worker.DNS_PORT',port):yield seen
    finally:
        stop.set();thread.join(3);tcp.close();udp.close()
        if thread.is_alive() or errors:raise AssertionError(errors)


class IPv6ProbeTests(unittest.TestCase):
    def test_real_ipv6_aaaa_segmented_tcp_and_matched_tc_only_retry(self):
        for transport in ('tcp','auto'):
            with dns6() as seen:
                result=run_probe({'stage':'dns','source':'::1','server':'::1','target':'web.lab.test','qtype':28,'transport':transport,'timeout':2})
                self.assertEqual(result['status'],'passed',result);self.assertEqual(result['record_type'],'AAAA')
                self.assertEqual(result['addresses'],['2001:db8::10']);self.assertEqual(result['fallback'],transport=='auto')
                self.assertEqual([m for m,q in seen],['udp','tcp'] if transport=='auto' else ['tcp'])
                if transport=='auto':self.assertEqual(seen[0][1],seen[1][1])
        for mode in ('wrong-question','short-data'):
            with dns6(mode) as seen:
                result=run_probe({'stage':'dns','source':'::1','server':'::1','target':'web.lab.test','qtype':28,'transport':'auto','timeout':2})
                self.assertEqual(result['status'],'unknown',result);self.assertNotIn('addresses',result)
                self.assertEqual(result['fallback'],mode!='wrong-question')

    def test_real_http_ipv6_literal_has_bracketed_host_header(self):
        errors=[];headers=[]
        with socket.socket(socket.AF_INET6,socket.SOCK_STREAM) as server:
            server.bind(('::1',0));server.listen(1);server.settimeout(2)
            def serve():
                try:
                    c,_=server.accept()
                    with c:
                        c.settimeout(2);data=b''
                        while not data.endswith(b'\r\n\r\n'):data+=c.recv(1024)
                        headers.append(data);c.sendall(b'HTTP/1.0 200 OK\r\n\r\n')
                except Exception as e:errors.append(e)
            thread=threading.Thread(target=serve);thread.start();port=server.getsockname()[1]
            result=run_probe({'stage':'http','source':'::1','address':'::1','target':'::1','port':port,'path':'/','timeout':2})
            thread.join(3);self.assertFalse(thread.is_alive());self.assertFalse(errors)
        self.assertEqual(result['status'],'passed',result);self.assertIn(('Host: [::1]:'+str(port)+'\r\n').encode(),headers[0])

    def test_ipv6_target_aaaa_query_can_use_observed_ipv4_guest_resolver(self):
        manager=manager_with_probes();original=manager.ns.side_effect
        def replies(index,*args,**kwargs):
            result=original(index,*args,**kwargs)
            if args[1:3]==('-I','-c'):
                request=json.loads(args[-1])
                if request['stage']=='dns':result.stdout=json.dumps({'stage':'dns','status':'passed','record_type':'AAAA','addresses':['2001:db8::10']})
            return result
        manager.ns.side_effect=replies
        with patch('network_labs.appliances.service_probe._endpoint',side_effect=lambda m,i,n,**k:{'status':'ready','address':'2001:db8::20' if k.get('family')=='ipv6' else '192.0.2.10'}):
            result=probe(manager,'PC1','web.lab.test',family='ipv6',protocol='dns')
        self.assertEqual(result['status'],'passed',result);self.assertEqual(result['stages'][0]['request']['qtype'],28)
        self.assertEqual(result['stages'][0]['request']['source'],'192.0.2.10');manager.save.assert_not_called()
        self.assertEqual(result['findings'][0]['code'],'DNS_AAAA_RECEIVED')

    def test_bad_family_wrong_literals_and_local_scoped_or_mapped_targets_reject_before_io(self):
        for target,family in (('2001:db8::1','ipv4'),('192.0.2.1','ipv6'),('::1','ipv6'),('fe80::1','ipv6'),
                              ('2001:db8::1%eth0','ipv6'),('::ffff:192.0.2.1','ipv6'),('::','ipv6'),('ff02::1','ipv6'),('web.lab.test','auto')):
            manager=manager_with_probes()
            with self.subTest(target=target,family=family),self.assertRaises(ValueError):probe(manager,'PC1',target,family=family)
            manager.ns.assert_not_called()

    def test_missing_resolver_family_source_never_uses_host_or_other_family(self):
        manager=manager_with_probes()
        with patch('network_labs.appliances.service_probe._endpoint',side_effect=lambda m,i,n,**k:{'status':'ready','address':'2001:db8::20'} if k.get('family')=='ipv6' else {'status':'blocked','address':None}):
            result=probe(manager,'PC1','web.lab.test',family='ipv6',protocol='dns')
        self.assertEqual(result['status'],'unknown');manager.ns.assert_not_called()

    def test_cli_resolver_choice_and_ipv6_findings_are_explicit(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['example','--rootfs','/rootfs','--dual-stack-dns','--dns-resolver-family','ipv6']),0)
        self.assertEqual(json.loads(out.getvalue())['nodes'][0]['resolvers'],['2001:db8:20::20'])
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            self.assertEqual(main(['example','--rootfs','/rootfs','--dns-resolver-family','ipv6']),1)
        rows=findings({'address_family':'ipv6','endpoint':{'status':'blocked'},'stages':[]})
        self.assertIn('IPv6',rows[0]['message'])

    def test_ipv6_resolver_policy_is_canonical_and_default_stays_ipv4(self):
        spec=dual_stack_dns_lab('/rootfs',resolver_family='ipv6');self.assertEqual(validate(spec),spec)
        self.assertEqual(resolver_config(spec['nodes'][0]),'nameserver 2001:db8:20::20\n')
        self.assertEqual(dual_stack_dns_lab('/rootfs')['nodes'][0]['resolvers'],['198.51.100.20'])
        for address in ('fe80::1','::1','::','ff02::1','::ffff:192.0.2.1','2001:db8::1%eth0'):
            spec=dual_stack_dns_lab('/rootfs');spec['nodes'][0]['resolvers']=[address]
            with self.subTest(address=address),self.assertRaises(ValueError):validate(spec)
