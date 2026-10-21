"""ARP authorization must expire, preserve policy drift and reject ambiguous owners."""
import copy
import json
import struct
import subprocess
import unittest
from unittest.mock import patch

from network_labs.appliances.arp_inspection import effective, render, fingerprint, authorization_script, refresh
from network_labs.appliances.examples import arp_inspection_lab
from network_labs.appliances.ios import compile_config
from network_labs.appliances.snooping import observer_scope
from network_labs.appliances.snooping_packets import decode, checksum
from network_labs.appliances.spec import validate
from test_native_snooping import frame

MAC = '02:00:00:00:10:10'


def binding(**changes):
    return {'mac': MAC, 'address': '10.10.0.100', 'port': 'eth0', 'vlan': 10, 'until': 200, **changes}


def raw(elements=None):
    return {'nftables': [{'set': {'family': 'bridge', 'name': 'dhcp_eth0', 'table': 'network_labs_arp_inspection',
                                 'type': ['ether_addr', 'ether_addr', 'ipv4_addr'], 'flags': ['timeout'],
                                 'timeout': 2000, 'size': 2048, 'elem': elements or []}},
                         {'rule': {'expr': [{'counter': {'packets': 0, 'bytes': 0}}, {'drop': None}]}}]}


class ARPInspectionTests(unittest.TestCase):
    def test_policy_requires_active_snooping_and_explicit_nonambiguous_static_owners(self):
        base = arp_inspection_lab('/rootfs')
        self.assertEqual(validate(base), base)
        changes = [lambda n: n['dhcp_snooping'].update(enabled=False),
                   lambda n: n['arp_inspection'].update(vlans=[10, 10]),
                   lambda n: n['arp_inspection'].update(trusted=['eth9']),
                   lambda n: n['arp_inspection']['bindings'][0].update(address='0.0.0.0'),
                   lambda n: n['arp_inspection']['bindings'][0].update(mac='ff:ff:ff:ff:ff:ff'),
                   lambda n: n['arp_inspection']['bindings'][0].update(vlan=20),
                   lambda n: n['arp_inspection']['bindings'].append(dict(n['arp_inspection']['bindings'][0]))]
        for change in changes:
            spec = copy.deepcopy(base); change(spec['nodes'][1])
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(spec)
        # DHCP trust is not ARP trust: independent explicit policy.
        base['nodes'][1]['arp_inspection']['trusted'] = []
        self.assertFalse(effective(validate(base)['nodes'][1])['trusted'])

    def test_ios_source_binding_and_arp_trust_validate_whole_blocks(self):
        spec = arp_inspection_lab('/rootfs'); original = copy.deepcopy(spec)
        result = compile_config(spec, 'SW1', 'conf t\nno ip source binding 0200.0000.1003 vlan 10 10.10.0.3 interface fa0/3\ninterface fa0/3\nip arp inspection trust\nend')
        self.assertFalse(result['nodes'][1]['arp_inspection']['bindings'])
        self.assertIn('eth2', result['nodes'][1]['arp_inspection']['trusted'])
        with self.assertRaises(ValueError):
            compile_config(spec, 'SW1', 'conf t\nno ip dhcp snooping\nend')
        with self.assertRaises(ValueError):
            compile_config(spec, 'SW1', 'conf t\ninterface fa0/1\nshutdown\nexit\nip arp inspection validate src-mac\nend')
        self.assertEqual(spec, original)
        disabled = compile_config(spec, 'SW1', 'conf t\nno ip arp inspection vlan 10\nno ip dhcp snooping\nend')
        self.assertIsNone(effective(disabled['nodes'][1]))
        self.assertNotEqual(observer_scope(spec['nodes'][1]), observer_scope(result['nodes'][1]))

    def test_rules_match_ethernet_and_arp_mac_together_and_only_inspect_arp(self):
        script = render(effective(arp_inspection_lab('/rootfs')['nodes'][1]))
        self.assertIn('type ether_addr . ether_addr . ipv4_addr', script)
        self.assertIn('ether saddr . arp saddr ether . arp saddr ip @dhcp_eth0', script)
        self.assertIn('timeout 2000ms', script)
        self.assertIn('meta length < 28', script)
        self.assertIn('arp operation != { request, reply }', script)
        self.assertIn('arp saddr ip 0.0.0.0 arp operation != request', script)
        self.assertIn('ether type arp jump inspect_eth0', script)
        self.assertNotIn('jump inspect_eth1', script)
        self.assertNotIn('ip saddr', script)
        self.assertIn('ether saddr 02:00:00:00:10:03 arp saddr ether 02:00:00:00:10:03 arp saddr ip 10.10.0.3', script)

    def test_grants_bound_by_lease_and_heartbeat_and_ignore_expired_wrong_vlan(self):
        policy = effective(arp_inspection_lab('/rootfs')['nodes'][1])
        script, count = authorization_script(policy, [binding(until=102.25)], 100)
        self.assertEqual(count, 1)
        self.assertIn(MAC + ' . ' + MAC + ' . 10.10.0.100 timeout 250ms', script)
        self.assertIn(MAC + ' . ' + MAC + ' . 0.0.0.0 timeout 250ms', script)
        script, count = authorization_script(policy, [binding()], 100)
        self.assertIn('timeout 2000ms', script)
        for bad in (binding(until=99), binding(vlan=20), binding(port='eth1')):
            script, count = authorization_script(policy, [bad], 100)
            self.assertEqual(count, 0)
            self.assertNotIn('add element', script)
            self.assertIn('flush set', script)

    def test_conflicts_do_not_authorize_either_dynamic_owner_or_override_static(self):
        policy = effective(arp_inspection_lab('/rootfs')['nodes'][1])
        script, count = authorization_script(policy, [binding(), binding(port='eth2', mac='02:00:00:00:10:99')], 100)
        self.assertEqual(count, 0)
        self.assertNotIn('add element', script)
        for entry in (binding(address='10.10.0.3'), binding(mac='02:00:00:00:10:03')):
            self.assertEqual(authorization_script(policy, [entry], 100)[1], 0)

    def test_dynamic_elements_and_counters_are_volatile_but_policy_changes_are_drift(self):
        first, second = raw(), raw([{'elem': {'val': 'example', 'expires': 400}}])
        self.assertEqual(fingerprint(first), fingerprint(second))
        second['nftables'][0]['set']['timeout'] = 20000
        self.assertNotEqual(fingerprint(first), fingerprint(second))
        second = copy.deepcopy(first); second['nftables'][1]['rule']['expr'][-1] = {'accept': None}
        self.assertNotEqual(fingerprint(first), fingerprint(second))

    def test_refresh_checks_both_policies_before_atomic_grant_update(self):
        from network_labs.appliances.firewall import fingerprint as base
        arp, snoop = raw(), {'nftables': []}
        config = {'arp_inspection': effective(arp_inspection_lab('/rootfs')['nodes'][1]),
                  'arp_fingerprint': fingerprint(arp), 'snoop_fingerprint': base(snoop)}
        answers = [subprocess.CompletedProcess([], 0, json.dumps(arp), ''),
                   subprocess.CompletedProcess([], 0, json.dumps(snoop), ''), subprocess.CompletedProcess([], 0, '', '')]
        with patch('network_labs.appliances.arp_inspection.subprocess.run', side_effect=answers) as run, \
             patch('network_labs.appliances.arp_inspection.time.monotonic', return_value=100):
            status = refresh(config, [binding()], 100)
        self.assertEqual(status['dynamic_bindings'], 1)
        self.assertEqual(run.call_count, 3)
        self.assertIn('flush set', run.call_args.kwargs['input'])
        self.assertIn('add element', run.call_args.kwargs['input'])
        self.assertIsNotNone(run.call_args.kwargs['preexec_fn'])
        with patch('network_labs.appliances.arp_inspection.subprocess.run', side_effect=answers[:2]) as run:
            with self.assertRaises(RuntimeError):
                refresh({**config, 'arp_fingerprint': 'tampered'}, [binding()], 100)
            self.assertEqual(run.call_count, 2)

    def test_dhcp_header_checksum_source_identifier_and_udp_checksum_validation(self):
        good = frame(5)
        self.assertIsNotNone(decode(good))
        bad = bytearray(good); bad[22] ^= 1
        self.assertIsNone(decode(bad, checksum_offloaded=True))
        bad = bytearray(good); bad[40:42] = b'\x00\x01'
        self.assertIsNone(decode(bad))
        self.assertIsNotNone(decode(bad, checksum_offloaded=True))
        valid = bytearray(good)
        udp = bytes(valid[34:])
        pseudo = bytes(valid[26:34]) + struct.pack('!BBH', 0, 17, len(udp))
        struct.pack_into('!H', valid, 40, (~checksum(pseudo + udp) & 65535) or 65535)
        self.assertIsNotNone(decode(valid))
        # Header remains valid but server identifier no longer matches IP source.
        wrong = bytearray(good); wrong[29] = 3; wrong[24:26] = b'\0\0'
        struct.pack_into('!H', wrong, 24, ~checksum(bytes(wrong[14:34])) & 65535)
        self.assertIsNone(decode(wrong))


def arp_frame(source_mac='02:00:00:00:10:03', sender_mac=None, sender_ip='10.10.0.2',
              target_ip='10.10.0.100', target_mac='00:00:00:00:00:00',
              destination='ff:ff:ff:ff:ff:ff', operation=1):
    import ipaddress
    hw = lambda value: bytes.fromhex(value.replace(':', ''))
    return hw(destination) + hw(source_mac) + b'\x08\x06' + struct.pack('!HHBBH6s4s6s4s',
        1, 0x0800, 6, 4, operation, hw(sender_mac or source_mac), ipaddress.IPv4Address(sender_ip).packed,
        hw(target_mac), ipaddress.IPv4Address(target_ip).packed)
