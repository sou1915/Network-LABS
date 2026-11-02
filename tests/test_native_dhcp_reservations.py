"""DHCP reservation identities and evidence must not be confused with lease state."""
import copy
import subprocess
import unittest
from unittest.mock import Mock

from network_labs.appliances.dhcp import server_config, observe_server
from network_labs.appliances.diagnostics import explain_node
from network_labs.appliances.examples import dhcp_reservations_lab
from network_labs.appliances.spec import validate


class ReservationTests(unittest.TestCase):
    def test_inside_and_outside_pool_reservations_use_canonical_unicast_identity(self):
        spec = dhcp_reservations_lab('/rootfs')
        reservation = spec['nodes'][2]['dhcp_server']['reservations'][0]
        reservation.update(mac='0200.0000.1003', address='10.10.0.50')
        checked = validate(spec)
        self.assertEqual(checked['nodes'][2]['dhcp_server']['reservations'],
                         [{'mac': '02:00:00:00:10:03', 'address': '10.10.0.50'}])
        self.assertEqual(reservation['mac'], '0200.0000.1003')  # Caller input was not mutated.

    def test_ambiguous_duplicate_mac_and_address_are_rejected_after_canonicalization(self):
        for other in ({'mac': '0200.0000.1003', 'address': '10.10.0.101'},
                      {'mac': '02:00:00:00:10:99', 'address': '10.10.0.100'}):
            spec = dhcp_reservations_lab('/rootfs')
            spec['nodes'][2]['dhcp_server']['reservations'].append(other)
            with self.subTest(other=other), self.assertRaises(ValueError):
                validate(spec)

    def test_invalid_unusable_reserved_addresses_and_injectable_fields_fail_before_start(self):
        for changes in ({'address': '10.10.0.0'}, {'address': '10.10.0.255'}, {'address': '10.10.0.2'},
                        {'address': '10.20.0.50'}, {'address': '224.0.0.1'}, {'address': 168427620},
                        {'mac': 'ff:ff:ff:ff:ff:ff'}, {'mac': '00:00:00:00:00:00'},
                        {'mac': '02:00:00:00:10:03\noption router 1.2.3.4'}, {'hostname': 'not-supported'}):
            spec = dhcp_reservations_lab('/rootfs')
            spec['nodes'][2]['dhcp_server']['reservations'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate(spec)
        spec = dhcp_reservations_lab('/rootfs')
        spec['nodes'][2]['dhcp_server']['router'] = '10.10.0.1'
        spec['nodes'][2]['dhcp_server']['reservations'][0]['address'] = '10.10.0.1'
        with self.assertRaises(ValueError):
            validate(spec)
        for value in ({}, [None], [{}] * 257):
            spec = dhcp_reservations_lab('/rootfs'); spec['nodes'][2]['dhcp_server']['reservations'] = value
            with self.subTest(value=type(value)), self.assertRaises(ValueError):
                validate(spec)

    def test_generated_busybox_policy_keeps_pool_and_emits_real_static_lease_directive(self):
        node = dhcp_reservations_lab('/rootfs')['nodes'][2]
        text = server_config(node)
        self.assertIn('static_lease 02:00:00:00:10:03 10.10.0.100\n', text)
        self.assertIn('start 10.10.0.100\nend 10.10.0.102\nmax_leases 3\n', text)
        # Old manifests without a reservations field keep their original output.
        node['dhcp_server'].pop('reservations')
        self.assertNotIn('static_lease', server_config(node))

    def test_file_observation_distinguishes_conformity_unavailable_and_changed_without_lease_claim(self):
        node = dhcp_reservations_lab('/rootfs')['nodes'][2]
        for code, output, verified, available in ((0, server_config(node), True, True),
                                                (0, 'changed config', False, True),
                                                (1, '', False, False),
                                                (0, 'x' * 65537, False, False)):
            manager = Mock(); manager.crun.return_value = subprocess.CompletedProcess([], code, output, '')
            observed = observe_server(manager, node)
            self.assertEqual(observed['configuration_verified'], verified)
            self.assertEqual(observed['configuration_available'], available)
            self.assertNotIn('leases', observed)
            self.assertNotIn('running', observed)
            self.assertEqual(manager.crun.call_count, 1)

    def test_explain_keeps_declared_reservations_separate_from_observed_leases(self):
        node = dhcp_reservations_lab('/rootfs')['nodes'][2]
        findings = explain_node(node, {'links': [], 'addresses': [], 'routes': []})
        self.assertTrue(any(f['code'] == 'DHCP_SERVER_CONFIG_UNVERIFIED' for f in findings))
        declaration = next(f for f in findings if f['code'] == 'DHCP_RESERVATIONS')
        self.assertEqual(declaration['evidence']['declared_reservations'], node['dhcp_server']['reservations'])
        self.assertIn('ne sont pas des baux', declaration['message'])
