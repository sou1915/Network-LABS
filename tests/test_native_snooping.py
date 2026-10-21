"""Wire-derived correlations, trust boundaries, bounded state and explicit unknowns."""
import copy
import ipaddress
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.examples import dhcp_snooping_lab, campus
from network_labs.appliances.ios import compile_config
from network_labs.appliances.snooping import TABLE, effective, observe, render
from network_labs.appliances.snooping_packets import Bindings, decode
from network_labs.appliances.spec import validate

MAC = '02:00:00:00:10:10'


def frame(kind=3, mac=MAC, xid=123, requested='10.10.0.100', server='10.10.0.2', lease=120,
          sport=None, ciaddr='0.0.0.0', yiaddr='10.10.0.100', giaddr='0.0.0.0', options_extra=b''):
    server_packet = kind in (5, 6)
    hw = bytes.fromhex(mac.replace(':', ''))
    boot = bytearray(240)
    boot[:3] = bytes((2 if server_packet else 1, 1, 6))
    struct.pack_into('!I', boot, 4, xid)
    boot[12:16] = ipaddress.IPv4Address(ciaddr).packed
    boot[16:20] = ipaddress.IPv4Address(yiaddr if server_packet else '0.0.0.0').packed
    boot[24:28] = ipaddress.IPv4Address(giaddr).packed
    boot[28:34] = hw; boot[236:240] = b'\x63\x82\x53\x63'
    options = bytes((53, 1, kind))
    if requested is not None and not server_packet:
        options += bytes((50, 4)) + ipaddress.IPv4Address(requested).packed
    if server is not None:
        options += bytes((54, 4)) + ipaddress.IPv4Address(server).packed
    if server_packet and lease is not None:
        options += bytes((51, 4)) + struct.pack('!I', lease)
    body = boot + options + options_extra + b'\xff'
    udp = struct.pack('!HHHH', sport if sport is not None else 67 if server_packet else 68, 68 if server_packet else 67, len(body) + 8, 0) + body
    ip = bytearray(struct.pack('!BBHHHBBH4s4s', 0x45, 0, len(udp) + 20, 1, 0, 64, 17, 0,
                               ipaddress.IPv4Address(server if server_packet and server else '0.0.0.0').packed,
                               b'\xff' * 4))
    words = struct.unpack('!10H', ip); value = sum(words)
    while value >> 16:
        value = (value & 65535) + (value >> 16)
    struct.pack_into('!H', ip, 10, ~value & 65535)
    return b'\xff' * 6 + (bytes.fromhex('020000001002') if server_packet else hw) + b'\x08\x00' + ip + udp


def table():
    return Bindings({'eth0': 10, 'eth1': 10, 'eth2': 10}, ['eth1'])


class SnoopTests(unittest.TestCase):
    def test_only_matching_request_and_trusted_ack_create_expiring_binding(self):
        t = table()
        t.feed('eth1', frame(5), 0)
        self.assertFalse(t.bindings)
        t.feed('eth0', frame(), 1)
        t.feed('eth2', frame(5), 2)
        self.assertFalse(t.bindings)
        t.feed('eth1', frame(5, xid=999), 3)
        self.assertFalse(t.bindings)
        t.feed('eth1', frame(5), 4)
        entry, = t.snapshot(5)['bindings']
        self.assertEqual((entry['mac'], entry['address'], entry['port'], entry['vlan']), (MAC, '10.10.0.100', 'eth0', 10))
        self.assertEqual(entry['remaining_seconds'], 119)
        self.assertFalse(t.snapshot(124)['bindings'])

    def test_server_address_lease_request_address_and_ambiguous_port_are_checked(self):
        for reply in (frame(5, server='10.10.0.3'), frame(5, yiaddr='10.10.0.101'), frame(5, lease=0), frame(5, lease=None)):
            t = table(); t.feed('eth0', frame(), 0); t.feed('eth1', reply, 1)
            self.assertFalse(t.bindings)
        t = table(); t.feed('eth0', frame(), 0); t.feed('eth2', frame(), 1); t.feed('eth1', frame(5), 2)
        self.assertFalse(t.bindings)
        t = table(); t.feed('eth0', frame(), 0); t.feed('eth1', frame(5), 61)
        self.assertFalse(t.bindings)

    def test_release_nak_renewal_capacity_and_untrusted_acks_do_not_forge_state(self):
        t = table(); t.limit = 1
        t.feed('eth0', frame(), 0); t.feed('eth1', frame(5), 1)
        t.feed('eth0', frame(xid=124, requested=None, ciaddr='10.10.0.100'), 2)
        t.feed('eth1', frame(5, xid=124, lease=240), 3)
        self.assertEqual(t.snapshot(4)['bindings'][0]['remaining_seconds'], 239)
        t.feed('eth2', frame(7, ciaddr='10.10.0.100'), 5)
        self.assertTrue(t.bindings)
        t.feed('eth0', frame(7, ciaddr='10.10.0.100'), 6)
        self.assertFalse(t.bindings)
        t.feed('eth0', frame(xid=125), 7); t.feed('eth1', frame(5, xid=125), 8)
        t.feed('eth0', frame(xid=126), 9); t.feed('eth1', frame(6, xid=126), 10)
        self.assertFalse(t.bindings)
        t = table(); t.limit = 1
        t.feed('eth0', frame(), 0)
        t.feed('eth2', frame(mac='02:00:00:00:10:11', xid=124), 1)
        self.assertEqual(len(t.pending), 1)
        self.assertEqual(t.events['capacity_refusals'], 1)

    def test_wire_parser_refuses_relay_tags_fragments_malformed_options_and_wrong_source(self):
        self.assertEqual(decode(frame())['kind'], 3)
        for bad in (frame(giaddr='10.10.0.1'), frame(options_extra=b'\x35\x01\x03'), frame(options_extra=b'\x34\x01\x01'), frame()[:-4], frame(5, sport=68)):
            self.assertIsNone(decode(bad))
        tagged = frame()[:12] + b'\x81\x00\x00\x0a' + frame()[12:]
        self.assertIsNone(decode(tagged))
        frag = bytearray(frame()); frag[20:22] = b'\x20\x00'
        self.assertIsNone(decode(frag))
        spoof = bytearray(frame()); spoof[6] = 4
        self.assertIsNone(decode(spoof))
        for size in range(0, len(frame()), 13):
            self.assertIsNone(decode(frame()[:size]))

    def test_ios_and_manifest_fail_before_mutation_for_unsupported_scope(self):
        spec = dhcp_snooping_lab('/rootfs'); original = copy.deepcopy(spec)
        configured = compile_config(spec, 'SW1', 'conf t\nno ip dhcp snooping\ninterface fa0/3\nip dhcp snooping trust\nend')
        self.assertFalse(configured['nodes'][1]['dhcp_snooping']['enabled'])
        self.assertIn('eth2', configured['nodes'][1]['dhcp_snooping']['trusted'])
        self.assertEqual(spec, original)
        for command in ('ip dhcp snooping information option', 'ip dhcp snooping vlan 99'):
            with self.assertRaises(ValueError):
                compile_config(spec, 'SW1', 'conf t\n' + command)
        for change in (lambda n: n['dhcp_snooping'].update(trusted=['eth9']),
                       lambda n: n['dhcp_snooping'].update(vlans=[10, 10]),
                       lambda n: n['dhcp_snooping'].update(enabled=1),
                       lambda n: n['switchports']['eth0'].update(mode='trunk'),
                       lambda n: n.update(startup=[['/bin/true']])):
            candidate = copy.deepcopy(spec); change(candidate['nodes'][1])
            with self.assertRaises(ValueError):
                validate(candidate)
        other = campus('/rootfs'); other['nodes'][4]['dhcp_snooping'] = {'enabled': True, 'vlans': [10]}
        with self.assertRaisesRegex(ValueError, 'access ports'):
            validate(other)

    def test_filter_scopes_untrusted_server_bootreply_fragments_and_tags(self):
        policy = effective(dhcp_snooping_lab('/rootfs')['nodes'][1])
        script = render(policy)
        self.assertIn('udp sport 67 counter drop', script)
        self.assertIn('@th,64,8 2 counter drop', script)
        self.assertIn('ip frag-off & 0x3fff', script)
        self.assertIn('hook prerouting priority -310', script)
        self.assertNotIn('server:eth1', script)
        self.assertNotIn('flush ruleset', script)
        self.assertIn('delete table bridge ' + TABLE, render(None, replace=True))

    def test_unavailable_or_stale_observer_is_not_an_empty_healthy_table(self):
        node = dhcp_snooping_lab('/rootfs')['nodes'][1]
        with tempfile.TemporaryDirectory() as folder:
            manager = SimpleNamespace(directory=Path(folder), state={}, read=lambda: {})
            with patch('network_labs.appliances.snooping.read_table', return_value=None):
                result = observe(manager, 1, node)
            self.assertFalse(result['policy_verified'])
            self.assertFalse(result['observer_available'])
            self.assertIsNone(result['bindings'])

    def test_token_heartbeat_expiry_and_policy_drift_gate_reported_bindings(self):
        from network_labs.appliances.firewall import fingerprint
        node = dhcp_snooping_lab('/rootfs')['nodes'][1]
        raw = {'nftables': [{'table': {'family': 'bridge', 'name': TABLE}}]}
        with tempfile.TemporaryDirectory() as folder:
            state = {'snooping_fingerprints': {'SW1': fingerprint(raw)},
                     'snooping_workers': {'SW1': {'token': 'owned', 'pid': 123, 'starttime': '1'}}}
            manager = SimpleNamespace(directory=Path(folder), state=state, read=lambda: state)
            snapshot = {'token': 'owned', 'status': 'ready', 'observed_monotonic': 99, 'capture_drops': 0,
                        'events': {}, 'bindings': [{'until': 102, 'mac': MAC}, {'until': 90, 'mac': 'expired'}]}
            path = Path(folder) / 'SW1.snooping.json'
            with patch('network_labs.appliances.snooping.read_table', return_value=raw), \
                 patch('network_labs.appliances.snooping.alive', return_value=True), \
                 patch('network_labs.appliances.snooping.time.monotonic', return_value=100):
                path.write_text(json.dumps(snapshot))
                observed = observe(manager, 1, node)
                self.assertTrue(observed['observer_available'])
                self.assertEqual(len(observed['bindings']), 1)
                self.assertEqual(observed['bindings'][0]['remaining_seconds'], 2)
                for change in ({'token': 'stale-worker'}, {'observed_monotonic': 95}, {'observed_monotonic': 101}, {'status': 'failed'}):
                    path.write_text(json.dumps({**snapshot, **change}))
                    self.assertIsNone(observe(manager, 1, node)['bindings'])
                path.write_text(json.dumps(snapshot))
                state['snooping_fingerprints']['SW1'] = 'modified'
                self.assertIsNone(observe(manager, 1, node)['bindings'])
