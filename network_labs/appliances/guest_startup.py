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
    by_port = {port: [] for port in node['interfaces']}
    interface = None; active = set()
    for line in text.splitlines():
        header = re.match(r'^\d+: ([^:]+): <([^>]*)>', line)
        if header:
            interface = header[1]
            if interface != 'lo' and interface not in by_port:
                raise ValueError('Guest has an undeclared interface.')
            if 'UP' in header[2].split(','): active.add(interface)
        fields = line.split()
        if fields and fields[0] == 'inet' and interface in by_port:
            by_port[interface].append(str(ipaddress.IPv4Interface(fields[1])))
    for port, primary_address in node['interfaces'].items():
        primary_address = str(ipaddress.IPv4Interface(primary_address))
        if port not in active or primary_address not in by_port[port]:
            raise ValueError('Save requires all declared guest interfaces up with primary IPv4 addresses.')
        if port != 'eth0' and by_port[port] != [primary_address]:
            raise ValueError('Extra-address persistence currently supports eth0 only.')
    primary = str(ipaddress.IPv4Interface(node['interfaces']['eth0']))
    addresses = by_port['eth0']
    routes = []
    connected = {(port, str(ipaddress.IPv4Interface(a).network), str(ipaddress.IPv4Interface(a).ip)) for port, values in by_port.items() for a in values}
    default_seen = False
    for line in query(socket, 'routes').splitlines():
        fields = line.split()
        if not fields: continue
        network = str(ipaddress.IPv4Network('0.0.0.0/0' if fields[0] == 'default' else fields[0]))
        if 'via' not in fields:
            if len(fields) != 7 or fields[1] != 'dev' or fields[3:6] != ['scope', 'link', 'src'] or (fields[2], network, fields[6]) not in connected:
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
    for port, address in node['interfaces'].items():
        if port != 'eth0':
            query(socket, 'address-add', interface=port, cidr=address)
            query(socket, 'link', interface=port, state='up')
    profile = node.get('guest_network', {'addresses': [], 'routes': []})
    for address in profile['addresses']:
        query(socket, 'address-add', cidr=address)
    for route in profile['routes']:
        query(socket, 'route-add', **route)
    if observe(socket, node) != profile:
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
    return {'saved': str(startup_path(manager.name)), 'scope': 'Observed eth0 extras/routes and declared primary addresses; interfaces up. No disk snapshot or IPv6 persistence.'}
