"""SLAAC policy contracts and independent RA wire decoding for native capture."""
import copy
import ipaddress
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from network_labs.appliances.examples import slaac_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.slaac import CLIENT_SYSCTLS, configure_client, server_config, prepare_files, drift
from network_labs.appliances.service_adapters import adapters


def captured_ras(data):
    if len(data) < 24:
        return []
    endian = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>', b'\x4d\x3c\xb2\xa1': '<', b'\xa1\xb2\x3c\x4d': '>'}.get(data[:4])
    if endian is None or struct.unpack(endian + 'I', data[20:24])[0] != 1:
        return []
    pos, result = 24, []
    while pos + 16 <= len(data):
        size = struct.unpack(endian + 'IIII', data[pos:pos + 16])[2]; pos += 16
        frame = data[pos:pos + size]; pos += size
        if len(frame) != size or len(frame) < 70 or frame[12:14] != b'\x86\xdd':
            continue
        ip = frame[14:]
        if ip[0] >> 4 != 6 or ip[6] != 58:
            continue
        payload_len = struct.unpack('!H', ip[4:6])[0]
        if payload_len < 16 or len(ip) < 40 + payload_len:
            continue
        ra = ip[40:40 + payload_len]
        if ra[0:2] != b'\x86\x00':
            continue
        row = {'source': str(ipaddress.IPv6Address(ip[8:24])), 'hop_limit': ip[7],
               'managed': bool(ra[5] & 0x80), 'other': bool(ra[5] & 0x40),
               'router_lifetime': struct.unpack('!H', ra[6:8])[0], 'options': [], 'prefixes': []}
        offset, valid = 16, True
        while offset < len(ra):
            if offset + 2 > len(ra) or ra[offset + 1] == 0:
                valid = False; break
            length = ra[offset + 1] * 8
            option = ra[offset:offset + length]; offset += length
            if len(option) != length:
                valid = False; break
            row['options'].append(option[0])
            if option[0] == 3:
                if length != 32 or option[2] > 128:
                    valid = False; break
                row['prefixes'].append({'network': str(ipaddress.IPv6Network((ipaddress.IPv6Address(option[16:32]), option[2]), strict=False)),
                                        'autonomous': bool(option[3] & 0x40), 'on_link': bool(option[3] & 0x80)})
        if valid:
            result.append(row)
    return result


class SLAACTests(unittest.TestCase):
    def test_policy_has_dynamic_host_and_only_one_advertised_router_port(self):
        spec = slaac_lab('/rootfs')
        self.assertEqual(validate(spec), spec)
        self.assertEqual(spec['nodes'][0]['slaac'], ['eth0'])
        self.assertEqual(spec['nodes'][0]['ipv6'], {})
        self.assertEqual(spec['nodes'][0]['ipv6_routes'], [])
        self.assertEqual(spec['nodes'][1]['router_advertisements'], ['eth0'])
        self.assertEqual(spec['nodes'][2]['router_advertisements'], [])

    def test_bad_roles_mixed_static_hosts_and_down_ports_rejected(self):
        for edit in (lambda n: n['slaac'].append('eth0'), lambda n: n.update(slaac=['eth99']),
                     lambda n: n.update(ipv6={'eth0': '2001:db8:10::10/64'}),
                     lambda n: n.update(shutdown=['eth0'])):
            spec = slaac_lab('/rootfs'); edit(spec['nodes'][0])
            with self.assertRaises(ValueError): validate(spec)
        spec = slaac_lab('/rootfs'); spec['nodes'][0]['router_advertisements'] = ['eth0']
        with self.assertRaises(ValueError): validate(spec)
        old = slaac_lab('/rootfs')['nodes'][0]; new = copy.deepcopy(old); new['slaac'] = []
        with self.assertRaises(ValueError): adapters(new, old)

    def test_client_settings_and_ra_only_config_are_explicit(self):
        spec = slaac_lab('/rootfs'); manager = Mock()
        configure_client(manager, 0, spec['nodes'][0])
        for key, value in CLIENT_SYSCTLS.items():
            manager.ns.assert_any_call(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/' + key + '=' + str(value))
        self.assertFalse(any('addr' in call.args for call in manager.ns.call_args_list))
        text = server_config(spec['nodes'][1])
        self.assertIn('ra-only,64,2h', text); self.assertIn('port=0\n', text)
        self.assertIn('dhcp-option=option6:dns-server\n', text)
        self.assertNotIn('interface=eth1', text)
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'files').mkdir(); prepare_files(folder, spec['nodes'][1])
            self.assertEqual((Path(folder) / 'files/ra.conf').read_text(), text)

    def test_client_audit_preserves_learned_state_but_rejects_wrong_policy(self):
        manager = Mock(); node = slaac_lab('/rootfs')['nodes'][0]
        routes = [{'dst': 'default', 'gateway': 'fe80::1', 'dev': 'eth0', 'protocol': 'ra'}]
        def ns(index, *args, **kwargs):
            value = json.dumps(routes) if args[0] == 'ip' else str(CLIENT_SYSCTLS.get(args[-1].rsplit('/', 1)[-1], 0))
            return subprocess.CompletedProcess([], 0, value, '')
        manager.ns.side_effect = ns
        self.assertEqual(drift(manager, 0, node), [])
        routes.append({'dst': '2001:db8:99::/64', 'protocol': 'static'})
        self.assertTrue(any('non-RA' in e for e in drift(manager, 0, node)))
        router = slaac_lab('/rootfs')['nodes'][1]
        with patch('network_labs.appliances.slaac.observe_config', return_value={'configuration_verified': False}):
            self.assertTrue(any('RA configuration' in e for e in drift(manager, 1, router)))

    def test_wire_decoder_checks_real_ra_fields_and_rejects_truncation(self):
        prefix = bytes([3, 4, 64, 0xc0]) + struct.pack('!III', 7200, 7200, 0) + ipaddress.IPv6Address('2001:db8:10::').packed
        ra = struct.pack('!BBHBBHII', 134, 0, 0, 64, 0, 15, 0, 0) + prefix
        ip = struct.pack('!IHBB', 6 << 28, len(ra), 58, 255) + ipaddress.IPv6Address('fe80::1').packed + ipaddress.IPv6Address('ff02::1').packed
        frame = b'\x00' * 12 + b'\x86\xdd' + ip + ra
        header = b'\xd4\xc3\xb2\xa1' + struct.pack('<HHIIII', 2, 4, 0, 0, 2048, 1)
        pcap = header + struct.pack('<IIII', 0, 0, len(frame), len(frame)) + frame
        result = captured_ras(pcap)
        self.assertEqual(result[0]['source'], 'fe80::1')
        self.assertEqual(result[0]['hop_limit'], 255); self.assertEqual(result[0]['router_lifetime'], 15)
        self.assertFalse(result[0]['managed']); self.assertFalse(result[0]['other'])
        self.assertEqual(result[0]['prefixes'], [{'network': '2001:db8:10::/64', 'autonomous': True, 'on_link': True}])
        self.assertEqual(captured_ras(pcap[:-1]), [])
