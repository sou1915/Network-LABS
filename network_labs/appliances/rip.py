"""RIP on router micro-VMs, from the IOS lines « router rip / version / network / passive-interface », run by BIRD 2.

As on IOS, « network A.B.C.D » is classful: RIP runs on every port whose address is in that class A, B or C network, and
announces those ports' networks. A passive interface is announced but sends no updates (it still listens). Version 2
unless « version 1 » is set (then broadcast, as RIPv1). RIP and OSPF share the guest's BIRD, so a router runs one of the
two. The guest agent writes BIRD's configuration from the typed process (guest_process); the network model computes
the same routes by hop count (rip_routes in network_model).
"""
import ipaddress

from . import ios_store


def classful(address):
    first = int(str(address).split('.')[0])
    length = 8 if first < 128 else 16 if first < 192 else 24
    return ipaddress.IPv4Network(f'{address}/{length}', strict=False)


def _block(node):
    return next((b for b in ios_store.config(node)['blocks'] if b['header'] == 'router rip'), None) if node.get('cli_config') else None


def process(node):
    """{'router_id', 'version', 'interfaces': [{'port', 'passive'}]} when RIP runs on at least one port, else None."""
    if node.get('role') != 'router' or node.get('runtime') != 'firecracker':
        return None
    block = _block(node)
    if block is None:
        return None
    from .vendor_config import _port
    networks, passive, version = [], set(), 2
    for line in block['lines']:
        words = line.lower().split()
        if words[:1] == ['network'] and len(words) == 2:
            networks.append(classful(words[1]))
        elif words[:1] == ['passive-interface'] and len(words) == 2:
            try:
                passive.add(_port(node, words[1]))
            except ValueError:
                pass
        elif words[:1] == ['version'] and len(words) == 2:
            version = int(words[1])
    ports = []
    for port, address in node['interfaces'].items():
        if address and any(ipaddress.IPv4Interface(address).ip in network for network in networks):
            ports.append({'port': port, 'passive': port in passive})
    if not ports:
        return None
    addresses = [ipaddress.IPv4Interface(a).ip for a in node['interfaces'].values() if a]
    return {'router_id': str(max(addresses)), 'version': version, 'interfaces': ports}


def validate(node):
    if _block(node) is not None and node.get('ospf'):
        raise ValueError('RIP et OSPF sur le même routeur : pas encore (un seul démon BIRD par micro-VM).')


def guest_process(node):
    return process(node)
