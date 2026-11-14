"""Persist bounded observed guest IPv4 state and replay it into fresh guest disks."""
import copy
import ipaddress
import re
import time
from .guest_control import request


def validate_profile(node):
    profile = node.get('guest_network')
    if 'guest_network' not in node:
        return
    if node['runtime'] != 'firecracker' or not isinstance(profile, dict) or set(profile) != {'addresses', 'routes'}:
        raise ValueError('guest_network requires a Firecracker addresses/routes object.')
    addresses, routes = profile['addresses'], profile['routes']
    if not isinstance(addresses, list) or len(addresses) > 32 or not isinstance(routes, list) or len(routes) > 32:
        raise ValueError('Guest startup supports at most 32 addresses and 32 routes.')
    primary = str(ipaddress.IPv4Interface(node['interfaces']['eth0']))
    normalized = [str(ipaddress.IPv4Interface(a)) for a in addresses if isinstance(a, str) and '/' in a]
    if len(normalized) != len(addresses) or len(set(normalized)) != len(normalized) or primary in normalized:
        raise ValueError('Guest extra addresses must be unique explicit IPv4 prefixes, excluding primary.')
    checked = []
    networks = [ipaddress.IPv4Interface(a).network for a in [primary, *normalized]]
    for route in routes:
        if not isinstance(route, dict) or set(route) != {'network', 'gateway'}:
            raise ValueError('Guest route requires network/gateway only.')
        if not isinstance(route['network'], str) or '/' not in route['network'] or not isinstance(route['gateway'], str):
            raise ValueError('Guest route network/prefix and gateway must be strings.')
        network = str(ipaddress.IPv4Network(route['network'], strict=True))
        gateway = str(ipaddress.IPv4Address(route['gateway']))
        if not any(ipaddress.IPv4Address(gateway) in net for net in networks):
            raise ValueError('Guest next hop must be on a configured subnet.')
        if network == '0.0.0.0/0' and node.get('gateway'):
            raise ValueError('Guest default route already supplied by primary gateway.')
        checked.append({'network': network, 'gateway': gateway})
    if len({r['network'] for r in checked}) != len(checked):
        raise ValueError('Guest static routes require unique prefixes.')
    profile['addresses'] = sorted(normalized)
    profile['routes'] = sorted(checked, key=lambda r: r['network'])


def query(socket, operation, **kwargs):
    result = request(socket, operation, **kwargs)
    if result['exit_code']:
        raise ValueError('Guest ' + operation + ' failed: ' + result['output'])
    return result['output']


def observe(socket, node):
    """Fail closed on unrepresentable state; never save shell output as commands."""
    text = query(socket, 'addresses')
    addresses = []; interface = None; up = False
    for line in text.splitlines():
        header = re.match(r'^\d+: ([^:]+): <([^>]*)>', line)
        if header:
            interface = header[1]
            if interface not in ('lo', 'eth0'):
                raise ValueError('Guest startup supports only lo and eth0.')
            if interface == 'eth0': up = 'UP' in header[2].split(',')
        fields = line.split()
        if fields and fields[0] == 'inet' and interface == 'eth0':
            addresses.append(str(ipaddress.IPv4Interface(fields[1])))
    primary = str(ipaddress.IPv4Interface(node['interfaces']['eth0']))
    if not up or primary not in addresses:
        raise ValueError('Save requires guest eth0 up with its declared primary IPv4 address.')
    routes = []
    connected = {str(ipaddress.IPv4Interface(a).network) for a in addresses}
    default_seen = False
    for line in query(socket, 'routes').splitlines():
        fields = line.split()
        if not fields: continue
        network = str(ipaddress.IPv4Network('0.0.0.0/0' if fields[0] == 'default' else fields[0]))
        if 'via' not in fields:
            if network not in connected or len(fields) != 7 or fields[1:6] != ['dev', 'eth0', 'scope', 'link', 'src'] or fields[6] not in {str(ipaddress.IPv4Interface(a).ip) for a in addresses}:
                raise ValueError('Unmanaged guest route cannot be saved: ' + line)
            continue
        if len(fields) != 5 or fields[1] != 'via' or fields[3:] != ['dev', 'eth0']:
            raise ValueError('Unsupported guest static route: ' + line)
        gateway = str(ipaddress.IPv4Address(fields[2]))
        if network == '0.0.0.0/0' and node.get('gateway'):
            if gateway != node['gateway']: raise ValueError('Guest primary gateway differs.')
            default_seen = True
        else: routes.append({'network': network, 'gateway': gateway})
    if node.get('gateway') and not default_seen: raise ValueError('Guest primary gateway missing.')
    candidate = copy.deepcopy(node)
    candidate['guest_network'] = {'addresses': [a for a in addresses if a != primary], 'routes': routes}
    validate_profile(candidate)
    return candidate['guest_network']


def apply(socket, node, timeout=40):
    """Fresh boot only: wait for agent, then apply once; failures abort lab startup."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            query(socket, 'ready')
            break
        except (OSError, ValueError):
            if time.monotonic() >= deadline: raise
            time.sleep(.1)
    for address in node['guest_network']['addresses']:
        query(socket, 'address-add', cidr=address)
    for route in node['guest_network']['routes']:
        query(socket, 'route-add', **route)
    if observe(socket, node) != node['guest_network']:
        raise ValueError('Guest startup readback differs from saved configuration.')


def save_observed(manager):
    """Explicit capture for VM-only labs; existing general save remains declarative."""
    from .spec import validate
    from .persistence import save_startup, startup_path
    manager.state = None
    state = manager.read()
    if state['phase'] != 'running' or any(n['runtime'] != 'firecracker' for n in state['spec']['nodes']):
        raise ValueError('microvm-save requires a running VM-only lab.')
    candidate = copy.deepcopy(state['spec'])
    for node in candidate['nodes']:
        node['guest_network'] = observe(manager.directory / node['name'] / 'guest.vsock', node)
    candidate = validate(candidate)
    # Re-read before publishing: do not accept drift across the capture window.
    for node in candidate['nodes']:
        if observe(manager.directory / node['name'] / 'guest.vsock', node) != node['guest_network']:
            raise ValueError('Guest changed during save; no startup configuration written.')
    save_startup(manager.name, candidate)
    return {'saved': str(startup_path(manager.name)), 'scope': 'Observed IPv4 addresses/routes; eth0 up. No disk snapshot or IPv6 persistence.'}
