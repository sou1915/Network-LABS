"""Packet replay: pcap parsing, hop order and direction, NAT detection, the bridge request and the GUI replay."""
import os
from pathlib import Path
import struct
import tempfile
import unittest

from network_labs.appliances import packet_trace


def frame(source, destination, kind, vlan=None, ident=7, seq=1):
    ip = bytes([0x45, 0, 0, 28, 0, 0, 0, 0, 64, 1, 0, 0]) + bytes(map(int, source.split('.'))) + bytes(map(int, destination.split('.')))
    icmp = bytes([8 if kind == 'request' else 0, 0, 0, 0]) + struct.pack('!HH', ident, seq)
    tag = struct.pack('!HH', 0x8100, vlan) if vlan else b''
    return b'\x02' * 6 + b'\x04' * 6 + tag + b'\x08\x00' + ip + icmp


def pcap(path, frames):
    data = struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 2048, 1)
    for index, raw in enumerate(frames):
        data += struct.pack('<IIII', 100, 1000 * index, len(raw), len(raw)) + raw
    Path(path).write_bytes(data)


class ParseTest(unittest.TestCase):
    def test_tagged_and_untagged_echo_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.pcap'
            pcap(path, [frame('192.0.2.11', '192.0.2.14', 'request', vlan=10), frame('192.0.2.14', '192.0.2.11', 'reply'),
                        b'\x00' * 10])
            frames = packet_trace.parse_icmp(path)
        self.assertEqual([(f['source'], f['destination'], f['type'], f['vlan']) for f in frames],
                         [('192.0.2.11', '192.0.2.14', 'request', 10), ('192.0.2.14', '192.0.2.11', 'reply', None)])
        self.assertAlmostEqual(frames[1]['time'] - frames[0]['time'], 0.001)

    def test_hops_are_ordered_and_one_per_crossing(self):
        links = [[['FW1', 'eth0'], ['VM2', 'eth0']], [['FW1', 'eth1'], ['VM3', 'eth0']]]
        request = {'time': 1.0, 'vlan': None, 'source': '192.0.2.20', 'destination': '198.51.100.20', 'type': 'request', 'id': 1, 'seq': 1}
        outside = dict(request, time=1.0002, source='198.51.100.1')
        hops = packet_trace.hops(links, {0: [request, dict(request)], 1: [outside]})
        self.assertEqual([(h['link'], h['source'], h['time_ms']) for h in hops], [(0, '192.0.2.20', 0.0), (1, '198.51.100.1', 0.2)])


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class ReplayTest(unittest.TestCase):
    def test_steps_follow_the_walk_and_flag_nat(self):
        import tkinter as tk
        from network_labs.__main__ import App
        from network_labs.appliances.microvm import firewall_nat_example
        from network_labs.appliances.ui_bridge import public_topology, validate_request
        root = tk.Tk()
        try:
            window = App(root).open_native_lab()
            lab = firewall_nat_example('/k', '/d')
            window.load_spec(lab)
            l0, l1 = lab['links']
            hops = [{'link': 0, 'endpoints': l0, 'time_ms': 0, 'vlan': None, 'source': '192.0.2.20', 'destination': '198.51.100.20',
                     'type': 'request'},
                    {'link': 1, 'endpoints': l1, 'time_ms': .2, 'vlan': None, 'source': '198.51.100.1', 'destination': '198.51.100.20',
                     'type': 'request'},
                    {'link': 1, 'endpoints': l1, 'time_ms': .4, 'vlan': None, 'source': '198.51.100.20', 'destination': '198.51.100.1',
                     'type': 'reply'}]
            data = {'source': 'VM2', 'destination': '198.51.100.20', 'answered': True, 'hops': hops}
            steps = window.trace_steps(data)
            self.assertEqual([(s['start'][0], s['end'][0], s['nat']) for s in steps],
                             [('VM2', 'FW1', False), ('FW1', 'VM3', True), ('VM3', 'FW1', False)])
            window.apply_response({'ok': True, 'action': 'trace', 'lab': lab['name'], 'topology': public_topology(lab), 'data': data},
                                  {'action': 'trace', 'lab': lab['name'], 'node': 'VM2'})
            root.update()
            self.assertTrue(window.canvas.find_withtag('trace'))
            self.assertIn('198.51.100.1 → 198.51.100.20 (NAT)', window.output.get('1.0', 'end'))
            envelope = {'id': '0' * 32, 'owner_uid': os.geteuid(), 'action': 'trace', 'target': lab['name'], 'lab': lab['name'],
                        'node': 'VM2', 'destination': '198.51.100.20'}
            self.assertEqual(validate_request(envelope)['action'], 'trace')
            with self.assertRaises(ValueError):
                validate_request(dict(envelope, destination='VM3'))
        finally:
            root.destroy()
