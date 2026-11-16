"""Wire-level option negotiation, including ignored options and malformed OACK."""
import hashlib
import socket
import struct
import threading
import unittest
from unittest.mock import patch
from network_labs.appliances.tftp_worker import read
from network_labs.appliances.tftp import read as managed_read
from test_native_verify import manager_for


def transfer(data, oack=b'blksize\x001024\x00', size=1024, requested=1428, repeat=False, lost_ack=False, late_oack=False, changed_duplicate=False):
    errors=[]; seen=[]
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server:
        server.bind(('127.0.0.1',0));server.settimeout(2)
        def serve():
            try:
                rrq,peer=server.recvfrom(1024);seen.append(rrq)
                if oack is not None:
                    for _ in range(2 if repeat else 1):
                        server.sendto(b'\x00\x06'+oack,peer);ack,_=server.recvfrom(1024);seen.append(ack)
                        if ack[:2]==b'\x00\x05':return
                    if lost_ack:
                        repeated,_=server.recvfrom(1024);seen.append(repeated)
                        if repeated != b'\x00\x04\x00\x00':raise AssertionError(repeated)
                block=1
                while True:
                    chunk=data[(block-1)*size:block*size]
                    server.sendto(struct.pack('!HH',3,block)+chunk,peer)
                    if len(chunk) > (1024 if oack is not None else 512):return
                    ack,_=server.recvfrom(1024);seen.append(ack)
                    if ack!=struct.pack('!HH',4,block):raise AssertionError(ack)
                    if block==1 and (late_oack or changed_duplicate):
                        bad=(b'\x00\x06'+oack) if late_oack else struct.pack('!HH',3,1)+b'changed'
                        server.sendto(bad,peer)
                        if late_oack:seen.append(server.recvfrom(1024)[0])
                        return
                    if len(chunk)<size:return
                    block+=1
            except Exception as e:errors.append(e)
        thread=threading.Thread(target=serve);thread.start()
        request={'source':'127.0.0.1','address':'127.0.0.1','port':server.getsockname()[1],'filename':'f','timeout':3}
        if requested is not None:request['block_size']=requested
        with patch('network_labs.appliances.tftp_worker.DALLY_SECONDS',.02):result=read(request)
        thread.join(3)
        if thread.is_alive() or errors:raise AssertionError(errors)
        return result,seen


class TFTPBlockSizeTests(unittest.TestCase):
    def test_negotiated_smaller_size_empty_exact_multiple_and_binary(self):
        for data in (b'',bytes(range(256))*8,bytes(range(256))*9):
            with self.subTest(size=len(data)):
                result,seen=transfer(data,repeat=True)
                self.assertEqual(result['status'],'passed',result)
                self.assertEqual(result['sha256'],hashlib.sha256(data).hexdigest())
                self.assertEqual(result['bytes_received'],len(data))
                self.assertEqual(result['block_size'],1024);self.assertTrue(result['option_negotiated'])
                self.assertTrue(seen[0].endswith(b'blksize\x001428\x00'))
                self.assertEqual(seen[1:3],[b'\x00\x04\x00\x00']*2)

    def test_ignored_option_and_classic_request_use_512(self):
        for requested in (None,1428):
            result,seen=transfer(b'x'*1024,oack=None,size=512,requested=requested)
            self.assertEqual(result['status'],'passed',result);self.assertEqual(result['block_size'],512)
            self.assertFalse(result['option_negotiated'])
            self.assertEqual(b'blksize' in seen[0],requested is not None)

    def test_bad_unsolicited_and_extra_options_fail_without_content_digest(self):
        for payload in (b'blksize\x001429\x00',b'blksize\x00511\x00',b'blksize\x00-1\x00',b'blksize\x00x\x00',
                        b'blksize\x001024',b'tsize\x000\x00',b'blksize\x001024\x00blksize\x001024\x00'):
            with self.subTest(payload=payload):
                result,seen=transfer(b'',oack=payload)
                self.assertEqual(result['status'],'unknown',result);self.assertIsNone(result['sha256'])
                self.assertEqual(seen[-1][:4],b'\x00\x05\x00\x08')
        result,_=transfer(b'',requested=None)
        self.assertEqual(result['status'],'unknown')

    def test_ack_zero_timeout_retry_keeps_transfer_peer(self):
        result,seen=transfer(b'x'*2048,lost_ack=True)
        self.assertEqual(result['status'],'passed',result)
        self.assertEqual(result['retransmissions'],1)
        self.assertEqual(seen[1:3],[b'\x00\x04\x00\x00']*2)

    def test_late_oack_changed_duplicate_and_oversize_data_are_not_success(self):
        for kwargs in ({'late_oack':True},{'changed_duplicate':True},{'size':1428}):
            with self.subTest(kwargs=kwargs):
                result,_=transfer(b'x'*2048,**kwargs)
                self.assertEqual(result['status'],'unknown',result);self.assertIsNone(result['sha256'])

    def test_invalid_requested_size_rejected_before_namespace_io(self):
        for size in (True,511,1429,'1024'):
            manager=manager_for()
            with self.assertRaises(ValueError):managed_read(manager,'PC1','192.0.2.20','f',block_size=size)
            manager.ns.assert_not_called()
