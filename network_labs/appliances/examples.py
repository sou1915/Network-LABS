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
