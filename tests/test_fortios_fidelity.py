"""Native policy sequence, objects and atomic web blocks affect real model results."""
import unittest
from network_labs.engine import Lab,Node
from network_labs.vendor_cli import console_session
from network_labs.cli import Session
from network_labs.firewall import ordered_rules
from network_labs.device_config import apply_native_commands
from network_labs.text_lab import export_lab,parse_lab
from network_labs.web_api import DeviceAPI,Conflict
from test_web_api import FakeApp

def lab_fixture():
    lab=Lab()
    for n in (Node('PC1','PC',address='192.168.10.10/24'),Node('PC2','PC',address='192.168.10.20/24'),Node('FW1','Switch',profile='fortigate')):lab.add(n)
    lab.connect('PC1','FW1');lab.connect('FW1','PC2')
    return lab

def policy(number,action='accept',source='all'):
    return ['config firewall policy','edit '+str(number),'set name "Rule '+str(number)+'"','set srcintf any','set dstintf any','set srcaddr '+source,'set dstaddr all','set schedule always','set service PING','set action '+action,'next','end']

class FortiOSFidelityTests(unittest.TestCase):
    def run_commands(self,console,commands):
        for command in commands:
            result=console.execute(command);self.assertFalse(result.startswith('%'),(command,result))

    def test_native_creation_sequence_and_move_change_first_matching_rule(self):
        lab=lab_fixture();c=console_session(lab,'FW1')
        self.run_commands(c,policy(50,'deny')+policy(10))
        self.assertEqual([r['id'] for r in ordered_rules(lab.nodes['FW1'])],[50,10])
        self.assertFalse(lab.ping('PC1','192.168.10.20')[0])
        self.run_commands(c,['config firewall policy','move 10 before 50','end'])
        self.assertTrue(lab.ping('PC1','192.168.10.20')[0])
        self.run_commands(c,['config firewall policy','move 10 after 50','end'])
        self.assertFalse(lab.ping('PC1','192.168.10.20')[0])

    def test_edit_retains_position_unset_and_auto_id(self):
        lab=lab_fixture();c=console_session(lab,'FW1')
        self.run_commands(c,policy(50)+policy(10))
        self.run_commands(c,['config firewall policy','edit 50','set comments "quoted text"','unset name','next','end'])
        self.assertEqual([r['id'] for r in ordered_rules(lab.nodes['FW1'])],[50,10])
        text=c.execute('show firewall policy');self.assertIn('set comments "quoted text"',text)
        self.assertNotIn('set name "Rule 50"',text)
        self.run_commands(c,policy(0))
        self.assertEqual([r['id'] for r in ordered_rules(lab.nodes['FW1'])],[50,10,1])

    def test_address_edit_recompiles_references_and_delete_checks_usage(self):
        lab=lab_fixture();c=console_session(lab,'FW1')
        self.run_commands(c,['config firewall address','edit "Client source"','set subnet 192.168.10.10 255.255.255.255','next','end'])
        self.run_commands(c,policy(10,source='"Client source"'))
        self.assertTrue(lab.ping('PC1','192.168.10.20')[0])
        self.run_commands(c,['config firewall address','edit "Client source"','set subnet 192.168.10.99 255.255.255.255','next','end'])
        self.assertFalse(lab.ping('PC1','192.168.10.20')[0])
        c.execute('config firewall address');before=lab.dumps()
        self.assertTrue(c.execute('delete "Client source"').startswith('%'));self.assertEqual(lab.dumps(),before)
        c.execute('end')
        self.run_commands(c,['config firewall policy','delete 10','end','config firewall address','delete "Client source"','end'])
        self.assertFalse(lab.nodes['FW1'].vendor['fortios_addresses'])

    def test_show_native_blocks_roundtrip_without_canonical_field_names(self):
        lab=lab_fixture();c=console_session(lab,'FW1');self.run_commands(c,policy(50,'deny')+policy(10))
        shown=c.execute('show firewall policy')
        self.assertTrue(shown.startswith('config firewall policy\n'));self.assertTrue(shown.endswith('\nend'))
        self.assertNotIn('set protocol',shown);self.assertNotIn('set target',shown)
        restored=lab_fixture();apply_native_commands(restored,'FW1',shown.splitlines())
        self.assertEqual([r['id'] for r in ordered_rules(restored.nodes['FW1'])],[50,10])
        self.assertFalse(restored.ping('PC1','192.168.10.20')[0])

    def test_json_and_canonical_text_preserve_sequence(self):
        lab=lab_fixture();apply_native_commands(lab,'FW1',policy(50,'deny')+policy(10))
        for restored in (Lab.loads(lab.dumps()),parse_lab(export_lab(lab)).lab):
            self.assertEqual([r['id'] for r in ordered_rules(restored.nodes['FW1'])],[50,10])
            self.assertFalse(restored.ping('PC1','192.168.10.20')[0])

    def test_web_native_blocks_are_atomic_preserve_references_and_check_revision(self):
        app=FakeApp();app.lab=lab_fixture();api=DeviceAPI(app);node=app.lab.nodes['FW1'];port=node.ports['gi0/1']
        state=api.snapshot('FW1');before=app.lab.dumps()
        with self.assertRaises(ValueError):api.dispatch('native',{'node':'FW1','revision':state['revision'],'commands':policy(10)+['config firewall policy','move 10 before 999','end']})
        self.assertEqual(app.lab.dumps(),before)
        updated=api.dispatch('native',{'node':'FW1','revision':state['revision'],'commands':policy(10)})
        self.assertIs(app.lab.nodes['FW1'],node);self.assertIs(node.ports['gi0/1'],port)
        with self.assertRaises(Conflict):api.dispatch('native',{'node':'FW1','revision':state['revision'],'commands':policy(20)})
        self.assertNotEqual(updated['revision'],state['revision'])

    def test_invalid_operations_and_incomplete_blocks_do_not_modify_project(self):
        lab=lab_fixture();apply_native_commands(lab,'FW1',policy(10));before=lab.dumps()
        for commands in (['config firewall policy','move 10 before 10','end'],['config firewall policy','edit 10','set nat enable','next','end'],['config firewall address','edit all','set subnet 1.1.1.1 255.255.255.255','end']):
            with self.assertRaises(ValueError):apply_native_commands(lab,'FW1',commands)
            self.assertEqual(lab.dumps(),before)

    def test_canonical_change_does_not_leave_stale_native_policy(self):
        lab=lab_fixture();apply_native_commands(lab,'FW1',policy(10));Session(lab,'FW1').execute('firewall rule 10 deny any any')
        shown=console_session(lab,'FW1').execute('show firewall policy')
        self.assertIn('sans objets FortiOS',shown);self.assertNotIn('set action accept',shown)
        self.assertFalse(lab.ping('PC1','192.168.10.20')[0])
