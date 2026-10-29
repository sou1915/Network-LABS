"""PD policy boundaries, bounded native hook, and wire prefix decoding."""
import copy
import ipaddress
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from network_labs.appliances.examples import dhcpv6_pd_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.dhcpv6_pd import server_config, gateway, hook_policy, dynamic_address, rootfs_assets
from network_labs.appliances.service_adapters import adapters
from test_native_dhcpv6 import options


def captured_pd(data):
    if len(data) < 24: return []
    endian = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>', b'\x4d\x3c\xb2\xa1': '<', b'\xa1\xb2\x3c\x4d': '>'}.get(data[:4])
    if endian is None or struct.unpack(endian + 'I', data[20:24])[0] != 1: return []
    pos = 24; result = []
    while pos + 16 <= len(data):
        length = struct.unpack(endian + 'IIII', data[pos:pos + 16])[2]; pos += 16
        frame = data[pos:pos + length]; pos += length
        if len(frame) != length or len(frame) < 66 or frame[12:14] != b'\x86\xdd': continue
        ip = frame[14:]
        if ip[0] >> 4 != 6 or ip[6] != 17: continue
        length = struct.unpack('!H', ip[4:6])[0]
        if length < 12 or len(ip) < 40 + length: continue
        udp = ip[40:40 + length]; src, dst, ulen, _ = struct.unpack('!HHHH', udp[:8])
        if (src, dst) not in ((546, 547), (547, 546)) or ulen != len(udp): continue
        message = udp[8:]
        try:
            fields = options(message[4:]); prefixes = []
            for code, ia in fields:
                if code != 25: continue
                if len(ia) < 12: raise ValueError('Truncated IA_PD')
                for subcode, value in options(ia[12:]):
                    if subcode != 26: continue
                    if len(value) < 25 or value[8] > 128: raise ValueError('Truncated IAPREFIX')
                    preferred, valid = struct.unpack('!II', value[:8])
                    prefixes.append({'prefix': str(ipaddress.IPv6Network((ipaddress.IPv6Address(value[9:25]), value[8]), strict=True)),
                                     'preferred': preferred, 'valid': valid})
            result.append({'type': message[0], 'xid': message[1:4].hex(), 'prefixes': prefixes,
                           'client_ids': [v.hex() for c, v in fields if c == 1],
                           'server_ids': [v.hex() for c, v in fields if c == 2], 'ia_na': any(c == 3 for c, _ in fields)})
        except ValueError: continue
    return result


class PDPolicyTests(unittest.TestCase):
    def test_one_prefix_profile_uses_real_pd_pool_and_has_no_preassigned_lan_gateway(self):
        spec = dhcpv6_pd_lab('/rootfs'); self.assertEqual(validate(spec), spec)
        host, client, server, _ = spec['nodes']
        self.assertEqual(host['ipv6'], {}); self.assertEqual(host['ipv6_routes'], [])
        self.assertNotIn('eth0', client['ipv6']); self.assertEqual(gateway(client), '2001:db8:10::1/64')
        from network_labs.appliances.runtime import oci_config
        mounts = oci_config(spec, server, 2, '/tmp/bundle/rootfs')['mounts']
        kea_mount = next(m for m in mounts if m['destination'] == '/etc/kea/kea-dhcp6.conf')
        self.assertEqual(kea_mount['source'], '/tmp/bundle/files/kea-pd.json')
        self.assertIn('ro', kea_mount['options'])
        pool = json.loads(server_config(server))['Dhcp6']['subnet6'][0]
        self.assertNotIn('pools', pool); self.assertEqual(pool['pd-pools'][0]['delegated-len'], 64)
        self.assertEqual(hook_policy(client), 'eth0\n2001:db8:10::/64\n30\n')
        info = {'valid_life_time': 25, 'preferred_life_time': 25}
        self.assertTrue(dynamic_address(client, 'eth0', gateway(client), info))
        self.assertFalse(dynamic_address(client, 'eth1', gateway(client), info))
        self.assertFalse(dynamic_address(client, 'eth0', gateway(client), {'valid_life_time': 4294967295, 'preferred_life_time': 30}))
        changed = copy.deepcopy(client); changed['dhcpv6_pd_client']['lease_seconds'] = 40
        with self.assertRaisesRegex(ValueError, 'recreation'): adapters(changed, client)

    def test_bad_delegations_interfaces_compositions_and_return_routes_are_rejected(self):
        for update in ({'prefix': '2001:db8:10::/56'}, {'prefix': '2001:db8:10::1/64'}, {'prefix': 'fe80::/64'},
                       {'server': 'ff02::1:2'}, {'server': '2001:db8:100::2'}, {'downstream': 'eth1'},
                       {'advertise': False}, {'lease_seconds': 1}, {'lease_seconds': True}):
            spec = dhcpv6_pd_lab('/rootfs'); spec['nodes'][1]['dhcpv6_pd_client'].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)
        for update in ({'ipv6_forwarding': False}, {'forwarding': True}, {'shutdown': ['eth0']},
                       {'ipv6': {'eth1': '2001:db8:100::2/64', 'eth0': '2001:db8:10::1/64'}}):
            spec = dhcpv6_pd_lab('/rootfs'); spec['nodes'][1].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)
        spec = dhcpv6_pd_lab('/rootfs'); spec['nodes'][2]['ipv6_routes'] = []
        with self.assertRaisesRegex(ValueError, 'return route'): validate(spec)
        spec = dhcpv6_pd_lab('/rootfs'); spec['nodes'][2]['dhcpv6_pd_server']['lease_seconds'] = 40
        with self.assertRaisesRegex(ValueError, 'match'): validate(spec)


@unittest.skipUnless(shutil.which('cc'), 'C compiler required')
class PDHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.folder.cleanup)
        root = Path(cls.folder.name); cls.policy = root / 'policy'; cls.binary = root / 'hook'; cls.stub = root / 'busybox'
        cls.stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n'); cls.stub.chmod(0o755)
        source = Path(__file__).parents[1] / 'network_labs/appliances/dhcpv6_pd_hook.c'
        subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-DNL_PD_POLICY="' + str(cls.policy) + '"',
                        '-DNL_BUSYBOX="' + str(cls.stub) + '"', str(source), '-o', str(cls.binary)], check=True, capture_output=True)

    def invoke(self, action, **variables):
        self.policy.write_text('eth0\n2001:db8:10::/64\n30\n')
        return subprocess.run([self.binary, action], capture_output=True, text=True,
                              env={'PATH': '/usr/bin:/bin', **variables}, timeout=3)

    def test_hook_canonicalizes_and_renews_finite_address_without_flushing_lan(self):
        for action in ('bound', 'renew'):
            result = self.invoke(action, ipv6prefix='2001:0db8:0010:0000:0000:0000:0000:0000/64', ipv6prefix_lease='30')
            self.assertEqual(result.returncode, 0, result)
            self.assertEqual(result.stdout.splitlines(), ['ip', '-6', 'addr', 'replace', '2001:db8:10::1/64', 'dev', 'eth0',
                                                          'valid_lft', '30', 'preferred_lft', '30'])
        self.assertTrue(any(str(p) == '/usr/lib/network-labs/dhcpv6-pd-hook' for _, p in rootfs_assets(hook=self.binary)))

    def test_rejected_or_expired_lease_never_adds_a_gateway(self):
        for prefix, lifetime in (('2001:db8:99::/64', '30'), ('2001:db8:10::/56', '30'),
                                 ('2001:db8:10::1/64', '30'), ('2001:db8:10::/64', '31'),
                                 ('2001:db8:10::/64', '-1'), ('2001:db8:10::/64', '30\n'), ('', '30')):
            result = self.invoke('bound', ipv6prefix=prefix, ipv6prefix_lease=lifetime)
            self.assertEqual(result.returncode, 126, result); self.assertEqual(result.stdout, '')
        self.assertEqual(self.invoke('bound').returncode, 126)
        for action, variables in (('deconfig', {}), ('renew', {'ipv6prefix': '2001:db8:10::/64', 'ipv6prefix_lease': '0'})):
            result = self.invoke(action, **variables)
            self.assertEqual(result.returncode, 0, result)
            self.assertEqual(result.stdout.splitlines(), ['ip', '-6', 'addr', 'flush', 'dev', 'eth0', 'to', '2001:db8:10::1/128'])
