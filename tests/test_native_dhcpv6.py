"""Stateful DHCPv6 policy and independent bounded IA_NA packet decoding."""
import copy
import ipaddress
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
from network_labs.appliances.examples import dhcpv6_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.dhcpv6 import CLIENT_SCRIPT, prepare_files, start_clients, drift
from network_labs.appliances.slaac import configure_client, server_config, client_settings
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.service_adapters import adapters


def options(data):
    result = []
    while data:
        if len(data) < 4: raise ValueError('Truncated DHCPv6 option')
        code, size = struct.unpack('!HH', data[:4])
        if len(data) < 4 + size: raise ValueError('Truncated DHCPv6 payload')
        result.append((code, data[4:4 + size])); data = data[4 + size:]
    return result


def captured_dhcpv6(data):
    if len(data) < 24: return []
    endian = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>', b'\x4d\x3c\xb2\xa1': '<', b'\xa1\xb2\x3c\x4d': '>'}.get(data[:4])
    if endian is None or struct.unpack(endian + 'I', data[20:24])[0] != 1: return []
    pos, result = 24, []
    while pos + 16 <= len(data):
        size = struct.unpack(endian + 'IIII', data[pos:pos + 16])[2]; pos += 16
        frame = data[pos:pos + size]; pos += size
        if len(frame) != size or len(frame) < 66 or frame[12:14] != b'\x86\xdd': continue
        ip = frame[14:]
        if ip[0] >> 4 != 6 or ip[6] != 17: continue
        plen = struct.unpack('!H', ip[4:6])[0]
        if plen < 12 or len(ip) < 40 + plen: continue
        udp = ip[40:40 + plen]; source, dest, length, _ = struct.unpack('!HHHH', udp[:8])
        if (source, dest) not in ((546, 547), (547, 546)) or length != len(udp): continue
        message = udp[8:]
        if message[0] not in (1, 2, 3, 5, 6, 7, 8): continue
        row = {'type': message[0], 'xid': message[1:4].hex(), 'ports': (source, dest), 'addresses': []}
        try:
            top = options(message[4:]); row['options'] = [c for c, _ in top]
            row['client_ids'] = [v.hex() for c, v in top if c == 1]
            row['server_ids'] = [v.hex() for c, v in top if c == 2]
            for code, ia in top:
                if code != 3: continue
                if len(ia) < 12: raise ValueError('Truncated IA_NA')
                for subcode, value in options(ia[12:]):
                    if subcode != 5: continue
                    if len(value) < 24: raise ValueError('Truncated IAADDR')
                    preferred, valid = struct.unpack('!II', value[16:24])
                    row['addresses'].append({'address': str(ipaddress.IPv6Address(value[:16])), 'preferred': preferred, 'valid': valid})
        except ValueError:
            continue
        result.append(row)
    return result


class DHCPv6Tests(unittest.TestCase):
    def test_example_and_rejected_pool_role_and_client_combinations(self):
        spec = dhcpv6_lab('/rootfs'); self.assertEqual(validate(copy.deepcopy(spec)), spec)
        self.assertEqual(spec['nodes'][0]['ipv6'], {}); self.assertEqual(spec['nodes'][0]['ipv6_routes'], [])
        for edit in (lambda n: n.update(slaac=['eth0']), lambda n: n.update(dhcpv6_clients=['eth1']),
                     lambda n: n.update(dhcpv6_clients=['eth0', 'eth0']), lambda n: n.update(shutdown=['eth0']),
                     lambda n: n.update(ipv6={'eth0': '2001:db8:10::10/64'})):
            bad = copy.deepcopy(spec); edit(bad['nodes'][0])
            with self.assertRaises(ValueError): validate(bad)
        for changes in ({'start': '2001:db8:20::100'}, {'end': '2001:db8:10::ffff'},
                        {'start': '2001:db8:10::1'}, {'lease_seconds': True}, {'lease_seconds': 60}, {'interface': 'eth1'}, {'end': '::/0'}):
            bad = copy.deepcopy(spec); bad['nodes'][1]['dhcpv6_server'].update(changes)
            with self.assertRaises(ValueError): validate(bad)
        bad = copy.deepcopy(spec); bad['nodes'][1]['router_advertisements'] = []
        with self.assertRaises(ValueError): validate(bad)
        bad = copy.deepcopy(spec); bad['nodes'][3]['ipv6']['eth0'] = '2001:db8:10::100/64'
        bad['nodes'][3]['ipv6_routes'] = []
        with self.assertRaises(ValueError): validate(bad)
        node = spec['nodes'][0]; new = copy.deepcopy(node); new['dhcpv6_clients'] = []
        with self.assertRaises(ValueError): adapters(new, node)

    def test_client_keeps_ra_but_no_slaac_or_injected_address_or_route(self):
        node = dhcpv6_lab('/rootfs')['nodes'][0]; manager = Mock()
        configure_client(manager, 0, node)
        self.assertEqual(client_settings(node)['autoconf'], 0)
        manager.ns.assert_any_call(0, 'sysctl', '-w', 'net/ipv6/conf/eth0/accept_ra=1')
        self.assertFalse(any('addr' in c.args or 'route' in c.args for c in manager.ns.call_args_list))
        self.assertNotIn('route', CLIENT_SCRIPT); self.assertNotIn('resolv', CLIENT_SCRIPT)
        self.assertIn('valid_lft "$lease"', CLIENT_SCRIPT); self.assertIn('scope global', CLIENT_SCRIPT)

    def test_config_real_stateful_range_without_dns_and_managed_script_drift(self):
        spec = dhcpv6_lab('/rootfs'); node = spec['nodes'][0]
        text = server_config(spec['nodes'][1])
        self.assertIn('dhcp-range=2001:db8:10::100,2001:db8:10::10f,64,120s', text)
        self.assertNotIn('ra-only', text); self.assertIn('port=0\n', text)
        self.assertIn('dhcp-option=option6:dns-server\n', text)
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'files').mkdir(); prepare_files(folder, node)
            self.assertEqual((Path(folder) / 'files/dhcpv6-client.sh').read_text(), CLIENT_SCRIPT)
        with patch('network_labs.appliances.dhcpv6.observe_config', return_value={'configuration_verified': False}):
            self.assertTrue(drift(Mock(), 0, node))

    def test_real_applet_required_before_daemon_launch_no_fallback(self):
        manager = Mock(); manager.directory = Path('/run/lab'); manager.state = {'spec': dhcpv6_lab('/rootfs')}
        manager.crun.return_value.stdout = 'sh\nip\n'
        with self.assertRaises(RuntimeFailure): start_clients(manager)
        self.assertEqual(manager.crun.call_count, 1)
        manager.crun.reset_mock(); manager.crun.return_value.stdout = 'sh\nudhcpc6\n'
        start_clients(manager)
        args = manager.crun.call_args.args
        self.assertIn('--detach', args); self.assertIn('udhcpc6', args); self.assertIn('-o', args)
        self.assertNotIn('-q', args); self.assertNotIn('-d', args)

    def test_decoder_requires_complete_ia_and_real_transaction_fields(self):
        def opt(code, value): return struct.pack('!HH', code, len(value)) + value
        lease = ipaddress.IPv6Address('2001:db8:10::10a').packed + struct.pack('!II', 60, 60)
        message = b'\x07\x12\x34\x56' + opt(1, b'client') + opt(2, b'server') + opt(3, b'\x00' * 12 + opt(5, lease))
        udp = struct.pack('!HHHH', 547, 546, 8 + len(message), 0) + message
        ip = struct.pack('!IHBB', 6 << 28, len(udp), 17, 1) + b'\x00' * 32
        frame = b'\x00' * 12 + b'\x86\xdd' + ip + udp
        pcap = b'\xd4\xc3\xb2\xa1' + struct.pack('<HHIIII', 2, 4, 0, 0, 2048, 1) + struct.pack('<IIII', 0, 0, len(frame), len(frame)) + frame
        row = captured_dhcpv6(pcap)[0]
        self.assertEqual(row['xid'], '123456'); self.assertEqual(row['type'], 7)
        self.assertEqual(row['addresses'], [{'address': '2001:db8:10::10a', 'preferred': 60, 'valid': 60}])
        self.assertEqual(captured_dhcpv6(pcap[:-1]), [])
        with self.assertRaises(ValueError): options(b'\x00\x03\x00\x10\x00')
