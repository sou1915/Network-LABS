"""Source admission: lease authority, port/VLAN scope, modes and DHCP bootstrap."""
import copy
import ipaddress
import json
import struct
import subprocess
import unittest
from unittest.mock import patch

from network_labs.appliances.examples import source_guard_lab
from network_labs.appliances.ios import compile_config
from network_labs.appliances.source_guard import effective, render, authorization_script, refresh, fingerprint, TABLE
from network_labs.appliances.snooping import observer_scope
from network_labs.appliances.snooping_packets import checksum
from network_labs.appliances.spec import validate
from test_native_arp_inspection import binding, raw


def ipv4_frame(source='10.10.0.100', mac='02:00:00:00:10:10', destination='10.10.0.2',
               destination_mac='02:00:00:00:10:02', protocol=1, payload=None, fragments=0):
    if payload is None:
        payload = b'\x08\x00\x00\x00\x12\x34\x00\x01IPSG-test'
        payload = payload[:2] + struct.pack('!H', ~checksum(payload) & 65535) + payload[4:]
    header = bytearray(struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(payload), 1234, fragments, 64,
                                   protocol, 0, ipaddress.IPv4Address(source).packed, ipaddress.IPv4Address(destination).packed))
    struct.pack_into('!H', header, 10, ~checksum(header) & 65535)
    hw = lambda value: bytes.fromhex(value.replace(':', ''))
    return hw(destination_mac) + hw(mac) + b'\x08\x00' + header + payload


class SourceGuardTests(unittest.TestCase):
    def test_policy_rejects_unsupported_scope_and_requires_snooping(self):
        base = source_guard_lab('/rootfs')
        self.assertEqual(validate(copy.deepcopy(base)), base)
        changes = [lambda n: n.update(ip_source_guard=[]),
                   lambda n: n['ip_source_guard'].update(eth9='ip'),
                   lambda n: n['ip_source_guard'].update(eth0='learn'),
                   lambda n: n['ip_source_guard'].update(eth0=[]),
                   lambda n: n['ip_source_guard'].update(eth1='ip'),
                   lambda n: n['dhcp_snooping'].update(enabled=False),
                   lambda n: n.update(startup=['echo untracked'])]
        for change in changes:
            spec = copy.deepcopy(base); change(spec['nodes'][1])
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(spec)
        base['nodes'][1]['arp_inspection']['vlans'] = []
        self.assertIsNotNone(effective(validate(base)['nodes'][1]))  # ARP inspection is independent.

    def test_partial_ios_modes_removal_source_binding_and_atomic_rejection(self):
        spec = source_guard_lab('/rootfs'); original = copy.deepcopy(spec)
        changed = compile_config(spec, 'SW1', 'conf t\ninterface fa0/1\nip verify source\ninterface fa0/3\nno ip verify source port-security\nend')
        self.assertEqual(changed['nodes'][1]['ip_source_guard'], {'eth0': 'ip'})
        self.assertNotEqual(observer_scope(spec['nodes'][1]), observer_scope(changed['nodes'][1]))
        for text in ('interface fa0/2\nip verify source', 'interface fa0/1\nip verify source tracking', 'no ip dhcp snooping'):
            with self.assertRaises(ValueError):
                compile_config(spec, 'SW1', 'conf t\n' + text + '\nend')
        self.assertEqual(spec, original)
        changed = compile_config(spec, 'SW1', 'conf t\nno ip source binding 0200.0000.1003 vlan 10 10.10.0.3 interface fa0/3\nend')
        self.assertFalse(effective(changed['nodes'][1])['bindings'])

    def test_ipv4_only_rules_and_narrow_initial_dhcp_exception(self):
        policy = effective(source_guard_lab('/rootfs')['nodes'][1])
        text = render(policy)
        self.assertIn('ether type ip jump verify_eth0', text)
        self.assertIn('ether saddr . ip saddr @dhcp_eth0', text)
        self.assertIn('ip saddr 0.0.0.0 ip daddr 255.255.255.255', text)
        self.assertIn('ip frag-off & 0x3fff == 0 udp sport 68 udp dport 67', text)
        self.assertIn('@th,64,32 0x01010600 @th,1952,32 0x63825363', text)
        self.assertIn('ether saddr 02:00:00:00:10:03 ip saddr 10.10.0.3', text)
        self.assertNotIn('jump verify_eth1', text)
        self.assertNotIn('ether type arp', text)
        policy['modes']['eth0'] = 'ip'
        text = render(policy)
        self.assertIn('set dhcp_eth0 { type ipv4_addr;', text)
        self.assertIn('ip saddr @dhcp_eth0', text)
        self.assertNotIn('ether saddr . ip saddr @dhcp_eth0', text)

    def test_grants_share_conflict_and_expiry_checks_without_authorizing_zero_source(self):
        policy = effective(source_guard_lab('/rootfs')['nodes'][1])
        text, count = authorization_script(policy, [binding(until=102.25)], 100)
        self.assertEqual(count, 1)
        self.assertIn('02:00:00:00:10:10 . 10.10.0.100 timeout 250ms', text)
        self.assertNotIn(' . 0.0.0.0', text)
        for values in ([binding(until=101)], [binding(vlan=20)], [binding(port='eth1')],
                       [binding(address='10.10.0.3')], [binding(mac='02:00:00:00:10:03')],
                       [binding(), binding(port='eth2', mac='02:00:00:00:10:99')]):
            self.assertEqual(authorization_script(policy, values, 100)[1], 0)
        policy['modes']['eth0'] = 'ip'
        self.assertIn('{ 10.10.0.100 timeout 2000ms }', authorization_script(policy, [binding()], 100)[0])

    def test_refresh_verifies_guard_and_snooping_definitions_before_atomic_update(self):
        from network_labs.appliances.firewall import fingerprint as base
        guard, snoop = raw(), {'nftables': []}
        config = {'ip_source_guard': effective(source_guard_lab('/rootfs')['nodes'][1]),
                  'guard_fingerprint': fingerprint(guard), 'snoop_fingerprint': base(snoop)}
        answers = [subprocess.CompletedProcess([], 0, json.dumps(guard), ''),
                   subprocess.CompletedProcess([], 0, json.dumps(snoop), ''), subprocess.CompletedProcess([], 0, '', '')]
        with patch('network_labs.appliances.arp_inspection.subprocess.run', side_effect=answers) as run, \
             patch('network_labs.appliances.arp_inspection.time.monotonic', return_value=100):
            self.assertEqual(refresh(config, [binding()], 100)['dynamic_bindings'], 1)
        self.assertIn(TABLE, run.call_args_list[0].args[0])
        self.assertIn(TABLE, run.call_args.kwargs['input'])
        self.assertIsNotNone(run.call_args.kwargs['preexec_fn'])
        with patch('network_labs.appliances.arp_inspection.subprocess.run', side_effect=answers[:2]) as run:
            with self.assertRaises(RuntimeError):
                refresh({**config, 'snoop_fingerprint': 'drift'}, [binding()], 100)
            self.assertEqual(run.call_count, 2)

    def test_manifest_static_bindings_are_shared_even_when_arp_inspection_disabled(self):
        spec = source_guard_lab('/rootfs'); node = spec['nodes'][1]
        node['arp_inspection']['vlans'] = []
        policy = effective(validate(spec)['nodes'][1])
        self.assertEqual(policy['bindings'][0]['address'], '10.10.0.3')
        # Same-VLAN owners on unguarded ports must also prevent ambiguity.
        policy['bindings'].append({'port': 'eth1', 'vlan': 10, 'mac': '02:00:00:00:10:02', 'address': '10.10.0.2'})
        self.assertEqual(authorization_script(policy, [binding(address='10.10.0.2')], 100)[1], 0)
