"""The built-in example labs of the LAN engine (engine.Lab), used by the tests and the vendor CLIs.

These were the starting labs of the old « Switching Studio » window, which is gone: the application is the
micro-VM workbench. The engine itself stays (vendor CLIs, the LAN model, the web management pages), and so do
these labs that exercise it.
"""
from pathlib import Path

from .cli import Session
from .engine import Node, demo, switching_demo

EXAMPLES = Path(__file__).resolve().parent.parent / 'examples'


def _parsed(name):
    from .text_lab import parse_lab
    return parse_lab((EXAMPLES / name).read_text(encoding='utf-8')).lab


def lan_demo():
    return _parsed('enterprise_lan.lab.txt')


def firewall_demo():
    return _parsed('firewall_lan.lab.txt')


def service_demo():
    return _parsed('service_firewall.lab.txt')


def _run(lab, node, commands):
    session = Session(lab, node)
    for command in commands:
        result = session.execute(command)
        if result.startswith('%'):
            raise ValueError(result)


def channel_demo():
    lab = demo()
    lab.add(Node('SW2', 'Switch', 710, 490))
    for _ in range(2):
        link = lab.connect('SW1', 'SW2', 'trunk', [10, 20])
        for node, port in ((link.a, link.a_port), (link.b, link.b_port)):
            entry = lab.nodes[node].ports[port]
            entry.channel = 1
            entry.channel_mode = 'active'
    return lab


def security_demo():
    lab = demo()
    _run(lab, 'R1', ['enable', 'configure terminal', 'ip dhcp excluded-address 192.168.10.1 192.168.10.20', 'ip dhcp pool USERS',
                     'network 192.168.10.0/24', 'default-router 192.168.10.1', 'dns-server 1.1.1.1', 'exit',
                     'ip dhcp excluded-address 192.168.20.1 192.168.20.20', 'ip dhcp pool SERVERS', 'network 192.168.20.0/24',
                     'default-router 192.168.20.1', 'end'])
    _run(lab, 'SW1', ['enable', 'configure terminal', 'ip dhcp snooping', 'ip dhcp snooping vlan 10,20', 'ip arp inspection vlan 10,20',
                      'interface gi0/3', 'ip dhcp snooping trust', 'ip arp inspection trust', 'exit', 'interface range gi0/1 - 2',
                      'ip verify source', 'end'])
    for name in ('PC1', 'PC2'):
        lab.nodes[name].address = ''
        lab.nodes[name].gateway = ''
    return lab


def mst_demo():
    lab = switching_demo()
    for node in ('SW1', 'SW2', 'SW3'):
        _run(lab, node, ['enable', 'configure terminal', 'spanning-tree mst configuration', 'name CAMPUS', 'revision 1',
                         'instance 1 vlan 10', 'instance 2 vlan 20', 'exit', 'spanning-tree mode mst', 'end'])
    lab.nodes['SW1'].priorities['mst:1'] = 0
    lab.nodes['SW3'].priorities['mst:2'] = 0
    return lab


def vtp_demo():
    lab = switching_demo()
    for node, mode in [('SW1', 'server'), ('SW2', 'client'), ('SW3', 'transparent')]:
        _run(lab, node, ['enable', 'configure terminal', 'vtp domain LAB', 'vtp mode ' + mode, 'end'])
    session = Session(lab, 'SW1')
    for command in ['enable', 'configure terminal', 'vlan 30', 'name USERS', 'end']:
        session.execute(command)
    return lab
