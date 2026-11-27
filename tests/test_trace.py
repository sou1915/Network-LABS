"""traceroute / tracert: BusyBox probes parsed, three per hop, printed as IOS, Huawei, BusyBox and a Windows PC print them;
the stopped lab's trace from the network model."""
import unittest

from network_labs.appliances import guest_console, trace
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.spec import validate

from tests.test_rip import TYPED, chain

ANSWER = 'traceroute to 10.0.0.9 (10.0.0.9), 2 hops max, 46 byte packets\n 2  10.0.12.2  0.512 ms\n'


def result(*hops):
    """A trace result from hop addresses (None: silent), each probe 0.4 ms."""
    rows = [{'ttl': ttl, 'probes': [{'address': a, 'time_ms': .4 if a else None, 'flag': None}] * 3} for ttl, a in enumerate(hops, 1)]
    return {'destination': '192.168.3.10', 'hops': rows, 'reached': hops[-1] == '192.168.3.10'}


class ProbeTest(unittest.TestCase):
    def test_busybox_lines(self):
        self.assertEqual(trace.probe(0, ANSWER), {'address': '10.0.12.2', 'time_ms': .512, 'flag': None})
        self.assertEqual(trace.probe(0, ' 3  *\n'), {'address': None, 'time_ms': None, 'flag': None})
        self.assertEqual(trace.probe(0, ' 2  10.0.12.2  0.4 ms !H\n')['flag'], '!H')
        self.assertEqual(trace.probe(1, 'traceroute: sendto: Network is unreachable\n')['flag'], '!N')

    def test_three_probes_per_hop_one_when_silent_and_a_stop_after_silent_hops(self):
        sent = []
        path = {1: '192.168.1.1', 2: '10.0.12.2', 3: '192.168.3.10'}

        def send(ttl):
            sent.append(ttl)
            return {'address': path.get(ttl), 'time_ms': 1.0, 'flag': None}
        walked = trace.walk(send, '192.168.3.10')
        self.assertTrue(walked['reached'])
        self.assertEqual(sent, [1, 1, 1, 2, 2, 2, 3, 3, 3])
        sent.clear()
        path = {1: '192.168.1.1'}
        walked = trace.walk(send, '192.168.3.10')
        self.assertEqual((walked['reached'], len(walked['hops'])), (False, 1 + trace.SILENT_STOP))
        self.assertEqual(sent, [1, 1, 1, 2, 3, 4])  # a silent hop costs one probe, not three
        flagged = trace.walk(lambda ttl: {'address': '192.168.1.1', 'time_ms': 1.0, 'flag': '!N'}, '192.168.3.10')
        self.assertEqual((flagged['reached'], len(flagged['hops'])), (False, 1))

    def test_the_guest_request_is_typed_and_bounded(self):
        from network_labs.appliances.guest_control import request
        for ttl in (0, 31, '3', None):
            with self.assertRaisesRegex(ValueError, 'TTL 1..30'):
                request('/nonexistent', 'trace', destination='10.0.0.9', ttl=ttl)
        with self.assertRaisesRegex(ValueError, 'Only trace accepts a TTL'):
            request('/nonexistent', 'ping', destination='10.0.0.9', ttl=2)

    def test_commands_of_each_dialect(self):
        self.assertEqual(trace.parse('ios', 'tr 10.0.0.9'), (True, '10.0.0.9'))
        self.assertEqual(trace.parse('ios', 'traceroute ip 10.0.0.9'), (True, '10.0.0.9'))
        self.assertEqual(trace.parse('ios', 'traceroute serveur'), (True, None))
        self.assertEqual(trace.parse('ios', 'terminal length 0'), (False, None))
        self.assertEqual(trace.parse('vrp', 'tracert 10.0.0.9'), (True, '10.0.0.9'))
        self.assertEqual(trace.parse('host', 'tracert 10.0.0.9'), (True, '10.0.0.9'))
        self.assertEqual(trace.parse('host', 'traceroute -n 10.0.0.9'), (True, '10.0.0.9'))


class TextTest(unittest.TestCase):
    def test_ios(self):
        self.assertEqual(trace.ios_text(result('10.0.12.2', None, '192.168.3.10')),
                         'Type escape sequence to abort.\nTracing the route to 192.168.3.10\nVRF info: (vrf in name/id, vrf out name/id)\n'
                         '  1 10.0.12.2 0 msec 0 msec 0 msec\n  2  *  *  *\n  3 192.168.3.10 0 msec 0 msec 0 msec')

    def test_windows_pc(self):
        self.assertEqual(trace.windows_text(result('192.168.1.1', None, '192.168.3.10')),
                         'Tracing route to 192.168.3.10 over a maximum of 15 hops:\n\n'
                         '  1    <1 ms    <1 ms    <1 ms  192.168.1.1\n'
                         '  2     *        *        *     Request timed out.\n'
                         '  3    <1 ms    <1 ms    <1 ms  192.168.3.10\n\nTrace complete.')

    def test_busybox_and_huawei(self):
        self.assertEqual(trace.busybox_text(result('192.168.1.1', None)).splitlines()[1:],
                         [' 1  192.168.1.1  0.400 ms  0.400 ms  0.400 ms', ' 2  *  *  *'])
        self.assertEqual(trace.vrp_text(result('10.0.12.2')).splitlines()[1], ' 1 10.0.12.2 1 ms  1 ms  1 ms')


class DraftTraceTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': chain()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def type(self, node, *lines):
        console = guest_console.Console('rip-lab', node, lambda name: self.lab)
        return [console.line(line) for line in lines]

    def test_hops_from_the_model_as_routing_is_typed(self):
        silent = self.type('PC1', 'tracert 192.168.3.10')[0]
        self.assertRegex(silent, r'  1 .* ms  192\.168\.1\.1\n')  # R1 answers; nothing knows the way further
        self.assertEqual(silent.count('Request timed out.'), trace.SILENT_STOP)
        for name, lines in TYPED.items():
            self.type(name, *lines)
        found = self.type('PC1', 'tracert 192.168.3.10')[0]
        self.assertRegex(found,
                         r'  1 .* ms  192\.168\.1\.1\n  2 .* ms  10\.0\.12\.2\n  3 .* ms  10\.0\.23\.2\n  4 .* ms  192\.168\.3\.10\n')
        self.assertRegex(self.type('R1', 'en', 'traceroute 192.168.3.10')[-1], r'\n  1 10\.0\.12\.2 1 msec .*\n  2 10\.0\.23\.2 ')
        # An ACL on R2 that drops what comes from PC1's LAN: R2 and everything after it stay silent.
        self.type('R2', 'en', 'conf t', 'access-list 1 deny 192.168.1.0 0.0.0.255', 'access-list 1 permit any', 'int g0/0/0',
                  'ip access-group 1 in', 'end')
        dropped = self.type('PC1', 'traceroute 192.168.3.10')[0].splitlines()
        self.assertEqual(dropped[1:], [' 1  192.168.1.1  1.000 ms  1.000 ms  1.000 ms', ' 2  *  *  *', ' 3  *  *  *', ' 4  *  *  *'])


if __name__ == '__main__':
    unittest.main()
