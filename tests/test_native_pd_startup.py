"""Kea must not launch while its required link-local address is tentative."""
import json
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
from network_labs.appliances.dhcpv6_pd import wait_server_linklocal,start_server
from network_labs.appliances.examples import dhcpv6_pd_lab
from network_labs.appliances.runtime import RuntimeFailure


class PDStartupTests(unittest.TestCase):
    def manager(self):
        manager=Mock();manager.state={'spec':dhcpv6_pd_lab('/rootfs')};manager.directory=Path('/tmp')
        return manager,manager.state['spec']['nodes'][2]

    def rows(self,**flags):
        return json.dumps([{'addr_info':[{'family':'inet6','scope':'link','local':'fe80::1',**flags}]}])

    def test_waits_for_both_encodings_of_tentative_before_returning_index(self):
        manager,node=self.manager()
        manager.ns.side_effect=[Mock(stdout=self.rows(tentative=True)),Mock(stdout=self.rows(flags=['tentative'])),Mock(stdout=self.rows())]
        with patch('network_labs.appliances.dhcpv6_pd.time.sleep') as sleep:
            self.assertEqual(wait_server_linklocal(manager,node),2);self.assertEqual(sleep.call_count,2)
        manager.crun.assert_not_called()

    def test_failed_dad_and_absent_linklocal_prevent_any_launch(self):
        for rows in (self.rows(dadfailed=True),self.rows(flags=['dadfailed']),'[]'):
            manager,node=self.manager();manager.ns.return_value.stdout=rows
            with patch('network_labs.appliances.dhcpv6_pd.processes',return_value=[]),patch('network_labs.appliances.dhcpv6_pd.time.monotonic',side_effect=[0,0,10]),patch('network_labs.appliances.dhcpv6_pd.time.sleep'):
                with self.assertRaises(RuntimeFailure):start_server(manager,node)
            manager.crun.assert_not_called()

    def test_start_waits_for_actual_udp_socket_after_process_is_visible(self):
        manager,node=self.manager();manager.crun.return_value.returncode=0
        manager.ns.side_effect=[Mock(stdout=''),Mock(stdout='bound UDP/547')]
        with patch('network_labs.appliances.dhcpv6_pd.wait_server_linklocal',return_value=2),patch('network_labs.appliances.dhcpv6_pd.processes',side_effect=[[],['12'],['12']]),patch('network_labs.appliances.dhcpv6_pd.time.sleep') as sleep:
            start_server(manager,node);sleep.assert_called_once_with(.1)
        self.assertEqual(manager.ns.call_count,2)
