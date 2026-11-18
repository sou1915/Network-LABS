"""Vendor-syntax configuration (IOS, FortiOS, Junos, RouterOS) of modelled native nodes."""
import os
import unittest
from unittest.mock import patch

from network_labs.appliances import vendor_config
from network_labs.appliances.microvm import firewall_nat_example, router_chain_example, switch_vlan_example
from network_labs.appliances.native_models import port_names
from network_labs.appliances.spec import validate

KERNEL, DISK = '/assets/vmlinux', '/assets/guest.ext4'


def modelled(lab, **models):
    for node in lab['nodes']:
        if node['name'] in models:
            node['model'] = models[node['name']]
    return validate(lab)


def node(lab, name):
    return next(n for n in lab['nodes'] if n['name'] == name)


class PortNameTest(unittest.TestCase):
    def test_vendor_port_names_by_eth_index(self):
        fortigate = {'model': 'fortigate', 'role': 'firewall', 'interfaces': {'eth0': '', 'eth1': ''}}
        self.assertEqual(port_names(fortigate), {'eth0': 'port1', 'eth1': 'port2'})
        mx = {'model': 'juniper-mx204', 'role': 'router', 'interfaces': {'eth0': '', 'eth1': ''}}
        self.assertEqual(port_names(mx)['eth1'], 'xe-0/0/1')
        self.assertEqual(port_names({'role': 'host', 'interfaces': {'eth0': ''}}), {'eth0': 'eth0'})

    def test_dialect_follows_the_brand(self):
        self.assertEqual(vendor_config.dialect({'model': 'cisco-9200l'}), 'ios')
        self.assertEqual(vendor_config.dialect({'model': 'fortigate'}), 'fortios')
        self.assertEqual(vendor_config.dialect({'model': 'juniper-srx'}), 'junos')
        self.assertEqual(vendor_config.dialect({'model': 'mikrotik-ccr'}), 'routeros')
        self.assertEqual(vendor_config.dialect({'model': 'palo-alto'}), 'panos')
        self.assertEqual(vendor_config.dialect({'model': 'arista-7050'}), 'eos')
        self.assertEqual(vendor_config.dialect({'model': 'huawei-s5700'}), 'vrp')
        self.assertIsNone(vendor_config.dialect({'model': 'checkpoint-fw'}))
        self.assertIsNone(vendor_config.dialect({}))


class RoundTripTest(unittest.TestCase):
    def labs(self):
        yield modelled(firewall_nat_example(KERNEL, DISK), FW1='fortigate'), 'FW1'
        yield modelled(firewall_nat_example(KERNEL, DISK), FW1='juniper-srx'), 'FW1'
        yield modelled(router_chain_example(KERNEL, DISK), R1='mikrotik-ccr'), 'R1'
        yield modelled(router_chain_example(KERNEL, DISK), R1='cisco-isr4331'), 'R1'
        yield modelled(switch_vlan_example(KERNEL, DISK), SW1='cisco-9200l'), 'SW1'
        yield modelled(switch_vlan_example(KERNEL, DISK), SW1='huawei-s5700'), 'SW1'
        yield modelled(switch_vlan_example(KERNEL, DISK), SW2='arista-7050'), 'SW2'
        yield modelled(router_chain_example(KERNEL, DISK), R1='arista-7280r'), 'R1'
        yield modelled(router_chain_example(KERNEL, DISK), R1='huawei-ar6120'), 'R1'
        yield modelled(firewall_nat_example(KERNEL, DISK), FW1='palo-alto'), 'FW1'

    def test_rendered_configuration_applies_back_unchanged(self):
        for lab, name in self.labs():
            with self.subTest(model=node(lab, name)['model']):
                text = vendor_config.render(lab, name)
                self.assertEqual(vendor_config.apply(lab, name, text), lab)


class FortiOSTest(unittest.TestCase):
    def setUp(self):
        self.lab = modelled(firewall_nat_example(KERNEL, DISK), FW1='fortigate')

    def test_policy_and_static_route(self):
        text = '\n'.join(['config firewall policy', '    edit 3', '        set name "web-out"', '        set srcintf "port1"',
                          '        set dstintf "port2"', '        set service "HTTPS"', '        set action accept', '    next', 'end',
                          'config router static', '    edit 1', '        set dst 10.50.0.0 255.255.0.0',
                          '        set gateway 198.51.100.254', '    next', 'end'])
        firewall = node(vendor_config.apply(self.lab, 'FW1', text), 'FW1')
        rule = firewall['firewall']['rules'][-1]
        self.assertEqual((rule['name'], rule['in'], rule['out'], rule['protocol'], rule['dport'], rule['action']),
                         ('web-out', 'eth0', 'eth1', 'tcp', 443, 'accept'))
        self.assertEqual(firewall['guest_network']['routes'], [{'network': '10.50.0.0/16', 'gateway': '198.51.100.254'}])

    def test_delete_policy_and_address_change(self):
        text = 'config firewall policy\n    delete 1\nend\nconfig system interface\n    edit "port1"\n' \
               '        set ip 192.0.2.254 255.255.255.0\n    next\nend\n'
        firewall = node(vendor_config.apply(self.lab, 'FW1', text), 'FW1')
        self.assertEqual(len(firewall['firewall']['rules']), len(node(self.lab, 'FW1')['firewall']['rules']) - 1)
        self.assertEqual(firewall['interfaces']['eth0'], '192.0.2.254/24')

    def test_errors_name_their_line(self):
        with self.assertRaisesRegex(ValueError, r'Ligne 2 : edit "port9"[\s\S]*port1, port2'):
            vendor_config.apply(self.lab, 'FW1', 'config system interface\n    edit "port9"\nend')
        with self.assertRaisesRegex(ValueError, 'Ligne 1 '):
            vendor_config.apply(self.lab, 'FW1', 'config vpn ipsec phase1-interface')
        with self.assertRaisesRegex(ValueError, 'end'):
            vendor_config.apply(self.lab, 'FW1', 'config firewall policy\n    edit 1\n    next')
        with self.assertRaisesRegex(ValueError, 'Renommer'):
            vendor_config.apply(self.lab, 'FW1', 'config system global\n    set hostname "OTHER"\nend')


class OtherDialectTest(unittest.TestCase):
    def test_ios_switchport_moves_a_port_to_a_new_vlan(self):
        lab = modelled(switch_vlan_example(KERNEL, DISK), SW1='cisco-9200l')
        result = vendor_config.apply(lab, 'SW1', 'conf t\nvlan 30\ninterface gi1/0/3\n switchport access vlan 30\nend')
        switch = node(result, 'SW1')
        self.assertIn(30, switch['vlans'])
        self.assertEqual(switch['switchports']['eth2'], {'mode': 'access', 'vlan': 30})
        with self.assertRaisesRegex(ValueError, 'switch'):
            vendor_config.apply(lab, 'SW1', 'interface gi1/0/1\n ip address 10.0.0.1 255.255.255.0')

    def test_junos_static_route_and_unsupported_statement(self):
        lab = modelled(router_chain_example(KERNEL, DISK), R1='juniper-mx204')
        result = vendor_config.apply(lab, 'R1', 'configure\nset routing-options static route 10.60.0.0/16 next-hop 203.0.113.2\ncommit')
        self.assertIn({'network': '10.60.0.0/16', 'gateway': '203.0.113.2'}, node(result, 'R1')['guest_network']['routes'])
        with self.assertRaisesRegex(ValueError, 'Ligne 1'):
            vendor_config.apply(lab, 'R1', 'set protocols ospf area 0')

    def test_routeros_add_and_remove_routes(self):
        lab = modelled(router_chain_example(KERNEL, DISK), R1='mikrotik-ccr')
        text = '/ip route add dst-address=10.50.0.0/16 gateway=203.0.113.2\n/ip route remove [find dst-address=198.51.100.0/24]'
        routes = node(vendor_config.apply(lab, 'R1', text), 'R1')['guest_network']['routes']
        self.assertEqual(routes, [{'network': '10.50.0.0/16', 'gateway': '203.0.113.2'}])

    def test_generic_nodes_have_no_vendor_configuration(self):
        lab = router_chain_example(KERNEL, DISK)
        with self.assertRaisesRegex(ValueError, 'formulaire'):
            vendor_config.render(lab, 'R1')


class NewDialectTest(unittest.TestCase):
    def test_vrp_vlan_batch_and_access_port(self):
        lab = modelled(switch_vlan_example(KERNEL, DISK), SW1='huawei-s5700')
        text = 'system-view\nvlan batch 30 to 31\ninterface GE0/0/3\n port default vlan 30\nquit\nreturn'
        switch = node(vendor_config.apply(lab, 'SW1', text), 'SW1')
        self.assertTrue({30, 31} <= set(switch['vlans']))
        self.assertEqual(switch['switchports']['eth2'], {'mode': 'access', 'vlan': 30})

    def test_eos_prefix_length_address_and_route(self):
        lab = modelled(router_chain_example(KERNEL, DISK), R1='arista-7280r')
        result = node(vendor_config.apply(lab, 'R1', 'interface Ethernet1\n ip address 192.0.2.254/24\n'
                                          'ip route 10.70.0.0/16 203.0.113.2'), 'R1')
        self.assertEqual(result['interfaces']['eth0'], '192.0.2.254/24')
        self.assertIn({'network': '10.70.0.0/16', 'gateway': '203.0.113.2'}, result['guest_network']['routes'])

    def test_panos_zones_rules_and_split_static_route(self):
        lab = modelled(firewall_nat_example(KERNEL, DISK), FW1='palo-alto')
        text = '\n'.join(['set zone trust network layer3 ethernet1/1', 'set zone untrust network layer3 ethernet1/2',
                          'set rulebase security rules web from trust to untrust source any destination any '
                          'application any service service-https action allow',
                          'set network virtual-router default routing-table ip static-route corp destination 10.50.0.0/16',
                          'set network virtual-router default routing-table ip static-route corp nexthop ip-address 198.51.100.254'])
        firewall = node(vendor_config.apply(lab, 'FW1', text), 'FW1')
        rule = firewall['firewall']['rules'][-1]
        self.assertEqual((rule['in'], rule['out'], rule['protocol'], rule['dport'], rule['action']), ('eth0', 'eth1', 'tcp', 443, 'accept'))
        self.assertEqual(firewall['guest_network']['routes'], [{'network': '10.50.0.0/16', 'gateway': '198.51.100.254'}])
        with self.assertRaisesRegex(ValueError, 'incomplète'):
            vendor_config.apply(lab, 'FW1', 'set network virtual-router default routing-table ip static-route x destination 10.9.0.0/16')
        with self.assertRaisesRegex(ValueError, 'application'):
            vendor_config.apply(lab, 'FW1', 'set rulebase security rules r application web-browsing')


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class VendorConsoleGUITest(unittest.TestCase):
    def test_console_shows_and_applies_vendor_configuration(self):
        import tkinter as tk
        from network_labs.__main__ import App
        root = tk.Tk()
        try:
            with patch('subprocess.Popen', side_effect=AssertionError('unexpected launch')):
                window = App(root).open_native_lab()
                window.load_spec(modelled(firewall_nat_example(KERNEL, DISK), FW1='fortigate'))
                window.choose_node('FW1')
                window.load_config(force=True)
                root.update()
                self.assertTrue(window.vendor_frame.winfo_manager())
                self.assertIn('edit "port1"', window.vendor_text.get('1.0', 'end'))
                self.assertEqual(window.port_table.item('eth0', 'text'), 'port1 (eth0)')
                window.vendor_text.delete('1.0', 'end')
                window.vendor_text.insert('1.0', 'config system interface\n edit "port1"\n set ip 192.0.2.9/24\n next\nend\n')
                self.assertTrue(window.apply_vendor_config())
                self.assertEqual(node(window.manifest(), 'FW1')['interfaces']['eth0'], '192.0.2.9/24')
                window.vendor_text.delete('1.0', 'end')
                window.vendor_text.insert('1.0', 'config system dns\nend\n')
                self.assertFalse(window.apply_vendor_config())
                self.assertIn('Ligne 1', window.vendor_message.get())
                window.load_spec(router_chain_example(KERNEL, DISK))
                window.choose_node('R1')
                window.load_config(force=True)
                root.update()
                self.assertFalse(window.vendor_frame.winfo_manager())
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()


class FortiOSWorkflowTest(unittest.TestCase):
    """The FortiOS-style web pages send these blocks: policy NAT and Virtual IPs."""
    def setUp(self):
        self.lab = modelled(firewall_nat_example(KERNEL, DISK), FW1='fortigate')

    def test_policy_nat_follows_the_policy(self):
        block = ('config firewall policy\n edit 3\n set name "web-out"\n set srcintf "port1"\n set dstintf "port2"\n'
                 ' set srcaddr "192.0.2.0/24"\n set service "HTTPS"\n set action accept\n set nat enable\n next\nend')
        lab = vendor_config.apply(self.lab, 'FW1', block)
        nat = {r['name']: r for r in node(lab, 'FW1')['firewall']['nat']}
        entry = nat['web-out-nat']
        self.assertEqual((entry['type'], entry['out'], entry['source']), ('masquerade', 'eth1', '192.0.2.0/24'))
        self.assertIn('set nat enable', vendor_config.render(lab, 'FW1'))
        renamed = vendor_config.apply(lab, 'FW1', 'config firewall policy\n edit 3\n set name "web"\n next\nend')
        self.assertEqual({r['name'] for r in node(renamed, 'FW1')['firewall']['nat']} & {'web-nat', 'web-out-nat'}, {'web-nat'})
        off = vendor_config.apply(lab, 'FW1', 'config firewall policy\n edit 3\n set nat disable\n next\nend')
        self.assertNotIn('web-out-nat', {r['name'] for r in node(off, 'FW1')['firewall']['nat']})
        gone = vendor_config.apply(lab, 'FW1', 'config firewall policy\n delete 3\nend')
        self.assertNotIn('web-out-nat', {r['name'] for r in node(gone, 'FW1')['firewall']['nat']})
        with self.assertRaisesRegex(ValueError, 'sortie'):
            vendor_config.apply(self.lab, 'FW1', 'config firewall policy\n edit 4\n set name "x"\n set nat enable\n next\nend')

    def test_virtual_ip_with_port_forwarding(self):
        block = ('config firewall vip\n edit "web-in"\n set extip 198.51.100.1\n set mappedip "192.0.2.20"\n set extintf "port2"\n'
                 ' set portforward enable\n set protocol tcp\n set extport 8443\n set mappedport 443\n next\nend')
        lab = vendor_config.apply(self.lab, 'FW1', block)
        vip = next(r for r in node(lab, 'FW1')['firewall']['nat'] if r['name'] == 'web-in')
        self.assertEqual((vip['in'], vip['destination'], vip['to'], vip['protocol'], vip['dport'], vip['to_port']),
                         ('eth1', '198.51.100.1/32', '192.0.2.20', 'tcp', 8443, 443))
        text = vendor_config.render(lab, 'FW1')
        self.assertEqual(vendor_config.render(vendor_config.apply(lab, 'FW1', text), 'FW1'), text)
        lab = vendor_config.apply(lab, 'FW1', 'config firewall vip\n delete "web-in"\nend')
        self.assertNotIn('web-in', {r['name'] for r in node(lab, 'FW1')['firewall']['nat']})
        with self.assertRaisesRegex(ValueError, 'traduction source'):
            vendor_config.apply(self.lab, 'FW1', 'config firewall vip\n edit "hide-inside"\n set extip 198.51.100.1\n next\nend')


class FortiOSDhcpTest(unittest.TestCase):
    BLOCK = ('config system dhcp server\n edit 1\n set interface "port1"\n set default-gateway 192.0.2.1\n set netmask 255.255.255.0\n'
             ' set dns-server1 192.0.2.53\n set lease-time 900\n config ip-range\n edit 1\n set start-ip 192.0.2.100\n'
             ' set end-ip 192.0.2.120\n next\n end\n next\nend')

    def setUp(self):
        self.lab = modelled(firewall_nat_example(KERNEL, DISK), FW1='fortigate')

    def test_dhcp_server_round_trip_and_delete(self):
        lab = vendor_config.apply(self.lab, 'FW1', self.BLOCK)
        server = node(lab, 'FW1')['dhcp_server']
        self.assertEqual((server['interface'], server['start'], server['end'], server['router'], server['dns'], server['lease_seconds']),
                         ('eth0', '192.0.2.100', '192.0.2.120', '192.0.2.1', ['192.0.2.53'], 900))
        text = vendor_config.render(lab, 'FW1')
        self.assertIn('config ip-range', text)
        self.assertEqual(vendor_config.render(vendor_config.apply(lab, 'FW1', text), 'FW1'), text)
        self.assertIsNone(node(vendor_config.apply(lab, 'FW1', 'config system dhcp server\n delete 1\nend'), 'FW1')['dhcp_server'])

    def test_dhcp_server_errors(self):
        with self.assertRaisesRegex(ValueError, 'edit 1'):
            vendor_config.apply(self.lab, 'FW1', self.BLOCK.replace('edit 1\n set interface', 'edit 2\n set interface'))
        with self.assertRaisesRegex(ValueError, 'ip-range'):
            vendor_config.apply(self.lab, 'FW1', 'config system dhcp server\n edit 1\n set interface "port1"\n next\nend')
        with self.assertRaises(ValueError):  # the pool must sit in the port's subnet, outside its address
            vendor_config.apply(self.lab, 'FW1', self.BLOCK.replace('192.0.2.100', '10.0.0.1').replace('192.0.2.120', '10.0.0.9'))


class IOSRouterFeaturesTest(unittest.TestCase):
    def test_subinterfaces(self):
        from network_labs.appliances.microvm import router_on_a_stick_example
        lab = modelled(router_on_a_stick_example(KERNEL, DISK), R1='cisco-isr4331')
        block = 'interface gi0/0/0.30\n encapsulation dot1Q 30\n ip address 203.0.113.1 255.255.255.0'
        result = node(vendor_config.apply(lab, 'R1', block), 'R1')
        self.assertEqual(result['subinterfaces']['eth0.30'], {'parent': 'eth0', 'vlan': 30, 'address': '203.0.113.1/24'})
        added = vendor_config.apply(lab, 'R1', 'interface gi0/0/0.30\n encapsulation dot1Q 30\n ip address 203.0.113.1 255.255.255.0')
        gone = vendor_config.apply(added, 'R1', 'no interface gi0/0/0.20')
        self.assertNotIn('eth0.20', node(gone, 'R1')['subinterfaces'])
        with self.assertRaisesRegex(ValueError, 'two interfaces'):  # a micro-VM router keeps two interfaces
            vendor_config.apply(lab, 'R1', 'no interface gi0/0/0.20\nno interface gi0/0/0.10')
        with self.assertRaisesRegex(ValueError, 'Sous-interface'):
            vendor_config.apply(lab, 'R1', 'interface gi0/0/0.20\n switchport mode access')

    def test_dhcp_pool(self):
        from network_labs.appliances.microvm import dhcp_example
        lab = modelled(dhcp_example(KERNEL, DISK), R1='cisco-isr4331')
        text = vendor_config.render(lab, 'R1')
        self.assertIn('ip dhcp excluded-address 192.0.2.1 192.0.2.99', text)
        self.assertEqual(vendor_config.render(vendor_config.apply(lab, 'R1', text), 'R1'), text)
        bare = vendor_config.apply(lab, 'R1', 'no ip dhcp pool LAN')
        self.assertIsNone(node(bare, 'R1')['dhcp_server'])
        # Without exclusions the pool skips only the router's own address.
        server = node(vendor_config.apply(bare, 'R1', 'ip dhcp pool LAN\n network 192.0.2.0 255.255.255.0\n default-router 192.0.2.1\n'
                                                 ' lease 0 1 0'), 'R1')['dhcp_server']
        self.assertEqual((server['start'], server['end'], server['lease_seconds']), ('192.0.2.2', '192.0.2.254', 3600))
        kept = node(vendor_config.apply(lab, 'R1', 'ip dhcp pool LAN\n dns-server 192.0.2.53'), 'R1')['dhcp_server']
        self.assertEqual((kept['start'], kept['end'], kept['dns']), ('192.0.2.100', '192.0.2.120', ['192.0.2.53']))
        with self.assertRaisesRegex(ValueError, 'réseau'):
            vendor_config.apply(bare, 'R1', 'ip dhcp pool LAN\n network 10.0.0.0 255.0.0.0')
