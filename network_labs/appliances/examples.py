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
