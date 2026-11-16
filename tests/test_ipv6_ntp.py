"""Explicit IPv6 local reference, fixed peers and no host clock privileges."""
import copy
import io
import json
from pathlib import Path
import socket
import struct
import unittest
from contextlib import redirect_stdout
from network_labs.appliances.examples import ipv6_ntp_lab, ntp_lab
from network_labs.appliances.ntp_server import command,config_text
from network_labs.appliances.ntp_socket import parse_udp_table
from network_labs.appliances.runtime import oci_config
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main
from test_native_ntp_socket import HEADER


class IPv6NTPTests(unittest.TestCase):
    def test_profile_and_cli_keep_local_reference_clockless_and_bound(self):
        spec=ipv6_ntp_lab('/rootfs');self.assertEqual(validate(spec),spec)
        node=spec['nodes'][3];text=config_text(node)
        self.assertIn('bindaddress 2001:db8:20::20\n',text)
        self.assertIn('allow 2001:db8:10::10/128\n',text)
        self.assertIn('local stratum 10\n',text);self.assertNotIn('server ',text)
        self.assertIn('-6',command('ipv6'));self.assertIn('-x',command('ipv6'))
        caps=oci_config(spec,node,3,Path('/rootfs'))['process']['capabilities']
        self.assertTrue(all('CAP_SYS_TIME' not in values for values in caps.values()))
        self.assertIn('-4',command());self.assertNotIn('family',ntp_lab('/rootfs')['nodes'][3]['ntp_server'])
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-ntp','--rootfs','/rootfs']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)

    def test_ipv6_udp_table_decodes_native_word_order_and_real_socket(self):
        packed=socket.inet_pton(socket.AF_INET6,'2001:db8:20::20')
        code=''.join(f'{struct.unpack("=I",packed[i:i+4])[0]:08X}' for i in range(0,16,4))
        row=f'  12: {code}:007B '+('0'*32)+':0000 07 00000000:00000000 00:00000000 00000000 0 0 123\n'
        self.assertEqual(parse_udp_table(HEADER+row,family='ipv6'),[{'address':'2001:db8:20::20','state':7}])
        for value in (row.replace(code,'00'),row.replace(':007B',':QQQQ')):
            with self.assertRaises(ValueError):parse_udp_table(HEADER+value,family='ipv6')
        with socket.socket(socket.AF_INET6,socket.SOCK_DGRAM) as sock:
            sock.bind(('::1',0))
            observed=parse_udp_table(Path('/proc/net/udp6').read_text(),port=sock.getsockname()[1],family='ipv6')
            self.assertIn({'address':'::1','state':7},observed)

    def test_upstream_unknown_clients_dynamic_and_other_services_remain_refused(self):
        original=ipv6_ntp_lab('/rootfs')
        for fault in ('upstream','unmanaged','self','mapped','family','mixed','dynamic','dns'):
            spec=copy.deepcopy(original);policy=spec['nodes'][3]['ntp_server']
            if fault=='upstream':policy.pop('local_stratum');policy['upstream']='2001:db8:10::10'
            if fault=='unmanaged':policy['clients']=['2001:db8:40::40']
            if fault=='self':policy['clients']=['2001:db8:20::20']
            if fault=='mapped':policy['clients']=['::ffff:192.0.2.10']
            if fault=='family':policy['family']='auto'
            if fault=='mixed':spec['nodes'][0]['interfaces']['eth0']='192.0.2.10/24'
            if fault=='dynamic':spec['nodes'][0]['slaac']=['eth0']
            if fault=='dns':spec['nodes'][0]['resolvers']=['2001:db8:20::20']
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)
