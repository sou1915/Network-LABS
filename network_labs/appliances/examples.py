"""Headless reference topology, deliberately using only bundled BusyBox tools."""
from pathlib import Path

from .spec import validate


def campus(rootfs):
    rootfs = str(Path(rootfs).resolve())
    def host(name, address, gateway='', **extra):
        return {'name': name, 'runtime': 'oci', 'rootfs': rootfs, 'interfaces': {'eth0': address},
                'gateway': gateway, **extra}
    def switch(name, ports):
        return {'name': name, 'runtime': 'oci', 'role': 'switch', 'rootfs': rootfs,
                'dialect': 'ios-basic', 'vlans': [1, 10, 20],
                'interfaces': {p: '' for p in ports}, 'switchports': ports,
                'interface_aliases': {'fa0/' + str(i + 1): port for i, port in enumerate(ports)}}
    access10 = {'mode': 'access', 'vlan': 10}; access20 = {'mode': 'access', 'vlan': 20}
    trunk = {'mode': 'trunk', 'native_vlan': 1, 'allowed': [10, 20]}
    return validate({'version': 2, 'name': 'campus-lan', 'budget_mib': 2048, 'reserve_mib': 512,
                     'nodes': [
                         host('PC1', '', dhcp_clients=['eth0']),
                         host('PC2', '10.20.20.20/24', '10.20.20.1'),
                         host('PC3', '10.10.10.30/24', '10.10.10.1'),
                         host('PC4', '10.20.20.40/24', '10.20.20.1'),
                         switch('SW1', {'eth0': access10, 'eth1': access20, 'eth2': trunk, 'eth3': trunk}),
                         switch('SW2', {'eth0': access10, 'eth1': access20, 'eth2': trunk, 'eth3': access10}),
                         {'name': 'R1', 'runtime': 'oci', 'role': 'router', 'rootfs': rootfs,
                          'dialect': 'ios-basic', 'interfaces': {'eth0': ''}, 'interface_aliases': {'fa0/0': 'eth0'},
                          'subinterfaces': {'eth0.10': {'parent': 'eth0', 'vlan': 10, 'address': '10.10.10.1/24'},
                                            'eth0.20': {'parent': 'eth0', 'vlan': 20, 'address': '10.20.20.1/24'}}},
                         host('SRV1', '10.10.10.2/24', '10.10.10.1',
                              dhcp_server={'interface': 'eth0', 'start': '10.10.10.100', 'end': '10.10.10.150',
                                           'router': '10.10.10.1', 'lease_seconds': 3600}),
                     ], 'links': [
                         [['PC1', 'eth0'], ['SW1', 'eth0']], [['PC2', 'eth0'], ['SW1', 'eth1']],
                         [['PC3', 'eth0'], ['SW2', 'eth0']], [['PC4', 'eth0'], ['SW2', 'eth1']],
                         [['SW1', 'eth2'], ['SW2', 'eth2']], [['R1', 'eth0'], ['SW1', 'eth3']],
                         [['SRV1', 'eth0'], ['SW2', 'eth3']],
                     ]})


def firewall_lab(rootfs):
    """Three real nodes; the WAN server deliberately has no route to the LAN."""
    return validate({'version': 2, 'name': 'firewall-lan', 'nodes': [
        {'name': 'PC1', 'runtime': 'oci', 'rootfs': str(rootfs),
         'interfaces': {'eth0': '10.42.0.10/24'}, 'gateway': '10.42.0.1'},
        {'name': 'FW1', 'runtime': 'oci', 'role': 'firewall', 'rootfs': str(rootfs),
         'interfaces': {'eth0': '10.42.0.1/24', 'eth1': '198.51.100.1/24'},
         'firewall': {'default': 'drop', 'stateful': True, 'rules': [
             {'name': 'lan-http', 'action': 'accept', 'in': 'eth0', 'out': 'eth1', 'protocol': 'tcp', 'dport': 80},
             {'name': 'lan-ping', 'action': 'accept', 'in': 'eth0', 'out': 'eth1', 'protocol': 'icmp'},
             {'name': 'published-http', 'action': 'accept', 'in': 'eth1', 'out': 'eth0',
              'destination': '10.42.0.10/32', 'protocol': 'tcp', 'dport': 80}],
             'nat': [
                 {'name': 'lan-masq', 'type': 'masquerade', 'out': 'eth1', 'source': '10.42.0.0/24'},
                 {'name': 'publish', 'type': 'dnat', 'in': 'eth1', 'destination': '198.51.100.1/32',
                  'protocol': 'tcp', 'dport': 8080, 'to': '10.42.0.10', 'to_port': 80}]}},
        {'name': 'SRV1', 'runtime': 'oci', 'rootfs': str(rootfs), 'interfaces': {'eth0': '198.51.100.10/24'}},
    ], 'links': [[['PC1', 'eth0'], ['FW1', 'eth0']], [['FW1', 'eth1'], ['SRV1', 'eth0']]]})


def enterprise(rootfs):
    """20 nodes: 12 PCs, 4 switches, router, firewall, DHCP and WAN servers."""
    rootfs = str(Path(rootfs).resolve())
    base = campus(rootfs)
    router = next(n for n in base['nodes'] if n['name'] == 'R1')
    router['interfaces']['eth1'] = '172.31.255.2/30'
    router['interface_aliases']['fa0/1'] = 'eth1'
    router['gateway'] = '172.31.255.1'
    dhcp = next(n for n in base['nodes'] if n['name'] == 'SRV1')
    dhcp['name'] = 'DHCP1'
    nodes, links = [], []
    for switch_index in range(4):
        sw = f'SW{switch_index + 1}'
        ports = {}
        for port_index in range(3):
            number = switch_index * 3 + port_index + 1
            vlan = 10 if number % 2 else 20
            interface = f'eth{port_index}'
            nodes.append({'name': f'PC{number}', 'runtime': 'oci', 'rootfs': rootfs,
                          'interfaces': {'eth0': '' if number == 1 else f'10.{vlan}.{vlan}.{10 + number}/24'},
                          **({'dhcp_clients': ['eth0']} if number == 1 else {'gateway': f'10.{vlan}.{vlan}.1'})})
            ports[interface] = {'mode': 'access', 'vlan': vlan}
            links.append([[f'PC{number}', 'eth0'], [sw, interface]])
        # A chain without L2 cycles; trunk IDs match on each link.
        ports['eth3'] = {'mode': 'trunk', 'native_vlan': 1, 'allowed': [10, 20]}
        if switch_index < 3:
            ports['eth4'] = {'mode': 'trunk', 'native_vlan': 1, 'allowed': [10, 20]}
            links.append([[sw, 'eth4'], [f'SW{switch_index + 2}', 'eth3']])
        if switch_index == 0:
            links.append([['R1', 'eth0'], [sw, 'eth3']])
        if switch_index == 3:
            ports['eth4'] = {'mode': 'access', 'vlan': 10}
            links.append([['DHCP1', 'eth0'], [sw, 'eth4']])
        nodes.append({'name': sw, 'runtime': 'oci', 'role': 'switch', 'rootfs': rootfs,
                      'dialect': 'ios-basic', 'vlans': [1, 10, 20], 'interfaces': {p: '' for p in ports},
                      'switchports': ports, 'interface_aliases': {f'fa0/{i+1}': p for i, p in enumerate(ports)}})
    firewall = firewall_lab(rootfs)['nodes'][1]
    firewall['interfaces']['eth0'] = '172.31.255.1/30'
    firewall['routes'] = [{'destination': f'10.{v}.{v}.0/24', 'gateway': '172.31.255.2', 'interface': 'eth0'} for v in (10, 20)]
    firewall['firewall']['rules'][2]['destination'] = '10.10.10.2/32'
    firewall['firewall']['nat'] = [
        {'name': f'vlan{v}-masq', 'type': 'masquerade', 'out': 'eth1', 'source': f'10.{v}.{v}.0/24'} for v in (10, 20)] + [
        {'name': 'publish-dhcp-http', 'type': 'dnat', 'in': 'eth1', 'destination': '198.51.100.1/32',
         'protocol': 'tcp', 'dport': 8080, 'to': '10.10.10.2', 'to_port': 80}]
    wan = firewall_lab(rootfs)['nodes'][2]; wan['name'] = 'WAN1'
    nodes += [router, firewall, dhcp, wan]
    links += [[['R1', 'eth1'], ['FW1', 'eth0']], [['FW1', 'eth1'], ['WAN1', 'eth0']]]
    return validate({'version': 2, 'name': 'enterprise-20', 'budget_mib': 2048, 'reserve_mib': 512,
                     'nodes': nodes, 'links': links})


def lacp_lab(rootfs):
    """Four PCs on two VLANs, two switches and one two-member LACP trunk."""
    rootfs = str(Path(rootfs).resolve())
    nodes = []
    for name, address in (('PC1', '192.0.2.10/24'), ('PC2', '198.18.0.10/24'),
                          ('PC3', '192.0.2.20/24'), ('PC4', '198.18.0.20/24')):
        nodes.append({'name': name, 'runtime': 'oci', 'rootfs': rootfs, 'interfaces': {'eth0': address}})
    for number in (1, 2):
        nodes.append({'name': f'SW{number}', 'runtime': 'oci', 'role': 'switch', 'rootfs': rootfs,
                      'dialect': 'ios-basic', 'interfaces': {f'eth{i}': '' for i in range(4)},
                      'interface_aliases': {f'fa0/{i+1}': f'eth{i}' for i in range(4)}, 'vlans': [1, 10, 20],
                      'port_channels': {'bond1': {'members': ['eth2', 'eth3'], 'mode': 'active' if number == 1 else 'passive', 'min_links': 1}},
                      'switchports': {'eth0': {'mode': 'access', 'vlan': 10}, 'eth1': {'mode': 'access', 'vlan': 20},
                                      'bond1': {'mode': 'trunk', 'native_vlan': 1, 'allowed': [10, 20]}}})
    return validate({'version': 2, 'name': 'lacp-lan', 'nodes': nodes, 'links': [
        [['PC1', 'eth0'], ['SW1', 'eth0']], [['PC2', 'eth0'], ['SW1', 'eth1']],
        [['PC3', 'eth0'], ['SW2', 'eth0']], [['PC4', 'eth0'], ['SW2', 'eth1']],
        [['SW1', 'eth2'], ['SW2', 'eth2']], [['SW1', 'eth3'], ['SW2', 'eth3']],
    ]})


def stp_lab(rootfs):
    """Three switches form a triangle; classic STP elects SW1 and blocks a port.

    Lab timers are deliberately shortened within the supported IEEE bounds:
    forward_delay=4, hello_time=1, max_age=6. This remains classic STP, not RSTP.
    """
    rootfs = str(Path(rootfs).resolve())
    nodes, links = [], []
    for number in (1, 2, 3):
        for offset, vlan in ((0, 10), (1, 20)):
            pc = f'PC{(number - 1) * 2 + offset + 1}'
            address = f'192.0.2.{number * 10}/24' if vlan == 10 else f'198.18.0.{number * 10}/24'
            nodes.append({'name': pc, 'runtime': 'oci', 'rootfs': rootfs, 'interfaces': {'eth0': address}})
            links.append([[pc, 'eth0'], [f'SW{number}', f'eth{offset}']])
        nodes.append({'name': f'SW{number}', 'runtime': 'oci', 'role': 'switch', 'rootfs': rootfs,
                      'dialect': 'ios-basic', 'interfaces': {f'eth{i}': '' for i in range(4)},
                      'interface_aliases': {f'fa0/{i+1}': f'eth{i}' for i in range(4)},
                      'vlans': [1, 10, 20],
                      'switchports': {'eth0': {'mode': 'access', 'vlan': 10}, 'eth1': {'mode': 'access', 'vlan': 20},
                                      'eth2': {'mode': 'trunk', 'native_vlan': 1, 'allowed': [10, 20]},
                                      'eth3': {'mode': 'trunk', 'native_vlan': 1, 'allowed': [10, 20]}},
                      'spanning_tree': {'mode': 'stp', 'priority': number * 4096,
                                        'hello_time': 1, 'max_age': 6, 'forward_delay': 4}})
    links += [[['SW1', 'eth2'], ['SW2', 'eth2']], [['SW1', 'eth3'], ['SW3', 'eth2']],
              [['SW2', 'eth3'], ['SW3', 'eth3']]]
    return validate({'version': 2, 'name': 'stp-lan', 'nodes': nodes, 'links': links})


def port_security_lab(rootfs):
    """Static secure access port with stable client identities across restore."""
    from .spec import example
    spec = example(rootfs)
    spec['name'] = 'port-security-lan'
    spec['nodes'][0]['interface_macs'] = {'eth0': '02:00:00:00:01:10'}
    spec['nodes'][2]['interface_macs'] = {'eth0': '02:00:00:00:02:20'}
    switch = spec['nodes'][1]
    switch['dialect'] = 'ios-basic'
    switch['interface_aliases'] = {'fa0/1': 'eth0', 'fa0/2': 'eth1'}
    switch['port_security'] = {'eth0': {'maximum': 1, 'mac_addresses': ['02:00:00:00:01:10'], 'violation': 'restrict'}}
    return validate(spec)


def dhcp_snooping_lab(rootfs):
    """One client, trusted DHCP server and actual rogue server on access VLAN 10."""
    rootfs = str(Path(rootfs).resolve())
    def server(name, address, start, end):
        return {'name': name, 'runtime': 'oci', 'rootfs': rootfs, 'interfaces': {'eth0': address},
                'dhcp_server': {'interface': 'eth0', 'start': start, 'end': end, 'lease_seconds': 120}}
    return validate({'version': 2, 'name': 'dhcp-snooping-lan', 'nodes': [
        {'name': 'PC1', 'runtime': 'oci', 'rootfs': rootfs, 'interfaces': {'eth0': ''},
         'interface_macs': {'eth0': '02:00:00:00:10:10'}, 'dhcp_clients': ['eth0']},
        {'name': 'SW1', 'runtime': 'oci', 'role': 'switch', 'rootfs': rootfs, 'dialect': 'ios-basic',
         'interfaces': {'eth0': '', 'eth1': '', 'eth2': ''}, 'vlans': [10],
         'switchports': {p: {'mode': 'access', 'vlan': 10} for p in ('eth0', 'eth1', 'eth2')},
         'interface_aliases': {'fa0/1': 'eth0', 'fa0/2': 'eth1', 'fa0/3': 'eth2'},
         'dhcp_snooping': {'enabled': True, 'vlans': [10], 'trusted': ['eth1']}},
        server('DHCP1', '10.10.0.2/24', '10.10.0.100', '10.10.0.110'),
        server('ROGUE', '10.10.0.3/24', '10.10.0.200', '10.10.0.210'),
    ], 'links': [[['PC1', 'eth0'], ['SW1', 'eth0']], [['DHCP1', 'eth0'], ['SW1', 'eth1']],
                  [['ROGUE', 'eth0'], ['SW1', 'eth2']]]})


def arp_inspection_lab(rootfs):
    spec = dhcp_snooping_lab(rootfs)
    spec['name'] = 'arp-inspection-lan'
    spec['nodes'][2]['interface_macs'] = {'eth0': '02:00:00:00:10:02'}
    spec['nodes'][3]['interface_macs'] = {'eth0': '02:00:00:00:10:03'}
    spec['nodes'][1]['arp_inspection'] = {'vlans': [10], 'trusted': ['eth1'], 'bindings': [
        {'port': 'eth2', 'vlan': 10, 'mac': '02:00:00:00:10:03', 'address': '10.10.0.3'}]}
    return validate(spec)


def source_guard_lab(rootfs):
    spec = arp_inspection_lab(rootfs)
    spec['name'] = 'source-guard-lan'
    spec['nodes'][1]['ip_source_guard'] = {'eth0': 'ip-mac', 'eth2': 'ip-mac'}
    return validate(spec)


def multicast_lab(rootfs):
    spec = {'version': 2, 'name': 'multicast-lan', 'nodes': [
        {'name': 'SW1', 'runtime': 'oci', 'role': 'switch', 'rootfs': str(rootfs), 'dialect': 'ios-basic',
         'interfaces': {p: '' for p in ('eth0', 'eth1', 'eth2')}, 'vlans': [10],
         'switchports': {p: {'mode': 'access', 'vlan': 10} for p in ('eth0', 'eth1', 'eth2')},
         'interface_aliases': {'fa0/1': 'eth0', 'fa0/2': 'eth1', 'fa0/3': 'eth2'},
         'multicast': {'snooping': True, 'querier': True}},
    ], 'links': []}
    for i, name in enumerate(('TX1', 'RX1', 'PC1')):
        spec['nodes'].append({'name': name, 'runtime': 'oci', 'rootfs': str(rootfs),
                              'interfaces': {'eth0': f'192.0.2.{10 + i}/24'}})
        spec['links'].append([[name, 'eth0'], ['SW1', 'eth' + str(i)]])
    return validate(spec)


def dhcp_reservations_lab(rootfs):
    """Reserve the first pool address before the ordinary client starts."""
    spec = dhcp_snooping_lab(rootfs)
    spec['name'] = 'dhcp-reservations-lan'
    server = spec['nodes'][2]['dhcp_server']
    server.update(end='10.10.0.102', reservations=[{'mac': '02:00:00:00:10:03', 'address': '10.10.0.100'}])
    printer = spec['nodes'][3]
    printer.update(name='PRN1', interfaces={'eth0': ''}, dhcp_server=None,
                   dhcp_clients=['eth0'], interface_macs={'eth0': '02:00:00:00:10:03'})
    spec['links'][2][0][0] = 'PRN1'
    switch = spec['nodes'][1]
    switch['interfaces']['eth3'] = ''
    switch['switchports']['eth3'] = {'mode': 'access', 'vlan': 10}
    switch['interface_aliases']['fa0/4'] = 'eth3'
    spec['nodes'].append({'name': 'PC2', 'runtime': 'oci', 'rootfs': str(rootfs),
                           'interfaces': {'eth0': ''}, 'dhcp_clients': ['eth0'],
                           'interface_macs': {'eth0': '02:00:00:00:10:20'}})
    spec['links'].append([['PC2', 'eth0'], ['SW1', 'eth3']])
    return validate(spec)


def dns_lab(rootfs):
    spec = dhcp_snooping_lab(rootfs)
    spec['name'] = 'dns-lan'
    server = spec['nodes'][2]
    server['name'] = 'DNS1'
    server['dhcp_server']['dns'] = ['10.10.0.2']
    server['dns_server'] = {'interface': 'eth0', 'zone': 'lab.test', 'ttl': 60,
                            'records': {'intranet.lab.test': '10.10.0.20', 'dns.lab.test': '10.10.0.2'}}
    spec['links'][1][0][0] = 'DNS1'
    web = spec['nodes'][3]
    web.update(name='WEB1', interfaces={'eth0': '10.10.0.20/24'}, dhcp_server=None,
               startup=[['/bin/sh', '-c', 'mkdir -p /tmp/www; echo "Network LABS HTTP via DNS" > /tmp/www/index.html; /bin/busybox httpd -p 80 -h /tmp/www']])
    spec['links'][2][0][0] = 'WEB1'
    switch = spec['nodes'][1]
    switch['interfaces']['eth3'] = ''
    switch['switchports']['eth3'] = {'mode': 'access', 'vlan': 10}
    switch['interface_aliases']['fa0/4'] = 'eth3'
    spec['nodes'].append({'name': 'PC2', 'runtime': 'oci', 'rootfs': str(rootfs),
                          'interfaces': {'eth0': '10.10.0.30/24'}, 'resolvers': ['10.10.0.2']})
    spec['links'].append([['PC2', 'eth0'], ['SW1', 'eth3']])
    return validate(spec)


def lldp_lab(rootfs):
    rootfs = str(Path(rootfs).resolve())
    nodes = []
    for name, address in (('PC1', '192.0.2.10/24'), ('PC2', '192.0.2.20/24')):
        nodes.append({'name': name, 'runtime': 'oci', 'rootfs': rootfs,
                      'interfaces': {'eth0': address}, 'lldp': {'ports': ['eth0']}})
    for name in ('SW1', 'SW2'):
        nodes.append({'name': name, 'runtime': 'oci', 'rootfs': rootfs, 'role': 'switch',
                      'interfaces': {'eth0': '', 'eth1': ''}, 'vlans': [10],
                      'switchports': {p: {'mode': 'access', 'vlan': 10} for p in ('eth0', 'eth1')},
                      'lldp': {'ports': ['eth0', 'eth1']}})
    return validate({'version': 2, 'name': 'lldp-lan', 'nodes': nodes, 'links': [
        [['PC1', 'eth0'], ['SW1', 'eth0']], [['SW1', 'eth1'], ['SW2', 'eth1']],
        [['PC2', 'eth0'], ['SW2', 'eth0']]]})


def rstp_lab(rootfs):
    rootfs = str(Path(rootfs).resolve())
    nodes = [{'name': 'PC' + str(i), 'runtime': 'oci', 'rootfs': rootfs,
              'interfaces': {'eth0': f'192.0.2.{i}0/24'}} for i in (1, 2, 3)]
    for i in (1, 2, 3):
        nodes.append({'name': 'SW' + str(i), 'role': 'switch', 'runtime': 'oci', 'rootfs': rootfs,
                      'memory_mib': 128, 'switch_backend': 'ovs', 'interfaces': {'eth0': '', 'eth1': '', 'eth2': ''},
                      'vlans': [10], 'switchports': {p: {'mode': 'access', 'vlan': 10} for p in ('eth0', 'eth1', 'eth2')},
                      'spanning_tree': {'mode': 'rstp', 'priority': i * 4096}})
    links = [[['PC' + str(i), 'eth0'], ['SW' + str(i), 'eth0']] for i in (1, 2, 3)]
    links += [[['SW1', 'eth1'], ['SW2', 'eth1']], [['SW1', 'eth2'], ['SW3', 'eth1']], [['SW2', 'eth2'], ['SW3', 'eth2']]]
    return validate({'version': 2, 'name': 'rstp-lan', 'nodes': nodes, 'links': links})


def svi_lab(rootfs):
    rootfs = str(Path(rootfs).resolve())
    nodes = []
    for name, address, gateway in (('PC1', '192.0.2.10/24', '192.0.2.1'), ('PC2', '192.0.2.20/24', '192.0.2.1'),
                                    ('PC3', '198.51.100.10/24', '198.51.100.1'), ('PC4', '198.51.100.20/24', '198.51.100.1')):
        nodes.append({'name': name, 'runtime': 'oci', 'rootfs': rootfs, 'interfaces': {'eth0': address}, 'gateway': gateway})
    for name in ('SW1', 'SW2'):
        nodes.append({'name': name, 'runtime': 'oci', 'role': 'switch', 'rootfs': rootfs, 'dialect': 'ios-basic',
                      'interfaces': {'eth0': '', 'eth1': '', 'eth2': ''}, 'vlans': [10, 20],
                      'interface_aliases': {'fa0/1': 'eth0', 'fa0/2': 'eth1', 'gi0/1': 'eth2'},
                      'switchports': {'eth0': {'mode': 'access', 'vlan': 10}, 'eth1': {'mode': 'access', 'vlan': 20},
                                      'eth2': {'mode': 'trunk', 'native_vlan': 1, 'allowed': [10, 20]}}})
    nodes[4]['svis'] = {'vlan10': {'vlan': 10, 'address': '192.0.2.1/24'}, 'vlan20': {'vlan': 20, 'address': '198.51.100.1/24'}}
    # Start with gateway management but no inter-VLAN forwarding; enable it
    # explicitly with the supported ip routing CLI command.
    return validate({'version': 2, 'name': 'svi-lan', 'nodes': nodes, 'links': [
        [['PC1', 'eth0'], ['SW1', 'eth0']], [['PC3', 'eth0'], ['SW1', 'eth1']],
        [['PC2', 'eth0'], ['SW2', 'eth0']], [['PC4', 'eth0'], ['SW2', 'eth1']],
        [['SW1', 'eth2'], ['SW2', 'eth2']]]})


def static_routing_lab(rootfs):
    rootfs = str(Path(rootfs).resolve())
    nodes = [
        {'name': 'PC1', 'runtime': 'oci', 'rootfs': rootfs,
         'interfaces': {'eth0': '192.0.2.10/24'}, 'gateway': '192.0.2.1'},
        {'name': 'SW1', 'runtime': 'oci', 'rootfs': rootfs, 'role': 'switch', 'dialect': 'ios-basic',
         'interfaces': {'eth0': '', 'eth1': ''}, 'vlans': [10, 20], 'forwarding': True,
         'switchports': {'eth0': {'mode': 'access', 'vlan': 10}, 'eth1': {'mode': 'access', 'vlan': 20}},
         'svis': {'vlan10': {'vlan': 10, 'address': '192.0.2.1/24'},
                  'vlan20': {'vlan': 20, 'address': '198.18.0.1/29'}}},
        {'name': 'R1', 'runtime': 'oci', 'rootfs': rootfs, 'role': 'router', 'dialect': 'ios-basic',
         'interfaces': {'eth0': '198.18.0.2/29', 'eth1': '203.0.113.1/24'},
         'interface_aliases': {'gi0/0': 'eth0', 'gi0/1': 'eth1'}},
        {'name': 'PC2', 'runtime': 'oci', 'rootfs': rootfs,
         'interfaces': {'eth0': '203.0.113.10/24'}, 'gateway': '203.0.113.1'}]
    # Both transit devices start without a route to the remote LAN.
    return validate({'version': 2, 'name': 'static-routing-lan', 'nodes': nodes, 'links': [
        [['PC1', 'eth0'], ['SW1', 'eth0']], [['SW1', 'eth1'], ['R1', 'eth0']],
        [['R1', 'eth1'], ['PC2', 'eth0']]]})


def dhcp_relay_lab(rootfs):
    rootfs = str(Path(rootfs).resolve())
    nodes = [{'name': 'PC' + str(i), 'runtime': 'oci', 'rootfs': rootfs,
              'interfaces': {'eth0': ''}, 'dhcp_clients': ['eth0'],
              'interface_macs': {'eth0': f'02:00:00:00:20:0{i}'}} for i in (1, 2)]
    nodes.append({'name': 'SW1', 'runtime': 'oci', 'role': 'switch', 'rootfs': rootfs,
                  'interfaces': {'eth0': '', 'eth1': '', 'eth2': ''}, 'vlans': [10, 20], 'forwarding': True,
                  'switchports': {'eth0': {'mode': 'access', 'vlan': 10}, 'eth1': {'mode': 'access', 'vlan': 10},
                                  'eth2': {'mode': 'access', 'vlan': 20}},
                  'svis': {'vlan10': {'vlan': 10, 'address': '192.0.2.1/24'},
                           'vlan20': {'vlan': 20, 'address': '198.51.100.1/24'}},
                  'dialect': 'ios-basic', 'dhcp_relay': {'interface': 'vlan10', 'upstream_interface': 'vlan20', 'server': '198.51.100.10'}})
    nodes.append({'name': 'DHCP1', 'runtime': 'oci', 'rootfs': rootfs,
                  'interfaces': {'eth0': '198.51.100.10/24'},
                  'routes': [{'destination': '192.0.2.0/24', 'gateway': '198.51.100.1', 'interface': 'eth0'}],
                  'dhcp_server': {'interface': 'eth0', 'network': '192.0.2.0/24',
                                  'start': '192.0.2.100', 'end': '192.0.2.110', 'router': '192.0.2.1',
                                  'reservations': [{'mac': '02:00:00:00:20:01', 'address': '192.0.2.100'}]}})
    return validate({'version': 2, 'name': 'dhcp-relay-lan', 'nodes': nodes, 'links': [
        [['PC1', 'eth0'], ['SW1', 'eth0']], [['PC2', 'eth0'], ['SW1', 'eth1']],
        [['DHCP1', 'eth0'], ['SW1', 'eth2']]]})


def dhcp_multi_lab(rootfs):
    spec = dhcp_relay_lab(rootfs)
    spec['name'] = 'dhcp-multi-lan'
    switch, server = spec['nodes'][2:]
    switch['vlans'] = [10, 20, 30]
    switch['switchports']['eth1']['vlan'] = 20
    switch['switchports']['eth2']['vlan'] = 30
    switch['svis']['vlan20']['address'] = '198.18.0.1/24'
    switch['svis']['vlan30'] = {'vlan': 30, 'address': '198.51.100.1/24'}
    switch['dhcp_relay'] = [
        {'interface': name, 'upstream_interface': 'vlan30', 'server': '198.51.100.10'}
        for name in ('vlan10', 'vlan20')]
    first = server.pop('dhcp_server'); first.pop('interface')
    first['dns'] = ['192.0.2.53']
    server['dhcp_pools'] = {'interface': 'eth0', 'pools': [first,
        {'network': '198.18.0.0/24', 'start': '198.18.0.100', 'end': '198.18.0.110',
         'router': '198.18.0.1', 'dns': ['198.18.0.53']}]}
    server['routes'].append({'destination': '198.18.0.0/24', 'gateway': '198.51.100.1', 'interface': 'eth0'})
    return validate(spec)


def ospf_lab(rootfs):
    rootfs = str(Path(rootfs).resolve())
    nodes = [
        {'name': 'PC1', 'runtime': 'oci', 'rootfs': rootfs, 'interfaces': {'eth0': '192.0.2.10/24'}, 'gateway': '192.0.2.1'},
        {'name': 'PC2', 'runtime': 'oci', 'rootfs': rootfs, 'interfaces': {'eth0': '198.51.100.10/24'}, 'gateway': '198.51.100.1'}]
    definitions = [
        ('R1', '1.1.1.1', {'eth0': '10.0.12.1/30', 'eth1': '10.0.13.1/30', 'eth2': '192.0.2.1/24'},
         {'eth0': {'cost': 10}, 'eth1': {'cost': 30}, 'eth2': {'passive': True}}),
        ('R2', '2.2.2.2', {'eth0': '10.0.12.2/30', 'eth1': '10.0.23.1/30', 'eth2': '198.51.100.1/24'},
         {'eth0': {'cost': 10}, 'eth1': {'cost': 10}, 'eth2': {'passive': True}}),
        ('R3', '3.3.3.3', {'eth0': '10.0.13.2/30', 'eth1': '10.0.23.2/30'},
         {'eth0': {'cost': 30}, 'eth1': {'cost': 10}})]
    for name, router_id, interfaces, ports in definitions:
        nodes.append({'name': name, 'runtime': 'oci', 'role': 'router', 'rootfs': rootfs, 'interfaces': interfaces,
                      'forwarding': True, 'dialect': 'ios-basic', 'ospf': {'router_id': router_id, 'interfaces': ports}})
    return validate({'version': 2, 'name': 'ospf-lan', 'nodes': nodes, 'links': [
        [['PC1', 'eth0'], ['R1', 'eth2']], [['PC2', 'eth0'], ['R2', 'eth2']],
        [['R1', 'eth0'], ['R2', 'eth0']], [['R1', 'eth1'], ['R3', 'eth0']],
        [['R2', 'eth1'], ['R3', 'eth1']]]})


def ospf_cli_lab(rootfs):
    spec = ospf_lab(rootfs)
    spec['name'] = 'ospf-cli-lan'
    for node in spec['nodes']:
        node['ospf'] = None
    return validate(spec)


def ospf_broadcast_lab(rootfs):
    rootfs = str(Path(rootfs).resolve())
    nodes = [
        {'name': 'PC1', 'runtime': 'oci', 'rootfs': rootfs, 'interfaces': {'eth0': '192.0.2.10/24'}, 'gateway': '192.0.2.1'},
        {'name': 'PC2', 'runtime': 'oci', 'rootfs': rootfs, 'interfaces': {'eth0': '198.51.100.10/24'}, 'gateway': '198.51.100.1'},
        {'name': 'SW1', 'role': 'switch', 'runtime': 'oci', 'rootfs': rootfs,
         'interfaces': {'eth0': '', 'eth1': '', 'eth2': '', 'eth3': ''},
         'multicast': {'snooping': False}}]
    for number, priority in ((1, 200), (2, 100), (3, 1), (4, 0)):
        interfaces = {'eth0': f'10.0.100.{number}/24'}
        ports = {'eth0': {'network_type': 'broadcast', 'priority': priority}}
        if number in (3, 4):
            interfaces['eth1'] = '192.0.2.1/24' if number == 3 else '198.51.100.1/24'
            ports['eth1'] = {'passive': True}
        nodes.append({'name': f'R{number}', 'runtime': 'oci', 'rootfs': rootfs, 'role': 'router',
                      'interfaces': interfaces, 'forwarding': True, 'dialect': 'ios-basic',
                      'ospf': {'router_id': f'{number}.{number}.{number}.{number}', 'interfaces': ports}})
    links = [[['SW1', f'eth{i-1}'], [f'R{i}', 'eth0']] for i in range(1, 5)]
    links += [[['PC1', 'eth0'], ['R3', 'eth1']], [['PC2', 'eth0'], ['R4', 'eth1']]]
    return validate({'version': 2, 'name': 'ospf-broadcast-lan', 'nodes': nodes, 'links': links})


def ospf_svi_lab(rootfs):
    """A real L3 switch peers through VLAN20 and advertises passive VLAN10."""
    spec = static_routing_lab(rootfs)
    spec['name'] = 'ospf-svi-lan'
    switch, router = spec['nodes'][1:3]
    switch['ospf'] = {'router_id': '1.1.1.1', 'interfaces': {
        'vlan10': {'passive': True}, 'vlan20': {'network_type': 'broadcast'}}}
    router['ospf'] = {'router_id': '2.2.2.2', 'interfaces': {
        'eth0': {'network_type': 'broadcast'}, 'eth1': {'passive': True}}}
    switch['vlans'] = [1, 10, 20]
    switch['switchports']['eth1'] = {'mode': 'trunk', 'native_vlan': 1, 'allowed': [20]}
    spec['nodes'].append({'name': 'SW2', 'role': 'switch', 'runtime': 'oci', 'rootfs': str(Path(rootfs).resolve()),
        'interfaces': {'eth0': '', 'eth1': ''}, 'vlans': [1, 20],
        'switchports': {'eth0': {'mode': 'trunk', 'native_vlan': 1, 'allowed': [20]},
                        'eth1': {'mode': 'access', 'vlan': 20}}})
    spec['links'][1] = [['SW1', 'eth1'], ['SW2', 'eth0']]
    spec['links'].append([['SW2', 'eth1'], ['R1', 'eth0']])
    return validate(spec)


def ospf_dhcp_lab(rootfs):
    """Co-located OSPF and DHCP relay, with an on-link upstream DHCP server."""
    spec = ospf_svi_lab(rootfs)
    spec['name'] = 'ospf-dhcp-lan'
    pc, switch = spec['nodes'][:2]
    pc['interfaces']['eth0'] = ''; pc['gateway'] = None
    pc['dhcp_clients'] = ['eth0']
    pc['interface_macs'] = {'eth0': '02:00:00:00:40:01'}
    switch['dhcp_relay'] = {'interface': 'vlan10', 'upstream_interface': 'vlan20', 'server': '198.18.0.3'}
    access = spec['nodes'][4]
    access['interfaces']['eth2'] = ''
    access['switchports']['eth2'] = {'mode': 'access', 'vlan': 20}
    spec['nodes'].append({'name': 'DHCP1', 'runtime': 'oci', 'rootfs': str(Path(rootfs).resolve()),
        'interfaces': {'eth0': '198.18.0.3/29'},
        'routes': [{'destination': '192.0.2.0/24', 'gateway': '198.18.0.1', 'interface': 'eth0'}],
        'dhcp_pools': {'interface': 'eth0', 'pools': [{'network': '192.0.2.0/24', 'start': '192.0.2.100',
            'end': '192.0.2.110', 'router': '192.0.2.1',
            'reservations': [{'mac': '02:00:00:00:40:01', 'address': '192.0.2.100'}]}]}})
    spec['links'].append([['SW2', 'eth2'], ['DHCP1', 'eth0']])
    return validate(spec)


def ospf_dhcp_multi_lab(rootfs):
    """Two isolated DHCP client VLANs advertised by the same real OSPF switch."""
    spec = ospf_dhcp_lab(rootfs)
    spec['name'] = 'ospf-dhcp-multi-lan'
    switch, server = spec['nodes'][1], spec['nodes'][5]
    switch['interfaces']['eth2'] = ''
    switch['vlans'].append(30)
    switch['switchports']['eth2'] = {'mode': 'access', 'vlan': 30}
    switch['svis']['vlan30'] = {'vlan': 30, 'address': '198.51.100.1/24'}
    switch['ospf']['interfaces']['vlan30'] = {'passive': True}
    switch['ospf']['networks'].append('198.51.100.0/24')
    switch['dhcp_relay'] = [switch['dhcp_relay'],
        {'interface': 'vlan30', 'upstream_interface': 'vlan20', 'server': '198.18.0.3'}]
    server['routes'].append({'destination': '198.51.100.0/24', 'gateway': '198.18.0.1', 'interface': 'eth0'})
    server['dhcp_pools']['pools'].append({'network': '198.51.100.0/24', 'start': '198.51.100.100',
        'end': '198.51.100.110', 'router': '198.51.100.1',
        'reservations': [{'mac': '02:00:00:00:40:02', 'address': '198.51.100.100'}]})
    spec['nodes'].append({'name': 'PC3', 'runtime': 'oci', 'rootfs': str(Path(rootfs).resolve()),
        'interfaces': {'eth0': ''}, 'dhcp_clients': ['eth0'], 'interface_macs': {'eth0': '02:00:00:00:40:02'}})
    spec['links'].append([['PC3', 'eth0'], ['SW1', 'eth2']])
    return validate(spec)


def ospf_dhcp_lldp_lab(rootfs):
    """Real physical neighbor discovery alongside SVI OSPF and two DHCP helpers."""
    spec = ospf_dhcp_multi_lab(rootfs)
    spec['name'] = 'ospf-dhcp-lldp-lan'
    # Only infrastructure links advertise; SVIs and client/server access ports
    # are deliberately outside this example's discovery scope.
    for index, ports in ((1, ['eth1']), (4, ['eth0', 'eth1']), (2, ['eth0'])):
        spec['nodes'][index]['lldp'] = {'ports': ports}
    return validate(spec)


def lan_services_lab(rootfs):
    """Eight real nodes: routed DHCP clients, local DNS, HTTP and physical LLDP."""
    spec = ospf_dhcp_lldp_lab(rootfs)
    spec['name'] = 'lan-services'
    access, dhcp, web = spec['nodes'][4], spec['nodes'][5], spec['nodes'][3]
    access['interfaces']['eth3'] = ''
    access['switchports']['eth3'] = {'mode': 'access', 'vlan': 20}
    for pool in dhcp['dhcp_pools']['pools']:
        pool['dns'] = ['198.18.0.4']
    # Explicit startup argv, as in dns_lab: restore recreates the sample page;
    # arbitrary HTTP filesystem changes are not persisted or audited.
    web['startup'] = [['/bin/sh', '-c',
        'mkdir -p /tmp/www; echo "Network LABS routed HTTP" > /tmp/www/index.html; /bin/busybox httpd -p 80 -h /tmp/www']]
    spec['nodes'].append({'name': 'DNS1', 'runtime': 'oci', 'rootfs': str(Path(rootfs).resolve()),
        'interfaces': {'eth0': '198.18.0.4/29'},
        'routes': [{'destination': network, 'gateway': gateway, 'interface': 'eth0'}
                   for network, gateway in (('192.0.2.0/24', '198.18.0.1'),
                                            ('198.51.100.0/24', '198.18.0.1'),
                                            ('203.0.113.0/24', '198.18.0.2'))],
        'dns_server': {'interface': 'eth0', 'zone': 'lab.test', 'ttl': 60,
                       'records': {'web.lab.test': '203.0.113.10', 'dns.lab.test': '198.18.0.4'}}})
    spec['links'].append([['SW2', 'eth3'], ['DNS1', 'eth0']])
    return validate(spec)


def ipv6_vlan_lab(rootfs):
    """Static IPv6, two VLANs over one trunk; no routing or RA services."""
    def host(name, suffix, vlan):
        return {'name': name, 'runtime': 'oci', 'rootfs': str(Path(rootfs).resolve()),
                'interfaces': {'eth0': ''}, 'ipv6': {'eth0': f'2001:db8:{vlan}::{suffix}/64'}}
    def switch(name):
        return {'name': name, 'runtime': 'oci', 'role': 'switch', 'rootfs': str(Path(rootfs).resolve()),
                'interfaces': {'eth0': '', 'eth1': '', 'eth2': ''}, 'vlans': [10, 20],
                'switchports': {'eth0': {'mode': 'access', 'vlan': 10}, 'eth1': {'mode': 'access', 'vlan': 20},
                                'eth2': {'mode': 'trunk', 'native_vlan': 1, 'allowed': [10, 20]}}}
    return validate({'version': 2, 'name': 'ipv6-vlan-lan', 'nodes': [host('PC1', 10, 10), host('PC2', 20, 10),
        host('PC3', 10, 20), host('PC4', 20, 20), switch('SW1'), switch('SW2')], 'links': [
        [['PC1', 'eth0'], ['SW1', 'eth0']], [['PC2', 'eth0'], ['SW2', 'eth0']],
        [['PC3', 'eth0'], ['SW1', 'eth1']], [['PC4', 'eth0'], ['SW2', 'eth1']],
        [['SW1', 'eth2'], ['SW2', 'eth2']]]})


def ipv6_routed_lab(rootfs):
    """Two internal IPv6 LANs and numbered router transit, all static."""
    rootfs = str(Path(rootfs).resolve())
    def route(prefix, via, port):
        return {'destination': prefix, 'gateway': via, 'interface': port}
    def node(name, values, routes, role='host'):
        return {'name': name, 'runtime': 'oci', 'rootfs': rootfs, 'role': role, 'forwarding': False,
                'interfaces': {p: '' for p in values}, 'ipv6': values, 'ipv6_routes': routes,
                'ipv6_forwarding': role == 'router'}
    return validate({'version': 2, 'name': 'ipv6-routed-lan', 'nodes': [
        node('PC1', {'eth0': '2001:db8:10::10/64'}, [route('::/0', '2001:db8:10::1', 'eth0')]),
        node('R1', {'eth0': '2001:db8:10::1/64', 'eth1': '2001:db8:100::1/64'},
             [route('2001:db8:20::/64', '2001:db8:100::2', 'eth1')], 'router'),
        node('R2', {'eth0': '2001:db8:100::2/64', 'eth1': '2001:db8:20::1/64'},
             [route('2001:db8:10::/64', '2001:db8:100::1', 'eth0')], 'router'),
        node('PC2', {'eth0': '2001:db8:20::20/64'}, [route('::/0', '2001:db8:20::1', 'eth0')]),
    ], 'links': [[['PC1', 'eth0'], ['R1', 'eth0']], [['R1', 'eth1'], ['R2', 'eth0']],
                [['R2', 'eth1'], ['PC2', 'eth0']]]})


def slaac_lab(rootfs):
    """A kernel SLAAC client reaches a static remote LAN using a real RA router."""
    spec = ipv6_routed_lab(rootfs)
    spec['name'] = 'slaac-lan'
    spec['nodes'][0].update(ipv6={}, ipv6_routes=[], slaac=['eth0'])
    spec['nodes'][1]['router_advertisements'] = ['eth0']
    return validate(spec)


def dhcpv6_lab(rootfs):
    """Stateful DHCPv6 client with an RA-discovered gateway and remote static LAN."""
    spec = slaac_lab(rootfs)
    spec['name'] = 'dhcpv6-lan'
    spec['nodes'][0].update(slaac=[], dhcpv6_clients=['eth0'])
    spec['nodes'][1]['dhcpv6_server'] = {'interface': 'eth0', 'start': '2001:db8:10::100',
                                       'end': '2001:db8:10::10f', 'lease_seconds': 120}
    return validate(spec)


def dual_stack_lab(rootfs):
    """Independent static IPv4/IPv6 routing across the same two internal routers."""
    spec = ipv6_routed_lab(rootfs)
    spec['name'] = 'dual-stack-lan'
    pc1, r1, r2, pc2 = spec['nodes']
    pc1.update(interfaces={'eth0': '192.0.2.10/24'}, gateway='192.0.2.1')
    r1.update(interfaces={'eth0': '192.0.2.1/24', 'eth1': '198.18.0.1/30'}, forwarding=True,
              routes=[{'destination': '198.51.100.0/24', 'gateway': '198.18.0.2', 'interface': 'eth1'}])
    r2.update(interfaces={'eth0': '198.18.0.2/30', 'eth1': '198.51.100.1/24'}, forwarding=True,
              routes=[{'destination': '192.0.2.0/24', 'gateway': '198.18.0.1', 'interface': 'eth0'}])
    pc2.update(interfaces={'eth0': '198.51.100.20/24'}, gateway='198.51.100.1')
    return validate(spec)


def radius_lab(rootfs, secret, password_sha256, username='learner'):
    from .spec import example
    spec = example(rootfs); spec['name'] = 'radius-lan'
    spec['nodes'][2]['radius_server'] = {'interface': 'eth0',
        'clients': [{'address': '192.0.2.10', 'secret': secret}],
        'users': {username: {'password_sha256': password_sha256}}}
    return validate(spec)


def tftp_lab(rootfs):
    """Two hosts and a switch with one declared public test file."""
    from .spec import example
    spec = example(rootfs); spec['name'] = 'tftp-lan'
    spec['nodes'][2]['tftp_server'] = {'interface': 'eth0', 'files': {'sample.txt': 'Network LABS TFTP\n', 'sample.bin': {'base64': 'AAECA/8='}}}
    return validate(spec)


def ntp_lab(rootfs):
    """Isolated client, relay and deliberately unsynchronised local reference."""
    from .spec import example
    spec = example(rootfs); spec['name'] = 'ntp-lan'
    spec['nodes'][1]['interfaces']['eth2'] = ''
    spec['nodes'][2]['ntp_server'] = {'interface': 'eth0', 'upstream': '192.0.2.30', 'clients': ['192.0.2.10']}
    spec['nodes'].append({'name': 'PC3', 'runtime': 'oci', 'rootfs': str(Path(rootfs).resolve()),
                          'interfaces': {'eth0': '192.0.2.30/24'},
                          'ntp_server': {'interface': 'eth0', 'local_stratum': 10, 'clients': ['192.0.2.20']}})
    spec['links'].append([['SW1', 'eth2'], ['PC3', 'eth0']])
    return validate(spec)


def management_lab(rootfs, ssh_key=None, telnet_password_hash=''):
    """Three-node internal IPv4 LAN with real management services on R1."""
    from .spec import example
    spec = example(rootfs); spec['name'] = 'management-lan'
    server = spec['nodes'][2]; server.update(name='R1', role='router', forwarding=False)
    spec['links'][1][1][0] = 'R1'
    server['management'] = {'interface': 'eth0', 'ssh_keys': [ssh_key] if ssh_key else [],
                            'telnet_password_hash': telnet_password_hash, 'syslog_remote': '192.0.2.10'}
    return validate(spec)


def syslog_lab(rootfs):
    """Real UDP sender through a switch to a node-local rsyslog collector."""
    spec = management_lab(rootfs); spec['name'] = 'syslog-lan'
    spec['nodes'][0]['syslog_server'] = {'interface': 'eth0', 'senders': ['192.0.2.20']}
    return validate(spec)


def snmp_lab(rootfs, community='network-labs-ro'):
    """Read-only SNMPv2c management from PC1, with a second monitored LAN."""
    from .spec import example
    spec = example(rootfs); spec['name'] = 'snmp-lan'
    router = spec['nodes'][2]; router.update(name='R1', role='router', forwarding=False,
                                           interfaces={'eth0': '192.0.2.20/24', 'eth1': '198.51.100.1/24'})
    spec['links'][1][1][0] = 'R1'
    router['snmp_agent'] = {'interface': 'eth0', 'community': community, 'managers': ['192.0.2.10']}
    spec['nodes'].append({'name': 'PC2', 'runtime': 'oci', 'rootfs': str(Path(rootfs).resolve()),
                          'interfaces': {'eth0': '198.51.100.10/24'}, 'gateway': '198.51.100.1'})
    spec['links'].append([['R1', 'eth1'], ['PC2', 'eth0']])
    return validate(spec)


def snmpv3_lab(rootfs, user):
    """USM SHA-256/AES authPriv on the existing two-LAN SNMP topology."""
    import copy
    spec = snmp_lab(rootfs); spec['name'] = 'snmpv3-lan'
    agent = spec['nodes'][2]['snmp_agent']; del agent['community']
    agent['usm'] = copy.deepcopy(user)
    return validate(spec)


def snmp_notifications_lab(rootfs, mode='trap'):
    """Genuine agent coldStart plus an authorized receiver and an untrusted peer."""
    spec = snmp_lab(rootfs); spec['name'] = 'snmp-notifications'
    spec['nodes'][0]['snmp_receiver'] = {'interface': 'eth0', 'community': 'network-labs-notify', 'sources': ['192.0.2.20']}
    spec['nodes'][2]['snmp_agent']['notifications'] = {'receiver': '192.0.2.10', 'community': 'network-labs-notify', 'mode': mode}
    spec['nodes'].append({'name': 'PC3', 'runtime': 'oci', 'rootfs': str(Path(rootfs).resolve()), 'interfaces': {'eth0': '192.0.2.30/24'}})
    spec['nodes'][1]['interfaces']['eth2'] = ''
    spec['links'].append([['SW1', 'eth2'], ['PC3', 'eth0']])
    return validate(spec)


def snmpv3_informs_lab(rootfs, user):
    """Receiver-authoritative USM informs; no community or trap-user fallback."""
    import copy
    spec = snmp_notifications_lab(rootfs, 'inform'); spec['name'] = 'snmpv3-informs'
    receiver = spec['nodes'][0]['snmp_receiver']; del receiver['community']
    receiver['usm'] = copy.deepcopy(user)
    agent = spec['nodes'][2]['snmp_agent']; del agent['community']
    agent['usm'] = copy.deepcopy(user)
    del agent['notifications']['community']
    agent['notifications']['usm'] = copy.deepcopy(user)
    return validate(spec)


def snmpv3_traps_lab(rootfs, user):
    """Two freshly identified trap senders and one explicitly bound USM sink."""
    import copy
    spec = snmpv3_informs_lab(rootfs, user); spec['name'] = 'snmpv3-traps'
    agent = spec['nodes'][2]['snmp_agent']; agent['notifications']['mode'] = 'trap'
    spec['nodes'][0]['snmp_receiver'].update(trap_senders=['R1', 'R2'], sources=['192.0.2.20', '192.0.2.40'])
    spec['nodes'].append({'name': 'R2', 'role': 'router', 'runtime': 'oci', 'rootfs': str(Path(rootfs).resolve()),
                          'interfaces': {'eth0': '192.0.2.40/24'}, 'snmp_agent': copy.deepcopy(agent)})
    spec['nodes'][1]['interfaces']['eth3'] = ''
    spec['links'].append([['SW1', 'eth3'], ['R2', 'eth0']])
    return validate(spec)


def snmp_links_lab(rootfs, user, mode='trap'):
    """Real IF-MIB link observations on R1 eth1; management uses eth0."""
    spec = snmpv3_traps_lab(rootfs, user) if mode == 'trap' else snmpv3_informs_lab(rootfs, user)
    if mode not in ('trap', 'inform'): raise ValueError('Choose trap or inform link events.')
    spec['name'] = 'snmp-link-events'
    spec['nodes'][2]['snmp_agent']['link_events'] = {'interfaces': ['eth1'], 'interval': 2}
    return validate(spec)
