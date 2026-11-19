"""EIGRP on router micro-VMs, from the IOS lines « router eigrp AS / network / eigrp router-id », run by FRR's eigrpd.

As on IOS, « network A.B.C.D » alone is classful and « network A.B.C.D WILDCARD » takes the ports whose address it
covers; EIGRP runs on those ports and announces their networks. The guest agent writes eigrpd's configuration from the
typed process (guest_process) and starts it with zebra; the network model computes the same routes (eigrp_routes).

FRR assumes 100 Mbit/s links, so its metrics are those IOS shows on FastEthernet ports; on GigabitEthernet ports IOS
shows a tenth of them (256 × (10 + one per interface on the way)), and the CLI does too. Two limits of the lab: FRR's
eigrpd keeps sending hellos on a « passive-interface » (kept in the configuration, as typed), and a router runs one
dynamic routing protocol (EIGRP with zebra; OSPF or RIP with BIRD; BGP with zebra).
"""
import ipaddress
import re

from . import ios_store
from .rip import classful


def _block(node):
    if not node.get('cli_config'):
        return None
    return next((b for b in ios_store.config(node)['blocks'] if re.fullmatch(r'router eigrp \d+', b['header'])), None)


def _network(words):
    """The network an IOS « network A.B.C.D [WILDCARD] » line selects."""
    if len(words) == 3:
        return ipaddress.IPv4Network(f'{words[1]}/{words[2]}', strict=False)
    return classful(words[1])


def process(node):
    """{'asn', 'router_id', 'networks', 'passive', 'interfaces': [{'port', 'passive'}]} when EIGRP runs on at least one
    port, else None."""
    if node.get('role') != 'router' or node.get('runtime') != 'firecracker':
        return None
    block = _block(node)
    if block is None:
        return None
    from .vendor_config import _port
    networks, passive, router_id = [], set(), None
    for line in block['lines']:
        words = line.lower().split()
        if words[:1] == ['network'] and len(words) in (2, 3):
            networks.append(_network(words))
        elif words[:1] == ['passive-interface'] and len(words) == 2:
            try:
                passive.add(_port(node, words[1]))
            except ValueError:
                pass
        elif words[:2] == ['eigrp', 'router-id'] and len(words) == 3:
            router_id = words[2]
    down = set(node.get('shutdown') or [])
    ports = [port for port, address in node['interfaces'].items()
             if address and port not in down and any(ipaddress.IPv4Interface(address).ip in n for n in networks)]
    if not ports:
        return None
    addresses = [ipaddress.IPv4Interface(a).ip for a in node['interfaces'].values() if a]
    return {'asn': int(block['header'].split()[2]), 'router_id': router_id or str(max(addresses)),
            'networks': sorted({str(n) for n in networks}), 'passive': sorted(passive),
            # FRR's eigrpd sends hellos on passive ports too: the model forms the same adjacencies as the guests.
            'interfaces': [{'port': port, 'passive': False} for port in ports]}


def validate(node):
    if _block(node) is None:
        return
    from .rip import _block as rip_block
    if node.get('ospf') or node.get('bgp') or rip_block(node) is not None:
        raise ValueError('EIGRP avec OSPF, RIP ou BGP sur le même routeur : pas encore (un protocole dynamique par micro-VM).')


def fields(eigrp):
    """« AS ROUTER_ID NET[,NET…] PASSIVE[,…]|- » for the agent's EIGRP_RENDER / EIGRP_START."""
    return (f'{eigrp["asn"]} {ipaddress.IPv4Address(eigrp["router_id"])} ' + ','.join(eigrp['networks']) + ' '
            + (','.join(eigrp['passive']) or '-'))


def config(eigrp):
    """eigrpd's configuration as the agent writes it (checked against the running daemon's)."""
    lines = ['frr defaults traditional', f'router eigrp {eigrp["asn"]}', f' eigrp router-id {eigrp["router_id"]}']
    lines += [f' network {n}' for n in eigrp['networks']] + [f' passive-interface {p}' for p in eigrp['passive']]
    return '\n'.join(lines) + '\n'


def ios_metric(frr_metric, gigabit=True):
    """The metric IOS shows for FRR's (computed on 100 Mbit/s links): a tenth of it on GigabitEthernet ports."""
    return frr_metric // 10 if gigabit else frr_metric


def parse_topology(text):
    """{network: FRR feasible distance} from « show ip eigrp topology »."""
    return {match[1]: int(match[2]) for match in re.finditer(r'^\S+\s+(\d+\.\d+\.\d+\.\d+/\d+), .*FD is (\d+)', text, re.M)}


def parse_neighbors(text):
    """[{'address', 'port', 'hold', 'uptime', 'srtt', 'rto', 'queue', 'seq'}] from « show ip eigrp neighbors »."""
    found = []
    for line in text.splitlines():
        words = line.split()
        if len(words) >= 9 and words[0].isdigit() and re.fullmatch(r'\d+\.\d+\.\d+\.\d+', words[1]):
            found.append({'address': words[1], 'port': words[2], 'hold': words[3], 'uptime': words[4], 'srtt': words[5],
                          'rto': words[6], 'queue': words[7], 'seq': words[8]})
    return found
