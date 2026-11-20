"""Port security and BPDU guard on switch micro-VMs, typed as on IOS. SW1 has PC1 on Fa0/1, PC2 on Fa0/2 and PC3 on
Fa0/3: a port whose secure address is not its PC's goes err-disabled (violation shutdown) or keeps that PC out
(restrict, protect); sticky learns the first PC; « shutdown » then « no shutdown » brings an err-disabled port back."""
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console, port_guard, topology_edit
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.runtime import guest_mac
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project

STICKY = ['en', 'conf t', 'int fa0/1', 'switchport mode access', 'switchport port-security', 'switchport port-security mac-address sticky',
          'end']
WRONG_MAC = ['en', 'conf t', 'int fa0/2', 'switchport mode access', 'switchport port-security',
             'switchport port-security mac-address 0200.0000.0001', 'end']
RESTRICT = ['en', 'conf t', 'int fa0/3', 'switchport mode access', 'switchport port-security',
            'switchport port-security violation restrict', 'switchport port-security mac-address 0200.0000.0003', 'end']


def lab(kernel='/k', disk='/d'):
    spec = blank_project('port-security')
    spec = topology_edit.add_microvm_node(spec, name='SW1', role='switch', kernel=kernel, disk=disk, ports=4, model='cisco-2960')
    for index in range(1, 4):
        spec = topology_edit.add_microvm_node(spec, name=f'PC{index}', role='host', kernel=kernel, disk=disk, ports=1,
                                              addresses=f'192.168.1.{index * 10}/24')
        spec = topology_edit.connect(spec, (f'PC{index}', 'eth0'), ('SW1', f'eth{index - 1}'))
    return validate(spec)


def cisco(name):
    return port_guard.cisco(guest_mac(name, 'eth0'))


class PortSecurityTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': lab()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))

    def type(self, name, lines):
        console = guest_console.Console('port-security', name, lambda _: self.lab)
        return [console.line(line) for line in lines]

    def node(self):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == 'SW1')

    def test_typed_lines_make_the_policy_and_the_guard_arguments(self):
        self.type('SW1', STICKY + WRONG_MAC + RESTRICT)
        self.assertEqual(port_guard.policy(self.node())['eth2'], {'secure': True, 'maximum': 1, 'violation': 'restrict',
                                                                   'bpduguard': False, 'macs': ['0200.0000.0003'], 'sticky': False})
        self.assertEqual(port_guard.arguments(self.node()), ['eth0/1/s/y/n/0/-', 'eth1/1/s/n/n/0/020000000001',
                                                             'eth2/1/r/n/n/0/020000000003'])

    def test_a_wrong_address_err_disables_the_port_and_sticky_learns_the_first(self):
        self.type('SW1', STICKY + WRONG_MAC)
        self.assertIn('0 packets received', self.type('PC2', ['ping 192.168.1.10'])[0])
        self.assertIn('4 packets received', self.type('PC1', ['ping 192.168.1.30'])[0])  # Fa0/1 learned PC1: no violation
        status = self.type('SW1', ['en', 'sh int status'])[-1]
        self.assertRegex(status, r'Fa0/2 +err-disabled')
        detail = self.type('SW1', ['en', 'sh port-security int fa0/2'])[-1]
        self.assertIn('Port Status                : Secure-shutdown', detail)
        self.assertIn(f'Last Source Address:Vlan   : {cisco("PC2")}:1', detail)
        table = self.type('SW1', ['en', 'sh port-security address'])[-1]
        self.assertRegex(table, rf'1 +{cisco("PC1")} +SecureSticky +Fa0/1')
        self.assertRegex(self.type('SW1', ['en', 'sh port-security'])[-1], r'Fa0/2 +1 +1 +1 +Shutdown')

    def test_restrict_keeps_the_host_out_without_shutting_the_port(self):
        self.type('SW1', RESTRICT)
        self.assertIn('0 packets received', self.type('PC1', ['ping 192.168.1.30'])[0])
        self.assertRegex(self.type('SW1', ['en', 'sh int status'])[-1], r'Fa0/3 +connected')
        self.assertRegex(self.type('SW1', ['en', 'sh port-security'])[-1], r'Fa0/3 +1 +1 +1 +Restrict')

    def test_the_right_address_lets_it_in(self):
        self.type('SW1', ['en', 'conf t', 'int fa0/2', 'switchport port-security',
                          f'switchport port-security mac-address {cisco("PC2")}', 'end'])
        self.assertIn('4 packets received', self.type('PC2', ['ping 192.168.1.10'])[0])

    def test_bpdu_guard_err_disables_a_port_facing_a_switch_that_runs_stp(self):
        spec = blank_project('bpdu')
        for name in ('SW1', 'SW2'):
            spec = topology_edit.add_microvm_node(spec, name=name, role='switch', kernel='/k', disk='/d', ports=3, model='cisco-2960')
        self.box['spec'] = validate(topology_edit.connect(spec, ('SW1', 'eth0'), ('SW2', 'eth0')))
        self.type('SW1', ['en', 'conf t', 'int fa0/1', 'spanning-tree bpduguard enable', 'end'])
        self.assertRegex(self.type('SW1', ['en', 'sh int status'])[-1], r'Fa0/1 +connected')  # SW2 sends no BPDU without STP
        self.type('SW2', ['en', 'conf t', 'spanning-tree vlan 1', 'end'])
        self.assertRegex(self.type('SW1', ['en', 'sh int status'])[-1], r'Fa0/1 +err-disabled')

    def test_ios_refusals(self):
        replies = self.type('SW1', ['en', 'conf t', 'int fa0/4', 'switchport mode trunk', 'switchport port-security',
                                    'switchport mode access',
                                    'switchport port-security maximum 9', 'switchport port-security mac-address 0200.0000.0001',
                                    'switchport port-security mac-address 0200.0000.0002', 'switchport port-security maximum 2',
                                    'switchport port-security mac-address 0200.0000.0002', 'switchport port-security maximum 1', 'end'])
        self.assertIn('Command rejected: FastEthernet0/4 is a dynamic port.', replies[4])
        self.assertIn('de 1 à 8', replies[6])
        self.assertIn('has reached maximum limit', replies[8])
        self.assertEqual(replies[9:11], ['', ''])
        self.assertIn('Maximum is less than number of currently secured mac-addresses', replies[11])


GUARD = '''== eth1
state err-disabled
reason psecure-violation
violations 3
last 0225b006cc00
macs 020000000001:s
== eth0
state secure
reason -
violations 0
last -
macs 02a8d6ae6600:k
'''


class PortGuardGuestTest(unittest.TestCase):
    def node(self):
        box = {'spec': lab()}
        draft = DraftLab(lambda: box['spec'], lambda spec: box.update(spec=validate(spec)))
        console = guest_console.Console('port-security', 'SW1', lambda _: draft)
        for line in STICKY + WRONG_MAC:
            console.line(line)
        return next(n for n in box['spec']['nodes'] if n['name'] == 'SW1')

    def test_the_guard_state_reads_as_ios_shows_it(self):
        states = port_guard.parse(GUARD)
        self.assertEqual(states['eth1'], {'state': 'err-disabled', 'reason': 'psecure-violation', 'violations': 3,
                                          'last': '0225.b006.cc00', 'macs': [('0200.0000.0001', 's')]})
        self.assertIn('Port Status                : Secure-shutdown', port_guard.interface(self.node(), 'eth1', states))
        self.assertRegex(port_guard.addresses(self.node(), states), r'1 +02a8\.d6ae\.6600 +SecureSticky +Fa0/1')

    def test_boot_starts_the_guard_and_recovery_clears_the_port(self):
        from network_labs.appliances import guest_startup
        node = self.node()
        calls = []
        with patch.object(guest_startup, 'query', side_effect=lambda s, o, **k: calls.append((o, k.get('guard') or k.get('interface'))) or
                          {'forwarding': '0\n'}.get(o, '')), patch.object(guest_startup, 'check_switch'):
            guest_startup.apply('/socket', node)
        self.assertIn(('port-guard-start', ['eth0/1/s/y/n/0/-', 'eth1/1/s/n/n/0/020000000001']), calls)
        shut = dict(node, shutdown=['eth1'])
        calls.clear()
        record = lambda s, o, **k: calls.append((o, k.get('guard') or k.get('interface'))) or ''
        with patch.object(guest_startup, 'query', side_effect=record), patch.object(guest_startup, 'check_switch'):
            guest_startup.change_switch('/socket', shut, node)  # « no shutdown » after « shutdown »
        self.assertEqual(calls[0], ('port-guard-clear', 'eth1'))
        self.assertIn(('link', 'eth1'), calls)
        self.assertEqual(calls[-1][0], 'port-guard-start')

    def test_the_readback_accepts_an_err_disabled_port_down(self):
        from network_labs.appliances import guest_startup
        node = self.node()
        text = ''.join(f'{i + 2}: eth{i}: <BROADCAST{",UP,LOWER_UP" if i != 1 else ""}>\n' for i in range(4))
        text += '6: br0: <BROADCAST,UP,LOWER_UP>\n'
        replies = {'bridge-ports': 'eth0\neth1\neth2\neth3\n', 'addresses': text, 'forwarding': '0\n',
                   'bridge-stp-show': 'bridge stp_state 0\n', 'port-guard-show': GUARD}
        with patch.object(guest_startup, 'query', side_effect=lambda s, o, **k: replies[o]):
            guest_startup.check_switch('/socket', node)
            with patch.dict(replies, {'port-guard-show': GUARD.replace('err-disabled', 'secure')}), self.assertRaises(ValueError):
                guest_startup.check_switch('/socket', node)  # down without a reason: refused



class AgentGuardParseTest(unittest.TestCase):
    """PORT_GUARD_START splits its policies with strtok: parsing one must leave that split where it was (run 875 guarded
    only the first port of three)."""

    def test_parsing_a_policy_keeps_the_request_split(self):
        import subprocess
        import tempfile
        from pathlib import Path
        agent = Path('network_labs/appliances/guest/agent.c').resolve()
        harness = (f'#define main agent_main\n#include "{agent}"\n#undef main\n'
                   'int main(void) { char line[] = "eth0/1/s/y/n/0/- eth1/1/s/n/n/0/020000000001 eth2/1/r/n/n/0/-";\n'
                   '  struct guard g; int count = 0;\n'
                   '  for (char *item = strtok(line, " "); item; item = strtok(NULL, " ")) count += guard_parse(item, &g);\n'
                   '  printf("%d\\n", count); return 0; }\n')
        with tempfile.TemporaryDirectory() as folder:
            source, binary = Path(folder) / 'harness.c', Path(folder) / 'harness'
            source.write_text(harness)
            subprocess.run(['gcc', '-Wall', '-Wno-unused-function', '-o', str(binary), str(source)], check=True)
            self.assertEqual(subprocess.run([str(binary)], capture_output=True, text=True, check=True).stdout.strip(), '3')


if __name__ == '__main__':
    unittest.main()
