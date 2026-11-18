"""Persist bounded observed guest IPv4 state and replay it into fresh guest disks."""
import copy
import ipaddress
import re
import time
from .guest_control import request


def guest_interfaces(node):
    """Every guest interface with its declared primary address: ports ('' when unnumbered), then subinterfaces."""
    return {**node['interfaces'], **{name: sub['address'] for name, sub in node.get('subinterfaces', {}).items()}}


def _port_networks(node, profile):
    """Every IPv4 network configured on each declared port, primary first."""
    extras = {'eth0': profile['addresses'], **profile.get('port_addresses', {})}
    # A DHCP client port has no declared primary; its leased address is never part of the profile.
    return {port: [ipaddress.IPv4Interface(a).network for a in [*([primary] if primary else []), *extras.get(port, [])]]
            for port, primary in guest_interfaces(node).items()}


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
        if not node['interfaces'][port]:
            if values:
                raise ValueError('An unnumbered port (DHCP client or subinterface parent) takes no extra static addresses.')
            continue
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


def dhcp_pool(node):
    server = node['dhcp_server']
    return {'start': server['start'], 'end': server['end'], 'router': server['router'], 'dns': server['dns'],
            'lease_seconds': server['lease_seconds'], 'netmask': ipaddress.IPv4Interface(node['interfaces'][server['interface']]).network.prefixlen}


def leases(socket, interface):
    """The guest DHCP server's current leases as [{mac, address, hostname}]; fails if the server is not running."""
    rows = []
    for line in query(socket, 'dhcp-leases', interface=interface).splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and re.fullmatch(r'[0-9a-f]{2}(:[0-9a-f]{2}){5}', fields[0]):
            rows.append({'mac': fields[0], 'address': str(ipaddress.IPv4Address(fields[1])),
                         # "Expires in" may read "1 days 02:00:00": a lone number before "days" is not a hostname.
                         'hostname': fields[2] if len(fields) > 3 and fields[3] != 'days' else ''})
    return rows


def vlan_plan(node):
    """The bridge VLAN entries a switch guest must hold, as {(port, vid, 'pvid' | 'tagged')}; None for one untagged VLAN 1.

    An access port is untagged in its VLAN. A trunk carries every allowed VLAN tagged, and its
    native VLAN untagged. A plain switch (only VLAN 1, all access) keeps the bridge without
    VLAN filtering, so it also runs on a guest kernel without 802.1Q.
    """
    ports = node['switchports']
    if node['vlans'] == [1] and all(port == {'mode': 'access', 'vlan': 1} for port in ports.values()):
        return None
    plan = set()
    for name, port in ports.items():
        if port['mode'] == 'access':
            plan.add((name, port['vlan'], 'pvid'))
            continue
        allowed = node['vlans'] if port['allowed'] == 'all' else port['allowed']
        plan.add((name, port['native_vlan'], 'pvid'))
        plan.update((name, vid, 'tagged') for vid in allowed if vid != port['native_vlan'])
    return plan


def observed_vlans(socket, node):
    """The guest bridge's VLAN entries on the declared ports, in vlan_plan() form."""
    found = set()
    for line in query(socket, 'bridge-vlans').splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] not in node['interfaces']:
            continue  # br0's own entries and other devices are not ports.
        pvid, untagged = 'pvid' in fields[2:], 'untagged' in fields[2:]
        if pvid != untagged:
            raise ValueError('Unmanaged bridge VLAN entry: ' + line)
        found.add((fields[0], int(fields[1]), 'pvid' if pvid else 'tagged'))
    return found


def check_switch(socket, node):
    """A switch guest bridges exactly its declared ports, all up, holds no IPv4 and does not route."""
    ports = sorted(query(socket, 'bridge-ports').split())
    if ports != sorted(node['interfaces']):
        raise ValueError('Switch guest bridges ' + (', '.join(ports) or 'no port') + ' instead of its declared ports.')
    up = set(); interface = None
    for line in query(socket, 'addresses').splitlines():
        header = re.match(r'^\d+: ([^:@]+)[^:]*: <([^>]*)>', line)
        if header:
            interface = header[1]
            if interface not in ('lo', 'br0') and interface not in node['interfaces']:
                raise ValueError('Guest has an undeclared interface.')
            if 'UP' in header[2].split(','): up.add(interface)
        elif line.split()[:1] == ['inet'] and interface != 'lo':
            raise ValueError(f'Switch guest holds an IPv4 address on {interface}; switch ports stay unnumbered.')
    if not {'br0', *node['interfaces']} <= up:
        raise ValueError('Switch guest bridge and all declared ports must be up.')
    plan = vlan_plan(node)
    if plan is not None and observed_vlans(socket, node) != plan:
        raise ValueError('Switch guest VLAN membership differs from its declared switchports.')
    check_forwarding(socket, node)


def observe(socket, node):
    """Fail closed on unrepresentable state; never save shell output as commands."""
    text = query(socket, 'addresses')
    declared = guest_interfaces(node)
    by_port = {port: [] for port in declared}
    interface = None; active = set()
    for line in text.splitlines():
        header = re.match(r'^\d+: ([^:@]+)(?:@[^:]+)?: <([^>]*)>', line)  # a subinterface reads "eth0.10@eth0
        if header:
            interface = header[1]
            if interface != 'lo' and interface not in by_port:
                raise ValueError('Guest has an undeclared interface.')
            if 'UP' in header[2].split(','): active.add(interface)
        fields = line.split()
        if fields and fields[0] == 'inet' and interface in by_port:
            by_port[interface].append(str(ipaddress.IPv4Interface(fields[1])))
    dynamic = set(node.get('dhcp_clients', []))
    for port, primary_address in declared.items():
        if port in dynamic or not primary_address:
            if port not in active:
                raise ValueError('Save requires all declared guest interfaces up.')
            continue
        primary_address = str(ipaddress.IPv4Interface(primary_address))
        if port not in active or primary_address not in by_port[port]:
            raise ValueError('Save requires all declared guest interfaces up with primary IPv4 addresses.')
    # Leased addresses come from the DHCP server on every boot; they are never saved as static ones.
    def unexpected(port, values):
        primary = str(ipaddress.IPv4Interface(declared[port])) if declared[port] else None
        return [] if port in dynamic else [a for a in values if a != primary]
    extras = {port: unexpected(port, values) for port, values in by_port.items()}
    for name in node.get('subinterfaces', {}):
        if extras.pop(name):
            raise ValueError(f'Extra addresses on subinterface {name} cannot be saved; only its declared address is.')
    routes = []; devices = {}
    connected = {(port, str(ipaddress.IPv4Interface(a).network), str(ipaddress.IPv4Interface(a).ip)) for port, values in by_port.items() for a in values}
    default_seen = False
    for line in query(socket, 'routes').splitlines():
        fields = line.split()
        if not fields: continue
        if node.get('ospf') and learned(fields):
            continue  # OSPF's own routes come back from the neighbours on every boot; they are never saved.
        network = str(ipaddress.IPv4Network('0.0.0.0/0' if fields[0] == 'default' else fields[0]))
        if 'via' not in fields:
            if len(fields) != 7 or fields[1] != 'dev' or fields[3:6] != ['scope', 'link', 'src'] or (fields[2], network, fields[6]) not in connected:
                raise ValueError('Unmanaged guest route cannot be saved: ' + line)
            continue
        if len(fields) != 5 or fields[1] != 'via' or fields[3] != 'dev' or fields[4] not in by_port:
            raise ValueError('Unsupported guest static route: ' + line)
        gateway = str(ipaddress.IPv4Address(fields[2]))
        if network == '0.0.0.0/0' and fields[4] in dynamic:
            continue  # Installed by the DHCP client from the lease's router option.
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
    elif node.get('acl_ports'):
        from .acl import policy
        from .guest_firewall import check
        check(socket, {'firewall': policy(node)})
    if node.get('dhcp_server'):
        leases(socket, node['dhcp_server']['interface'])  # Fails closed if the declared server is not running.
    if node.get('ospf'):
        check_ospf(socket, node)
    return candidate['guest_network']


BIRD_METRIC = '32'  # BIRD 2's kernel protocol installs its routes with metric 32 (its default; config() keeps it)


def learned(fields):
    """A route BIRD installed. BusyBox's 'ip route' never prints the protocol, so BIRD's routes are told apart by
    their metric; static routes the agent adds and connected routes carry none. iproute2 also prints 'proto bird'."""
    pairs = {fields[i]: fields[i + 1] for i in range(len(fields) - 1)}
    return pairs.get('proto') in ('bird', '12') or pairs.get('metric') == BIRD_METRIC


def check_ospf(socket, node):
    """The guest's BIRD runs the configuration the lab declares, byte for byte."""
    from .ospf import config
    try:
        running = query(socket, 'ospf-show', state='config')
    except ValueError as error:
        raise ValueError(f'{node["name"]}: OSPF is not running in the guest ({error}).') from error
    if running != config(node):
        raise ValueError(f'{node["name"]}: the guest OSPF configuration differs from the lab.')


def start_ospf(socket, node, timeout=5):
    """Start BIRD from the typed process, then wait for its control socket to answer."""
    from .ospf import guest_process
    query(socket, 'ospf-start', ospf=guest_process(node))
    deadline = time.monotonic() + timeout
    while True:
        try:
            query(socket, 'ospf-show', state='neighbors')
            break
        except ValueError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.1)
    check_ospf(socket, node)


LIVE_ROUTING = ('gateway', 'guest_network', 'ospf', 'acls', 'acl_ports')


def _route(socket, node, operation, network, gateway):
    profile = node.get('guest_network') or {'addresses': [], 'routes': []}
    port = route_port(node, profile, gateway)
    # eth0 keeps the original request, as at boot.
    query(socket, operation, network=network, gateway=gateway, **({} if port == 'eth0' else {'interface': port}))


def change_routing(socket, old, new):
    """Bring a running guest from OLD's static routes, gateway and OSPF to NEW's: only what differs changes."""
    from .vendor_config import routes
    before, after = set(routes(old)), set(routes(new))
    ospf_changed = old.get('ospf') != new.get('ospf')
    if ospf_changed and old.get('ospf'):
        query(socket, 'ospf-stop')  # BIRD withdraws the routes it installed as it stops
    for network, gateway in sorted(before - after):
        _route(socket, old, 'route-delete', network, gateway)
    for network, gateway in sorted(after - before):
        _route(socket, new, 'route-add', network, gateway)
    if ospf_changed and new.get('ospf'):
        start_ospf(socket, new)
    if (old.get('acl_ports'), old.get('acls')) != (new.get('acl_ports'), new.get('acls')):
        from .acl import policy
        from .guest_firewall import apply as apply_firewall
        # No list left: an open chain (accept, no rule but the invalid-state drop every guest chain starts with).
        apply_firewall(socket, {'firewall': policy(new)})
    if observe(socket, new) != (new.get('guest_network') or {'addresses': [], 'routes': []}):
        raise ValueError('Guest routing readback differs from the declared routes.')


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
    if node.get('role') == 'switch':
        for port in node['interfaces']:
            query(socket, 'link', interface=port, state='up')
            query(socket, 'bridge-add', interface=port)
        plan = vlan_plan(node)
        if plan is not None:
            try:
                query(socket, 'bridge-vlan-filtering')
            except ValueError as error:
                raise ValueError(str(error) + ' (VLANs need the Network LABS guest kernel, tools/guest_kernel)') from error
            for port in node['interfaces']:
                query(socket, 'bridge-vlan-delete', interface=port, vlan=1)  # Ports join VLAN 1 untagged by default.
            # Untagged (pvid) entries last: each one replaces the port's default VLAN.
            for port, vid, mode in sorted(plan, key=lambda entry: (entry[2] == 'pvid', entry)):
                query(socket, 'bridge-vlan-add', interface=port, vlan=vid, state=mode)
        check_switch(socket, node)
        return
    for port, address in node['interfaces'].items():
        if port != 'eth0' and address:
            query(socket, 'address-add', interface=port, cidr=address)
        if port != 'eth0' or not address:
            query(socket, 'link', interface=port, state='up')
    for name, sub in node.get('subinterfaces', {}).items():
        # Router-on-a-stick: each 802.1Q subinterface rides its (already up) parent port.
        query(socket, 'vlan-add', interface=sub['parent'], vlan=sub['vlan'])
        query(socket, 'address-add', interface=name, cidr=sub['address'])
        query(socket, 'link', interface=name, state='up')
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
    if node.get('acl_ports'):
        # A router's access lists run in its forward chain, installed before forwarding starts.
        from .acl import policy
        from .guest_firewall import apply as apply_firewall
        apply_firewall(socket, {'firewall': policy(node)})
    if node.get('role') in ('router', 'firewall'):
        query(socket, 'forward', state='on')
    if node.get('dhcp_server'):
        port = node['dhcp_server']['interface']
        query(socket, 'dhcp-serve', interface=port, dhcp=dhcp_pool(node))
        # The daemon writes its pid file just after the request returns: wait for it before reading back.
        started = time.monotonic() + 5
        while True:
            try: leases(socket, port); break
            except ValueError:
                if time.monotonic() >= started: raise
                time.sleep(.1)
    if node.get('ospf'):
        start_ospf(socket, node)
    for port in node.get('dhcp_clients', []):
        # Started, not awaited: the server may be a guest that boots later in this lab.
        query(socket, 'dhcp-client', interface=port)
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
        if node['role'] == 'switch':  # Nothing to capture: the bridge is rebuilt from the declared ports.
            check_switch(manager.directory / node['name'] / 'guest.vsock', node); continue
        node['guest_network'] = observe(manager.directory / node['name'] / 'guest.vsock', node)
    candidate = validate(candidate)
    # Re-read before publishing: do not accept drift across the capture window.
    for node in candidate['nodes']:
        if node['role'] == 'switch':
            check_switch(manager.directory / node['name'] / 'guest.vsock', node); continue
        if observe(manager.directory / node['name'] / 'guest.vsock', node) != node['guest_network']:
            raise ValueError('Guest changed during save; no startup configuration written.')
    save_startup(manager.name, candidate)
    return {'saved': str(startup_path(manager.name)), 'scope': 'Observed extra IPv4 addresses and on-link static routes on every declared port, plus declared primary addresses; interfaces up. No disk snapshot or IPv6 persistence.'}
