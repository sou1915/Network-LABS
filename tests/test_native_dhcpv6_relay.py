"""DHCPv6 relay policy boundaries and independent relay packet decoding."""
import copy
import ipaddress
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock

from network_labs.appliances.examples import dhcpv6_relay_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.dhcpv6_relay import config, ra_config, prepare_files, observe, drift
from network_labs.appliances.service_adapters import adapters
from test_native_dhcpv6 import options


def relay_message(data):
    if len(data) < 34 or data[0] not in (12, 13): raise ValueError('Not a complete DHCPv6 relay header')
    entries = options(data[34:]); nested = [v for code, v in entries if code == 9]
    if len(nested) != 1 or len(nested[0]) < 4: raise ValueError('Relay needs one complete nested message')
    inner = nested[0]
    if inner[0] not in (1, 2, 3, 5, 6, 7, 8): raise ValueError('Unsupported nested message')
    fields = options(inner[4:]); addresses = []
    for code, value in fields:
        if code != 3: continue
        if len(value) < 12: raise ValueError('Truncated IA_NA')
        for subcode, address in options(value[12:]):
            if subcode == 5:
                if len(address) < 24: raise ValueError('Truncated IAADDR')
                preferred, valid = struct.unpack('!II', address[16:24])
                addresses.append({'address': str(ipaddress.IPv6Address(address[:16])), 'preferred': preferred, 'valid': valid})
    return {'type': data[0], 'hop_count': data[1], 'link': str(ipaddress.IPv6Address(data[2:18])),
            'peer': str(ipaddress.IPv6Address(data[18:34])), 'inner_type': inner[0], 'xid': inner[1:4].hex(),
            'client_ids': [v.hex() for c, v in fields if c == 1], 'server_ids': [v.hex() for c, v in fields if c == 2],
            'addresses': addresses}


def captured_relays(data):
    if len(data) < 24: return []
    endian = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>', b'\x4d\x3c\xb2\xa1': '<', b'\xa1\xb2\x3c\x4d': '>'}.get(data[:4])
    if endian is None or struct.unpack(endian + 'I', data[20:24])[0] != 1: return []
    result = []; pos = 24
    while pos + 16 <= len(data):
        size = struct.unpack(endian + 'IIII', data[pos:pos + 16])[2]; pos += 16
        frame = data[pos:pos + size]; pos += size
        if len(frame) != size or len(frame) < 66 or frame[12:14] != b'\x86\xdd': continue
        ip = frame[14:]
        if ip[0] >> 4 != 6 or ip[6] != 17: continue
        length = struct.unpack('!H', ip[4:6])[0]
        if length < 8 or len(ip) < 40 + length: continue
        udp = ip[40:40 + length]; src, dst, ulen, _ = struct.unpack('!HHHH', udp[:8])
        if (src, dst) != (547, 547) or ulen != len(udp): continue
        try: row = relay_message(udp[8:])
        except ValueError: continue
        row.update(source=str(ipaddress.IPv6Address(ip[8:24])), destination=str(ipaddress.IPv6Address(ip[24:40])))
        result.append(row)
    return result


class DHCPv6RelayTests(unittest.TestCase):
    def test_example_has_separate_allocation_relay_ra_and_explicit_return_routes(self):
        spec = dhcpv6_relay_lab('/rootfs'); self.assertEqual(validate(spec), spec)
        client, relay, server, _ = spec['nodes']
        self.assertEqual(client['ipv6'], {}); self.assertEqual(client['ipv6_routes'], [])
        self.assertTrue(all(not n['dhcpv6_server'] and not n['router_advertisements'] for n in spec['nodes']))
        relay_text, server_text = config(relay), config(server)
        self.assertIn('dhcp-relay=2001:db8:10::1,2001:db8:100::2,eth1', relay_text)
        self.assertNotIn('dhcp-range=', relay_text); self.assertNotIn('enable-ra', server_text)
        self.assertIn('dhcp-range=2001:db8:10::100,2001:db8:10::10f,64,120s', server_text)
        ra = ra_config(relay)
        self.assertIn('managed yes; other config no;', ra); self.assertIn('autonomous no;', ra)
        self.assertLess(ra.index('prefix 2001:db8:10::/64'), ra.index('prefix ::/0'))
        self.assertNotIn('protocol kernel', ra); self.assertNotIn('interface "eth1"', ra)
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'files').mkdir(); prepare_files(folder, relay)
            self.assertEqual((Path(folder) / 'files/bird.conf').read_text(), ra)

    def test_invalid_interfaces_destinations_and_service_compositions_rejected(self):
        for update in ({'interface': 'eth9'}, {'upstream': 'eth0'}, {'server': 'ff05::1:3'},
                       {'server': 'fe80::2'}, {'server': '2001:db8:100::1'}, {'server': '2001:db8:99::2'},
                       {'server': True}, {'advertise': False}, {'advertise': 1}, {'pd': True}):
            spec = dhcpv6_relay_lab('/rootfs'); spec['nodes'][1]['dhcpv6_relay'].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)
        for update in ({'ipv6_forwarding': False}, {'shutdown': ['eth1']}, {'forwarding': True},
                       {'router_advertisements': ['eth0']}, {'dhcpv6_clients': ['eth0']},
                       {'ospfv3': {'router_id': '1.1.1.1', 'interfaces': {'eth0': {}}}}):
            spec = dhcpv6_relay_lab('/rootfs'); spec['nodes'][1].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)

    def test_remote_pool_mapping_overlap_and_return_path_are_explicit(self):
        for update in ({'network': '2001:db8:20::/64'}, {'network': '2001:db8::/48'}, {'start': '2001:db8:10::1'},
                       {'end': '2001:db8:10::ffff'}, {'interface': 'eth9'}, {'lease_seconds': 60}):
            spec = dhcpv6_relay_lab('/rootfs'); spec['nodes'][2]['dhcpv6_remote_server'].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)
        spec = dhcpv6_relay_lab('/rootfs'); spec['nodes'][2]['ipv6_routes'] = []
        with self.assertRaisesRegex(ValueError, 'return route'): validate(spec)
        for index, field in ((1, 'dhcpv6_relay'), (2, 'dhcpv6_remote_server')):
            spec = dhcpv6_relay_lab('/rootfs'); spec['nodes'][index][field] = None
            with self.assertRaises(ValueError): validate(spec)

    def test_file_observation_does_not_invent_leases_and_both_relay_files_are_audited(self):
        import subprocess
        node = dhcpv6_relay_lab('/rootfs')['nodes'][1]; manager = Mock()
        manager.crun.side_effect = [subprocess.CompletedProcess([], 0, config(node), ''),
                                   subprocess.CompletedProcess([], 0, '# drift', ''),
                                   subprocess.CompletedProcess([], 1, '', 'no socket')]
        result = observe(manager, node)
        self.assertFalse(result['configuration_verified']); self.assertIsNone(result['ra_protocol'])
        self.assertNotIn('leases', result)
        manager.crun.side_effect = None; manager.crun.return_value = subprocess.CompletedProcess([], 1, '', '')
        self.assertTrue(drift(manager, node))
        changed = copy.deepcopy(node); changed['dhcpv6_relay']['server'] = '2001:db8:100::3'
        with self.assertRaisesRegex(ValueError, 'recreation'): adapters(changed, node)

    def test_wire_decoder_preserves_identity_and_rejects_truncated_or_duplicate_nested_messages(self):
        option = lambda code, value: struct.pack('!HH', code, len(value)) + value
        inner = b'\x03\x12\x34\x56' + option(1, b'client') + option(2, b'server')
        header = b'\x0c\x00' + ipaddress.IPv6Address('2001:db8:10::1').packed + ipaddress.IPv6Address('fe80::123').packed
        payload = header + option(9, inner)
        row = relay_message(payload)
        self.assertEqual((row['type'], row['inner_type'], row['xid'], row['link']), (12, 3, '123456', '2001:db8:10::1'))
        self.assertEqual(row['client_ids'], [b'client'.hex()])
        for bad in (payload[:33], payload[:-1], payload + option(9, inner), header + option(9, b'')):
            with self.subTest(length=len(bad)), self.assertRaises(ValueError): relay_message(bad)
        udp = struct.pack('!HHHH', 547, 547, 8 + len(payload), 0) + payload
        ip = struct.pack('!IHBB', 6 << 28, len(udp), 17, 64) + ipaddress.IPv6Address('2001:db8:100::1').packed + ipaddress.IPv6Address('2001:db8:100::2').packed
        frame = b'\0' * 12 + b'\x86\xdd' + ip + udp
        pcap = struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 2048, 1) + struct.pack('<IIII', 0, 0, len(frame), len(frame)) + frame
        self.assertEqual(captured_relays(pcap)[0]['xid'], '123456')
        self.assertEqual(captured_relays(pcap[:-1]), [])
