"""Recovery rejects invalid policy/drift before PID removal or service launch."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from network_labs.appliances.examples import syslog_tcp_lab
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.syslog_recover import recover,_dead


class SyslogRecoverTests(unittest.TestCase):
    def test_running_disk_sender_and_conformity_are_required_before_mutations(self):
        spec=syslog_tcp_lab('/rootfs',forward=True,disk_queue=True)
        for fault in ('stopped','pending','unknown','memory','drift'):
            state={'phase':'running','spec':spec};name='PC2'
            if fault=='stopped':state['phase']='stopped'
            if fault=='pending':state['pending_spec']=spec
            if fault=='unknown':name='missing'
            if fault=='memory':state['spec']=syslog_tcp_lab('/rootfs',forward=True)
            manager=Mock();manager.read.return_value=state
            with self.subTest(fault=fault),patch('network_labs.appliances.management.observe',return_value={'configuration_verified':False}),self.assertRaises((RuntimeFailure,ValueError)):
                recover(manager,name)
            manager.crun.assert_not_called()

    def test_failed_or_ambiguous_process_census_never_authorizes_cleanup(self):
        node={'name':'PC2'}
        for code,output in ((1,''),(0,'garbage'),(0,'1:2:3\n4:5:6')):
            manager=Mock();manager.crun.return_value=SimpleNamespace(returncode=code,stdout=output,stderr='')
            with self.subTest(code=code,output=output),self.assertRaises(RuntimeFailure):_dead(manager,node)
            self.assertEqual(manager.crun.call_count,1)
