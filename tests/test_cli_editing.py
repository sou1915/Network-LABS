import unittest
from network_labs.engine import demo
from network_labs.cli import Session

class EditingTests(unittest.TestCase):
    def test_abbreviations_and_arguments_preserved(self):
        lab=demo(); cli=Session(lab,'SW1')
        for line in ['en','conf t','hostname t','int g0/1','sw mo acc','sw acc vl 10','desc run','no shut','end']:
            result=cli.execute(line)
            self.assertFalse(result.startswith('%'),(line,result))
        self.assertEqual(lab.nodes['SW1'].hostname,'t')
        self.assertEqual(lab.nodes['SW1'].ports['gi0/1'].description,'run')
        self.assertIn('connected',cli.execute('sh int status'))
        self.assertIn('Access VLAN: 10',cli.execute('sh int g0/1 sw'))

    def test_pipe_filters(self):
        cli=Session(demo(),'SW1'); cli.execute('enable')
        self.assertEqual(cli.execute('show run | include ^hostname'),'hostname SW1')
        self.assertNotIn('hostname',cli.execute('show run | exclude hostname'))
        self.assertTrue(cli.execute('show run | begin interface gi0/3').startswith('interface gi0/3'))

    def test_context_help_completion_and_ambiguous_incomplete(self):
        cli=Session(demo(),'SW1')
        cli.execute('enable'); cli.execute('conf t'); cli.execute('int gi0/1')
        self.assertIn('switchport trunk',cli.execute('switchport trunk ?'))
        self.assertNotIn('dns-server',cli.execute('?'))
        self.assertEqual(cli.completion_candidates('sw mo tr'),['switchport mode trunk'])
        self.assertIn('Incomplete',cli.execute('switchport mode'))
        cli.execute('end')
        self.assertIn('Ambiguous',cli.execute('show i'))
        self.assertIn('Invalid',Session(demo(),'SW1').execute('end'))
