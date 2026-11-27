"""DHCP relay on a router micro-VM, from the IOS line « ip helper-address A.B.C.D » on its LAN ports, for real.

As on IOS, a DHCP request broadcast on a port with a helper address is sent to that address with the port's address as
giaddr; the server picks the pool of that network and answers to it; the router broadcasts the answer back on the port.
dnsmasq relays (the agent's --dhcp-relay mode writes its configuration): one relay per router, so every helper of a router
names the same server. The server side is a pool whose network is on none of the server's ports (a relayed pool,
dhcp_server['network']): it is served on the port the relayed requests arrive by (toward()).
"""
import ipaddress
import re

from . import ios_store

HELPER = re.compile(r'ip helper-address (\d+\.\d+\.\d+\.\d+)', re.IGNORECASE)


def helpers(node):
    """{port: server address} for the numbered, unshut ports with a helper address."""
    if node.get('role') != 'router' or node.get('runtime') != 'firecracker' or not node.get('cli_config'):
        return {}
    down = set(node.get('shutdown') or [])
    found = {}
    for port, lines in ios_store.config(node)['interfaces'].items():
        for line in lines:
            match = HELPER.fullmatch(line.strip())
            if match and port not in down and (node['interfaces'].get(port) or (node.get('subinterfaces') or {}).get(port)):
                found[port] = match[1]
    return found


def process(node):
    """{'server', 'clients'} for the guest's relay, or None when no port relays."""
    found = helpers(node)
    if not found:
        return None
    server = sorted(set(found.values()))[0]
    return {'server': server, 'clients': sorted(port for port, address in found.items() if address == server)}


def validate(node):
    servers = set(helpers(node).values())
    if len(servers) > 1:
        raise ValueError('ip helper-address : une seule adresse de serveur DHCP par routeur dans le lab (relais de la micro-VM).')


def toward(node, network):
    """The port NODE reaches NETWORK by: its most specific static route (the default route last), else its only port
    running OSPF or RIP. None when neither says."""
    from .guest_startup import _port
    from .vendor_config import routes
    network = ipaddress.IPv4Network(network)
    matching = [(ipaddress.IPv4Network(n), g) for n, g in routes(node) if network.subnet_of(ipaddress.IPv4Network(n))]
    for _, gateway in sorted(matching, key=lambda entry: -entry[0].prefixlen):
        port = _port(node, gateway)
        if port:
            return port
    ports = set()
    if node.get('ospf'):
        from .ospf import enabled_interfaces
        ports |= {p for p, settings in enabled_interfaces(node).items() if not settings.get('passive')}
    from .rip import process as rip_process
    ports |= {p['port'] for p in (rip_process(node) or {}).get('interfaces', []) if not p['passive']}
    return ports.pop() if len(ports) == 1 else None
