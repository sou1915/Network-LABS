"""IOS NAT on a router micro-VM: « ip nat inside source list N interface PORT overload » (PAT), for real.

The IOS lines stay in the device's stored configuration (ios_store); this module compiles them into the NAT entries
the guest firewall already runs (masquerade, the same nftables/iptables path the firewall guests use), and the network
model reads the same entries. As on IOS, nothing is translated unless the outgoing port is marked « ip nat outside » and
some port « ip nat inside ». The sources are the « permit » entries of list N, in order; a « deny » entry stops the
permits it covers entirely (a deny that covers only part of a later permit is not honoured: the whole permit is
translated). Static NAT and pools need public addresses the router does not hold yet: they stay configuration only.
"""
import ipaddress
import re

from . import ios_store

OVERLOAD = re.compile(r'ip nat inside source list (\S+) interface (\S+) overload', re.IGNORECASE)


def _marked(node, side):
    lines = ios_store.config(node)['interfaces']
    return {port for port, entries in lines.items() if any(l.lower() == f'ip nat {side}' for l in entries)}


def entries(node):
    """The masquerade entries the router's IOS NAT lines give (empty when nothing would be translated)."""
    if node.get('role') != 'router' or not node.get('cli_config'):
        return []
    from .vendor_config import _port
    outside, inside = _marked(node, 'outside'), _marked(node, 'inside')
    found = []
    for line in ios_store.config(node)['global']:
        match = OVERLOAD.fullmatch(line.strip())
        if not match:
            continue
        try:
            port = _port(node, match[2])
        except ValueError:
            continue
        if port not in outside or not inside:
            continue  # IOS translates only from an inside port out of an outside one
        denied = []
        for index, entry in enumerate((node.get('acls') or {}).get(match[1], []), 1):
            network = ipaddress.IPv4Network(entry['source'])
            if entry['action'] == 'deny':
                denied.append(network)
                continue
            if any(network.subnet_of(d) for d in denied):
                continue
            found.append({'name': f'nat-{match[1]}-{index}', 'type': 'masquerade', 'out': port, 'protocol': 'any',
                          **({} if network.prefixlen == 0 else {'source': str(network)})})
    return found
