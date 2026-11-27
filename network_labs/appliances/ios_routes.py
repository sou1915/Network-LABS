"""Static routes through a port and proxy ARP, as IOS has them.

« ip route 0.0.0.0 0.0.0.0 GigabitEthernet0/0/1 » sends packets out of the port with no next hop: the router asks ARP for
each destination there, and the neighbour answers by proxy ARP (on by default on IOS, « no ip proxy-arp » turns it off on
a port) for the addresses it reaches through another port. The IOS lines stay in the stored configuration; the router
guest gets « ip route add NET dev ethN » and proxy_arp on its ports, and the network model lets routers answer by proxy
ARP the same way (only for an address they reach through another port, as Linux and IOS do).
"""
import ipaddress
import re

from . import ios_store

PORT_ROUTE = re.compile(r'ip route (\d+\.\d+\.\d+\.\d+) (\d+\.\d+\.\d+\.\d+) (\S+)', re.IGNORECASE)


def _is_address(word):
    try:
        ipaddress.IPv4Address(word)
        return True
    except ValueError:
        return False


def port_routes(node):
    """[(network, port)] for the « ip route NET MASK PORT » lines (no next hop)."""
    if node.get('role') not in ('router', 'firewall') or not node.get('cli_config'):
        return []
    from .vendor_config import _port
    found = []
    for line in ios_store.config(node)['global']:
        match = PORT_ROUTE.fullmatch(line.strip())
        if match and not _is_address(match[3]):
            try:
                found.append((ipaddress.IPv4Network(f'{match[1]}/{match[2]}'), _port(node, match[3])))
            except ValueError:
                continue
    return found


def proxy_arp(node):
    """{port: on} for a Cisco router's numbered ports: IOS answers ARP by proxy unless « no ip proxy-arp » is on the port.
    Other routers keep it off, as their systems do by default."""
    from .vendor_config import dialect
    if node.get('role') != 'router' or dialect(node) != 'ios':
        return {}
    lines = ios_store.config(node)['interfaces'] if node.get('cli_config') else {}
    return {port: 'no ip proxy-arp' not in [l.lower() for l in lines.get(port, [])]
            for port, address in node['interfaces'].items() if address}


def store(node, network, port_word, remove=False):
    """Keep (or drop) the « ip route NET MASK PORT » line for NETWORK; any route to NETWORK through a port goes."""
    from .vendor_config import _port, ios_name, port_names
    current = ios_store.config(node)
    kept = []
    for line in current['global']:
        match = PORT_ROUTE.fullmatch(line.strip())
        if match and not _is_address(match[3]) and ipaddress.IPv4Network(f'{match[1]}/{match[2]}') == network:
            continue
        kept.append(line)
    if not remove:
        port = _port(node, port_word)
        label = port_names(node).get(port, port)
        kept.append(f'ip route {network.network_address} {network.netmask} {ios_name(label)}')
    current['global'] = kept
    node['cli_config'] = current
