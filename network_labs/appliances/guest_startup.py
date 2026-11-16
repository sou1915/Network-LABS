"""Persist bounded observed guest IPv4 state and replay it into fresh guest disks."""
import copy
import ipaddress
import re
import time
from .guest_control import request


def _port_networks(node, profile):
    """Every IPv4 network configured on each declared port, primary first."""
    extras = {'eth0': profile['addresses'], **profile.get('port_addresses', {})}
    return {port: [ipaddress.IPv4Interface(a).network for a in [primary, *extras.get(port, [])]]
            for port, primary in node['interfaces'].items()}


def route_port(node, profile, gateway):
    """Ports never share a subnet, so an on-link next hop identifies one port."""
    gateway = ipaddress.IPv4Address(gateway)
    ports = [port for port, nets in _port_networks(node, profile).items() if any(gateway in net for net in nets)]
    if len(ports) != 1:
        raise ValueError('Guest next hop must be on a configured subnet.')
    return ports[0]


def validate_profile(node):
    profile = node.get('guest_network')
    if 'guest_network' not in node:
        return
    if (node['runtime'] != 'firecracker' or not isinstance(profile, dict)
            or not {'addresses', 'routes'} <= set(profile) <= {'addresses', 'routes', 'port_addresses'}):
        raise ValueError('guest_network requires a Firecracker addresses/routes object.')
    routes, extra_ports = profile['routes'], profile.get('port_addresses', {})
    if not isinstance(extra_ports, dict) or set(extra_ports) - (set(node['interfaces']) - {'eth0'}):
        raise ValueError('port_addresses must map declared guest ports other than eth0 to address lists.')
    by_port = {'eth0': profile['addresses'], **extra_ports}
    if any(not isinstance(values, list) for values in by_port.values()) or sum(map(len, by_port.values())) > 32 or not isinstance(routes, list) or len(routes) > 32:
        raise ValueError('Guest startup supports at most 32 addresses and 32 routes.')
    for port, values in by_port.items():
        primary = str(ipaddress.IPv4Interface(node['interfaces'][port]))
        normalized = [str(ipaddress.IPv4Interface(a)) for a in values if isinstance(a, str) and '/' in a]
        if len(normalized) != len(values) or len(set(normalized)) != len(normalized) or primary in normalized:
            raise ValueError('Guest extra addresses must be unique explicit IPv4 prefixes, excluding primary.')
        by_port[port] = sorted(normalized)
    profile['addresses'] = by_port.pop('eth0')
    profile.pop('port_addresses', None)
    if any(by_port.values()):
        profile['port_addresses'] = {port: values for port, values in sorted(by_port.items()) if values}
    networks = _port_networks(node, profile)
    ports = list(networks)
    if any(a.overlaps(b) for i, left in enumerate(ports) for right in ports[i+1:] for a in networks[left] for b in networks[right]):
        raise ValueError('Guest addresses on different ports must not share or overlap a subnet.')
    checked = []
    for route in routes:
        if not isinstance(route, dict) or set(route) != {'network', 'gateway'}:
            raise ValueError('Guest route requires network/gateway only.')
        if not isinstance(route['network'], str) or '/' not in route['network'] or not isinstance(route['gateway'], str):
            raise ValueError('Guest route network/prefix and gateway must be strings.')
        network = str(ipaddress.IPv4Network(route['network'], strict=True))
        gateway = str(ipaddress.IPv4Address(route['gateway']))
        route_port(node, profile, gateway)
        if network == '0.0.0.0/0' and node.get('gateway'):
            raise ValueError('Guest default route already supplied by primary gateway.')
        checked.append({'network': network, 'gateway': gateway})
    if len({r['network'] for r in checked}) != len(checked):
        raise ValueError('Guest static routes require unique prefixes.')
    profile['routes'] = sorted(checked, key=lambda r: r['network'])


def query(socket, operation, **kwargs):
    result = request(socket, operation, **kwargs)
    if result['exit_code']:
        raise ValueError('Guest ' + operation + ' failed: ' + result['output'])
    return result['output']


def forwarding(socket):
    """True/False from the guest kernel; None for an image whose agent predates routers."""
    try:
        return query(socket, 'forwarding').strip() == '1'
    except ValueError as error:
        # Such an agent cannot have enabled forwarding either, so a host on it is still off.
        if 'unsupported operation' in str(error):
            return None
        raise


def check_forwarding(socket, node):
    state = forwarding(socket)
    if node.get('role') in ('router', 'firewall'):
        if state is not True:
            raise ValueError('Router or firewall guest is not forwarding IPv4; rebuild its image with the current agent.' if state is None
                             else 'Router or firewall guest is not forwarding IPv4.')
    elif state:
        raise ValueError('Host guest forwards IPv4 although its role is host; declare a router instead.')


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
    extras = {port: [a for a in values if a != str(ipaddress.IPv4Interface(node['interfaces'][port]))] for port, values in by_port.items()}
    routes = []; devices = {}
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
        if len(fields) != 5 or fields[1] != 'via' or fields[3] != 'dev' or fields[4] not in by_port:
            raise ValueError('Unsupported guest static route: ' + line)
        gateway = str(ipaddress.IPv4Address(fields[2]))
        if network == '0.0.0.0/0' and node.get('gateway'):
            if gateway != node['gateway'] or fields[4] != 'eth0': raise ValueError('Guest primary gateway differs.')
            default_seen = True
        else:
            routes.append({'network': network, 'gateway': gateway}); devices[network] = fields[4]
    if node.get('gateway') and not default_seen: raise ValueError('Guest primary gateway missing.')
    candidate = copy.deepcopy(node)
    candidate['guest_network'] = {'addresses': extras.pop('eth0'), 'routes': routes, 'port_addresses': extras}
    validate_profile(candidate)
    for route in candidate['guest_network']['routes']:
        # A next hop reached through another port than its own subnet cannot be replayed.
        if route_port(candidate, candidate['guest_network'], route['gateway']) != devices[route['network']]:
            raise ValueError('Unsupported guest static route device for ' + route['network'])
    check_forwarding(socket, node)
    if node.get('role') == 'firewall':
        from .guest_firewall import check
        check(socket, node)
    return candidate['guest_network']


def apply(socket, node, timeout=40, alive=None):
    """Fresh boot only: wait for agent, then apply once; failures abort lab startup."""
    deadline = time.monotonic() + timeout
    while True:
        if alive is not None and not alive():
            raise ValueError('Guest VMM exited before its agent answered.')
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
    for port, values in profile.get('port_addresses', {}).items():
        for address in values:
            query(socket, 'address-add', interface=port, cidr=address)
    for route in profile['routes']:
        port = route_port(node, profile, route['gateway'])
        # eth0 keeps the original request so guest images built before multi-port routes still restore.
        query(socket, 'route-add', **route, **({} if port == 'eth0' else {'interface': port}))
    if node.get('role') == 'firewall':
        # Filter first: forwarding is never switched on before the declared policy is in place.
        from .guest_firewall import apply as apply_firewall
        apply_firewall(socket, node)
    if node.get('role') in ('router', 'firewall'):
        query(socket, 'forward', state='on')
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
    return {'saved': str(startup_path(manager.name)), 'scope': 'Observed extra IPv4 addresses and on-link static routes on every declared port, plus declared primary addresses; interfaces up. No disk snapshot or IPv6 persistence.'}
