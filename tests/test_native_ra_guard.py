"""RA Guard access boundaries and independently decodable wire fixtures."""
import copy
import ipaddress
import struct
import unittest
from network_labs.appliances.examples import ra_guard_lab
from network_labs.appliances.ra_guard import render
from network_labs.appliances.service_adapters import adapters
from network_labs.appliances.spec import validate


def checksum(data):
    if len(data) % 2: data += b'\0'
    value = sum(struct.unpack('!' + 'H' * (len(data) // 2), data))
    while value >> 16: value = (value & 0xffff) + (value >> 16)
    return (~value) & 0xffff


def rogue_frames(mac, source):
    """Valid plain/padded RA, fragment cases, and tags on the SAME access VID."""
    source = ipaddress.IPv6Address(source).packed; destination = ipaddress.IPv6Address('ff02::1').packed
    prefix = struct.pack('!BBBBIII16s', 3, 4, 64, 0xc0, 600, 600, 0, ipaddress.IPv6Address('2001:db8:666::').packed)
    ra = struct.pack('!BBHBBHII', 134, 0, 0, 64, 0, 1800, 0, 0) + prefix
    pseudo = source + destination + struct.pack('!I3xB', len(ra), 58)
    ra = ra[:2] + struct.pack('!H', checksum(pseudo + ra)) + ra[4:]
    ethernet = bytes.fromhex('333300000001') + bytes.fromhex(mac.replace(':', ''))
    def packet(next_header, payload):
        return struct.pack('!IHBB16s16s', 6 << 28, len(payload), next_header, 255, source, destination) + payload
    plain = packet(58, ra); padding = bytes([58, 0, 1, 4, 0, 0, 0, 0])
    ipv6 = b'\x86\xdd'
    return {'plain': ethernet + ipv6 + plain,
            'destination-options': ethernet + ipv6 + packet(60, padding + ra),
            'hop-by-hop': ethernet + ipv6 + packet(0, padding + ra),
            'atomic-fragment': ethernet + ipv6 + packet(44, struct.pack('!BBHI', 58, 0, 0, 0x12345678) + ra),
            'first-fragment': ethernet + ipv6 + packet(44, struct.pack('!BBHI', 58, 0, 1, 0x12345679) + ra[:16]),
            'later-fragment': ethernet + ipv6 + packet(44, struct.pack('!BBHI', 58, 0, 16, 0x12345679) + ra[16:]),
            'dot1q': ethernet + b'\x81\x00\x00\x0a' + ipv6 + plain,
            'qinq': ethernet + b'\x88\xa8\x00\x0a\x81\x00\x00\x0a' + ipv6 + plain}


class RAGuardTests(unittest.TestCase):
    def test_only_declared_router_port_is_trusted_and_opaque_ipv6_is_explicitly_dropped(self):
        spec = ra_guard_lab('/rootfs'); self.assertEqual(validate(spec), spec)
        switch = spec['nodes'][5]; text = render(switch, replace=True)
        self.assertEqual(switch['ra_guard'], {'trusted': ['eth1']})
        self.assertTrue(text.startswith('delete table bridge network_labs_ra_guard\n'))
        self.assertIn('priority -320; policy accept;', text)
        self.assertIn('ip6 nexthdr != { tcp, udp, ipv6-icmp } counter drop comment "opaque:eth2"', text)
        self.assertIn('icmpv6 type nd-router-advert counter drop comment "ra:eth2"', text)
        self.assertIn('counter accept comment "trusted:eth1"', text)
        self.assertNotIn('opaque:eth1', text); self.assertNotIn('flush ruleset', text)
        candidate = copy.deepcopy(switch); candidate['ra_guard']['trusted'] = []
        with self.assertRaisesRegex(ValueError, 'recreation'): adapters(candidate, switch)

    def test_invalid_trust_ports_tags_bundles_and_service_compositions_are_rejected(self):
        for update in ({'ra_guard': {'trusted': ['eth99']}}, {'ra_guard': {'trusted': ['eth1', 'eth1']}},
                       {'ra_guard': {'trusted': 'eth1'}}, {'ra_guard': {'trusted': [], 'enabled': True}},
                       {'role': 'host'}, {'switch_backend': 'ovs'}, {'shutdown': ['eth2']},
                       {'startup': [['/bin/true']]}, {'ipv6': {'eth0': '2001:db8:10::1/64'}}):
            spec = ra_guard_lab('/rootfs'); spec['nodes'][5].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)
        spec = ra_guard_lab('/rootfs'); spec['nodes'][5]['switchports']['eth2'] = {'mode': 'trunk', 'allowed': [10]}
        with self.assertRaises(ValueError): validate(spec)
        spec = ra_guard_lab('/rootfs'); spec['nodes'][5]['vlans'].append(20); spec['nodes'][5]['switchports']['eth2']['vlan'] = 20
        with self.assertRaises(ValueError): validate(spec)

    def test_wire_ra_checksums_and_padding_are_valid_independently_of_guard(self):
        frames = rogue_frames('02:00:00:00:00:66', 'fe80::66'); raw = frames['plain'][14:]; ra = raw[40:]
        pseudo = raw[8:40] + struct.pack('!I3xB', len(ra), 58)
        self.assertEqual(checksum(pseudo + ra), 0)
        self.assertEqual(raw[7], 255); self.assertEqual(ra[0], 134)
        self.assertEqual(len(ra), 48)
        for name in ('destination-options', 'hop-by-hop'):
            self.assertEqual(frames[name][54:62], bytes([58, 0, 1, 4, 0, 0, 0, 0]))
            self.assertEqual(frames[name][62:], ra)
        self.assertEqual(frames['dot1q'][12:18], b'\x81\x00\x00\x0a\x86\xdd')
